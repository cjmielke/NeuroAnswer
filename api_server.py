import os
import json
from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from mcp import ClientSession
from mcp.client.sse import sse_client
from rich.console import Console
from rich.syntax import Syntax

console = Console(force_terminal=True, color_system="truecolor")

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


# Tools whose results are consumed by Claude but not surfaced in the chat UI
SILENT_TOOLS = {"get_neuroglancer_screenshot", "get_neuroglancer_viewer_state"}

class ExtensionRequest(BaseModel):
    prompt: str


@app.post("/chat")
async def handle_chat(request: ExtensionRequest):
    """The main endpoint the Chrome Extension hits."""

    async def generate():
        history_checkpoint = len(conversation_history)
        try:
            trace = langfuse_client.start_observation(
                name="chat",
                input={"prompt": request.prompt}
            ) if langfuse_client else None

            async with sse_client(MCP_SERVER_URL) as streams:
                async with ClientSession(streams[0], streams[1]) as mcp:
                    await mcp.initialize()

                    tools_response = await mcp.list_tools()
                    anthropic_tools = [
                        {
                            "name": tool.name,
                            "description": tool.description,
                            "input_schema": tool.inputSchema
                        }
                        for tool in tools_response.tools
                    ]

                    conversation_history.append({"role": "user", "content": request.prompt})

                    turn = 0

                    while True:
                        generation = trace.start_observation(
                            name=f"claude-turn-{turn}",
                            as_type="generation",
                            model=CLAUDE_MODEL,
                            input=conversation_history,
                        ) if trace else None

                        claude_response = await anthropic_client.messages.create(
                            model=CLAUDE_MODEL,
                            max_tokens=2000,
                            messages=conversation_history,
                            tools=anthropic_tools
                        )

                        if generation:
                            generation.update(
                                output=[b.text if b.type == "text" else b.model_dump() for b in claude_response.content],
                                usage_details={"input": claude_response.usage.input_tokens,
                                               "output": claude_response.usage.output_tokens},
                            )
                            generation.end()

                        conversation_history.append({"role": "assistant", "content": claude_response.content})
                        turn += 1

                        if claude_response.stop_reason == "tool_use":
                            tool_results = []
                            for content_block in claude_response.content:
                                if content_block.type == "tool_use":

                                    console.print(f"\n[bold blue]🤖 Claude is calling tool:[/bold blue] {content_block.name}")

                                    if content_block.name == "execute_analysis":
                                        code_str = content_block.input.get("code", "")
                                        code_str = code_str.replace("\\n", "\n").replace("\\'", "'")
                                        syntax = Syntax(code_str, "python", theme="monokai", line_numbers=True, word_wrap=True)
                                        console.print(syntax)
                                        yield (json.dumps({
                                            "type": "code",
                                            "language": "python",
                                            "content": code_str,
                                        }) + "\n").encode('utf-8')
                                    else:
                                        console.print(f"[cyan]📥 Inputs:[/cyan] {content_block.input}")

                                    friendly_name = content_block.name.replace("_", " ").title()
                                    yield (json.dumps({
                                        "type": "status",
                                        "message": f"⚙️ {friendly_name}..."
                                    }) + "\n").encode('utf-8')

                                    tool_span = trace.start_observation(
                                        name=content_block.name,
                                        as_type="span",
                                        input=content_block.input,
                                    ) if trace else None

                                    result = await mcp.call_tool(content_block.name, content_block.input)

                                    image_items = []
                                    raw_text_parts = []
                                    for item in result.content:
                                        if item.type == "text":
                                            raw_text_parts.append(item.text)
                                        elif item.type == "image":
                                            image_items.append(item)

                                    raw_text = "\n\n".join(raw_text_parts)

                                    if tool_span:
                                        tool_span.update(output=raw_text[:2000])
                                        tool_span.end()

                                    short_result = raw_text[:300] + "..." if len(raw_text) > 300 else raw_text
                                    console.print(f"[green]📤 Result:[/green] {short_result}\n")

                                    try:
                                        tool_data = json.loads(raw_text)
                                        if isinstance(tool_data, dict):
                                            clean_result = tool_data.get("summary", raw_text)
                                            if len(tool_data) > 1:
                                                yield (json.dumps({"type": "detail", "tool": content_block.name, "content": tool_data}) + "\n").encode('utf-8')
                                        else:
                                            clean_result = raw_text
                                        display_text = str(clean_result) if not isinstance(clean_result, str) else clean_result
                                    except Exception:
                                        clean_result = raw_text
                                        display_text = raw_text

                                    if content_block.name not in SILENT_TOOLS:
                                        if display_text:
                                            yield (json.dumps({"type": "text", "content": display_text}) + "\n").encode('utf-8')
                                        for item in image_items:
                                            yield (json.dumps({"type": "image", "content": f"data:{item.mimeType};base64,{item.data}"}) + "\n").encode('utf-8')

                                    # Build tool_result content for Claude — include images so Claude can see screenshots
                                    claude_content = []
                                    if clean_result:
                                        claude_content.append({"type": "text", "text": str(clean_result) if not isinstance(clean_result, str) else clean_result})
                                    for item in image_items:
                                        claude_content.append({"type": "image", "source": {"type": "base64", "media_type": item.mimeType, "data": item.data}})

                                    tool_results.append({
                                        "type": "tool_result",
                                        "tool_use_id": content_block.id,
                                        "content": claude_content if claude_content else "",
                                    })

                            conversation_history.append({"role": "user", "content": tool_results})
                        else:
                            final_text = next(
                                (block.text for block in claude_response.content if block.type == "text"),
                                "Done."
                            )
                            if trace:
                                trace.update(output={"reply": final_text})
                                trace.end()
                            if langfuse_client:
                                langfuse_client.flush()

                            yield (json.dumps({
                                "type": "final",
                                "blocks": [{"type": "text", "content": final_text}],
                            }) + "\n").encode('utf-8')
                            return

        except Exception as e:
            import traceback
            del conversation_history[history_checkpoint:]  # roll back any partial turn
            console.print(f"[bold red]❌ generate() error:[/bold red] {e}", highlight=False)
            traceback.print_exc()
            yield (json.dumps({
                "type": "final",
                "blocks": [{"type": "text", "content": f"⚠️ Server error: {e}"}],
            }) + "\n").encode('utf-8')

    return StreamingResponse(generate(), media_type="text/plain")


@app.post("/reset")
async def reset_conversation():
    conversation_history.clear()
    return {"status": "conversation cleared"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("api_server:app", host="0.0.0.0", port=8080, reload=True)