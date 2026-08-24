# 115 - 实现任务当地日复盘与分层主人投递

Type: task
Status: ready-for-agent
Parent: [健康管家首发 TO、CAN 与 HOW 决策闭合路线](../map.md)
Blocked by: [113 - 实现 StrictHealthLLM 治理知识与非诊断回答](113-implement-strict-health-llm-governed-knowledge-and-nondiagnostic-answer.md), [114 - 实现主人设置数据权利与业务状态](114-implement-owner-settings-data-rights-and-business-status.md)

**What to build:** 让健康管家根据主人目标、画像/证据变化和既有任务事件建立可验收任务，并按主人当地自然日运行复盘、生成 outbox 意图和分层主人 Weixin 投递。任务、业务提交、发送尝试、接口接受、送达、已读和未知必须保持不同事实。

**Contract synchronization (2026-08-25):** `d1450bc`、`5e94d3c`、`6a25954` 的既有实现保留为增量加固基线，不得整体重写。下列 `115-A1`—`115-A8` 是旧版关闭后补入的当前验收合同；独立差额审计尚未证明它们全部通过，因此本票重新开放为 `ready-for-agent`。实施 Agent 必须先 claim，只修复当前合同相对既有实现的缺口；Ticket 116 在本票经独立复审重新关闭前仍受阻塞。

**Blocked by:** 113 - 实现 StrictHealthLLM 治理知识与非诊断回答; 114 - 实现主人设置数据权利与业务状态

## Previous broad-contract baseline

下列六项已由既有提交和旧版复审形成绿色基线；实施 Agent 必须保留其回归，不得把它们当成待从头实现的范围。当前是否完成只由后面的 `115-A1`—`115-A8` 差额合同决定。

- [x] `TaskEngine` 独占任务目的、承担者、允许资料、阶段、批准、验收、四类主标签、查重和后继关系；Skill 和模型只能返回候选。
- [x] 每个主人当地自然日最多一次复盘；时区变化从下一有效当地日开始，不补做、堆积或重复旧日；无行动保持安静。
- [x] 任务在发送前重新检查当前证据、批准、控制、时间窗、重复关系和 writer fence；失效或撤回不生成旧效果。
- [x] 业务事实和 transactional outbox 意图原子提交；发送在事务外执行并记录形成、提交、尝试、接口接受、送达/已读和未知层级。
- [x] Weixin 发送使用稳定幂等标识；未知或可能已离站的效果冻结自动重试，不能把接口无错改写为主人已看到或任务 solved。
- [x] 合成测试覆盖复盘恢复、任务 claim/lease、控制竞态、outbox 崩溃、重复投递、未知回查和状态投影。

## Implementation contract

### Start gate and authority to load

只在 Ticket 113、114 均 `resolved` 后开始。实现前必须读取：

- [当前实现 Spec](../spec.md)的“任务、复盘和业务三态”“支持联系人和投递”“Plugin/core 深接口”“Testing Decisions”；
- [当前 HOW 证据](../evidence/36-how-route-after-current-can-closure-20260822.md)的“Tasks, daily review, controls, delivery, and business status”和代表性主人旅程；
- [`CONTEXT.md`](../../../CONTEXT.md)中的“健康任务候选来源”“健康任务”“健康任务四项流程职责”“健康任务状态与恢复”“健康任务目标调整”“健康任务验收”“健康任务通知选择”“每日复盘”“主动支持”和“处理结果无法确认”；
- Ticket 112 的画像/证据/职责候选，Ticket 113 的受控模型结果，以及 Ticket 114 的设置、独立控制、时区和 StatusProjector typed facts，以最终已验收接口为准。

任一 blocker 未闭合时只能只读审计，不得 claim、写任务/outbox 占位实现或假设其接口。

### Scope and ownership

本票完整拥有：

1. `TaskEngine` 的任务身份、目的、承担者、允许资料、阶段、批准、验收、四类主标签、查重和前后继关系；
2. owner generation + 当前 IANA 时区 + 当地自然日的一次复盘账本；
3. 业务结果与 transactional outbox 意图的原子提交，以及事务外执行后的分层交付事实；
4. 主人 Weixin 投递的稳定幂等身份、未知冻结和恢复重判。

