"""FastAPI service entrypoint for the single-session chat agent."""

from __future__ import annotations

import asyncio
import json
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, AsyncIterator

import tracing
from agents import RunConfig, Runner, SQLiteSession
from agents.mcp import MCPServerManager
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

import mem_tools
from crew import MODEL, build_chat_agent, build_memory_tool
from context_policy import build_run_config
from mcp_servers import build_servers


@dataclass
class RuntimeState:
    session_id: str
    session: SQLiteSession
    active_servers: int
    chat_agent: Any
    run_config: RunConfig
    request_lock: asyncio.Lock = field(default_factory=asyncio.Lock)


class ChatStreamRequest(BaseModel):
    message: str = Field(min_length=1)
    session_id: str | None = None


def _sse_event(event: str, payload: dict[str, Any]) -> str:
    data = json.dumps(payload, ensure_ascii=False)
    return f"event: {event}\ndata: {data}\n\n"


def _get_runtime(request: Request) -> RuntimeState:
    runtime = getattr(request.app.state, "runtime", None)
    if runtime is None:
        raise RuntimeError("Application runtime is not initialized")
    return runtime


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    session_id = await mem_tools.init()
    session = SQLiteSession(session_id=session_id, db_path="chat.db")
    mcp_servers = build_servers()
    run_config = build_run_config()

    async with MCPServerManager(mcp_servers, strict=False) as manager:
        app.state.runtime = RuntimeState(
            session_id=session_id,
            session=session,
            active_servers=len(manager.active_servers),
            chat_agent=build_chat_agent(
                manager.active_servers,
                extra_tools=[build_memory_tool()],
            ),
            run_config=run_config,
        )
        try:
            yield
        finally:
            session.close()
            await mem_tools.close()
            tracing.tracer_provider.force_flush()


app = FastAPI(lifespan=lifespan)
UI_DIR = Path(__file__).resolve().parent / "ui"


@app.get("/health")
async def health(request: Request) -> dict[str, Any]:
    runtime = _get_runtime(request)
    return {
        "status": "ok",
        "model": MODEL,
        "session_id": runtime.session_id,
        "active_servers": runtime.active_servers,
    }


@app.post("/chat/stream")
async def chat_stream(payload: ChatStreamRequest, request: Request) -> StreamingResponse:
    runtime = _get_runtime(request)
    if payload.session_id is not None and payload.session_id != runtime.session_id:
        raise HTTPException(
            status_code=409,
            detail="This server only supports one active session. Reuse the issued session_id.",
        )

    async def event_stream() -> AsyncIterator[str]:
        async with runtime.request_lock:
            messages: list[str] = []
            tool_calls: dict[str, str] = {}  # call_id → tool_name
            result = Runner.run_streamed(
                runtime.chat_agent,
                payload.message,
                run_config=runtime.run_config,
                session=runtime.session,
            )
            try:
                yield _sse_event("session", {"session_id": runtime.session_id})

                async for event in result.stream_events():
                    if event.type != "run_item_stream_event":
                        continue
                    raw = getattr(event.item, "raw_item", None)
                    if event.name == "tool_called" and raw is not None:
                        call_id = getattr(raw, "call_id", None) or (raw.get("call_id") if isinstance(raw, dict) else None)
                        name = getattr(raw, "name", None) or (raw.get("name") if isinstance(raw, dict) else None)
                        if call_id and name:
                            tool_calls[call_id] = name
                    elif event.name == "tool_output" and raw is not None:
                        call_id = raw.get("call_id") if isinstance(raw, dict) else getattr(raw, "call_id", None)
                        if call_id and tool_calls.get(call_id) == "response_to_user":
                            text = event.item.output or ""
                            messages.append(text)
                            yield _sse_event("message", {"text": text})

                final_output = "\n\n".join(messages).strip()

                await mem_tools.on_turn(payload.message, final_output)
                yield _sse_event(
                    "done",
                    {
                        "session_id": runtime.session_id,
                        "final_output": final_output,
                    },
                )
            except Exception as exc:
                yield _sse_event("error", {"detail": str(exc)})
            finally:
                tracing.tracer_provider.force_flush()

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@app.get("/")
async def index() -> FileResponse:
    return FileResponse(UI_DIR / "index.html")


app.mount("/static", StaticFiles(directory=UI_DIR), name="static")
