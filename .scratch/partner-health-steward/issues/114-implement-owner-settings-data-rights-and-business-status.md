# 114 - 实现主人设置数据权利与业务状态

Type: task
Status: resolved
Parent: [健康管家首发 TO、CAN 与 HOW 决策闭合路线](../map.md)
Blocked by: [111 - 实现唯一准入与主人初始化](111-implement-unique-admission-and-owner-initialization.md), [112 - 实现七 Skill 协调与日常证据画像处理](112-implement-seven-skill-coordination-and-daily-evidence-portrait-turn.md)

**What to build:** 让主人通过 `health-settings` 真实查看和控制健康管家，并看到由业务事实聚合出的 active、abnormal 或 cannot-confirm 状态。设置、停止记录、暂停主动支持、任务取消、批准撤回、查看、纠正和导出必须是相互独立的权威命令，不得由 Skill 或模型自行宣布生效。

**Blocked by:** 111 - 实现唯一准入与主人初始化; 112 - 实现七 Skill 协调与日常证据画像处理

- [ ] 支持时区、联系时间范围、表达方式、主动联系偏好和五类普通通知偏好的独立查看/修改，并显示时区生效时间和下一有效当地日规则。
- [ ] 暂停主动支持、停止新增记录、任务取消、外部批准撤回和联系人控制互不合并；停止记录期间不新增个人健康正文、不倒填恢复前缺口。
- [ ] 查看、纠正和导出只读取当前受管对象，保持证据引用、版本和权限边界，不经过普通聊天形成第二份权威。
- [ ] `StatusProjector` 只从入口、启用、密钥/状态、证据、任务、控制、模型、投递、安全和 current head 的业务事实聚合三态；进程存活、Cron 或 heartbeat 不能冒充 active。
- [ ] 设置请求缺少必需上下文、权限、current-head generation 或 writer fence 时失败关闭，并给出可确认/无法确认而不是模型自述的结果。
- [ ] 合成测试覆盖控制并发、时区切换、停止记录与恢复、查看/导出权限、纠正版本和状态投影。

## Implementation contract

### Start gate and authority to load

只在 Ticket 112 已 `resolved` 后开始。实现前必须读取：

- [当前实现 Spec](../spec.md)的“任务、联系人、控制、删除和迁移”“主人控制、删除和迁移”“任务、复盘和业务三态”“Plugin/core 深接口”；
- [当前 HOW 证据](../evidence/36-how-route-after-current-can-closure-20260822.md)的“Tasks, daily review, controls, delivery, and business status”和“三类稳定接口”；
- [`CONTEXT.md`](../../../CONTEXT.md)中的“健康管家设置面”“健康任务通知选择”“停止新增记录”“主动支持暂停”“主人数据权利”“关闭但保留资料请求”“健康画像导出”和“健康管家运行状态”；
- Ticket 111 的初始化偏好/同意结果与 Ticket 112 的 `SettingsDecision`、证据/画像读取和唯一提交接缝，以其最终已验收代码和 `## Answer` 为准。

若 Ticket 112 尚未闭合，只能做只读审计，不得 claim 或建立与其设置候选、受管读取相竞争的接口。

### Scope and ownership

本票完整拥有：

1. 主人设置、受控执行批准、当前支持联系人设置与独立控制命令的权威状态转换；
2. 受权限、对象 current version 和命令提交 CAS 约束的查看、纠正与导出；
3. 只基于业务事实的 `active`、`abnormal`、`cannot-confirm` 状态投影和一次性状态变化事实。

本票只定义后续任务、模型、投递、安全和诊断事实进入 `StatusProjector` 的稳定 typed input；不提前实现 TaskEngine/outbox（Ticket 115）、模型（Ticket 113）、安全/诊断/联系人警报（Ticket 116）或永久删除/迁移（Ticket 117）。尚未实现或无法证明的核心能力必须作为缺失/未知事实进入投影，不能用 synthetic “健康”默认值让完整产品显示 `active`。

优先把新职责放入聚焦模块，例如 `settings.py`、`rights.py`、`status.py`；`coordination.py` 只保留 Skill 候选，`core.py`/`storage.py` 负责命令编排与原子持久化，`plugin.py` 只适配已提交结果。若上游已有等价模块，扩展该单一实现，不建立第二套设置或状态真相。

