# 125 - 实现 Partner 首跳模型与治理知识 Adapter

Type: task
Status: ready-for-agent
Parent: [健康管家首发 TO、CAN 与 HOW 决策闭合路线](../map.md)
Blocked by: [123 - 实现生产 health-core 与 CorePort 服务](123-implement-production-health-core-and-coreport-service.md)
Unblocks: [127 - 取得医学内容权利与专业审核](127-obtain-medical-content-rights-and-review.md), [128 - 部署并完成主人产品验收](128-deploy-and-complete-owner-product-acceptance.md)

**What to build:** 为既有 `StrictModelAdapter` 实现当前 Partner 首跳的生产 Adapter，并把 `KnowledgePublisher` 的不可变发布物装配进生产组合根。模型只执行 Core 已授权的 exact intent；Adapter 不直接读取数据库、决定诊断或写健康状态。

## Bounded acceptance

- 通过 Ticket 118 capability-profile builder 绑定 provider、canonical base URL、API mode、requested model、允许 actual-model identity/alias、config generation、共同上下文下界、包装开销和输出预留。
- 最终 wire payload 在调用前执行容量和接收方门；profile 缺失／过期／漂移、actual model 不允许、fallback、结构不完整或终态未知均失败关闭。
- completed、incomplete、failed、unknown、actual model、usage 和 result identity 分层回交现有 Core；unknown 不自动重调模型。
- 禁止主人派生 Web Search、MCP、普通 Tool、任意 HTTP 和跨 provider/base URL fallback；知识发布不包含主人资料。
- synthetic Adapter 先通过 Ticket 119 G06；真实模型只在 G10 对同一 target/release/config generation 的 profile 通过且 G11 单独批准后，用最小合成／脱敏输入执行。

## Not in this ticket

不取得医学许可或审核，不激活 BMI，不实现微信投递，不改变 StrictHealthLLM 或非诊断回答的业务语义。

## Delivery discipline

冻结设计只覆盖 Adapter、profile currentness 和终态映射；不重新设计模型路线。通过后普通提交并推送，真实模型凭据和 transcript 不进入仓库、日志或聊天。
