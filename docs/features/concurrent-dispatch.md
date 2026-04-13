# 并发消息处理（Inbox 中断）

用户在 Anna 回复中途连发消息时，不阻塞 monitor、不丢消息、不起独立 run —— 新消息直接注入正在跑的 run，作为 user message 参与下一轮 LLM 推理。

## 涉及代码

### 路由层（wechat.py）

- `wechat.py:92-93` — `_inbox` / `_active_ctx` 模块级状态
- `wechat.py:96-110` — `dispatch_reply()` 非阻塞路由
- `wechat.py:126-175` — `worker()` 单消费者协程
  - `wechat.py:133-138` — 贪心合并入队消息
  - `wechat.py:150-161` — `_active_ctx` 生命周期（try/finally）
  - `wechat.py:168-172` — straggler 抢救
- `wechat.py:203` — `main()` 中启动 worker

### 注入层（core/loop.py）

- `core/loop.py:71-82` — 每轮 LLM call 前 drain `ctx.inbox`

### 数据结构

- `core/context.py:12` — `AgentContext.inbox: asyncio.Queue`

## 测试

- `tests/test_wechat_dispatch.py` — 9 个测试覆盖：
  - 空闲入队 / 空消息过滤
  - worker 消费
  - run 进行中 dispatch 非阻塞（< 20ms）
  - mid-run 按序注入 ctx.inbox
  - 启动前排队消息贪心合并
  - `_active_ctx` 正确复位
  - Straggler 抢救触发下一轮 run
  - `append_to_history` 严格早于 `_active_ctx = None`
