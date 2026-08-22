# 为首发健康管家 Plugin 选择统一端到端实现路线

> 状态：已确认（HOW）。本文是 Ticket 109 闭合后的当前技术路线权威；旧 Ticket 98 与 ADR 0021 只保留为历史候选。本文不证明实现、部署、医学审核、真实模型／微信使用或主人／联系人验收已经完成。

## 背景与决策

最新 TO 将健康管家固定为单人专用 Partner Hermes 中的一个健康 Plugin，要求七个健康 Skill、唯一准入、六域画像、三类证据、任务、诊断、安全、支持联系人、数据权利、三态、删除防复活和完整迁移共同工作。Ticket 108 的 CAN 闭合审计确认：固定 Hermes／iLink 扩展面、SQLite／认证加密／systemd 原语和有限发送边界支持至少一类无已知根本矛盾的实施空间，但当前 Partner 没有完整运行能力链。

本 HOW 选择一条统一路线：

```text
唯一主人入口
  -> health_weixin（原生去重/合批/cursor 前的确定性准入）
  -> Partner Health Plugin（协调、Skill 证明、模型/投递适配）
  -> 受限 Unix socket
  -> health-core（唯一健康状态写入者与业务裁决者）
       |- 本地加密 SQLite 受管状态域
       |- 单区域 DynamoDB 不透明 current-head item
       |- 离线 KnowledgePublisher / staged release
       |- 事务 outbox、StatusProjector、writer-fence 删除与迁移
  -> StrictHealthLLM（同一 Partner 的已同意首跳、无跨首跳 fallback）
  -> 分层 Weixin／支持联系人投递
```

`health-core` 不是第二个 Agent、人格、画像或 LLM Gateway。它没有聊天入口、普通会话、微信凭据、模型供应商配置、独立定时器或直接外发权；Gateway、Plugin、core、密钥、current head 或 contract probe 无法证明时，健康路径失败关闭。

## 稳定边界

Plugin 与 core 之间只有三类深接口：带来源、因果 ID、generation 和允许范围的健康命令；由 core 生成、由适配器执行并回交完整终态的受控模型／投递效果；以及按权利和 manifest 限定的受管读取／迁移快照。数据库表、Skill、Tool、Command、Cron、模型输出、普通 Agent 和外部服务都不是替代写入者。

`health_weixin` 先收每个可用 envelope；core 保留逐次来源、字段缺失和重投歧义，并只在业务提交确定后推进受管 cursor。初始化由确定性 `health-init` 状态机完成披露、主人同意、首跳路线同意、时区偏好、初始画像、密钥、本地 revision 与 current head 的 prepare／条件提交／finalize；中断或未知不得启用或倒填。

七 Skill 按角色组织：`health-steward` 唯一协调，`health-settings` 主人控制，四个 B 类 Skill 只返回候选。Skill 发现、全文加载、模型自述和回复披露不等于真实使用；只有运行时可证明的必需动作才形成最小使用事实。任何候选必须回到 core，职责 Skill 不直接写、发、回复或完成任务。

## 权威状态与外部头

本地 SQLite 统一承载 receipt／来源、六域画像、三类证据、任务、批准、控制、诊断修订、未知、outbox、交付、状态、删除和迁移。内容使用标准认证加密与专用密钥边界；普通 Session、Memory、FTS、日志、cache、通用备份和模型 transcript 永不成为第二权威。

DynamoDB current-head item 只保存不透明 installation/generation、最终 revision digest、transition ID、active writer fence、站点和不可逆 terminal deletion 标记，不保存健康正文、凭据、联系人身份或可推断医学值。每次变化执行本地 prepared revision → DynamoDB 条件推进 → 本地 finalize；结果未知时按 transition ID 强读回查，未达成一致前健康读写、模型和外发均停止。单区域、固定资源身份、最小 IAM、凭据注入、费用／配额和 old-snapshot canary 是后继硬依赖。

## 模型、医学、安全与投递

`StrictHealthLLM` 只使用同一 Partner 的已同意首跳，禁止跨 provider／base URL／gateway fallback；它在最终 wire payload 上执行容量与严格结构门禁，并保留 `completed`、`incomplete`、`failed`、实际 model、usage 和 fallback 事实。健康路径不因主人问题访问 Web Search、MCP、普通 Tool 或任意 HTTP；无主人数据的 KnowledgePublisher 产生带来源、版本、许可、中文状态、审核与 hash 的不可变 staged release。

首发诊断范围只选窄 BMI 候选并保持 staged，直到实际使用权、冻结中文版本、医学专业审核、实现兼容和真实主人验收通过。模型前、模型后、提交前三段失败关闭；安全不可用、可信危险、危险未明、范围外、范围内固定分支。危险联系人是单一最小数据接收者，批准、警报、纠正和交付层级独立记录，可能已离站的未知效果冻结自动重试。

## 任务、权利、删除与迁移

core 的 TaskEngine 独占任务目标、阶段、验收、四标签、批准和后继关系；Cron 只唤醒，自然日账本决定复盘，业务三态来自业务事实而不是进程心跳。暂停主动支持、停止记录、任务取消、撤回批准和永久删除彼此独立。

永久删除先冻结效果、任务、模型和 outbox，再条件推进 terminal generation，随后销毁密钥并清除所有受管对象、备份、导出、迁移暂存和联系人／警报事实。迁移使用同一 writer fence：源端冻结并生成完整 semantic manifest，目标离线校验后一次 CAS 接管；旧 VM／旧 fence 失去写入、模型和发送资格，未知转移不重放。

## 验证与非承诺

验证顺序为：静态 release／manifest；合成 core；本机 socket、SQLite／认证加密与崩溃／未知故障；锁定 Hermes 的 Plugin／Adapter 无旁路合同；StrictHealthLLM 模型合同；医学权利、中文版本、专业审核与范围激活；DynamoDB 条件冲突、回查、删除与旧 VM／迁移 canary；最后才是获准的合成与真实模型／微信、主人和联系人验收。任何未通过项都只能显示不可用或无法确认，不能显示 active、已送达、已读、已审核或已验收。

本 ADR 选择的是 HOW 路线，不是实现计划。字段、schema、函数签名、部署命令、完整测试矩阵、真实外部授权和生产操作留给下一条显式流程；若后续发现会改变路线存在性的事实，必须退回单一 CAN 前提票。

## 依据

- [Ticket 109 HOW Answer](../../.scratch/partner-health-steward/issues/109-choose-unified-end-to-end-how-route-after-current-can-closure.md)
- [Evidence 36](../../.scratch/partner-health-steward/evidence/36-how-route-after-current-can-closure-20260822.md)
- [Ticket 108 CAN closure](../../.scratch/partner-health-steward/issues/108-close-current-can-after-seven-skill-contact-investigations.md)
- [Current Map](../../.scratch/partner-health-steward/map.md)
- 固定 Hermes v0.20.0／commit [`3c27eb6234bf91b8ceee9e9071591b31e9b148cb`](https://github.com/NousResearch/hermes-agent/commit/3c27eb6234bf91b8ceee9e9071591b31e9b148cb)
- [DynamoDB 强一致读取](https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/HowItWorks.ReadConsistency.html) 与 [条件写入](https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/Expressions.ConditionExpressions.html) 只证明所选 current-head 原语可用；实际账号、资源、最小 IAM、凭据和 canary 尚未配置或验证。
