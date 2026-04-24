# 飞书多Agent跨实例协作协议

让两个或多个Hermes Bot在同一个飞书群内通过互相@实现协作的完整解决方案。

## 典型场景

- **Bot A = 主持者**：战略/合规/方案/决策辅助
- **Bot B = 执行者**：信息采集/技术操作/文档整理
- **用户**在群里发指令，主持者接收后@执行者派发任务，执行者完成后@主持者汇报

## 快速开始

### 1. 下载技能包

克隆本仓库到本地：
```bash
git clone https://github.com/503496348-ops/feishu-multi-agent-relay.git
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
feishu-multi-agent-relay/
├── SKILL.md                      # 通用逻辑（Hermes技能文件）
├── references/
│   ├── 配置模板.md                 # ⚡ 用户填写自己的ID
│   ├── 消息格式规范.md             # @标签正确/错误写法
│   └── 故障排查清单.md             # 常见问题排查
└── scripts/
    └── validate_config.py          # 配置校验脚本
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
