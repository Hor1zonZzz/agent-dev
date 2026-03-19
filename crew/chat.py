"""Chat agent definition for the FastAPI service."""

from __future__ import annotations

import os

from agents import Agent, Tool
from agents.mcp import MCPServer
from dotenv import load_dotenv

from tools import response_to_user, end_of_turn

load_dotenv()

MODEL = os.getenv("OPENAI_MODEL", "gpt-4.1-mini")


def build_chat_agent(
    mcp_servers: list[MCPServer] | None = None,
    extra_tools: list[Tool] | None = None,
) -> Agent:
    tools: list[Tool] = [response_to_user, end_of_turn] + list(extra_tools or [])
    return Agent(
        name="assistant",
        instructions=(
            "You are a concise, helpful assistant.\n"
            "IMPORTANT: Never output text directly. Always use response_to_user to send messages.\n"
            "Use recall_memory to look up user preferences and facts when relevant.\n"
            "When you are done responding, call end_of_turn."
        ),
        model=MODEL,
        tools=tools,
        tool_use_behavior={"stop_at_tool_names": ["end_of_turn"]},
        mcp_servers=list(mcp_servers or []),
    )
