# Ticket 115 冻结实施设计

> 设计状态：候选。本文内容只有在 Ticket 115 记录通过复审的精确 commit 与 tree 后才成为 frozen；冻结前不得开始产品代码。冻结后，编码 Agent 只能按本文实现。发现新事实足以使本文不成立时必须停工并退回设计复审，不能在编码中改路线。

## 1. 身份、依据与优先级

- 实施基线：d468e0ac3e33a37efd53f03328f16dcbc42cff09。
- 只读 salvage：23d4827557b532f4eee4fe5511c458ed2b5d8e15，tree c179a9ba297f10d42aa1f534679c7d935836e213。
- salvage 不是实施基线、合并目标或既定路线。不得整体 cherry-pick 其五个提交；只能按第 12 节逐项人工提取已被本文采用的测试、纯值对象或算法思想。
- 产品权威依次为：当前 Spec、CONTEXT.md、ADR 0022、已 resolved 的 Ticket 110—114、本文、Ticket 115 的 A1—A8。测试用于证明这些合同，不能反向创造新产品或新架构要求。
- 若上位合同之间出现真实冲突，停止并记录冲突；不得用测试数量、旧实现或 salvage 自行裁决。

本文冻结的是 Ticket 115 的 HOW。后续编码 Agent 不再选择状态机、事务边界、权限模型、兼容策略或模块分工，只负责按本文实施并提供证据。

## 2. 目标与非目标

本票完成五项能力：

1. core 独占的任务建立、查重、控制、claim、推进、验收和终态；
2. 按当前主人时区的当地自然日复盘，当前日恢复但不补旧日；
3. 业务事实与 outbox intent 的同一权威提交；
4. 事务外、分层、可恢复且未知冻结的主人 Weixin 投递；
5. task、review、delivery 能力事实进入既有三态投影，并把状态变化及必要主人决定变成去重行动请求。

本票明确不做：

- Ticket 116 的安全诊断门和支持联系人警报；
- Ticket 117 的永久删除、防复活、跨安装迁移和完整 semantic manifest；
- Ticket 118/119 的真实 Hermes 宿主、真实 Weixin、真实模型、部署、凭据、canary 和主人验收；
- 修改 Ticket 110 ExecutionLease 的字段或语义；
- 建立第二套 task、status、mandatory request、outbox 或兼容真相；
- 把 salvage 的 Case registry、ticket115_contracts.py 或并行状态系统带回主线。

## 3. 全局不变量

I1. health-core 是唯一业务裁决者和受管状态写入者。Skill、模型、Plugin、Adapter、observer 和测试替身都不能提交任务、状态、outbox 或投递事实。

I2. 稳定归属只有 owner_id + installation_id。current-head generation 只用于本次 CAS；task version、approval version、route/config/disclosure generation 各自只在命名域内生效。不得新增 owner generation。

I3. 任务主标签只有 active、solved、failed、cancelled。阶段、等待、延期、claim、能力缺口和外部结果未知都是独立事实，不能替代主标签。

I4. 候选不等于事实。TaskEngine 只能消费 core 已重新解析到当前权威对象的候选；候选携带的 revision digest 只是待比较材料，不是授权。

I5. claim 只解决互斥，不授予业务权限，不改变任务主标签，也不自动改变任务阶段。外部效果仍必须使用 Ticket 110 ExecutionLease。

I6. 业务事实与 outbox intent 在同一个 Ticket115 prepared → current-head CAS → local finalize 转换中可见。Adapter 只在 finalize 后、SQLite 事务外调用。

I7. dispatch-armed 是外部效果的不可逆边界：其前必须完成最后一次当前性检查；其后系统必须按“可能已离站”处理。dispatch-armed 本身不证明 Adapter 已调用，因此不能自动产生 attempted。

I8. attempted 只由绑定本次 execution 的 Adapter completion，或渠道对该 execution 的权威回查证明。interface-accepted、delivered、read、actual-action 分别需要各自证明，低层不能提升为高层。

I9. dispatch-armed 后没有精确 completion/readback 时，效果进入 unknown 并冻结自动重试。主人接受重复风险只能建立新的因果效果和新的幂等键，不能解冻或复用旧效果。