### Required semantic contracts

- 本节是在 Ticket 114 尚未完成、尚未交审时对本票 implementation contract 和测试接缝的实施前澄清；不改写 Ticket 111/112 的历史事实、已验收结论或持久数据，也不改变本票目标、114-A1—A9 verdict 和既有 Case 强度。
- 设置字段至少独立表达 IANA 时区、Ticket 111 已提交的 `contact_window` 联系时间范围、表达方式、主动联系偏好，以及五类普通通知：新任务、普通阶段变化、关心提醒、任务终态、复盘摘要。不得把 `contact_window` 推断、收窄或迁移成单点 `contact_time`。五类通知各自使用显式三态 `not-configured`/`enabled`/`disabled`；上游没有旧选择时必须返回 `not-configured` 并等待主人选择，不得默认全部开启或全部关闭。
- 稳定归属只由 `owner_id + installation_id` 表达，不新增或推断 `owner_epoch_generation`。设置、联系人、批准、受管对象和纠正记录各自使用自己的 current object version/revision 判断新旧；命令上下文中的 current-head generation 与 writer fence 只用于 `prepare → commit → finalize` 时的 CAS 权威校验，不得充当稳定主人代际、对象版本或跨对象授权继承依据。route/config/disclosure generation 仍只表达各自命名域的配置版本。
- 控制命令至少独立表达暂停主动支持、停止新增记录、任务取消、`ExecutionScopeApproval` 的建立/修订/撤回，以及支持联系人的更换/专门暂停/批准撤回；一个命令只能改变被点名的控制及其必需派生事实。
- `ExecutionScopeApproval` 只能由 current owner 命令建立或修订，至少绑定 approval ID/version、`owner_id + installation_id`、task/effect request ID、承担者、具体目的、允许资料类别/稳定引用、首跳接收方、外部效果种类，以及适用的 `max_attempts`（允许外部尝试次数）、`min_contact_interval_seconds`（两次联系最小间隔，秒）、`expires_at_utc`（授权失效 UTC 时刻）、route/config/disclosure generation 和撤回状态。批准 currentness 由 approval version 与已绑定各域版本判断；命令提交另由 current-head generation/fence 做 CAS。空白/通配授权不可构造；扩大主人负担、资料、接收方、效果或验收含义必须形成新版本并重新批准，旧版本不自动覆盖后继任务。
- `SupportContactSettings` 必须允许显式 `not-configured` 状态；此时不得虚构联系人身份、联系方法、用途、最小警报字段或批准，相关 alert/correction authority 均不可用。配置后才向主人显示唯一 current 联系人可识别身份、联系方法、用途、最小警报字段、route generation、对象版本、专门暂停、警报批准和“原警报已/可能离站时向同一接收者至多一次必要纠正”的专用 authority 状态；更换联系人/方法先使旧批准与纠正 authority 失效，新对象只有完成精确披露和 owner approval 才可用。Ticket 116 只消费该权威并执行 alert/correction，不建立第二份联系人设置或批准真相。
- 时区变化记录请求时间、生效时间和下一有效当地日；不补做、堆积或重复旧日复盘。
- `TimezoneTransition` 使用 core 已提交 UTC 时刻 `requested_at`；`first_review_local_date` 是该时刻换算到新 IANA 时区后严格下一且实际存在的当地日，`effective_at` 是该日最早可表示 UTC 瞬间。生效前旧时区继续决定 review key；尚未生效的多次切换只保留最后一个已提交 pending 值，已生效历史不可改写；DST 缺失/重复时刻按“当地日最早有效瞬间”解析，重启从已提交 transition 恢复。
- 停止新增记录期间不写新的个人证据、画像、诊断、安全事件或任务，不在恢复后倒填；允许的临时回答、最低安全和无正文防重复事实由相应后续能力按当前控制检查。
- `ManagedRightsService` 不拥有独立持久 `seed/state`，也不复制健康正文。它只消费 `HealthCore.daily_state` 从 `DailyHealthState` 及 Ticket 112 纠正链形成的 owner-scoped 受管投影；查看返回该投影中的 current 受管对象及稳定引用。`correct()` 只能根据受管投影生成待提交 correction draft，不得直接修改或持久化权威状态；正式写入必须由 core 复用 Ticket 112 的纠正链和唯一 writer，经 `prepare → commit → finalize` 原子完成后才可成为 current。
- 导出是从同一 current 受管投影生成、带对象版本/快照版本/时间和证据引用的有限快照，不成为持续权威；测试只允许 serialize → schema parse validation，不提供 import/write API。纠正 draft 及最终 revision 保留原值、原因、时间、对象版本和受影响对象退出/重判请求；任何 managed read、correction 或 export 都不得建立第二份证据正文或独立持久真相。
- 设置面必须可查看资料范围、当前首跳接收方、启用/同意 generation 和 disclosure version；接收方或锁定配置变化时，受影响健康路径暂停，主人通过精确绑定 route/config-generation/disclosure 的重新说明与同意命令恢复。含义模糊的“关闭但保留资料”只形成澄清结果，不改变任何控制或启用事实。
- `StatusProjector` 只接受 core 从各域权威转换提交的 sealed、无正文 `CapabilityFactEnvelope`：至少绑定 domain、requiredness、`confirmed-ok`/`confirmed-fault`/`unknown`/`isolated`、generation、revision digest/transition ID、producer contract version、证据引用和有效期。observer、adapter 和普通调用者无构造权；缺失、未知 producer、旧 generation 或过期 envelope 默认 `cannot-confirm`。
- 状态投影遵循 `CONTEXT.md`：核心权威未知为 `cannot-confirm`；核心能力确认故障为 `abnormal`；只有所有要求的核心能力可证明且至少一个诊断范围有效时才可能 `active`。状态结果不含健康正文或底层堆栈。

