# 聊天接口、主人身份与逐条消息来源能力核验（Ticket 43）

## 1. 核验范围与证据纪律

- 核验时间：2026-08-16 02:02–02:16（Asia/Shanghai）。
- 目标：主机 `findjoin` 上正式运行的 `partner` Hermes；源码基线为目标现场 HEAD `3c27eb6234bf91b8ceee9e9071591b31e9b148cb`，即 Hermes v0.20.0 的官方发布提交。
- 方法：固定提交的官方源码审计，加一次 SSH 只读现场检查。没有发送微信测试消息；token、聊天正文和身份值均未进入核验输出，身份清单只做非敏感计数与相等性比较；没有修改配置、安装插件、停止或重启服务。
- 本报告只回答 CAN：目标 Hermes 已支持什么、当前路径缺什么以及哪些事实仍未证明；不选择聊天 Adapter、Hook、存储或授权流程等 HOW。

## 2. 结论矩阵

| 产品要求 | 目标 Hermes 与现场证据 | CAN 判断 |
|---|---|---|
| 聊天接口中立 | Hermes 用统一的 `SessionSource` / `MessageEvent` 表达接口、会话、发送身份和消息；Plugin 可注册聊天 Adapter，注册表允许同名 Adapter 覆盖内置实现 | **架构扩展面已支持，健康产品尚未实现** |
| 单一真实主人 | 微信入站带发送身份；现场采用私聊白名单，去重后只有一个允许值，且与 home channel 相同 | **技术准入部分支持**；不能据此证明该值就是已知情授权的真实主人 |
| 未授权身份和群聊失败关闭 | 内置微信 Adapter 在创建事件前拒绝不在白名单的私聊；现场群聊策略为关闭、全开放为关闭 | **源码与当前配置支持失败关闭**；没有用第二账号或群聊做真人负向测试 |
| 每条物理消息保留接口、发送身份、消息标识和接收时间 | 每条通过入口检查的消息会先形成带这些字段的事件，但相同正文去重可在建事件前丢弃一条真实消息，快速文本合并又只保留第一条事件的来源 | **当前内置微信路径明确不满足** |
| 健康能力在合并前可靠取数 | `pre_gateway_dispatch` 收到的是 Adapter 调用 `handle_message` 后的事件；微信文本在此之前已经完成去重与合并 | **当前内置 Adapter 后的 Plugin Hook 不满足** |
| 回复接口中立并真实到达微信 | 通用路由会交给来源接口的 Adapter；iLink 未返回错误时 Hermes 记为发送成功 | **只证明提交给发送接口**；没有主人端展示、收取或已读回执 |
| 主人看到健康插件运行状态 | 现场没有已启用 Plugin、健康实现或健康运行状态 | **未具备**；调度、恢复与状态由下一张 CAN 票核验 |

## 3. 通用聊天契约与可扩展边界