I10. business_status() 保留 Ticket 114 的既有语义：它计算投影，并在同一加密存储事务中持久化上一次投影，使同一状态变化在并发和重启后只返回一次。Ticket 115 不得让该接口依赖 delivery issuer、route 或 mandatory request 是否可形成。

I11. 状态 domain 表示能力是否可证明，不表示某个业务对象的结果。单个任务失败、今天尚未复盘或单次投递 unknown 不能把 tasks、daily_review 或 delivery 核心能力直接判为 fault。

I12. 兼容读取只解释 d468e0a 已认证的精确旧 wire，不能补造缺失批准、claim、结果、签名、送达、已读或主人决定。无法精确分类时失败关闭。

## 4. 模块与依赖

| Module | 唯一职责 | 禁止承担 |
|---|---|---|
| tasks.py | 任务值对象、单一 TaskRuntimeState、任务转换、task claim | current-head、外部调用、route、status、legacy 通用默认 |
| review.py | LocalDayKey、pending/record/ledger、复盘纯决策 | 定时器、发送、主人设置写入 |
| delivery.py | outbox intent、分层 delivery facts、unknown decision、纯投递转换 | Adapter 调用、ExecutionLease 实现、SQLite、status 投影 |
| status.py | 复用 Ticket 114 sealed capability facts；MandatoryRequest 及其纯派生规则 | delivery effect 执行、第二状态投影 |
| storage.py | 单一 legacy decoder seam、加密 SQLite、Ticket115 prepared/finalize、execution journal、状态变化日志 | 业务取舍、Skill/Adapter 权限判断 |
| core.py | 唯一协调 Module：重新解析权威、当前性检查、Task/Review/Delivery/Status 编排、CAS 与恢复 | 网络调用、Weixin 凭据、第二个持久模型 |
| plugin.py | 验证 peer/capability；把一个 DispatchPlan 恰好交给 Adapter 一次并把 completion 回交 core | 直接读写受管状态、推断重试、生成高层 delivery facts |
| health_commands.py | immutable trusted command/receipt 与进程内不可伪造 capability | 业务状态机 |
| tasking.py | task-only 兼容 facade | re-export delivery/status/mandatory contract |

不得新增 partner_health_steward/ticket115_contracts.py。跨域编排留在 core.py；稳定值对象放回其所属深模块。

依赖方向固定为：Plugin/Adapter → core 的深接口；core → tasks/review/delivery/status 的纯转换；core → storage 的持久化原语。domain 模块不反向 import core、plugin 或 storage。

## 5. 任务设计

### 5.1 权威聚合

TaskRuntimeState 是唯一任务真相，字段固定为：

- owner_id、installation_id、version；
- tasks；
- candidate_receipts；
- control_facts；
- claims；
- unknown_facts。

不得另建 synchronized claims、task gap ledger 或 legacy shadow state。

ManagedTask 保留 d468e0a 已有业务字段，并以以下结构替代平行 source arrays：

- goal_anchor_ref：主人目标、证据缺口或既有任务事件的稳定锚点；
- goal_key：对 task-goal-v1、owner_id、installation_id、goal_anchor_ref 的稳定摘要；
- expected_result_kind：第 5.5 节允许的结果种类；
- source_bindings：TaskSourceBinding 有序集合；
- 其他既有字段：task_id、version、purpose、assignee、allowed data、external boundary、approval、acceptance criteria、primary label、phase、前后继、terminal fact、时间。

TaskSourceBinding 精确字段：

- kind：owner-goal、portrait-evidence、task-event；
- source_ref；
- source_revision_digest；
- goal_anchor_ref；
- authority_transition_id。

semantic_digest 只覆盖目标合同：purpose、expected_result_kind、assignee、允许资料、external boundary、acceptance criteria。它不覆盖 phase、control、claim、result 或来源当前 revision。

CandidateReceipt 是 replay-safe 的权威结果，字段为 candidate_id、candidate_digest、disposition、task_id 可选、goal_key、recorded_transition_id。disposition 只有 created、merged、not-established、linked-expansion。not-established 不得伪造 task_id。

### 5.2 准入与查重

core 在唯一 Ticket115 write authority 内按固定顺序执行：

