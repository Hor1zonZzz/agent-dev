"""Runtime context shared across the agent loop."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field


@dataclass
class AgentContext:
    inbox: asyncio.Queue[str | None] = field(default_factory=asyncio.Queue)
    last_user_input: str = ""
    send_reply: Callable[[str], Awaitable[None]] | None = None
    memory: str | None = None
