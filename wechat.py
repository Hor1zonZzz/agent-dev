"""WeChat ClawBot bridge — connects Anna to WeChat via the iLink API."""

from __future__ import annotations

import asyncio
import os
import sys
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv
from loguru import logger
from wechat_clawbot.api.client import WeixinApiOptions
from wechat_clawbot.auth.accounts import DEFAULT_BASE_URL, CDN_BASE_URL
from wechat_clawbot.claude_channel.credentials import (
    AccountData,
    load_credentials,
)
from wechat_clawbot.claude_channel.setup import do_qr_login
from wechat_clawbot.messaging.inbound import WeixinMsgContext
from wechat_clawbot.messaging.send import send_message_weixin
from wechat_clawbot.monitor.monitor import MonitorOpts, monitor_weixin_provider

from core.context import AgentContext
from core.loop import Agent
from core.memory import compression_watchdog
from core.meta import get_dispatch_info, update_dispatch_info
from core.proactive import proactive_loop
from core.session import ChatSessionRequest, ChatSessionRunner
from core.trace import RunMeta, TraceRecorder, get_default_trace_sink, truncate_preview
from hermes.scheduler import start as start_hermes_cron
from prompts import build
from core.tools import end_turn, recall_day, send_message

load_dotenv()

HISTORY_DIR = Path(__file__).parent / "history" / "wechat"

agent = Agent(
    name="anna",
    instructions=lambda ctx: build(memory=ctx.memory if ctx else None),
    model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
    tools=[send_message, recall_day, end_turn],
    stop_at={"end_turn"},
)

_trace_sink = get_default_trace_sink()
_session_runner = ChatSessionRunner(agent, trace_sink=_trace_sink)


@dataclass(frozen=True)
class DispatchItem:
    user_id: str
    text: str
    context_token: str | None
    is_proactive: bool = False


def _history_path(user_id: str) -> Path:
    safe = user_id.replace("/", "_").replace("@", "_")
    return HISTORY_DIR / f"{safe}.json"


_inbox: asyncio.Queue[DispatchItem] = asyncio.Queue()
_active_ctx: AgentContext | None = None
_active_user_id: str | None = None


async def dispatch_reply(msg_ctx: WeixinMsgContext) -> None:
    """Route an inbound message. Returns immediately (no agent work here)."""
    global _active_user_id

    text = (msg_ctx.body or "").strip()
    if not text:
        return

    user_id = msg_ctx.from_user
    logger.info("[wechat] Message from {}: {}", user_id, text[:120])

    update_dispatch_info(_history_path(user_id), user_id, msg_ctx.context_token)

    if _active_ctx is not None and _active_user_id == user_id:
        _active_ctx.inbox.put_nowait(text)
        if _active_ctx.trace_recorder is not None:
            await _active_ctx.trace_recorder.emit(
                lane="dispatch",
                type="dispatch.injected",
                status="ok",
                summary="wechat message injected into active run",
                payload={
                    "preview": truncate_preview(text),
                    "inbox_size": _active_ctx.inbox.qsize(),
                },
            )
        logger.info("[wechat] → 注入运行中 inbox")
        return

    _inbox.put_nowait(
        DispatchItem(
            user_id=user_id,
            text=text,
            context_token=msg_ctx.context_token,
            is_proactive=False,
        )
    )
    logger.info("[wechat] → 入队等待 worker")


async def enqueue_proactive(user_id: str, text: str, _is_proactive: bool = True) -> None:
    _, ctx_token = get_dispatch_info(_history_path(user_id))
    _inbox.put_nowait(DispatchItem(user_id=user_id, text=text, context_token=ctx_token, is_proactive=True))


def _build_reply_fn(user_id: str, context_token: str | None):
    api_opts = WeixinApiOptions(
        base_url=_account.base_url,
        token=_account.token,
        context_token=context_token,
    )

    async def reply_fn(reply_text: str) -> None:
        await send_message_weixin(to=user_id, text=reply_text, opts=api_opts)

    return reply_fn


def _requeue(items: list[DispatchItem]) -> None:
    for item in items:
        _inbox.put_nowait(item)


async def worker() -> None:
    global _active_ctx

    while True:
        try:
            await _run_one_iteration()
        except asyncio.CancelledError:
            raise
        except Exception:
            _active_ctx = None
            logger.exception("[wechat] Worker iteration failed; continuing")


