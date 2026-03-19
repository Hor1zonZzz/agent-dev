"""Tools for memory retrieval."""

from agents import function_tool

import mem_manager


@function_tool
async def search_memory(query: str) -> str:
    """Search user memories by semantic query. Returns relevant facts and preferences."""
    results = await mem_manager.get_memories(query, limit=5)
    if not results:
        return "No relevant memories found."
    return "\n".join(f"- {m.abstract}" for m in results)
