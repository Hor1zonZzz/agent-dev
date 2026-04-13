# Hermes（Anna 的手）

把 NousResearch 的 Hermes Agent 作为 Python 依赖接入，定时执行信息摄入类任务（查天气、看新闻、刷 HN 等），以 **Anna 第一人称** 写入 `history/diary/YYYY-MM-DD.md`。Anna 侧读取日记得到"今天做了什么"的真实事实，避免编造。

## 涉及代码

- `hermes/diary.py:18` — `append_entry(title, content)` atomic 写入今日日记（tmp + os.replace）
- `hermes/prompt.py` — 给 Hermes 的 system prompt（强制 Anna 第一人称 + 输出格式约束）
- `hermes/tasks.py` — 各时段任务定义（`morning` / `noon` / `evening` → list of `(title, instruction)`）
- `hermes/runner.py:34` — `run_slot(slot)` 主流程：每任务起新 `AIAgent` → `chat(instruction)` → `append_entry`
- `hermes/runner.py:57` — CLI 入口：`python -m hermes.runner <slot>`

## 调度

由 crontab 触发（Hermes Python SDK 本身是同步、一次性调用）：

```
0 8  * * * cd /Users/wangyilin/python-project/agent-dev && uv run python -m hermes.runner morning
0 12 * * * cd /Users/wangyilin/python-project/agent-dev && uv run python -m hermes.runner noon
0 21 * * * cd /Users/wangyilin/python-project/agent-dev && uv run python -m hermes.runner evening
```

## 设计要点

- **共享 `~/.hermes/`**：默认不覆盖 `HERMES_*` 配置，和用户日常 Hermes CLI 共享 episodic memory / skills。好处是 Anna 的 hermes 能复用用户积累的技能；代价是并发访问时要注意文件锁。
- **一任务一 agent 实例**：Hermes 文档明确说 `AIAgent` 不是线程/任务安全的，每个任务 `new AIAgent(...)`。
- **单向通信**：Hermes 只写 `history/diary/`，不读。Anna 只读，不写。两边靠文件系统解耦。
- **失败不中断**：单个任务异常会 log + 写一条"这件事没能做成"占位，其他任务继续跑。
- **模型优先级**：`HERMES_MODEL` > `OPENAI_MODEL`（和 Anna 共用） > `deepseek-chat` 硬 fallback。信息摄入类任务用 `deepseek-chat` 比 `deepseek-reasoner` 便宜/快很多，如果要省钱建议 `.env` 加 `HERMES_MODEL=deepseek-chat`。
- **toolset 只开 browser**：Hermes 有 20 个 toolset，我们只启用 `browser`（内置 chromium，不需要额外 API key）。注意不是 `web` —— `web` toolset 需要 Tavily/Exa/Firecrawl 等付费 key，否则会静默过滤成零工具，LLM 就只能脑补。
- **命名空间隔离**：Hermes 的 PyPI 包在 site-packages 根目录有个叫 `tools/` 的包，会和我们项目根的 `tools/` 撞车。所以我们自己的 tools 迁到了 `core/tools/`。