本票不实现安全/诊断/联系人警报（Ticket 116）、永久删除/迁移（Ticket 117）或真实 Hermes/Weixin 宿主接线（Ticket 118）。发送端只使用合成 delivery port；真实接口接受、送达和已读只有实际可证明时才可记录。

优先把新职责放入聚焦模块，例如 `tasks.py`、`review.py`、`delivery.py`；`core.py` 负责编排单一权威转换，`storage.py` 提供原子事务与恢复原语，`plugin.py` 只执行 core 发出的受控效果。不得把任务状态、outbox 状态或交付状态压成一个布尔字段。

### Required semantic contracts

- 每个任务绑定稳定 ID、具体目的、画像/证据或主人目标锚点、承担者、允许资料、外部边界、当前阶段、可判定验收、批准引用、四类主标签、查重键和前/后继关系。
- 四类主标签只有 `active`、`solved`、`failed`、`cancelled`；等待、延期、能力缺口、单步失败、claim/lease 和结果未知是独立事实。终态历史不可原位重开；新事实需要新建链接后继任务。
- 主人可独立取消、延期或调整普通任务。原目标内的必要小步骤留在原任务；扩大主人负担、联系次数、资料、接收方、外部效果或验收含义时必须新建关联 `active` 任务，明确等待 Ticket 114 的 current `ExecutionScopeApproval`，主人拒绝后 `cancelled` 且同一旧依据不重复提出。TaskEngine/Skill/模型只有提出 approval request 与校验/消费已提交批准的权力，无 grant/revise/revoke 权。
- 一个任务只有在预先说明或经主人知情修订的验收有相称证据时才能 `solved`；接口接受、提醒形成、送达或主人回复各自只证明对应层级。
- Ticket 110 已有的 `ExecutionLease` 继续只作为“一个受控外部 effect”的 current-head fence，保持其已验收 schema/序列化合同，不为任务调度增加到期字段。任务执行另用 `TaskClaimLease`：至少绑定 claim ID、task ID、generation、holder role、`runtime_epoch`、同一 epoch 内 core 单调时钟的 `acquired_at_monotonic_seconds`/`expires_at_monotonic_seconds`（秒）和 task revision/CAS identity；单调时刻绝不跨 epoch 比较。core 重启会生成新 epoch，使所有旧 task claim 失效且旧 holder 提交被拒绝；若关联外部 effect 可能已经离站，仍由原 `ExecutionLease`/transition/readback 保持 unknown，不能因任务重新 claim 而盲重做。两种 lease 都不改变四类主标签。
- 复盘键绑定 owner generation、IANA timezone 和 local date。每个当地日最多一个已提交 review；时区改变从 Ticket 114 给出的下一有效当地日起生效，恢复只重判当前日，不补放旧 backlog。
- 无行动复盘提交无通知结果；有行动时先查重/合并任务，再按主人当前普通通知选择形成 outbox 意图。
- 业务事实与 outbox intent 在同一 local/current-head transition 中提交；适配器发送在事务外发生，并以稳定 effect/client ID 回交完整终态。
- 交付层级至少区分 formed、business-committed、attempted、interface-accepted/rejected/unknown、delivered、read/actual-action；无法证明的高层不得由低层推导。
- `DeliveryEvidenceAuthority` 固定各层证明来源：core 证明 formed/business-committed；绑定当前 effect 的 adapter 只证明 attempted/interface result；delivered/read 只接受绑定 effect ID 的渠道权威回执；actual-action 只接受后续唯一准入主人事件或另行获准权威证据。每层绑定 producer contract、generation、signature/attestation 和 replay identity。
- effect 可能已经离站但结果未知时冻结自动重试；只有主人知情接受重复风险后的新因果动作才能产生新的有界尝试。
- 发送前重检 current evidence、approval、controls、time window、dedupe relation、generation 和 writer fence；任一失效都不执行旧 intent。
- `active` ↔ `abnormal`/`cannot-confirm` 的全局状态变化形成一次性主人通知；需要主人新增授权、决定 unknown 是否承担重复风险或知悉当前能力缺口时，形成一次无多余健康正文的必要行动请求。两类结果不受普通通知关闭或主动支持暂停吞掉，但同一 causal state 不重复催促。