1. candidate_id 已见：digest 相同则返回原 receipt；不同则拒绝。
2. 重新读取 source_ref 当前 revision、goal_anchor_ref 和 owner/install 归属；不一致则拒绝候选。
3. 用 goal_key 跨来源查重。
4. 同一 active goal 且 semantic_digest 相同：合并新的 current source binding。
5. 同一 goal 但合同维度变化：按第 5.3 节判断 ordinary adjustment 或 linked expansion。
6. terminal task 永不原位重开；仍有目标时建立显式 successor。
7. 自然语言重复无法确定时不自动建任务，只形成一次 clarification/authorization request。

Skill、模型和 Plugin 只能提交 TaskCandidate；它们不能提交 task_id、终态、批准有效性或 dedupe verdict。

### 5.3 主人控制与范围变化

TaskControlFact 为 append-only，字段包含 control_id、task_id、kind、basis_ref、previous_task_version、resulting_task_version、effective_at_utc。kind 只有 defer、resume、ordinary-adjustment、scope-expansion、owner-cancel。

ordinary adjustment 只允许改变阶段、恢复时点、下一小步或 current source binding；purpose、expected result、acceptance、assignee、允许资料、接收方、外部效果、主人负担、联系次数和频率全部不变。

任一上述合同维度扩大都建立 linked active successor/child，初始 phase 为 waiting-approval，原任务不被静默改写。新任务只消费 Ticket 114 当前 ExecutionScopeApproval；主人拒绝后新任务 cancelled，同一 goal_key + requested_scope_digest 不重复提出。

TaskApprovalBinding 固定字段：

- status：not-required、waiting、bound、withdrawn；
- approval_request_id；
- requested_scope_digest；
- approval_id、approval_version、approval_revision_digest。

bound 只在 core 重新读取 Ticket 114 当前批准，并逐项匹配 owner/install、task/effect request、assignee、purpose、允许资料、接收方、effect kind、attempt/contact bounds、expiry、route/config/disclosure generation 后成立。撤回或任一绑定域过期时转 waiting-approval/withdrawn并清除 claim，不自动 failed/cancelled。

### 5.4 TaskClaimLease

d468e0a 的 TaskLease 被 TaskClaimLease 取代；TaskRuntimeState 只保留这一组 current claims。字段固定为：

- claim_id；
- task_id；
- head_generation：仅绑定 claim 创建时的 current-head CAS；
- holder_role：由 core capability 决定，不接受调用者自报 holder_id；
- runtime_epoch；
- acquired_at_monotonic_seconds；
- expires_at_monotonic_seconds；
- task_revision；
- task_cas_identity。

单调时间只在相同 runtime_epoch 内比较。core 启动生成新 epoch，所有旧 epoch claim 立即失效。claim 创建、接管和消费都通过 TaskRuntimeState version/CAS；同一任务至多一个 current claim。

claim 不改变 phase。advance、solve、fail、形成外部 effect 前必须验证 live claim、task revision、head/current controls；成功转换消费 claim。defer、cancel、批准撤回也清除 claim。

Ticket 110 ExecutionLease 字段、序列化、lookup/release 语义保持原样；TaskClaimLease 不替代它。

### 5.5 阶段、结果与终态

active 任务阶段及合法方向固定为：

- waiting-owner → planned；
- waiting-approval → planned；
- planned → in-progress；
- in-progress → awaiting-result；
- awaiting-result → planned 或 in-progress（需要明确的新一步）；
- 任一 active 阶段可因 owner defer 进入 waiting-owner；
- 任一需重新批准的 active 阶段进入 waiting-approval；
- solved 固定 accepted；failed/cancelled 固定 closed。

TaskResultBinding 由 core 从当前权威业务结果临时构造，不能从 wire 直接输入。字段为 result_ref、kind、status、producer_contract、producer_version、producer_generation、revision_digest、transition_id、observed_at_utc。

首发允许的 kind/status 组合只有：

- portrait-update / portrait-committed；
- evidence-maintenance / evidence-assessment-committed；
- owner-inquiry / owner-answer-admitted；
- literature-result / qualified-result；
- literature-result / no-qualified-result；
- reminder-delivery / delivered；
- owner-action / owner-action-admitted。

删除 broad internal-result/completed。solve 必须覆盖全部 acceptance criteria，绑定 current TaskResultBinding 和 current evidence revision，且无 unresolved unknown。accepted、formed、attempted 或 interface-accepted 不能证明 delivered；普通 owner 文本不能自动证明 owner-action。

