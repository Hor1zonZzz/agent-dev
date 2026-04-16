# CLI 入口

终端交互式 REPL，用于本地测试 agent loop。现在由共享的 `ChatSessionRunner` 负责 history / meta / memory compression / trace，CLI 自己只保留 transport 和控制台展示。

## 涉及代码

- `cli.py` — REPL 入口、Agent 装配、`ConsoleTraceSink`
- `core/session.py` — `ChatSessionRunner`
- `core/trace.py` — 默认 NDJSON sink + CLI fanout sink

## 启动

```bash
uv run python cli.py
```

## 相关功能

- 时间感知（gap hint 注入）：[time-awareness.md](time-awareness.md)
- Memory 压缩：[memory-compression.md](memory-compression.md)
- Trace 可观测性：[trace-observability.md](trace-observability.md)
