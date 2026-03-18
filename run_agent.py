"""Chat agent with sliding-window memory management."""

import asyncio
import os

import tracing  # noqa: F401 — side-effect: registers Phoenix OTEL tracer

from agents import Agent, Runner, SQLiteSession
from agents.mcp import MCPServer, MCPServerManager
from dotenv import load_dotenv

import mem_tools
from mcp_servers import build_servers

load_dotenv()

MODEL = os.getenv("OPENAI_MODEL", "gpt-4.1-mini")


# --- Conversation agent ---


async def chat_instructions(_, __) -> str:
    base = (
        "You are a concise, helpful assistant. "
    )
    memories = await mem_tools.get_memories("user preferences and facts")
    if not memories:
        return base
    memory_block = "\n".join(f"- {m.abstract}" for m in memories)
    return f"{base}\n\nYou remember these facts about the user:\n{memory_block}"


def build_chat_agent(mcp_servers: list[MCPServer] | None = None) -> Agent:
    return Agent(
        name="assistant",
        instructions=chat_instructions,
        model=MODEL,
        mcp_servers=list(mcp_servers or []),
    )


async def main() -> None:
    session_id = await mem_tools.init()
    session = SQLiteSession(session_id=session_id, db_path="chat.db")
    mcp_servers = build_servers()

    try:
        async with MCPServerManager(mcp_servers, strict=False) as manager:
            chat_agent = build_chat_agent(manager.active_servers)
            print(
                " | ".join(
                    [
                        f"Model: {MODEL}",
                        "Session DB: chat.db",
                        f"Session ID: {session_id}",
                        f"DeepWiki MCP: {'connected' if manager.active_servers else 'unavailable'}",
                    ]
                )
            )

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