### Acceptance matrix

| ID | Required observable result | Forbidden substitute | Required test evidence |
|---|---|---|---|
| 115-A1 | TaskEngine 对同一缺口/目标查重，保留完整目的、阶段、批准、验收、四标签和后继关系；延期/调整留痕，范围扩大建立待批准关联任务并只消费 Ticket 114 的精确批准 | 每个 Skill 步骤建任务、模型/Skill/TaskEngine 自批、用初始化同意/空白布尔批准、静默扩大原任务或任务标题冒充事实 | 建立/合并/不建立、延期/调整、scope approval 匹配/旧版/撤回/扩大、拒绝不重提、阶段推进、终态后继、标签互斥和候选无写权测试 |
| 115-A2 | `solved`、`failed`、`cancelled` 严格按业务验收形成；等待/延期/未知仍作为独立事实 | 接口 accepted、消息 sent、Cron 完成或提醒送达冒充 solved | 画像更新、提醒、资料查找、拒绝/延期、能力缺口和未知的状态表测试 |
| 115-A3 | 每个 owner local day 最多一次 review，时区变化按下一有效当地日，恢复不补 backlog；无行动保持安静 | 服务器日期、固定 24 小时、重启补发、每日强制通知 | DST、跨日、时区切换、崩溃前后、同日并发和 no-action 测试 |
| 115-A4 | 业务事实与 outbox intent 原子提交，发送只在提交后、事务外发生 | 先发送后落库、业务提交成功但意图丢失、适配器直接写任务 | 事务回滚、commit/finalize 崩溃、outbox 恢复和适配器写权拒绝测试 |
| 115-A5 | 每次投递保留稳定幂等 ID、分层不可变事实和该层权威证明，低层结果不提升为高层 | no-error=送达、accepted=已读、adapter 伪造 delivered/action、重复调用覆盖旧 attempt | 各层 producer/signature、accepted/rejected/unknown/delivered/read/action、重复回交、乱序和伪造高层结果测试 |
| 115-A6 | 未发送 intent 在执行前重检证据、批准、控制、时间窗和 writer fence；`TaskClaimLease` 按 runtime epoch/单调时钟拒绝旧 holder，既有 `ExecutionLease` 合同保持不变；未知外发冻结自动重试 | 使用提交时旧批准、撤回后继续、跨 epoch 比较单调时间、改写 ExecutionLease schema、lease 改标签、过期 holder 提交或超时自动盲重试 | task claim acquire/expire/epoch restart/CAS/旧 holder、effect lease/readback 回归、控制竞态、批准撤回、旧 fence、未知回查和主人批准新尝试测试 |
| 115-A7 | 任务/review/delivery typed facts 进入 Ticket 114 的 StatusProjector，不携带健康正文或技术堆栈 | heartbeat 或 worker 存活直接改变三态 | 核心任务故障、隔离单项投递未知、review 缺失/恢复和内容自由状态事实测试 |
| 115-A8 | 全局状态变化通知和授权/unknown/能力缺口行动请求各因果状态最多一次，且不被普通通知或主动支持暂停吞掉 | 周期 heartbeat、静默隐藏行动请求、恢复后重复催促或夹带多余健康正文 | active↔abnormal/cannot-confirm、通知关闭、支持暂停、重启/replay、主人未决定和一次性去重测试 |

每个 `115-A*` 是功能 verdict；`Required test evidence` 中以顿号、斜线、逗号或“分别/每类/全分支”列出的每个场景都是独立 Case。实现前按出现顺序登记 `115-Ax-Cyy`，每个 Case 必须映射到可单独失败、测试输出可见的 test/subTest 和独立断言；不能用一个整体断言覆盖多个 Case。测试以 Plugin -> core 受控协议和 fake delivery/current-head 为主，完成条件是全部 Case `covered=green`。

### TDD execution slices

先按当前实现逐 Case 做差额盘点：已有正确行为用 characterization test 固定并确认 `green`，只有缺失或错误行为才执行“添加红测并确认预期失败 → 最小增量实现转绿”。每个 slice 随后运行本 slice 与全部前置 slice 回归。测试按 slice 拆为 `tests/test_ticket115_task_engine.py`、`test_ticket115_review.py`、`test_ticket115_outbox.py`、`test_ticket115_delivery.py` 和 `test_ticket115_integration.py`。

