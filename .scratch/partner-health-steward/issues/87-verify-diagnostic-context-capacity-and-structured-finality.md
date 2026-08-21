# 【CAN】核验诊断资料选择、上下文容量与结构化终态能力

Type: research
Status: wontfix
Parent: [健康管家首发 TO、CAN 与 HOW 决策闭合路线](../map.md)
Blocked by: [【CAN】核验受管健康状态数据平面、保护隔离与单一权威能力](81-verify-managed-health-state-plane-protection-and-single-authority.md), [【CAN】核验紧凑六域健康画像与三类证据卡的维护追溯能力](82-verify-six-domain-portrait-and-three-class-evidence-capabilities.md), [【CAN】核验首跳模型路线、主人派生查询隔离与非诊断健康问答结果链](85-verify-first-hop-model-route-and-owner-derived-query-isolation.md), [【CAN】核验明确诊断范围候选形成、准入与诊断全链能力](86-verify-medical-content-governance-and-diagnostic-scope-candidates.md)

## Question

目标模型路线、Plugin 模型调用面、结构化输出、token 计量、上下文装配和最终状态提交面，能否支持每次诊断只选择省略后会实质改变判断、证据关系、紧急程度或下一步的个人资料，同时区分主人陈述、附件/外部记录、旧 AI 假设、仅用于安全的事实、冲突资料、事件时间和当前适用未知？

在形成任何诊断候选前，系统能否证明当前范围所需个人证据、医学依据、安全条件、固定指令与完整输出空间都没有缺项；主人当前同意的首跳路线在其正常内部路由/故障切换下能够保证的有效容量边界、输入/输出计量、结构化格式和截断/失败终态又是否有可靠事实，而不重新要求枚举服务内部最终下游？返回后能否证明结构终态完整且未截断，把未通过候选隔离为非最终、不写画像、不发送；只有最终写入或发送事实也不明时才进入处理结果无法确认，而不是用删减必要资料、缩窄问题、低置信度文字或等待报错冒充完整诊断。

任何成为最终的诊断性回答至少必须完整表达带顺序和不确定性的可能方向、关键支持证据、关键反对证据、会改变判断的关键未知、当前紧急程度和安全下一步；缺一项或结构终态不可证都不是较弱成功。只有通过范围、授权、证据、来源、安全和完整性门槛的最终结果才保留结构化诊断及其最小证据卡/医学版本链接、适用时间、紧急程度和下一步；原始提示、模型输入输出和草稿、临时资料集合、未通过候选、整份外部记录与完整诊断回复不得长期保存，处理闭合后清除受控临时副本。

本票调查通用调用与最终性机制；具体命名范围的最小医学内容仍由[【CAN】核验明确诊断范围候选形成、准入与诊断全链能力](86-verify-medical-content-governance-and-diagnostic-scope-candidates.md)产生的范围专属 CAN 证明。静态 `context_length`、粗估、调用后 usage、`stop` 或一次正向模型回答均不足；真实边界实验必须使用无健康正文的隔离输入并另行批准。本票不选择模型、tokenizer、上下文算法或提交 HOW。

## Comments

### 2026-08-20 — 由完整 TO 能力链重建创建

本票对应[【CAN】重建完整 TO 的能力链与追溯关系](76-rebuild-complete-to-capability-chain-and-traceability.md)中的 C11。

本票条件继承[【CAN】核验健康模型路线的有效上下文上限、token 计量与超限行为](69-verify-health-model-context-capacity-token-accounting-and-overflow-behavior.md)对旧固定路线的负向事实，但必须以当前指纹重核，且不能用旧结论替代命名范围的完整性证明。

### 2026-08-20 — 被诊断全链调查吸收

本票尚未形成 `## Answer`，不构成负向 CAN，也不计入同一 TO 节点的研究轮次。其 C11 调查内容已由[【CAN】按连贯技术问题压缩并重接剩余能力调查](94-consolidate-current-can-investigations-by-coherent-route.md)完整吸收到[【CAN】核验明确诊断范围候选形成、准入与诊断全链能力](86-verify-medical-content-governance-and-diagnostic-scope-candidates.md)；当前权威事实以后只来自该后继票的 Answer。本票仅保留为历史问题输入，不再参与 Frontier、依赖或 CAN 闭合。