目标版本的通用 `SessionSource` 用于路由并携带聊天接口、会话、用户及可选消息标识；`MessageEvent` 另带原始消息、消息标识和时间。这个模型是接口中立的路由/事件结构，但源码没有把它定义成健康档案所需的不可变逐条来源账本。[目标版本通用消息模型](https://github.com/NousResearch/hermes-agent/blob/3c27eb6234bf91b8ceee9e9071591b31e9b148cb/gateway/platforms/base.py#L2054-L2128)

Hermes 会优先创建 Plugin 注册的聊天 Adapter，再回退到内置 Adapter；平台注册表明确采用“同名后注册者覆盖”规则，目的之一就是允许 Plugin 覆盖内置实现。[Adapter 选择顺序](https://github.com/NousResearch/hermes-agent/blob/3c27eb6234bf91b8ceee9e9071591b31e9b148cb/gateway/run.py#L12727-L12770) [平台注册覆盖规则](https://github.com/NousResearch/hermes-agent/blob/3c27eb6234bf91b8ceee9e9071591b31e9b148cb/gateway/platform_registry.py#L209-L225)

因此，Hermes 已提供在核心之外实现接口中立聊天 Adapter 的正式扩展空间。它只证明存在可行扩展面，不证明逐条健康来源、主人授权或真实送达已经实现。

## 4. 当前微信入站路径的硬限制

### 4.1 初始事件拥有的字段

内置微信 Adapter 对每条 iLink 消息先取得 `from_user_id` 和可选的 `message_id`，判断私聊/群聊并做准入检查，然后构造：

- `source`：微信接口、会话类型、会话标识和发送身份；
- `message_id`：上游字段，允许为空；
- `raw_message`：当时收到的整条上游字典；
- `timestamp`：Hermes 本机执行到这里时生成的 `datetime.now()`。

这个时间是本机处理时间，不是已证明的微信源端发送时间；源码也没有证明每条上游消息一定提供非空消息标识。[微信入站事件构造](https://github.com/NousResearch/hermes-agent/blob/3c27eb6234bf91b8ceee9e9071591b31e9b148cb/gateway/platforms/weixin.py#L1341-L1406)

### 4.2 相同正文会丢掉不同的物理消息

除了按 `message_id` 去重，内置 Adapter 还以“发送身份 + 正文 MD5”作为第二个去重键，缓存有效期为 300 秒，即 5 分钟。物理含义是：同一发送者在 5 分钟内发送两条标识不同但正文完全相同的真实文本，第二条会在 `MessageEvent` 创建前被丢弃。[300 秒去重常量与入站去重](https://github.com/NousResearch/hermes-agent/blob/3c27eb6234bf91b8ceee9e9071591b31e9b148cb/gateway/platforms/weixin.py#L101-L107) [正文去重分支](https://github.com/NousResearch/hermes-agent/blob/3c27eb6234bf91b8ceee9e9071591b31e9b148cb/gateway/platforms/weixin.py#L1349-L1359)

### 4.3 快速文本合并只保留第一条来源

目标 profile 没有覆盖微信文本合并参数，所以当前使用源码默认值：

- 普通快速连发：最后一条到达后等待 3.0 秒再派发；
- 最后一条文本长度达到 1800 字符时：等待 5.0 秒，以接收可能继续到达的拆分长消息。

这两个数表示合并等待时间，不是健康策略阈值。[默认合并参数](https://github.com/NousResearch/hermes-agent/blob/3c27eb6234bf91b8ceee9e9071591b31e9b148cb/gateway/platforms/weixin.py#L1165-L1178)

合并实现把第一条 `MessageEvent` 留在缓冲区；后续事件只追加正文与媒体列表，没有追加各自的 `message_id`、`timestamp`、`raw_message` 或来源封套。静默期结束后，只有这个合并后的第一条事件被送入 `handle_message`。[微信文本合并实现](https://github.com/NousResearch/hermes-agent/blob/3c27eb6234bf91b8ceee9e9071591b31e9b148cb/gateway/platforms/weixin.py#L1435-L1490)

`pre_gateway_dispatch` 虽然在 Hermes 普通授权前运行并能收到 `MessageEvent`，但它位于 `handle_message` 路径内；对微信文本而言，此时去重和合并已经发生。Hook 异常还会被记日志后继续原流程。[目标版本 Hook 调用点](https://github.com/NousResearch/hermes-agent/blob/3c27eb6234bf91b8ceee9e9071591b31e9b148cb/gateway/run.py#L13355-L13376)

结论：**“内置微信 Adapter + 其后的 `pre_gateway_dispatch` Hook”不能可靠保留和检查每条物理文本来源。** 媒体消息不走这段文本合并，但这不修复文本路径。

## 5. 当前主人准入与失败关闭

现场非敏感配置事实如下；只统计和比较清单值，没有记录或输出任何身份值：

| 配置 | 当前值 | 物理含义 |
|---|---|---|
| `WEIXIN_DM_POLICY` | `allowlist` | 只有列入允许清单的私聊发送身份进入后续处理 |
| `WEIXIN_ALLOW_ALL_USERS` | `false` | 没有打开所有私聊身份 |
| `GATEWAY_ALLOW_ALL_USERS` | 未设置 | 没有通过全局开关绕过微信私聊限制 |
| `WEIXIN_GROUP_POLICY` | `disabled` | 已被 iLink 交付给 Adapter 的群聊事件直接停止 |
| 允许清单 | 去重后 1 个值；与 home channel 相同 | 当前技术配置收敛到一个私聊发送身份 |

`.env` 修改时间早于当前服务启动时间；目标启动代码以 partner profile 加载该文件。`config.yaml` 没有微信节或相反覆盖项。结合目标源码，当前配置对未获准私聊和已收到的群聊事件采用入口失败关闭。

边界必须保留：

- 白名单只证明一个技术标识被允许，不能证明它现实中属于主人，也不能替代知情启用、身份迁移和恢复权利。
- 本次没有使用未授权账号或群聊发送测试消息，所以负向行为尚无真人端到端证据。
- iLink 是否会把普通群聊消息交付给该身份不是本票已证明的能力；群聊本来就在当前产品范围外。

## 6. 回复与真实到达边界

微信发送路径为每个文本块生成新的 `hermes-weixin-<uuid>` 作为 `client_id`。iLink `sendmessage` 没有报告错误时，Adapter 返回 `SendResult(success=True)`，其中的 `message_id` 实际是 Hermes 自己生成的客户端标识，不是微信客户端展示、收取或已读回执。[微信文本发送结果](https://github.com/NousResearch/hermes-agent/blob/3c27eb6234bf91b8ceee9e9071591b31e9b148cb/gateway/platforms/weixin.py#L1799-L1815)

当前服务自 2026-08-07 07:30:33 +08:00 起仍为 `active/running`。仅按固定日志标记计数且未读取正文：

- 最近一条可连起的链为 2026-08-11 08:48:25 入站，08:48:35 生成回复并进入微信发送；
- 当前保留日志中，服务启动后有 16 次微信入站、10 次回复就绪、10 次微信发送入口；
- 最近 Adapter 发送失败标记在 2026-08-07 12:55:10；2026-08-13 还出现过 3 次轮询错误；之后没有新的保留入站记录。

这些日志最多证明 8 月 11 日的请求进入了发送路径且没有留下对应失败标记，不能证明主人微信实际展示，更不能证明 8 月 16 日当前仍可端到端送达。服务进程存活、Adapter 曾连接或日志中没有新失败，都不能替代真实主人微信验收。

## 7. TO-CAN 差距判断与后续边界

当前内置微信路径对逐条物理来源存在确定性硬不匹配，但目标 Hermes 的受支持 Plugin 机制可以注册并覆盖聊天 Adapter，因此尚不能判定产品目标在 Hermes 架构内做不到。本票不创建 TO-CAN 差距决策，也不降低“每条物理消息保留来源”的要求。

后续 HOW 必须选择一个能在任何正文去重或文本合并之前保留逐条来源封套的受支持扩展位置；不得把内置 Adapter 之后的 Hook 说成已经解决。选择具体 Adapter、事件结构、授权数据、持久化与验收方法不属于本票。

仍待后续阶段证明：真实身份与主人的绑定及知情启用、未授权真人负向用例、主人端真实收到回复、健康插件活跃/异常/无法确认状态，以及其他聊天接口是否采用同一产品契约。
