# 时间感知

让 agent 感受到两次对话之间的"沉默"。每次 run 开始前，算出距上次活动的间隔，按自然语言分桶（`[3 天没说话了]`、`[昨天]`、`[几分钟前刚聊过]` 等）prepend 到首条用户消息；<2 分钟视为连续对话不加 hint。hint 只进当前 run 的 LLM 输入，不写入历史。

另外 system prompt 的末尾会注入当天日期（每次 `build()` 刷新），给模型一个粗粒度时间锚。

## 涉及代码

- `core/time_hint.py:14` — `format_gap_hint(delta)` 分桶返回 hint 字符串或 `None`
- `core/memory.py:136` — `_meta_path()` sidecar `.meta.json` 路径
- `core/memory.py:158` — `get_last_activity()` 读 `last_activity_at`
- `core/memory.py:168` — `update_last_activity()` 写 `last_activity_at`
- `prompts/__init__.py:44-46` — system prompt 末尾追加 `Today is YYYY-MM-DD (周X)`

## 调用位置

- `cli.py:75-77` — run 前算 gap、prefix user 消息
- `cli.py:87-91` — run 后还原 clean content、更新 `last_activity_at`
- `wechat.py:154-161` — 同上（只给 batch 首条加 hint）
- `wechat.py:170-174` — run 后还原 + 更新

## 设计要点

- **对比对象**：最后一次任意一方活动时间（`last_activity_at`），不是只看用户消息。避免把 agent 处理耗时误判为沉默。
- **持久化**：sidecar `<history_stem>.meta.json`，跟历史文件同目录。
- **历史保持干净**：hint 是派生信号，写入前 restore 原始 content。避免多轮累积噪音。
- **中途 inbox 消息不加 hint**：它们本来就是快速连发，加了是噪音。