fail 只由 core 的确定性“目标仍需完成但当前批准边界内无合理路径且不再等待”判断触发。不存在 Plugin/wire 的 task.fail，也不存在调用者自签 TaskFailureProof。能力暂缺、批准撤回、延期和 unknown 均保持 active。

terminal task 不重开；新事实建立 successor。unknown-risk 主人决定建立新 effect，不把旧 unknown task 直接改写为 solved。

## 6. 当地日复盘

LocalDayKey 精确为 owner_id、installation_id、effective IANA timezone、local_date。不得加入 owner generation。

时区只使用 Ticket 114 已提交的 current/pending TimezoneTransition：生效前旧时区有效；从 first_review_local_date 起使用新时区；不改旧 key、不补 backlog。

DailyReviewPending 绑定：

- LocalDayKey；
- 当前 task/evidence/settings/control 摘要；
- effective timezone revision；
- action_refs；
- prepared_at_utc 与 pending_digest。

DailyReviewLedger 对每个 LocalDayKey 最多一个 committed record。没有今天的 record 表示 eligible/not-run-yet，不是 fault 或 unknown。旧日 pending 作废；当前日 pending 若时区或 state digest 变化则重新计算。

quiet review 仍提交一个 review record，但不生成 outbox。action review 在同一 Ticket115 mutation 中完成当前来源重读、任务查重/合并、review record 和按当前普通通知偏好形成的 outbox intent。

Cron、startup 和 Plugin tick 只唤醒 core；服务器日期、固定 24 小时和 missed-day replay 都不是业务时钟。

## 7. 业务提交协议

Ticket115PreparedMutation 升级为 v2，并原子覆盖 task_state、review_state、delivery_state、mandatory_request_state 和可选 health command receipt。其 base digest 必须分别绑定四个当前聚合及精确 current-head base。

固定顺序：

1. core 在 write lane 读取 owner/install、current head/fence、task/review/outbox/mandatory、Ticket 114 settings/controls/approval/route 和所需业务来源。
2. 纯计算完整 next aggregate；没有部分写。
3. storage 写入加密 local prepared，外部读不可见；prepared 同时绑定 base authority、每个 base digest、next aggregate digest、operation digest。
4. core 以完整 target 对 current-head 做一次条件 CAS。
5. CAS 返回未知时按 transition_id + operation digest 强读：
   - 同一 transition 已选中：只执行 local finalize；
   - head 仍为精确 base 且 transition 不存在：重放同一 CAS；
   - 冲突、terminal、fence 变化或无法强读：保留 pending，停止健康写、模型和外部效果。
6. local finalize 在一个 SQLite 事务中使五个聚合、receipt、final authority 和兼容归档同时可见，并清除 pending。
7. finalize 前禁止形成 DispatchPlan 或调用 Adapter。

任何 current-head target 都不含健康正文，只含既有不透明 installation/generation、revision digest、transition ID、fence、site 和 terminal 标记。

## 8. 投递与恢复

### 8.1 业务事实层

DeliveryOutbox 是 outbox/delivery 的唯一业务聚合。每个 intent 使用由 owner/install、causal request、payload digest、recipient、effect kind、route/config/disclosure generation 推导的稳定 intent_id 和 idempotency_key。dispatcher 必须先用一次 Ticket115 CAS 把唯一 attempt_ref 写成 reserved 并 finalize；只有已 finalized 的 reserved attempt 才能进入 begin_owner_delivery。

事实层严格为：

1. formed：意图已在 prepared 中形成，尚不可见；
2. business-committed：Ticket115 finalize 后可见；
3. reserved：为该 intent 分配唯一 attempt_ref，尚未发送；
4. attempted：Adapter completion 或权威 provider readback 证明该 execution 已调用；
5. interface-accepted / interface-rejected / interface-unknown；
6. delivered；
7. read；
8. actual-action。

各层 append-only。accepted 不等于 delivered，delivered 不等于 read，read 不等于 actual-action。乱序 observation 只有在其前置 identity、producer authority、signature/attestation 和 replay identity 可验证时才接纳；它不能回写更低层的虚构事实。

### 8.2 深接口与不可逆点

core 对 Plugin 只暴露两个深操作：

