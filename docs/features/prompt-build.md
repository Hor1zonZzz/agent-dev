# Prompt 组装

把 `prompts/` 下的 markdown 片段（soul / guidelines / mood / user_profile）拼成 system prompt，并把 memory 摘要注入其中。

## 涉及代码

- `prompts/__init__.py:10-15` — `_read()` 读取 md 片段
- `prompts/__init__.py:17-43` — `build(memory=...)` 主入口
- `prompts/soul.md` — Anna 人设
- `prompts/guidelines.md` — 行为准则
- `prompts/mood.md` — 情绪状态模板
- `prompts/user_profile.md` — 用户画像模板

## 调用位置

- `cli.py:22` — CLI 启动时作为 `agent.instructions`
- `wechat.py:43` — 微信启动时作为 `agent.instructions`
