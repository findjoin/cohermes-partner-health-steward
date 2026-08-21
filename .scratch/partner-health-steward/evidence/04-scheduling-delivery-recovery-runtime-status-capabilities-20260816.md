# 每日复盘、发送恢复与运行状态能力核验（Ticket 44）

## 1. 核验范围与证据纪律

- 核验时间：2026-08-16 02:24–02:33（Asia/Shanghai）。
- 目标：主机 `findjoin` 上正式运行的 `partner` Hermes；源码基线为目标现场 HEAD `3c27eb6234bf91b8ceee9e9071591b31e9b148cb`，即 Hermes v0.20.0 的官方发布提交。
- 方法：固定提交的官方文档与源码审计，加一次 SSH 只读现场检查。没有创建或修改 Cron Job，没有发送微信消息，没有安装插件，也没有停止或重启服务；没有读取或输出 token、身份值或聊天正文。
- 本报告只回答 CAN：区分任务存在、实际执行、发送接口结果、主人真实到达和健康核心可验证，不选择每日时刻、账本、状态机、监控或投递策略等 HOW。

## 2. 分层结论矩阵

| 事实层 | Hermes v0.20.0 的能力 | 当前 Partner 现场 | CAN 判断 |
|---|---|---|---|
| 定时任务存在 | 支持按配置时区解释 Cron 表达式，并由 Gateway 周期性查找到期任务 | `cron list` 无任务，`jobs.json` 不存在 | **能表达，尚未配置**；任务存在不等于执行 |
| 任务实际执行 | 有任务状态、最近结果、执行尝试账本、Ticker 心跳和错误；错过的重复周期恢复后折叠为一次执行 | `cron runs` 无执行尝试；任务开始、成功、失败日志标记均为 0 | **基座支持部分可验证，健康复盘未运行** |
| 发送接口结果 | 可把任务结果发往来源接口或微信，并分别记录任务结果与发送错误；成功结果可显式静默 | 无健康主动发送记录 | **可提交给接口，但没有健康投递事实** |
| 主人真实到达 | 没有微信客户端展示、收取或已读回执；在途发送超时还可能被当作已送达以避免重复 | 本次未发送测试消息 | **原生不能证明** |
| 健康核心可验证 | CLI 能看 Gateway/Ticker/Cron 的部分状态，Plugin 可扩展查询和状态能力 | 没有已启用健康 Plugin、健康任务、可识别的健康产品持久状态或主人状态面 | **当前不具备**；调度器活着不能证明健康管家活跃 |

## 3. 主人当地自然日与恢复语义

