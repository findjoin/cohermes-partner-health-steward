# 【HOW】选择健康能力入口与 Skill/Tool 契约

Type: grilling
Status: wontfix
Parent: [健康管家首发 TO、CAN 与 HOW 决策闭合路线](../map.md)
Blocked by: [【TO】确认首发健康管家的基础产品能力与不可妥协边界](53-confirm-foundational-product-capabilities-and-boundaries.md), [【CAN】核验目标 Hermes 基线与受支持的健康扩展面](42-verify-target-hermes-baseline-and-supported-extension-surface.md), [【CAN】核验健康画像数据平面的可用工具与接口](56-verify-health-data-plane-tools-and-interfaces.md), [【CAN】核验健康能力发现、调用与结果返回契约](63-verify-health-capability-discovery-invocation-and-result-contract.md), [【HOW】选择健康画像数据平面、模型调用与保护路线](49-choose-health-record-rights-and-protection-route.md), [【HOW】选择辅助诊断、医学知识与安全强制路线](50-choose-diagnostic-knowledge-and-safety-route.md), [【HOW】选择每日复盘、主动发送、恢复与运行状态路线](51-choose-daily-review-delivery-recovery-and-status-route.md), [【CAN】闭合完整能力与约束事实并形成当前 CAN 报告](77-close-complete-capability-and-constraint-report.md)

## Question

在单一健康画像、诊断安全、每日复盘、投递恢复和真实运行状态的路线都已确定后，如何把已经确认的初始化健康管家、询问健康管家、更新健康画像、导出健康画像、设置管家行为、删除健康画像和查看运行状态，映射为同一个 Hermes 中既可由自然语言触发、又能明确发现和调用的健康能力；哪些职责由可发现的 Skill 说明、Plugin Tool/Command 或自动流程承载，怎样让主人和同一个 Hermes Agent 都能调用专用画像更新并获得真实结果，同时确保模型未选择调用某项能力时也不能绕过身份、画像权利、诊断安全或失败关闭边界，且不新增第二个 Agent 或 LLM Gateway？

## Comments

### 2026-08-20 — CAN 重建期间的历史问题标记

旧身份恢复、防回滚和域外身份代际依赖已被现行 TO 取消并从 `Blocked by` 移除。本票仍处于 `needs-info` 且由完整 CAN 闭合票阻塞；其“七个入口”范围不足以覆盖当前四项职责、开放健康任务、证据准入和初始化硬闸门。完整 CAN 闭合后必须先按当时报告重写本 HOW 的 Question 与当前依赖，不能直接沿用本段旧问题进入选择。

### 2026-08-20 — 被统一 HOW 吸收

完整 CAN 已证明入口与 Skill/Tool 映射必须和初始化、微信接管、单一状态、任务、模型、安全、权利及迁移一并选择。本票未形成 `## Answer`；全部仍有效的问题由[【HOW】选择健康管家的统一技术路线、权威职责与分层验证架构](98-choose-unified-health-steward-technical-route-and-authority-architecture.md)吸收。本票停止，不计作已选路线。
