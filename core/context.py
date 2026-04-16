"""Runtime context shared across the agent loop."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from core.trace import TraceRecorder


@dataclass
class AgentContext:
    inbox: asyncio.Queue[str | None] = field(default_factory=asyncio.Queue)
    last_user_input: str = ""
    send_reply: Callable[[str], Awaitable[None]] | None = None
    memory: str | None = None
    trace_recorder: TraceRecorder | None = None
