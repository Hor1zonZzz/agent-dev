"""Agent loop — the core LLM ↔ tool-call cycle."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Any, Callable

from dotenv import load_dotenv
from loguru import logger
from openai import AsyncOpenAI, NOT_GIVEN
from pydantic import BaseModel

from core.tool import Tool
from core.trace import (
    RunMeta,
    TraceRecorder,
    TraceSink,
    get_default_trace_sink,
    truncate_preview,
)

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
    run_id: str | None = None
    trace_seq: int = 0


def _maybe_json(value: str) -> Any:
    try:
        return json.loads(value)
    except Exception:
        return value


async def run(
    agent: Agent,
    input: list[dict],
    *,
    ctx: Any = None,
    max_turns: int = 10,
    trace_sink: TraceSink | None = None,
    run_meta: RunMeta | None = None,
) -> RunResult:
    """Run the agent loop until the LLM stops calling tools or a stop_at tool fires."""

    instructions = agent.instructions(ctx) if callable(agent.instructions) else agent.instructions
    cleaned_input = [{k: v for k, v in msg.items() if k != "reasoning_content"} for msg in input]
    messages: list[dict] = [{"role": "system", "content": instructions}] + cleaned_input

    tool_map = {tool.name: tool for tool in agent.tools}
    openai_tools = [tool.to_openai() for tool in agent.tools] or NOT_GIVEN

    recorder = TraceRecorder(
        trace_sink or get_default_trace_sink(),
        run_meta or RunMeta(run_kind="cli_chat", source="runtime"),
    )
    if ctx is not None and hasattr(ctx, "trace_recorder"):
        ctx.trace_recorder = recorder

    last_tool: str | None = None
    final_output = ""

    await recorder.emit(
        lane="runtime",
        type="run.started",
        status="ok",
        summary=f"{agent.name} started",
        payload={
            "agent_name": agent.name,
            "model": agent.model,
            "max_turns": max_turns,
            "tool_names": [tool.name for tool in agent.tools],
            "message_count": len(cleaned_input),
        },
    )

    try:
        for turn in range(max_turns):
            await recorder.emit(
                lane="runtime",
                type="turn.started",
                status="ok",
                summary=f"turn {turn + 1} started",
                payload={"turn": turn + 1},
            )

            pending: list[str] = []
            if ctx is not None and hasattr(ctx, "inbox"):
                while not ctx.inbox.empty():
                    msg = ctx.inbox.get_nowait()
                    if msg is not None:
                        pending.append(msg)
                if pending:
                    logger.info("Injecting {} inbox message(s) into LLM input", len(pending))
                    for msg in pending:
                        messages.append({"role": "user", "content": msg})

            await recorder.emit(
                lane="runtime",
                type="inbox.drained",
                status="ok",
                summary=f"drained {len(pending)} inbox message(s)",
                payload={
                    "turn": turn + 1,
                    "count": len(pending),
                    "previews": [truncate_preview(msg) for msg in pending],
                },
            )

            logger.debug("Request messages:\n{}", json.dumps(messages, ensure_ascii=False, indent=2))
            await recorder.emit(
                lane="llm",
                type="llm.requested",
                status="ok",
                summary=f"requesting LLM turn {turn + 1}",
                payload={
                    "turn": turn + 1,
                    "message_count": len(messages),
                    "tool_count": len(agent.tools),
                    "last_message_role": messages[-1]["role"] if messages else None,
                    "last_message_preview": truncate_preview(messages[-1].get("content")) if messages else "",
                },
            )

            response = await client.chat.completions.create(
                model=agent.model,
                messages=messages,
                tools=openai_tools,
            )
            choice = response.choices[0].message

            await recorder.emit(
                lane="llm",
                type="llm.responded",
                status="ok",
                summary=f"received LLM turn {turn + 1}",
                payload={
                    "turn": turn + 1,
                    "content_preview": truncate_preview(choice.content),
                    "reasoning_preview": truncate_preview(getattr(choice, "reasoning_content", None)),
                    "tool_call_names": [tc.function.name for tc in choice.tool_calls or []],
                    "tool_call_count": len(choice.tool_calls or []),
                },
            )

            messages.append(choice.model_dump(exclude_none=True))

            if not choice.tool_calls:
                final_output = choice.content or ""
                break

            for tc in choice.tool_calls:
                tool_name = tc.function.name
                args_preview = truncate_preview(tc.function.arguments)
                parsed_arguments = _maybe_json(tc.function.arguments)
                await recorder.emit(
                    lane="tool",
                    type="tool.started",
                    status="ok",
                    summary=f"{tool_name} started",
                    payload={
                        "tool_name": tool_name,
                        "arguments": parsed_arguments,
                        "arguments_preview": args_preview,
                    },
                )

                tool = tool_map.get(tool_name)
                if tool is None:
                    error_message = f"Error: unknown tool '{tool_name}'"
                    logger.warning("Unknown tool call: {}", tool_name)
                    messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": tc.id,
                            "content": error_message,
                        }
                    )
                    await recorder.emit(
                        lane="tool",
                        type="tool.finished",
                        status="error",
                        summary=f"{tool_name} missing",
                        payload={
                            "tool_name": tool_name,
                            "error_message": error_message,
                        },
                    )
                    continue

                try:
                    result = await tool.execute(tc.function.arguments, ctx)
                except Exception as exc:
                    await recorder.emit(
                        lane="tool",
                        type="tool.finished",
                        status="error",
                        summary=f"{tool_name} failed",
                        payload={
                            "tool_name": tool_name,
                            "error_type": type(exc).__name__,
                            "error_message": str(exc),
                        },
                    )
                    raise

                await recorder.emit(
                    lane="tool",
                    type="tool.finished",
                    status="ok",
                    summary=f"{tool_name} finished",
                    payload={
                        "tool_name": tool_name,
                        "result_preview": truncate_preview(result),
                    },
                )

                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": result,
                    }
                )
                last_tool = tool_name
                final_output = result

            called_names = {tc.function.name for tc in choice.tool_calls}
            if agent.stop_at & called_names:
                break
        else:
            logger.warning("Agent '{}' hit max_turns={}", agent.name, max_turns)
            await recorder.emit(
                lane="runtime",
                type="run.max_turns_hit",
                status="error",
                summary=f"hit max_turns={max_turns}",
                payload={"max_turns": max_turns},
            )

        await recorder.emit(
            lane="runtime",
            type="run.finished",
            status="ok",
            summary=f"{agent.name} finished",
            payload={
                "agent_name": agent.name,
                "last_tool": last_tool,
                "final_output_preview": truncate_preview(final_output),
            },
        )
        return RunResult(
            messages=messages,
            final_output=final_output,
            last_tool=last_tool,
            run_id=recorder.run_id,
            trace_seq=recorder.seq,
        )
    except Exception as exc:
        await recorder.emit(
            lane="runtime",
            type="run.failed",
            status="error",
            summary=f"{agent.name} failed",
            payload={
                "agent_name": agent.name,
                "error_type": type(exc).__name__,
                "error_message": str(exc),
            },
        )
        raise