### Acceptance matrix

| ID | Required observable result | Forbidden substitute | Required test evidence |
|---|---|---|---|
| 114-A1 | 每项设置可独立查看/修改并返回旧值、新值、本对象 current version、生效时间；联系时间保持 `contact_window` 范围语义；五类普通通知分别以 `not-configured`/`enabled`/`disabled` 生效 | 一个 settings blob 覆盖全部字段、把范围推断成单点、无旧值时默认通知全开/全关、Skill 自述已生效或模糊“关闭” | 字段级修改、并发更新、非法时区/时间范围、`contact_window` 边界、通知初始 `not-configured`、通知逐类选择和精确 replay 测试 |
| 114-A2 | 暂停支持、停止记录、任务取消、批准撤回、联系人控制互不联动，且未发送效果按当前控制重判 | “关闭健康管家”自动合并控制、撤回把可能已外发结果改写为未发生 | 控制笛卡尔组合、旧对象 version/旧 current-head generation、并发撤回、未知效果与恢复不倒填测试 |
| 114-A3 | `ManagedRightsService` 只消费 `HealthCore.daily_state`/`DailyHealthState` 的 current owner-scoped 受管投影；查看/导出保持对象版本、来源、证据引用和权限边界，`correct()` 只产出由 Ticket 112 纠正链正式提交的 draft | 普通聊天/Memory 或 rights 独立持久 `seed/state` 第二份权威、复制证据正文、导出反写/导入、`correct()` 直接持久化或原位覆盖历史 | owner-only 权限、受管投影范围读取、纠正 draft 继承与提交前无状态变化、经 `prepare → commit → finalize` 后 revision 可见、导出 serialize/schema-parse/只读，以及已被修订取代、权限撤回或非 current 对象版本引用拒绝测试；terminal delete/旧 snapshot 拒绝留给 Ticket 117 |
| 114-A4 | 时区从声明的下一有效当地日生效，既有 review key 不重写、不补发 backlog | 立即重算旧日、重复复盘或静默使用服务器时区 | DST/跨日/连续切换/重启、旧日不补做和生效时间主人可见测试 |
| 114-A5 | StatusProjector 对 core-sealed capability facts 产生稳定三态并说明受影响核心能力；相同事实重放同一结果 | heartbeat、进程、Cron、Plugin loaded、调用方布尔值或伪造/旧 envelope 冒充 active | active/abnormal/cannot-confirm 真值表、forged/stale/unknown-domain/过期 envelope、后续 producer 尚不存在、最后诊断范围失效和单项隔离故障测试 |
| 114-A6 | 缺权限、`owner_id + installation_id`、必需上下文、current-head generation 或 writer fence 时失败关闭且不产生部分设置/权利结果；对象 currentness 由各自 version 判断 | 模型猜测、虚构 `owner_epoch_generation`、把对象版本混作 writer generation、旧 current-head/fence 写入、先写后报错 | settings 与 correction draft 的 prepare/commit/finalize、对象旧 version、current-head CAS 冲突、未知 generation、旧 fence、原子回滚和 idempotent replay 测试 |
| 114-A7 | 主人可查看资料/首跳接收方/启用同意边界，并以精确新 route/config generation 重新同意；模糊“关闭但保留”只澄清 | 旧同意沿用、route drift 自动恢复、澄清请求静默改变控制 | managed read、route/config drift pause、重新说明/同意、旧 disclosure/旧 generation 拒绝和 no-state-change clarification 测试 |
| 114-A8 | current owner 以 `owner_id + installation_id` 归属建立、修订、撤回精确 ExecutionScopeApproval；批准 currentness 使用 approval version 与所绑定 route/config/disclosure generation，提交命令另由 current-head generation/fence CAS；扩大边界必须新批准，消费者只能校验/消费 | 初始化同意、虚构 owner epoch、空白布尔、Skill/TaskEngine 自批、旧批准覆盖新接收方/资料/效果或撤回后继续 | 全字段 grant/revise/revoke、空白/通配拒绝、scope 扩大、旧 approval version、旧 route/config/disclosure generation、旧 current-head/fence、replay、并发撤回与 unknown 测试 |
| 114-A9 | health-settings 可查看支持联系人 `not-configured`，或唯一 current 联系人/方法/用途/最小警报/route generation/对象版本/警报与纠正 authority 状态，并分别执行更换、专门暂停、批准撤回和新对象精确批准 | 未配置时虚构非空联系人、只存后端 ID、联系人更换沿用旧批准/纠正权、普通支持开关替代联系人专门控制或 Ticket 116 建第二真相 | managed read 的 `not-configured` 与 configured 分支、replace/method change、pause/resume、alert/correction authority grant/revoke/re-approve、旧 route generation/对象 version/current-head fence、权限与独立控制组合测试 |

