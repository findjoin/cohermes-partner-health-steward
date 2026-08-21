# 微信 iLink 与目标 Hermes 真实接口能力核验（Ticket 52）

## 1. 结论

本票可以确认的 CAN 是：**腾讯 iLink 与目标 Hermes v0.20.0 已提供面向单个微信身份的私聊收取、回复及主动调用 `sendmessage` 的技术接口，但没有提供足以证明“每条物理消息可靠处理一次”或“主人微信真实收到一次”的公开契约。**

关键边界如下：

- 腾讯公开契约把 `get_updates_buf` 定义为下轮长轮询要回传的同步游标，把 `message_id` 称为唯一消息 ID，把 `seq` 称为消息序号；但所有消息封套字段在官方 TypeScript 类型中均为可选，官方没有公布 ID 唯一性的作用域、`seq` 的单调/重置规则、重投时字段是否稳定、游标保留期、逐消息确认、至少一次、至多一次或恰好一次语义。[腾讯 v2.4.6 getUpdates 契约](https://github.com/Tencent/openclaw-weixin/blob/cef0bfc390393f716903e16d50408118047f87e0/README.md#L125-L171) [腾讯 v2.4.6 消息字段说明](https://github.com/Tencent/openclaw-weixin/blob/cef0bfc390393f716903e16d50408118047f87e0/README.md#L273-L288) [腾讯 v2.4.6 消息类型](https://github.com/Tencent/openclaw-weixin/blob/cef0bfc390393f716903e16d50408118047f87e0/src/api/types.ts#L153-L215)
- 腾讯官方客户端插件 v2.4.6 虽保留可选 `group_id`，却只宣告 `direct` 聊天能力，并把规范化入站固定成私聊；这是客户端固定实现行为，不是 iLink 服务端交付保证，不能证明普通微信群会向 iLink Bot 投递，也不能提供群成员/群会话的可靠身份语义。[官方客户端聊天能力](https://github.com/Tencent/openclaw-weixin/blob/cef0bfc390393f716903e16d50408118047f87e0/src/channel.ts#L142-L181) [官方客户端入站规范化](https://github.com/Tencent/openclaw-weixin/blob/cef0bfc390393f716903e16d50408118047f87e0/src/messaging/inbound.ts#L220-L237)
- 目标 Hermes 会先持久化整批响应的新游标，再为每条消息创建异步处理任务；消息是否完成、失败或仍在处理中不会产生逐条 ACK。进程在游标推进后、业务处理完成前中断时，该条消息处于无法确认状态。[目标轮询顺序](https://github.com/NousResearch/hermes-agent/blob/3c27eb6234bf91b8ceee9e9071591b31e9b148cb/gateway/platforms/weixin.py#L1371-L1435)
- 目标 Hermes 在主人准入和正式业务成功之前，就按 `message_id` 以及“发送身份 + 正文 MD5”写入内存去重缓存；相同正文在 300 秒内可能被静默丢弃。快速文本又会合并成首条事件，后续消息自己的 `message_id`、协议时间和原始封套不会进入合并结果。[目标去重入口](https://github.com/NousResearch/hermes-agent/blob/3c27eb6234bf91b8ceee9e9071591b31e9b148cb/gateway/platforms/weixin.py#L1437-L1472) [目标合批实现](https://github.com/NousResearch/hermes-agent/blob/3c27eb6234bf91b8ceee9e9071591b31e9b148cb/gateway/platforms/weixin.py#L1555-L1603)
- 腾讯公开的 `sendmessage` 响应类型只有可选 `ret` 与 `errmsg`，没有服务端消息 ID、客户端展示、收取或已读回执；腾讯官方客户端把非零 `ret` 当作错误，但“未报告错误”仍不是送达证明。目标 Hermes 返回的 `message_id` 是自己生成的 `client_id`。因此“接口未报错”与“主人真实收到”必须分层，不能合并为发送成功。[腾讯发送响应类型](https://github.com/Tencent/openclaw-weixin/blob/cef0bfc390393f716903e16d50408118047f87e0/src/api/types.ts#L221-L229) [腾讯官方客户端发送判定](https://github.com/Tencent/openclaw-weixin/blob/cef0bfc390393f716903e16d50408118047f87e0/src/api/api.ts#L502-L520) [目标发送结果](https://github.com/NousResearch/hermes-agent/blob/3c27eb6234bf91b8ceee9e9071591b31e9b148cb/gateway/platforms/weixin.py#L1928-L1944)

这些是接口和实现约束，不是新的 TO 取舍。目标 Hermes 的正式 Plugin 扩展面仍允许注册聊天 Adapter，所以当前没有证据证明健康管家的 TO 在 Hermes 架构内必然做不到；本票不创建 TO-CAN 差距决策，也不选择 HOW。

## 2. 证据范围与方法

- 核验日期：2026-08-16（Asia/Shanghai）。
- 腾讯基线：官方 [`openclaw-weixin` v2.4.6](https://github.com/Tencent/openclaw-weixin/releases/tag/v2.4.6)，固定提交 [`cef0bfc390393f716903e16d50408118047f87e0`](https://github.com/Tencent/openclaw-weixin/commit/cef0bfc390393f716903e16d50408118047f87e0)。
- Hermes 基线：目标现场 Hermes Agent v0.20.0（2026.8.3），固定提交 [`3c27eb6234bf91b8ceee9e9071591b31e9b148cb`](https://github.com/NousResearch/hermes-agent/commit/3c27eb6234bf91b8ceee9e9071591b31e9b148cb)。
- 现场方法：17:24（+08:00）使用现有 SSH 身份只读复核服务状态、版本、Git HEAD、目标微信 Adapter 哈希、已检查路径的工作树差异、Plugin manifest 数量和 Cron Job 数量。没有读取或输出 token、身份值、聊天正文或消息封套，没有发送消息、重启服务或修改现场。
- Evidence 07 只作为问题线索；本文重新核对了上述两个固定提交与现场状态。既有现场基线只用于交叉核对证明边界：[目标扩展面基线](02-target-hermes-extension-baseline-20260816.md) [聊天接口现场基线](03-channel-owner-provenance-capabilities-20260816.md) [运行与发送恢复基线](04-scheduling-delivery-recovery-runtime-status-capabilities-20260816.md)。

以下五个层级严格分开：

1. **腾讯公开契约**：仅限腾讯 README 与协议类型明确写出的接口合同；不把官方客户端源码行为提升为 iLink 服务端保证。
2. **固定源码行为**：分别标明腾讯官方客户端 v2.4.6 与目标 Hermes `3c27...` 的代码行为；两者都不冒充腾讯服务端保证。
3. **目标现场已只读验证**：只说明当前文件、配置元数据或进程状态，不冒充真实微信端到端结果。
4. **尚未验证**：公开资料和只读现场均不能下结论。
5. **须经主人批准的真实微信实验**：会产生微信消息、读取非正文元数据或中断现场的动作，本票只列计划，不执行。

## 3. 五层证据矩阵

| 维度 | 腾讯公开契约 | 固定源码行为（腾讯官方客户端／目标 Hermes） | 目标现场已只读验证 | 尚未验证 | 须主人批准的真实微信实验 |
|---|---|---|---|---|---|
| 私聊与身份 | 入站封套类型可带发送者/接收者 ID；公开契约没有把技术 ID 保证为现实主人身份 | 腾讯官方客户端：QR 状态类型把 `ilink_bot_id`、`ilink_user_id` 声明为可选字段，确认分支会读取二者；目标 Hermes：使用 `from_user_id` 作为发送身份，可用 allowlist 限制私聊 | 当前为单值私聊 allowlist、全开放关闭 | 技术 ID 是否就是知情授权的真实主人；身份迁移/恢复 | 主人用目标账号发送无健康内容标记，核对扫码者、发送者、allowlist 三者关系 |
| 群聊 | 消息类型中有可选 `group_id`；没有普通微信群交付保证 | 腾讯官方客户端：只声明并规范化为 `direct`；目标 Hermes：含群策略分支，但群判断不消费官方 `group_id`，并警告 iLink Bot 通常收不到普通群事件 | 当前群策略为 `disabled` | 普通微信群是否可投递、群成员身份、@ 语义 | 当前 Destination 不需要群聊；不建议实验，除非主人以后扩展范围 |
| 入站封套 | 可选 `seq`、`message_id`、发送/接收者、`client_id`、三个协议时间、`session_id`、`group_id`、消息类型/状态、items、`context_token`、`run_id` | 目标 Hermes：只提升发送者、顶层消息 ID、上下文令牌、内容/媒体；其余只暂存在 `raw_message`，文本合批后可能丢失 | Adapter 文件与固定提交哈希一致 | 目标真实消息中各字段的存在率、格式和跨重投稳定性 | 仅采集字段“存在/缺失”、类型、长度和不可逆摘要，不采集正文或实际 ID |
| 同步与确认 | `get_updates_buf` 是下轮回传的同步游标 | 腾讯官方客户端和目标 Hermes 都在处理完成前推进本地游标，均没有逐消息业务 ACK；目标 Hermes 再异步处理消息 | 服务和 Adapter 存在；未做中断探针 | 游标保留期、旧游标重放、服务端重投、崩溃窗口结果 | 需要单独维护批准的受控 canary 中断实验；当前不得做 |
| 去重与快速连发 | 未公布重投、去重或 exactly-once 合同 | 目标 Hermes：300 秒内存去重，最多 2000 个近期键；普通文本静默 3 秒、疑似长拆分静默 5 秒后合批 | 当前 Adapter 未被现场修改；合批参数未在已核验配置中覆盖 | 真实重投的 ID/序号/时间是否稳定；有意相同正文与重投能否区分 | 主人发送约定的两组无健康内容标记，核对原始 envelope 数、业务处理数和微信回复数 |
| 回复 | `sendmessage` 接收目标、上下文令牌和 item；响应可带 `ret`/`errmsg`，没有送达或展示回执 | 腾讯官方客户端：把非零 `ret` 当作错误，并返回本地 `client_id`；目标 Hermes：使用最近上下文令牌，对文本拆块、重试，也返回本地 `client_id`。[腾讯官方客户端本地消息标识](https://github.com/Tencent/openclaw-weixin/blob/cef0bfc390393f716903e16d50408118047f87e0/src/messaging/send.ts#L73-L97) | 历史日志只证明曾进入发送路径；本次未发消息 | 当前主人端展示、收取、顺序、重复、长消息拆块 | 一次无健康内容回复，主人确认可见数量和顺序 |
| 主动发送 | README 没有另设具有更强保证的“主动推送”接口 | 腾讯官方客户端与目标 Hermes 都复用 `sendmessage`；Cron/直接发送可能使用持久化上下文令牌，也可能无令牌尝试 | 当前 Cron Job 为 0，健康 Plugin 为 0 | 上下文令牌寿命、无令牌/过期令牌主动发送、主人实际到达 | 一次经批准的立即主动发送；长期静默后的能力需另定时间再测 |
| 重启与无法确认 | 没有公布逐条恢复/重投保证 | 目标 Hermes：游标和上下文令牌落盘；去重缓存、合批缓存和在途任务不落盘 | 服务 active/enabled；只证明进程状态 | 中断点位对应的丢失、重放、重复发送和在途发送结果 | 只可在获准维护窗口和可回滚 canary 中验证，不在本票执行 |

## 4. 腾讯 iLink 官方契约

### 4.1 入站、游标和字段可选性

`POST /ilink/bot/getupdates` 是 HTTP JSON 长轮询。首次请求发送空的 `get_updates_buf`，以后回传上一响应给出的值；成功响应可以包含 `msgs`、新的游标和 `longpolling_timeout_ms`。[官方接口说明](https://github.com/Tencent/openclaw-weixin/blob/cef0bfc390393f716903e16d50408118047f87e0/README.md#L125-L171)

这里出现的数值只有以下公开物理含义：

- 示例中的 `35000` 毫秒等于 35 秒，表示服务端建议下一次长轮询连接最多挂起等待多久；它不是消息处理期限、去重窗口、游标保留期或送达保证。[官方长轮询响应字段](https://github.com/Tencent/openclaw-weixin/blob/cef0bfc390393f716903e16d50408118047f87e0/README.md#L141-L171)
- `message_id` 被描述为数值型“唯一消息 ID”，但官方没有写明唯一性是在单 Bot、单会话、单账号还是全局范围内成立，也没有写明一次重投是否沿用同一值。
- `seq` 只被描述为消息序号；官方没有写明它是否连续、单调、按何种范围分配、何时重置或能否用于去重。[官方消息字段说明](https://github.com/Tencent/openclaw-weixin/blob/cef0bfc390393f716903e16d50408118047f87e0/README.md#L273-L288)
- `create_time_ms`、`update_time_ms`、`delete_time_ms` 是毫秒时间；一毫秒是千分之一秒。官方没有声明服务端时钟的可信度、精度、顺序保证或重投稳定性。
- `get_updates_buf` 在官方类型注释中是需要原样缓存和回传的完整上下文缓冲区；它是不透明的同步位置，不是公开可解释的消息 offset，更不是逐消息 ACK 或幂等键。[官方类型注释](https://github.com/Tencent/openclaw-weixin/blob/cef0bfc390393f716903e16d50408118047f87e0/src/api/types.ts#L186-L205)

`WeixinMessage` 的 `seq`、`message_id`、`from_user_id`、`to_user_id`、`client_id`、三个协议时间、`session_id`、`group_id`、`message_type`、`message_state`、`item_list`、`context_token` 和 `run_id` 全部带 `?`；item 级 `create_time_ms`、`update_time_ms` 与 `msg_id` 也都是可选。[官方完整消息类型](https://github.com/Tencent/openclaw-weixin/blob/cef0bfc390393f716903e16d50408118047f87e0/src/api/types.ts#L153-L205) 因而后续系统必须如实保留“字段缺失”，不能伪造一个微信已保证的 ID 或时间。

### 4.2 私聊、群聊与身份

腾讯官方客户端的 QR 状态类型把 `ilink_bot_id` 与扫码者的 `ilink_user_id` 声明为两个可选字段；登录确认分支会读取二者，并要求 `ilink_bot_id` 存在后才返回连接成功。账户源码也分别识别 Bot 的 `@im.bot` 与用户/对端的 `@im.wechat` 后缀。这些都是官方客户端实现读取到的身份角色，不是服务端保证每次都返回二者，也不能仅凭 Bot ID 推定主人现实身份。[QR 状态可选字段](https://github.com/Tencent/openclaw-weixin/blob/cef0bfc390393f716903e16d50408118047f87e0/src/auth/login-qr.ts#L35-L46) [登录确认分支](https://github.com/Tencent/openclaw-weixin/blob/cef0bfc390393f716903e16d50408118047f87e0/src/auth/login-qr.ts#L410-L434) [账户标识解析](https://github.com/Tencent/openclaw-weixin/blob/cef0bfc390393f716903e16d50408118047f87e0/src/auth/accounts.ts#L16-L32)

虽然原始类型含 `group_id`，腾讯官方 v2.4.6 客户端插件只发布 `chatTypes: ["direct"]`，规范化入站又把 `ChatType` 固定为 `direct`，不使用原始 `group_id`、`session_id` 或 `to_user_id` 建立群路由。[官方客户端 channel 声明](https://github.com/Tencent/openclaw-weixin/blob/cef0bfc390393f716903e16d50408118047f87e0/src/channel.ts#L142-L181) [官方客户端入站映射](https://github.com/Tencent/openclaw-weixin/blob/cef0bfc390393f716903e16d50408118047f87e0/src/messaging/inbound.ts#L220-L237) 这是客户端固定实现行为，不是服务端交付保证；当前一手资料只支持“私聊 Adapter 存在”，不支持普通微信群能力承诺。

### 4.3 腾讯官方客户端实现的恢复边界

腾讯官方 v2.4.6 客户端插件启动时加载已保存的游标；每次成功轮询后先保存新游标，再逐条 `await` 处理消息。如果某一处理器随后抛错，下一轮仍使用已经推进的游标；源码没有逐条 ACK，也没有按原游标自动请求同批消息。[官方客户端 monitor 启动顺序](https://github.com/Tencent/openclaw-weixin/blob/cef0bfc390393f716903e16d50408118047f87e0/src/monitor/monitor.ts#L64-L75) [官方客户端保存游标与处理顺序](https://github.com/Tencent/openclaw-weixin/blob/cef0bfc390393f716903e16d50408118047f87e0/src/monitor/monitor.ts#L138-L193)

这是客户端实现约束，不足以断言服务端一定丢失或一定重投。准确结论是：**腾讯官方客户端公开实现没有提供“业务处理完成后才确认”的耐久保证。**

网络/API 普通错误时，腾讯官方客户端前两次失败各等待 2 秒；第 3 次连续失败等待 30 秒并把计数归零。2 秒与 30 秒只是客户端重试节奏，3 是触发较长退避的连续失败次数，不是服务端保留或重投合同。`-14` 在 README 中只是“session timeout”示例，固定客户端实现则把它当成 token 陈旧/过期并暂停该账户 1 小时；1 小时是插件本地冷却时间，不是腾讯公布的 token 寿命，插件也没有在该分支自动换取新凭据。[腾讯公开错误字段](https://github.com/Tencent/openclaw-weixin/blob/cef0bfc390393f716903e16d50408118047f87e0/README.md#L164-L171) [官方客户端 API 错误分支](https://github.com/Tencent/openclaw-weixin/blob/cef0bfc390393f716903e16d50408118047f87e0/src/monitor/monitor.ts#L129-L147) [官方客户端异常分支](https://github.com/Tencent/openclaw-weixin/blob/cef0bfc390393f716903e16d50408118047f87e0/src/monitor/monitor.ts#L184-L205) [官方客户端 session guard](https://github.com/Tencent/openclaw-weixin/blob/cef0bfc390393f716903e16d50408118047f87e0/src/api/session-guard.ts#L2-L44)

## 5. 目标 Hermes v0.20.0 固定源码行为

### 5.1 入站确认顺序与恢复

目标 Hermes 从每个账户自己的 `*.sync.json` 读取 `get_updates_buf`，并用原子 JSON 写回新游标。[目标游标存储](https://github.com/NousResearch/hermes-agent/blob/3c27eb6234bf91b8ceee9e9071591b31e9b148cb/gateway/platforms/weixin.py#L1018-L1034)

一次成功轮询后的实际顺序是：

1. 接收整批 `msgs` 和新游标；
2. 先持久化新游标；
3. 对每条消息分别创建异步任务；
4. 异步任务中的异常只记日志，不回退游标。

[目标轮询与派发](https://github.com/NousResearch/hermes-agent/blob/3c27eb6234bf91b8ceee9e9071591b31e9b148cb/gateway/platforms/weixin.py#L1371-L1435)

因此：

- 游标保存后、某条处理完成前崩溃：本地会从新游标恢复，未完成消息是否由服务端再次提供没有公开保证，状态只能是“无法确认”。
- 接收响应后、游标成功保存前崩溃：本地仍保留旧游标，服务端是否重放以及字段是否相同仍无公开保证。
- 重启会恢复游标和最近的 per-peer `context_token`，但不会恢复内存去重表、待合批文本或正在执行的消息任务。[上下文令牌持久化](https://github.com/NousResearch/hermes-agent/blob/3c27eb6234bf91b8ceee9e9071591b31e9b148cb/gateway/platforms/weixin.py#L298-L345) [断开时清空合批](https://github.com/NousResearch/hermes-agent/blob/3c27eb6234bf91b8ceee9e9071591b31e9b148cb/gateway/platforms/weixin.py#L1346-L1366)

目标在 `-14` 或符合源码条件的 `-2/unknown error` 时等待 600 秒，即 10 分钟，然后继续轮询；600 秒只是本地暂停时间，不是会话恢复或消息保留保证。[目标陈旧会话判定](https://github.com/NousResearch/hermes-agent/blob/3c27eb6234bf91b8ceee9e9071591b31e9b148cb/gateway/platforms/weixin.py#L113-L126) [目标错误处理](https://github.com/NousResearch/hermes-agent/blob/3c27eb6234bf91b8ceee9e9071591b31e9b148cb/gateway/platforms/weixin.py#L1390-L1412)

### 5.2 身份、封套与时间映射

目标会读取 `from_user_id`、顶层 `message_id`、`context_token` 和 `item_list`；将完整上游字典暂存为 `raw_message`。标准 `MessageEvent` 的时间却是处理时本机的 `datetime.now()`，不是上游 `create_time_ms`；`seq`、`client_id`、item 级 `msg_id` 和协议时间也没有提升为标准逐条来源字段。[目标事件映射](https://github.com/NousResearch/hermes-agent/blob/3c27eb6234bf91b8ceee9e9071591b31e9b148cb/gateway/platforms/weixin.py#L1437-L1507)

群聊判断函数不读取官方 `group_id`，而尝试 `room_id`、`chat_room_id`、`to_user_id` 与 `msg_type`；这些字段组合不是腾讯 v2.4.6 公布的群聊保证。[目标群聊推断](https://github.com/NousResearch/hermes-agent/blob/3c27eb6234bf91b8ceee9e9071591b31e9b148cb/gateway/platforms/weixin.py#L391-L397) 目标自身也明确警告 QR 登录得到的是 iLink Bot 身份，通常无法进入普通微信群，群事件可能根本不会到达 Hermes。[目标连接警告](https://github.com/NousResearch/hermes-agent/blob/3c27eb6234bf91b8ceee9e9071591b31e9b148cb/gateway/platforms/weixin.py#L1333-L1343)

### 5.3 去重与快速连发合批

目标的 `MessageDeduplicator` 默认最多保留 2000 个近期键，每个键有效 300 秒。2000 是单进程内存缓存容纳的近期键数量上限，不是消息量、用户数或健康档案上限；300 秒等于 5 分钟，是本进程把同一键视为近期见过的时间，不是腾讯重投期限。键在首次检查时立即插入，缓存不持久化。[目标缓存实现](https://github.com/NousResearch/hermes-agent/blob/3c27eb6234bf91b8ceee9e9071591b31e9b148cb/gateway/platforms/helpers.py#L24-L66)

微信路径先按非空顶层 `message_id` 去重，再按“发送者 + 正文 MD5”去重；这发生在主人 allowlist 检查、媒体处理和业务处理成功之前。[目标去重顺序](https://github.com/NousResearch/hermes-agent/blob/3c27eb6234bf91b8ceee9e9071591b31e9b148cb/gateway/platforms/weixin.py#L1437-L1472) 结果是：

- 相同 `message_id` 在缓存期内会被丢弃，但官方未承诺重投 ID 稳定；
- 同一发送者 5 分钟内有意发送两条完全相同的正文，第二条也会被丢弃，即使 ID 不同；
- 进程重启后缓存为空，之前见过的重投可能再次进入；
- 当前公开证据不能同时保证“不重复处理重投”和“不吞掉主人有意重复发送”。

目标还会把同一 Hermes 会话中的快速文本合批：普通文本以最后一条到达后静默 3.0 秒为窗口；最后一条长度达到 1800 个字符时改用 5.0 秒。3.0/5.0 秒都是等待是否还有后续片段的本地静默时间；1800 是选择较长等待窗口的字符数阈值，不是微信消息上限或健康业务阈值。后续事件只追加正文和媒体列表，自己的 `message_id`、`timestamp`、`raw_message`、`seq` 与协议时间不会追加到首条事件。[目标默认合批参数](https://github.com/NousResearch/hermes-agent/blob/3c27eb6234bf91b8ceee9e9071591b31e9b148cb/gateway/platforms/weixin.py#L1246-L1259) [目标合批内容](https://github.com/NousResearch/hermes-agent/blob/3c27eb6234bf91b8ceee9e9071591b31e9b148cb/gateway/platforms/weixin.py#L1543-L1603)

### 5.4 回复、主动发送和未知结果

腾讯请求中的 `context_token` 是回复时回传的会话上下文令牌；官方没有公布寿命或主动发送刷新合同。[腾讯回复请求](https://github.com/Tencent/openclaw-weixin/blob/cef0bfc390393f716903e16d50408118047f87e0/README.md#L173-L191) 目标会把最近令牌按账户 + 对端持久化；回复和主动发送都调用同一个 `sendmessage`，不存在另一个具有更强保证的主动推送接口。[目标上下文存储](https://github.com/NousResearch/hermes-agent/blob/3c27eb6234bf91b8ceee9e9071591b31e9b148cb/gateway/platforms/weixin.py#L298-L345) [目标直接发送入口](https://github.com/NousResearch/hermes-agent/blob/3c27eb6234bf91b8ceee9e9071591b31e9b148cb/gateway/platforms/weixin.py#L2321-L2419)

固定源码会对文本生成 `hermes-weixin-<uuid>` 本地客户端 ID；接口响应没有错误时，以这个本地值作为 `SendResult.message_id`。它不是微信服务端消息 ID，更不是主人端回执。[目标文本发送结果](https://github.com/NousResearch/hermes-agent/blob/3c27eb6234bf91b8ceee9e9071591b31e9b148cb/gateway/platforms/weixin.py#L1928-L1944)

默认发送参数的物理含义如下：[目标常量](https://github.com/NousResearch/hermes-agent/blob/3c27eb6234bf91b8ceee9e9071591b31e9b148cb/gateway/platforms/weixin.py#L105-L115) [目标发送参数](https://github.com/NousResearch/hermes-agent/blob/3c27eb6234bf91b8ceee9e9071591b31e9b148cb/gateway/platforms/weixin.py#L1178-L1227) [目标发送 API 超时应用](https://github.com/NousResearch/hermes-agent/blob/3c27eb6234bf91b8ceee9e9071591b31e9b148cb/gateway/platforms/weixin.py#L468-L502) [目标重试循环](https://github.com/NousResearch/hermes-agent/blob/3c27eb6234bf91b8ceee9e9071591b31e9b148cb/gateway/platforms/weixin.py#L1760-L1877)

- 2000 个字符是 Hermes 对单个出站文本块采用的本地上限；不是微信客户端展示保证。
- 1.5 秒是连续文本块之间的本地发送间隔；不是收件顺序确认。
- `send_chunk_retries=4` 表示初次请求失败后最多再试 4 次，即一个块最多发起 5 次 API 尝试。
- 普通失败的基础延迟为 1.0 秒，随后按第几次失败等待 1、2、3、4 秒。遇到源码判定的频率限制时，只有在该事件尚未触发熔断且仍可重试时，才等待 3 倍基础延迟，即 3 秒；默认熔断阈值为 1，因此默认配置下首个频率限制事件会直接打开 30 秒熔断并结束该块的重试循环，不会走 3 秒等待分支。这些都只是本地控制节奏。
- 单次普通 API 超时为 15000 毫秒，即本地最多等待 HTTP 调用 15 秒；超时不能证明服务端此前没有接受请求。
- 默认频率限制熔断阈值是 30 秒窗口内 1 次事件，打开 30 秒；1 是触发熔断的事件数，两个 30 秒分别是统计窗口和本地拒绝后续发送的冷却时间，不是腾讯限流配额。

重试沿用同一 `client_id`，但腾讯没有公布 `client_id` 的幂等保证。因此网络超时或进程中断会产生两种都无法排除的结果：请求未被接受，或请求已被接受但本地没拿到响应；盲目重发可能重复。目标在令牌过期分支还会去掉 `context_token` 再试一次，这是固定源码行为，不是腾讯公开保证无令牌主动发送必然可用。[目标无令牌重试](https://github.com/NousResearch/hermes-agent/blob/3c27eb6234bf91b8ceee9e9071591b31e9b148cb/gateway/platforms/weixin.py#L1760-L1828)

## 6. 当前目标现场：只读已验证与证明边界

2026-08-16 17:24（+08:00）只读复核得到：

| 项目 | 当前事实 | 不能证明什么 |
|---|---|---|
| Partner 服务 | `active`、`enabled`；主进程仍是 2026-08-07 启动的进程 | 不能证明 iLink 当前会话有效、消息正在轮询或主人能收到 |
| Hermes 版本 | v0.20.0（2026.8.3），HEAD 为 `3c27...48cb` | 不能套用更新版本或 `main` 的行为 |
| 微信 Adapter | SHA-256 为 `e745f2bc7faaa6bbbdd8615fbfc79ca327ca6d0e7700620f37fc21fed14a178a`，与 HEAD 相同 | 只证明该文件没有现场脏改，不证明服务端契约 |
| 已检查的相关源码差异 | 只有 `gateway/run.py` 属于现场未提交修改；微信 Adapter 未修改 | 本地披露/通知改动不能冒充微信可靠性或健康能力 |
| 健康 Plugin | profile 中 Plugin manifest 数量为 0 | 当前没有健康插件运行，更没有主人可见健康状态 |
| Cron | Job 数量为 0 | 当前没有每日复盘或健康主动发送 |

当前允许入口仍收敛为一个私聊 allowlist，群聊关闭、全开放关闭；这只证明技术准入配置，不证明该身份已经由主人完成产品级绑定。既有日志曾证明消息到达 Adapter 并进入发送路径，但没有主人端展示/收取/已读回执；本票没有新增任何真实微信消息，因此不能把历史链扩大为 2026-08-16 当前端到端可用。[既有现场边界](03-channel-owner-provenance-capabilities-20260816.md#L60-L89)

## 7. 尚未验证的事实

以下结论目前都不能写成“支持”或“保证”：

1. 普通微信群是否会向目标 iLink Bot 交付事件，以及群成员、群会话和 @ 的身份语义。
2. 真实主人每种消息的 `message_id`、`seq`、协议时间、item 级 `msg_id`、`session_id`、`group_id`、`client_id` 和 `context_token` 实际存在率与格式。
3. 一次逻辑消息重投时，上述字段是否保持不变；游标推进前后服务端会重投、保留还是跳过哪些消息。
4. 主人有意发送两条相同正文与服务端重复投递能否被可靠区分。
5. `context_token` 的真实寿命、过期错误形态、无令牌主动发送和令牌刷新语义。
6. HTTP/JSON 返回无错误后，主人微信是否展示、何时展示、是否只展示一次，以及是否存在收取或已读回执。
7. 目标进程在游标保存、处理、模型调用或发送各中断点重启后的真实丢失、重放与未知状态。
8. 当前目标 iLink 会话在本票核验时是否仍可完成新的请求—回复和主动发送闭环。

## 8. 需要主人另行批准的最小真实实验

本节不是授权。每个实验必须单独获得主人批准，且只使用无健康含义的约定标记。

### 实验 A：主人身份与私聊封套

- 目的：确认真实主人账号、扫码者身份、`from_user_id` 和当前 allowlist 的关系；统计字段存在/缺失。
- 动作：主人从目标微信私聊发送 1 条约定标记；测试入口只记录字段名称、类型、长度、协议时间是否存在和 ID 的不可逆摘要，不记录正文、token 或原始身份值。
- 外部影响：产生 1 条微信入站；会接触该条非健康消息的元数据。
- 停止条件：接收身份不符、出现群来源、正文或真实 ID 即将进入报告、或目标产生非预期回复时立即停止。

### 实验 B：有意重复与快速连发

- 目的：区分主人有意相同正文、快速不同正文与 Adapter 合批/去重结果。
- 动作：主人按约定发送两组非健康标记：一组是快速发送的两条不同文本，一组是快速发送的两条相同文本；逐 envelope 比较可选 ID、序号和时间的不可逆摘要，并统计进入业务处理和回复的数量。
- 外部影响：产生 4 条微信入站及最多 2 轮 Bot 回复；可能暴露当前实现吞掉相同正文或合并多条文本的既有行为。
- 停止条件：出现重复主动回复、回复到错误身份、任何内容跨会话、或观察代码需要写入健康数据时立即停止。

### 实验 C：接口接受与主人真实收到

- 目的：把回复、立即主动发送的 API 结果与主人端可见结果对齐。
- 动作：在 A 成功后各发送 1 条无健康含义且带不同标记的回复和主动消息；系统记录 API 结果类别与本地 `client_id` 摘要，主人只确认看到的数量、顺序和大致时间，不提供聊天截图或正文。
- 外部影响：向主人微信发送 2 条测试消息。
- 停止条件：任一 API 返回未知/超时、出现多于预期的消息、顺序异常、发送对象无法确认或主人要求停止。

### 实验 D：游标、重启与在途未知

- 目的：验证游标保存后处理未完成、以及发送请求在途时中断的真实结果。
- 动作：只能在独立可回滚 canary、已批准维护窗口和无健康数据条件下，通过受控闸门暂停处理或发送，再执行一次明确的进程中断与恢复；主人只发送/接收约定标记。
- 外部影响：会主动中断目标 canary、可能造成标记消息丢失或重复，并产生维护窗口。
- 停止条件：无法证明目标是隔离 canary、回滚点不可用、影响现有 Partner/default Hermes、需要查看真实聊天正文、或出现任何非测试消息时不得开始或立即停止。

群聊不属于当前 Destination，腾讯官方客户端固定实现也没有给出群能力；因此本票不建议为群聊引入额外真实实验或隐私暴露。

## 9. 对后续 HOW 的 CAN 约束（不选择实现）

1. 后续不得把腾讯官方客户端插件或目标 Hermes 的标准事件当成完整逐条来源：原始 envelope 的可用字段必须在正文去重和文本合批之前仍可逐条审计；缺失必须保留为缺失。
2. 不得以正文指纹单独判定重投，也不得宣称 `message_id`、`seq`、协议时间或 cursor 任一字段具有腾讯未公布的 exactly-once 语义。
3. 任何接收流程都必须显式表达“尚未业务处理”“处理失败/无法确认”和“已完成”；推进 poll cursor 不能冒充业务完成确认。
4. 任何发送流程都必须把“接口拒绝”“接口未报告错误”“结果无法确认”和“主人已在微信确认看到”分开；本地 `client_id` 不能冒充微信回执。
5. 主动发送必须沿用同一不确定性边界；持久化 `context_token` 不等于它仍有效，无令牌重试也不是腾讯保证。
6. 重启恢复不能依赖内存去重或合批状态；在途接收和发送必须允许标记为无法确认，禁止因缺少证据而自动写成成功。
7. 当前产品只要求私聊主人，群聊应保持无权访问；现有资料不足以支持普通微信群能力，不得为迁就接口而改写主人身份边界。
8. 目标 Hermes 仍有正式 Plugin/Adapter 扩展空间，所以当前是 HOW 受约束而非 TO 被证明不可行。若后续要求同时禁止任何能在现有去重/合批前接触 envelope 的受支持扩展位置，才需要建立 TO-CAN 差距决策。

本报告没有选择 Adapter、存储、去重、发送、恢复或验收实现，没有修改目标现场，也没有执行真实微信实验。
