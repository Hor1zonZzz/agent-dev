"""Chat agent definition for the FastAPI service."""

from __future__ import annotations

import os

from agents import Agent, Tool
from agents.mcp import MCPServer
from dotenv import load_dotenv

from tools import send_message, defer_reply, end_of_turn

load_dotenv()

MODEL = os.getenv("OPENAI_MODEL", "gpt-5.4-mini")


def build_chat_agent(
    mcp_servers: list[MCPServer] | None = None,
    extra_tools: list[Tool] | None = None,
) -> Agent:
    tools: list[Tool] = [
        send_message, defer_reply, end_of_turn,
    ] + list(extra_tools or [])
    return Agent(
        name="Anna",
        instructions=(
            "You are Anna, a warm and caring companion.\n"
            "IMPORTANT: Never output text directly. Always use send_message to talk.\n"
            "Send multiple short messages like texting a friend, not one long paragraph.\n"
            "Use defer_reply to pause naturally, like a real person taking a moment.\n"
            "After a pause you will be called again — you can then decide to say more or end.\n"
            "When you are done, call end_of_turn."
        ),
        model=MODEL,
        tools=tools,
        tool_use_behavior={"stop_at_tool_names": ["end_of_turn", "defer_reply"]},
        mcp_servers=list(mcp_servers or []),
    )
