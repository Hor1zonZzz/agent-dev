"""Lifecycle hooks for the agent loop."""

from __future__ import annotations

from typing import Protocol

from loguru import logger

from core.context import AgentContext
from core.tool import Tool


class Hooks(Protocol):
    """Protocol for agent loop lifecycle callbacks."""

    async def on_agent_start(self, agent_name: str, ctx: AgentContext) -> None: ...
    async def on_agent_end(self, agent_name: str, output: str, ctx: AgentContext) -> None: ...
    async def on_tool_start(self, agent_name: str, tool: Tool, args: str, ctx: AgentContext) -> None: ...
    async def on_tool_end(self, agent_name: str, tool: Tool, result: str, ctx: AgentContext) -> None: ...


class CompanionHooks:
    """Concrete hooks: structured logging for the agent loop."""

    async def on_agent_start(self, agent_name: str, ctx: AgentContext) -> None:
        logger.info("┌─ Agent START | {}", agent_name)

    async def on_agent_end(self, agent_name: str, output: str, ctx: AgentContext) -> None:
        preview = output.replace("\n", "\\n")[:120]
        logger.info("└─ Agent END   | {} → {}", agent_name, preview)

    async def on_tool_start(self, agent_name: str, tool: Tool, args: str, ctx: AgentContext) -> None:
        preview = args.replace("\n", "\\n")[:150]
        logger.info("│  Tool START  | {}.{} args={}", agent_name, tool.name, preview)

    async def on_tool_end(self, agent_name: str, tool: Tool, result: str, ctx: AgentContext) -> None:
        preview = result.replace("\n", "\\n")[:150]
        logger.info("│  Tool END    | {}.{} → {}", agent_name, tool.name, preview)
