# 唯一微信准入、排他分流、逐次来源与重投结果能力（Ticket 80）

## Answer

截至本票可定位的最新目标快照，**当前 Partner Hermes 不能证明 C03 已经闭合，也不存在已部署的健康能力可完成真实接管实验**：2026-08-20 12:41–12:49（Asia/Shanghai）的正式 Partner 仍为 Hermes v0.20.0、固定提交 `3c27eb6234bf91b8ceee9e9071591b31e9b148cb`；目标 Weixin Adapter 与该提交一致，但 ordinary/user/project Plugin 为零、profile Plugin manifest 为零、业务 Cron 为零，Telegram 与 Weixin 两个聊天平台同时 configured。[L1] 13:31 的补充脱敏只读探针进一步确认：Weixin 当前为 `dm_policy=allowlist`、允许清单去重计数 1、Weixin 与全局 allow-all 均为 false、`group_policy=disabled`、群允许清单计数 0；Telegram 则同时为 configured=true、enabled=true、allow-all=false、允许清单去重计数 1。[L2]

固定 Hermes 确有私聊 allowlist、群策略及 Plugin Adapter 覆盖内置 Adapter 的扩展原语，当前 Weixin 技术配置也确实收敛为一个允许值且关闭全部已查全开放开关。[F3][F5][L2] 但内置路径会在准入判断前提取正文并写入短期内存正文指纹，因此只能证明被拒来源不会形成后续 `MessageEvent`，不能证明正文完全未读或没有任何内容派生留痕。[F2][F3] `group_policy=disabled` 还只覆盖被当前 classifier 认出的群事件，而 13:31 静态配置显示 Telegram 是另一个 configured、enabled 且有一个允许值的人类消息入口；CLI/chat、Command、Tool、Cron、`send` 和内部 dispatch 等入口也仍存在。[F10][L1][L2] 同日网络快照没有发现归属于 Partner PID 的 TCP/Unix listener，所以不能声称 Partner API 当前启用；固定源码仍有 `APIServerAdapter` 构造面，API 只能作为未来健康能力也必须收敛的候选入口。[L1][F14] 当前没有健康 Plugin 把这些路径统一收敛到初始化与健康边界，所以**“单值 Weixin DM 配置成立”不等于“只有微信能到达健康能力”**。[P1]

内置微信入站路径对逐次来源存在确定性不匹配。腾讯官方封套字段全部可选，未承诺重投时标识稳定、逐消息确认或 exactly-once；Hermes 又在 DM/group 准入与业务处理前先推进整批游标、按 `message_id` 及“发送身份 + 相同正文”做内存去重，再把快速文本合并为只保留第一条 `MessageEvent` 来源的一个事件。[O1][O2][F1][F2][F3][F4] 因而两次相同正文可能在第二次 `MessageEvent` 形成前被静默丢弃；重启后内存去重消失，旧投递又可能重新进入。当前标准路径既不能保证保留两次来源，也不能保证只形成一次健康效果。

发送端同样没有端到端成功合同。iLink `sendmessage` 响应只有可选 `ret`/`errmsg`，目标 Adapter 把“请求链未抛错”映射为 `SendResult(success=True)`，返回的 `message_id` 是 Hermes 自生成的 `client_id`；它不是微信服务端回执，也不是主人展示、收取或已读证明。[O3][F6] 固定发送路径会自动重试，腾讯公开契约又没有说明同一 `client_id` 的幂等语义，所以超时或中断后不能从当前证据判断请求未被接受还是已经接受；业务提交、回复形成、接口接受、主人实际看到及处理结果无法确认必须分层，不能由同一个“success”代替。[F7]

结论是：**当前 iLink/Hermes 基座提供私聊准入和可覆盖 Adapter 等候选能力，但唯一健康入口、初始化前后排他分流、逐次来源耐久关联、相同正文重投歧义冻结、业务幂等以及主人真实到达均未实现或未证明。** 这项负向 CAN 不降低 TO，也不选择 Adapter、Hook、字段组合、去重、存储、重试或发送 HOW。真实入站、负向准入、重复投递、回复、断线/重启和主人端可见性仍须在实际候选存在后，按具体消息、时间、外部写入与停止条件另行取得主人批准；本票没有执行 canary。

## 1. 范围、证据层级与禁止动作

