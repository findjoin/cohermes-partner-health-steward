# 【TO】决定健康模型接收方锁定缺口下的产品承诺边界

Type: grilling
Status: resolved
Parent: [健康管家首发 TO、CAN 与 HOW 决策闭合路线](../map.md)
Blocked by: [【CAN】核验健康模型调用与全部实际接收方事前锁定能力](57-verify-health-model-routing-and-recipient-preflight-capabilities.md)

## Question

CAN 已确认：在当前 Hermes v0.20.0、正式 Plugin 接口、同一 Hermes 模型能力和 JOJO relay 路线内，没有受支持接口能够同时保证健康正文不进入普通历史，并在发送前锁定全部实际数据接收方。主人需要决定如何处理这一差距：

1. 保持现有产品承诺与“仍由同一个 Hermes 处理”的原则，允许后续 CAN/Prototype 评估同一 Hermes 内能够闭合该合同的路线，包括升级 Hermes、为 Hermes 宿主补充最小模型调用接口，或把该 Hermes 改为可证明接收方且可强制路由的直接 provider；健康 Plugin 最终必须获得无普通历史、禁用 fallback、锁定 endpoint/接收方且失败关闭的宿主能力，仍不新增独立 Agent、LLM Gateway 或健康专用的另一套 provider/auth。
2. 保持当前未修改的 Hermes v0.20.0 与 JOJO 动态路由，向主人明确披露 JOJO 是第一跳、平台存在动态路由，并且实际下游身份与留存目前无法事前确定，再取得主人对这种不确定性的同意；这会明确降低“实际接收方变化时重新同意”的既定产品承诺。
3. 同时保持现有产品承诺和当前技术边界，把健康模型处理与产品上线设为 No-Go，直到 Hermes 或 relay 提供所需正式合同。

本票只决定保持或改变哪一项边界，不选择具体 core patch、升级版本、provider、endpoint 或实现方案。若选择第一项，后续先新建针对候选 Hermes 宿主接口的 CAN/Prototype，再回到 HOW；若选择第二项，必须明确更新对应 TO 与知情同意边界；若选择第三项，相关 HOW 与上线票保持阻塞。

## Comments

### 2026-08-17 — Claimed

本票已认领。当前只解决 CAN 已确认缺口后的边界选择；不重新研究接口、不选择具体 HOW，也不把当前工具限制静默写回 TO。

## Answer

主人确认：健康 Plugin 不需要锁定某一个具体模型，也不需要在发送前枚举 JOJO 内部最终采用的模型、运行节点或其他下游。健康 Plugin 始终使用同一个 Partner Hermes 当前配置的模型能力；Hermes 配置什么模型路线，健康 Plugin 就沿用该路线及其正常路由与故障切换，不自行选择另一套模型、provider、认证或 LLM Gateway。

知情同意以 Hermes 当前配置的模型服务路线为边界：启用时向主人说明当前首跳模型服务商以及该路线可能存在正常路由或故障切换；服务内部最终模型、节点、模型版本或一次调用的实际路由变化，不单独视为健康数据接收方变化，也不要求逐次重新同意。只有 Hermes 被改为另一条首跳模型服务路线时，新的健康处理才暂停，直至重新告知主人并取得同意。

因此，[核验健康模型调用与实际接收方事前锁定能力](57-verify-health-model-routing-and-recipient-preflight-capabilities.md)关于“无法锁定全部最终下游”的负向 CAN 结论仍是事实，但“锁定全部最终下游”不再是当前产品合同，不能继续阻塞 HOW。后续 [选择单一健康画像、主人权利与保护路线](49-choose-health-record-rights-and-protection-route.md)可以采用固定源码已证明不会自动写入普通 Session/Memory 的 `ctx.llm` 作为同一 Hermes 的模型调用入口；端到端日志、入站与备份隔离仍由该 HOW 票选择并验证，同时继续遵守不得新增独立健康模型路线以及首跳模型服务路线变化时重新同意的边界。
