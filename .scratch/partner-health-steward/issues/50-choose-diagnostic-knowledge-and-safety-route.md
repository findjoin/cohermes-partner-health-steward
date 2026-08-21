# 【HOW】选择辅助诊断、医学知识与安全强制路线

Type: grilling
Status: wontfix
Parent: [健康管家首发 TO、CAN 与 HOW 决策闭合路线](../map.md)
Blocked by: [【TO】确认首发健康管家的基础产品能力与不可妥协边界](53-confirm-foundational-product-capabilities-and-boundaries.md), [【TO】确定健康管家诊断性判断与持证医生正式诊断的责任边界](40-define-diagnostic-physician-handoff-boundary.md), [【TO】决定医学来源缺口下是否保留辅助诊断目标及上线边界](60-decide-medical-source-gap-boundary.md), [【TO】确定辅助诊断覆盖、范围外行为与安全未知或故障时的主人可见结果](64-define-diagnostic-scope-and-safe-unavailable-result.md), [【TO】确定辅助诊断中的个人证据最小化、外部医学接收方与持久保留边界](65-define-diagnostic-evidence-recipients-and-retention-boundary.md), [【TO】确定诊断性判断的变更、纠正与可追溯产品合同](66-define-diagnostic-judgment-change-and-traceability-contract.md), [【TO】确定辅助诊断上下文不完整、超限或截断时的产品结果与上线边界](70-decide-diagnostic-launch-boundary-under-unverifiable-context-capacity.md), [【CAN】核验辅助诊断、医学知识与安全边界能力](46-verify-diagnostic-reasoning-knowledge-and-safety-capabilities.md), [【CAN】核验医学知识来源、检索接口与安全强制工具](59-verify-medical-knowledge-and-safety-enforcement-tools.md), [【CAN】核验健康能力发现、调用与结果返回契约](63-verify-health-capability-discovery-invocation-and-result-contract.md), [【CAN】核验健康模型路线的有效上下文上限、token 计量与超限行为](69-verify-health-model-context-capacity-token-accounting-and-overflow-behavior.md), [【HOW】选择健康管家在 Hermes 中的单一执行与权威路线](47-choose-hermes-health-execution-and-authority-route.md), [【HOW】选择健康画像数据平面、模型调用与保护路线](49-choose-health-record-rights-and-protection-route.md), [【CAN】闭合完整能力与约束事实并形成当前 CAN 报告](77-close-complete-capability-and-constraint-report.md)

## Question

在已选定的健康执行与单一健康画像路线内，如何由同一个 Partner Hermes 自己完成受控辅助诊断而不新增独立 LLM Gateway、独立健康模型服务或独立 provider 入口：只使用当前问题所需的个人证据，输出可能诊断、支持与反对证据、缺失信息、紧急度和下一步，保持 AI 判断与主人转述的医生诊断分离，并只使用符合准入和引用要求的医学知识；急症、自伤、危险用药和不得擅自建议调整处方药的边界由哪条不可绕过、故障时失败关闭的生成与发送路线强制执行？

## Comments

### 2026-08-17 — HOW paused for direct medical CAN

既有 Ticket 46 证明 Hermes 具有 Plugin、结构化模型调用和通用检索扩展空间，也证明当前没有内置医学知识、诊断质量保证或不可绕过的医疗安全闸门；但它没有核验本票实际选择所需的具体医学权威来源、检索与引用接口、中文覆盖、许可和目标可用性，也没有核验可在健康 Plugin 自有路径中强制执行的急症、自伤、危险用药与处方药边界机制。为遵守 `TO → CAN → HOW`，本票新增直接 CAN Ticket 59，并在其闭合前暂停 HOW，不向主人询问来源、规则或阈值选择。

### 2026-08-17 — Grilling Round 1: root route decisions

Ticket 59 与后继 Ticket 60 已闭合医学来源和安全工具的事实缺口，并允许在上线硬门槛不降低的前提下继续选择 HOW。第一轮只询问八个彼此独立的根路线决定，不把来源清单、字段名、阈值或实现参数交给主人猜：

