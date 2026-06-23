# 荒原序列 · Barren Order

多Bot协作解决方案 — 让两个或多个Hermes Bot在飞书群内通过互相@实现协作。

## 概述

荒原序列是一个多Agent协作框架，支持：
- **Bot-to-Bot通信**: 通过飞书@mention实现跨Bot任务分发
- **主持者-执行者模式**: 战略Bot分配任务，执行Bot完成并汇报
- **工作流编排**: DAG引擎，支持条件分支、并行执行、重试机制
- **共享记忆**: 四级作用域（GLOBAL/AGENT/SESSION/WORKFLOW），TTL过期+快照恢复

## 快速开始

```bash
# 安装
pip install barren-order

# 配置飞书Bot
barren-order init --workspace your-feishu-group

# 启动协作
barren-order start --bots bot-a,bot-b --mode coordinator-executor
```

## 使用场景

- **信息采集+分析**: Bot A采集数据，Bot B分析并生成报告
- **代码审查+部署**: Bot A审查代码，Bot B执行部署
- **内容创作+发布**: Bot A生成内容，Bot B排版并发布

## 技术架构

- **通信层**: 飞书@mention消息解析与路由，支持Bot-to-Bot直接对话
- **任务调度**: DAG工作流引擎（WorkflowBuilder/WorkflowExecutor），支持条件分支和并行
- **状态管理**: 四级作用域记忆系统（GLOBAL/AGENT/SESSION/WORKFLOW），TTL过期+快照恢复
- **错误处理**: max_retries + retry_delay重试，降级策略，人工介入兜底

## API

```python
from barren_order import Coordinator, Executor

coordinator = Coordinator(bot_id="bot-a")
executor = Executor(bot_id="bot-b")

coordinator.register(executor)
result = coordinator.dispatch("分析竞品数据", target="bot-b")
```

## License

MIT
