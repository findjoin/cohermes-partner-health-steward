# 【CAN】核验诊断修订链、依据失效传播与单一当前权威能力

Type: research
Status: wontfix
Parent: [健康管家首发 TO、CAN 与 HOW 决策闭合路线](../map.md)
Blocked by: [【CAN】核验受管健康状态数据平面、保护隔离与单一权威能力](81-verify-managed-health-state-plane-protection-and-single-authority.md), [【CAN】核验紧凑六域健康画像与三类证据卡的维护追溯能力](82-verify-six-domain-portrait-and-three-class-evidence-capabilities.md), [【CAN】核验当地自然日复盘、通知投递、未知结果与故障恢复能力](84-verify-local-day-review-notification-delivery-unknown-and-recovery.md), [【CAN】核验诊断资料选择、上下文容量与结构化终态能力](87-verify-diagnostic-context-capacity-and-structured-finality.md), [【CAN】核验诊断范围隔离、安全强制与不可用结果能力](88-verify-diagnostic-safety-enforcement-and-unavailable-results.md)

## Question

受管状态事务、证据依赖关系、修订图和纠错通知候选能力，能否保证同一健康问题、事件和适用时期只有一条诊断判断链，并且至多有一个可证明的当前 AI 判断或明确没有当前判断；只有实质个人证据、医生结论、已准入医学知识/安全规则、专业审核或已确认缺陷变化才能触发改判，模型重跑、随机差异或 provider/提示词变化不得自行改变当前结论？

本票要核验修订、降级、撤回、替代和复核无变化的确定性语义，依据纠正/撤回/失效时立即传播并让旧判断退出当前，历史时期、医生结论、主人纠正与异议不被原位覆盖。停止新增记录时仍能使旧错误退出当前但不形成新的长期健康事件；权威改变未知时旧判断与候选都不能冒充当前；曾交付或影响行动的实质变化主动尝试一次必要纠错，发送尝试不能冒充主人收到。

主人转述的医生结论必须保留“主人提供/转述”的真实来源、医生结论时间和记录时间，与 AI 判断分开显示和修订；两者冲突时同时保留冲突与证据不足，建议主人向合格医疗人员澄清，AI 不得宣称推翻医生。历史只保留结构化诊断语义、退出原因、适用时期和解释变化所需的最小证据卡链接，不保存旧完整回复、聊天、提示、草稿或模型过程。

本票结论须依靠可定位的状态转换、依赖失效、并发/崩溃和时间语义证据，不得用重复运行模型或显示一段历史文本证明合法修订。它不选择版本号、差异算法、事务、通知通道或重试 HOW。

## Comments

### 2026-08-20 — 由完整 TO 能力链重建创建

本票对应[【CAN】重建完整 TO 的能力链与追溯关系](76-rebuild-complete-to-capability-chain-and-traceability.md)中的 C13。

本票直接服务[【TO】确定诊断性判断的变更、纠正与可追溯产品合同](66-define-diagnostic-judgment-change-and-traceability-contract.md)，旧 CAN 尚未对这条完整修订链做当前能力核验。

### 2026-08-20 — 被诊断全链调查吸收

本票尚未形成 `## Answer`，不构成负向 CAN，也不计入同一 TO 节点的研究轮次。其 C13 调查内容已由[【CAN】按连贯技术问题压缩并重接剩余能力调查](94-consolidate-current-can-investigations-by-coherent-route.md)完整吸收到[【CAN】核验明确诊断范围候选形成、准入与诊断全链能力](86-verify-medical-content-governance-and-diagnostic-scope-candidates.md)；当前权威事实以后只来自该后继票的 Answer。本票仅保留为历史问题输入，不再参与 Frontier、依赖或 CAN 闭合。
