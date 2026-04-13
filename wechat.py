"""WeChat ClawBot bridge — connects Anna to WeChat via the iLink API.

Prerequisites
~~~~~~~~~~~~~
1. ``uv sync`` to install wechat-clawbot.
2. Run ``python wechat.py setup`` once to scan the QR code and save credentials.
3. Run ``python wechat.py`` to start the long-poll message loop.
"""

from __future__ import annotations

import asyncio
import os
import sys
from datetime import datetime
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
from core.loop import Agent, run
from core.memory import (
    append_to_history,
    get_last_activity,
    load_for_llm,
    maybe_compress,
    update_dispatch_info,
    update_last_activity,
    update_last_anna_message,
    update_next_proactive_at,
)
from core.proactive import compute_next_proactive, proactive_loop
from core.time_hint import format_gap_hint
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


# ---------------------------------------------------------------------------
# Hooks
# ---------------------------------------------------------------------------

class WeChatHooks:
    async def on_agent_start(self, agent_name, ctx):
        logger.info("[wechat] Agent START | {}", agent_name)

    async def on_agent_end(self, agent_name, output, ctx):
        logger.info("[wechat] Agent END | {}", agent_name)

    async def on_tool_start(self, agent_name, tool, args, ctx):
        logger.debug("[wechat] Tool START | {}.{}", agent_name, tool.name)

    async def on_tool_end(self, agent_name, tool, result, ctx):
        logger.debug("[wechat] Tool END | {}.{}", agent_name, tool.name)


# ---------------------------------------------------------------------------
# Per-user conversation history
# ---------------------------------------------------------------------------

def _history_path(user_id: str) -> Path:
    safe = user_id.replace("/", "_").replace("@", "_")
    return HISTORY_DIR / f"{safe}.json"


# ---------------------------------------------------------------------------
# Message dispatch — non-blocking router + single-worker consumer
#
# dispatch_reply is called by the monitor's for-loop (awaited), so it MUST
# return quickly. It only routes the text into one of two queues:
#
#   - _active_ctx.inbox   → when a run is in progress (mid-run interrupt)
#   - _inbox              → when idle (worker picks it up)
#
# The long-running worker coroutine owns the agent run, history I/O, and
# memory compression. One worker = one-user-at-a-time serialization.
# ---------------------------------------------------------------------------

_hooks = WeChatHooks()

# Inbox tuple: (user_id, text, context_token, is_proactive)
# is_proactive=True items are synthetic system triggers — gap_hint is skipped
# and the synthetic user message is stripped from persisted history.
_inbox: asyncio.Queue[tuple[str, str, str | None, bool]] = asyncio.Queue()
_active_ctx: AgentContext | None = None


async def dispatch_reply(msg_ctx: WeixinMsgContext) -> None:
    """Route an inbound message. Returns immediately (no agent work here)."""
    text = (msg_ctx.body or "").strip()
    if not text:
        return

    user_id = msg_ctx.from_user
    logger.info("[wechat] Message from {}: {}", user_id, text[:120])

    # Persist dispatch info on every inbound so the proactive loop can
    # send messages even after a long quiet period.
    update_dispatch_info(_history_path(user_id), user_id, msg_ctx.context_token)

    if _active_ctx is not None:
        _active_ctx.inbox.put_nowait(text)
        logger.info("[wechat] → 注入运行中 inbox")
    else:
        _inbox.put_nowait((user_id, text, msg_ctx.context_token, False))
        logger.info("[wechat] → 入队等待 worker")


async def enqueue_proactive(user_id: str, text: str, _is_proactive: bool = True) -> None:
    """Called by the proactive loop to inject a synthetic trigger."""
    # Reuse the most recent context_token from meta (saved on each user message).
    from core.memory import get_dispatch_info
    _, ctx_token = get_dispatch_info(_history_path(user_id))
    _inbox.put_nowait((user_id, text, ctx_token, True))


def _build_reply_fn(user_id: str, context_token: str | None):
    api_opts = WeixinApiOptions(
        base_url=_account.base_url,
        token=_account.token,
        context_token=context_token,
    )

    async def reply_fn(reply_text: str) -> None:
        await send_message_weixin(to=user_id, text=reply_text, opts=api_opts)

    return reply_fn


