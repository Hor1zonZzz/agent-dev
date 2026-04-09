"""Interactive REPL for testing the core agent loop."""

import asyncio
import json
import os
from pathlib import Path

from dotenv import load_dotenv

from core.loop import Agent, run
from prompts import build
from tools import end_turn, send_message

load_dotenv()

HISTORY_PATH = Path(__file__).parent / "history" / "cli.json"

agent = Agent(
    name="anna",
    instructions=lambda _ctx: build(),
    model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
    tools=[send_message, end_turn],
    stop_at={"end_turn"},
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


def load_history() -> list[dict]:
    if HISTORY_PATH.exists():
        data = json.loads(HISTORY_PATH.read_text(encoding="utf-8"))
        print(f"Loaded {len(data)} messages from history.\n")
        return data
    return []


def save_history(messages: list[dict]) -> None:
    HISTORY_PATH.parent.mkdir(parents=True, exist_ok=True)
    HISTORY_PATH.write_text(json.dumps(messages, ensure_ascii=False, indent=2), encoding="utf-8")


async def main():
    messages = load_history()
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
        save_history(messages)

        if result.last_tool is None and result.final_output:
            print(f"Anna: {result.final_output}\n")
        else:
            print()


if __name__ == "__main__":
    asyncio.run(main())