- begin_owner_delivery(intent_id, execution_grant) → DispatchPlan；
- complete_owner_delivery(execution_id, completion) → DeliveryExecutionResult。

begin 在同一 core write lane 内完成：重读 owner/install/head/fence、intent、当前证据、批准、独立控制、联系窗口、当地日、route/config/disclosure、attempt bounds；分配 attempt_ref；取得并核对 Ticket 110 ExecutionLease；写入 execution journal 的 dispatch-armed；然后返回最小 DispatchPlan。

写入 dispatch-armed 是不可逆点。它表示效果从此“可能离站”，不表示 Adapter 已调用。之后的主人撤回不能改写历史，只能阻止后续新效果。Plugin 收到 plan 后不得排队、缓存或二次调度，只能立即调用注入的 Adapter 恰好一次，并回交绑定 execution_id 的 completion。

Plugin/Adapter 无权构造 delivery fact、改变 task/status、选择重试或声称 delivered/read/action。Adapter completion 只说明本次调用返回、抛错或提供 provider receipt；更高层 observation 由相应渠道权威另行进入 core。

### 8.3 Execution journal

storage 新增加密、完整性受管的 owner_delivery_execution_journal_v1。它是执行恢复原语，不是第二个 DeliveryOutbox。每项字段绑定 execution_id、intent_id/digest、attempt_ref、idempotency_key、精确 ExecutionLease identity、head/fence、holder capability 和 phase。

phase 只有：

- lease-bound：已取得 lease，尚可安全释放/重取；
- dispatch-armed：已过不可逆点，可能已离站；
- completion-pending：completion 已在本地持久化，等待业务 CAS；
- cleared：业务 reconciliation 已 finalize，可删除/压缩 journal。

completion 必须先持久化为 completion-pending，再释放/终态化 ExecutionLease，随后用新的 Ticket115 CAS 把 attempted/interface result、task unknown 和 mandatory request 写入业务聚合。业务 finalize 后才清理 journal。

进程内 completion capability 不持久化。generic pending_effect_results_v1 和 Ticket 110 lease 表不改 schema；journal 只保存 Ticket115 特有恢复数据。

### 8.4 崩溃真值表

| 最后耐久点 | 恢复动作 | 禁止声明 |
|---|---|---|
| local prepare 前 | 无状态、无效果 | committed/attempted |
| prepare 后、CAS 前 | 依第 7 节重放或丢弃 | business-committed |
| CAS 已选中、finalize 前 | 只 finalize | 重新形成不同 intent |
| finalize 后、reserve 前 | 保留 pending intent，可重新调度 | attempted |
| lease-bound | 证明未 armed 后可释放/重取 | unknown/attempted |
| dispatch-armed、无 completion | 不再调用 Adapter；写 may-have-left + interface-unknown；不写 attempted | failed/not-delivered/attempted |
| Adapter 已返回但 completion 未耐久 | 只有精确 provider readback 可证明 attempted/outcome；否则同上 unknown | 自动再发 |
| completion-pending | 重放业务 reconciliation，Adapter 调用次数为 0 | 第二次调用 |
| 业务 finalize、journal 未清 | 幂等清理 | 新业务事实 |

因此一次执行的 Adapter 调用最多一次；dispatch-armed 崩溃时真实调用次数可能为 0 或 1，系统必须如实保留这种未知。

### 8.5 unknown 主人决定

OwnerUnknownDecision 必须由 core 从唯一准入主人事件和固定重复风险披露形成，绑定 owner/install、unknown_id、原 effect E0、原 intent、disclosure version、admitted owner event、affirmative/decline。

affirmative 产生新的 effect E1、attempt_ref 和 idempotency_key，全部稳定派生自 decision_id；replay 同一 decision 返回同一 E1。decline 关闭行动请求但保留 E0 unknown。任何任意 owner message、提醒回复或 Adapter 文本都不能冒充决定。

## 9. 状态与必要行动请求

### 9.1 保持 Ticket 114 状态合同

StatusProjector、CapabilityFactEnvelope、CapabilityFactAuthority、BusinessStatusResult 和 Ticket 114 的 producer manifest 继续是唯一状态体系。