- 核验日期：2026-08-20（Asia/Shanghai）。
- 目标 Hermes：正式 `partner` profile；固定源码为 Hermes Agent v0.20.0 / commit `3c27eb6234bf91b8ceee9e9071591b31e9b148cb`。
- 腾讯基线：官方客户端 `openclaw-weixin` v2.4.6 / commit `cef0bfc390393f716903e16d50408118047f87e0` 的公开 API 说明、类型和客户端源码；`v2.4.6` 是客户端版本，不是腾讯对 iLink 服务端协议版本的保证，也不是目标 Hermes 的运行依赖。
- `[LIVE]`：2026-08-20 12:41–12:49 的目标现场基线，以及 13:31 的准入配置脱敏只读探针；只引用策略名、布尔值、hash 和去重计数，没有输出身份、凭据、聊天或健康正文。
- `[FIXED-SOURCE]`：上述两个固定提交可定位的源码行为；不冒充服务端运行保证。
- `[OFFICIAL]`：腾讯公开接口契约明确写出的字段和端点；不把客户端实现提升为服务端承诺。
- `[HISTORICAL]`：早先目标现场或本项目票据，只作为带时间的输入；不能冒充 2026-08-20 同时点事实。
- `[UNPROVEN]`：固定源码、公开合同和只读现场都不能确认，通常需要实际候选或主人微信 canary。
- `[PRODUCT]`：当前 `CONTEXT.md`/已解决 TO 规定的目标合同；它是本票要核验的要求，不是技术能力证据。
- `[INFERENCE]`：由已标注的一手事实推得的边界判断，不能提升为官方保证或现场已验收结果。
- `[WORKTREE-CANDIDATE]`：当前仓库尚未部署的候选源码，只能证明候选静态行为；不能冒充目标现场或被本票选择为 HOW。
- 本票没有连接微信、调用模型、发送消息、制造重投、停止或重启服务、改变游标、Plugin、配置或 Cron；没有读取或输出 secret、env 全文、身份值、聊天正文或健康内容。

## 2. 要证明的完整链，而不是一个“微信成功”

| 层 | 要证明的事实 | 当前可见的局部证据 | 不能用来代替 |
|---|---|---|---|
| 1. 投递观察 | iLink 本次确实交给 Hermes 一条 envelope，缺失字段如实保留 | `msgs[]` 中的一次对象观察 | 主人一次独立发送、已经处理 |
| 2. 技术准入 | 本次来源属于唯一获准私聊，群聊与其他人类入口被排除 | 固定 allowlist/group policy 分支 | 初始化、现实身份、健康权利 |
| 3. 健康接管 | 初始化后整条健康、混合或无法排除风险的消息只进入健康路径 | 当前无已部署健康 Plugin | 分类文字、Tool 被模型选择、普通回复 |
| 4. 权威业务提交 | 唯一画像/证据/任务等权威状态形成一个可查询结果 | 当前无健康业务状态 | cursor 推进、handler 未抛错、模型输出 |
| 5. 回复形成 | 与第 4 层一致的主人回复已经确定 | 普通 Agent 可生成文字 | 权威业务已提交、接口已接受 |
| 6. 接口接受 | iLink 明确未返回错误，或明确拒绝/结果未知 | `ret`/`errmsg` 与本地异常 | 主人已经看到、只收到一次 |
| 7. 主人实际看到 | 有独立证据证明目标微信端实际出现结果 | 需要主人端确认或等价回执 | 本地 `client_id`、无报错、日志标记 |

`[INFERENCE]` “处理结果无法确认”不是第八种成功，而是第 3–7 层任一关键边界上现有证据既不能证明完成、也不能证明未完成的状态。只有第 4 层已经确认、而第 6/7 层未知时，权威健康状态才可保持已提交，未知仅属于交付；第 4 层本身未知时不能猜测重做或沿用旧状态。[P2]

## 3. 唯一私聊准入与所有其他入口

### 3.1 iLink 与内置 Weixin 能提供什么

- `[OFFICIAL]` 腾讯 `getupdates` 是返回 `msgs[]` 与新 `get_updates_buf` 的长轮询；`sendmessage` 是向用户发送消息的接口。官方客户端 v2.4.6 声明 `chatTypes: ["direct"]`，原始类型虽有可选 `group_id`，但公开资料没有普通微信群交付或群成员身份保证。[O1][O4]
- `[FIXED-SOURCE]` 目标 Hermes 的 DM 策略可以是 `disabled`、`allowlist`、`pairing` 或显式 opt-in 的 `open`；`allowlist` 分支只有 `sender_id in allow_from` 才继续。群策略为 `disabled` 时，已交给 Adapter 且被判断为群聊的事件会直接停止。[F3]
- `[FIXED-SOURCE]` 目标的群聊猜测读取 `room_id`、`chat_room_id`、`to_user_id` 和 `msg_type`，没有直接读取腾讯公开类型中的 `group_id`。所以 `group_policy=disabled` 只证明**被该函数识别为群聊**的 envelope 会停止，不能仅凭开关证明所有可能被 iLink 交付的群 envelope 都会被识别并排除。[F10]
- `[FIXED-SOURCE]` 这不是“在读取正文前拒绝”。目标先读取 `item_list`、提取文本并按“发送身份 + 正文 MD5”把键和本地时间写入短期内存缓存，之后才判断 DM/group 准入；被拒来源不会构造后续 `MessageEvent`、不会下载其媒体，也不会由该分支产生回复，但固定源码不能支持“正文完全未读、没有任何内容派生留痕”的更强表述。[F2][F3]
- `[FIXED-SOURCE]` 非 bundled Plugin 可以注册同名 Platform/Adapter，固定 Gateway 优先创建 Plugin Adapter，平台注册表允许后注册者覆盖。这证明可在内置正文去重与合批之前采用另一条受支持路径，**不证明该路径已经实现或应当如何实现**。[F5]

