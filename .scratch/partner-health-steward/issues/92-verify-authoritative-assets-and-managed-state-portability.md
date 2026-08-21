# 【CAN】核验权威文档、Skill 与受管个人状态的完整迁移能力

Type: research
Status: wontfix
Parent: [健康管家首发 TO、CAN 与 HOW 决策闭合路线](../map.md)
Blocked by: [【CAN】核验当前 Partner Hermes 基线、Plugin 生命周期与可信执行边界](78-verify-current-partner-hermes-baseline-plugin-lifecycle-and-trust-boundary.md), [【CAN】核验健康能力入口、初始化门禁与真实结果返回能力](79-verify-health-capability-entry-initialization-gate-and-result-contract.md), [【CAN】核验唯一微信准入、排他分流、逐次来源与重投结果能力](80-verify-unique-weixin-admission-routing-provenance-and-replay-results.md), [【CAN】核验受管健康状态数据平面、保护隔离与单一权威能力](81-verify-managed-health-state-plane-protection-and-single-authority.md), [【CAN】核验健康任务与受管运行框架的生命周期、复盘投递、主人控制、三态观测及迁移能力](83-verify-open-health-task-lifecycle-dispatch-acceptance-and-scope-approval.md), [【CAN】核验首跳模型路线、主人派生查询隔离与非诊断健康问答结果链](85-verify-first-hop-model-route-and-owner-derived-query-isolation.md), [【CAN】核验诊断修订链、依据失效传播与单一当前权威能力](89-verify-diagnostic-revision-chain-and-current-authority.md), [【CAN】核验主人数据权利、分离控制、永久删除与防复活能力](90-verify-owner-rights-control-deletion-and-non-resurrection.md), [【CAN】核验健康管家三态运行状态与跨故障域观测能力](91-verify-runtime-three-state-observation-and-fault-isolation.md)

## Question

当前项目文档、配套 Skill、Plugin 受管状态与源/目标 Hermes 环境能否形成一个完整、可枚举、可校验且不依赖 LLM 会话记忆的健康管家迁移边界；产品规则、四项职责所需流程、六域画像、三类证据、任务、批准与撤回、控制、未知、交付、诊断修订和删除状态分别由哪些权威资产承载，哪些普通聊天、草稿、模型过程或缓存不得被误作权威？

本票要核验搬迁后引用、来源时间、当前权威、撤权、终态和未知结果不会被改写，源端与目标端不会同时形成两份继续变化的当前真相；目标端的唯一入口、初始化状态、首跳同意和受管保护仍正确。缺项、版本不兼容、权限/密钥错误、源目标切换或结果未知时必须失败关闭并如实显示异常或无法确认，不能空白重初始化、补发积压或复活旧批准/已删内容。

这项能力是健康管家文档、Skill 和个人受管状态的产品迁移，不是聊天账号迁移、真人身份恢复、恢复码或第三方接管。复制文件或校验和一致只证明字节搬迁，不能证明语义、权限、引用和单一权威；完整结论需要在可丢弃源/目标环境中的获准迁移演练。本票不选择包格式、传输、加密、锁、切换命令或部署 HOW。

## Comments

### 2026-08-20 — 由完整 TO 能力链重建创建

本票对应[【CAN】重建完整 TO 的能力链与追溯关系](76-rebuild-complete-to-capability-chain-and-traceability.md)中的 C16。

本票落实[【TO】确认首次主人绑定、消息准入与首发信任边界](74-confirm-owner-binding-message-admission-and-trust-boundary.md)中“权威文档、画像、证据、任务、控制和 Skill 可随产品搬迁”的现行目标，明确不恢复已经取消的账号迁移与恢复流程。

### 2026-08-20 — 被连贯受管运行框架调查吸收

本票对应的 C16 没有取消，也没有被视为已经证明；权威文档、Skill 与全部受管个人状态的完整枚举、来源和引用连续、批准/终态/未知保真、源目标单一当前权威及失败关闭，现由[【CAN】核验健康任务与受管运行框架的生命周期、复盘投递、主人控制、三态观测及迁移能力](83-verify-open-health-task-lifecycle-dispatch-acceptance-and-scope-approval.md)统一调查。它仍不是账号迁移、真人身份恢复或恢复码。本票改为 `wontfix` 只表示不再作为独立 Frontier 或 CAN 闭合前提；原 Question 保留作追溯输入，不在本票追加 Answer。重接决定见[【CAN】按连贯技术问题压缩并重接剩余能力调查](94-consolidate-current-can-investigations-by-coherent-route.md)。
