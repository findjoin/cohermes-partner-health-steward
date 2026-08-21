# 【HOW】选择主人身份迁移、恢复与域外代际权威路线

Type: grilling
Status: wontfix
Parent: [健康管家首发 TO、CAN 与 HOW 决策闭合路线](../map.md)
Blocked by: [【TO】确定主人授权聊天身份变化后的健康画像连续性与恢复边界](38-define-owner-identity-continuity-boundary.md), [【TO】确定旧状态恢复下的身份失效与健康管家启用边界](67-decide-owner-recovery-anti-rollback-launch-promise.md), [【CAN】核验主人身份迁移与恢复所需的身份、凭据和持久化能力](61-verify-owner-identity-migration-and-recovery-capabilities.md), [【CAN】核验抵抗旧状态恢复的身份权威锚点能力](68-verify-non-rollback-owner-identity-authority-anchor-capabilities.md), [【CAN】核验域外身份代际权威候选的强一致与防回滚能力](71-verify-external-owner-generation-authority-candidates.md), [【HOW】选择健康管家在 Hermes 中的单一执行与权威路线](47-choose-hermes-health-execution-and-authority-route.md), [【HOW】选择微信接入、主人授权与逐次来源路线](48-choose-channel-identity-and-provenance-route.md), [【HOW】选择健康画像数据平面、模型调用与保护路线](49-choose-health-record-rights-and-protection-route.md), [【CAN】闭合完整能力与约束事实并形成当前 CAN 报告](77-close-complete-capability-and-constraint-report.md)

## Question

在主人身份连续性、一次性主人恢复权利、永久失败关闭和旧状态不得复活失效授权已经由 TO 锁定，目标现场又被证明没有现成防回滚锚点，而域外候选 CAN 只允许“受管强一致事务/CAS”或“强一致条件对象 current head”进入比较的前提下，同一健康 Plugin 应选择怎样的主人身份迁移、恢复和域外代际权威路线？本票选择 HOW，包括设计、职责、验证方法和实施依赖；不实现、开通、购买、部署或执行真实恢复实验。

必须选择并说明具体候选类别及进入实施时需要固定的服务、Region/location、资源身份、费用边界与账号信任边界；决定域外最小状态与本地专用 SQLite 的职责分工，包括不可关联健康正文的稳定锚点、单调 generation、身份授权摘要、恢复权状态、唯一 transition ID、不可恢复终止事实及永久删除后的最小防复活保留。不得把身份明文、恢复凭据明文、聊天或健康正文写入域外权威，也不得让公开 SDK、WORM、备份或普通 vTPM 冒充已经部署的能力。

路线必须覆盖：首次初始化时如何建立唯一权威而不把“资源缺失”误当成可重复首次启动；旧身份发起、新身份接受的迁移；预先建立的一次性主人恢复权利的创建、消费、替换与撤销；全部权利丢失后的不可恢复锁定；本地准备、域外条件推进、本地提交与 outbox 之间的顺序；并发、重启、远端已经提交但响应丢失、本地与远端代际不一致、credential/网络/资源不可用或资源被删除重建时的查证、幂等与“无法确认”失败关闭。SQLite 与域外服务没有共同事务，任何路线都不得用一句“原子更新”掩盖跨域未知窗口。

必须决定应用 credential 的最小权限、启动与轮换方式，以及哪些操作只能通过被审查的状态机入口完成；同时继承当前威胁边界：域外权威用于让遵循协议的诚实 Plugin 拒绝旧快照和并发旧条件，不承诺抵抗恶意 guest root 替换 Plugin 或外部账号管理员摧毁整个信任边界。若主人希望扩大到这类主动对抗，停止本票并返回新的 TO，不得在 HOW 中静默加入。

Answer 还须给出明确验证路线和 No-Go：选定候选后的账号内只读配置核验、只含随机 ID/整数代际/随机摘要的隔离 Prototype、并发与结果未知故障矩阵、资源删除/重建、Hermes/Plugin/整机 old-snapshot canary、永久删除后旧状态仍被拒绝，以及所有测试的费用、外部写入、不可逆保留和停止条件。真实账号资源、credential、正式 Partner profile、主人微信、模型、身份值或健康资料在主人另批前一律不得触碰；上述证据未闭合前，初始化、创建正式健康画像、保存健康资料、产品级验收和上线继续 No-Go。

## Comments

### 2026-08-20 — 被现行 TO 取代

[【TO】确认首次主人绑定、消息准入与首发信任边界](74-confirm-owner-binding-message-admission-and-trust-boundary.md)已经明确取消聊天账号迁移、一次性恢复权、不可恢复身份锁定和域外身份代际权威这组首发目标；本 HOW 因而不再可执行，保留为历史路线记录并标记 `wontfix`。旧状态可能复活已删除资料或已撤回批准的通用风险，已改由[【CAN】核验主人数据权利、分离控制、永久删除与防复活能力](90-verify-owner-rights-control-deletion-and-non-resurrection.md)重新调查，不得借此恢复身份迁移目标。

### 2026-08-20 — 当前后继调查再次合并

上段指向的独立主人权利调查已由[【CAN】按连贯技术问题压缩并重接剩余能力调查](94-consolidate-current-can-investigations-by-coherent-route.md)吸收到[【CAN】核验健康任务与受管运行框架的生命周期、复盘投递、主人控制、三态观测及迁移能力](83-verify-open-health-task-lifecycle-dispatch-acceptance-and-scope-approval.md)。旧状态防复活风险继续调查，但本票的身份迁移目标仍保持取消。
