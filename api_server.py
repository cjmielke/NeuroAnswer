import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional, List
from mcp import ClientSession
from mcp.client.sse import sse_client


from anthropic import Anthropic, AsyncAnthropic

def get_latest_model(family_prefix: str = "claude-sonnet") -> str:
    # 1. Use the sync client just for the startup script
    client = Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))
    # 2. Iterate directly over the paginator (No .data required!)
    models_list = client.models.list()
    print(f'Models available : {" | ".join([model.id for model in models_list.data])}')
    for model in models_list.data:
        if family_prefix in model.id:
            print(f"✅ Auto-selected model: {model.id}")
            return model.id

    raise ValueError(f"No models found matching: '{family_prefix}'")


CLAUDE_MODEL = get_latest_model()
print(f'Using {CLAUDE_MODEL}')

# 1. Setup the API and clients
app = FastAPI()
anthropic_client = AsyncAnthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))
MCP_SERVER_URL = "http://127.0.0.1:8000/sse"


# 2. CORS is CRITICAL for Chrome Extensions
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In production, restrict to chrome-extension://[your-id]
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# 3. Define the payload expected from the Chrome Extension
class ExtensionRequest(BaseModel):
    prompt: str
    bbox: Optional[List[float]] = None  # Expecting [xmin, ymin, zmin, xmax, ymax, zmax]


@app.post("/chat")
async def handle_chat(request: ExtensionRequest):
    """The main endpoint the Chrome Extension hits."""

    # 4. Inject the bounding box into the prompt if the extension found one
    contextual_prompt = request.prompt
    if request.bbox:
        contextual_prompt += f"\n\n[SYSTEM CONTEXT: The user is currently viewing this 3D bounding box in Neuroglancer: {request.bbox}]"
        print(contextual_prompt)

    # 5. Connect to your FastMCP server
    #try:
    async with sse_client(MCP_SERVER_URL) as streams:
        async with ClientSession(streams[0], streams[1]) as mcp:
            await mcp.initialize()

            # Fetch your tools (search_excitatory_population, etc.)
            response = await mcp.list_tools()

            # Format tools for Anthropic API
            anthropic_tools = [
                {
                    "name": tool.name,
                    "description": tool.description,
                    "input_schema": tool.inputSchema
                }
                for tool in response.tools
            ]

            # 6. The Agent Loop
            messages = [{"role": "user", "content": contextual_prompt}]

            while True:
                # Ask Claude what to do
                response = await anthropic_client.messages.create(
                    model=CLAUDE_MODEL,
                    max_tokens=2000,
                    messages=messages,
                    tools=anthropic_tools
                )

                # Append Claude's response to the history
                messages.append({"role": "assistant", "content": response.content})

                # If Claude wants to use a tool, execute it and loop back
                if response.stop_reason == "tool_use":
                    for content_block in response.content:
                        if content_block.type == "tool_use":
                            print(f"Executing tool: {content_block.name} with inputs: {content_block.input}")

                            # Call your FastMCP tool
                            result = await mcp.call_tool(content_block.name, content_block.input)

                            # Pass the result back to Claude
                            messages.append({
                                "role": "user",
                                "content": [
                                    {
                                        "type": "tool_result",
                                        "tool_use_id": content_block.id,
                                        "content": result.content[0].text
                                    }
                                ]
                            })
                else:
                    # If Claude is done, extract the final text and return it to the extension
                    final_text = next(
                        (block.text for block in response.content if block.type == "text"),
                        "Done."
                    )
                    return {"reply": final_text}

    #except Exception as e:
    #    #return {"reply": f"Error connecting to MCP server or Anthropic API: {str(e)}"}
    #    raise

if __name__ == "__main__":
    import uvicorn

    # Run the orchestrator on port 8080 (since your FastMCP is on 8000)
    uvicorn.run("api_server:app", host="127.0.0.1", port=8080, reload=True)
