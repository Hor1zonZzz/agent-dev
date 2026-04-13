# 并发消息处理（Inbox 中断）

用户在 Anna 回复中途连发消息时，不阻塞 monitor、不丢消息、不起独立 run —— 新消息直接注入正在跑的 run，作为 user message 参与下一轮 LLM 推理。worker 单消费者协程一次处理一轮，外层 try/except 让单次失败不会拖垮整个 worker。

## 涉及代码

### 路由层（wechat.py）

- `wechat.py:108-109` — `_inbox` / `_active_ctx` 模块级状态。inbox 元素是 4-元素 tuple `(user_id, text, context_token, is_proactive)`
- `wechat.py:112-130` — `dispatch_reply()` 非阻塞路由（每条入站还顺手 `update_dispatch_info` 持久化 user_id 和 token，见 [proactive.md](proactive.md)）
- `wechat.py:133-138` — `enqueue_proactive()` proactive loop 调用入口
- `wechat.py:154-171` — `worker()` 外层循环 + `try/except` 容错（`asyncio.CancelledError` 透传，其他异常 log + 继续）
- `wechat.py:174-241` — `_run_one_iteration()` 单轮主体
  - `wechat.py:180-189` — 贪心合并入队消息（proactive 触发独占消费）
  - `wechat.py:195-201` — gap hint prefix（见 [time-awareness.md](time-awareness.md)；proactive 跳过）
  - `wechat.py:212-227` — `_active_ctx` 生命周期（try/finally）；proactive 时合成消息从 history 剥离
  - `wechat.py:236-239` — straggler 抢救
- `wechat.py:278-281` — `main()` 中启动 worker / proactive / hermes-cron

### 注入层（core/loop.py）

- `core/loop.py:71-82` — 每轮 LLM call 前 drain `ctx.inbox`

### 数据结构

- `core/context.py:12` — `AgentContext.inbox: asyncio.Queue`

## worker 容错设计

`worker()` 用 `asyncio.create_task()` 启动且不被 await，所以**未捕获异常会被 asyncio 静默吞掉、worker 直接死亡**，后续消息永远卡在 `_inbox` 里。所以拆分成 outer + inner 两层：

```
worker():
    while True:
        try:
            await _run_one_iteration()
        except CancelledError: raise   # 关停时透传
        except Exception:               # 其他全部捕获
            log + 重置 _active_ctx + 继续
```

这样单条消息处理失败（LLM 报错、history 损坏等）不会让 worker 永久挂掉。

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
