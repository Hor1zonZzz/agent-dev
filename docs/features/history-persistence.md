# 对话历史持久化

每轮 run 完成后把新增 messages append 到 JSON 文件；启动新 run 时读取最近 K 条。全量 history 永不截断。

## 涉及代码

- `core/memory.py:115-130` — `load_for_llm()` 读最近窗口 + memory 摘要
- `core/memory.py:133-142` — `append_to_history()` 追加写盘
- `core/memory.py:20` — `RECENT_K` 窗口大小（默认 40）

## 存储位置

- `cli.py:18` — CLI：`history/cli.json`
- `wechat.py:39, 72-74` — 微信：`history/wechat/<user_id>.json`

## 调用位置

- `cli.py:64, 73` — CLI 每轮 load / append
- `wechat.py:141-143, 154` — worker 每轮 load / append