1. 诊断覆盖采用“已审核范围白名单分批开放”，还是等待广泛常见生理与心理问题全部闭合后一次开放？推荐前者；范围外仍执行安全判断，但不得输出诊断性判断。
2. 运行时医学知识是否仅来自本地固定版本知识包，并禁止把由主人事实派生的查询发送给外部医学接口？推荐确认；外部接口只用于不含主人资料的离线更新与审核。
3. 诊断核心采用“规则直接限定诊断、模型只解释”，还是“模型生成结构化诊断候选、本地确定性规则接受/拒绝/升级”？推荐后者，并让确定性规则独占危险、处方药与放行权；前者只用于危险规则和适合规则化的重点病种。
4. 生成与发送是否固定为“健康 Plugin 编排结构化候选 → 本地确定性校验 → 确定性渲染 → 唯一发送闸门”，不允许模型自由文本、普通聊天或通用 Hook/Middleware 直接成为最终健康结果？推荐确认。
5. 每次诊断性判断是否只向模型提供从唯一健康画像临时派生的“本次诊断证据集”，包含与当前判断直接相关的个人健康证据和必要安全证据，而不读取整份画像？推荐确认；该集合不是第二份画像。
6. 判断完成后是否只长期保存结构化判断、最小个人证据引用、医学知识引用、时间与变化原因，而不保存渲染后的完整回复？推荐确认。
7. 既有判断是否仅因个人证据或医生结论变化、准入医学知识或安全规则版本变化而更新，并强制记录变化原因，禁止仅因模型重跑而静默漂移？推荐确认。
8. 明确危险、安全状态仍不明或安全组件故障时，是否允许唯一的预置“安全最低响应”：只做非诱导的最小澄清和/或急救、人工医疗介入建议，同时完全压制诊断方向与用药建议？推荐允许；不得用低/中/高风险分层或未命中关键词证明安全。

### 2026-08-18 — Paused for Destination correction

主人要求先暂停本票，并纠正 Map 的 Destination：最终目标是在目标 Partner Hermes 中实际部署一个健康管家 Plugin；该 Plugin 的用途、产品形态、能力、边界和成功条件由【TO】讨论，不应由 Destination、CAN 或本 HOW 预写。本票未形成 `## Answer`，本轮 claim 已释放；既有 Grilling 问题保留为历史对话，等待主人以后明确恢复本票时继续。

### 2026-08-18 — Recharted: unresolved TO removed from HOW frontier

主人修正 Destination 后重新调用 Map。本票被重新领取时复核发现，上一轮八项问题不能作为纯 HOW 继续：诊断覆盖及范围外行为、主人事实派生的外部医学接收方、每次判断的个人证据最小化与持久保留、既有判断的允许变更原因，以及安全未知或必要组件故障时主人得到什么，均会改变产品承诺，尚未由既有 TO 完整回答。

因此，本票新增直接前提 [【TO】确定辅助诊断覆盖、范围外行为与安全未知或故障时的主人可见结果](64-define-diagnostic-scope-and-safe-unavailable-result.md)、[【TO】确定辅助诊断中的个人证据最小化、外部医学接收方与持久保留边界](65-define-diagnostic-evidence-recipients-and-retention-boundary.md) 与 [【TO】确定诊断性判断的变更、纠正与可追溯产品合同](66-define-diagnostic-judgment-change-and-traceability-contract.md)。同时补入已有 [【CAN】核验健康能力发现、调用与结果返回契约](63-verify-health-capability-discovery-invocation-and-result-contract.md)，因为不可绕过的诊断安全路线必须先知道 Skill、Tool、Command、自动流程和其他 Plugin 是否存在绕过健康边界的入口。

上一轮问题只保留为历史提案，不构成主人答案：诊断核心的规则/模型职责及 Plugin 内生成、校验、渲染、发送拓扑仍是本票未来要决定的 HOW；本地或远程知识路线、临时证据视图、存储和版本归因、安全响应实现只能在对应 TO 与 CAN 闭合后重写为新的 HOW frontier。当前未形成 `## Answer`，claim 再次释放，本票改为等待前提信息。

### 2026-08-18 — Grilling resumed after TO closure: pure HOW root frontier

Tickets 64–66 已闭合诊断范围与失败结果、个人资料与接收方/保留边界、以及判断变更与纠错合同；Ticket 50 的全部直接前提现在均已解决。本轮重新领取本票，但 2026-08-17 的八项历史提案仍不构成主人答案。

