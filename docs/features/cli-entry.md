# CLI 入口

终端交互式 REPL，用于本地测试 agent loop。

## 涉及代码

- `cli.py:16` — `load_dotenv()`
- `cli.py:18` — history 路径
- `cli.py:20-26` — Agent 装配（`send_message` + `end_turn`，`stop_at={"end_turn"}`）
- `cli.py:29-41` — `CLIHooks`（见 [hooks.md](hooks.md)）
- `cli.py:45-46` — `_print_reply()` 作为 `ctx.send_reply`
- `cli.py:49-81` — `main()` REPL 循环
- `cli.py:84-85` — `__main__` 启动

## 启动

```bash
uv run python cli.py
```