### 3.2 当前现场能证明什么

- `[LIVE]` 2026-08-20 12:41–12:49：Weixin Adapter 与固定提交 hash 一致；Partner ordinary enabled Plugin 为零、profile manifest 为零、业务 Cron 为零；Telegram 与 Weixin 同时 configured。[L1]
- `[LIVE]` 13:31：通过目标 venv 加载 Partner profile 的 `.env` 与 `load_gateway_config()`，只输出归一化策略、布尔值与去重计数。Weixin 为 `dm_policy=allowlist`、允许清单计数 1、`WEIXIN_ALLOW_ALL_USERS=false`、`GATEWAY_ALLOW_ALL_USERS=false`、`group_policy=disabled`、群允许清单计数 0；Telegram 为 configured=true、enabled=true、`TELEGRAM_ALLOW_ALL_USERS=false`、允许清单计数 1。未输出任何身份或 token。[L2]
- `[HISTORICAL]` 2026-08-16 的同类核验也曾得到单值 Weixin allowlist、全开放关闭和群策略关闭，并额外确认当时 Weixin allowlist 与 home channel 相同；13:31 的新探针没有重做这项身份相等性比较，所以只继承带时间事实。[H1]
- `[UNPROVEN]` 当前 Weixin 允许值与 Telegram 允许值是否代表现实中的同一人，以及 Weixin 允许值是否仍与 home channel 相同，均未读取或比较；产品也不要求凭这些技术值核验现实身份。
- `[UNPROVEN]` 上述“清单计数 1”只对应本次指定核验的平台清单；没有读取身份值，也没有核验 Telegram pairing 或其他可能授权来源，因此不能提升为“Telegram 当前总共只有一个可用身份”。
- `[LIVE]` 13:31 静态配置显示 Telegram 是另一个 configured、enabled 且有一个允许值的人类消息入口。CLI/chat、Plugin Command/Tool、Cron、`send` 和内部 dispatch 仍是 Hermes 原语；当前未发现健康 Plugin，所以不能说 Telegram 或这些原语**已经**进入健康能力，但未来健康能力必须证明它们不能旁路唯一微信边界。[L1][L2][P1]
- `[LIVE]` 同日网络快照没有发现归属于 Partner PID 的 TCP/Unix listener，不能声称 Partner API 当前正在监听；`[FIXED-SOURCE]` 固定 Gateway 仍有 `APIServerAdapter` 构造面，所以 API 是未来健康能力仍须显式收敛的候选入口，而不是当前已启用入口。[L1][F14]

所以当前不能写成“只有微信能到达健康能力”。更准确的状态是：**当前 Weixin 确实配置为单值 DM allowlist，但 Telegram 也是启用并有单值 allowlist 的人类入口；当前根本没有已部署健康能力，未来健康能力的所有入口收敛尚未证明。**

### 3.3 当前仓库候选不能补出正向结论

`[WORKTREE-CANDIDATE]` 当前仓库的 `health-steward` 代码不是正式 Partner 部署事实。[L1] 本次实际读取的候选还存在三个与当前 C03 直接冲突的静态反例：

- 候选构造 Weixin Adapter 时要求 `expected_owner` 与 `expected_viewer` 两个配置槽，并把二者共同写入 `allow_from`；源码既未强制二者相同，也未在这里去重，所以不能静态证明最终只有一个唯一允许值。[W1]
- 候选注册一个全局 `pre_llm_call` 投影 Hook；该 Hook 只排除 `cron_` Session 并检查投影文件，没有按 Weixin、owner sender 或唯一入口过滤。若候选被加载且投影存在，Telegram/CLI 等普通非 Cron Agent 回合也可能取得这份健康投影，因而不能证明其他入口不读健康状态。[W1]
- 候选注释和分支明确允许“分类器在任何健康决定形成前失败”后继续 ordinary chat；生产构造还启用健康重试。当前产品把无法排除健康风险的消息留在健康路径，健康处理不可用时不得回退普通聊天，所以这个候选不能继承为现行排他分流合同。[W1][W2]

