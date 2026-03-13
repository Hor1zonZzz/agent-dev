import asyncio
import os
from typing import Any

from dotenv import load_dotenv

load_dotenv()

from claude_agent_sdk import (
    ClaudeSDKClient,
    ClaudeAgentOptions,
    AssistantMessage,
    ResultMessage,
    TextBlock,
    tool,
    create_sdk_mcp_server,
)

from run import Registry, run_tool_description
from commands import register_memory_commands

# ---------------------------------------------------------------------------
# Build registry
# ---------------------------------------------------------------------------
registry = Registry()
register_memory_commands(registry)

# ---------------------------------------------------------------------------
# Single `run` tool exposed to the LLM
# ---------------------------------------------------------------------------
run_description = run_tool_description(registry.help)


@tool(
    "run",
    run_description,
    {
        "type": "object",
        "properties": {
            "command": {
                "type": "string",
                "description": "Unix-style command to execute",
            },
            "stdin": {
                "type": "string",
                "description": "Standard input for the command",
            },
        },
        "required": ["command"],
    },
)
async def run_tool(args: dict[str, Any]) -> dict[str, Any]:
    command = args["command"]
    stdin = args.get("stdin", "")
    output = registry.exec(command, stdin)
    return {"content": [{"type": "text", "text": output}]}


agent_server = create_sdk_mcp_server(
    name="agent",
    version="0.1.0",
    tools=[run_tool],
)

SYSTEM_PROMPT = """\
You are memAgent — a memory management relay agent.

Your role is to manage contextual memories on behalf of external models and users.
You have a single tool: run(command="..."). All operations go through it.
Commands can be chained: cmd1 | cmd2, cmd1 && cmd2, cmd1 ; cmd2

Guidelines:
- Use descriptive, namespaced keys (e.g. "project/auth-flow", "user/preferences").
- Use --tag to categorise memories for easier retrieval.
- Summarise what you stored or retrieved so the caller can verify.
"""


async def main() -> None:
    options = ClaudeAgentOptions(
        system_prompt=SYSTEM_PROMPT,
        model=os.environ.get("MODEL", "deepseek-chat"),
        mcp_servers={"agent": agent_server},
        allowed_tools=["mcp__agent__run"],
        env={
            "ANTHROPIC_BASE_URL": os.environ.get("ANTHROPIC_BASE_URL", ""),
            "ANTHROPIC_AUTH_TOKEN": os.environ.get("ANTHROPIC_AUTH_TOKEN", ""),
        },
    )

    async with ClaudeSDKClient(options=options) as client:
        print("memAgent ready. Type your message (Ctrl+C to quit).\n")

        while True:
            try:
                loop = asyncio.get_event_loop()
                user_input = (await loop.run_in_executor(None, input, "You: ")).strip()
            except (EOFError, KeyboardInterrupt):
                print("\nBye.")
                break
            if not user_input:
                continue

            await client.query(user_input)

            async for message in client.receive_response():
                if isinstance(message, AssistantMessage):
                    for block in message.content:
                        if isinstance(block, TextBlock):
                            print(f"memAgent: {block.text}")
                elif isinstance(message, ResultMessage):
                    pass


if __name__ == "__main__":
    asyncio.run(main())
