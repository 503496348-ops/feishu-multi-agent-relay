---
name: barren-order
description: "飞书群多Bot协作引擎。主从分工·@通信协议·任务编排·共享记忆。当需要配置多Bot协作、编排复杂任务、实现Bot间通信时使用。"
version: 1.2.0
author: Hermes Agent
license: MIT
metadata:
  hermes:
    tags: [飞书, 多Agent, 跨实例, 协作协议, Bot通信]
    related_skills: [feishu-bot-at-format]

triggers:
  - 多Agent协作
  - 任务编排
  - DAG工作流
  - barren-order
  - 荒原序列
---

# 荒原序列 · BarrenOrder

## 这是什么

让**两个或多个Hermes Bot**在**同一个飞书群**内通过**互相@**实现协作的完整解决方案。

典型场景：
- Bot A = 主持者（战略/合规/方案）
- Bot B = 执行者（信息采集/技术操作）
- 用户在群里发指令，主持者接收后@执行者派发任务，执行者完成后@主持者汇报

---

## 核心原理

```
用户 → 飞书群 → Bot A（主持者）@Bot B（执行者） → Bot B处理 → @Bot A汇报 → 用户看到结果
```

**唯一正确@格式：**
```xml
<at user_id="ou_对方的open_id">对方名字</at>
```

**⚠️ 关键：user_id必须是open_id（ou_开头），不是cli_会话ID！**

---

## 快速开始（3步配置）

### 第1步：填写配置模板

打开 `references/配置模板.md`，填写：
- 群ID（Group ID）
- 每个Bot的名字和open_id
- 角色分配（主持者/执行者）

### 第2步：校验配置

```bash
python scripts/validate_config.py
```

### 第3步：启动协作

配置校验通过后，在群里测试：
```
<at user_id="ou_执行者open_id">执行者名字</at> 通信测试，请回复"收到"
```

---

## 目录结构

```
barren-order/
├── SKILL.md                      # 本文件（通用逻辑）
├── references/
│   ├── 配置模板.md                 # ⚡ 用户填写自己的ID（必须）
│   ├── 消息格式规范.md             # @标签的正确vs错误写法
│   └── 故障排查清单.md             # 常见问题与解决路径
└── scripts/
    ├── message_router.py           # 运行时路由决策：manager-only、去重、drop reason
    ├── task_state.py               # intent锚定 + 审批状态机
    ├── shared_memory.py            # 共享记忆 + 团队经验池
    ├── watchdog.py                 # PID/cmdline/heartbeat/agent状态健康验证
    └── validate_config.py          # 配置校验脚本
```

---

## @标签正确vs错误示范

### ✅ 正确
```xml
<at user_id="ou_47eb6e4cddfcebaa8f1150a16e88713b">珠珠</at> 请帮我查一下
```

### ❌ 错误（千万避免）
```xml
<!-- 错误1：用了cli_开头 -->
<at user_id="cli_a9637d13d4f95bb3">珠珠</at>  ← 错！

<!-- 错误2：user_id为空 -->
<at user_id="">珠珠</at>  ← 错！

<!-- 错误3：没有at标签 -->
珠珠请帮我查一下  ← gateway不会路由到对方
```

---

## 角色分工模式

### 主持者（Bot A）
- 接收用户指令
- 分析任务、拆解步骤
- @执行者派发具体操作
- 把关合规、审核结果
- 代表用户做最终决策

### 执行者（Bot B）
- 接收主持者@的任务
- 执行信息采集/技术操作
- 完成后@主持者汇报结果
- 不直接响应用户（由主持者转发）

---

## 触发场景

| 场景 | 触发方式 |
|------|---------|
| 日常协同 | 群里@任一Bot |
| 主持者开场 | 执行者@主持者报到，主持者开场 |
| 执行者操作 | 主持者@执行者派发任务 |
| 紧急联络 | 群里@对方+简要说明 |

---

## 重要概念区分

| ID类型 | 格式 | 用途 | 用于@标签？ |
|--------|------|------|------------|
| open_id | `ou_`开头 | 用户的唯一标识 | ✅ 是 |
| cli_会话ID | `cli_`开头 | Bot的会话标识 | ❌ 否 |
| 群ID | `oc_`开头 | 群的唯一标识 | 不用于@ |

---

## 相关技能

- `feishu-bot-at-format` — @标签格式的底层技术说明（open_id vs cli_ ID）

---

## 使用前提

1. 所有Bot都已加入同一个飞书群
2. 每个Bot都知道自己在群里的角色（主持者/执行者）
3. 每个Bot的memory中都正确配置了其他Bot的open_id
4. 配置模板已填写并通过校验

---

## v1.2.0 新增能力

### 运行时路由状态机 (`scripts/message_router.py`)