1. **Task model gap characterization**：在 `tests/test_ticket115_task_engine.py` 登记任务 schema、状态表、查重、延期/调整/范围扩大、后继和非法转移 Case；已有正确行为固定为绿色 characterization test，真实缺口确认红测。完成标准：115-A1、A2 的全部 Case 已登记并形成可定位的绿色基线或红色缺口。
2. **TaskEngine gap hardening**：只对红色缺口补候选准入、任务 claim/lease、阶段、验收、查重或终态后继。完成标准：115-A1、A2 全部通过，四个 Skill/模型仍只有候选权，既有绿色行为无回归。
3. **Local-day ReviewEngine**：实现 review key、时区生效、单日一次、当前日恢复和 no-action。完成标准：115-A3 通过，重启、并发和 DST 不生成第二 review 或旧日 backlog。
4. **Transactional outbox**：实现业务事实 + intent 原子提交和事务外 effect claim。完成标准：115-A4 通过，所有故障点都能恢复为一个真实状态。
5. **Delivery ledger**：实现稳定幂等身份、分层 evidence authority、独立的 TaskClaimLease 与既有 ExecutionLease 回归、执行前重检及 unknown freeze。完成标准：115-A5、A6 通过，重启 epoch 后旧 task holder 无权提交，既有 effect fence schema 未改，低层 producer 无高层写权，可能已离站 effect 没有自动重试路径。
6. **Status and mandatory delivery integration**：把无正文 task/review/delivery facts 接入 Ticket 114 projector，并形成一次状态变化通知/必要行动请求。完成标准：115-A7、A8 通过，普通通知关闭和支持暂停不吞掉必要结果。
7. **Regression and review**：运行本票及全量验证，冻结待审 diff，再启动下面规定的 fresh-context Standards/Spec 双轴审查。完成标准：所有原始复选项和 115-A1—A8 有“测试 + 实现位置 + 结果”映射，两轴最终 verdict 均为通过。

### Verification and stop conditions

交审至少运行：

- `python -m unittest discover -v -s tests -p "test_ticket115_*.py"`
- `python -m unittest discover -v`
- `python -m compileall -q partner_health_steward tests`
- `git diff --check`

列出并审查全部未跟踪文件，记录实际 Python/关键依赖版本。若必须接真实 Weixin、把 Ticket 116 的安全联系人效果提前并入普通投递、无法取得 Ticket 114 的当前控制/时区/status 接缝，或发现会改变已选路线的事实，立即停止并报告。不得用 heartbeat、布尔 `sent`、重试循环或降低验收继续。

实施 Agent 先在本票末尾追加 `## Implementation evidence (unreviewed)`，逐 Case 记录测试名、实现 symbol、命令/结果摘要和 diff/commit identity。随后同一个顶层任务可以自行完成闭票编排，但直接编写实现的上下文不能把自评当作审查证据，必须执行以下双轴门：

1. 冻结待审代码后启动两个全新上下文的 reviewer Agent；reviewer 只读取当前仓库、权威合同、实际 diff 和测试证据，不继承实施推理或实施 Agent 的完成判断。
2. **Spec reviewer** 逐项核对当前 Spec、`CONTEXT.md`、ADR 0022、本票 required semantic contracts、禁止替代物和每个 `115-Ax-Cyy`，输出带文件/行号证据的 findings、A1—A8 verdict 和总 verdict。
3. **Standards reviewer** 独立核对适用 `AGENTS.md`、项目 agent 文档、ADR 0022、Plugin/core 权威边界、测试真实性、回归和可维护性，输出带文件/行号证据的 findings 和总 verdict。
4. 任一 A Case 非绿、验证失败、硬规范违规或未解决的 P1/P2 finding 都阻止关闭。顶层 Agent 修复后必须重跑受影响测试与全量验证，并让两个 reviewer 对最终 diff 重新给出 verdict；P3 只有在明确证明不影响当前合同且记录为后继工作时才可保留。
5. 两轴均对最终 diff 给出通过后，顶层 Agent 才能追加 `## Answer`，记录两个 reviewer 的证据、最终 Case 映射、验证命令/结果和 commit identity，并把本票标为 `resolved`。若无法启动两个 fresh-context reviewer，本票保持 `claimed`。