每个 `114-A*` 是功能 verdict；`Required test evidence` 中以顿号、斜线、逗号或“分别/每类/全分支”列出的每个场景都是独立 Case。实现前按出现顺序登记 `114-Ax-Cyy`，每个 Case 必须映射到可单独失败、测试输出可见的 test/subTest 和独立断言；不能用一个整体断言覆盖多个 Case。状态真值表必须覆盖尚未实现的后续 producer，完成条件是全部 Case `covered=green`。

本次实施前澄清不得删除、合并或跳过已登记 Case，也不得以修改断言降低原验收要求。与旧歧义冲突的未提交测试须在同一 Case 下改为上述明确语义；新出现的独立场景须以连续 Case ID 追加，登记总数只能保持或增加。最终仍逐 Case 实际创建、运行并报告，不得把 contract 构造测试冒充对应行为测试。

### TDD execution slices

每个 slice 固定执行：登记本 slice 全部 Case → 添加红测并确认预期失败 → 最小实现转绿 → 运行本 slice 与全部前置 slice 回归。测试按 slice 拆为 `tests/test_ticket114_*.py`。

1. **Red schemas and command matrix**：先在 `tests/test_ticket114_contract.py` 写设置、控制、rights、consent、ExecutionScopeApproval、SupportContactSettings 与 sealed status fact 的严格构造和非法组合测试。完成标准：114-A1—A9 的 contract Case 已登记并按预期失败；`contact_window`、通知三态、联系人 `not-configured`、对象版本与 command current-head CAS 字段均有明确 schema，五类通知和独立控制有显式枚举。
2. **Settings and controls**：实现字段级命令、对象 version、命令 current-head generation/fence CAS、时区生效、独立控制、精确执行批准、可未配置联系人设置，以及 route/consent/config generation 变化后的重新同意。完成标准：114-A1、A2、A4、A7—A9 的正常、并发、重放和失败分支通过；`contact_window` 不被收窄，通知无旧值时保持 `not-configured`，单一命令不会改动未点名控制，旧 consent/approval 不会跨对象版本或其绑定域版本复用。
3. **Managed rights**：先修正 114-A3 红测接缝，使测试从 `HealthCore.daily_state`/`DailyHealthState` 受管投影构造输入，并确认它只因 projection-backed read、correction draft 或提交适配尚未实现而红；不得以独立持久 `seed/state` 作为测试夹具或实现入口。随后最小实现 owner-scoped managed read、correction draft、export snapshot，并把 draft 经 Ticket 112 纠正链的 `prepare → commit → finalize` 提交为正式 revision。完成标准：114-A3 全部读取、draft、正式 revision 和只读导出分支通过；draft 在提交前不改变权威状态，finalize 后新 revision 才可见，导出无法被当作写入口，rights 不复制第二份证据正文。
4. **Business status**：实现 sealed capability facts、权威 producer 转换、确定性投影和状态变化事实。完成标准：114-A5 的完整真值表通过，observer/heartbeat/adapter 无构造权。
5. **Authority integration**：把设置/rights/status 接入 Ticket 110—112 的唯一 writer、current-head 和回复接缝；correction draft 必须复用 Ticket 112 纠正链，经 `prepare → commit → finalize` 才形成正式 revision。current-head generation/fence 仅在该命令提交链做 CAS，对象 currentness 仍由各自 version 判断。完成标准：114-A6 通过；未知提交、旧对象 version、旧 current-head/fence 和重放不产生部分状态、第二权威或第二回复。
6. **Regression and review**：运行本票及全量验证并完成 Standards/Spec 双轴审查。完成标准：所有原复选项和 114-A1—A9 都有“测试 + 实现位置 + 结果”映射，Ticket 保持 `claimed` 等待独立审查。

