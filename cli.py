"""Interactive REPL for testing the core agent loop."""

import asyncio
import json
import os

from dotenv import load_dotenv

from core.loop import Agent, run
from core.hooks import Hooks
from prompts import build
from tools import send_message, edit_prompt

load_dotenv()

agent = Agent(
    name="anna",
    instructions=lambda _ctx: build(),
    model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
    tools=[send_message, edit_prompt],
    stop_at={"send_message"},
)


class CLIHooks:
    async def on_agent_start(self, agent_name, ctx):
        pass

    async def on_agent_end(self, agent_name, output, ctx):
        pass

    async def on_tool_start(self, agent_name, tool, args, ctx):
        parsed = json.loads(args)
        print(f"  [tool] {tool.name}({parsed})")

    async def on_tool_end(self, agent_name, tool, result, ctx):
        print(f"  [tool] → {result}")


async def main():
    messages: list[dict] = []
    hooks = CLIHooks()
    print("Interactive agent loop (Ctrl+C to quit)\n")

    while True:
        try:
            user_input = input("You: ")
        except (KeyboardInterrupt, EOFError):
            print("\nBye.")
            break

        if not user_input.strip():
            continue

        messages.append({"role": "user", "content": user_input})
        result = await run(agent, messages, hooks=hooks)
        messages = result.messages[1:]  # strip system message for next round

        # Only print text output if the model replied without tools
        if result.last_tool is None and result.final_output:
            print(f"Anna: {result.final_output}\n")
        else:
            print()


if __name__ == "__main__":
    asyncio.run(main())
