# 【CAN】核验健康管家三态运行状态与跨故障域观测能力

Type: research
Status: wontfix
Parent: [健康管家首发 TO、CAN 与 HOW 决策闭合路线](../map.md)
Blocked by: [【CAN】核验当地自然日复盘、通知投递、未知结果与故障恢复能力](84-verify-local-day-review-notification-delivery-unknown-and-recovery.md), [【CAN】核验诊断范围隔离、安全强制与不可用结果能力](88-verify-diagnostic-safety-enforcement-and-unavailable-results.md), [【CAN】核验诊断修订链、依据失效传播与单一当前权威能力](89-verify-diagnostic-revision-chain-and-current-authority.md), [【CAN】核验主人数据权利、分离控制、永久删除与防复活能力](90-verify-owner-rights-control-deletion-and-non-resurrection.md), [【CAN】核验有依据的非诊断健康问答与真实结果能力](93-verify-evidence-grounded-nondiagnostic-health-answer-capabilities.md)

## Question

Plugin 业务自检、状态一致性检查、进程/服务观测、范围状态、跨故障域观察和微信状态通知候选能力，能否让主人查询“活跃、异常、无法确认”、最近确认时间、受影响能力和当前可依赖结果，并保证只有画像、任务、控制、安全、非诊断健康问答及至少一个激活诊断范围都可证明可信时才显示活跃？

本票必须核验最后一个诊断范围失效时显示异常、范围或核心权威无法证明时显示无法确认；单项提醒未知或可选文献失败在不破坏核心时只隔离在任务层。任务、画像、非诊断健康问答、安全、数据权利、模型路线、调度和消息入口故障如何影响全局必须有确定传播，状态转为非活跃和恢复活跃各主动尝试一次不含健康正文的通知，不发送周期性绿色心跳。

单人专用 Hermes、唯一获准入口或其他声明的可信前提一旦已知失效，健康管家必须停止可信健康处理并显示异常；若只是无法证明这些前提仍成立，则停止相应健康处理并显示无法确认。两种结果都不得继续显示活跃或把基础 Hermes 普通聊天状态冒充健康管家状态。

Gateway/Ticker/Cron/systemd 存活、单个自检、同机 dashboard 或组件自报均不能证明完整业务活跃，也不能证明自身故障域外仍有人观察。结论须区分固定源码、当前现场和获准的进程、状态、模型、调度、范围及通知故障实验。本票不选择监控系统、探针、阈值、通知通道或恢复 HOW。

## Comments

### 2026-08-20 — 由完整 TO 能力链重建创建

本票对应[【CAN】重建完整 TO 的能力链与追溯关系](76-rebuild-complete-to-capability-chain-and-traceability.md)中的 C15。

本票接续[【CAN】核验每日复盘、主动投递恢复与跨故障域状态观测工具](62-verify-daily-review-delivery-recovery-and-cross-fault-status-tools.md)的观测事实，但必须按最终任务核心、诊断范围归零、数据权利和初始化合同重新核验。

### 2026-08-20 — 被连贯受管运行框架调查吸收

本票对应的 C15 没有取消，也没有被视为已经证明；活跃/异常/无法确认、最近确认时间、故障传播、单项隔离、最后诊断范围归零、可信前提、状态变化通知和跨故障域证明边界，现由[【CAN】核验健康任务与受管运行框架的生命周期、复盘投递、主人控制、三态观测及迁移能力](83-verify-open-health-task-lifecycle-dispatch-acceptance-and-scope-approval.md)统一调查。其他模型、问答和诊断调查负责提供各能力自身的事实，本后继票只核验统一状态如何承载和传播。本票改为 `wontfix` 只表示不再作为独立 Frontier 或 CAN 闭合前提；原 Question 保留作追溯输入，不在本票追加 Answer。重接决定见[【CAN】按连贯技术问题压缩并重接剩余能力调查](94-consolidate-current-can-investigations-by-coherent-route.md)。
