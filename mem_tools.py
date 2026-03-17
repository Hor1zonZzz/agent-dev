"""Sliding window memory manager. Pure logic — no storage dependency."""

from __future__ import annotations

import json
import os

from agents import Agent, Runner

import mem_backend

# --- Config ---

WINDOW_SIZE = 5       # 每 5 轮触发一次 check
MAX_EXPANSIONS = 4    # 最多扩容 4 次

# --- Buffer state ---

_buffer: list[dict] = []   # [{"role": "user"|"assistant", "content": "..."}]
_turn_count: int = 0
_check_count: int = 0

# --- Topic detection agent ---

_topic_detector: Agent | None = None


def _build_topic_detector() -> Agent:
    model = os.getenv("OPENAI_MODEL", "gpt-4.1-mini")
    return Agent(
        name="topic_detector",
        instructions=(
            "You are a topic boundary detector. Given a multi-turn conversation, "
            "determine whether a topic shift occurs.\n\n"
            "Rules:\n"
            '- If the entire conversation stays on the same topic, return {"pivot": null}\n'
            "- If a user message introduces a clearly different topic, "
            'return {"pivot": N}, where N is the sequence number of that user message '
            "(starting from 1, counting only user messages)\n\n"
            "Output JSON only. No explanation."
        ),
        model=model,
    )


def _format_buffer_for_detection() -> str:
    lines = []
    user_idx = 0
    for msg in _buffer:
        if msg["role"] == "user":
            user_idx += 1
            lines.append(f"[User #{user_idx}] {msg['content']}")
        else:
            lines.append(f"[Assistant] {msg['content']}")
    return "\n".join(lines)


async def _detect_topic_shift() -> int | None:
    """Return pivot user message number (1-based), or None if no shift."""
    global _topic_detector
    if _topic_detector is None:
        _topic_detector = _build_topic_detector()

    prompt = _format_buffer_for_detection()
    result = await Runner.run(_topic_detector, prompt)

    try:
        data = json.loads(str(result.final_output))
        pivot = data.get("pivot")
        if isinstance(pivot, int) and pivot >= 1:
            return pivot
        return None
    except (json.JSONDecodeError, TypeError, AttributeError):
        return None


def _buffer_index_for_user_n(n: int) -> int:
    """Find buffer index of the n-th user message (1-based)."""
    count = 0
    for i, msg in enumerate(_buffer):
        if msg["role"] == "user":
            count += 1
            if count == n:
                return i
    return len(_buffer)


async def _commit_and_split(split_idx: int | None = None) -> None:
    """Commit messages before split_idx to backend, keep the rest in buffer."""
    global _buffer, _turn_count, _check_count

    if split_idx is None:
        # commit all
        await mem_backend.commit(_buffer)
        _buffer = []
    else:
        to_commit = _buffer[:split_idx]
        carry_over = _buffer[split_idx:]
        await mem_backend.commit(to_commit)
        _buffer = carry_over

    _turn_count = len([m for m in _buffer if m["role"] == "user"])
    _check_count = 0


# --- Public API ---

async def init() -> None:
    """Initialize the backend."""
    await mem_backend.init()


async def close() -> None:
    """Commit remaining buffer and close backend."""
    global _turn_count, _check_count

    if _buffer:
        await mem_backend.commit(_buffer)
        _buffer.clear()
    _turn_count = 0
    _check_count = 0
    await mem_backend.close()


async def get_memories(query: str, limit: int = 5) -> list[mem_backend.MemoryResult]:
    """Retrieve memories from backend."""
    return await mem_backend.search(query, limit=limit)


async def on_turn(user_msg: str, assistant_msg: str) -> None:
    """Called after each conversation turn. Manages sliding window and commit timing."""
    global _turn_count, _check_count

    _buffer.append({"role": "user", "content": user_msg})
    _buffer.append({"role": "assistant", "content": assistant_msg})
    _turn_count += 1

    if _turn_count < WINDOW_SIZE:
        return

    # Window boundary reached
    _turn_count = 0
    _check_count += 1

    # Exceeded max expansions — force commit all
    if _check_count > MAX_EXPANSIONS + 1:
        await _commit_and_split()
        return

    # LLM topic detection
    pivot = await _detect_topic_shift()

    if pivot is None:
        return

    # Topic shift detected — commit before pivot, keep the rest
    split_idx = _buffer_index_for_user_n(pivot)
    await _commit_and_split(split_idx)