当前恢复实施顺序固定为：先使修正后的 114-A3 在正确接缝上红转绿，再完成 114-A5，最后完成 114-A6 集成；受本次澄清影响的 114-A1/A8/A9 contract 与行为用例同时保持登记并回归。预期红测仅证明目标行为尚未实现，不能作为停工理由。

### Verification and stop conditions

交审至少运行：

- `python -m unittest discover -v -s tests -p "test_ticket114_*.py"`
- `python -m unittest discover -v`
- `python -m compileall -q partner_health_steward tests`
- `git diff --check`

列出并审查全部未跟踪文件，记录实际 Python/关键依赖版本；本票只做本地代码和测试工作，不操作服务器。只有在实际接入并给出具体失败证据后，确认必须提前实现后续 Ticket 的完整业务、必须合并多个控制、无法通过上游 current-head generation/fence 完成命令 CAS、无法从 `HealthCore.daily_state`/`DailyHealthState` 取得唯一受管投影，或发现其他会改变既定路线的新事实时，才立即停止并报告失败命令、失败 Case、受影响验收项和路线影响。缺少待实现 symbol、修正后的预期红测或尚未编写的最小实现均不是停工理由。不得用占位“healthy”输入或扩大普通聊天权限继续。实现 Agent 不得标记 `resolved`。

实施 Agent 在交审前于本票末尾追加 `## Implementation evidence (unreviewed)`，逐 Case 记录测试名、实现 symbol、命令/结果摘要和 diff/commit identity；独立 reviewer 才能写 `## Answer` 并决定是否 `resolved`。

## Implementation evidence (unreviewed)

本节是实现 Agent 的交审证据，不是独立验收结论；本票保持 `claimed`，未写 `## Answer`，未操作服务器。

### Diff identity and scope

- 实施基线：`main` at `08c7ebbd131791873140e0f41e455fff31da7176`。
- 实现范围：本票、`partner_health_steward/{admission,contract,coordination,core,plugin,storage,owner_authority,rights,settings,status}.py`、`tests/test_ticket114_*.py` 与 `tests/ticket114_case_registry.py`。
- 交审时工作树另有用户未提交的 Ticket 115—119 文档和 `.scratch/debug/repair_codex_thread_history_after_exit.ps1`；它们已逐项列出并排除在 Ticket 114 实施范围及后续暂存之外。
- 实现 commit identity：最终 handoff 以本基线、上述精确文件集和实施提交哈希共同标识；Ticket 115—119 与 `.scratch/debug/` 不进入本票提交。

### Per-case ledger and implementation mapping