## Previous implementation evidence (old-contract baseline)

本节记录合同同步前的既有实施基线，只证明旧版六项宽合同下曾完成本地合成实现；它没有逐项覆盖后来加入的 `115-A1`—`115-A8`，不得作为当前验收结论。未操作服务器或真实 Weixin。

- `TaskEngine` 独占候选准入、目的/承担者/允许资料、阶段、claim/lease、批准、验收证明、四类主标签、查重和后继关系；验收绑定当前证据卡 revision digest，重启后仍保留完整终态证明。主人取消与任务状态在同一原子提交中闭合。
- `DailyReviewEngine` 以 owner、installation、时区和当地自然日形成账本；同日恢复只重算当前事实，旧日不补做，无变化不生成通知。复盘业务事实和 owner-delivery outbox 意图由 Ticket 115 prepared/commit/finalize 链原子提交。
- 发送前重新核验当前证据、批准、独立主人控制、联系窗口、当前当地日、route/disclosure 配置代际、重复尝试和 writer fence。合法 route generation 更新并重新同意后使用当前代际；旧代际意图失败关闭。
- Plugin 只通过 wire-shaped health command、controlled effect 和 managed read 接缝调用 core。适配器在 SQLite 事务外执行；稳定幂等键绑定完整权威意图，形成、提交、尝试、接口接受、送达、已读和未知保持独立事实。
- `prepared -> authorized-in-flight` 短时两阶段 marker 防止 managed read 把正常 handoff 误判为 orphan，也原子阻止并发/重复授权。适配器已发送但终态提交失败时保留 in-flight marker，TTL/重启恢复只冻结为 `unknown`，不会第二次调用 transport。
- 实现提交：`d1450bc`（任务、复盘和投递主体）、`5e94d3c`（发送前当前性加固）、`6a25954`（wire authority、原子恢复、路由代际和重复发送竞态闭合）。
- `python -m unittest discover -s tests -p "test_ticket115_*.py"` -> `Ran 102 tests in 68.359s ... OK`。
- `python -m unittest discover -s tests` -> `Ran 675 tests in 216.122s ... OK`。
- `python -m compileall -q partner_health_steward tests` -> exit `0`；`git diff --check` -> exit `0`，仅有既存 LF/CRLF 转换提示，无 whitespace error。
- 验证环境：Python `3.11.6`、SQLite `3.42.0`、`cryptography 3.3.1`。证据只覆盖本地合成 Plugin/core；真实 Hermes、Weixin、模型、部署和生产 canary 仍由后继 Tickets 验收。

## Previous review (superseded by current contract)

以下是合同同步前的历史复审记录：当时结论为 Ticket 115 满足旧版实现 Spec 与六项宽合同。该结论不覆盖后来加入的 `115-A1`—`115-A8`，也不再授权把本票标记为 `resolved`；当前权威架构决定以 ADR 0022 为准。

- **当时的 Spec 轴结论：**旧版复审曾认为任务权威、当地日复盘、原子 outbox、分层投递、当前性复核、未知冻结和恢复已有实现与合成覆盖；复审发现的路由配置代际问题已改用当时的当前代际，并增加 generation 2 重新同意和投递用例。适配器发送后终态失败的重复发送窗口曾以两阶段 marker、TTL 恢复和故障注入用例闭合。
- **当时的 Standards 轴结论：**旧版复审曾记录无硬性规范违规、freshness 重复逻辑已抽为共享 helper、旧 typed `OwnerDeliveryAdapter` 与 `DeliveryEngine` 兼容出口已移除。该记录引用的 ADR 0021 已非当前权威，不构成当前合同或 ADR 0022 的合规证据。
- 验证结果：Ticket 115 `102/102`、项目全量 `675/675`、`compileall` 和 `git diff --check` 全部通过；最终实现提交为 `6a25954`，实施证据提交为 `af80dc7`。
- 结论仅覆盖本地合成 Plugin/core 与 fake transport；真实 Partner Hermes、Weixin、模型、部署、医学审核和生产 canary 仍不属于本票验收。
