# 【CAN】核验诊断范围隔离、安全强制与不可用结果能力

Type: research
Status: wontfix
Parent: [健康管家首发 TO、CAN 与 HOW 决策闭合路线](../map.md)
Blocked by: [【CAN】核验健康能力入口、初始化门禁与真实结果返回能力](79-verify-health-capability-entry-initialization-gate-and-result-contract.md), [【CAN】核验紧凑六域健康画像与三类证据卡的维护追溯能力](82-verify-six-domain-portrait-and-three-class-evidence-capabilities.md), [【CAN】核验明确诊断范围候选形成、准入与诊断全链能力](86-verify-medical-content-governance-and-diagnostic-scope-candidates.md), [【CAN】核验诊断资料选择、上下文容量与结构化终态能力](87-verify-diagnostic-context-capacity-and-structured-finality.md)

## Question

在目标 Hermes 的正式 Plugin 执行面中，可审计本地强制规则、已审核安全内容、范围状态、生成前后校验和唯一发送出口等候选能力，能否不可绕过地保证：只有明确激活且当前全部准入条件有效的范围形成个体辅助诊断；范围归属不明、存在会改变结论的重要范围外方向或范围失效时不做疾病排序、排除、个体用药改变或残缺诊断，但仍独立执行安全分流？

本票必须分别证明三种主人可见安全结果及故障语义：完整可信危险证据触发时立即停止诊断并优先给出急救/人工医疗行动；安全链完整但缺少会改变立即行动的主人事实时只问最小非诱导问题，不能安全等待时停止并建议及时紧急人工评估；安全来源、组件或校验不可信时只给预先约束、非个性化、无诊断和调药含义的最低求助提示。未命中规则不得被写成已经安全，范围外、上下文失败和模型不可用也不得绕过独立安全链。

全部诊断路径都必须把结果标为 AI 辅助判断，不冒充持证医生正式诊断，不建立医生账户、逐回复医生审核或自动医生工作流，也不得独立建议开始、停止或调整处方药；这些边界不能只在范围外或降级安全结果中成立。

持久结果也必须按分支收敛：范围外、处理前失败关闭、安全能力不可用和未通过候选不建立结构化诊断；可信危险只保留触发升级所需的最小证据与时间、适用安全依据、建议行动和交付状态；危险未明只保留会改变立即行动的关键缺口、必要补全任务或“仍未明且已建议紧急人工评估”的最小处置；安全能力不可用只留不含健康正文的处理状态。任何分支都不得借安全记录保存完整提示、模型输入输出、整份外部记录或完整回复。

提示词、模型一次正确回答、普通 Tool、Skill 或 fail-open Hook/Middleware 均不足以证明强制成立；需要适用来源和版本、医学审核、固定执行路径、范围失效、组件故障和对抗样例证据。具体病种规则由范围专属 CAN 证明，本票不选择规则引擎、阈值、渲染、发送或模型职责 HOW，也不输出个体医疗建议。

## Comments

### 2026-08-20 — 由完整 TO 能力链重建创建

本票对应[【CAN】重建完整 TO 的能力链与追溯关系](76-rebuild-complete-to-capability-chain-and-traceability.md)中的 C12。

本票重建[【CAN】核验辅助诊断、医学知识与安全边界能力](46-verify-diagnostic-reasoning-knowledge-and-safety-capabilities.md)的强制路径问题，并继承[【CAN】核验医学知识来源、检索接口与安全强制工具](59-verify-medical-knowledge-and-safety-enforcement-tools.md)关于 Skill、提示词和 fail-open 扩展面不足的受限事实。

### 2026-08-20 — 被诊断全链调查吸收

本票尚未形成 `## Answer`，不构成负向 CAN，也不计入同一 TO 节点的研究轮次。其 C12 调查内容已由[【CAN】按连贯技术问题压缩并重接剩余能力调查](94-consolidate-current-can-investigations-by-coherent-route.md)完整吸收到[【CAN】核验明确诊断范围候选形成、准入与诊断全链能力](86-verify-medical-content-governance-and-diagnostic-scope-candidates.md)；当前权威事实以后只来自该后继票的 Answer。本票仅保留为历史问题输入，不再参与 Frontier、依赖或 CAN 闭合。
