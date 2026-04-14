# 生命周期 Hooks

Agent 主循环在以下时刻回调：`on_agent_start` / `on_agent_end` / `on_tool_start` / `on_tool_end`。

## 涉及代码

- `core/hooks.py:13-19` — `Hooks` Protocol 定义（具体实现由各 host 各自提供）

## 在主循环中的触发点

- `core/loop.py:65-66` — `on_agent_start`
- `core/loop.py:115-116` — `on_tool_start`（工具执行前）
- `core/loop.py:120-121` — `on_tool_end`（工具执行后）
- `core/loop.py:138-139` — `on_agent_end`

## 入口处的具体实现

- `cli.py:29-41` — `CLIHooks`（工具名 + 参数 + 结果打印到 stdout）
- `wechat.py:54-65` — `WeChatHooks`（loguru 结构化日志）
