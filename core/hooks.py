"""RunHooks for the companion agent — centralises status pushes and logging."""

from __future__ import annotations

from agents import Agent, RunHooks, RunContextWrapper, Tool
from loguru import logger

from core.context import AgentContext


class CompanionHooks(RunHooks[AgentContext]):
    async def on_agent_start(
        self, context: RunContextWrapper[AgentContext], agent: Agent[AgentContext]
    ) -> None:
        logger.info("┌─ Agent START | {}", agent.name)
        await context.context.websocket.send_json(
            {"type": "status", "status": "typing"}
        )

    async def on_agent_end(
        self, context: RunContextWrapper[AgentContext], agent: Agent[AgentContext], output: str
    ) -> None:
        output_preview = str(output).replace("\n", "\\n")[:120]
        logger.info("└─ Agent END   | {} → {}", agent.name, output_preview)

    async def on_tool_start(
        self, context: RunContextWrapper[AgentContext], agent: Agent[AgentContext], tool: Tool
    ) -> None:
        args = getattr(context, "tool_arguments", None) or ""
        args_preview = str(args).replace("\n", "\\n")[:150]
        logger.info("│  Tool START  | {}.{} args={}", agent.name, tool.name, args_preview)

    async def on_tool_end(
        self, context: RunContextWrapper[AgentContext], agent: Agent[AgentContext], tool: Tool, result: str
    ) -> None:
        result_preview = str(result).replace("\n", "\\n")[:150]
        logger.info("│  Tool END    | {}.{} → {}", agent.name, tool.name, result_preview)
