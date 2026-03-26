"""RunHooks for the companion agent — centralises status pushes and logging."""

from __future__ import annotations

from agents import Agent, RunHooks, RunContextWrapper, Tool
from loguru import logger

from agent_context import AgentContext


class CompanionHooks(RunHooks[AgentContext]):
    async def on_agent_start(
        self, context: RunContextWrapper[AgentContext], agent: Agent[AgentContext]
    ) -> None:
        logger.info("Agent run start | agent={}", agent.name)
        await context.context.websocket.send_json(
            {"type": "status", "status": "typing"}
        )

    async def on_agent_end(
        self, context: RunContextWrapper[AgentContext], agent: Agent[AgentContext], output: str
    ) -> None:
        logger.info("Agent run end | agent={} output={}", agent.name, str(output)[:80])

    async def on_tool_start(
        self, context: RunContextWrapper[AgentContext], agent: Agent[AgentContext], tool: Tool
    ) -> None:
        logger.info("Tool start | {}", tool.name)

    async def on_tool_end(
        self, context: RunContextWrapper[AgentContext], agent: Agent[AgentContext], tool: Tool, result: str
    ) -> None:
        logger.info("Tool end | {} result={}", tool.name, str(result)[:80])