将“谁能处理”升级为“谁应该接住”：

| 能力 | 说明 |
|------|------|
| 显式路由决策 | `RoutingDecision` 输出 `action/targets/reason/msg_id`，便于审计和监控 |
| 主持者唯一入口 | 人类/未知发送者默认只路由到主持者，执行者不直接对用户发散响应 |
| 执行者回报主持者 | worker 无显式目标时自动回到 manager，形成闭环 |
| 稳定 drop reason | `no_msg_id/dedup/cross_team/bot_self/empty/agent_no_target` 等可量化原因 |
| Slash 命令识别 | 零 LLM 正则识别 `/status` 等命令并交给主持者 |

### intent锚定与审批状态机 (`scripts/task_state.py`)

| 能力 | 说明 |
|------|------|
| 不可变原始意图 | `IntentRecord.raw_text` 保留用户原话，防止上下文压缩后任务漂移 |
| 合法状态迁移 | `待处理/进行中/需审批/已完成/已取消` 有明确迁移规则 |
| 审批硬暂停 | `需审批` 只能通过 `approve()` / `reject()` 离开 |
| 终态冻结 | `已完成/已取消` 不能被普通 update 复活 |
| JSON持久化 | 可落盘保存 tasks/intents/_meta |

### 团队经验池 (`scripts/shared_memory.py`)

在原有 `SharedMemory` 基础上新增 `TeamExperienceStore`：

| 能力 | 说明 |
|------|------|
| JSONL经验池 | 追加式记录团队经验，ID形如 `E-1` |
| pinned core | 固定经验始终可注入 prompt |
| on-demand recall | 长尾经验按查询召回，不全量塞进上下文 |
| 容量控制 | 超额时优先淘汰最旧未 pin 条目，保护核心规则 |

### 健康验证 (`scripts/watchdog.py`)

| 能力 | 说明 |
|------|------|
| PID验证 | 检查 pid_file 与进程存活 |
| cmdline防PID复用 | 要求进程命令行包含预期片段 |
| heartbeat新鲜度 | 区分进程活着但心跳停滞 |
| agent状态探针 | 区分 `idle/busy/ready/healthy` 与 wedged/error 等退化状态 |

---

## v1.1.0 新增能力

### DAG工作流引擎 (`scripts/workflow_engine.py`)

对标 Dify/CrewAI 的核心编排：

| 能力 | 说明 |
|------|------|
| DAG依赖解析 | 拓扑排序 + 环检测，确保工作流无死锁 |
| 并行执行 | 无依赖的独立任务自动并行 |
| 条件分支 | `BranchCondition` 支持 equals/contains/success/failed 等 |
| 重试机制 | 每个任务独立配置 max_retries + retry_delay |
| 上下文传递 | `{{task_xxx_output}}` 模板变量自动替换 |
| 状态持久化 | 执行状态可保存到磁盘，支持恢复 |
| 工作流模板 | 内置研究-撰写-审核流水线、并行多维分析 |

关键类：
- `WorkflowBuilder` — 流式API构建工作流
- `WorkflowExecutor` — 执行引擎
- `WorkflowDefinition` — 工作流数据模型（支持JSON序列化）

### 共享Agent记忆 (`scripts/shared_memory.py`)

对标 CrewAI 的 memory 系统：

| 能力 | 说明 |
|------|------|
| 命名空间隔离 | GLOBAL / AGENT / SESSION / WORKFLOW 四级作用域 |
| TTL过期 | 条目可设生存时间，自动清理 |
| 任务上下文 | 工作流任务间共享状态 |
| 对话历史 | 按角色记录，支持摘要生成 |
| 快照/恢复 | 创建检查点，支持磁盘持久化 |
| 全文搜索 | 跨所有记忆条目检索 |
| Agent上下文构建 | `AgentContextBuilder` 为指定Agent组装prompt上下文 |

关键类：
- `SharedMemory` — 核心记忆存储
- `AgentContextBuilder` — Agent上下文组装器
- `MemoryScope` — 作用域枚举


---

## 工作流

- [ ] 1. 确认用户需求和协作场景
- [ ] 2. 配置Bot身份和飞书群权限
- [ ] 3. 编排协作工作流（主持者→执行者）
- [ ] 4. 启动任务并监控执行状态
- [ ] 5. 验证输出结果

---

## 技术架构

- **通信层**: 飞书@mention消息解析与路由，支持Bot-to-Bot直接对话
- **任务调度**: DAG工作流引擎（WorkflowBuilder/WorkflowExecutor），支持条件分支和并行
- **状态管理**: 四级作用域记忆系统（GLOBAL/AGENT/SESSION/WORKFLOW），TTL过期+快照恢复
- **错误处理**: max_retries + retry_delay重试，降级策略，人工介入兜底
