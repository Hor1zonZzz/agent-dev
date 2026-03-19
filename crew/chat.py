"""Chat agent definition for the FastAPI service."""

from __future__ import annotations

import os

from agents import Agent, Tool
from agents.mcp import MCPServer
from dotenv import load_dotenv

load_dotenv()

MODEL = os.getenv("OPENAI_MODEL", "gpt-4.1-mini")


def build_chat_agent(
    mcp_servers: list[MCPServer] | None = None,
    extra_tools: list[Tool] | None = None,
) -> Agent:
    tools: list[Tool] = list(extra_tools or [])
    return Agent(
        name="assistant",
        instructions=(
            "You are a concise, helpful assistant. "
            "Use the recall_memory tool to look up user preferences and facts when relevant."
        ),
        model=MODEL,
        tools=tools,
        mcp_servers=list(mcp_servers or []),
    )
