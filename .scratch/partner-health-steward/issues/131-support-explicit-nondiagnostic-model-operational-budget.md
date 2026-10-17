# 131 - 支持明确标识的非诊断模型操作预算

Type: task
Status: ready-for-agent
Parent: [健康管家有限实施链](../map.md)
Blocked by: [125 - 生产模型与治理知识 Adapter](125-implement-partner-model-and-governed-knowledge-adapter.md)
Unblocks: [130 - 受控自然语言日常 Runtime](130-connect-governed-natural-language-daily-runtime.md), [128 - 主人产品验收](128-deploy-and-complete-owner-product-acceptance.md)

## Owner decision input

主人于 2026-10-18 在本会话明确选择继续使用当前 JOJO，接受仅非诊断、固定请求长度、禁止自动切换和自动重试、不完整即停止，以及目前不能保证服务端完整接收上下文的限制。决定及其精确技术边界只由 [ADR 0024](../../../docs/adr/0024-allow-owner-selected-nondiagnostic-model-operational-budget.md) 承接；这不是容量证明或 G10/G11 通过。

当前 `/models` 目录只证明 bound model 被列出，没有可靠共同容量、tokenizer 或实际模型集合来源。配置 `240000`、少数 usage 和用户接受风险均不得填充 `proven common_context_lower_bound`。Ticket 125 的严格 profile／证明模式继续保留给 full／诊断，本票不修改其冻结合同。

## Required delta and retained boundaries

在同一模型 Module、现有 Core exact intent 与三类 CorePort 边界内，承接一个明确标识的非诊断操作预算：最终 wire bytes 固定上限、输出预留、route/provider/requested model/config generation 绑定，并公开／记录“不提供共同上下文保证”。预算不是 tokenizer、服务端窗口或完整上下文的证明；`completed` 也不得消除这项声明。超预算停止，不通过静默截断或移除证据凑入预算。

保留当前同意、权威、有效期、currentness、terminal 与 unknown 规则；Plugin 发网络，Core 不持凭据或联网。不新增第二模型路由器、批准 ledger、健康状态写入者或普通聊天 fallback。发送前失效零调用，发送后失效保留真实 attempt／终态且拒绝候选。禁止自动切换和重试；不完整、failed、畸形或未知结果停止，unknown 冻结继续有效。

raw response identity、actual model、usage、完成／不完整／失败／未知及结构事实必须完整回交 Core 重验；实际 model 未知不能用 requested model 补齐。非诊断结果仍须通过既有 typed 候选、证据／治理知识、安全与确定性渲染／唯一提交链，不能生成疾病排序、诊断标签、排除结论、个体化处方调整或激活 BMI。

## Timing and proof boundary

本票当前只记录已确认的主人决定与后继验收输入，不提前冻结详细设计、验证合同或测试，不修改产品。Ticket 125 闭票后才对当前代码 characterization，形成唯一有限设计和独立 verifier-owned 门，并对同一 checkpoint 完成 fresh Spec／Standards 预审。届时同步现有 Spec 与验收 Module，明确区分非诊断操作预算与 full／诊断严格证明，不竞争或改写旧证据。

真实调用仍须同一 target/release/run/config 的既有精确批准和执行验证；此选择不伪造 G10/G11 passed、不授权读取健康资料或凭据，也不证明部署、初始化或主人可用。唯一部署目标继续是用户 default Hermes，不触碰 partner。医学权利与诊断激活仍归 Ticket 127，主人验收仍归 Ticket 128。
