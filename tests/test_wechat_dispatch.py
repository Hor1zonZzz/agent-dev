"""WeChat dispatch/worker concurrency tests."""

from __future__ import annotations

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock

import pytest

import wechat
from core.loop import RunResult


def _mk_msg(text: str, user_id: str = "u1", token: str = "tok") -> MagicMock:
    message = MagicMock()
    message.body = text
    message.from_user = user_id
    message.context_token = token
    return message


def _ok_result() -> RunResult:
    return RunResult(messages=[], final_output="", last_tool=None, run_id="run_1", trace_seq=1)


@pytest.fixture(autouse=True)
def isolate_module_state(monkeypatch):
    monkeypatch.setattr(wechat, "_inbox", asyncio.Queue())
    monkeypatch.setattr(wechat, "_active_ctx", None)
    monkeypatch.setattr(wechat, "_active_user_id", None)
    monkeypatch.setattr(wechat, "update_dispatch_info", lambda *args, **kwargs: None)
    monkeypatch.setattr(wechat, "get_dispatch_info", lambda path: ("u1", "tok"))
    monkeypatch.setattr(
        wechat,
        "_build_reply_fn",
        lambda uid, tok: AsyncMock(return_value=None),
    )
    yield


async def _drive(worker_task: asyncio.Task, tick: float = 0.05) -> None:
    await asyncio.sleep(tick)
    worker_task.cancel()
    try:
        await worker_task
    except (asyncio.CancelledError, Exception):
        pass


def test_dispatch_when_idle_enqueues_to_inbox():
    async def body():
        await wechat.dispatch_reply(_mk_msg("hi"))
        assert wechat._inbox.qsize() == 1
        item = wechat._inbox.get_nowait()
        assert item.user_id == "u1"
        assert item.text == "hi"
        assert item.context_token == "tok"
        assert item.is_proactive is False

    asyncio.run(body())


def test_dispatch_ignores_blank_messages():
    async def body():
        await wechat.dispatch_reply(_mk_msg("   "))
        await wechat.dispatch_reply(_mk_msg(""))
        assert wechat._inbox.empty()

    asyncio.run(body())


def test_worker_consumes_queued_message(monkeypatch):
    captured: list[list[str]] = []

    async def fake_process(request):
        captured.append(list(request.incoming_messages))
        return _ok_result()

    monkeypatch.setattr(wechat._session_runner, "process", fake_process)

    async def body():
        task = asyncio.create_task(wechat.worker())
        await wechat.dispatch_reply(_mk_msg("hello"))
        await _drive(task)

    asyncio.run(body())

    assert captured == [["hello"]]


def test_dispatch_is_non_blocking_during_run(monkeypatch):
    run_started = asyncio.Event()
    run_release = asyncio.Event()

    async def slow_process(request):
        run_started.set()
        await run_release.wait()
        return _ok_result()

    monkeypatch.setattr(wechat._session_runner, "process", slow_process)

    async def body():
        task = asyncio.create_task(wechat.worker())
        await wechat.dispatch_reply(_mk_msg("first"))
        await run_started.wait()

        t0 = time.perf_counter()
        await wechat.dispatch_reply(_mk_msg("second"))
        elapsed = time.perf_counter() - t0

        assert elapsed < 0.02, f"dispatch blocked for {elapsed:.3f}s"
        assert wechat._active_ctx is not None
        assert wechat._active_ctx.inbox.qsize() == 1
        assert wechat._inbox.empty()

        run_release.set()
        await _drive(task)

    asyncio.run(body())


