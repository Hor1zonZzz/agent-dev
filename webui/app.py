"""FastAPI app for the local trace WebUI."""

from __future__ import annotations

import os
from pathlib import Path

import uvicorn
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sse_starlette.sse import EventSourceResponse

from core.trace import TRACE_DIR, TraceRepository
from webui.views import (
    DEFAULT_HISTORY_ROOT,
    STREAM_POLL_SECONDS,
    build_artifact_preview,
    build_run_detail_payload,
    build_runs_payload,
    stream_run_events,
    stream_run_summaries,
)

WEBUI_ROOT = Path(__file__).resolve().parent
TEMPLATES_DIR = WEBUI_ROOT / "templates"
STATIC_DIR = WEBUI_ROOT / "static"
DEFAULT_HOST = os.getenv("TRACE_WEB_HOST", "127.0.0.1")
DEFAULT_PORT = int(os.getenv("TRACE_WEB_PORT", "8000"))
DEFAULT_RELOAD = os.getenv("TRACE_WEB_RELOAD", "0").lower() in {"1", "true", "yes"}
DEFAULT_SSE_PING = float(os.getenv("TRACE_WEB_SSE_PING", "1.0"))


def create_app(
    *,
    trace_dir: Path | None = None,
    history_root: Path | None = None,
    poll_seconds: float = STREAM_POLL_SECONDS,
    sse_ping_seconds: float = DEFAULT_SSE_PING,
) -> FastAPI:
    app = FastAPI(title="Trace WebUI", version="0.1.0")
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    app.state.repo = TraceRepository(trace_dir or TRACE_DIR)
    app.state.history_root = (history_root or DEFAULT_HISTORY_ROOT).resolve()
    app.state.poll_seconds = poll_seconds
    app.state.sse_ping_seconds = sse_ping_seconds
    templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

    @app.get("/", include_in_schema=False)
    async def root() -> RedirectResponse:
        return RedirectResponse(url="/traces", status_code=307)

    @app.get("/traces", include_in_schema=False)
    async def traces_page(
        request: Request,
        limit: int = Query(50, ge=1, le=200),
        day: str | None = None,
        run_kind: str | None = None,
        source: str | None = None,
        session_id: str | None = None,
        status: str | None = None,
    ):
        payload = build_runs_payload(
            request.app.state.repo,
            limit=limit,
            day=day,
            run_kind=run_kind,
            source=source,
            session_id=session_id,
            status=status,
        )
        return templates.TemplateResponse(
            request=request,
            name="runs.html",
            context={
                "page_title": "Trace Runs",
                "payload": payload,
                "stream_url": str(request.url_for("stream_runs_api").include_query_params(
                    limit=limit,
                    day=day or "",
                    run_kind=run_kind or "",
                    source=source or "",
                    session_id=session_id or "",
                    status=status or "",
                )),
            },
        )

    @app.get("/traces/{run_id}", include_in_schema=False)
    async def run_detail_page(request: Request, run_id: str):
        payload = build_run_detail_payload(
            request.app.state.repo,
            run_id,
            history_root=request.app.state.history_root,
        )
        if payload is None:
            raise HTTPException(status_code=404, detail="Run not found")
        return templates.TemplateResponse(
            request=request,
            name="run_detail.html",
            context={
                "page_title": f"Run {run_id}",
                "payload": payload,
                "stream_url": str(request.url_for("stream_run_api", run_id=run_id)),
            },
        )

    @app.get("/artifacts/preview", include_in_schema=False)
    async def artifact_preview_page(request: Request, path: str):
        try:
            payload = build_artifact_preview(path, request.app.state.history_root)
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return templates.TemplateResponse(
            request=request,
            name="artifact_preview.html",
            context={
                "page_title": f"Artifact {payload['relative_path']}",
                "payload": payload,
            },
        )

    @app.get("/api/runs", name="runs_api")
    async def runs_api(
        limit: int = Query(50, ge=1, le=200),
        day: str | None = None,
        run_kind: str | None = None,
        source: str | None = None,
        session_id: str | None = None,
        status: str | None = None,
    ) -> JSONResponse:
        payload = build_runs_payload(
            app.state.repo,
            limit=limit,
            day=day,
            run_kind=run_kind,
            source=source,
            session_id=session_id,
            status=status,
        )
        return JSONResponse(payload)

    @app.get("/api/runs/{run_id}", name="run_detail_api")
    async def run_detail_api(run_id: str) -> JSONResponse:
        payload = build_run_detail_payload(
            app.state.repo,
            run_id,
            history_root=app.state.history_root,
        )
        if payload is None:
            raise HTTPException(status_code=404, detail="Run not found")
        return JSONResponse(payload)

    @app.get("/api/artifacts/preview", name="artifact_preview_api")
    async def artifact_preview_api(path: str) -> JSONResponse:
        try:
            payload = build_artifact_preview(path, app.state.history_root)
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return JSONResponse(payload)

    @app.get("/api/stream/runs", name="stream_runs_api")
    async def stream_runs_api(
        limit: int = Query(50, ge=1, le=200),
        day: str | None = None,
        run_kind: str | None = None,
        source: str | None = None,
        session_id: str | None = None,
        status: str | None = None,
    ) -> EventSourceResponse:
        generator = stream_run_summaries(
            app.state.repo,
            limit=limit,
            day=day,
            run_kind=run_kind,
            source=source,
            session_id=session_id,
            status=status,
            poll_seconds=app.state.poll_seconds,
        )
        return EventSourceResponse(generator, ping=app.state.sse_ping_seconds)

    @app.get("/api/stream/runs/{run_id}", name="stream_run_api")
    async def stream_run_api(run_id: str) -> EventSourceResponse:
        if app.state.repo.get_run(run_id) is None:
            raise HTTPException(status_code=404, detail="Run not found")
        generator = stream_run_events(
            app.state.repo,
            run_id,
            poll_seconds=app.state.poll_seconds,
        )
        return EventSourceResponse(generator, ping=app.state.sse_ping_seconds)

    return app


app = create_app()


def main() -> None:
    uvicorn.run(
        "webui.app:app",
        host=DEFAULT_HOST,
        port=DEFAULT_PORT,
        reload=DEFAULT_RELOAD,
    )


if __name__ == "__main__":
    main()
