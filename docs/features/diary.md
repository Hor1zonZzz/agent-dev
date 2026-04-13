# 日记（Diary）

让 Anna 基于真实发生的事聊天，而不是编造"今天做了什么"。"手"（Hermes，后续实现）每天往 `history/diary/YYYY-MM-DD.md` 写活动记录，"心"（Anna）读取今日日记并以此为事实基础对话。两者解耦——文件系统是唯一接口。

## 涉及代码

- `core/diary.py:16` — `diary_path(day)` 路径约定
- `core/diary.py:20` — `read_diary(day)` 读取单日内容
- `core/diary.py:28` — `read_today()` 读当日
- `core/diary.py:32` — `read_days_ago(n)` 读 N 天前
- `prompts/__init__.py:50-60` — `build()` 里把今日日记注入 system prompt
- `prompts/guidelines.md` — "Grounded activity" 规则禁止编造今日活动
- `core/tools/recall_day.py` — `recall_day(days_ago)` 工具查往日

## 调用位置

- `cli.py:26` — agent tool 列表包含 `recall_day`
- `wechat.py:48` — 同上

## 设计要点

- **单向数据流**：Hermes 只写，Anna 只读。没有双向通信。
- **约定路径**：`history/diary/YYYY-MM-DD.md`，按日一个文件，markdown 自由格式。
- **注入 vs 工具二分**：今日日记自动注入 system prompt（Anna 不用主动查），往日用 `recall_day` 工具（省 token）。
- **空日记有提示**：没有日记文件时注入 `（今天还没有记录...）`，明确引导 Anna 诚实说"还没做什么"。
- **事实 vs 感受**：日记里是事实（做了啥），Anna 说感受可以现场生成——只要事件本身来自日记就不算编造。