这些是候选反例，不是技术路线选择。本票不修改候选，也不据此预选 Adapter、Hook 或失败处理 HOW。

## 4. 初始化前后排他分流

- `[PRODUCT]` 初始化前健康管家不启动，不分类健康消息、不读写画像、不形成健康证据、任务、诊断、危险处理或健康接收事实；只有初始化引导可用，其他消息由基础 Hermes 按普通聊天合同处理且以后不得倒填。初始化后，健康、混合或无法排除健康风险的整条消息只走健康路径，健康处理不可用时不得回退普通聊天。[P2]
- `[LIVE]` 当前 Partner 没有健康 Plugin、健康初始化状态或业务 Cron，不能产生“未初始化/已初始化”的权威分流证据。[L1][P1]
- `[FIXED-SOURCE]` 内置 Weixin 只做技术 sender/group gate，之后把事件交给通用 Gateway；它不认识健康初始化、健康/混合分类、唯一健康结果或普通历史不倒填语义。[F3][F4]
- `[FIXED-SOURCE]` Plugin Adapter、Hook、Tool、Command 和内部 dispatch 可提供候选扩展点，但 Ticket 79 已证明这些入口不天然共享不可绕过的初始化闸门；模型也可能不调用 Tool。[P1]
- `[UNPROVEN]` 当前没有一条真实消息能够证明：初始化前只进入基础 Hermes；初始化后健康、混合或无法确定消息只被健康接管；接管失败时不会继续普通 Agent；同一条消息不会形成普通与健康两个结果。

因此 C03 的初始化前后路由合同当前为“未实现/未证明”，不能从 allowlist 或 Adapter `enforces_own_access_policy=True` 推导出来。

## 5. 一次 iLink 投递经过固定 Hermes 的真实顺序

### 5.1 腾讯封套与缺失字段

`[OFFICIAL]` `WeixinMessage` 的 `seq`、`message_id`、`from_user_id`、`to_user_id`、`client_id`、三个协议时间、`session_id`、`group_id`、`message_type`、`message_state`、`item_list`、`context_token` 与 `run_id` 全部是可选字段；item 级 `msg_id` 和时间也可缺失。[O2]

官方只把 `get_updates_buf` 定义为下次请求回传的完整同步上下文，把 `message_id` 描述为消息 ID、`seq` 描述为消息序号；没有公布这些字段的唯一性作用域、单调/重置规则、重投稳定性、逐消息 ACK、至少一次、至多一次或恰好一次保证。[O1][O2]

所以每次来源最多按实际可用情况关联：

- 聊天接口与 Hermes account/profile；
- 实际观察到的 `from_user_id`、可选 `to_user_id`/`session_id`/`group_id`；
- 可选 `message_id`、`seq`、`client_id`、item `msg_id`；
- 可选协议时间与独立 Hermes 接收时间；
- 本批次前后 cursor 的不可解释关联；
- 字段缺失状态。

这些事实只能证明一次投递观察，不能证明一次独立主人动作或已处理。

### 5.2 固定 Hermes 的处理顺序

固定 v0.20.0 实际顺序是：

1. `[FIXED-SOURCE]` 一次 `getupdates` 返回整批 `msgs[]` 和新 cursor；Hermes **先**持久化新 `get_updates_buf`，再为每条消息创建异步处理任务。单条处理异常只记日志，不回退 cursor。[F1]
2. `[FIXED-SOURCE]` 单条任务先要求非空 `from_user_id`，随后按可选顶层 `message_id` 进入内存去重。[F2]
3. `[FIXED-SOURCE]` 若有文本，再按“发送者 + 正文 MD5”进入同一内存去重；这仍发生在 DM/group 准入之前。[F2]
4. `[FIXED-SOURCE]` 之后才判断 group/DM 并应用策略；再持久化 `context_token`、处理媒体，并构造 `MessageEvent`。标准事件只提升发送者、上游 `message_id`、完整 `raw_message` 与本机 `datetime.now()`；协议时间和 `seq` 没有成为标准逐次来源字段。[F3]
5. `[FIXED-SOURCE]` 非文本事件随后进入 `handle_message`；文本事件先按会话进入快速合批。第一条事件留在缓冲区，后续事件只追加正文和媒体列表，没有追加后续 `message_id`、`raw_message`、协议时间或本机接收时间；静默窗口后只 dispatch 这一个事件。[F4]
6. `[FIXED-SOURCE]` 到 Gateway Hook、健康候选逻辑或普通 Session/Agent 能看到事件时，正文去重和文本合批已经完成；被去重的第二条没有事件，合批后只有第一条来源。普通 Session 的持久字段面向 user/assistant/tool 消息与内容，不是逐 iLink envelope 来源账本，不能补回已经丢失的字段。[F9][P1]
7. `[FIXED-SOURCE]` 固定 Gateway/Agent 基线还会在创建普通 Session 前把入站/回复片段写入 INFO 日志，在首次模型调用前持久化完整 user message；若外部 Memory 启用，它也可在 turn 边界取得用户正文和回复。[F11][F12] `[LIVE]` 当前目标 `gateway/run.py` 是 dirty 文件，且本票没有读取当前日志、Memory 或 delivery-ledger 配置，所以这些只能作为必须重证的固定基线，不能冒充当前逐字节运行行为或当前确已留存的事实。[L1]