async def worker() -> None:
    """Consume messages one turn at a time.

    The outer try/except keeps the worker alive across per-iteration failures
    (bad history, LLM 4xx, network blips). Without it, a single unhandled
    exception would kill the task silently — it's never awaited — and subsequent
    messages would queue forever with no response.
    """
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
    global _active_ctx

    user_id, first_text, ctx_token, is_proactive = await _inbox.get()

    # Greedily batch any messages already queued (zero-delay merge).
    # A proactive trigger is consumed alone — if real user messages are also
    # queued for this user, the trigger is dropped (the user just spoke, no
    # need to nudge them).
    batch_texts = [first_text]
    if not is_proactive:
        while not _inbox.empty():
            other_uid, other_text, other_token, other_proactive = _inbox.get_nowait()
            if other_proactive:
                continue  # skip stale proactive triggers when real user is talking
            batch_texts.append(other_text)
            ctx_token = other_token or ctx_token  # keep freshest token

    history_path = _history_path(user_id)
    recent, memory_text = load_for_llm(history_path)

    # Gap hint: compare now to last_activity_at; prepend only to the first
    # message of this batch. Skipped for proactive triggers — the synthetic
    # message already encodes time context and a hint would be redundant.
    gap_hint: str | None = None
    if not is_proactive:
        last_activity = get_last_activity(history_path)
        gap_hint = format_gap_hint(datetime.now() - last_activity) if last_activity else None

    for i, t in enumerate(batch_texts):
        content = f"{gap_hint}\n{t}" if (i == 0 and gap_hint) else t
        recent.append({"role": "user", "content": content})
    n_from_disk = len(recent) - len(batch_texts)

    ctx = AgentContext(
        send_reply=_build_reply_fn(user_id, ctx_token),
        memory=memory_text,
    )
    _active_ctx = ctx
    try:
        result = await run(agent, recent, ctx=ctx, hooks=_hooks)
        new_this_turn = result.messages[1 + n_from_disk:]
        if is_proactive and new_this_turn and new_this_turn[0].get("role") == "user":
            # Synthetic trigger should not appear in history at all.
            new_this_turn = new_this_turn[1:]
        elif gap_hint and new_this_turn and new_this_turn[0].get("role") == "user":
            # Strip gap hint from persisted history — it's a per-run annotation.
            new_this_turn[0] = {**new_this_turn[0], "content": batch_texts[0]}
        append_to_history(history_path, new_this_turn)
        if not is_proactive:
            update_last_activity(history_path)
        now = datetime.now()
        update_last_anna_message(history_path, now)
        update_next_proactive_at(history_path, compute_next_proactive(now))
    finally:
        # IMPORTANT: history is written BEFORE clearing _active_ctx, so
        # any message that slipped into ctx.inbox during append_to_history
        # will find a fully-persisted history when the next run loads it.
        _active_ctx = None

    # Salvage mid-run stragglers (put into ctx.inbox between last turn's
    # inbox-drain and _active_ctx = None) back onto the global queue.
    while not ctx.inbox.empty():
        leftover = ctx.inbox.get_nowait()
        if leftover is not None:
            _inbox.put_nowait((user_id, leftover, ctx_token, False))

    await maybe_compress(history_path)


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------

_account: AccountData  # set in main()


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
        log=lambda m: logger.info("[monitor] {}", m),
        err_log=lambda m: logger.error("[monitor] {}", m),
        dispatch_reply=dispatch_reply,
    )

    logger.info("[wechat] 启动消息监听 (Ctrl+C 退出)...")

    worker_task = asyncio.create_task(worker(), name="anna-worker")
    proactive_task = asyncio.create_task(
        proactive_loop(HISTORY_DIR, enqueue_proactive),
        name="anna-proactive",
    )
    cron_task = start_hermes_cron()

    try:
        await monitor_weixin_provider(opts, stop_event=stop)
    except KeyboardInterrupt:
        stop.set()
        logger.info("[wechat] 已停止。")
    finally:
        for task in (worker_task, proactive_task, cron_task):
            task.cancel()
        for task in (worker_task, proactive_task, cron_task):
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "setup":
        asyncio.run(do_qr_login())
    else:
        asyncio.run(main())
