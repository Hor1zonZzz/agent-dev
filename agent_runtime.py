"""Shared agent construction for the FastAPI service."""

from __future__ import annotations

import os

from agents import Agent
from agents.mcp import MCPServer
from dotenv import load_dotenv

import mem_tools

load_dotenv()

MODEL = os.getenv("OPENAI_MODEL", "gpt-4.1-mini")


async def chat_instructions(_, __) -> str:
    base = "You are a concise, helpful assistant. "
    memories = await mem_tools.get_memories("user preferences and facts")
    if not memories:
        return base

    memory_block = "\n".join(f"- {memory.abstract}" for memory in memories)
    return f"{base}\n\nYou remember these facts about the user:\n{memory_block}"


def build_chat_agent(mcp_servers: list[MCPServer] | None = None) -> Agent:
    return Agent(
        name="assistant",
        instructions=chat_instructions,
        model=MODEL,
        mcp_servers=list(mcp_servers or []),
    )