这条顺序直接否定“当前内置 Adapter 后方可以逐次保存完整来源”的假设。cursor 更不能冒充业务提交：cursor 已经在健康接管、普通 Session 写入、模型调用、回复形成和发送之前推进。

## 6. 相同正文、合批与重投歧义

### 6.1 当前确定会发生的两类风险

- `[FIXED-SOURCE]` `MessageDeduplicator` 默认保存最多 2000 个近期键，每个键 300 秒有效；键在首次检查时立即写入进程内存，重启后不恢复。[F2]
- `[FIXED-SOURCE]` 同一 sender 在 300 秒内投递两条完全相同正文，即使上游 `message_id` 不同，第二条也会在准入和 `MessageEvent` 构造前返回。因此当前路径不能保留两次来源。[F2]
- `[FIXED-SOURCE]` 进程重启清空内存去重；如果 iLink 再次交付旧 envelope，当前路径可能重新处理。腾讯没有 published contract 说明重投时 ID/时间/cursor 如何保持，所以也不能证明不会重复效果。[O1][O2][F2]
- `[FIXED-SOURCE]` 快速但不同正文可以被合并成一个普通 Agent 输入，并只保留第一条来源。这既不能证明主人意图只有一次，也不能满足“每次投递来源均可追溯”。[F4]

### 6.2 产品要求与当前缺口

`[PRODUCT]` 两次实际观察到的相同正文必须保留为两次来源；在不能确认是重投还是主人有意再次发送时，不静默吞掉第二次来源，也不自动产生第二次画像更新、任务变化、诊断、回复或外部效果。只有歧义会改变判断或下一步时才向主人确认；危险处理不等待消歧。[P2]

`[UNPROVEN]` 当前没有持久化的“投递观察 → 歧义组 → 一个或零个权威健康效果”关系，也没有可查询的冻结状态。内置正文去重采取“直接丢弃”，不是“保留来源并冻结效果”；内存去重消失后重新进入也没有业务幂等证明。因此不能同时满足“不吞有意重复”和“不重复健康效果”。

## 7. 入站中断、出站重试与真实结果

### 7.1 入站与 cursor

- `[OFFICIAL]` `get_updates_buf` 只是下轮回传的同步 cursor；没有逐消息业务 ACK、保留期或重投保证。[O1][O2]
- `[FIXED-SOURCE]` Hermes 先保存 cursor，后异步处理单条消息。若进程在 cursor 保存后、业务提交前中断，本地重启会从新 cursor 开始，而腾讯是否重投该消息没有合同；结果只能是“接管/业务提交无法确认”，不能宣称已经处理或没有处理。[F1]
- `[FIXED-SOURCE]` 去重和待合批事件是内存状态；重启不会恢复正在等待的合批或在途任务。[F2][F4]

### 7.2 回复与主动发送

- `[OFFICIAL]` `SendMessageResp` 只有可选 `ret` 和 `errmsg`，没有服务端消息 ID、展示、收取或已读回执。[O3]
- `[FIXED-SOURCE]` 每个文本块使用 Hermes 本地生成的 `hermes-weixin-<uuid>`；发送链没有抛错就返回 `SendResult(success=True, message_id=<本地 client_id>)`。[F6]
- `[FIXED-SOURCE]` 文本块请求失败后默认还会自动重试；同一块沿用同一个 `client_id`，但公开 iLink 契约没有把它定义为幂等键。一次 HTTP 超时可能是请求未被接受，也可能是已被接受但响应未返回；自动重试可能产生重复，不能据此形成健康业务的“已送达一次”。[F7]
- `[FIXED-SOURCE]` Cron/`send_message` 的一次性主动发送可绕过长轮询 Adapter 生命周期并直接调用同一 raw API；它同样只有接口结果，没有主人到达保证。[F8]
- `[FIXED-SOURCE]` 通用发送层另有可选 delivery-obligation ledger：它可在发送前记录完整回复，并按 Adapter `SendResult.success` 标记 delivered/failed；这仍只继承 Adapter 层语义，不会把微信主人实际看到变成已证明。[F13] `[UNPROVEN]` 当前 Partner 是否启用该 ledger、它的保留边界和现有内容均未核验。

