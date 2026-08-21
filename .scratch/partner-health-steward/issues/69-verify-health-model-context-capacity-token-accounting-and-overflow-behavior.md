# 【CAN】核验健康模型路线的有效上下文上限、token 计量与超限行为

Type: research
Status: resolved
Parent: [健康管家首发 TO、CAN 与 HOW 决策闭合路线](../map.md)
Blocked by: [【TO】确定辅助诊断中的个人证据最小化、外部医学接收方与持久保留边界](65-define-diagnostic-evidence-recipients-and-retention-boundary.md), [【CAN】核验健康画像数据平面的可用工具与接口](56-verify-health-data-plane-tools-and-interfaces.md), [【CAN】核验健康模型调用与全部实际接收方事前锁定能力](57-verify-health-model-routing-and-recipient-preflight-capabilities.md), [【HOW】选择健康管家在 Hermes 中的单一执行与权威路线](47-choose-hermes-health-execution-and-authority-route.md), [【HOW】选择健康画像数据平面、模型调用与保护路线](49-choose-health-record-rights-and-protection-route.md)

## Question

针对目标 Partner Hermes v0.20.0 固定提交、目标现场当前配置的首跳模型服务路线、该路线允许的正常内部路由或故障切换，以及已经选定的健康 Plugin `ctx.llm` 调用面，调用前究竟能否取得一个可证明有效的上下文容量合同：真实可用的最小上下文窗口是多少，Plugin 固定指令、消息、图片、结构化候选 schema、provider/Hermes 序列化包装与输出预留分别如何计入，目标环境能否用与实际请求一致的 tokenizer 或经验证的保守上界计算中文、JSON 和引用标识的 token；配置、模型、API 模式、fallback 或服务内部路线变化时，这份容量事实如何失效？

研究必须核验 `ctx.llm` 最终组装与发送的请求、公开 `max_tokens` 在目标 `codex_responses` 路线中是否真实成为输出限制、结构化 `response_format` 是否真实透传、所有允许路线能否在调用前给出可靠共同下限，以及输入超限或输出耗尽时服务端和 Hermes 是明确拒绝、返回可识别的不完整状态、自动截断、静默裁剪、压缩还是改走 fallback；成功后的 usage、finish reason、实际模型标识和错误是否足以证明请求没有被截断。不得用模型名称、营销窗口、静态配置值或调用后猜测冒充调用前保证。

结论必须区分官方或服务合同、固定提交源码行为、目标现场只读配置、无健康正文合成 canary、推论与仍未证明项，并解释每个容量参数的物理含义。先完成不发送模型请求的源码、文档和现场只读核验；如果只有真实请求才能闭合边界，只列明最小无健康正文 canary 的请求形态、外部影响、费用、停止条件和需要记录的非敏感结果，等待主人另行批准后再执行。不得读取或输出密钥、聊天或健康正文，不得修改配置、切换模型、触发 fallback、发送微信消息或把历史 sidecar 行为冒充当前权威。

产出带固定引用的 Markdown 证据并追加 `## Answer`。若无法在调用前证明所有允许路线的有效共同下限、token 计量上界及无静默截断语义，形成负向 CAN，并使 [【HOW】选择辅助诊断、医学知识与安全强制路线](50-choose-diagnostic-knowledge-and-safety-route.md) 继续失败关闭；不得先删除实质相关证据、依赖服务端报错、按局部材料拼接诊断或用任意巨大余量猜测安全预算。

## Answer

负向 CAN。完整证据见 [健康模型上下文容量、token 计量与超限行为核验](../evidence/16-health-model-context-capacity-token-accounting-overflow-20260818.md)。

目标现场 2026-08-18 只读核验确认固定 commit 正确、Partner 服务 active，当前名义路线为 `jojo` / `https://max2.jojocode.com/v1` / `codex_responses` / `gpt-5.6-sol`，配置 `context_length` 为 240,000，且未配置顶层 fallback。但 240,000 只是 Hermes 优先采用的静态配置值，不是 JOJO 全部实际上游的容量合同；JOJO 公开资料还说明实际模型可按任务、上下文和策略变化。

固定源码证明：公开 `ctx.llm(max_tokens=...)` 在该目标路径不会成为 wire `max_output_tokens`；`complete_structured()` 的 `response_format` 也未由目标 adapter 透传；Responses 的 `incomplete`、`failed`、`incomplete_details`、response id 和权威实际 model 不会进入 Plugin 结果，且已有部分正文但没有终态事件的流会被本地归为 `completed`，最终表现为合成的 `finish_reason=stop`。现有中文/ASCII 粗估与每图约 1,500 token 不是目标 tokenizer 或已证明保守上界，`task=None` 的 fallback 也没有共同上下文下限。

所以调用前无法证明 `当前会话 + 健康画像 + 其他附带信息 + 固定指令/包装 + 输出预留` 落在所有允许路线的窗口内，调用后也不能靠 usage、`stop` 或请求 model 名称证明未截断。只读事实已足以解决本票；真实 canary 未执行且不是负向结论的必要条件。Ticket 50 继续失败关闭，直至后继能力补齐最终请求可计量、真实输出 cap、结构化格式透传、完整终态保留、全部允许路线共同下限及配置指纹失效机制。
