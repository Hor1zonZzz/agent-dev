"""Runtime context shared between agent tools and the WebSocket connection."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

from fastapi import WebSocket


@dataclass
class AgentContext:
    websocket: WebSocket
    inbox: asyncio.Queue[str | None] = field(default_factory=asyncio.Queue)
