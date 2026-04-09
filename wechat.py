"""WeChat ClawBot bridge — connects Anna to WeChat via the iLink API.

Prerequisites
~~~~~~~~~~~~~
1. ``uv sync`` to install wechat-clawbot.
2. Run ``python wechat.py setup`` once to scan the QR code and save credentials.
3. Run ``python wechat.py`` to start the long-poll message loop.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
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
from prompts import build
from tools import end_turn, send_message

load_dotenv()

HISTORY_DIR = Path(__file__).parent / "history" / "wechat"

agent = Agent(
    name="anna",
    instructions=lambda _ctx: build(),
    model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
    tools=[send_message, end_turn],
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


def load_history(user_id: str) -> list[dict]:
    path = _history_path(user_id)
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return []


def save_history(user_id: str, messages: list[dict]) -> None:
    HISTORY_DIR.mkdir(parents=True, exist_ok=True)
    path = _history_path(user_id)
    path.write_text(json.dumps(messages, ensure_ascii=False, indent=2), encoding="utf-8")


# ---------------------------------------------------------------------------
# Message dispatch — called by monitor_weixin_provider for each inbound msg
# ---------------------------------------------------------------------------

_hooks = WeChatHooks()


async def dispatch_reply(msg_ctx: WeixinMsgContext) -> None:
    """Handle an inbound WeChat message: run the agent and reply."""
    user_id = msg_ctx.from_user
    text = msg_ctx.body
    if not text or not text.strip():
        return

    logger.info("[wechat] Message from {}: {}", user_id, text[:120])

    # Load per-user conversation history
    messages = load_history(user_id)
    messages.append({"role": "user", "content": text})

    # Build a send_reply callback that sends text back to the WeChat user
    api_opts = WeixinApiOptions(
        base_url=_account.base_url,
        token=_account.token,
        context_token=msg_ctx.context_token,
    )

    async def reply_fn(reply_text: str) -> None:
        await send_message_weixin(to=user_id, text=reply_text, opts=api_opts)

    ctx = AgentContext(send_reply=reply_fn)

    # Run the agent loop
    result = await run(agent, messages, ctx=ctx, hooks=_hooks)

    # Persist history (strip system message added by run())
    save_history(user_id, result.messages[1:])


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

    try:
        await monitor_weixin_provider(opts, stop_event=stop)
    except KeyboardInterrupt:
        stop.set()
        logger.info("[wechat] 已停止。")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "setup":
        asyncio.run(do_qr_login())
    else:
        asyncio.run(main())
