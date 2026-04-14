"""WeChat dispatch/worker concurrency tests.

Verifies that dispatch_reply routes correctly and the worker handles:
  - idle enqueue
  - non-blocking dispatch during run
  - mid-run interrupt via ctx.inbox
  - greedy batch merge
  - straggler salvage (message landing in ctx.inbox after last LLM turn)

Run:  uv run python -m pytest tests/test_wechat_dispatch.py -v
"""

from __future__ import annotations

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock

import pytest

import wechat
from core.loop import RunResult


def _mk_msg(text: str, user_id: str = "u1", token: str = "tok") -> MagicMock:
    m = MagicMock()
    m.body = text
    m.from_user = user_id
    m.context_token = token
    return m


def _ok_result(input_msgs: list[dict]) -> RunResult:
    return RunResult(
        messages=[{"role": "system", "content": "sys"}] + list(input_msgs),
        final_output="",
        last_tool=None,
    )


@pytest.fixture(autouse=True)
def isolate_module_state(monkeypatch):
    """Reset wechat queues + disable disk/network I/O for each test."""
    monkeypatch.setattr(wechat, "_inbox", asyncio.Queue())
    monkeypatch.setattr(wechat, "_active_ctx", None)

    monkeypatch.setattr(wechat, "load_for_llm", lambda path: ([], None))
    monkeypatch.setattr(wechat, "append_to_history", lambda path, msgs: None)
    monkeypatch.setattr(wechat, "maybe_compress", AsyncMock(return_value=None))
    monkeypatch.setattr(
        wechat, "_build_reply_fn",
        lambda uid, tok: AsyncMock(return_value=None),
    )
    yield


async def _drive(worker_task: asyncio.Task, tick: float = 0.05) -> None:
    """Yield briefly so the worker can make progress, then cancel it."""
    await asyncio.sleep(tick)
    worker_task.cancel()
    try:
        await worker_task
    except (asyncio.CancelledError, Exception):
        pass


# ─────────────────────────── tests ───────────────────────────


def test_dispatch_when_idle_enqueues_to_inbox():
    async def body():
        await wechat.dispatch_reply(_mk_msg("hi"))
        assert wechat._inbox.qsize() == 1
        uid, text, tok, is_proactive = wechat._inbox.get_nowait()
        assert (uid, text, tok, is_proactive) == ("u1", "hi", "tok", False)

    asyncio.run(body())


def test_dispatch_ignores_blank_messages():
    async def body():
        await wechat.dispatch_reply(_mk_msg("   "))
        await wechat.dispatch_reply(_mk_msg(""))
        assert wechat._inbox.empty()

    asyncio.run(body())


def test_worker_consumes_queued_message(monkeypatch):
    captured: list[list[dict]] = []

    async def fake_run(agent, input_msgs, *, ctx, hooks=None):
        captured.append(list(input_msgs))
        return _ok_result(input_msgs)

    monkeypatch.setattr(wechat, "run", fake_run)

    async def body():
        task = asyncio.create_task(wechat.worker())
        await wechat.dispatch_reply(_mk_msg("hello"))
        await _drive(task)

    asyncio.run(body())

    assert captured == [[{"role": "user", "content": "hello"}]]


def test_dispatch_is_non_blocking_during_run(monkeypatch):
    """While run() is in flight, dispatch_reply must return near-instantly."""
    run_started = asyncio.Event()
    run_release = asyncio.Event()

    async def slow_run(agent, input_msgs, *, ctx, hooks=None):
        run_started.set()
        await run_release.wait()
        return _ok_result(input_msgs)

    monkeypatch.setattr(wechat, "run", slow_run)

    async def body():
        task = asyncio.create_task(wechat.worker())
        await wechat.dispatch_reply(_mk_msg("first"))
        await run_started.wait()  # run is now in-flight

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
    """Messages arriving during run() must land in ctx.inbox in arrival order."""
    run_started = asyncio.Event()
    drained: list[str] = []

    async def fake_run(agent, input_msgs, *, ctx, hooks=None):
        run_started.set()
        # Let dispatches happen, then drain the inbox like loop.py would.
        await asyncio.sleep(0.03)
        while not ctx.inbox.empty():
            drained.append(ctx.inbox.get_nowait())
        return _ok_result(input_msgs)

    monkeypatch.setattr(wechat, "run", fake_run)

    async def body():
        task = asyncio.create_task(wechat.worker())
        await wechat.dispatch_reply(_mk_msg("first"))
        await run_started.wait()
        await wechat.dispatch_reply(_mk_msg("second"))
        await wechat.dispatch_reply(_mk_msg("third"))
        await _drive(task, tick=0.1)

    asyncio.run(body())

    assert drained == ["second", "third"]


