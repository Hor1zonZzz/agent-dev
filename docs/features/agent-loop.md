# Agent 主循环

LLM ↔ 工具调用循环：系统消息拼装、多轮 tool_calls、`stop_at` 终止条件、`max_turns` 保护、`reasoning_content` 裁剪、mid-run inbox 注入点。

## 涉及代码

- `core/loop.py:24-31` — `Agent` dataclass
- `core/loop.py:34-38` — `RunResult` dataclass
- `core/loop.py:41-140` — `run()` 主循环
  - `core/loop.py:54-58` — `reasoning_content` 裁剪
  - `core/loop.py:71-82` — inbox 注入点（每轮 LLM call 前）
  - `core/loop.py:96-99` — 无 tool_calls 时终止
  - `core/loop.py:131-134` — `stop_at` 终止判定
- `core/context.py:10-15` — `AgentContext`（inbox / send_reply / memory）
