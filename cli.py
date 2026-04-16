"""Interactive REPL for testing the core agent loop."""

import asyncio
import os
from pathlib import Path

from dotenv import load_dotenv

from core.loop import Agent
from core.session import ChatSessionRequest, ChatSessionRunner
from core.tools import end_turn, recall_day, send_message
from core.trace import FanoutTraceSink, TraceEvent, TraceSink, get_default_trace_sink
from prompts import build

load_dotenv()

HISTORY_PATH = Path(__file__).parent / "history" / "cli.json"

agent = Agent(
    name="anna",
    instructions=lambda ctx: build(memory=ctx.memory if ctx else None),
    model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
    tools=[send_message, recall_day, end_turn],
    stop_at={"end_turn"},
)


class ConsoleTraceSink:
    def emit(self, event: TraceEvent) -> None:
        if event.type == "tool.started":
            print(f"  [tool] {event.payload.get('tool_name')}({event.payload.get('arguments')})")
        elif event.type == "tool.finished":
            if event.status == "ok":
                print(f"  [tool] → {event.payload.get('result_preview')}")
            else:
                print(f"  [tool] ! {event.payload.get('error_message')}")


async def _print_reply(text: str) -> None:
    print(f"Anna: {text}")


def _build_trace_sink() -> TraceSink:
    return FanoutTraceSink([get_default_trace_sink(), ConsoleTraceSink()])


async def main():
    runner = ChatSessionRunner(agent, trace_sink=_build_trace_sink())
    print("Interactive agent loop (Ctrl+C to quit)\n")

    while True:
        try:
            user_input = input("You: ")
        except (KeyboardInterrupt, EOFError):
            print("\nBye.")
            break

        if not user_input.strip():
            continue

        result = await runner.process(
            ChatSessionRequest(
                history_path=HISTORY_PATH,
                incoming_messages=[user_input],
                send_reply=_print_reply,
                source="cli",
                run_kind="cli_chat",
                session_id="cli",
                context={"transport": "cli"},
            )
        )

        if result.last_tool is None and result.final_output:
            print(f"Anna: {result.final_output}\n")
        else:
            print()


if __name__ == "__main__":
    asyncio.run(main())