business_status() 保持现有 owner-visible 行为。storage 在替换 business_status_v1 投影的同一事务中，把真正改变三态的 StatusTransition append 到 business_status_transitions_v1；三态未改变时不追加。接口仍返回 projection 与至多一个 transition，不要求 delivery route 存在。

该 transition log 是 Ticket 114 状态变化的耐久因果来源，不带 processed 标志；它不是第二状态真相。Ticket 115 的 pure reconciliation 通过 stable request id 判断是否已投影，崩溃后可重做。

producer 语义固定：

- tasks core：TaskEngine 聚合可读、合同有效且 writer/current head 一致；单个 task failed/unknown 不等于 core fault；
- daily_review core：ReviewEngine/ledger 可读且合同有效；今天尚未 review 不等于 missing/fault；
- delivery core：outbox、execution journal 和 Adapter capability 的整体一致性；单次 effect unknown 进入 non-core delivery-effects isolated fact；
- current-head 非健康始终优先，不能被 delivery unknown 覆盖或降级。

### 9.2 MandatoryRequest

status.py 拥有 MandatoryRequest、MandatoryRequestState 和纯 MandatoryRequestPolicy。不得新增 MandatoryDeliveryLedger。

request kind 只有：

- status-change；
- authorization-request；
- unknown-risk-decision；
- capability-gap。

stable request_id = H(owner_id, installation_id, kind, immutable causal_state_id)。不得包含 head generation、task version、phase、route generation、attempt 或时间。

causal_state_id 固定为：

- status-change：StatusTransition.transition_id；
- authorization-request：task_id + requested_scope_digest；
- unknown-risk-decision：unknown_id + E0；
- capability-gap：gap/terminal capability fact id + affected task/capability。

MandatoryRequestState 是唯一 obligation/dedupe 真相，状态只有 pending-route、projected(intent_id)、resolved。只有需要主人决定的 kind 才能 resolved；status-change 通过已投影事实自然闭合。

普通通知 disabled 和 proactive support paused 不抑制 mandatory request；terminal deletion、owner/install 不匹配、非 private entry、缺少必要 consent 或 route 不当前仍是硬门。route 不可用时在同一 Ticket115 mutation 中保存 causing fact + pending-route request，不构造假 recipient/outbox。route 恢复后同一 request 在同一 mutation 中投影为唯一 outbox intent。

business_status() 不直接发送，也不要求 mandatory state 已存在。core 的显式 reconcile_mandatory_requests、startup recovery、review tick 和 owner command finalize 都调用同一纯派生函数，再通过第 7 节提交。

## 10. 权限矩阵

| 主体 | 可做 | 不可做 |
|---|---|---|
| Skill / 模型 | 返回候选、草稿、来源引用 | 写任务、批准、终态、outbox、状态、发送 |
| Plugin | 以可信 peer/capability 调 core；立即执行一个 DispatchPlan；回交 completion | 读写 SQLite、判断当前性、重试、生成高层事实 |
| health-core | 重新解析权威、全部业务裁决、CAS、恢复、形成 plan | 持有 Weixin 凭据、直接网络发送 |
| storage | 验证 wire、原子持久化、journal/readback | 决定批准、结果含义或重试 |
| Adapter | 使用 plan 的最小 recipient/payload/idempotency 调一次 transport | 业务写入、伪造 delivered/read/action |
| 渠道 receipt authority | 对精确 effect/execution 提供 accepted/delivered/read 证明 | 改任务或扩大批准 |
| 唯一准入主人事件 | 形成 current owner command/actual-action/unknown decision 候选 | 仅凭自然语言被 Adapter 或模型自行解释成授权 |
| observer | 提供无正文 missing/recovered observation | 宣布 active、写健康状态、触发效果 |

health_commands.py 提供不可变 trusted command/receipt 与 process-local unforgeable capability。capability 不序列化、不进入日志、不从 wire 重建。

## 11. d468e0a 兼容升级

所有兼容只在 storage.py 的一个 decoder seam 完成。认证解密后精确分类：

1. current-v2：交给所属 domain 的严格 from_storage/from_wire；
2. legacy-d468-v1-normalizable：只匹配 d468e0a 的精确字段集合与约束；
3. legacy-unclassified：失败关闭；
4. corrupt/unauthenticated：失败关闭。

