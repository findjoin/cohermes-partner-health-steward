# 125 - 实现 Partner 首跳模型与治理知识 Adapter

Type: task
Status: claimed
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

## 2026-10-18 pre-code checkpoint candidate

用户已要求完成项目；本轮在保留 Windows 原文件的可写整合分支承接本票。基线 `19417da` 已整合生产 core 的 `c9b0d64` 与非诊断里程碑 `b32649c`。

- 唯一设计：`../design/125-production-model-design.md`。
- 独立 verification authority：`implementation_audit`；合同 `../design/125-frozen-verification-contract.md`；门 `../../../tests/test_ticket125_partner_model.py`。
- characterization：既有 StrictPort 32/32 绿色；nonsynthetic profile 无生产计量策略时 capacity-unavailable、0 调用；model_adapter 尚不存在。
- 预期红灯：新门 4 failures、0 errors/skips，根因均为公开生产 Adapter 尚不存在。尚未授权生产编码，等待同一 commit/tree 的 fresh-context Spec/Standards 预审。
- 真实模型、配置、批准、容量依据和医学内容未被测试 fixture 冒充；任何未获目标证明的真实路径继续失败关闭。

## Frozen implementation authority (2026-10-18)

- reviewed pre-code commit: `5f5286cfdddb358baec14a4bee17c2fa7f85417f`; tree `2ef6d576519f69485de297b4dac0f794ce7cbc7b`。
- Fresh-context Spec: PASS；Fresh-context Standards: PASS；证据见 `../evidence/39-ticket125-precode-review-20261018.md`。
- `.scratch/partner-health-steward/design/125-production-model-design.md` blob: `7cc317bd2c98a88b40024d355f7bde9b25224643`。
- `.scratch/partner-health-steward/design/125-frozen-verification-contract.md` blob: `e4ed2a9eb90f20880bc0cb632920e126368b47d2`。
- `tests/test_ticket125_partner_model.py` blob: `35519de98288911c4902db209245e4999fd7db63`。
- 独立 verifier-owned 四门仍是缺公开生产 Module 的预期四红；既有 StrictPort 32/32，119+StrictPort 39/39 绿色。全量首次本机运行的阻塞来自正式 Linux/root/runtime/pinned-source 环境未装配，不把它们写成通过。
- 允许在这份冻结设计内实现 `model_adapter.py`、`model_contract.py`、必要的 `answer_resolution.py` 原因闭集和既有 Core 报告接缝；不改冻结三件套，不改变 wire/业务权威，不接真实模型。实现验证后另做执行门和独立实施后审查，不能自行关闭本票。
