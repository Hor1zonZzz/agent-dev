# 微信 ClawBot 入口

通过 `wechat-clawbot` SDK 对接微信 iLink，长轮询拉消息、发回复。

## 涉及代码

- `wechat.py:37` — `load_dotenv()`
- `wechat.py:39` — history 目录（`history/wechat/`）
- `wechat.py:41-47` — Agent 装配
- `wechat.py:54-65` — `WeChatHooks`（见 [hooks.md](hooks.md)）
- `wechat.py:72-74` — `_history_path(user_id)` 每用户独立 JSON
- `wechat.py:113-123` — `_build_reply_fn()` 绑定回复回调
- `wechat.py:178-198` — `main()` 启动 monitor + worker
- `wechat.py:200-205` — 登录 / 监听模式切换

## 启动

```bash
uv run python wechat.py setup   # 首次扫码
uv run python wechat.py          # 启动监听
```

## 并发模型

见 [concurrent-dispatch.md](concurrent-dispatch.md)。