只读复核确认没有新的 TO 或基础 CAN 缺口。现有事实已经把路线约束到健康 Plugin 自有执行空间：普通 Agent、Skill、提示词、普通 Tool、Hook 或 Middleware 都不能作为医学安全闸门；Tool、Command、Cron、`ctx.dispatch_tool` 与其他 Plugin 路径也不会天然共享可信主人身份、健康数据隔离或相同结果合同。结构化输出和本地 schema 只能证明格式，不能证明医学正确；当前目标现场仍没有已准入医学知识包、安全规则、校验器、统一健康发送边界或端到端 canary，这些必须作为实施和上线 No-Go 验证，不能冒充已经具备。

当前设计树只解锁三个彼此独立的根路线决定：

1. 模型与确定性规则的权威分工：模型生成非权威结构化候选、Plugin 本地规则独占准入、危险升级、处方药禁令、接受/拒绝与放行；或由规则直接产生全部诊断、模型只解释；不得让模型自由文本成为最终判断。
2. 运行时医学知识权威：只使用健康 Plugin 已晋级的本地、不可变、固定版本知识发布包；或在运行时访问预先固定的远程文档。按主人事实实时检索网页/API、用模型参数知识补足医学前提或使用未晋级缓存均与既定边界不相容。
3. 合法入口的收敛方式：所有聊天接入、未来自动流程及其他合法入口只向同一个 Plugin 私有健康操作协调器提交带可信身份与来源的请求，由协调器内部重新校验并独占模型、画像权威状态与待发结果；或让各入口分别编排并只共享校验函数。依赖 Tool schema、Hook、Middleware 或提示词统一约束已经被 CAN 否定。

知识包拆分与晋级、最小资料视图、候选到发送的状态机、确定性渲染、失效传播、未知状态恢复及验证矩阵都依赖上述根答案，留到下一轮设计树展开，不在本轮抢答。

#### Owner answers to resumed root frontier

- Q1：主人要求先解释“确定性规则”的具体含义，尚未选择。
- Q2：选择 A。运行时医学知识只使用本地、不可变、固定版本且已经许可、中文化和医学审核的知识发布包；模型参数知识不得补作医学前提。
- Q3：选择 A。所有合法入口收敛到同一个 Plugin 私有健康操作协调器，由其重新核验可信身份与来源，并独占健康模型调用、画像权威状态和待发结果。

主人随后确认 Q1 选择 A：模型只生成非权威结构化候选，Plugin 的确定性审查与放行机制拥有最终接受、拒绝、危险升级、处方药禁令和发送放行权。同时主人明确指出，这一选择不等于审查机制已经定形；审查发生在哪些阶段、规则如何分层和维护、以及如何证明其失败关闭，必须继续在本 HOW 设计树中讨论。

### 2026-08-18 — Grilling Round 2: deterministic review architecture

Q1–Q3 均选择 A 后，下一层设计树解锁四个并列 HOW 决定：

1. 审查采用模型前、模型后、提交/放行前的三段失败关闭，还是只做一次输出后审查。三段分别负责输入与运行条件、结构化候选合同、以及并发状态与版本的最终复核；任何一步未知或异常均不放行。
2. 规则资产采用分层、版本化的兼容组合，还是一份可直接热改的总规则：工程不变量、所有范围共享且经医学审核的安全核心、按诊断范围发布的证据投影/医学知识/诊断接受规则、以及经审核的渲染模板分别承担清晰职责，并由不可变兼容清单原子激活；运行时模型不得生成或修改规则。
3. 每个诊断范围是否随发布包携带经过医学审核、可版本化的最小资料投影策略，由 Plugin 在本地画像中构造短生命周期只读视图；还是让模型先读取更大范围甚至整份画像后自行选择。前者须区分个人事实、医生结论、既有 AI 假设、安全专用事实与未知，无法证明最小充分性时不生成候选。
4. 模型候选是否严格限制为不可直接发送的结构化内容，并仅由确定性渲染器映射到经审核模板；还是允许关键词过滤后的模型自由段落或普通 Agent 润色进入最终回复。

本轮不选择规则语言、字段、医学阈值、具体病种、来源供应商或模板文案。规则/来源发布晋级与失效传播、候选被拒后的状态、以及分层验证矩阵依赖本轮答案，将在下一轮展开。HOW49 已锁定的两段短事务与加密 outbox、TO65/66 已锁定的权威未知和交付未知不重新提问。

