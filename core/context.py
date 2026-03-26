"""Runtime context shared between agent tools and the WebSocket connection."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

from fastapi import WebSocket


MAX_RECENT = 4


@dataclass
class AgentContext:
    websocket: WebSocket
    inbox: asyncio.Queue[str | None] = field(default_factory=asyncio.Queue)
    last_user_input: str = ""
    recent_messages: list[tuple[str, str]] = field(default_factory=list)

    def record(self, role: str, text: str) -> None:
        """Record a (role, text) pair, keeping at most MAX_RECENT entries."""
        self.recent_messages.append((role, text))
        if len(self.recent_messages) > MAX_RECENT:
            self.recent_messages = self.recent_messages[-MAX_RECENT:]
