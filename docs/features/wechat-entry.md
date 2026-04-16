# 微信 ClawBot 入口

通过 `wechat-clawbot` SDK 对接微信 iLink，长轮询拉消息、发回复。会话编排委托给 `ChatSessionRunner`，入口层只保留 dispatch / batching / proactive / worker 生命周期。

## 涉及代码

- `wechat.py` — transport / queue / worker / proactive 接线
- `core/session.py` — `ChatSessionRunner`
- `core/trace.py` — `dispatch.enqueued` / `dispatch.injected` / `dispatch.batched` / `dispatch.salvaged`
- `core/meta.py` — dispatch sidecar 信息

## 启动

```bash
uv run python wechat.py setup   # 首次扫码
uv run python wechat.py          # 启动监听
```

## 并发模型

见 [concurrent-dispatch.md](concurrent-dispatch.md)。

## 相关功能

- Trace 可观测性：[trace-observability.md](trace-observability.md)