`tests/ticket114_case_registry.py` 是本票逐 Case 证据账本：208 个 tuple 分别记录连续 Case ID、可唯一解析到测试方法的 method locator 和独立 observable。`test_case_registry_has_208_unique_cases_in_acceptance_order` 校验顺序、唯一性和各 A 项数量，`test_case_registry_dotted_test_names_resolve_when_modules_exist` 校验每个登记 locator 都能唯一解析到真实测试方法。下表中的 Case 范围逐行适用于账本中的每一个同范围 tuple；本票全量命令实际运行每个 tuple 对应测试，结果均为 green。

| Verdict / registered Cases | Exact test-name source | Implementation symbols | Command/result |
|---|---|---|---|
| 114-A1 / C01—C18 | registry rows 10—27; `test_ticket114_settings_controls`, `test_ticket114_contract`, `test_ticket114_authority_integration` | `FieldUpdate`, `NotificationUpdate`, `OwnerSettingsState`, `OwnerSettingsEngine.seed/apply/managed_view`, `HealthCore._current_owner_settings`, owner mutation status | Ticket 114 suite: every registered Case green |
| 114-A2 / C01—C34 | registry rows 30—63; settings/control and authority-integration tests | `ControlUpdate`, `OwnerControlCommand`, `OwnerSettingsState.excludes_health_recording`, `HealthCore._handle_inbound_admit`, `_daily_source_binding`, `recording_excluded_owner_correction_handoff_required`, `release_recording_plaintext_if_unowned`, `HealthPlugin.prepare_owner_correction`, body-free source/command receipts | Ticket 114 suite: every registered Case green |
| 114-A3 / C01—C31 | registry rows 66—96; rights, contract and authority-integration tests | `ManagedRightsProjection`, `ManagedRightsService.managed_read/correct/export`, `HealthCore._managed_rights_projection_from_state`, `managed_correction_draft`, `_handle_owner_mutation_prepare`, `OwnerPreparedCorrectionRecovery`, Ticket 112 daily-turn/owner mutation finalize | Ticket 114 suite: every registered Case green |
| 114-A4 / C01—C13 | registry rows 99—111; settings/control and authority-integration tests | `TimezoneTransition`, `_next_valid_local_day_start`, `OwnerSettingsEngine._apply_field/activate_due_timezone_transition`, core committed-time activation | Ticket 114 suite: every registered Case green |
| 114-A5 / C01—C21 | registry rows 114—134; status, contract and authority-integration tests | `CapabilityFactAuthority.seal/verify`, `CapabilityFactEnvelope`, `StatusProjector.project/transition`, `HealthCore.business_status`, encrypted status projection/transition storage | Ticket 114 suite: every registered Case green |
| 114-A6 / C01—C23 | registry rows 137—159; contract and authority-integration tests | `OwnerMutationContext`, `OwnerMutationRequest`, `OwnerPreparedMutation`, `OwnerPreparedCorrectionRecovery`, `HealthCore._handle_owner_mutation_prepare`, `_daily_draft_recovery_is_authorized`, generic `prepare → commit → finalize`, current-head CAS, durable body-free prepared/committed/finalized replay, transaction rollback and integrity-manifest checks | Ticket 114 suite: every registered Case green |
| 114-A7 / C01—C12 | registry rows 162—173; settings/control and authority-integration tests | `RouteConfigurationUpdate`, `ConsentRenewal`, `CloseButRetainRequest`, `OwnerSettingsEngine.observe_route_configuration/_apply_consent_renewal` | Ticket 114 suite: every registered Case green |
| 114-A8 / C01—C29 | registry rows 176—204; settings/control and contract tests | `ExecutionScopeApproval`, `ExecutionScopeConsumptionRequest/Decision`, `OwnerSettingsEngine._apply_owner_control/validate_execution_scope_consumption/rejudge_effect` | Ticket 114 suite: every registered Case green |
| 114-A9 / C01—C27 | registry rows 207—233; settings/control, contract and authority-integration tests | `SupportContactSettings`, `SupportContactCommand`, `_contact_binding`, `OwnerSettingsEngine._apply_support_contact/managed_view`, public managed settings seam | Ticket 114 suite: every registered Case green |

### TDD and verification results

