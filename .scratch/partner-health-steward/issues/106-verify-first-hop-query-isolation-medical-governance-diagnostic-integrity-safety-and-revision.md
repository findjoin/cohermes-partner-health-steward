# 【CAN】核验首跳路线、查询隔离、医学治理、诊断完整性、安全与修订能力

Type: research
Status: resolved
Parent: [健康管家首发 TO、CAN 与 HOW 决策闭合路线](../map.md)
Blocked by: [【CAN】核验受管领域状态、任务时序、主人控制、删除、观测与迁移能力](105-verify-managed-domain-state-tasks-controls-local-day-deletion-observation-and-migration.md)

## Question

本票服务 T12、T19、T24—T30、T33—T36 中有依据问答、首跳接收方、主人派生查询隔离、医学内容治理、诊断完整性、危险安全分支、判断修订、删除、三态、迁移和未来验收义务；对应能力节点 K11—K15，并核验 K18—K21 的模型、医学、诊断与安全侧集成。K14 不依赖 Skill 的独立最低安全路径由上游调查先核验，本票补完可信危险规则、诊断链和联系人候选之间的治理集成。

在 K01—K10 的当前事实和 K14 独立最低安全路径的交接面基础上，调查当前候选中的模型路线、出站调用、知识来源、容量与终态、固定安全裁决、诊断状态和修订表面，能否用非真实健康资料逐节点证明：

1. 当前首跳模型服务路线能否定位和监视，路线变化能否先暂停相关健康处理并重新取得同意；正常内部路由与未经同意的新首跳能否区分。
2. 主人派生医学查询能否被限制在当前首跳路线内，路线外搜索、API、普通 Tool、日志或缓存不得接收个人派生内容；通用医学知识更新与请求驱动查询不得互相冒充。
3. 非诊断健康问答能否只使用当前适用且可追溯的个人证据与合格通用知识，保留不确定性并在诊断资料、范围或安全条件不完整时停止越界；完整回复不得成为长期第二权威。
4. 医学内容权利路线、中文来源版本、专业审核入口、明确诊断范围候选、撤回／过期和最后有效范围状态能否被观察。CAN 只核验现实要求、候选入口、限制和 No-Go，不要求已经取得许可、完成审核、激活范围或通过主人验收。
5. 诊断最小资料、依据、安全条件、共同上下文容量、结构化完整输出和明确终态能否在形成结果前证明完整；静态窗口、粗略 token 估算、事后 usage、部分或截断输出不得冒充完整诊断，临时资料须在闭合后清除。
6. 危险升级、危险未明与安全能力不可用三分支能否由不可绕过的确定性边界严格区分；固定主人提示不得由 LLM 临场生成。只有经治理规则和当前可信证据确认的危险升级才可形成联系人最小警报候选，安全故障或危险未明不得外发。
7. 同一问题／事件／时期的诊断修订链能否保持至多一个可证明的当前判断或明确无当前，旧判断不原位覆盖，依据失效和权威未知能正确传播；必要纠错只形成一次受管尝试，联系人侧纠正交由后继票核验。
8. 模型、知识、诊断、安全、范围、修订与交付对象能否纳入上游通用删除、防复活、三态观测和完整迁移底座，并为未来真实模型、真实微信、医学审核和主人验收留下分层可观察性；不得把当前未实现误判为平台不可行。