async def _run_one_iteration() -> None:
    global _active_ctx, _active_user_id

    first = await _inbox.get()
    user_id = first.user_id
    ctx_token = first.context_token

    if first.is_proactive:
        leftovers: list[DispatchItem] = []
        same_user_real: list[DispatchItem] = []
        while not _inbox.empty():
            other = _inbox.get_nowait()
            if other.user_id == user_id and not other.is_proactive:
                same_user_real.append(other)
            else:
                leftovers.append(other)
        if same_user_real:
            _requeue(same_user_real + leftovers)
            logger.info("[wechat] 丢弃过期 proactive trigger: {}", user_id)
            return
        _requeue(leftovers)

    batch_items = [first]
    held_back: list[DispatchItem] = []
    if not first.is_proactive:
        while not _inbox.empty():
            other = _inbox.get_nowait()
            if other.user_id != user_id:
                held_back.append(other)
                continue
            if other.is_proactive:
                continue
            batch_items.append(other)
            ctx_token = other.context_token or ctx_token
        _requeue(held_back)

    history_path = _history_path(user_id)
    run_kind = "wechat_proactive" if first.is_proactive else "wechat_chat"
    recorder = TraceRecorder(
        _trace_sink,
        RunMeta(
            run_kind=run_kind,
            source="wechat",
            session_id=user_id,
            user_id=user_id,
            context={"history_path": str(history_path), "transport": "wechat"},
        ),
    )
    await recorder.emit(
        lane="dispatch",
        type="dispatch.enqueued",
        status="ok",
        summary="wechat batch dequeued",
        payload={
            "message_count": len(batch_items),
            "first_preview": truncate_preview(first.text),
        },
    )
    if len(batch_items) > 1:
        await recorder.emit(
            lane="dispatch",
            type="dispatch.batched",
            status="ok",
            summary=f"batched {len(batch_items)} messages",
            payload={
                "message_count": len(batch_items),
                "previews": [truncate_preview(item.text) for item in batch_items],
            },
        )

    ctx = AgentContext(
        send_reply=_build_reply_fn(user_id, ctx_token),
        trace_recorder=recorder,
    )
    _active_ctx = ctx
    _active_user_id = user_id
    result = None
    try:
        result = await _session_runner.process(
            ChatSessionRequest(
                history_path=history_path,
                incoming_messages=[item.text for item in batch_items],
                send_reply=ctx.send_reply,
                source="wechat",
                run_kind=run_kind,
                ctx=ctx,
                run_id=recorder.run_id,
                start_seq=recorder.seq,
                session_id=user_id,
                user_id=user_id,
                is_proactive=first.is_proactive,
                context={
                    "transport": "wechat",
                    "context_token_present": ctx_token is not None,
                },
            )
        )
        recorder.sync(result.trace_seq)
    finally:
        _active_ctx = None
        _active_user_id = None

    salvaged: list[str] = []
    while not ctx.inbox.empty():
        leftover = ctx.inbox.get_nowait()
        if leftover is not None:
            salvaged.append(leftover)
            _inbox.put_nowait(
                DispatchItem(
                    user_id=user_id,
                    text=leftover,
                    context_token=ctx_token,
                    is_proactive=False,
                )
            )

    if salvaged:
        await recorder.emit(
            lane="dispatch",
            type="dispatch.salvaged",
            status="ok",
            summary=f"salvaged {len(salvaged)} straggler(s)",
            payload={"previews": [truncate_preview(item) for item in salvaged]},
        )


_account: AccountData


async def main() -> None:
    global _account

    creds = load_credentials()
    if creds is None:
        logger.error("未找到微信凭据。请先运行: python wechat.py setup")
        sys.exit(1)

    _account = creds
    logger.info("[wechat] 账号: {} ({})", _account.account_id, _account.user_id)

    stop = asyncio.Event()

    opts = MonitorOpts(
        base_url=_account.base_url or DEFAULT_BASE_URL,
        cdn_base_url=CDN_BASE_URL,
        token=_account.token,
        account_id=_account.account_id,
        log=lambda message: logger.info("[monitor] {}", message),
        err_log=lambda message: logger.error("[monitor] {}", message),
        dispatch_reply=dispatch_reply,
    )

    logger.info("[wechat] 启动消息监听 (Ctrl+C 退出)...")

    worker_task = asyncio.create_task(worker(), name="anna-worker")
    proactive_task = asyncio.create_task(
        proactive_loop(HISTORY_DIR, enqueue_proactive),
        name="anna-proactive",
    )
    cron_task = start_hermes_cron()
    compress_task = asyncio.create_task(
        compression_watchdog(HISTORY_DIR, trace_sink=_trace_sink),
        name="anna-compress-watchdog",
    )

    try:
        await monitor_weixin_provider(opts, stop_event=stop)
    except KeyboardInterrupt:
        stop.set()
        logger.info("[wechat] 已停止。")
    finally:
        for task in (worker_task, proactive_task, cron_task, compress_task):
            task.cancel()
        for task in (worker_task, proactive_task, cron_task, compress_task):
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "setup":
        asyncio.run(do_qr_login())
    else:
        asyncio.run(main())
