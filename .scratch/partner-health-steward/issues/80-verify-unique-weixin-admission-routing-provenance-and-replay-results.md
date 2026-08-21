# 【CAN】核验唯一微信准入、排他分流、逐次来源与重投结果能力

Type: research
Status: resolved
Parent: [健康管家首发 TO、CAN 与 HOW 决策闭合路线](../map.md)
Blocked by: [【CAN】核验当前 Partner Hermes 基线、Plugin 生命周期与可信执行边界](78-verify-current-partner-hermes-baseline-plugin-lifecycle-and-trust-boundary.md), [【CAN】核验健康能力入口、初始化门禁与真实结果返回能力](79-verify-health-capability-entry-initialization-gate-and-result-contract.md)

## Question

针对单人专用 Hermes 的唯一获准微信私聊入口，当前 iLink、目标 Hermes Adapter、allowlist、群聊/全开放开关和所有其他人类入口能否共同证明：只有一个技术私聊入口能够到达健康能力，其他私聊、群聊或旁路入口不读取、不回复、不保存健康内容；初始化前由基础 Hermes 处理普通聊天，初始化后健康、混合或无法排除健康风险的整条消息只产生一个受控健康结果，健康处理不可用时也不回退普通聊天？

本票还要核验每次实际投递在正文去重、快速合批、游标推进和普通会话写入前可获得并持久关联哪些真实来源事实；两次相同正文能否保留为两次来源而冻结未经判断的重复画像、任务、诊断、回复或外部效果；接管、业务提交、回复形成、接口接受、主人真实看到和处理结果无法确认能否分层。消息字段缺失不得伪造，接口无报错、本地标识或静态源码不得冒充真实送达、恰好一次或端到端成功。

固定协议与源码只证明候选路径；真实入站、回复、重投、断线/重启、游标和主人实际看到若需要微信 canary，必须先取得主人对具体消息、时间、外部写入和停止条件的批准。本票不选择 Adapter、Hook、消息字段或幂等实现 HOW。

## Comments

### 2026-08-20 — 由完整 TO 能力链重建创建

本票对应[【CAN】重建完整 TO 的能力链与追溯关系](76-rebuild-complete-to-capability-chain-and-traceability.md)中的 C03。

本票重建[【CAN】核验聊天接口、主人身份与逐条消息来源能力](43-verify-channel-owner-identity-and-message-provenance-capabilities.md)，条件继承[【CAN】核验微信 iLink 与目标 Hermes 的真实接口能力](52-verify-weixin-ilink-and-target-hermes-interface-capabilities.md)的固定接口事实，并明确取消真人身份核验、账号迁移和恢复问题。

## Answer

完整调查与引用见[《唯一微信准入、排他分流、逐次来源与重投结果能力》](../evidence/21-unique-weixin-admission-routing-provenance-replay-results-20260820.md)。本轮只读取固定协议、固定源码、当前仓库候选与目标 Partner 的脱敏配置；没有发送微信消息、调用模型、重启服务、制造重投或修改现场。

2026-08-20 13:31 的当前静态配置确认为：Weixin 使用私聊 allowlist，允许值去重计数为 1，Weixin 与全局全开放均关闭，群策略为 disabled，群允许清单为空。这个结果只证明一个技术微信私聊值通过当前准入配置；同一次静态读取还显示 Telegram configured、enabled 且其允许清单计数也为 1，CLI/chat、Command、Tool、Cron、主动发送和内部 dispatch 等原语仍存在，而当前没有健康 Plugin、初始化权威状态或业务 Cron。同日网络快照没有发现归属于 Partner PID 的 TCP/Unix listener，所以不能声称 API 当前启用；固定源码中的 API Adapter 仍是未来健康能力需要收敛的候选入口。因此不能由单值 Weixin 配置推出“只有微信能到达健康能力”，也不能证明初始化后所有健康、混合或无法排除健康风险的消息都会排他进入健康路径。

固定内置 Weixin 路径还与逐次来源合同存在确定性不匹配：它在 DM/group 准入之前已经提取正文并写入短期“发送身份 + 正文”指纹，所以准入外消息虽不会形成后续聊天事件、下载媒体或得到该分支回复，却不能表述为正文完全未读、没有任何内容派生留痕。群策略只会阻止被当前 classifier 认出的群事件，而 classifier 没有直接使用官方封套中的 `group_id`。整批 cursor 又在单条异步处理前保存；相同正文可能在第二个事件形成前被静默去重，快速文本合批只保留第一条事件的来源，进程重启后内存去重则会消失。当前路径因此既不能保留每次实际投递的真实来源，也不能可靠冻结重复画像、任务、诊断、回复或外部效果。

出站 `success` 也只表示 iLink 请求链没有报告错误；返回的消息标识是 Hermes 本地产生的 `client_id`，不是微信服务端送达、展示或已读回执。接管、权威业务提交、回复形成、接口接受、主人实际看到以及处理结果无法确认必须分别证明，不能由 cursor、handler 无异常、本地标识或单一成功字符串互相替代。

结论：C03 在当前 Partner 中**未实现且未证明**。Hermes 提供 allowlist、群策略和可覆盖内置 Weixin 的 Plugin Adapter 等候选扩展能力，但当前仓库候选的 owner/viewer 两配置槽未被强制归一为一个唯一允许值，还存在跨入口健康投影以及分类失败回退普通聊天等反例，不能继承为现行能力。该负向 CAN 不降低任何 TO，也不选择 Adapter、Hook、来源字段、存储、去重、重试或发送 HOW。只有在后续形成实际候选后，才值得另行取得主人批准，用限定消息、时间、外部写入和停止条件验证负向准入、两次相同正文、快速连发、断线/重启、接口接受与主人实际看到。
