# CLI 入口

终端交互式 REPL，用于本地测试 agent loop。

## 涉及代码

- `cli.py:24` — `load_dotenv()`
- `cli.py:26` — history 路径（`history/cli.json`）
- `cli.py:28-34` — Agent 装配（`send_message + recall_day + end_turn`，`stop_at={"end_turn"}`）
- `cli.py:37-49` — `CLIHooks`（见 [hooks.md](hooks.md)）
- `cli.py:53-54` — `_print_reply()` 作为 `ctx.send_reply`
- `cli.py:57-99` — `main()` REPL 循环
  - `cli.py:72` — load history + memory
  - `cli.py:75-77` — 算 gap hint，prefix 当前用户消息
  - `cli.py:83` — 跑 agent
  - `cli.py:87-90` — 还原 clean content + 写 history
  - `cli.py:91` — 更新 `last_activity_at`
  - `cli.py:99` — 触发后台 memory 压缩
- `cli.py:102-103` — `__main__` 启动

## 启动

```bash
uv run python cli.py
```

## 相关功能

- 时间感知（gap hint 注入）：[time-awareness.md](time-awareness.md)
- Memory 压缩：[memory-compression.md](memory-compression.md)
