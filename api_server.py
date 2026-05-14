import os
import json
import time
from dotenv import load_dotenv
load_dotenv()

import caveclient
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from nglui import statebuilder
from pydantic import BaseModel
from typing import Optional, List
from mcp import ClientSession
from mcp.client.sse import sse_client
from rich.console import Console
console = Console()

from anthropic import Anthropic, AsyncAnthropic

# --- LANGFUSE (optional) ---
_lf_pub = os.environ.get("LANGFUSE_PUBLIC_KEY")
_lf_sec = os.environ.get("LANGFUSE_SECRET_KEY")

if _lf_pub and _lf_sec:
    from langfuse import get_client
    langfuse_client = get_client()
    print("✅ Langfuse tracing enabled")
else:
    langfuse_client = None


def get_latest_model(family_prefix: str = "claude-sonnet") -> str:
    client = Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))
    models_list = client.models.list()
    print(f'Models available : {" | ".join([model.id for model in models_list.data])}')
    for model in models_list.data:
        if family_prefix in model.id:
            print(f"✅ Auto-selected model: {model.id}")
            return model.id
    raise ValueError(f"No models found matching: '{family_prefix}'")


CLAUDE_MODEL = get_latest_model()
print(f'Using {CLAUDE_MODEL}')

app = FastAPI()
anthropic_client = AsyncAnthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))
conversation_history: list = []
MCP_SERVER_URL = os.environ.get("MCP_SERVER_URL", "http://127.0.0.1:8000/sse")


app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


KNOWN_DATASETS = {
    "minnie65": {
        "label": "MICrONs Minnie65",
        "description": "Mouse visual cortex, ~1mm³ cortical column",
        "cave_dataset": "minnie65_public",
    }
}


def _source_to_url(source) -> str:
    """Normalise a Neuroglancer source field (string, dict, or list) to a URL string."""
    if isinstance(source, str):
        return source
    if isinstance(source, dict):
        return source.get("url", "")
    if isinstance(source, list) and source:
        return _source_to_url(source[0])
    return ""


def identify_dataset(ng_state: dict) -> Optional[str]:
    """Return the dataset label if a known dataset is found in the layer sources."""
    for layer in ng_state.get("layers", []):
        url = _source_to_url(layer.get("source", ""))
        for key, ds in KNOWN_DATASETS.items():
            if key in url:
                return ds["label"]
    return None


class ExtensionRequest(BaseModel):
    prompt: str
    ng_state: Optional[dict] = None


@app.post("/chat")
async def handle_chat(request: ExtensionRequest):
    """The main endpoint the Chrome Extension hits."""

    trace = langfuse_client.start_observation(
        name="chat",
        input={"prompt": request.prompt}
    ) if langfuse_client else None

    contextual_prompt = request.prompt
    if request.ng_state:
        state = request.ng_state
        dataset = identify_dataset(state)

        if dataset is None:
            return {
                "reply": "I only support the MICrONs Minnie65 dataset right now. "
                         "Please open a Minnie65 Neuroglancer session and try again.",
                "layers": [],
                "suggested_position": None,
            }

        position = state.get("position") or (
            state.get("navigation", {}).get("pose", {}).get("position", {}).get("voxelCoordinates")
        )
        context_parts = [f"Dataset: {dataset}"]
        if position:
            context_parts.append(f"Current viewer position (nm): {position}")
        contextual_prompt += "\n\n[SYSTEM CONTEXT: " + " | ".join(context_parts) + "]"
        print(contextual_prompt)

    async with sse_client(MCP_SERVER_URL) as streams:
        async with ClientSession(streams[0], streams[1]) as mcp:
            await mcp.initialize()

            response = await mcp.list_tools()
            anthropic_tools = [
                {
                    "name": tool.name,
                    "description": tool.description,
                    "input_schema": tool.inputSchema
                }
                for tool in response.tools
            ]

            conversation_history.append({"role": "user", "content": contextual_prompt})

            # Accumulate layers by name across tool calls (last write wins per name)
            scene_layers: dict = {}
            suggested_position = None
            blocks: list = []  # ordered {type, content} blocks for the frontend
            turn = 0

            while True:
                generation = trace.start_observation(
                    name=f"claude-turn-{turn}",
                    as_type="generation",
                    model=CLAUDE_MODEL,
                    input=conversation_history,
                ) if trace else None

                response = await anthropic_client.messages.create(
                    model=CLAUDE_MODEL,
                    max_tokens=2000,
                    messages=conversation_history,
                    tools=anthropic_tools
                )

                # Update generation completion:
                if generation:
                    generation.update(
                        output=[b.text if b.type == "text" else b.model_dump() for b in response.content],
                        usage_details={"input": response.usage.input_tokens, "output": response.usage.output_tokens},
                    )
                    generation.end()

                conversation_history.append({"role": "assistant", "content": response.content})
                turn += 1

                if response.stop_reason == "tool_use":
                    for content_block in response.content:
                        if content_block.type == "tool_use":
                            console.print(f"\n[bold blue]🤖 Claude is calling tool:[/bold blue] {content_block.name}")
                            console.print(f"[cyan]📥 Inputs:[/cyan] {content_block.input}")

                            tool_span = trace.start_observation(
                                name=content_block.name,
                                as_type="span",
                                input=content_block.input,
                            ) if trace else None

                            result = await mcp.call_tool(content_block.name, content_block.input)

                            # Split content blocks by type into typed frontend blocks
                            tool_blocks = []
                            for item in result.content:
                                if item.type == "text":
                                    tool_blocks.append({"type": "text", "content": item.text})
                                elif item.type == "image":
                                    tool_blocks.append({"type": "image", "content": f"data:{item.mimeType};base64,{item.data}"})
                            blocks.extend(tool_blocks)

                            # Text-only view: fed back to Claude and used for JSON parsing
                            raw_text = "\n\n".join(b["content"] for b in tool_blocks if b["type"] == "text")

                            # Update tool span completion:
                            if tool_span:
                                tool_span.update(output=raw_text[:2000])
                                tool_span.end()

                            short_result = raw_text[:300] + "..." if len(raw_text) > 300 else raw_text
                            console.print(f"[green]📤 Result:[/green] {short_result}\n")

                            try:
                                tool_data = json.loads(raw_text)
                                for layer in tool_data.get("layers", []):
                                    name = layer.get("name", f"layer_{len(scene_layers)}")
                                    scene_layers[name] = layer
                                if tool_data.get("suggested_position") is not None:
                                    suggested_position = tool_data["suggested_position"]
                                clean_result = tool_data.get("summary", raw_text)
                            except json.JSONDecodeError:
                                clean_result = raw_text

                            conversation_history.append({
                                "role": "user",
                                "content": [
                                    {
                                        "type": "tool_result",
                                        "tool_use_id": content_block.id,
                                        "content": clean_result
                                    }
                                ]
                            })
                else:
                    final_text = next(
                        (block.text for block in response.content if block.type == "text"),
                        "Done."
                    )
                    if trace:
                        trace.update(output={"reply": final_text})
                        trace.end()
                    if langfuse_client:
                        langfuse_client.flush()

                    blocks.append({"type": "text", "content": final_text})
                    return {
                        "blocks": blocks,
                        "layers": list(scene_layers.values()),
                        "suggested_position": suggested_position,
                    }


