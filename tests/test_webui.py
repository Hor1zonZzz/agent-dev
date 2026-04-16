from __future__ import annotations

import asyncio
import json
import threading
import time
from pathlib import Path

from fastapi.testclient import TestClient
from sse_starlette.sse import EventSourceResponse

from core.trace import NdjsonTraceSink, RunMeta, TraceRecorder, TraceRepository
from webui.app import create_app
from webui.views import stream_run_events, stream_run_summaries


def _make_client(trace_dir: Path, history_root: Path) -> TestClient:
    return TestClient(
        create_app(
            trace_dir=trace_dir,
            history_root=history_root,
            poll_seconds=0.01,
            sse_ping_seconds=0.01,
        )
    )


def _emit_sample_run(trace_dir: Path, history_root: Path) -> str:
    sink = NdjsonTraceSink(trace_dir)
    history_path = history_root / "wechat" / "u1.json"
    history_path.parent.mkdir(parents=True, exist_ok=True)
    history_path.write_text('[{"role":"user","content":"hi"}]', encoding="utf-8")
    diary_path = history_root / "diary" / "2026-04-17.md"
    diary_path.parent.mkdir(parents=True, exist_ok=True)
    diary_path.write_text("## 08:00  查天气\n内容\n", encoding="utf-8")

    recorder = TraceRecorder(
        sink,
        RunMeta(
            run_kind="wechat_chat",
            source="wechat",
            session_id="u1",
            user_id="u1",
            context={"history_path": str(history_path), "transport": "wechat"},
        ),
    )
    recorder.emit_sync(
        lane="dispatch",
        type="dispatch.enqueued",
        status="ok",
        summary="wechat batch dequeued",
        payload={"message_count": 1, "first_preview": "hi"},
    )
    recorder.emit_sync(
        lane="runtime",
        type="run.started",
        status="ok",
        summary="anna started",
        payload={},
    )
    recorder.emit_sync(
        lane="llm",
        type="llm.requested",
        status="ok",
        summary="requesting LLM turn 1",
        payload={"turn": 1},
    )
    recorder.emit_sync(
        lane="llm",
        type="llm.responded",
        status="ok",
        summary="received LLM turn 1",
        payload={"tool_call_count": 1},
    )
    recorder.emit_sync(
        lane="tool",
        type="tool.started",
        status="ok",
        summary="send_message started",
        payload={"tool_name": "send_message", "arguments": {"message": "hello"}},
    )
    recorder.emit_sync(
        lane="tool",
        type="tool.finished",
        status="ok",
        summary="send_message finished",
        payload={"tool_name": "send_message", "result_preview": "Message sent."},
    )
    recorder.emit_sync(
        lane="artifact",
        type="artifact.written",
        status="ok",
        summary="history appended",
        payload={"artifact_kind": "history", "path": str(history_path)},
    )
    recorder.emit_sync(
        lane="artifact",
        type="diary.appended",
        status="ok",
        summary="diary appended",
        payload={"path": str(diary_path)},
    )
    recorder.emit_sync(
        lane="runtime",
        type="run.finished",
        status="ok",
        summary="anna finished",
        payload={},
    )
    return recorder.run_id


def _emit_error_run(trace_dir: Path) -> str:
    sink = NdjsonTraceSink(trace_dir)
    recorder = TraceRecorder(
        sink,
        RunMeta(run_kind="planner", source="planner", session_id="planner"),
    )
    recorder.emit_sync(
        lane="runtime",
        type="run.started",
        status="ok",
        summary="planner started",
        payload={},
    )
    recorder.emit_sync(
        lane="runtime",
        type="run.failed",
        status="error",
        summary="planner failed",
        payload={"error_message": "boom"},
    )
    return recorder.run_id


def test_runs_api_filters_and_derived_fields(tmp_path: Path):
    trace_dir = tmp_path / "traces"
    history_root = tmp_path / "history"
    run_id = _emit_sample_run(trace_dir, history_root)
    _emit_error_run(trace_dir)

    client = _make_client(trace_dir, history_root)
    response = client.get("/api/runs", params={"limit": 10, "source": "wechat", "status": "ok"})
    assert response.status_code == 200

    payload = response.json()
    assert payload["count"] == 1
    run = payload["runs"][0]
    assert run["run_id"] == run_id
    assert run["tool_count"] == 1
    assert run["artifact_count"] >= 1
    assert run["lane_counts"]["llm"] == 2
    assert run["status"] == "ok"


