# 【CAN】核验当地自然日复盘、通知投递、未知结果与故障恢复能力

Type: research
Status: wontfix
Parent: [健康管家首发 TO、CAN 与 HOW 决策闭合路线](../map.md)
Blocked by: [【CAN】核验唯一微信准入、排他分流、逐次来源与重投结果能力](80-verify-unique-weixin-admission-routing-provenance-and-replay-results.md), [【CAN】核验受管健康状态数据平面、保护隔离与单一权威能力](81-verify-managed-health-state-plane-protection-and-single-authority.md), [【CAN】核验健康任务与受管运行框架的生命周期、复盘投递、主人控制、三态观测及迁移能力](83-verify-open-health-task-lifecycle-dispatch-acceptance-and-scope-approval.md)

## Question

Hermes Cron/内部 dispatch、系统时区与定时面、Plugin 持久自然日账本、任务状态和微信主动发送接口，能否证明每个主人当地自然日业务级完成一次受影响画像与开放任务复盘，而不只是触发一次 Job；主人能够查询最近一次复盘时间和结论，无变化时安静，错过、重启或恢复后按当前状态重判且不补发积压？

本票必须分别核验主人可以独立选择的新任务、普通阶段变化、关心/提醒、任务终态和复盘摘要五类普通主动通知；危险升级、必要纠错和全局状态关键变化不可关闭，需要新增授权、决定未知外部效果或知悉能力缺口时至少主动请求一次且不重复催促。暂停主动支持、停止新增记录、任务取消和执行批准撤回不得互相替代。每次外发要分开记录结果形成、发送尝试、接口接受和主人真实到达；崩溃、超时、在途发送或返回不明时保持未知并阻止盲目重发。时区变化、自然日边界、重复触发、任务恢复和通知关闭的场景都须保留真实主人可见结果。

Cron 配置、Ticker/Gateway 存活、数据库中有任务或接口无报错都不足以证明业务复盘、任务派发或主人收到。真实发送、时间边界和故障实验若需要改变外部或正式状态，必须先取得主人批准。本票不选择调度器、outbox、通知通道、重试次数或恢复 HOW。

## Comments

### 2026-08-20 — 由完整 TO 能力链重建创建

本票对应[【CAN】重建完整 TO 的能力链与追溯关系](76-rebuild-complete-to-capability-chain-and-traceability.md)中的 C07。

本票重建[【CAN】核验每日复盘、发送恢复与运行状态能力](44-verify-scheduling-delivery-recovery-and-runtime-status-capabilities.md)与[【CAN】核验每日复盘、主动投递恢复与跨故障域状态观测工具](62-verify-daily-review-delivery-recovery-and-cross-fault-status-tools.md)中的复盘、投递和恢复部分；全局三态由独立后继 CAN 汇总。

### 2026-08-20 — 被连贯受管运行框架调查吸收

本票对应的 C07 没有取消，也没有被视为已经证明；其当地自然日复盘、五类普通通知、不可关闭消息、投递分层、结果未知、恢复不补积压及实验批准边界，现由[【CAN】核验健康任务与受管运行框架的生命周期、复盘投递、主人控制、三态观测及迁移能力](83-verify-open-health-task-lifecycle-dispatch-acceptance-and-scope-approval.md)在同一任务与运行状态旅程中统一调查。本票改为 `wontfix` 只表示不再作为独立 Frontier 或 CAN 闭合前提；原 Question 保留作追溯输入，不在本票追加 Answer。重接决定见[【CAN】按连贯技术问题压缩并重接剩余能力调查](94-consolidate-current-can-investigations-by-coherent-route.md)。
