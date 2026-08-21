# 每日复盘、投递恢复与跨故障域状态工具核验（Ticket 62）

## 1. 范围、基线与证据层级

- 核验目标：同一 `partner` Hermes 中尚待实现的健康 Plugin、同名 `weixin` Adapter 与专用健康数据库路线，只回答候选工具 **CAN**，不选择调度、监控、通知或恢复 **HOW**。
- 固定源码：Hermes v0.20.0，提交 `3c27eb6234bf91b8ceee9e9071591b31e9b148cb`；微信公开接口以腾讯 `openclaw-weixin` v2.4.6，提交 `cef0bfc390393f716903e16d50408118047f87e0` 为准。
- 现场只读复核：2026-08-18 02:52–03:00（Asia/Shanghai），主机 `findjoin`。没有修改服务或配置，没有创建任务，没有调用模型或发送微信，没有故障注入，也没有读取健康正文、聊天正文、身份值或凭据。
- systemd 作用域：本文所称 Partner unit 是 **root 用户 manager** 中的 `systemctl --user` 单元，不是系统 manager 单元。最终交叉复核显示：系统作用域 `systemctl show hermes-gateway-partner.service` 为 `LoadState=not-found`、`ActiveState=inactive`、`MainPID=0`；root 用户作用域同名单元为 `loaded/active/running/enabled`、`MainPID=143611`，且 root `Linger=yes`。这与系统作用域只见 dashboard 的现场记录一致。
- 证据严格分为：官方文档保证、固定源码行为、目标现场事实、未知项、须另行批准的实验。源码“存在接口”和现场“进程 active”均不视为产品能力已经可用。

## 2. 结论先行

目标版本与系统环境有足够的基础工具，让后续 HOW 在既定 Hermes Plugin 路线内实现：主人 IANA 时区下的自然日计算、持久执行/业务账本、唯一键防重、失败或重启后的未知态保留、无健康正文的核心自检，以及进程外观察接口。因而本票是 **正向 CAN**，无需降低 TO。

但是，目标现场当前只有 Hermes、systemd、主机 watchdog、QEMU Guest Agent 等基础设施：健康 Plugin、健康 Cron、健康专用数据库、业务提交账本、投递 outbox、主人三态状态面、跨主机观察者和主人故障通知均未部署或未证明。当前不能声称每日复盘存在、主动消息已送达、四项健康核心可验证，或 Partner/整机离线时主人仍能收到通知。

## 3. 七层事实矩阵

