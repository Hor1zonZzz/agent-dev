"""Browse the OpenViking memories filesystem."""

from agents import function_tool

import mem_backend


@function_tool
async def list_memories(uri: str = "viking://user/default/memories/") -> str:
    """List files and directories under a Viking URI.
    Defaults to the user memories root. Returns name, type (dir/file), and uri for each entry."""
    entries = await mem_backend.ls(uri)
    if not entries:
        return "No entries found."
    lines = []
    for e in entries:
        kind = "dir" if e.get("isDir") else "file"
        lines.append(f"- [{kind}] {e['name']}  uri={e['uri']}")
    return "\n".join(lines)


@function_tool
async def read_memory(uri: str) -> str:
    """Read a file from the memory filesystem by Viking URI.
    Recommended workflow: list_memories first, then read .abstract.md to understand a directory,
    read .overview.md for more detail if relevant, only then explore subdirectories or read full files."""
    content = await mem_backend.read(uri)
    if not content:
        return "File is empty or does not exist."
    return content
