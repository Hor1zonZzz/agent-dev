"""Interactive REPL for testing the core agent loop."""

import asyncio
import json
import os
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

from core.context import AgentContext
from core.loop import Agent, run
from core.memory import (
    append_to_history,
    get_last_activity,
    load_for_llm,
    maybe_compress,
    update_last_activity,
)
from core.time_hint import format_gap_hint
from prompts import build
from core.tools import end_turn, recall_day, send_message

load_dotenv()

HISTORY_PATH = Path(__file__).parent / "history" / "cli.json"

agent = Agent(
    name="anna",
    instructions=lambda ctx: build(memory=ctx.memory if ctx else None),
    model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
    tools=[send_message, recall_day, end_turn],
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



async def _print_reply(text: str) -> None:
    print(f"Anna: {text}")


async def main():
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

        # Load recent window + memory summary from disk
        recent, memory_text = load_for_llm(HISTORY_PATH)

        # Compute gap hint vs. last activity (silence since last exchange)
        last_activity = get_last_activity(HISTORY_PATH)
        gap_hint = format_gap_hint(datetime.now() - last_activity) if last_activity else None
        decorated = f"{gap_hint}\n{user_input}" if gap_hint else user_input

        recent.append({"role": "user", "content": decorated})
        n_from_disk = len(recent) - 1

        ctx = AgentContext(send_reply=_print_reply, memory=memory_text)
        result = await run(agent, recent, ctx=ctx, hooks=hooks)

        # Append only this turn's new messages to the archive, but restore the
        # clean user content — gap hints are ephemeral per-run, not history.
        new_this_turn = result.messages[1 + n_from_disk:]
        if gap_hint and new_this_turn and new_this_turn[0].get("role") == "user":
            new_this_turn[0] = {**new_this_turn[0], "content": user_input}
        append_to_history(HISTORY_PATH, new_this_turn)
        update_last_activity(HISTORY_PATH)

        if result.last_tool is None and result.final_output:
            print(f"Anna: {result.final_output}\n")
        else:
            print()

        # Non-blocking background compression check
        await maybe_compress(HISTORY_PATH)


if __name__ == "__main__":
    asyncio.run(main())
