"""Semantic search over memories (powered by OpenViking find)."""

from agents import function_tool

import mem_backend


@function_tool
async def search_memory(query: str) -> str:
    """Search user memories by semantic query. Returns relevant facts and preferences."""
    results = await mem_backend.search(query, limit=5)
    if not results:
        return "No relevant memories found."
    return "\n".join(f"- {m.abstract}" for m in results)
