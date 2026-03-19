"""Memory retrieval agent — search-only, no write tools."""

from __future__ import annotations

from agents import Agent, Tool, function_tool

import mem_tools

from .chat import MODEL


@function_tool
async def search_memory(query: str) -> str:
    """Search user memories by semantic query. Returns relevant facts and preferences."""
    results = await mem_tools.get_memories(query, limit=5)
    if not results:
        return "No relevant memories found."
    return "\n".join(f"- {m.abstract}" for m in results)


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
