"""Lifecycle hooks for the agent loop."""

from __future__ import annotations

from typing import Protocol

from core.context import AgentContext
from core.tool import Tool


class Hooks(Protocol):
    """Protocol for agent loop lifecycle callbacks."""

    async def on_agent_start(self, agent_name: str, ctx: AgentContext) -> None: ...
    async def on_agent_end(self, agent_name: str, output: str, ctx: AgentContext) -> None: ...
    async def on_tool_start(self, agent_name: str, tool: Tool, args: str, ctx: AgentContext) -> None: ...
    async def on_tool_end(self, agent_name: str, tool: Tool, result: str, ctx: AgentContext) -> None: ...
