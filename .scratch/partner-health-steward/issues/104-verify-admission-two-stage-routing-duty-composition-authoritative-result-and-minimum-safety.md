# 【CAN】核验唯一准入、两级健康路由、职责组合、权威结果与独立最低安全能力

Type: research
Status: resolved
Parent: [健康管家首发 TO、CAN 与 HOW 决策闭合路线](../map.md)
Blocked by: [【CAN】核验当前 Partner、七个健康 Skill 资产加载与受管权威底座](103-verify-current-partner-seven-health-skill-assets-loading-and-managed-authority-foundation.md)

## Question

本票服务 T02—T04 的唯一主人、初始化门禁和持续启用，T05—T15 的两级路由、零／一／多职责组合、候选交接、权威提交、唯一回复与真实使用披露，T19、T20、T23、T30、T31、T33、T34、T36 的处理入口、失败／未知、安全优先级和未来验收可观察性；对应能力节点 K03、K04，并核验 K14 不依赖任何 Skill 的独立最低安全路径。模型路线、医学治理、诊断完整性与修订链由后继调查承接，本票只证明交接面，不提前解决 K11—K15。

在 K01、K02、K05 的当前事实基础上，核验唯一消息准入、初始化状态门禁、保守粗分流、`health-steward`、职责 Skill 调用、最小上下文投影接口、候选返回、业务权威提交、Skill 使用事实、主人回复和消息交付候选表面，能否形成一条可分层证明的处理链。代表性旅程至少覆盖：

1. 初始化前明确初始化请求只进入 `health-init`，普通健康陈述不被健康系统识别、记录或安全分流；初始化后覆盖明确非健康、健康、混合和无法确定消息。
2. `health-steward` 采用零项、一项或多项职责，存在依赖顺序、资料缺失、职责失败或版本冲突时的候选回传与唯一回复。
3. 两次相同正文、处理中断、提交前失败、提交结果未知、已提交但 Skill 披露或微信交付未知；来源、业务效果和重投不得互相冒充。
4. 画像、证据、任务、设置、模型／知识／诊断和安全只通过有类型的最小请求与候选结果交接；本票可证明接口、禁止越权和失败传播，但不把下游领域或模型能力尚未调查冒充已经成立。
5. 旧 `medical`、B 类职责直达、普通 Hermes 或模型自述旁路尝试均不得形成受管健康结果。

非 Skill 安全边界须单独核验：正常时由 `health-steward` 路由，但由安全边界最终裁决；初始化已完成且唯一准入成功后，`health-steward` 或任何 Skill 不可用时，K14 仍须形成安全能力不可用的固定最低求助提示，并在存在独立、已治理且可用的危险规则时保留形成固定危险提示的承载面；不得伪造 Skill 使用、建立画像／证据／诊断／普通任务。危险规则、可信危险成立及与诊断链的集成由后继模型／医学／诊断调查核验，危险未明或安全能力不可用不得产生联系人警报候选。

[健康能力入口、初始化门禁与真实结果返回能力](../evidence/20-health-capability-entry-initialization-gate-result-contract-20260820.md)、[唯一微信准入、排他分流、逐次来源与重投结果能力](../evidence/21-unique-weixin-admission-routing-provenance-replay-results-20260820.md)与[Hermes 七个健康 Skill 的文档分层、加载与 token 成本核验](../evidence/29-hermes-seven-health-skill-context-loading-and-token-efficiency-20260821.md)需要按最新入口与 Skill 合同重新核验；[聊天接口、主人身份与逐条消息来源能力](../evidence/03-channel-owner-provenance-capabilities-20260816.md)、[微信 iLink 入站接口与重复投递语义](../evidence/07-weixin-ilink-inbound-contract-and-replay-semantics-20260816.md)、[微信 iLink 与目标 Hermes 真实接口能力](../evidence/08-weixin-ilink-target-hermes-interface-capabilities-20260816.md)与[健康能力发现、调用与结果返回契约](../evidence/15-health-capability-discovery-invocation-result-contract-20260818.md)只在原版本和固定源码边界内作输入。须区分官方合同、固定源码、2026-08-22 当前脱敏资产事实、历史候选和获准的非真实健康实验。不得读取真实健康资料、聊天、联系人、密钥、Token、服务器配置或运行数据库；真实微信、故障注入或正式状态改变须另行批准。

解决条件是对 K03、K04 及 K14 的独立最低安全路径逐项报告已证明、限制、反例、未知和 TO 覆盖，并明确区分准入、路由、加载、候选、提交、使用事实、回复形成、接口接受与真实到达；同时把 K11—K15 所需的最小交接事实和未决项准确交给后继票。本票不选择 Adapter、分类器、Skill/Tool/Command 映射、提交介质、安全组件或其他 HOW。

## Answer

已完成本票的受限 CAN 核验，详细证据见[Ticket 104 唯一准入、两级路由、职责组合、权威结果与独立最低安全核验（2026-08-22）](../evidence/31-ticket-104-admission-routing-duty-composition-minimum-safety-20260822.md)。

- **K03**：Hermes 固定版本提供 allowlist、群策略、Adapter、cursor、去重和发送等局部原语；历史 Weixin 路径同时暴露准入前读正文、cursor-first、相同正文吞并、合批来源丢失和接口接受不等于主人到达的边界。当前 Partner 的唯一入口、初始化前后排他分流、来源/重投冻结、业务幂等和真实到达均需重新核验，完整链尚未实现或证明。
- **K04**：Skill/Tool/Command/direct/Cron 的发现、加载、调用、候选、提交、披露和到达互不等价；仓库候选有 handler 和 pinned responder 表面，但没有七项运行 Skill、steward 零/一/多职责组合、B 类候选回传、唯一权威提交、系统生成使用事实或唯一主人回复的当前证明。
- **K14**：产品合同要求独立于 Skill 的固定最低求助结果；旧安全候选只有静态分类和固定文案，未证明初始化/唯一准入门禁、独立可用性判定、可信危险治理或零健康副作用。因此独立最低安全路径尚未实现或证明，危险规则集成交给后继 K12—K15。

结论分类为：固定 Hermes 原语和产品边界已证明或有界可继承；历史现场与运行绑定需要重新核验；`ops/` 候选、旧 `medical`/普通回退假设已经失效为当前权威；K03、K04、K14 的核心产品能力尚未实现或未证明。本票仍停在 **CAN**，没有进入 HOW、实现、部署或验收。
