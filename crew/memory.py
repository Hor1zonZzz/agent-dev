"""Memory retrieval agent — search-only, no write tools."""

from __future__ import annotations

from agents import Agent, Tool

from tools import search_memory

from .chat import MODEL


def build_memory_agent() -> Agent:
    return Agent(
        name="memory",
        instructions=(
            "You are a memory retrieval assistant. "
            "Use the search_memory tool to find relevant user memories. "
            "Return the results directly without embellishment."
        ),
        tools=[search_memory],
        model=MODEL,
    )


def build_memory_tool() -> Tool:
    agent = build_memory_agent()
    return agent.as_tool(
        tool_name="recall_memory",
        tool_description="Retrieve user memories and preferences by semantic search.",
    )