### 7.3 当前能够安全使用的结果词

| 已有证据 | 允许记录 | 不允许记录 |
|---|---|---|
| iLink envelope 出现在本批次 | 观察到一次投递；字段缺失按缺失 | 主人有意发了一次；已处理 |
| sender/group gate 允许 | 技术准入通过 | 已初始化；健康接管成功 |
| cursor 已保存 | 同步位置已推进 | 单条业务已确认 |
| 健康权威状态可读回并符合预期 | 业务提交成功 | 主人已收到 |
| 回复文本已确定 | 回复形成 | 接口已接受、主人已看到 |
| `sendmessage` 未报告错误 | 接口未报告错误/接受层成功 | 主人收到、只收到一次、已读 |
| API 超时、进程中断或状态读回不足 | 对应层结果无法确认 | 自动写失败、自动重试、猜测成功 |
| 主人独立确认微信中实际看到 | 主人实际看到 | 主人已理解或已采取行动 |

## 8. 当前判定与后继证明边界

| C03 子能力 | 当前判定 | 正向已证明 | 缺失／反例 |
|---|---|---|---|
| 单值 DM 技术准入 | **当前静态配置成立** | 13:31 为 allowlist、计数 1、Weixin/全局全开放 false | 真实负向投递未做；技术值不证明现实身份或初始化 |
| 群聊排除 | **当前开关关闭；不能证明全部群 envelope** | 13:31 为 `disabled`、群清单计数 0；被识别为群时停止 | iLink 普通群投递无保证；猜测不直接读官方 `group_id` |
| 准入外正文不读/不留痕 | **内置路径不满足强合同** | 拒绝后不构造后续聊天事件、不下载媒体、不由该分支回复 | 准入前已提取正文并写短期内存正文指纹 |
| 其他人类入口不能触达健康 | **未证明** | 当前没有健康 Plugin；当前未发现 Partner API listener | Telegram 静态配置为 configured+enabled 且 allowlist 计数 1；CLI/chat/Command/Tool/Cron/internal 原语及 API 构造面仍在 |
| 初始化前基础聊天 | **未实现／未证明** | 基础 Hermes 可普通聊天 | 无初始化权威状态或阶段隔离 |
| 初始化后排他健康分流 | **未实现／未证明** | Adapter 可覆盖的候选扩展面 | 无健康 Plugin、分类接管、无回退证据 |
| 每次投递来源保留 | **内置路径不满足** | 原始 envelope 包含若干可选字段 | 正文去重先丢、合批只留首条、字段均可缺 |
| cursor 与业务结果分离 | **接口事实成立，产品状态缺失** | cursor 先推进可定位 | 无逐消息 ACK、无健康业务 readback |
| 重投歧义冻结重复效果 | **未实现** | 无 | 当前是静默正文去重与重启后可能重进 |
| 权威业务提交 | **未实现** | 无健康权威状态 | handler/cursor/模型文字不能代替 |
| 回复接口接受 | **仅有候选技术层** | 固定发送可返回本地 success | 无当前 health reply canary；超时/重试幂等未知 |
| 主人真实看到 | **未证明** | 无 | iLink 无送达回执，本票未发消息 |

后继候选若要得到正向 CAN，至少要用可复现证据同时证明：所有人类/内部入口的健康准入收敛；初始化前后每个路由分支；去重/合批前逐 envelope 耐久来源；相同正文两次投递的来源保留和效果冻结；cursor、接管、业务提交、回复、接口接受及主人实际看到逐层可查询；中断和重启后的失败/未知不盲重试。具体机制由后续 HOW 决定。

## 9. 一手来源

### `[LIVE]` 目标 Partner

- **[L1]** [Ticket 78 同日目标现场报告](19-current-partner-hermes-baseline-plugin-lifecycle-trust-20260820.md)：第 1–3、8–10 节。快照为 2026-08-20 12:41–12:49；记录正式版本/HEAD、Weixin Adapter hash、普通 Plugin/manifest/Cron 为零、Telegram/Weixin configured，以及禁止动作和原始只读命令边界。
- **[L2]** 2026-08-20 13:31 脱敏只读配置探针：使用现有 SSH 身份和已保存 host key，在目标 venv 中加载 `/root/.hermes/profiles/partner/.env` 与固定 `load_gateway_config()`；程序只计算并输出上述策略名、布尔值和去重计数。没有输出 env 行、身份值、home channel、token 或其他 secret，没有调用模型/微信、发送消息、读取聊天/健康正文、写远端文件、重启或改配置。

