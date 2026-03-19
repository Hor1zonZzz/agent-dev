"""Memory retrieval agent — search and browse, no write tools."""

from __future__ import annotations

from agents import Agent, Tool

from tools import list_memories, read_memory, search_memory

from .chat import MODEL


def build_memory_agent() -> Agent:
    return Agent(
        name="memory",
        instructions=(
            "You are a memory retrieval assistant. "
            "Use search_memory to find relevant user memories by semantic query. "
            "Use list_memories and read_memory to browse the memory filesystem. "
            "Return results directly without embellishment."
        ),
        tools=[search_memory, list_memories, read_memory],
        model=MODEL,
    )


def build_memory_tool() -> Tool:
    agent = build_memory_agent()
    return agent.as_tool(
        tool_name="recall_memory",
        tool_description="Retrieve user memories and preferences by semantic search or filesystem browsing.",
    )