def test_run_detail_api_and_pages_render(tmp_path: Path):
    trace_dir = tmp_path / "traces"
    history_root = tmp_path / "history"
    run_id = _emit_sample_run(trace_dir, history_root)
    client = _make_client(trace_dir, history_root)

    api_response = client.get(f"/api/runs/{run_id}")
    assert api_response.status_code == 200
    payload = api_response.json()
    assert payload["run"]["run_id"] == run_id
    assert any(item["type"] == "llm.exchange" for item in payload["timeline"])
    assert any(item["type"] == "tool.send_message" for item in payload["timeline"])
    assert len(payload["artifacts"]) >= 1

    page_response = client.get("/traces")
    assert page_response.status_code == 200
    assert "Trace Runs" in page_response.text
    assert run_id in page_response.text

    detail_page = client.get(f"/traces/{run_id}")
    assert detail_page.status_code == 200
    assert "Run Summary" in detail_page.text
    assert "Timeline" in detail_page.text
    assert "Related Artifacts" in detail_page.text


def test_empty_state_and_missing_run(tmp_path: Path):
    trace_dir = tmp_path / "traces"
    history_root = tmp_path / "history"
    client = _make_client(trace_dir, history_root)

    runs = client.get("/traces")
    assert runs.status_code == 200
    assert "还没有 trace run" in runs.text

    missing = client.get("/traces/missing-run")
    assert missing.status_code == 404


def test_artifact_preview_and_security(tmp_path: Path):
    trace_dir = tmp_path / "traces"
    history_root = tmp_path / "history"
    diary_path = history_root / "diary" / "2026-04-17.md"
    diary_path.parent.mkdir(parents=True, exist_ok=True)
    diary_path.write_text("hello diary", encoding="utf-8")
    outside = tmp_path / "secret.txt"
    outside.write_text("secret", encoding="utf-8")

    client = _make_client(trace_dir, history_root)

    ok = client.get("/api/artifacts/preview", params={"path": str(diary_path)})
    assert ok.status_code == 200
    assert ok.json()["artifact_kind"] == "diary"

    page = client.get("/artifacts/preview", params={"path": str(diary_path)})
    assert page.status_code == 200
    assert "Artifact Preview" in page.text

    forbidden = client.get("/api/artifacts/preview", params={"path": str(outside)})
    assert forbidden.status_code == 403


def test_sse_run_summary_stream_emits_on_new_run(tmp_path: Path):
    trace_dir = tmp_path / "traces"
    history_root = tmp_path / "history"
    repo = TraceRepository(trace_dir)
    _emit_sample_run(trace_dir, history_root)

    def writer():
        time.sleep(0.05)
        _emit_error_run(trace_dir)

    thread = threading.Thread(target=writer)
    thread.start()

    async def body():
        generator = stream_run_summaries(repo, limit=20, poll_seconds=0.01)
        try:
            event = await asyncio.wait_for(anext(generator), timeout=1.0)
        finally:
            await generator.aclose()
        return event

    event = asyncio.run(body())
    thread.join()

    assert event["event"] == "run_update"
    data = json.loads(event["data"])
    assert data["run_id"]
    assert data["status"] == "error"


def test_sse_run_event_stream_emits_new_event(tmp_path: Path):
    trace_dir = tmp_path / "traces"
    history_root = tmp_path / "history"
    sink = NdjsonTraceSink(trace_dir)
    recorder = TraceRecorder(
        sink,
        RunMeta(run_kind="wechat_chat", source="wechat", session_id="u1"),
    )
    recorder.emit_sync(
        lane="runtime",
        type="run.started",
        status="ok",
        summary="started",
        payload={},
    )
    run_id = recorder.run_id
    repo = TraceRepository(trace_dir)

    def writer():
        time.sleep(0.05)
        follow_up = TraceRecorder(
            sink,
            RunMeta(
                run_kind="wechat_chat",
                source="wechat",
                run_id=run_id,
                session_id="u1",
                start_seq=recorder.seq,
            ),
        )
        follow_up.emit_sync(
            lane="runtime",
            type="run.finished",
            status="ok",
            summary="finished",
            payload={},
        )

    thread = threading.Thread(target=writer)
    thread.start()

    async def body():
        generator = stream_run_events(repo, run_id, poll_seconds=0.01)
        try:
            event = await asyncio.wait_for(anext(generator), timeout=1.0)
        finally:
            await generator.aclose()
        return event

    event = asyncio.run(body())
    thread.join()

    assert event["event"] == "run_event"
    data = json.loads(event["data"])
    assert data["type"] == "run.finished"


def test_sse_endpoints_smoke(tmp_path: Path):
    trace_dir = tmp_path / "traces"
    history_root = tmp_path / "history"
    run_id = _emit_sample_run(trace_dir, history_root)
    app = create_app(
        trace_dir=trace_dir,
        history_root=history_root,
        poll_seconds=0.01,
        sse_ping_seconds=0.01,
    )

    runs_route = next(route for route in app.routes if route.name == "stream_runs_api")
    run_route = next(route for route in app.routes if route.name == "stream_run_api")

    runs_response = asyncio.run(runs_route.endpoint(limit=50))
    assert isinstance(runs_response, EventSourceResponse)
    assert runs_response.media_type == "text/event-stream"

    run_response = asyncio.run(run_route.endpoint(run_id=run_id))
    assert isinstance(run_response, EventSourceResponse)
    assert run_response.media_type == "text/event-stream"