#### Owner answers to Round 2 and new context-budget requirement

- Q4：选择 A。采用模型前、模型后、提交/放行前三段失败关闭审查。
- Q5：选择 A。工程不变量、共享医学安全核心、分诊断范围的证据/知识/接受规则以及渲染模板分层版本化，并以不可变兼容组合激活。
- Q6：选择 A。每个范围使用经医学审核、带版本的最小资料投影策略，由 Plugin 在本地构造短生命周期只读视图，整份画像不进入模型。
- Q7：选择 A。模型只产生不可直接发送的结构化候选，最终文字仅由确定性渲染器根据已接受结构和经审核模板形成。

主人新增上下文预算要求：健康管家调用模型时必须组织本次模型输入，并在调用前判断“当前交互所需内容加上健康画像的必要片段、医学知识引用、规则/结构说明及输出预留”是否超过当前模型路线的有效上下文限制。该要求不得被实现为把完整当前会话或整份健康画像直接交给模型；它须继承 Ticket 65 与 Q6 的最小化合同，只使用本次判断必要且获准的片段。是否能从目标 Hermes/当前模型路线取得可靠的上下文上限、如何计量实际 token、以及超限后的安全降级路线需要先核验，不能凭模型名称或静态假设决定。

### 2026-08-18 — HOW paused for direct context-capacity CAN

现有 Evidence 06/10 只证明 `ctx.llm` 允许 Plugin 自行构造输入并提供名义 `max_tokens` 参数；它们没有证明目标 `codex_responses` 路线调用前暴露真实上下文窗口、实际 tokenizer、Hermes/provider 隐藏序列化开销、fallback 的最小共同窗口，或超限/输出耗尽时不会静默截断。固定提交初步复核还显示 `ctx.llm` 没有输入 token 预检，目标 adapter 对输出限制、结构化 response format 和不完整状态的透传也不能由公开接口语义直接推定。

因此新增直接前提 [【CAN】核验健康模型路线的有效上下文上限、token 计量与超限行为](69-verify-health-model-context-capacity-token-accounting-and-overflow-behavior.md)，本票释放 claim 并改为等待事实。CAN 闭合前只能保留定性不变量：完整会话和整份画像不得进入模型；实质相关证据、关键冲突、必要安全事实与医学依据不得为适配窗口而静默删除；任何无法证明未超限、自动截断、输出截断或不完整 schema 的候选都不得提交、渲染或发送。具体容量、计数算法、输出预留和超限处理路线不得先行选择。

### 2026-08-18 — Negative context-capacity CAN returned to TO

Ticket 69 已形成负向 CAN：目标现场名义 `context_length` 为 240,000，且未配置 Hermes 顶层 fallback，但当前 `ctx.llm` / `codex_responses` 固定路径不透传真实输出 cap 与结构化 `response_format`，会丢失或归一化不完整终态，现有 token 粗估也不是目标 tokenizer 的保守上界；因此既不能调用前证明完整必要输入与输出预留落在所有允许路线的有效窗口，也不能调用后可靠证明结果未被截断。

这一事实不能由本 HOW 静默改写为删除证据、依赖 provider 报错、粗估后尽力调用或自动分块诊断。后继 [【TO】确定辅助诊断上下文不完整、超限或截断时的产品结果与上线边界](70-decide-diagnostic-launch-boundary-under-unverifiable-context-capacity.md) 已确认继续保留完整性硬门槛：不能证明完整时该次诊断不可用，零个诊断范围通过全部门槛时不得冒充完整首发；上下文装配、容量预算、超限处置、截断检测以及是否需要宿主补强均留给后续 HOW。本票仍须等待完整 TO 闭合及能力链重建，不再把“升级、停用或降级”当作待主人决定的产品选项。

### 2026-08-20 — 被统一 HOW 吸收

完整 CAN 闭合后，诊断、模型、入口、状态、任务、安全、权利和迁移必须作为一条端到端技术路线共同选择。本票未形成 `## Answer`，其历史讨论不构成当前路线；全部仍有效的问题由[【HOW】选择健康管家的统一技术路线、权威职责与分层验证架构](98-choose-unified-health-steward-technical-route-and-authority-architecture.md)吸收。本票停止，不计作已选路线。