def test_greedy_batch_merges_queued_messages(monkeypatch):
    """Messages queued before worker starts must collapse into one run."""
    captured: list[list[dict]] = []

    async def fake_run(agent, input_msgs, *, ctx, hooks=None):
        captured.append(list(input_msgs))
        return _ok_result(input_msgs)

    monkeypatch.setattr(wechat, "run", fake_run)

    async def body():
        # Pre-fill the inbox before worker starts.
        await wechat.dispatch_reply(_mk_msg("a"))
        await wechat.dispatch_reply(_mk_msg("b"))
        await wechat.dispatch_reply(_mk_msg("c"))

        task = asyncio.create_task(wechat.worker())
        await _drive(task)

    asyncio.run(body())

    assert len(captured) == 1, f"expected 1 run, got {len(captured)}"
    assert captured[0] == [
        {"role": "user", "content": "a"},
        {"role": "user", "content": "b"},
        {"role": "user", "content": "c"},
    ]


def test_active_ctx_cleared_after_run(monkeypatch):
    async def fast_run(agent, input_msgs, *, ctx, hooks=None):
        return _ok_result(input_msgs)

    monkeypatch.setattr(wechat, "run", fast_run)

    async def body():
        task = asyncio.create_task(wechat.worker())
        await wechat.dispatch_reply(_mk_msg("x"))
        await asyncio.sleep(0.05)
        assert wechat._active_ctx is None
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    asyncio.run(body())


def test_stragglers_in_ctx_inbox_trigger_next_run(monkeypatch):
    """If a message lands in ctx.inbox after the last LLM turn (i.e., run
    returned without draining it), the worker must salvage + re-run."""
    run_calls: list[list[dict]] = []

    async def fake_run(agent, input_msgs, *, ctx, hooks=None):
        run_calls.append(list(input_msgs))
        if len(run_calls) == 1:
            # Simulate a straggler: put into ctx.inbox just before returning.
            ctx.inbox.put_nowait("straggler")
        return _ok_result(input_msgs)

    monkeypatch.setattr(wechat, "run", fake_run)

    async def body():
        task = asyncio.create_task(wechat.worker())
        await wechat.dispatch_reply(_mk_msg("hi"))
        await _drive(task, tick=0.1)

    asyncio.run(body())

    assert len(run_calls) == 2
    assert run_calls[0] == [{"role": "user", "content": "hi"}]
    assert run_calls[1] == [{"role": "user", "content": "straggler"}]


def test_history_appended_before_active_ctx_cleared(monkeypatch):
    """Regression: append_to_history must run before _active_ctx = None, so
    any straggler sees the persisted history on its next load."""
    order: list[str] = []

    async def fake_run(agent, input_msgs, *, ctx, hooks=None):
        return _ok_result(input_msgs)

    def fake_append(path, msgs):
        order.append("append")
        # At this moment, worker is still inside the try block → _active_ctx set
        assert wechat._active_ctx is not None, "_active_ctx cleared too early"

    monkeypatch.setattr(wechat, "run", fake_run)
    monkeypatch.setattr(wechat, "append_to_history", fake_append)

    async def body():
        task = asyncio.create_task(wechat.worker())
        await wechat.dispatch_reply(_mk_msg("x"))
        await _drive(task)

    asyncio.run(body())

    assert order == ["append"]
