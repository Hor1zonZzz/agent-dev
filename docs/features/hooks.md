# 生命周期 Hooks（已废弃）

旧版 Agent 主循环通过 `Hooks` 在 `on_agent_start` / `on_agent_end` / `on_tool_start` / `on_tool_end` 这些时刻回调。

## 涉及代码

- `core/hooks.py` — 保留旧协议定义，作为历史参考

## 现状

- 主执行链路已改为 `TraceSink` / `TraceRecorder`。
- CLI 控制台输出基于 trace 事件实现。
- WeChat / scheduler / Hermes / memory compression 统一写入 NDJSON trace。
- 新增说明见 [trace-observability.md](trace-observability.md)。
