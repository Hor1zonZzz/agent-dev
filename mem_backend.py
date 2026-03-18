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
_session_id: str | None = None


async def init(config_path: str = "./ov.conf", data_path: str = "./data") -> str:
    """Initialize OpenViking and create one shared session for this run."""
    os.environ.setdefault("OPENVIKING_CONFIG_FILE", config_path)
    global _ov, _session_id
    if _ov is not None and _session_id is not None:
        return _session_id

    _ov = AsyncOpenViking(path=data_path)
    await _ov.initialize()
    session = await _ov.create_session()
    session_id = session.get("session_id")
    if not isinstance(session_id, str) or not session_id:
        raise RuntimeError("OpenViking returned an invalid session_id")
    _session_id = session_id
    return _session_id


async def close() -> None:
    global _ov, _session_id
    if _ov:
        await _ov.close()
        _ov = None
    _session_id = None


async def commit(messages: list[dict]) -> int:
    """Write to the shared session, commit, return memories extracted count.

    Args:
        messages: [{"role": "user"|"assistant", "content": "..."}]

    Returns:
        Number of memories extracted.
    """
    if not messages:
        return 0
    if not _ov or not _session_id:
        raise RuntimeError("OpenViking is not initialized")

    for msg in messages:
        await _ov.add_message(_session_id, role=msg["role"], content=msg["content"])

    result = await _ov.commit_session(_session_id)
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
