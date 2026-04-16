# Agent 主循环

LLM ↔ 工具调用循环：系统消息拼装、多轮 `tool_calls`、`stop_at` 终止条件、`max_turns` 保护、`reasoning_content` 截断预览、mid-run inbox 注入点，以及统一 trace 事件输出。

## 涉及代码

- `core/loop.py` — `Agent` / `RunResult` / `run()`
- `core/context.py` — `AgentContext`（`inbox` / `send_reply` / `memory` / `trace_recorder`）
- `core/trace.py` — `RunMeta` / `TraceRecorder`

## 关键事件

- `run.started` / `run.finished` / `run.failed`
- `turn.started`
- `inbox.drained`
- `llm.requested` / `llm.responded`
- `tool.started` / `tool.finished`
- `run.max_turns_hit`
