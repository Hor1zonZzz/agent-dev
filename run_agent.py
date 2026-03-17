"""Chat agent with sliding-window memory management."""

import asyncio
import os

import tracing  # noqa: F401 — side-effect: registers Phoenix OTEL tracer

from agents import Agent, Runner, SQLiteSession
from dotenv import load_dotenv

import mem_tools

load_dotenv()

MODEL = os.getenv("OPENAI_MODEL", "gpt-4.1-mini")


# --- Conversation agent ---


async def chat_instructions(_, __) -> str:
    base = "You are a concise, helpful assistant."
    memories = await mem_tools.get_memories("user preferences and facts")
    if not memories:
        return base
    memory_block = "\n".join(f"- {m.abstract}" for m in memories)
    return f"{base}\n\nYou remember these facts about the user:\n{memory_block}"


chat_agent = Agent(
    name="assistant",
    instructions=chat_instructions,
    model=MODEL,
)


async def main() -> None:
    await mem_tools.init()
    session = SQLiteSession(session_id="default", db_path="chat.db")
    print(f"Model: {MODEL} | Session: chat.db")

    try:
        while True:
            try:
                user_input = input("You: ").strip()
            except (EOFError, KeyboardInterrupt):
                print("\nBye.")
                break
            if not user_input:
                continue
            if user_input == "/exit":
                break

            result = await Runner.run(chat_agent, user_input, session=session)
            reply = str(result.final_output)
            print(f"Agent: {reply}")

            await mem_tools.on_turn(user_input, reply)
    finally:
        session.close()
        await mem_tools.close()


if __name__ == "__main__":
    asyncio.run(main())
