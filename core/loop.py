"""Agent loop — the core LLM ↔ tool-call cycle."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Any, Callable

from loguru import logger
from openai import AsyncOpenAI, NOT_GIVEN
from pydantic import BaseModel

from dotenv import load_dotenv

from core.hooks import Hooks
from core.tool import Tool

load_dotenv()

client = AsyncOpenAI()


@dataclass
class Agent:
    name: str
    instructions: str | Callable[..., str]
    model: str
    tools: list[Tool] = field(default_factory=list)
    stop_at: set[str] = field(default_factory=set)
    output_type: type[BaseModel] | None = None


@dataclass
class RunResult:
    messages: list[dict]
    final_output: str
    last_tool: str | None = None


async def run(
    agent: Agent,
    input: list[dict],
    *,
    ctx: Any = None,
    max_turns: int = 10,
    hooks: Hooks | None = None,
) -> RunResult:
    """Run the agent loop until the LLM stops calling tools or a stop_at tool fires."""

    # Build system message
    instructions = agent.instructions(ctx) if callable(agent.instructions) else agent.instructions
    messages: list[dict] = [{"role": "system", "content": instructions}] + list(input)

    # Build tool definitions
    tool_map = {t.name: t for t in agent.tools}
    openai_tools = [t.to_openai() for t in agent.tools] or NOT_GIVEN

    if hooks:
        await hooks.on_agent_start(agent.name, ctx)

    last_tool: str | None = None
    final_output = ""

    for turn in range(max_turns):
        # Inject pending inbox messages before each LLM call
        if ctx is not None and hasattr(ctx, "inbox"):
            pending: list[str] = []
            while not ctx.inbox.empty():
                msg = ctx.inbox.get_nowait()
                if msg is not None:
                    pending.append(msg)
            if pending:
                logger.info("Injecting {} inbox message(s) into LLM input", len(pending))
                for msg in pending:
                    ctx.record("user", msg)
                    messages.append({"role": "user", "content": msg})

        response = await client.chat.completions.create(
            model=agent.model,
            messages=messages,
            tools=openai_tools,
        )
        choice = response.choices[0].message

        # Append assistant message to history
        messages.append(choice.model_dump(exclude_none=True))

        # No tool calls → pure text, done
        if not choice.tool_calls:
            final_output = choice.content or ""
            break

        # Execute tool calls
        stopped = False
        for tc in choice.tool_calls:
            tool = tool_map.get(tc.function.name)
            if tool is None:
                logger.warning("Unknown tool call: {}", tc.function.name)
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": f"Error: unknown tool '{tc.function.name}'",
                })
                continue

            if hooks:
                await hooks.on_tool_start(agent.name, tool, tc.function.arguments, ctx)

            result = await tool.execute(tc.function.arguments, ctx)

            if hooks:
                await hooks.on_tool_end(agent.name, tool, result, ctx)

            messages.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "content": result,
            })
            last_tool = tc.function.name
            final_output = result

        # Check stop_at
        called_names = {tc.function.name for tc in choice.tool_calls}
        if agent.stop_at & called_names:
            break
    else:
        logger.warning("Agent '{}' hit max_turns={}", agent.name, max_turns)

    if hooks:
        await hooks.on_agent_end(agent.name, final_output, ctx)

    return RunResult(messages=messages, final_output=final_output, last_tool=last_tool)
