from __future__ import annotations

from core.trace import NdjsonTraceSink, RunMeta, TraceRecorder, TraceRepository


def test_ndjson_roundtrip_and_repository_grouping(tmp_path):
    sink = NdjsonTraceSink(tmp_path)

    cli = TraceRecorder(sink, RunMeta(run_kind="cli_chat", source="cli", session_id="cli"))
    cli.emit_sync(
        lane="runtime",
        type="run.started",
        status="ok",
        summary="cli start",
        payload={},
    )
    cli.emit_sync(
        lane="runtime",
        type="run.finished",
        status="ok",
        summary="cli finish",
        payload={},
    )

    chat = TraceRecorder(sink, RunMeta(run_kind="wechat_chat", source="wechat", session_id="u1"))
    chat.emit_sync(
        lane="dispatch",
        type="dispatch.enqueued",
        status="ok",
        summary="queued",
        payload={},
    )
    chat.emit_sync(
        lane="runtime",
        type="run.finished",
        status="ok",
        summary="wechat finish",
        payload={},
    )

    repo = TraceRepository(tmp_path)
    runs = repo.list_runs(limit=10)
    assert len(runs) == 2
    assert {run.run_kind for run in runs} == {"cli_chat", "wechat_chat"}

    run = repo.get_run(cli.run_id)
    assert run is not None
    assert [event.seq for event in run.events] == [1, 2]
    assert [event.type for event in run.events] == ["run.started", "run.finished"]


def test_repository_filters(tmp_path):
    sink = NdjsonTraceSink(tmp_path)

    TraceRecorder(sink, RunMeta(run_kind="cli_chat", source="cli", session_id="cli")).emit_sync(
        lane="runtime",
        type="run.finished",
        status="ok",
        summary="cli",
        payload={},
    )
    TraceRecorder(sink, RunMeta(run_kind="wechat_chat", source="wechat", session_id="u1")).emit_sync(
        lane="runtime",
        type="run.finished",
        status="ok",
        summary="wechat",
        payload={},
    )

    repo = TraceRepository(tmp_path)
    wechat_runs = repo.list_runs(limit=10, run_kind="wechat_chat", session_id="u1")
    assert len(wechat_runs) == 1
    assert wechat_runs[0].source == "wechat"