@app.post("/reset")
async def reset_conversation():
    conversation_history.clear()
    return {"status": "conversation cleared"}


@app.get("/scenes")
async def list_scenes():
    return {
        "scenes": [
            {"id": key, "label": ds["label"], "description": ds["description"]}
            for key, ds in KNOWN_DATASETS.items()
        ]
    }

'''
{
  "dimensions": {"x": [1e-9,"m"],"y": [1e-9,"m"],"z": [1e-9,"m"]},
  "position": [ 962560, 831488, 854400],
  "crossSectionScale": 1,
  "projectionOrientation": [0.4607859253883362, -0.5477277040481567, -0.2193523645401001, 0.662989616394043],
  "projectionScale": 50000,
  "layers": [
    {
      "type": "image",
      "source": "precomputed://https://bossdb-open-data.s3.amazonaws.com/iarpa_microns/minnie/minnie65/em",
      "tab": "source",
      "name": "EM_Background"
    },
    {
      "type": "segmentation",
      "source": "graphene://middleauth+https://minnie.microns-daf.com/segmentation/table/minnie65_public",
      "tab": "source",
      "selectedAlpha": 0.2,
      "objectAlpha": 0.9,
      "segments": [],
      "name": "3D_Meshes"
    }
  ],
  "showSlices": false,
  "layout": "xy-3d"
}
'''



@app.get("/new_scene/{dataset_id}")
async def get_new_scene(dataset_id: str):
    if dataset_id not in KNOWN_DATASETS:
        return {"error": f"Unknown dataset: {dataset_id}"}
    ds = KNOWN_DATASETS[dataset_id]
    start = time.time()
    client = caveclient.CAVEclient(ds["cave_dataset"], auth_token=os.environ['CAVE_TOKEN'])
    print(f'took {time.time()-start} seconds to init caveclient')
    start = time.time()
    em_source = client.info.image_source()
    print(f'took {time.time() - start} seconds to get image_source')
    start = time.time()
    seg_source = client.info.segmentation_source()
    print(f'took {time.time() - start} seconds to get segmentation_source')
    start = time.time()
    viewer = (
        statebuilder.ViewerState(dimensions=[1, 1, 1], position=[962560, 831488, 854400], infer_coordinates=False)
        .add_image_layer(name='EM_Background', source=em_source)
        .add_segmentation_layer(name='3D_Meshes', source=seg_source, segments=[])
    )
    print(f'took {time.time() - start} seconds to make viewer')
    start = time.time()
    scene_url = viewer.to_url(target_url='https://neuroglancer-demo.appspot.com/')
    print(f'took {time.time() - start} seconds to make scene_url')
    return {"scene_url": scene_url, "label": ds["label"]}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("api_server:app", host="0.0.0.0", port=8080, reload=True)
