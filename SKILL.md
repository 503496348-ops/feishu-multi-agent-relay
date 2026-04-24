---
name: feishu-multi-agent-relay
description: 飞书多Agent跨实例协作协议 — 让多个Hermes Bot在同一个飞书群内互相@通信，实现主持者/执行者分工模式。开箱即用，配置模板分离设计。
version: 1.0.0
author: Hermes Agent
license: MIT
metadata:
  hermes:
    tags: [飞书, 多Agent, 跨实例, 协作协议, Bot通信]
    related_skills: [feishu-bot-at-format]
---

# 飞书多Agent跨实例协作协议

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
feishu-multi-agent-relay/
├── SKILL.md                      # 本文件（通用逻辑）
├── references/
│   ├── 配置模板.md                 # ⚡ 用户填写自己的ID（必须）
│   ├── 消息格式规范.md             # @标签的正确vs错误写法
│   └── 故障排查清单.md             # 常见问题与解决路径
└── scripts/
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
