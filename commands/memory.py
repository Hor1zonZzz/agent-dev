"""Memory management commands for the run registry."""

from __future__ import annotations

from typing import Any

from run import Registry

# In-process placeholder — swap with external service (e.g. OpenViking) later
_store: dict[str, dict[str, Any]] = {}


def register_memory_commands(registry: Registry) -> None:
    registry.register(
        "memory",
        "Manage memories.\n"
        "  memory store <key> <content> [--tag <t>]  — store a memory\n"
        "  memory get <key>                          — retrieve by key\n"
        "  memory list                               — list all memories\n"
        "  memory search <query>                     — search by keyword\n"
        "  memory delete <key>                       — delete by key",
        _memory_handler,
    )


def _memory_handler(args: list[str], stdin: str) -> str:
    if not args:
        raise ValueError("usage: memory store|get|search|list|delete")

    sub = args[0]
    rest = args[1:]

    if sub == "store":
        return _store_cmd(rest, stdin)
    if sub == "get":
        return _get_cmd(rest)
    if sub == "list":
        return _list_cmd()
    if sub == "search":
        return _search_cmd(rest)
    if sub == "delete":
        return _delete_cmd(rest)

    raise ValueError(f"unknown: memory {sub}. Use: store|get|search|list|delete")


def _store_cmd(args: list[str], stdin: str) -> str:
    if len(args) < 2 and not stdin:
        raise ValueError("usage: memory store <key> <content>")
    key = args[0]
    content = " ".join(args[1:]) if len(args) > 1 else stdin
    metadata: dict[str, Any] = {}
    filtered: list[str] = []
    parts = content.split() if content else []
    i = 0
    while i < len(parts):
        if parts[i] == "--tag" and i + 1 < len(parts):
            metadata.setdefault("tags", []).append(parts[i + 1])
            i += 2
        else:
            filtered.append(parts[i])
            i += 1
    content = " ".join(filtered)
    _store[key] = {"content": content, "metadata": metadata}
    return f"Stored memory '{key}'."


def _get_cmd(args: list[str]) -> str:
    if not args:
        raise ValueError("usage: memory get <key>")
    key = args[0]
    entry = _store.get(key)
    if entry is None:
        return f"No memory found for key '{key}'."
    return f"[{key}] {entry['content']}\nMetadata: {entry['metadata']}"


def _list_cmd() -> str:
    if not _store:
        return "No memories stored."
    lines = [f"  {k} — {v['content'][:80]}" for k, v in _store.items()]
    return f"Memories ({len(lines)}):\n" + "\n".join(lines)


def _search_cmd(args: list[str]) -> str:
    if not args:
        raise ValueError("usage: memory search <query>")
    query = " ".join(args).lower()
    results = []
    for key, entry in _store.items():
        if query in entry["content"].lower() or query in str(entry["metadata"]).lower():
            results.append(f"  [{key}] {entry['content'][:120]}")
    if not results:
        return f"No memories matching '{' '.join(args)}'."
    return f"Found {len(results)} result(s):\n" + "\n".join(results)


def _delete_cmd(args: list[str]) -> str:
    if not args:
        raise ValueError("usage: memory delete <key>")
    key = args[0]
    if key in _store:
        del _store[key]
        return f"Deleted memory '{key}'."
    return f"No memory found for key '{key}'."