CompatibilityFact 记录 compat_id、object_kind/ref、source_schema、source_digest、decoder_contract、classification、authority_ceiling、normalized_digest。普通 domain object 不携带 generic missing/legacy flags。

读取只在内存规范化，不 eager rewrite。第一次合法业务 mutation 在同一 local prepare/finalize 中：

- 归档原始 authenticated canonical wire 与 CompatibilityFact 到 ticket115_compat_v1；
- 用原始 canonical digest 作为 base；
- 写当前 v2 聚合；
- 与 current-head target 一起 finalize。

精确归一规则：

- task：平行 source arrays 只有长度一致且各项有效时组成 TaskSourceBinding；旧 wall-clock TaskLease 只归档为 historical claim，不进入 current claims，新 runtime_epoch 下无权；旧 external approval 缺 requested scope/current revision 时转 waiting-approval；已 terminal 的历史任务保持 terminal，但 authority ceiling 禁止它授权新效果；
- review：现有 owner/install/timezone/local date 和 committed record 保留；旧日 pending 作废，当前日按当前时区与 state digest 重算；
- delivery：原层级与原 wire 归档。d468e0a 在 Adapter 调用前写出的 attempted 只能规范化为 legacy-ambiguous-attempt/may-have-left，不成为 v2 attempted 证明；已有可验证的更高层 receipt 只保留其精确层级；旧 unknown 保持 frozen；
- status：保留 business_status_v1 当前投影；升级前未持久化的历史 transition 不倒造通知；
- mandatory：只从当前耐久 causal facts 纯派生，不按时间或 task version 追补历史催促。

Ticket 117 才负责删除时清除兼容归档、跨安装语义迁移和密钥销毁；Ticket 115 只保证同一 installation 的本地升级。

## 12. salvage 使用规则

禁止 cherry-pick da4d43c、7bb5017、46c26fc、8ceb964 或 23d4827。

允许人工移植的内容必须同时满足：

1. 一个测试可在 d468e0a 上稳定复现本文某条不变量的违反；
2. 测试不依赖 ticket115_contracts.py、Case registry、第二 claim、owner generation、legacy wrapper 或 WIP 专用 API；
3. 纯值对象字段与本文完全一致，并重新实现在本文指定模块；
4. 算法不携带 WIP 的平行状态或权限假设。

每个移植项在实现证据中记录 salvage source commit/path、采用原因、本文条款和重写后的目标 path。其余 salvage 只作反例，不进入实现。

## 13. 固定实施检查点

编码 Agent 必须单线执行，不并行修改同一权威聚合。每个 checkpoint 先写本文行为的失败测试，再做最小实现，运行本 checkpoint、此前 checkpoint 和上游 sentinel，形成独立 commit 后进入下一步。

### CP1：兼容 seam、任务与权限

允许修改 tasks.py、tasking.py、health_commands.py、storage.py 的 task decoder、core.py 的 task command、plugin.py 的对应接缝及 task 测试。

必须证明：candidate currentness、goal dedupe、ordinary adjustment/scope expansion、精确批准、四标签、typed result、claim epoch/CAS、旧 holder、terminal successor、旧 d468 task normalization。

停止条件：出现第二 claim truth、修改 ExecutionLease、调用者自签 fail/approval、旧 terminal 历史丢失。

### CP2：当地日与原子业务提交

允许修改 review.py、Ticket115PreparedMutation v2、core review/recovery 及 review/outbox 原子测试。

必须证明：DST/跨日/时区切换、同日并发、quiet review、当前日恢复、prepare/CAS/readback/finalize 每个崩溃点、五聚合同一可见性。

停止条件：owner generation、服务器日期、旧日 backlog、finalize 前效果。

### CP3：投递执行与 unknown

允许修改 delivery.py、storage execution journal、core delivery deep interface、plugin Adapter 接缝及 delivery/fault tests。

必须证明：最后当前性检查、ExecutionLease 不变、armed/attempted 区分、Adapter 最多一次、completion-pending、全部第 8.4 节恢复分支、receipt producer 权限、unknown 新因果决定。

停止条件：自动重试 armed/unknown、Adapter 写状态、低层提升、真实 Weixin/凭据。

### CP4：状态与 mandatory request

允许修改 status.py、business status transition log、MandatoryRequestState、core reconciliation 及 status tests。正常情况下不再修改 delivery/plugin。

