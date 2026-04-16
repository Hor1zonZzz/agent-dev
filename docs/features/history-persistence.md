# 对话历史持久化

每轮 chat run 完成后把新增 messages append 到 JSON 文件；启动新 run 时读取最近 K 条。全量 history 永不截断。history JSON、sidecar meta、memory summary 现在分别由不同模块负责。

## 涉及代码

- `core/history.py` — `load_recent_messages()` / `append_to_history()`
- `core/meta.py` — `last_activity_at` / `last_anna_message_at` / `next_proactive_at` / `dispatch_info`
- `core/memory.py` — `load_latest_summary()` / `load_for_llm()` 兼容入口
- `core/session.py` — 统一编排 load / append / meta 更新 / compression 触发

## 存储位置

- `cli.py:18` — CLI：`history/cli.json`
- `wechat.py:39, 72-74` — 微信：`history/wechat/<user_id>.json`

## 调用位置

- `core/session.py` — CLI / WeChat 共用同一套会话编排