| 事实层 | 官方保证／固定源码能证明什么 | 2026-08-18 目标现场 | 未知项与须批准实验 | 明确不能冒充什么 |
|---|---|---|---|---|
| 1. 任务存在 | Hermes Cron 可持久保存任务；`cron list` 可列出任务。任务字段与最近运行字段由固定源码定义。[Cron 官方执行流程](https://github.com/NousResearch/hermes-agent/blob/3c27eb6234bf91b8ceee9e9071591b31e9b148cb/website/docs/user-guide/features/cron.md#L234-L273) [任务字段源码](https://github.com/NousResearch/hermes-agent/blob/3c27eb6234bf91b8ceee9e9071591b31e9b148cb/cron/jobs.py#L1391-L1429) | `partner cron list` 为 0；没有健康任务。 | 实现后须只读核对任务定义、主人时区事实和当前自然日。 | 任务存在不等于已开始、已完成或已发出消息。 |
| 2. 开始执行 | `executions.db` 在调用 Agent/provider 前先写 `claimed`，随后可写 `running`；状态还包括 `completed`、`failed`、`unknown`。[执行账本定义与状态](https://github.com/NousResearch/hermes-agent/blob/3c27eb6234bf91b8ceee9e9071591b31e9b148cb/cron/executions.py#L20-L62) [claimed/running 写入](https://github.com/NousResearch/hermes-agent/blob/3c27eb6234bf91b8ceee9e9071591b31e9b148cb/cron/executions.py#L135-L172) | `cron runs` 为 0；没有健康执行尝试。 | 实现后须验证一次无健康内容 canary 的状态顺序和崩溃点。 | `claimed`/`running` 不等于健康业务状态已提交。 |
| 3. 业务状态提交 | SQLite 事务提供 `BEGIN`/`COMMIT`/`ROLLBACK`，唯一约束可拒绝重复键；专用健康库因此可以持久保存“主人 + IANA 当地日期 + 复盘种类”的唯一业务提交、发送尝试与未知态。[SQLite 事务](https://www.sqlite.org/lang_transaction.html) [SQLite 唯一约束](https://www.sqlite.org/lang_createtable.html#unique_constraints) [Python `sqlite3`](https://docs.python.org/3.11/library/sqlite3.html) | 只有原生 Cron `executions.db`；没有健康专用库、业务提交行或 outbox。 | 表结构、唯一键和事务边界尚属 HOW；须在隔离 canary 验证重复、回滚与重启。 | 原生 Cron 的任务结果/`last_status` 不是健康业务提交；数据库事务也不能把外部模型或微信副作用纳入同一原子提交。 |
| 4. 接口接受 | 腾讯 `sendmessage` 响应最多提供可选 `ret`/`errmsg`；Hermes 无显式错误时返回自己生成的本地 `client_id`。Cron 也只按 Adapter 返回结果记录 delivery outcome。[腾讯响应类型](https://github.com/Tencent/openclaw-weixin/blob/cef0bfc390393f716903e16d50408118047f87e0/src/api/types.ts#L221-L229) [腾讯发送调用](https://github.com/Tencent/openclaw-weixin/blob/cef0bfc390393f716903e16d50408118047f87e0/src/api/weixin-api.ts#L502-L520) [Hermes 本地发送标识](https://github.com/NousResearch/hermes-agent/blob/3c27eb6234bf91b8ceee9e9071591b31e9b148cb/gateway/platforms/weixin.py#L1928-L1944) [Cron 投递后记账](https://github.com/NousResearch/hermes-agent/blob/3c27eb6234bf91b8ceee9e9071591b31e9b148cb/cron/scheduler.py#L4000-L4059) | 没有健康发送尝试；本票未发消息。 | 网络超时/中断时请求是否已被服务端接受无法只读判定；须保留 `unknown`。 | 接口未报错、本地 `client_id` 或 Cron 的 `delivered` 标签都不是主人真实收到。 |
| 5. 主人真实到达 | 已检查的腾讯类型与发送响应没有服务端消息 ID、客户端展示、收取或已读回执；Hermes 也没有更强的端到端回执。 | 没有本次主人端确认。 | 只有经批准的唯一无健康标记 + 主人确认，才能建立一次具体 canary 的“看到”；仍不能推出长期 exactly-once。 | 不得把 API 接受、进程日志或发送协程返回冒充主人收到。 |
| 6. 健康核心当前可验证 | Plugin 可另行暴露不含健康正文的状态。Hermes 内置详细 readiness 只检查普通 `state.db` 可读、配置、磁盘、Gateway/平台计数和后台队列；简单 `/health` 仅返回服务存活信息。[readiness 探针](https://github.com/NousResearch/hermes-agent/blob/3c27eb6234bf91b8ceee9e9071591b31e9b148cb/gateway/readiness.py#L27-L119) [Bearer 鉴权](https://github.com/NousResearch/hermes-agent/blob/3c27eb6234bf91b8ceee9e9071591b31e9b148cb/gateway/api_server.py#L1645-L1722) [健康路由](https://github.com/NousResearch/hermes-agent/blob/3c27eb6234bf91b8ceee9e9071591b31e9b148cb/gateway/api_server.py#L1938-L1944) [健康处理器](https://github.com/NousResearch/hermes-agent/blob/3c27eb6234bf91b8ceee9e9071591b31e9b148cb/gateway/api_server.py#L2814-L2875) | Partner PID 没有 TCP 监听；健康 Plugin/专用库/四项核心自检均不存在。Gateway/Ticker 心跳近期更新，只证明循环近期写过心跳。 | 四项核心各自的状态信号和陈旧阈值尚待 HOW；真实模型调用也未获准。 | `/health=ok`、systemd active、Ticker 心跳或“模型已配置”不能证明画像读写、问答、每日复盘和安全闸门当前都可用。 |
| 7. 跨故障域观察仍可用 | systemd 能在同一主机重启进程；硬件 watchdog 可在配置条件下重启主机；QEMU Guest Agent 提供宿主机查询来宾的通道。Hermes 官方也明确：监控 Gateway 自身应放在其外部。[systemd Restart/Watchdog](https://manpages.ubuntu.com/manpages/jammy/man5/systemd.service.5.html) [watchdog](https://manpages.ubuntu.com/manpages/jammy/man8/watchdog.8.html) [QEMU Guest Agent](https://www.qemu.org/docs/master/interop/qemu-ga.html) [Hermes 外部监控边界](https://github.com/NousResearch/hermes-agent/blob/3c27eb6234bf91b8ceee9e9071591b31e9b148cb/website/docs/guides/cron-script-only.md#L232-L240) | root 用户作用域的 Partner unit 为 `Restart=always`、5 秒后重启；无 systemd watchdog/`OnFailure`。系统作用域没有 Partner unit；同机系统作用域的 `watchdog.service` 与 `qemu-guest-agent.service` active。未发现已接线的跨主机轮询、失联判定或主人通知。 | 云/宿主机侧是否正在轮询、是否有独立持久状态和主人通知均未知；须选定外部观察者后再做获准实验。 | 同机 systemd、root 用户作用域默认 Hermes、系统作用域 dashboard、主机日志或 active 状态都不是跨主机能力；QGA 进程存在也不等于云侧已观察并通知主人。 |

七层只能沿证据向后推进，不能反向推断。特别是“任务存在 → 执行开始 → 业务提交 → 接口接受 → 主人到达”之间每一步都可能失败或变成无法确认；“核心当前可验证”和“跨故障域观察仍可用”又是两条独立证据链。

## 4. 主人自然日、持久化与恢复边界

Hermes 固定源码按 `HERMES_TIMEZONE`、配置 `timezone`、服务器本地时区的顺序解析时区，并使用 Python `zoneinfo`；无效时区会退回服务器本地时区，结果还会缓存至显式重置。[Hermes 时区解析](https://github.com/NousResearch/hermes-agent/blob/3c27eb6234bf91b8ceee9e9071591b31e9b148cb/hermes_time.py#L1-L13) [读取、校验与缓存](https://github.com/NousResearch/hermes-agent/blob/3c27eb6234bf91b8ceee9e9071591b31e9b148cb/hermes_time.py#L37-L133) Python `zoneinfo` 能处理 IANA 时区和夏令时 `fold`，但不会替产品决定“主人现在属于哪个时区”。[Python `zoneinfo`](https://docs.python.org/3.11/library/zoneinfo.html)

现场主机、Partner 配置均为 `Asia/Shanghai`，systemd 报告 NTP 已同步；这只能证明当前服务器/配置时钟基础，不能证明它就是主人现实所在地，或主人移动后会自动更新。自然日业务键必须来自经授权保存的主人 IANA 时区事实，不能只读服务器日期猜测。

- Hermes Cron 有持久执行尝试，但它是审计账本，不是自动重试队列；重启后只有在旧 owner 进程已不存在时才把未完成尝试改成 `unknown`，且不会自动重跑。[执行恢复边界](https://github.com/NousResearch/hermes-agent/blob/3c27eb6234bf91b8ceee9e9071591b31e9b148cb/cron/executions.py#L1-L5) [unknown 恢复](https://github.com/NousResearch/hermes-agent/blob/3c27eb6234bf91b8ceee9e9071591b31e9b148cb/cron/executions.py#L199-L233)
- 重复 Cron 会在实际业务执行前推进下一次运行，形成调度层 at-most-once 倾向，也留下“已推进、业务未提交”的崩溃缺口。[执行前推进](https://github.com/NousResearch/hermes-agent/blob/3c27eb6234bf91b8ceee9e9071591b31e9b148cb/cron/jobs.py#L1990-L2004)
- systemd timer 的 `OnCalendar=` 能表达墙钟计划，`Persistent=true` 能在 timer 停止期间漏过触发后补触发一次；但现场没有该 timer，它仍在同一主机，且不能证明健康业务提交或微信送达。[systemd.timer 官方手册](https://manpages.ubuntu.com/manpages/jammy/man5/systemd.timer.5.html)
- 专用 SQLite 可以把调度意图、执行尝试、自然日业务提交、发送尝试和结果未知分别持久化，并用唯一键阻止同一业务提交重复；但外部 API 与数据库之间没有分布式原子事务。无论“先提交再发送”还是“先发送再提交”，崩溃窗口都可能留下未知态，正确 CAN 边界是持久保存并停止盲目重发，而不是宣称 exactly-once。

## 5. 不含健康正文的核心自检信号

下列是现有 Plugin/SQLite/Python 接口能够承载的**候选信号类别**，不是已选 HOW，也不是现场已实现事实：

| 健康核心 | 可提供的无正文信号 | 当前现场与证明边界 |
|---|---|---|
| 健康画像读写 | Plugin/数据模式版本、专用库只读打开、唯一约束存在、非健康随机哨兵可解密、最近成功提交时间/事务标识 | 当前均无。只读成功不能替代写入/加解密 canary；普通 Hermes `state.db` 正常与健康库无关。 |
| 健康问答 | 路由配置有效、最近一次获准的无健康内容合成探针结果与时间 | 当前只可能知道“模型已配置”，本票未调模型；配置存在不等于模型请求可通过。 |
| 每日复盘 | 主人 IANA 时区事实有效、当地日期键、Cron 尝试、当日业务提交、决策状态、outbox/发送未知态 | 当前任务、尝试、业务提交与 outbox 都不存在。 |
| 固定安全闸门 | Plugin/规则包版本或摘要、固定无正文测试向量的最近通过时间和失败类别 | 当前没有健康 Plugin 或规则包；代码装载也不能替代闸门执行证据。 |

这些信号可被映射为 TO 的“活跃、异常、无法确认”，并只披露当前状态、最后确认时间、受影响核心能力和主人影响，不需要披露健康正文。阈值、合并规则与通知渠道仍须后续 HOW 决定。

Hermes 进程内还有每 30 秒 best-effort 原子写入的 Gateway 心跳，以及在事件循环卡死时可硬退出进程的线程 watchdog；写心跳失败会被吞掉。[进程心跳与 watchdog](https://github.com/NousResearch/hermes-agent/blob/3c27eb6234bf91b8ceee9e9071591b31e9b148cb/gateway/shutdown_watchdog.py#L46-L270) [Gateway 接入点](https://github.com/NousResearch/hermes-agent/blob/3c27eb6234bf91b8ceee9e9071591b31e9b148cb/gateway/run.py#L6119-L6125) 它们能帮助同机进程恢复和陈旧判断，但仍不能验证上述四项核心，更不能在整机失联时观察自己。

## 6. 故障域与主人通知边界

| 观察位置 | 当前/受支持工具 | 能覆盖 | 自身失效边界与主人通知 |
|---|---|---|---|
| Partner 进程内 | Cron Ticker、runtime/readiness、事件循环 heartbeat/watchdog | 局部逻辑、循环卡死、近期调度活动 | 进程退出即不可用；不能从故障域外证明失联，也不能保证通知。 |
| 同一主机、Partner 进程外 | root 用户 systemd manager 及其 default Hermes、OS timer/cron、系统作用域 dashboard、主机 watchdog | root 用户 manager 存活时可观察/重启 Partner 进程；主机 watchdog 可处理部分整机卡死 | 主机断电、内核/存储严重故障或出站网络断开时共同失效；同机微信 Adapter 也无法可靠通知主人。 |
| 宿主机/云平台侧 | QEMU Guest Agent 是宿主查询通道；云平台通常可另有实例状态工具，但本票没有目标提供商的一手配置证据 | 理论上可越过来宾进程/部分整机故障域 | 现场仅证明来宾侧 QGA active；没有证明宿主轮询、失联阈值、独立存储或通知已配置。保持未知。 |
| 独立主机/外部服务 | 可轮询经鉴权的无正文状态面，或接收独立 heartbeat 并持久保存最后确认/状态转换 | 可在 Partner 进程或整机离线后继续判定失联 | 当前没有部署。还需要独立时钟、持久状态、最小权限凭据、隐私安全 payload、独立网络/通知通道；其自身也必须有陈旧/失效边界。 |

现场系统 manager 中不存在 Partner unit；只有 root 用户 manager 中的 Partner unit 为 `Type=simple`、`Restart=always`、重启等待 5 秒，`WatchdogUSec=0`、`OnFailure=` 为空，root `Linger=yes` 且用户 manager active。该用户作用域配置能在该 manager 与主机仍工作时恢复 Partner 进程，却没有状态变化通知。Partner 当前也没有 TCP 监听，因此即使固定源码含 `/health`，现场外部观察者也没有正在服务的该入口。

`network-online.target` 只用于启动期排序，并非持续网络监控；不能从它 active 推出微信网络仍通。[systemd 网络目标语义](https://manpages.ubuntu.com/manpages/jammy/man7/systemd.special.7.html) 现场清单中未发现已接线的 Prometheus/exporter、Zabbix、Telegraf、Datadog、Netdata、Monit 或外部 heartbeat 客户端；这不是对云平台控制面的否定，只把其当前状态保留为未知。

TO 要求状态离开“活跃”时一次通知、恢复时一次通知。要在 Partner 或整机故障后做到这一点，观察者必须位于被观察故障域之外，并独立持久化上次状态与转换；同一 Partner 微信 Adapter 无法在自身、主机或出站网络故障时完成该保证。当前没有这样的已验证路径。

## 7. 尚未证明与最小批准实验

当前尚未证明：主人实际 IANA 时区；每个当地自然日唯一业务提交；健康专用库与四项核心自检；模型当前可请求；iLink 上下文令牌可用；接口接受后的主人展示；重启/超时两侧的真实发送结果；任何云侧或跨主机观察者仍在工作；状态转换能按 TO 只通知一次。

本票没有授权下列实验。若后续 HOW 选定候选，最小实验和停止条件是：

1. **账本 canary**：在隔离、无健康数据环境验证自然日唯一键、事务回滚、重启后 `unknown` 与不盲重发。任何可能写入正式健康库、触发真实任务或影响现有 Hermes 时停止。
2. **核心自检 canary**：只用无健康正文的固定测试向量，分别验证画像读写/解密哨兵、一次模型探针、当日提交和安全闸门。若会调用未批准模型、记录正文或访问正式画像，停止。
3. **微信到达 canary**：向已确认主人发两个不同的无健康标记，分别记录接口结果与主人看到的数量；超时、重复、错收件人或出现非测试消息立即停止。该实验只能证明这一次，不能建立长期回执合同。
4. **故障域 canary**：只有在独立观察者已配置、维护窗口和恢复通道获批后，才分别验证 Partner 进程失联/恢复与整机或网络失联。若无法证明隔离、恢复路径丢失、影响 default/正式 Partner、或通知将携带健康正文，禁止开始或立即停止。

## 8. CAN 边界

固定 Hermes、Python/SQLite、systemd 与可选外部观察路径共同提供了实现既定状态承诺的基础能力；没有证据表明 TO 在现有 Plugin 路线下不可实现。本票因此不创建负向 CAN，也不选择监控或通知 HOW。

后续 HOW 必须继续保留七层分离，并明确主人时区来源、业务提交幂等、发送未知态、四项核心无正文自检、跨故障域观察者及其自身故障边界。直到实现和获准实验完成前，现场事实只能写成“基础 Hermes 运行；健康管家未部署，跨主机观察与主人通知未证明”。
