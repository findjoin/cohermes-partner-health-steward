# 微信 iLink 入站接口与重复投递语义核验（Ticket 48）

## 1. 核验范围与纪律

- 核验日期：2026-08-16（Asia/Shanghai）。
- 腾讯接口依据：腾讯官方 `openclaw-weixin` v2.4.6 协议说明与类型定义；目标 Hermes 依据现场固定提交 `3c27eb6234bf91b8ceee9e9071591b31e9b148cb`。
- 本次仅做官方资料与固定源码研究，没有连接服务器、发送微信消息、读取聊天正文、身份值或凭据，也没有修改运行环境。
- 现有现场日志没有打印入站 `message_id`，且此前现场核验明确没有发送测试消息，因此不能把历史的 16 次入站标记当成真实字段存在率、格式或重投稳定性的证明。

## 2. 腾讯官方 iLink 入站接口

微信入站使用 HTTP JSON 长轮询：客户端向 `POST /ilink/bot/getupdates` 回传上一响应的 `get_updates_buf`；服务端返回 `msgs`、新的 `get_updates_buf` 和可选的 `longpolling_timeout_ms`。这里的游标表示轮询同步位置；官方没有把它定义为某条消息的唯一键、逐消息确认或幂等键。[腾讯 getUpdates 契约](https://github.com/Tencent/openclaw-weixin/blob/v2.4.6/README.md#L125-L158)

`longpolling_timeout_ms` 的物理含义是服务端建议下一次长轮询最多等待多少毫秒，例如 `35000` 表示约 35 秒的挂起等待；它不是消息去重窗口、处理期限或送达保证。

官方 `WeixinMessage` 主要字段如下；在 TypeScript 契约中这些字段均为可选：[腾讯消息类型](https://github.com/Tencent/openclaw-weixin/blob/v2.4.6/src/api/types.ts#L168-L205) [腾讯字段说明](https://github.com/Tencent/openclaw-weixin/blob/v2.4.6/README.md#L254-L278)

| 字段 | 官方含义 | 已公布的可靠性边界 |
|---|---|---|
| `message_id` | 数值型“消息唯一 ID” | 可选；未说明唯一性的账号/会话/时间范围，也未承诺重投沿用同一值 |
| `seq` | 消息序号 | 可选；未说明单调性、重置规则或能否作为唯一键 |
| `from_user_id` / `to_user_id` | 发送者 / 接收者标识 | 可选字段；健康能力仍需独立验证当前主人授权 |
| `client_id` | 客户端标识 | 可选；官方未把它定义为所有入站消息的稳定标识 |
| `create_time_ms` / `update_time_ms` / `delete_time_ms` | 协议对象的毫秒时间 | 可选；未声明时钟可信度或重投时是否保持不变 |
| `session_id` / `group_id` | 会话 / 群标识 | 可选；不能替代主人身份与私聊准入 |
| `message_type` / `message_state` | 用户或 Bot、消息状态 | 可选；属于消息状态，不是幂等键 |
| `item_list` | 文本、图片、语音、文件、视频等内容项 | 可选；每个 item 还可带自己的 `msg_id` 和时间，但官方同样未给出唯一性保证 |
| `context_token` | 回复时回传的会话上下文令牌 | 用于回复上下文，不是主人身份或消息唯一键 |

因此，接口确实提供了比目标 Hermes 当前标准事件更多的来源字段；但公开契约没有给出“每条必有稳定 ID”或“恰好一次投递”的保证。

## 3. 目标 Hermes v0.20.0 实际怎样消费接口

目标 Hermes 在轮询成功后先保存新的 `get_updates_buf`，再把 `msgs` 中每一项异步交给处理任务；它没有等每条消息成功处理后再逐条确认。因此这个 cursor 不能冒充逐消息 durable ACK。[目标轮询实现](https://github.com/NousResearch/hermes-agent/blob/3c27eb6234bf91b8ceee9e9071591b31e9b148cb/gateway/platforms/weixin.py#L1281-L1327)

入站时，Hermes：

- 读取 `from_user_id`、顶层 `message_id`、`context_token` 和 `item_list`；
- 把缺失、`null`、空串或数值 `0` 的 `message_id` 归为空，并令标准事件的 `message_id=None`，不生成替代入站 ID；
- 不把 `seq`、`client_id`、item 级 `msg_id` 或协议时间用于去重或标准来源字段；它们只暂存在原始 payload；
- 把事件时间写成媒体处理之后的本机 `datetime.now()`，而不是 iLink 的 `create_time_ms`。

[目标入站映射](https://github.com/NousResearch/hermes-agent/blob/3c27eb6234bf91b8ceee9e9071591b31e9b148cb/gateway/platforms/weixin.py#L1341-L1401)

目标版本的去重实际有两层：

1. 非空 `message_id` 在内存中近期见过就丢弃；
2. 文本还按“发送者 + 正文 MD5”去重，即使 `message_id` 不同也会丢弃。

两层共用 300 秒（5 分钟）、最多 2000 个键的内存缓存。300 秒表示同一进程把键视为“近期见过”的时间，不表示微信保证的重投期限；2000 表示缓存最多保留的近期键数量，不表示消息、用户或档案上限。缓存不持久化，进程重启后丢失，而且键在授权检查和正式处理成功之前就会被记为“见过”。[去重分支](https://github.com/NousResearch/hermes-agent/blob/3c27eb6234bf91b8ceee9e9071591b31e9b148cb/gateway/platforms/weixin.py#L1349-L1359) [缓存语义](https://github.com/NousResearch/hermes-agent/blob/3c27eb6234bf91b8ceee9e9071591b31e9b148cb/gateway/platforms/helpers.py#L24-L66)

快速文本随后还会合批；后续消息只追加正文和媒体列表，自己的 `message_id`、原始 payload 和时间没有加入批次来源。因此合批后的标准事件只保留第一条消息的来源。[文本合批实现](https://github.com/NousResearch/hermes-agent/blob/3c27eb6234bf91b8ceee9e9071591b31e9b148cb/gateway/platforms/weixin.py#L1438-L1493)

## 4. 重复投递的已知事实与矛盾

腾讯 README 把 `message_id` 称为唯一 ID，但没有发布重投稳定性契约。Hermes 已合并的修复记录了一个实际反例：iLink 曾在约 3 秒内把同一逻辑用户消息再次交付，但两次 `message_id` 不同；目标版本正因该问题加入正文指纹去重。[Hermes 已合并 PR #19742](https://github.com/NousResearch/hermes-agent/pull/19742)

正文去重又产生相反问题：主人在 5 分钟内有意发送两条相同正文时，第二条会被静默丢掉。这个行为由目标源码直接决定，Hermes 也有对应的用户问题报告。[Hermes Issue #29779](https://github.com/NousResearch/hermes-agent/issues/29779)

所以目前公开证据无法同时证明以下两件事：

- 不把 iLink 的一次重复投递误当成主人发了两次；
- 不把主人确实发出的两条相同内容误当成一次重复投递。

`seq`、协议时间、item 级 `msg_id` 和 cursor 值都值得保留作证据，但官方没有给出足以让它们确定消除该歧义的契约。把这些字段组合起来只能增加观测信息，不能直接宣称实现了恰好一次。

## 5. 对 Ticket 48 的纠正

- 撤回“缺少可靠消息 ID 时应让主人先选择产品行为”的上一轮假设性提问；这首先是接口契约与实现证据问题，不是新的 TO 取舍。
- 保留主人在 Round 6 中真正的产品意图：不能仅因为发送者与正文相同，就吞掉主人有意重复发送的一条消息。
- 撤回其中的传输层推断：`message_id` 不同并不等于已经证明是两次独立主人动作；`message_id` 相同也只是一项重复证据，不是公开的完整 exactly-once 契约。
- 当前路线应在任何正文去重或文本合批之前，逐项保留 iLink 原始 envelope，包括可用的 `message_id`、`seq`、`client_id`、item 级 `msg_id`、协议时间、poll cursor 证据和独立的 Hermes 首次接收时间。字段缺失必须如实标为缺失或身份歧义，不能伪造成“可信微信 ID”。
- 具体重复判断、持久化、恢复与失败处置仍属于 Ticket 48 的 HOW；真实微信的字段存在率与重投行为必须在后续获准的元数据测试中验证。当前不据此降低产品愿景，也不宣称接口已满足恰好一次。
