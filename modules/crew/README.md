# 荒原序列 × CrewAI 融合增强

## 融合来源
- **竞品**: crewAIInc/crewAI (25K⭐)
- **核心能力**: 角色编排 + 事件驱动工作流 + 任务依赖解析

## 新增模块

### role_orchestrator.py
角色编排引擎，从 CrewAI 提取核心设计：
- `AgentRole`: YAML 声明式 agent 定义（role/goal/backstory/tools）
- `Task`: 带依赖关系的任务定义
- `Crew`: 团队编排器，支持 sequential/parallel/hierarchical 三种执行模式
- 依赖解析: 拓扑排序 + 并行层级分组 + 环检测

### flow_engine.py
事件驱动工作流引擎：
- `@flow.start()`: 流程入口
- `@flow.listen("event")`: 事件触发
- `@flow.router()`: 条件路由
- `FlowState`: 可变状态管理
- 支持 and/or 逻辑组合触发

## 用法

```python
from role_orchestrator import AgentRole, Task, Crew, ProcessMode
from flow_engine import Flow

# 1. 定义角色
agents = {
    "researcher": AgentRole(name="研究员", role="信息收集", goal="找到最全面的信息", backstory="..."),
    "writer": AgentRole(name="写手", role="内容创作", goal="写出最好的文章", backstory="..."),
}

# 2. 定义任务
tasks = [
    Task(id="research", description="研究主题", expected_output="研究笔记", agent="researcher"),
    Task(id="write", description="撰写文章", expected_output="完整文章", agent="writer", dependencies=["research"]),
]

# 3. 组建团队并执行
crew = Crew("content_team", agents, tasks, ProcessMode.PARALLEL)
results = crew.execute(your_executor_fn)
```
