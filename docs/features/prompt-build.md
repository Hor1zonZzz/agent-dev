# Prompt 组装

把 `prompts/` 下的 markdown 片段（soul / guidelines / mood / user_profile）拼成 system prompt，并按需注入运行时片段（长期记忆摘要、今日日记、当前日期）。每次 `run()` 开始时由 `agent.instructions` lambda 调用，所以**每轮对话都重新构建一次**——意味着日记、日期等动态内容能实时刷新。

## 涉及代码

- `prompts/__init__.py:13-17` — `_read()` 读取 md 片段
- `prompts/__init__.py:20-62` — `build(memory=...)` 主入口
- `prompts/soul.md` — Anna 人设
- `prompts/guidelines.md` — 行为准则（含"Grounded activity"反编造规则）
- `prompts/mood.md` — 情绪状态模板
- `prompts/user_profile.md` — 用户画像模板

## 注入的 7 个片段（按顺序）

| 段落 | 来源 | 何时出现 |
|---|---|---|
| 1. soul | `soul.md` | 总是 |
| 2. guidelines | `guidelines.md` | 总是 |
| 3. user profile | `user_profile.md` | 总是 |
| 4. mood | `mood.md` | 总是 |
| 5. `## Long-term memory` | 调用方 `ctx.memory` | 仅当传入 |
| 6. `## 我今天做了这些` | `core/diary.read_today()` | 总是出现（无内容时插入"还没记录"占位 + 反编造提示） |
| 7. `## Current date` | `datetime.now()` | 总是；格式 `YYYY-MM-DD (Weekday)` |

## 调用位置

- `cli.py:30` — CLI 启动时作为 `agent.instructions` lambda
- `wechat.py:51` — 微信启动时作为 `agent.instructions` lambda

## 相关功能

- 日记注入：[diary.md](diary.md)
- 长期记忆：[memory-compression.md](memory-compression.md)
- 时间感知：[time-awareness.md](time-awareness.md)