### `[OFFICIAL]` 腾讯 iLink / 官方客户端 v2.4.6

- **[O1]** [腾讯固定 `getUpdates` / `sendMessage` 契约](https://github.com/Tencent/openclaw-weixin/blob/cef0bfc390393f716903e16d50408118047f87e0/README.md#L125-L191)。
- **[O2]** [腾讯固定消息与 cursor 类型，字段均可选](https://github.com/Tencent/openclaw-weixin/blob/cef0bfc390393f716903e16d50408118047f87e0/src/api/types.ts#L153-L205)。
- **[O3]** [腾讯固定发送响应只有 `ret`/`errmsg`](https://github.com/Tencent/openclaw-weixin/blob/cef0bfc390393f716903e16d50408118047f87e0/src/api/types.ts#L207-L215)。
- **[O4]** [腾讯官方客户端只声明 direct chat](https://github.com/Tencent/openclaw-weixin/blob/cef0bfc390393f716903e16d50408118047f87e0/src/channel.ts#L142-L181)；[固定入站规范化为 direct](https://github.com/Tencent/openclaw-weixin/blob/cef0bfc390393f716903e16d50408118047f87e0/src/messaging/inbound.ts#L220-L237)。
- **[O5]** [腾讯固定客户端包声明版本为 2.4.6](https://github.com/Tencent/openclaw-weixin/blob/cef0bfc390393f716903e16d50408118047f87e0/package.json#L1-L3)。

### `[FIXED-SOURCE]` Hermes v0.20.0 / `3c27eb...`

- **[F1]** [整批 cursor 先保存、单条再异步处理](https://github.com/NousResearch/hermes-agent/blob/3c27eb6234bf91b8ceee9e9071591b31e9b148cb/gateway/platforms/weixin.py#L1281-L1327)。
- **[F2]** [`message_id` 与正文指纹去重先于准入和事件构造](https://github.com/NousResearch/hermes-agent/blob/3c27eb6234bf91b8ceee9e9071591b31e9b148cb/gateway/platforms/weixin.py#L1336-L1406)；[300 秒、2000 键、进程内缓存](https://github.com/NousResearch/hermes-agent/blob/3c27eb6234bf91b8ceee9e9071591b31e9b148cb/gateway/platforms/helpers.py#L24-L66)。
- **[F3]** [DM/group 准入、原始 envelope 与本机事件时间](https://github.com/NousResearch/hermes-agent/blob/3c27eb6234bf91b8ceee9e9071591b31e9b148cb/gateway/platforms/weixin.py#L1336-L1406)；[DM policy 分支](https://github.com/NousResearch/hermes-agent/blob/3c27eb6234bf91b8ceee9e9071591b31e9b148cb/gateway/platforms/weixin.py#L1407-L1428)。
- **[F4]** [快速文本只向第一条事件追加正文和媒体](https://github.com/NousResearch/hermes-agent/blob/3c27eb6234bf91b8ceee9e9071591b31e9b148cb/gateway/platforms/weixin.py#L1438-L1490)。
- **[F5]** [Plugin Adapter 优先于内置 Adapter](https://github.com/NousResearch/hermes-agent/blob/3c27eb6234bf91b8ceee9e9071591b31e9b148cb/gateway/run.py#L12727-L12770)；[同名 Platform 后注册覆盖](https://github.com/NousResearch/hermes-agent/blob/3c27eb6234bf91b8ceee9e9071591b31e9b148cb/gateway/platform_registry.py#L209-L225)。
- **[F6]** [本地 `client_id` 被作为 `SendResult.message_id`](https://github.com/NousResearch/hermes-agent/blob/3c27eb6234bf91b8ceee9e9071591b31e9b148cb/gateway/platforms/weixin.py#L1693-L1815)。
- **[F7]** [同一文本块的发送重试与结果边界](https://github.com/NousResearch/hermes-agent/blob/3c27eb6234bf91b8ceee9e9071591b31e9b148cb/gateway/platforms/weixin.py#L1660-L1755)。
- **[F8]** [Cron/`send_message` 可绕过长轮询 Adapter 生命周期直接发送](https://github.com/NousResearch/hermes-agent/blob/3c27eb6234bf91b8ceee9e9071591b31e9b148cb/gateway/platforms/weixin.py#L2172-L2262)。
- **[F9]** [普通 Session 的消息与内容持久字段](https://github.com/NousResearch/hermes-agent/blob/3c27eb6234bf91b8ceee9e9071591b31e9b148cb/website/docs/developer-guide/session-storage.md#L2-L27)；[消息记录结构](https://github.com/NousResearch/hermes-agent/blob/3c27eb6234bf91b8ceee9e9071591b31e9b148cb/website/docs/developer-guide/session-storage.md#L75-L123)。
- **[F10]** [Hermes 群聊猜测没有直接读取官方 `group_id`](https://github.com/NousResearch/hermes-agent/blob/3c27eb6234bf91b8ceee9e9071591b31e9b148cb/gateway/platforms/weixin.py#L360-L366)。
- **[F11]** [固定 Gateway 基线的入站/回复片段日志与 Session 前路径](https://github.com/NousResearch/hermes-agent/blob/3c27eb6234bf91b8ceee9e9071591b31e9b148cb/gateway/run.py#L15141-L15168)；[首次模型调用前保存 user message](https://github.com/NousResearch/hermes-agent/blob/3c27eb6234bf91b8ceee9e9071591b31e9b148cb/agent/turn_context.py#L985-L1171)。
- **[F12]** [外部 Memory 在 turn 边界可取得用户正文](https://github.com/NousResearch/hermes-agent/blob/3c27eb6234bf91b8ceee9e9071591b31e9b148cb/agent/turn_context.py#L1077-L1095)；[turn complete 路径](https://github.com/NousResearch/hermes-agent/blob/3c27eb6234bf91b8ceee9e9071591b31e9b148cb/run_agent.py#L3768-L3850)。
- **[F13]** [可选 delivery-obligation ledger 在发送前记录内容并按 `SendResult` 结算](https://github.com/NousResearch/hermes-agent/blob/3c27eb6234bf91b8ceee9e9071591b31e9b148cb/gateway/platforms/base.py#L5580-L5654)。
- **[F14]** [固定 Gateway 的 `APIServerAdapter` 构造面](https://github.com/NousResearch/hermes-agent/blob/3c27eb6234bf91b8ceee9e9071591b31e9b148cb/gateway/run.py#L12801-L12808)。

### `[HISTORICAL]` 与当前产品合同

- **[H1]** [2026-08-16 现场脱敏准入核验](03-channel-owner-provenance-capabilities-20260816.md)：第 5 节。当时单值 DM allowlist、全开放关闭、群聊关闭；本票只继承其带时间事实，不冒充 8 月 20 日同时点结果。
- **[P1]** [Ticket 79 与 Evidence 20](../issues/79-verify-health-capability-entry-initialization-gate-and-result-contract.md)：当前没有健康 Plugin/初始化状态；Hermes 的 Platform、Tool、Command、Hook、Cron 与 internal dispatch 原语不天然共享初始化门禁和真实结果合同。
- **[P2]** [`CONTEXT.md`](../../../CONTEXT.md)：人物与访问、消息来源证据、重投歧义、健康处理、健康处理失败关闭、处理结果无法确认及健康结果交付事实的当前领域合同。

### `[WORKTREE-CANDIDATE]` 当前仓库（未部署）

- **[W1]** [`plugin/health-steward/__init__.py`](../../../ops/partner-health-steward/plugin/health-steward/__init__.py)：`:84-150` 要求 owner/viewer、把二者放入 Weixin allowlist并启用 health retry；`:317-370` 的投影 Hook 没有来源/owner 过滤；`:373-442` 注册 Hook 与 Weixin Platform。本次 SHA-256 为 `1748ec7c76cb59a78539375f6ca51d3a21fe66e36e84e945ad7590eb34334a60`。
- **[W2]** [`plugin/health-steward/weixin_adapter.py`](../../../ops/partner-health-steward/plugin/health-steward/weixin_adapter.py)：`:371-415` 在健康决定形成前的分类失败后仍可把事件排入 ordinary chat，并在生产构造启用重试；`:460-500` 只有已经形成 `health_outcome` 的分支才禁止普通回退。本次 SHA-256 为 `5580f31fdcb79bdff7b05e3b9cd3eb2b4ee7cb552542c816a5482c4de2553313`。

## 10. 本票明确没有做的事

- 没有执行真实主人微信入站、第二账号、群聊、相同正文、快速连发、回复或主动发送实验。
- 没有停止/重启 Partner、制造断线、回退 cursor、故障注入或修改任何远端文件、服务、配置、Plugin、Skill、Cron、allowlist 或状态。
- 没有调用模型或健康能力，没有读取/输出 secret、env 全文、聊天正文、健康内容、真实身份值或 token。
- 没有把 8 月 16 日配置事实冒充 8 月 20 日同时点事实，没有把系统服务 active、Adapter hash、接口无错或本地 `client_id` 冒充健康接管、业务提交或主人实际看到。
- 没有选择 Adapter、Hook、消息字段、幂等键、存储、重试、发送、恢复或验收 HOW。