def test_mid_run_messages_go_to_ctx_inbox(monkeypatch):
    run_started = asyncio.Event()
    drained: list[str] = []

    async def fake_process(request):
        run_started.set()
        await asyncio.sleep(0.03)
        while not request.ctx.inbox.empty():
            drained.append(request.ctx.inbox.get_nowait())
        return _ok_result()

    monkeypatch.setattr(wechat._session_runner, "process", fake_process)

    async def body():
        task = asyncio.create_task(wechat.worker())
        await wechat.dispatch_reply(_mk_msg("first"))
        await run_started.wait()
        await wechat.dispatch_reply(_mk_msg("second"))
        await wechat.dispatch_reply(_mk_msg("third"))
        await _drive(task, tick=0.1)

    asyncio.run(body())

    assert drained == ["second", "third"]


def test_greedy_batch_merges_same_user_messages(monkeypatch):
    captured: list[list[str]] = []

    async def fake_process(request):
        captured.append(list(request.incoming_messages))
        return _ok_result()

    monkeypatch.setattr(wechat._session_runner, "process", fake_process)

    async def body():
        await wechat.dispatch_reply(_mk_msg("a"))
        await wechat.dispatch_reply(_mk_msg("b"))
        await wechat.dispatch_reply(_mk_msg("c"))

        task = asyncio.create_task(wechat.worker())
        await _drive(task)

    asyncio.run(body())

    assert captured == [["a", "b", "c"]]


def test_active_ctx_cleared_after_run(monkeypatch):
    async def fast_process(request):
        return _ok_result()

    monkeypatch.setattr(wechat._session_runner, "process", fast_process)

    async def body():
        task = asyncio.create_task(wechat.worker())
        await wechat.dispatch_reply(_mk_msg("x"))
        await asyncio.sleep(0.05)
        assert wechat._active_ctx is None
        assert wechat._active_user_id is None
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    asyncio.run(body())


def test_stragglers_in_ctx_inbox_trigger_next_run(monkeypatch):
    run_calls: list[list[str]] = []

    async def fake_process(request):
        run_calls.append(list(request.incoming_messages))
        if len(run_calls) == 1:
            request.ctx.inbox.put_nowait("straggler")
        return _ok_result()

    monkeypatch.setattr(wechat._session_runner, "process", fake_process)

    async def body():
        task = asyncio.create_task(wechat.worker())
        await wechat.dispatch_reply(_mk_msg("hi"))
        await _drive(task, tick=0.1)

    asyncio.run(body())

    assert run_calls == [["hi"], ["straggler"]]


def test_different_user_during_active_run_stays_in_queue(monkeypatch):
    run_started = asyncio.Event()
    run_release = asyncio.Event()

    async def slow_process(request):
        run_started.set()
        await run_release.wait()
        return _ok_result()

    monkeypatch.setattr(wechat._session_runner, "process", slow_process)

    async def body():
        task = asyncio.create_task(wechat.worker())
        await wechat.dispatch_reply(_mk_msg("u1-first", user_id="u1"))
        await run_started.wait()
        await wechat.dispatch_reply(_mk_msg("u2-msg", user_id="u2"))

        assert wechat._active_ctx is not None
        assert wechat._active_user_id == "u1"
        assert wechat._active_ctx.inbox.empty()
        assert wechat._inbox.qsize() == 1
        queued = wechat._inbox.get_nowait()
        assert queued.user_id == "u2"
        assert queued.text == "u2-msg"

        wechat._inbox.put_nowait(queued)
        run_release.set()
        await _drive(task)

    asyncio.run(body())


def test_stale_proactive_trigger_is_dropped_when_real_message_waits(monkeypatch):
    captured: list[list[str]] = []

    async def fake_process(request):
        captured.append(list(request.incoming_messages))
        return _ok_result()

    monkeypatch.setattr(wechat._session_runner, "process", fake_process)

    async def body():
        await wechat._inbox.put(wechat.DispatchItem("u1", "proactive", "tok", True))
        await wechat._inbox.put(wechat.DispatchItem("u1", "real", "tok", False))
        task = asyncio.create_task(wechat.worker())
        await _drive(task, tick=0.1)

    asyncio.run(body())

    assert captured == [["real"]]
