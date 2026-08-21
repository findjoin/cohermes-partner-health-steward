# 【HOW】选择健康管家在 Hermes 中的单一执行与权威路线

Type: grilling
Status: resolved
Parent: [健康管家首发 TO、CAN 与 HOW 决策闭合路线](../map.md)
Blocked by: [【CAN】核验目标 Hermes 基线与受支持的健康扩展面](42-verify-target-hermes-baseline-and-supported-extension-surface.md), [【CAN】核验聊天接口、主人身份与逐条消息来源能力](43-verify-channel-owner-identity-and-message-provenance-capabilities.md), [【CAN】核验每日复盘、发送恢复与运行状态能力](44-verify-scheduling-delivery-recovery-and-runtime-status-capabilities.md), [【CAN】核验健康画像、数据权利与保护能力](45-verify-health-record-data-rights-and-protection-capabilities.md), [【CAN】核验辅助诊断、医学知识与安全边界能力](46-verify-diagnostic-reasoning-knowledge-and-safety-capabilities.md)

## Question

在已完成的目标 Hermes CAN 核验内，健康消息进入、健康状态读写、辅助诊断与安全处理、每日复盘和回复发送分别由哪一类 Hermes 扩展职责承接，哪一个组件拥有唯一健康状态与处理结果权威；怎样划定健康路径与普通 Agent 的边界，使健康路径不可用时失败关闭且不会退回不受控的普通健康处理，同时避免形成第二套 Agent、第二份健康画像或竞争性运行状态？

## Comments

### 2026-08-16 — Grilling Round 1

主人明确产品形态：现有 Partner Hermes 仍是唯一智能体，只是在该 Hermes 中安装一项设计好的健康管理能力；不创建第二个健康 Agent 或另一套产品。`Adapter` 与 `Cron` 是需要由 Agent 解释的 Hermes 内部实现词，不是主人要使用或理解的独立产品功能。具体内部职责继续用用户可见行为来确认。

### 2026-08-16 — Grilling Round 2

主人确认：消息涉及健康而健康管理能力不可用时，Hermes 停止本次健康处理，明确说明当前无法安全处理且没有记录，不得退回普通聊天继续给出健康建议；明确无关健康的普通聊天仍可继续。

### 2026-08-16 — Grilling Round 3

主人确认：每条授权私聊先判断是否属于健康处理；明确非健康内容才进入普通聊天，健康、混合或无法确定的内容只产生一个受控健康回复。安装的健康管理能力是健康档案、主人控制状态、诊断与复盘结果以及健康管家运行状态的唯一权威，普通聊天历史、Memory、聊天接入和定时触发均不能形成第二份权威。主人同时明确：健康内容调用安装在同一个 Hermes 中的健康插件，再由该 Hermes 自己完成模型处理；不得新增独立 LLM 网关。

## Answer

健康管家采用“同一个 Partner Hermes 安装一项健康管理能力”的路线。它不是第二个 Agent、独立 sidecar 或另一套产品；主人始终面对同一个 Hermes 和同一个人格。该能力由同一 Hermes 内的正式健康 Plugin 承担可执行职责，配套 Skill 只提供可检查的流程说明或知识，不拥有状态，也不充当安全闸门。

健康 Plugin 是唯一健康执行与最终裁决边界：只有它可以读取或修改同一健康画像与主人控制状态、组织健康问答和诊断性判断、承接每日复盘与主动支持、批准最终健康处理结果并汇总健康管家运行状态。普通聊天历史与通用 Memory 不是健康画像，聊天接入只负责收发，定时能力只负责触发；它们均不能独立写入健康资料、产生健康结果或宣称画像更新、复盘和运行正常。具体健康画像介质、接口适配、任务和状态实现仍由后续票决定。

每条已授权私聊都必须先经过健康准入。明确不涉及健康处理的消息才交给普通聊天；涉及健康、同时包含健康与普通内容或无法确定的消息，整条只进入健康能力并只产生一个最终回复，普通聊天不得并行回答。健康能力不可用，或无法确认授权、必要来源、权威状态或安全完成时，本次健康处理失败关闭：不读写档案、不产生诊断或用药建议、不表示已经记录，并向主人如实说明当前无法安全处理且没有记录。明确非健康聊天仍可继续；不能确认非健康的消息不得降级到普通聊天。

健康 Plugin 调用 Hermes 自己受支持的模型能力完成推理，仍使用同一个 Hermes 运行实例；不得为健康能力新增独立 LLM Gateway、独立健康模型服务、独立 provider 入口或另一套模型认证。Plugin 负责选择最小健康上下文、应用健康规则、检查结果并决定是否提交和发送，不能把健康消息重新交给不受控的普通聊天模型路径。当前 provider 以后若发生变化，仍受既定健康数据接收方重新同意边界约束。

后续 [选择聊天接入、主人授权与逐条来源路线](48-choose-channel-identity-and-provenance-route.md) 只决定逐条接入和放行机制；[选择单一健康画像、主人权利与保护路线](49-choose-health-record-rights-and-protection-route.md) 决定同一健康画像与主人控制状态的具体承载；[选择辅助诊断、医学知识与安全强制路线](50-choose-diagnostic-knowledge-and-safety-route.md) 决定同一 Hermes 内的受控推理和安全检查；[选择每日复盘、主动发送、恢复与运行状态路线](51-choose-daily-review-delivery-recovery-and-status-route.md) 决定触发、投递、恢复与状态聚合。它们不得重新打开本票已确认的单 Hermes、单健康权威和无独立 LLM Gateway 边界。
