# 荒原序列 · BarrenOrder

让两个或多个Hermes Bot在同一个飞书群内通过互相@实现协作的完整解决方案。

## 典型场景

- **Bot A = 主持者**：战略/合规/方案/决策辅助
- **Bot B = 执行者**：信息采集/技术操作/文档整理
- **用户**在群里发指令，主持者接收后@执行者派发任务，执行者完成后@主持者汇报

## 快速开始

### 1. 下载技能包

克隆本仓库到本地：
```bash
git clone https://github.com/503496348-ops/barren-order.git
```

### 2. 配置

编辑 `references/配置模板.md`，填写：
- 群ID（Group ID）
- 每个Bot的名字和open_id
- 角色分配

### 3. 校验配置

```bash
python scripts/validate_config.py
```

### 4. 启动协作

在飞书群里测试通信：
```
<at user_id="ou_执行者open_id">执行者名字</at> 通信测试，请回复"收到"
```

## 目录结构

```
barren-order/
├── SKILL.md                      # 通用逻辑（Hermes技能文件）
├── references/
│   ├── 配置模板.md                 # ⚡ 用户填写自己的ID
│   ├── 消息格式规范.md             # @标签正确/错误写法
│   └── 故障排查清单.md             # 常见问题排查
└── scripts/
    ├── validate_config.py          # 配置校验脚本
    ├── message_router.py           # 优先级路由 + 断路器 + 上下文感知路由
    ├── workflow_engine.py          # ⭐ DAG工作流引擎（顺序/并行/条件分支）
    └── shared_memory.py            # ⭐ 多Agent共享记忆与上下文管理
```

## 核心原理

```
用户 → 飞书群 → Bot A（主持者）@Bot B（执行者） → Bot B处理 → @Bot A汇报 → 用户看到结果
```

## @标签唯一正确格式

```xml
<at user_id="ou_对方的open_id">对方名字</at> 消息内容
```

**⚠️ user_id必须是open_id（ou_开头），不是cli_会话ID！**

## 更多信息

详见 [SKILL.md](SKILL.md)

---

## ⭐ 新增能力（v1.1.0）

### 1. DAG工作流引擎 (`scripts/workflow_engine.py`)

对标 Dify/CrewAI 的核心编排能力：
- **顺序/并行执行**：任务自动按依赖拓扑排序，独立任务并行执行
- **条件分支**：基于上游输出的 `equals` / `contains` / `success` / `failed` 等条件路由
- **重试与超时**：每个任务可独立配置 `max_retries` / `timeout` / `retry_delay`
- **流式上下文传递**：任务输出自动注入 `shared context`，下游任务用 `{{task_xxx_output}}` 引用
- **状态持久化**：工作流执行状态可保存/恢复

```python
from scripts.workflow_engine import WorkflowBuilder, WorkflowExecutor

wf = (WorkflowBuilder("demo", "我的工作流")
    .add_task("step1", "研究", prompt="研究{{user_query}}", agent_id="researcher")
    .add_task("step2", "撰写", prompt="写报告", agent_id="writer", depends_on=["step1"])
    .build())

executor = WorkflowExecutor(wf)
result = executor.run(initial_context={"user_query": "AI趋势"})
```

内置模板：
- `create_research_report_workflow()` — 研究→撰写→审核流水线
- `create_parallel_analysis_workflow()` — 多Agent并行分析→综合

### 2. 共享Agent记忆 (`scripts/shared_memory.py`)

对标 CrewAI 的 memory 系统：
- **命名空间隔离**：`GLOBAL`（全局共享）/ `AGENT`（Agent私有）/ `SESSION` / `WORKFLOW`
- **TTL自动过期**：支持带过期时间的记忆条目
- **任务上下文**：`set_task_context()` / `get_task_context()` 在工作流任务间传递状态
- **对话历史**：按角色记录多Agent对话，支持 `get_conversation_summary()` 注入prompt
- **快照/恢复**：`create_snapshot()` / `restore_snapshot()` 实现检查点
- **全文搜索**：`memory.search("关键词")` 跨所有记忆条目检索
- **磁盘持久化**：自动/手动保存到JSON文件

```python
from scripts.shared_memory import SharedMemory, MemoryScope, AgentContextBuilder

memory = SharedMemory(persist_path=Path("memory.json"))
memory.set("user_query", "分析市场", scope=MemoryScope.GLOBAL)
memory.set_task_context("research_data", "...")

# 为特定Agent构建上下文
ctx = AgentContextBuilder(memory, "bot_a").build_context()
```
