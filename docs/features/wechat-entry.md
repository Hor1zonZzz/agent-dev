# 微信 ClawBot 入口

通过 `wechat-clawbot` SDK 对接微信 iLink，长轮询拉消息、发回复。

## 涉及代码

- `wechat.py:50` — `load_dotenv()`
- `wechat.py:52` — history 目录（`history/wechat/`）
- `wechat.py:54-60` — Agent 装配（`send_message + recall_day + end_turn`，`stop_at={"end_turn"}`）
- `wechat.py:67-78` — `WeChatHooks`（见 [hooks.md](hooks.md)）
- `wechat.py:85-87` — `_history_path(user_id)` 每用户独立 JSON
- `wechat.py:141-151` — `_build_reply_fn()` 绑定回复回调
- `wechat.py:251-296` — `main()` 启动 monitor + worker + proactive + hermes-cron
- `wechat.py:298-302` — 登录 / 监听模式切换

## 启动

```bash
uv run python wechat.py setup   # 首次扫码
uv run python wechat.py          # 启动监听
```

## 并发模型

见 [concurrent-dispatch.md](concurrent-dispatch.md)。
