"""Memory storage backend backed by OpenViking."""

from __future__ import annotations

import os
from dataclasses import dataclass

from openviking import AsyncOpenViking


@dataclass
class MemoryResult:
    """A single retrieved memory."""
    uri: str
    abstract: str
    score: float


_ov: AsyncOpenViking | None = None


async def init(config_path: str = "./ov.conf", data_path: str = "./data") -> None:
    """Initialize OpenViking. Call once at startup."""
    os.environ.setdefault("OPENVIKING_CONFIG_FILE", config_path)
    global _ov
    _ov = AsyncOpenViking(path=data_path)
    await _ov.initialize()


async def close() -> None:
    global _ov
    if _ov:
        await _ov.close()
        _ov = None


async def commit(messages: list[dict]) -> int:
    """Create a session, batch-write messages, commit, return memories extracted count.

    Args:
        messages: [{"role": "user"|"assistant", "content": "..."}]

    Returns:
        Number of memories extracted.
    """
    if not _ov or not messages:
        return 0

    session = await _ov.create_session()
    sid = session["session_id"]

    for msg in messages:
        await _ov.add_message(sid, role=msg["role"], content=msg["content"])

    result = await _ov.commit_session(sid)
    return result.get("memories_extracted", 0)


async def search(query: str, limit: int = 5) -> list[MemoryResult]:
    """Search memories by semantic query."""
    if not _ov:
        return []

    results = await _ov.find(query, limit=limit)

    return [
        MemoryResult(uri=m.uri, abstract=m.abstract, score=m.score)
        for m in results.memories
        if m.abstract
    ]
