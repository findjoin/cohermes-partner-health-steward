# 【CAN】核验医学知识来源、检索接口与安全强制工具

Type: research
Status: resolved
Parent: [健康管家首发 TO、CAN 与 HOW 决策闭合路线](../map.md)
Blocked by: [【CAN】核验辅助诊断、医学知识与安全边界能力](46-verify-diagnostic-reasoning-knowledge-and-safety-capabilities.md)

## Question

针对目标 Hermes v0.20.0、目标运行环境和已经确认的辅助诊断与安全 TO，核验 Ticket 50 选择 HOW 所需的具体工具与接口，而不只证明抽象扩展空间：哪些一手医学权威来源或正式数据接口能够为常见生理、心理健康问题提供可追溯、带版本和日期的诊断依据，如何访问、检索和引用，它们的中文覆盖、更新方式、许可、可用性与个人健康资料接收边界是什么；目标环境有哪些已经可用或可引入的确定性机制，能够在健康 Plugin 自有路径中对急症、自伤、危险用药及不得擅自调整处方药进行模型前检查、模型后校验和发送前失败关闭，而不依赖 fail-open Hook、普通 Agent 提示词或未调用的 Tool。

研究必须逐项区分官方保证、固定版本或源码行为、目标现场已验证、尚未验证，以及必须另行取得主人批准的合成 canary、外部服务注册或真实请求；解释每个数值参数的物理含义。输出一份带一手来源引用的 Markdown 证据，并明确哪些候选已经足以进入 HOW、哪些仍需 Prototype 或形成 TO-CAN 差距。不得选择最终医学来源组合、安全规则、模型提示、阈值或实现结构，不得发送真实健康资料、真实微信消息或修改目标现场。

## Answer

详见 [医学知识来源、检索接口与安全强制工具核验](../evidence/12-medical-knowledge-and-safety-enforcement-tools-20260817.md)。本轮查清了来源职责与接口边界：WHO ICD-11 MMS 可提供带版本的中文术语和编码但不是诊断规则；WHO CDDR/mhGAP、具体 NICE 指南和国家卫生健康委具体指南是临床内容候选，但分别存在语言、许可、接口或项目授权缺口；MedlinePlus、PubMed、DailyMed/openFDA、RxNorm 和 WHO SMART Guidelines 只能承担解释、证据发现、标签/术语或特定领域规则，不能单独充当完整诊断依据。

目标 Partner Hermes v0.20.0 现场已有 Pydantic、jsonschema、HTTP/YAML 客户端和正式 Plugin Adapter/`ctx.llm` 扩展面，可用于后续实现模型前、模型后与发送前的本地检查；但当前没有医疗规则、校验器、统一发送出口或健康 Plugin，Skill、提示词、普通 Tool 及 fail-open Hook/Middleware 也不能冒充不可绕过的医疗闸门。没有执行模型、医学接口或微信 canary，因此不宣称端到端失败关闭已成立。

结论为负向 CAN：当前没有一套同时闭合足够中文诊断内容、当前项目许可、版本追溯和目标可用性的生产来源组合，所以 [选择辅助诊断、医学知识与安全强制路线](50-choose-diagnostic-knowledge-and-safety-route.md) 不能直接进入 HOW。新建 [决定辅助诊断医学来源缺口的处理边界](60-decide-medical-source-gap-boundary.md)，由主人决定是否保持辅助诊断目标并把内容许可/采购、逐病种中文来源清单和专业审核列为上线硬依赖；不得静默采用无许可或未经审核的资料，也不得静默降低既定诊断与安全目标。

## Comments

### 2026-08-17 — 继承权威说明

本票关于医学来源职责、许可/中文/版本缺口及目标现场强制构件的负向 CAN 原样继承；`## Answer` 不回写。其中“Ticket 50 不能进入 HOW”只记录差距决定前的状态；[【TO】决定医学来源缺口下是否保留辅助诊断目标及上线边界](60-decide-medical-source-gap-boundary.md) 已允许在内容使用权、中文来源版本清单和医学专业审核硬门槛下继续 HOW，因此 [【HOW】选择辅助诊断、医学知识与安全强制路线](50-choose-diagnostic-knowledge-and-safety-route.md) 当前已解除该阻塞，但不得绕过上线门槛。