必须证明：Ticket 114 business_status 行为完全保留；tasks/review/delivery capability 语义；non-core isolated unknown；四种 request identity、route pending/projected、普通偏好和暂停不吞请求、重启 dedupe。

停止条件：business_status 对 delivery issuer/route 产生硬依赖、missing-today=fault、task failed=core fault、mandatory 绕过 owner/install/terminal/consent/route 硬门。

### CP5：最终集成

只修复相对本文的实现缺口，不接受新架构。运行 Ticket 110—115 targeted、项目全量、compileall 和 diff check；核对所有未跟踪文件；记录 Python、SQLite、cryptography 版本及 commit/tree。

## 14. 测试与验收证据

不设置固定 Case 数量，也不要求标点拆成 registry。每条不变量、每个合法/非法状态边、每个权限边界和第 8.4 节每个崩溃耐久点必须至少有一个能独立失败的行为测试；一个参数化测试可覆盖同一规则的等价输入，但不得用 schema 构造测试冒充端到端行为。

测试文件按职责保留/整理为：

- test_ticket115_tasks.py；
- test_ticket115_review.py；
- test_ticket115_storage.py；
- test_ticket115_delivery.py；
- test_ticket115_health_commands.py；
- test_ticket115_plugin_delivery.py；
- test_ticket115_integration.py。

必须保留未修改的上游 sentinel，至少包括：

- Ticket 110 current-head prepare/CAS/finalize 与 ExecutionLease schema/readback；
- Ticket 112 候选无写权与唯一提交；
- Ticket 114 stale approval/route/config/disclosure、状态真值表；
- test_114_a5_c21_status_transition_is_deduplicated_across_restart。

最终命令：

- python -m unittest discover -v -s tests -p "test_ticket115_*.py"
- python -m unittest discover -v -s tests -p "test_ticket11[0-4]*.py"
- python -m unittest discover -v
- python -m compileall -q partner_health_steward tests
- git diff --check

真实 Hermes、Weixin、模型、部署与 canary 仍必须报告为未验证，不能由 fake Adapter 的绿色测试替代。

## 15. 冻结、偏差与审查规则

设计冻结前，五个领域轴——状态机、事务/恢复、权限、兼容、模块/可执行性——必须由不同上下文独立审查；第六名 reviewer 做跨轴一致性检查。finding 必须引用本文条款与当前代码/上位合同证据，不能只提出“更好的做法”。

冻结记录包含：

- frozen design content commit 与 tree；
- implementation base；
- 六轴最终 verdict；
- 已解决分歧与明确非目标。

冻结后，编码 Agent 不得修改本文或 Ticket 的技术路线。实现后的 reviewer 只检查：

1. A1—A8 与本文是否被忠实实现；
2. 必需测试和上游回归是否真实通过；
3. 是否存在未声明的设计偏差或权限旁路。

只有三类 finding 阻止完成：

- 明确违反 A1—A8、本文不变量或上位硬合同；
- 测试/验证失败或证据不真实；
- 新发现且可复现的事实证明冻结路线不可实现、不安全或破坏 d468e0a 兼容。

第三类发生时立即停工，保留 checkpoint，回到本设计做有边界的 amendment 并重新审查受影响轴。不得由编码 Agent边写边改路线。纯风格、可选重构、另一种也可行的技术偏好和不影响合同的 P2/P3 进入后继 backlog，不触发大面积返工。

最终 fidelity verdict 后任何产品代码、测试、schema 或配置变化都会使 verdict 失效；只允许 Ticket/Map 关票元数据变化。

## 16. 被明确拒绝的路线

- 以 salvage 为新主线继续修补；
- 先实现大块功能、再用开放式双轴审查重新设计；
- 固定 56/152 等测试数量或全局 Case registry；
- owner generation；
- ticket115_contracts.py 跨域浅模块；
- synchronized/dual claim；
- Caller/Skill/模型自签 TaskFailureProof；
- codec-only legacy compatibility；
- MandatoryDeliveryLedger；
- business_status 依赖 mandatory delivery issuer；
- Adapter 调用前写 attempted；
- unknown 自动重试；
- 任意 owner 回复视为重复风险同意或 actual-action；
- 单个 task failed/单次 delivery unknown/今天未复盘直接把核心能力判 fault。