[24 首跳路线、派生查询与非诊断回答](../evidence/24-first-hop-model-route-owner-derived-query-isolation-nondiagnostic-answer-results-20260820.md)需要按最新七 Skill、首跳和最低安全合同重新核验；[06 诊断推理、知识与安全](../evidence/06-diagnostic-reasoning-knowledge-safety-capabilities-20260816.md)、[11 模型路线与接收方事前锁定](../evidence/11-health-model-routing-and-recipient-preflight-20260817.md)、[12 医学知识与安全强制工具](../evidence/12-medical-knowledge-and-safety-enforcement-tools-20260817.md)、[16 模型上下文容量与超限](../evidence/16-health-model-context-capacity-token-accounting-overflow-20260818.md)、[25 命名诊断范围治理与全链能力](../evidence/25-named-diagnostic-scope-governance-and-full-chain-capabilities-20260820.md)与[27 成人高血压测量确认与紧急分流](../evidence/27-adult-hypertension-measurement-confirmation-and-urgent-referral-chain-20260820.md)只在其固定版本、一手医学事实和明确反例边界内作输入。现在是 2026-08-22，旧 `medical`、[【CAN】闭合完整能力与约束事实并形成当前 CAN 报告](77-close-complete-capability-and-constraint-report.md)、[28 完整当前能力与约束报告](../evidence/28-complete-current-capability-and-constraint-report-20260820.md)、[【HOW】选择健康管家的统一技术路线、权威职责与分层验证架构](98-choose-unified-health-steward-technical-route-and-authority-architecture.md)、[用一个 Plugin 私有 Health Core 统一入口、状态、模型、安全与运行](../../../docs/adr/0021-use-one-plugin-owned-health-core-and-governed-authority-stack.md)与 `ops/` 均只是历史审计输入，不是当前完整 CAN、已选 HOW 或已实现路线。

不得读取真实健康资料、聊天、联系人、密钥、Token、服务器配置、运行数据库或生产日志；不得发送主人派生查询、调用真实诊断、改变正式路线、激活医学范围、执行危险升级、联系人警报或产品验收。任何真实模型、真实微信、医学审核、故障注入或外部效果实验均须另行批准。

解决条件是在一份带引用 Evidence 中按 K11—K15 及诊断侧 K18—K21 分别给出已证明能力、限制、确定反例、未知、版本／来源适用范围、TO 覆盖和未来验证义务；明确 K14 的独立最低安全路径与可信危险治理集成各自成立或未成立的边界，并把联系人所需的危险候选、必要纠正和交付事实准确交给后继票。本票不选择模型、路由 Adapter、检索服务、医学来源组合、诊断范围、token 策略、安全引擎、状态机或其他 HOW。

## Answer

已完成本票的受限 CAN 核验，详细证据见[Ticket 106 首跳隔离、医学治理、诊断完整性、安全与修订核验（2026-08-22）](../evidence/33-ticket-106-first-hop-medical-governance-diagnostic-integrity-safety-revision-20260822.md)。

- **K11—K13**：固定 Hermes 的 Plugin out-of-band 模型调用、最小输入构造、Tool/Skill 扩展和局部结构校验原语已证明；历史现场可定位当时名义首跳，历史候选可展示来源卡/ID 校验与无正文投递账本。但当前 Partner 的首跳同意快照、路线变化暂停、全接收方锁定、主人派生查询隔离、有依据非诊断结果、医学内容权利、完整诊断资料/容量/结构终态和最小留存均尚未实现或未证明。
- **K12**：BMI 与疑似原发性高血压两个实质不同候选均已形成可审计边界；中文来源、版本入口和医学事实不等于项目已取得 AI/生产权利、完成专业审核、激活范围或具备撤回/过期观察。当前可证明的激活诊断范围为 0。
- **K14**：Ticket 104 已单独固定独立最低求助结果的产品边界；本票进一步确认可信危险规则、来源/版本/专业审核、当前证据和五态安全收敛尚未形成。危险未明或安全能力不可用不得生成联系人警报候选；联系人对象交给 Ticket 107。
- **K15 及诊断侧 K18—K21**：旧画像版本/current pointer、资料卡后继关系和通用删除/观测/迁移原语只能有界继承；诊断单一当前、依据失效传播、一次必要纠错、诊断资产全对象删除/防复活、三态业务观测、完整迁移 manifest 和未来真实验收承载均尚未实现或未证明。

历史 `ops/`、旧 `medical`、旧回答 schema、名义 endpoint、模型 `stop`、接口 accepted、固定来源和测试通过均不能作为当前 HOW 或诊断能力证明。当前仍处于 **CAN**；本票不进入 HOW、实现、部署或验收。