- 修正 A3 接缝后先运行红测：当时共 87 项，76 通过、11 个错误；11 个错误均为尚未实现 `ManagedRightsService`，证明测试已从 `HealthCore.daily_state`/`DailyHealthState` 的受管投影进入目标接缝，而非依赖 rights 独立 `seed/state`。随后实现 projection-backed read、draft-only correction、finite export 和 Ticket 112 正式提交链使其转绿。
- 审查中追加的独立红测继续按连续 Case 修复：停止记录历史区间/无事件时间、native alias、异常退出时 transient plaintext 所有权、body-free prepare receipts、correction affected-scope 精确一致、跨重启 owner/daily 同一 CAS 恢复、A6-C23 body-free prepared correction 经标准 owner commit/finalize 恢复，以及 legacy/fresh manifest 的事务内 TOCTOU 均先暴露目标失败，再以最小实现转绿。
- A2-C22、C29—C34 明确验证：未完成 correction CAS 链仅在内存中暂时拥有正文；Ticket 112 daily aggregate 是 prepared 期唯一持久正文，owner aggregate 仅保存 `daily_turn_ref`、identity/digest 与必要设置结果；跨进程恢复只通过 public `managed_correction_draft → prepare_owner_correction → commit → finalize`，错误正文、未重登记、伪造 scope 和旧设置版本均失败关闭并清理 transient plaintext。
- 独立审查发现登记 locator 元测试未锁住模块缺失、同名多重命中和反向漏登记；修正后的元测试直接验证 208 个 locator 与 observable 各自唯一、Case ID 与方法前缀一致、每个 locator 恰好命中一个真实 TestCase 自有方法，并反向覆盖五个登记模块的全部 `test_114_*` 方法，未新增或删除验收 Case。
- `python -m unittest discover -s tests -p "test_ticket114_*.py"` → `Ran 210 tests in 46.785s ... OK`（208 个登记 Case + 2 个登记完整性元测试）。
- `python -m unittest discover -s tests -p "test_ticket11[1-3]*.py"` → `Ran 228 tests in 33.230s ... OK`（Ticket 111—113 回归）。
- `python -m unittest discover -s tests` → `Ran 573 tests in 84.083s ... OK`（项目全量）。
- `python -m compileall -q partner_health_steward tests` → exit 0。
- `git diff --check` → exit 0；仅报告现有 LF/CRLF 转换 warning，无 whitespace error。
- 验证环境：Python `3.11.6`；SQLite `3.42.0`；`cryptography 3.3.1`。

## Answer

独立 reviewer 复核结论：Ticket 114 已满足当前 implementation contract 与 114-A1—A9 验收矩阵，可标记为 `resolved`。

- 主人设置保留 Ticket 111 的 `contact_window` 时间段语义；五类普通通知和支持联系人均支持显式 `not-configured`。暂停主动支持、停止新增记录、任务取消、执行批准及联系人控制保持独立，并以对象自身 version 判断 currentness、以 current-head generation/fence 完成命令 CAS。
- `ManagedRightsService` 只消费 `HealthCore.daily_state`/`DailyHealthState` 的 owner-scoped 受管投影；纠正只先形成 draft，正式 revision 复用 Ticket 112 的 `prepare → commit → finalize` 唯一写入链。prepared owner correction、终态 receipt 和停止记录来源保持无正文，跨重启恢复不会建立第二套持久真相。
- `StatusProjector` 只接受 core-sealed capability facts；未知、过期、伪造或后续尚未实现的 producer 均不能冒充 `active`。登记账本的 208 个 Case ID、method locator 与 observable 已双向核对为唯一、完整且真实可执行，未发现 skip、xfail 或占位测试。
- 已核验实现提交 `09dc2f5d0a6b6e26aa484177e7f591dbc4967634`：Ticket 114 `210/210`、Ticket 111—113 回归 `228/228`、项目全量 `573/573` 均通过；`compileall` 与 `git diff --check` 通过。独立审查最终 P0/P1/P2 均为 0。

本结论仅覆盖本地合成 Plugin/core 合同与当前代码证据；未操作服务器，也不代表真实 Hermes/Weixin、模型、投递或生产 canary 已验收。实现路线与下一张已解锁票见[项目 Map](../map.md)，由 Ticket 115 继续承接任务、当地日复盘与分层主人投递。

