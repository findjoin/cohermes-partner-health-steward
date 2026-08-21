# 【CAN】核验健康模型调用与全部实际接收方事前锁定能力

Type: research
Status: resolved
Parent: [健康管家首发 TO、CAN 与 HOW 决策闭合路线](../map.md)
Blocked by: [【CAN】核验健康画像数据平面的可用工具与接口](56-verify-health-data-plane-tools-and-interfaces.md)

## Question

在“不新增独立 Agent 或 LLM Gateway、仍由同一个 Partner Hermes 使用自身模型能力”的既定边界内，核验目标 Hermes v0.20.0 与目标现场是否存在一条受支持且实际可用的健康模型调用路线，能够同时做到：健康正文不进入普通 Session、Memory、全文索引或通用日志；在任何健康内容离开本机前确定并强制限制 provider、endpoint、fallback 以及会接收内容的 relay/下游集合；路由或接收方无法证明时失败关闭，而不是先发送后审计。

研究必须逐项核对 `ctx.llm`、普通 Agent/Tool、Plugin Command/direct dispatch、目标现有 provider client/configuration surface，以及同一 Hermes 内任何官方支持的直连或禁用 fallback 机制；分开记录官方保证、固定源码行为、目标现场配置、relay/下游一手证据、仍未知和需主人批准的真实请求或故障注入。不得读取 secret、聊天或健康正文，不得发送模型/微信请求，不得修改目标或选择 HOW，也不得把导入 Hermes 私有内部模块的一般 Python 可行性冒充受支持接口。

若不存在同时满足两项硬条件的受支持路线，Answer 必须给出明确负向结论和最小不可满足原因，以便新建 TO-CAN 差距决策；不得在本票中静默放宽接收方知情同意或普通历史隔离目标。

## Answer

结论为负向：目标 Partner Hermes v0.20.0 / commit `3c27eb6234bf91b8ceee9e9071591b31e9b148cb` 与当前 JOJO relay 路线中，没有一条已验证、受支持且实际可用的接口，能够同时保证健康正文不进入普通 Session、Memory、全文索引或通用日志，并在正文离开本机前锁定 provider、endpoint、Hermes fallback 与 relay 的全部真实下游接收方。

正式 Plugin 的 `ctx.llm` 是唯一受支持的 out-of-band 模型调用面。它不自动创建普通 Session，但公开参数只有名义 provider/model/agent/profile 等 override，没有 endpoint、禁用 fallback、route preview、实际接收方允许表或发送前回调；固定源码还会在额度、连接、限流、模型不兼容或无效响应等容量类失败时绕过显式 provider 限制并尝试 fallback。Plugin command、Adapter 前置处理与 `ctx.dispatch_tool` 可以不进入普通 Session，却自身不提供模型 completion；普通 Agent/Tool 有模型调用但会写入普通 Session/FTS，并可能进入 Memory。`register_auxiliary_task` 只注册配置槽位；直接导入 private `auxiliary_client.call_llm`、新建 `AIAgent`/API server 或自带 provider client 不能冒充符合既定架构的正式 Plugin 接口。

同日现场只读证据确认名义第一跳为 provider `jojo`、endpoint `https://max2.jojocode.com/v1`、API mode `codex_responses`，但这不证明 relay 下游；JOJO 当前公开 FAQ 还把 `max.jojocode.com/v1` 列为包月对话地址、把 `max2.jojocode.com/v1` 列为包月生图地址，现场用途与公开说明并不一致，尚无一手合同解释。JOJO 自己的公开资料说明其使用智能故障转移、动态模型路由并按最终模型记录用量；在核对的官方主页、FAQ、状态与支持页面中没有找到发送前下游清单、可强制的下游允许表/禁路由参数，或覆盖请求正文的留存、删除与不训练承诺。真实请求只能证明一次调用结果，不能补出全部候选和合同边界。

因此 Ticket 57 的 CAN 问题已以负向答案闭合，但 Ticket 49 仍不得进入 HOW。必须先创建 TO-CAN 差距决策，由主人决定保持既定接收方承诺时允许怎样扩大技术路线，或是否修改产品承诺；本票不替主人选择，也没有静默把“名义 JOJO relay”改写成“全部实际健康数据接收方”。完整逐项接口、源码、现场、relay 一手证据、未知项与需审批实验见 [健康模型路由与实际接收方事前锁定核验](../evidence/11-health-model-routing-and-recipient-preflight-20260817.md)。

## Comments

### 2026-08-17 — 继承权威说明

本票仍权威回答其原 Question：目标路线不能在发送前锁定全部实际下游接收方；`## Answer` 不回写。但“全部最终下游事前锁定”已不再是当前 TO，当前产品合同由 [【TO】决定健康模型接收方锁定缺口下的产品承诺边界](58-decide-health-model-recipient-lock-gap-boundary.md) 确定为首跳模型服务路线及其正常内部路由与故障切换，[【HOW】选择健康画像数据平面、模型调用与保护路线](49-choose-health-record-rights-and-protection-route.md) 已据此闭合。本票不再阻塞 HOW，也不得单独冒充当前接收方合同。