Hermes 的 Cron 以配置时区下的当地墙上时间计算下一次运行，Gateway 约每 60 秒检查一次到期任务。这里的 60 秒是调度器查找任务的轮询间隔，不是每日复盘允许误差或产品验收阈值。[官方 Cron 执行流程](https://github.com/NousResearch/hermes-agent/blob/3c27eb6234bf91b8ceee9e9071591b31e9b148cb/website/docs/user-guide/features/cron.md#L234-L273) [时区与到期计算源码](https://github.com/NousResearch/hermes-agent/blob/3c27eb6234bf91b8ceee9e9071591b31e9b148cb/cron/jobs.py#L664-L829)

现场服务器与 partner `config.yaml` 的时区都为 `Asia/Shanghai`，进程环境没有 `HERMES_TIMEZONE` 覆盖。因此当前调度会按上海自然日解释；它是否等于主人的现实所在地时区尚未验证，也不证明未来主人时区迁移、时区变更或跨午夜的业务规则已经存在。后续 HOW 仍须明确主人时区事实来源和“某个当地自然日已经完成复盘”的持久判断。

对于 Gateway 停止期间错过的重复任务，目标源码会跳过积压的历史槽位，恢复后只立即执行一次，再安排未来运行；不会为每个错过时点补跑并洪泛发送。[错过周期折叠源码](https://github.com/NousResearch/hermes-agent/blob/3c27eb6234bf91b8ceee9e9071591b31e9b148cb/cron/jobs.py#L2399-L2435)

这个行为符合“恢复后评估当前状态、不补发一串历史提醒”的方向，但只属于调度语义。Cron 任务在独立的新 Agent 会话中运行，不会自动知道健康档案的当前状态；健康插件仍须提供权威档案、当前自然日和主动联系状态，才能完成真正的当前状态重评估。

另一个限制是：重复任务会在实际执行前先推进并保存下次运行时间；只有这一步成功落盘后才提供调度层的 at-most-once 行为，推进尚未落盘时的窄崩溃窗口不在保证内。如果落盘后、执行完成前崩溃，这一次可能不再自动补跑；启动时无法确认是否完成的旧执行会标为 `unknown`，且官方明确不会自动重跑。[执行前推进下次运行](https://github.com/NousResearch/hermes-agent/blob/3c27eb6234bf91b8ceee9e9071591b31e9b148cb/cron/jobs.py#L1953-L2004) [执行状态与重启边界](https://github.com/NousResearch/hermes-agent/blob/3c27eb6234bf91b8ceee9e9071591b31e9b148cb/website/docs/user-guide/features/cron.md#L251-L273)

因此，原生 Cron 不等于“每个主人当地自然日业务级恰好完成一次”。后续 HOW 需要用健康产品自己的持久状态判断当日是否真正完成，并在失败或 `unknown` 时重新基于当前状态决定行动。

## 4. 静默、主动发送与不确定送达

成功的 Cron 结果可以用 `[SILENT]` 抑制消息，同时保留执行结果；这可承载“每日复盘没有值得行动的事项时保持安静”。Cron 也能把非静默结果投递到来源接口或微信。[Cron 能力与投递目标](https://github.com/NousResearch/hermes-agent/blob/3c27eb6234bf91b8ceee9e9071591b31e9b148cb/website/docs/user-guide/features/cron.md#L11-L35) [接口投递说明](https://github.com/NousResearch/hermes-agent/blob/3c27eb6234bf91b8ceee9e9071591b31e9b148cb/website/docs/user-guide/features/cron.md#L275-L314)

任务运行状态与发送错误会分开保存，所以“任务完成但发送失败”可以被识别。[任务与发送结果字段](https://github.com/NousResearch/hermes-agent/blob/3c27eb6234bf91b8ceee9e9071591b31e9b148cb/cron/jobs.py#L1689-L1717) [执行、保存与投递顺序](https://github.com/NousResearch/hermes-agent/blob/3c27eb6234bf91b8ceee9e9071591b31e9b148cb/cron/scheduler.py#L4000-L4059)

但这不是主人真实到达证明。实时 Adapter 只有显式返回成功时才算已确认；若发送协程已经在途而等待 60 秒仍未返回，源码为了避免再次发送会假定已经送达。这里的 60 秒是内部等待发送结果的最长时间，不是微信展示时限；超时后的真实结果仍然未知。[Adapter 成功判定与在途超时](https://github.com/NousResearch/hermes-agent/blob/3c27eb6234bf91b8ceee9e9071591b31e9b148cb/cron/scheduler.py#L1384-L1402) [避免重复的超时分支](https://github.com/NousResearch/hermes-agent/blob/3c27eb6234bf91b8ceee9e9071591b31e9b148cb/cron/scheduler.py#L1786-L1920)

结合 Ticket 43 已核验的微信边界，接口成功最多表示 iLink 未报告错误，不表示主人微信已经展示、收取或已读。Hermes 也没有健康主动消息的稳定业务投递标识和端到端恰好一次证明。后续 HOW 必须保留“无法确认”状态并禁止盲目重发，不能把接口接受写成真实到达。

## 5. 运行状态的真实性边界

操作者 CLI 可以查看 Gateway、Ticker 最近心跳与最近成功、任务状态、最近执行和发送错误；模型侧的 Cron 列表只公开任务级字段，不构成统一的健康产品状态。[操作者 Cron 状态](https://github.com/NousResearch/hermes-agent/blob/3c27eb6234bf91b8ceee9e9071591b31e9b148cb/hermes_cli/cron.py#L217-L331) [模型侧任务列表字段](https://github.com/NousResearch/hermes-agent/blob/3c27eb6234bf91b8ceee9e9071591b31e9b148cb/tools/cronjob_tools.py#L555-L589)

Ticker 心跳和错误记录本身是 best-effort：写入失败会被吞掉。健康产品必须把缺失或陈旧映射为“无法确认”；但当前原生 CLI 在 Gateway PID 存在而心跳值缺失时仍可能落入绿色提示，所以原生状态本身不满足该产品语义。[Ticker 状态持久化](https://github.com/NousResearch/hermes-agent/blob/3c27eb6234bf91b8ceee9e9071591b31e9b148cb/cron/jobs.py#L834-L1006) [原生 CLI 状态分支](https://github.com/NousResearch/hermes-agent/blob/3c27eb6234bf91b8ceee9e9071591b31e9b148cb/hermes_cli/cron.py#L269-L306) 更重要的是，这些指标只覆盖 Gateway 和调度器，不能证明健康档案、健康问答和每日复盘三项核心能力都正常。

Hermes 官方也明确说明：如果要监控 Hermes/Gateway 本身是否存活，观察路径必须独立于 Gateway；同一进程无法在自身完全停止时可靠发出故障通知。[独立存活监控边界](https://github.com/NousResearch/hermes-agent/blob/3c27eb6234bf91b8ceee9e9071591b31e9b148cb/website/docs/guides/cron-script-only.md#L232-L240)

因此，后续 HOW 需要建立无健康正文的综合状态权威，将核心能力、调度、最近确认和发送不确定态组合成主人可查询的“活跃、异常、无法确认”，并提供状态变化的一次通知。具体观察方式尚未选择。

## 6. 目标现场事实

- `hermes-gateway-partner.service` 为 `active/running/enabled`，MainPID `143611`，自 2026-08-07 07:30:33 +08:00 起运行。
- 2026-08-16 02:28:32 查询时，Ticker 最近心跳与最近成功均为 02:27:49，即距查询 43 秒；物理含义只是调度循环近期成功写入了心跳。
- `hermes --profile partner cron list` 返回无任务；`cron runs` 返回无执行尝试；`jobs.json` 不存在。保留日志中的 Cron tick error、任务开始、任务成功、任务失败、发送成功和发送失败标记均为 0。
- `executions.db` 存在但 CLI 历史为空；没有 Cron 任务失败、被重启中断或 `unknown` 执行样本可验证恢复行为。
- 未发现已启用健康 Plugin、健康任务、可识别的健康产品持久状态或主人状态面；profile 中也没有 Plugin manifest。
- `cron status` 的 PID 列表同时包含 Partner 与 default Gateway，不能只凭该列表证明严格的 profile 状态隔离。

现场结论只能是“目标 Hermes 调度器近期存活，但健康管家尚未部署”。它不能证明每日复盘任务存在或执行、主动消息不重复、主人微信真实收到、健康核心活跃、主人可查询状态或收到状态变化通知。

## 7. TO-CAN 判断与后续边界

目标版本已经提供时区 Cron、执行账本、静默结果、接口投递、Plugin 扩展面和部分无内容状态信号，仍存在在 Hermes 架构内实现产品目标的空间。本票不创建 TO-CAN 差距决策，也不降低已确认目标。

同时，不能把内置 Cron 单独当成完整健康能力。后续 HOW 必须明确：主人时区事实与变更、当地自然日业务幂等、权威健康状态读取、失败和 `unknown` 后的当前态重评估、主动消息逻辑投递标识、发送不确定态、综合三态状态，以及独立于被观察故障域的失联确认。若后续约束为“禁止任何独立于 Gateway 的观察路径”，则 Gateway 或整机完全离线时无法自行向主人发出状态变化通知，届时才需要创建 TO-CAN 差距决策。
