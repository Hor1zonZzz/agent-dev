# Planner（Anna 自主规划明天）

每天 23:00 由调度器触发，让 Anna 以本人身份（复用 `prompts.build()`）决定明天想做的 1-6 件小事，几点做，通过 `save_plan` 工具写到 `history/plans/YYYY-MM-DD.json`。第二天 Hermes 按这个计划跑，完全覆盖默认 `hermes/tasks.py` 的时段模板；无 plan 文件时回退到默认模板。规划失败不写日记、不发消息。

## 涉及代码

- `hermes/plan.py:28` — `PlanTask` / `Plan` Pydantic 模型
- `hermes/plan.py:57` — `plan_path(day)` 路径约定 `history/plans/YYYY-MM-DD.json`
- `hermes/plan.py:69` — `validate_tasks()` 校验规则（时间范围、升序、间隔、字段长度）
- `hermes/plan.py:112` — `write_plan()` 原子写
- `hermes/plan.py:137` — `read_plan()` 读取 + 校验（失败返回 None）
- `core/tools/save_plan.py` — `save_plan` 工具：Anna 用它落盘，校验失败会把错误返回给 LLM 让她修正
- `hermes/planner.py:60` — `run_planner()` 构造 planner Agent 并运行
- `hermes/planner.py:25` — `PLANNER_TRIGGER_TEMPLATE` 触发消息
- `hermes/scheduler.py:26` — `PLANNER_TIME = 23:00`
- `hermes/scheduler.py:39` — `ScheduledEvent` 统一事件类型
- `hermes/scheduler.py:48` — `_candidates_for_day()` 合并 planner + plan / 默认 schedule
- `hermes/scheduler.py:83` — `_next_event()` 严格晚于 now 的下一条
- `hermes/runner.py:62` — `run_single_task()` 单条 Hermes 任务（被 scheduler 按 plan 逐条调）

## 调用位置

- `wechat.py:281` — `start_hermes_cron()`（接口不变）
- `hermes/scheduler.py` 顶层 `python -m hermes.scheduler` 独立运行
- `hermes/planner.py` 顶层 `python -m hermes.planner` 手动触发一次

## 设计要点

- **规划者是 Anna 本人**：planner Agent 的 instructions 就是 `prompts.build()`，所以 soul / guidelines / user_profile / mood / 今日日记都自然注入。plan 是她"自己的决定"，不是外部 planner persona。
- **工具集去 send_message**：planner 只有 `recall_day` + `save_plan` + `end_turn`，避免规划时突然给用户发消息。
- **校验失败可重试**：`save_plan` 把校验错误作为 tool result 返回给 LLM，Anna 可以看到错误后再次调用。
- **去重依赖时间语义**：scheduler 只找严格晚于 `now` 的下一条事件，host 中途重启不会重跑已过时间的任务；同理不补跑。
- **fallback 简单**：没有 plan 文件 / JSON 解析失败 / 校验失败，都当作"无 plan"，当天走 `DEFAULT_SCHEDULE` + `hermes/tasks.py`。
- **规划本身不写日记**：留痕只有 loguru 日志和 plan 文件。避免系统性提示进 Anna 的上下文。
- **时间护栏**：任务时间强制在 `[06:30, 22:30]`，相邻至少隔 30 分钟，最多 6 条 —— 防 Anna 排满一天或和 quiet hour / planner 自己冲突。
