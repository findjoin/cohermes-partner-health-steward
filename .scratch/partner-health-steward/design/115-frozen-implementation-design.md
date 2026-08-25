# Ticket 115 冻结实施设计

> 设计状态：第二版候选，尚未 frozen。本文只有在同一内容 commit/tree 通过规定复审、写入 Ticket 115 并由主人确认后才成为实施路线。此前禁止修改产品代码。冻结后，编码 Agent 只实现本文，不再选择状态机、事务、权限、兼容或模块路线。

## 1. 设计身份与依据

- 实施基线：d468e0ac3e33a37efd53f03328f16dcbc42cff09。
- 只读 salvage：23d4827557b532f4eee4fe5511c458ed2b5d8e15，tree c179a9ba297f10d42aa1f534679c7d935836e213。
- 第一版候选：8721b1b34f9ee311600531c82d97ac174e41b9f5，tree 44cbb9cd623c35bf315c7bd101cfeeabccc3c0d6；六轴 verdict 为 FAIL，只保留为审查输入。
- salvage 不是实施基线、合并目标或既定路线。禁止整体 cherry-pick。第 15 节只允许按冻结条款人工提取单个测试或纯算法思想。
- 产品权威依次为：当前 Spec、CONTEXT.md、ADR 0022、已 resolved 的 Ticket 110—114、本文、Ticket 115 的 A1—A8。测试证明合同，不能创造新的产品目标或替代设计。

本文冻结的是 Ticket 115 的 HOW。上位合同若出现真实冲突，必须停在设计阶段交给主人；不得在编码时自行裁决。

## 2. 目标、非目标与交付边界

本票交付五项能力：

1. health-core 独占的任务建立、查重、控制、claim、推进、验收和终态；
2. 按主人当前有效时区运行的当地自然日复盘，只恢复当前日，不补旧日；
3. task、review、delivery、mandatory 四聚合与 outbox intent 的同一权威提交；
4. 事务外、分层、可恢复且 unknown 冻结的主人 Weixin 投递；
5. task、review、delivery 能力事实进入 Ticket 114 三态投影，状态变化和必要主人决定形成去重请求。

本票不做：

- Ticket 116 的诊断安全门和支持联系人警报；
- Ticket 117 的永久删除、防复活、跨安装迁移和密钥销毁；
- Ticket 118/119 的真实 Hermes socket、真实 Weixin、真实模型、部署、canary 和主人上线验收；
- 修改 Ticket 110 ExecutionLease 的五字段、current-head 接口或 writer-fence 语义；
- 建立第二套 task、review、outbox、status、mandatory 或 claim 真相；
- 引入 owner generation、ticket115_contracts.py、Case registry 或 salvage 的平行状态。

本票验收只证明本地合成 Plugin/core 与 fake transport。真实宿主和渠道仍必须明确报告为未验证。

## 3. 全局不变量

I1. health-core 是唯一业务裁决者和受管状态写入者。Skill、模型、Plugin、Adapter、渠道 observer 和测试替身不能直接提交任务、状态、outbox 或投递高层事实。

I2. 稳定归属只有 owner_id + installation_id。current-head generation 只用于一次 CAS；task version、approval version、route generation、configuration generation、consent generation 和 disclosure version 各自只在命名域内生效。

I3. 任务主标签只有 active、solved、failed、cancelled。phase、等待、延期、claim、能力缺口和外部结果 unknown 是独立事实。

I4. 候选不等于事实。候选中的 source、scope、revision、approval、result、task_id 和权限声明都不能直接成为权威；core 必须从当前受管对象重新构造。

I5. TaskClaimLease 只解决任务工作互斥，不授予业务权限。外部效果仍必须使用 Ticket 110 ExecutionLease。

I6. Ticket115PreparedMutationV2 始终只有四个聚合：TaskRuntimeState、DailyReviewLedger、DeliveryOutboxState、MandatoryRequestState。HealthCommandReceipt 是同事务附属回执，不是第五聚合。

I7. 四聚合与 outbox intent 只在 prepared → current-head CAS → local finalize 完成后同时可见。finalize 前不得产生 DispatchPlan，不得调用 Adapter。

I8. dispatch-armed 是外部效果不可逆边界。它只表示“可能已经离站”，不证明 Adapter 已调用，因此不能自动产生 attempted。

I9. attempted 只由绑定本次 execution 的严格 Adapter completion，或注册渠道对该 execution 的权威 readback 证明。interface-accepted、delivered、read、actual-action 分别需要各自证明。

I10. dispatch-armed 后若无精确 completion/readback，效果进入 may-have-left + unknown，自动重试冻结。主人接受重复风险只建立新效果 E1，不能解冻 E0。

I11. business_status 保留 Ticket 114 行为：计算当前投影，并原子记住上一投影，使同一状态变化在并发和重启后只返回一次。它不依赖 delivery route 或 mandatory 是否可投影。

I12. 状态 domain 表示核心能力是否可证明，不表示单个业务对象的结果。单个 task failed、今天尚未复盘或单次 delivery unknown 不能直接把对应核心能力判 fault。

I13. 兼容只解释 d468e0a 已认证的精确旧 wire。无法证明的旧字段只能进入明确的 historical/non-authoritative 变体，不能猜测、提升或触发新效果。

I14. 兼容归档只供审计和前向迁移，不参与业务授权，也不是回滚真相。

## 4. 权限与受信入口

### 4.1 命令入口拆分

health_commands.py 把现有 TrustedHealthCommand 拆为两个不同对象。

UnsignedHealthRequest 是可序列化请求，精确字段只有 action、causal_id、payload、request_digest。它不携带 source、scope、holder_role、owner、installation、runtime_epoch、generation 或权限结论。

CoreCommandCapability 是不可序列化、不可日志化、不可从 wire 重建的进程内对象，固定绑定：

- capability_id；
- owner_id、installation_id；
- runtime_epoch；
- peer_role；
- allowed_actions；
- admitted_source_binding_digest；
- bootstrap_session_id。

capability 只能由 core/plugin 的受信 bootstrap 创建；Plugin 初始化时取得最小 allowed_actions。core 的唯一入口为 execute_health_request(request, capability)。source、scope、owner/install、holder role 和允许动作全部从 capability 与当前受管状态推导，request 中同名字段一律拒绝。

Ticket 115 只实现本地进程 capability。Ticket 118 的 socket/client 必须以已认证 session 替换本地 capability，不能把 peer_id = plugin 字符串当权限。

### 4.2 任务 claim 权限

TaskClaimLease 持久字段固定为：

- claim_id、task_id；
- owner_id、installation_id；
- runtime_epoch；
- holder_role；
- holder_binding_digest；
- allowed_task_actions；
- acquired_at_monotonic_seconds、expires_at_monotonic_seconds；
- task_revision、task_cas_identity、head_generation。

claim 成功时 core 返回不可序列化 TaskClaimCapability，绑定同一 claim_id、holder_binding_digest、runtime_epoch、owner/install/task 和 allowed_task_actions。所有 worker transition 必须同时提交 claim_id 与精确 capability；仅有 holder_role 或 holder_id 不构成证明。

同一 runtime_epoch 内才比较单调时间。core 启动生成新 epoch；旧 epoch claim 立即失效。每个任务至多一个 current claim。

### 4.3 候选的三个准入源

TaskCandidate 只能从以下三条路径进入 core：

| source kind | 必需证明 | 禁止替代 |
|---|---|---|
| owner-goal | 唯一准入主人事件回执 + 同一事件的 health-steward 权威结果 | 普通 Adapter 文本、模型自报主人意图 |
| portrait-evidence | Ticket 112 已 finalized 的职责结果 + 精确 SkillUseProof + 当前 portrait/evidence revision | 模型草稿、旧 revision |
| task-event | core 内部已提交的 task/result/status transition | Plugin 或 wire 自报 task event |

Plugin 只运输 UnsignedHealthRequest。模型和职责 Skill 只能产生 TaskCandidate 草案；core 重新解析上述证明后才构造进程内 AdmittedTaskCandidate。

### 4.4 渠道回执权限

delivery.observe(kind, evidence_ref) 旧入口删除，不作为 v2 权限。

ChannelReceiptObservation 固定字段：

- producer_id、producer_contract_version；
- channel_id、route_id；
- owner_id、installation_id；
- effect_id、intent_id、execution_id、attempt_ref、idempotency_key；
- kind：interface-accepted、interface-rejected、interface-unknown、delivered、read；
- provider_receipt_id；
- observation_digest；
- replay_identity；
- observed_at_utc；
- signature_or_attestation。

core 只接受注册 ChannelReceiptAuthority 验证成功且 owner/install、route、effect/execution/attempt 全部匹配的 observation。Adapter completion 最多证明 attempted 与 interface result；只有注册渠道 authority 可证明 delivered/read。actual-action 不由渠道回执证明。

本地合成测试使用固定 producer manifest 和测试密钥；生产 producer 注册属于 Ticket 118。

### 4.5 主人决定与主人行动

OwnerDecisionFact 只能由 core 从准入主人事件形成，字段固定为：

- decision_id = H(admitted_event_id, admitted_event_digest, request_id, causal_state_id, disclosure_version)；
- owner_id、installation_id；
- request_id、causal_state_id；
- disclosure_receipt_id、disclosure_version、disclosure_digest；
- disposition：affirmative、decline；
- admitted_event_id、admitted_event_digest；
- decided_at_utc、recorded_transition_id。

主人事件必须明确 in-reply-to 同一 request，且披露回执先于事件。任意普通文本不能冒充决定。

OwnerActionFact 是另一对象，绑定 admitted_event、task_id、expected_result_kind、result_ref、current task/result revision。它只证明 owner-action-admitted；不能由 OwnerDecisionFact、read 回执或模型解释代替。

## 5. 模块与依赖

| Module | 唯一职责 | 禁止承担 |
|---|---|---|
| tasks.py | TaskContract、候选/来源值、TaskRuntimeState、control、claim、task 纯转换、legacy task history | current-head、route、外部调用、status |
| review.py | EffectiveTimezoneBinding、LocalDayKey、pending/record/tombstone/ledger、复盘纯决策 | 定时器、发送、设置写入 |
| delivery.py | OutboxIntent、attempt、分层 facts、unknown、receipt observation 的纯转换 | Adapter 调用、ExecutionLease 实现、SQLite、status |
| status.py | Ticket 114 sealed capability facts；MandatoryRequest/State/Policy | 执行 delivery effect、第二状态投影 |
| storage.py | 版本化 decoder、完整性 manifest、四聚合 prepare/finalize、execution journal、status transition log、compat archive | 业务取舍 |
| core.py | 唯一跨域协调、当前性检查、CAS、恢复、两操作投递接口、主动 status refresh | 网络发送、Weixin 凭据、第二持久模型 |
| plugin.py | 持有最小 capability；把一个 DispatchPlan 立即交给 Adapter 一次；回交 completion | SQLite、当前性判断、重试、高层事实 |
| health_commands.py | UnsignedHealthRequest、HealthCommandReceipt、进程内 capability | 业务状态机 |
| tasking.py | task-only 兼容 facade | re-export delivery/status/mandatory |

禁止新增 partner_health_steward/ticket115_contracts.py。跨域编排只在 core.py；值对象回到所属深模块。domain 模块不反向 import core、plugin 或 storage。

## 6. CP0 必须先固定的共享形状

在任何行为实现前，以下形状和严格 codec 必须同时存在：

1. tasks.py：TaskContract、TaskCandidate、AdmittedTaskCandidate、TaskSourceBinding、TaskControlFact 及 payload、TaskClaimLease、legacy task history；
2. review.py：EffectiveTimezoneBinding、ReviewCompletionTombstone；
3. delivery.py：OutboxIntentV2、OutboxAttempt、DeliveryFactV2、DeliveryOutboxStateV2；
4. status.py：MandatoryRequest、MandatoryProjection、MandatoryRequestRecord、空 MandatoryRequestState；
5. storage.py：Ticket115PreparedMutationV2、CompatibilityFact、LegacyDecoderResult、OwnerDeliveryExecutionJournal；
6. health_commands.py：UnsignedHealthRequest、CoreCommandCapability、TaskClaimCapability、ChannelReceiptCapability 的本地构造边界。

CP0 只落定值、严格序列化、升级门和空状态，不实现完整 task/review/delivery/status 行为。之后 CP1—CP4 只能消费这些形状，不能再改字段；若字段必须改，立即回到 design amendment。

Ticket115PreparedMutationV2 的四个 base digest、四个 next aggregate 和总 state digest 都在 CP0 固定。任何临时第五聚合或 checkpoint 私有 schema 都禁止。

## 7. 任务状态机

### 7.1 TaskContract 与候选

TaskContract 固定字段：

- purpose；
- expected_result_kind；
- expected_result_description；
- assignee_role；
- allowed_data_categories、allowed_data_refs；
- recipient_refs、effect_kinds；
- max_attempts；
- minimum_contact_interval_seconds；
- required_owner_actions；
- max_owner_contacts；
- acceptance_criteria。

contract_digest 覆盖以上全部字段。requested_scope_digest 等于 contract_digest，由 core 计算，调用者不得输入。

TaskCandidate 草案字段固定为：

- candidate_id；
- purpose、expected_result_kind、expected_result_description；
- assignee_role；
- allowed_data_categories、allowed_data_refs；
- recipient_refs、effect_kinds；
- max_attempts、minimum_contact_interval_seconds；
- required_owner_actions、max_owner_contacts；
- acceptance_criteria；
- goal_anchor_hint；
- related_task_hint 可选。

草案不含 task_id、owner/install、source authority、goal_key、approval、phase、label、result 或 dedupe verdict。

AdmittedTaskCandidate 由 core 构造并增加 owner/install、verified goal_anchor_ref、goal_key、TaskContract/contract_digest、current TaskSourceBinding、verified_related_task_id 可选和 admission_transition_id。

goal_key = H(task-goal-v1, owner_id, installation_id, goal_anchor_ref)。

TaskSourceBinding 固定字段：

- kind：owner-goal、portrait-evidence、task-event；
- source_ref；
- source_revision_digest；
- goal_anchor_ref；
- authority_transition_id；
- skill_use_proof_ref 可选，仅 portrait-evidence 必需。

CandidateReceipt 字段固定为 candidate_id、candidate_digest、disposition、task_id 可选、goal_key、contract_digest、recorded_transition_id。disposition 只有 created、merged、not-established、linked-narrowed、linked-substituted、linked-expanded、legacy-replayed。

### 7.2 合同关系与查重

两个合同的关系只按字段比较：

- equal：contract_digest 相同；
- narrowed：purpose、result kind/description、assignee、acceptance 全同；data/recipient/effect/required action 为子集；max attempts、max contacts 不增；minimum interval 不减；
- expanded：上述语义字段全同，且至少一个资料、接收方、效果、主人动作、次数或频率权限扩大，没有语义替换；
- substituted：purpose、result kind/description、assignee、acceptance 任一变化，或同时存在收窄和扩大。

core 的固定准入顺序：

1. candidate_id 已有 receipt：digest 相同返回原 receipt；不同拒绝。
2. 重新读取全部 source 当前 revision、owner/install、goal anchor 和 proof；不一致拒绝。
3. 在同一 goal_key 的 active v2 tasks 中查找 exact contract_digest。
4. 恰有一个 equal：合并新的 current source binding，disposition = merged。
5. 没有 equal 但存在 same-goal active task：必须有 current verified_related_task_id；缺失或不匹配则 not-established 并形成一次 clarification request。
6. 有 verified related task：按 narrowed/substituted/expanded 建立显式 linked task。narrowed 可复用覆盖它的当前批准；substituted/expanded 初始 waiting-approval。
7. terminal task 不原位重开；仍有目标时只建立 successor。
8. 同一 goal_key + contract_digest 至多一个 active v2 task。

任何非 equal 合同都不原位改写旧 task。related task 由当前权威来源绑定，Agent 不选择最近或最像的 task。

### 7.3 ManagedTask 与唯一任务聚合

TaskRuntimeState 是唯一任务聚合，固定包含 owner/install/version、v2 tasks、candidate_receipts、control_facts、current_claims、unknown_facts、legacy_task_history、legacy_candidate_receipts、legacy_dispositions。

legacy 集合是 non-authoritative history，不是 current task truth；第 12 节规定其 ceiling。

ManagedTask 固定包含：

- task_id、version、goal_key、goal_anchor_ref、contract、contract_digest；
- source_bindings；
- primary_label、phase；
- approval；
- control_projection；
- predecessor_task_ids、successor_task_ids；
- terminal_fact；
- created_at_utc、updated_at_utc。

TaskControlProjection 固定字段为 deferred_until_utc 可选、next_step_ref 可选、active_source_binding_digests、last_control_id 可选。

### 7.4 主人控制的 typed payload

TaskControlFact 公共字段固定为 control_id、task_id、kind、basis_ref、previous/resulting task version、previous/resulting projection digest、effective_at_utc、typed_payload。

| kind | payload | 唯一落点 |
|---|---|---|
| defer | resume_not_before_utc 可选、reason_code | control projection；phase → waiting-owner；清 claim |
| resume | resumed_from_control_id、next_step_ref 可选 | 清 deferred；批准 current 则 planned，否则 waiting-approval |
| ordinary-adjustment | previous_next_step_ref、next_step_ref、remove binding digests、add current bindings | 只改 next step/current source；合同不变 |
| scope-expansion | parent_task_id、child_task_id、relation = expanded、old/new contract digest | 原 task 不改合同；建立 linked child |
| owner-cancel | admitted_owner_event_id、reason_code | active → cancelled/closed；terminal 历史不改 |

ordinary-adjustment 若导致任一 TaskContract 字段变化，拒绝并走 linked task。source binding 只能换成 core 已重读的 current binding。

narrowed/substituted 的关联由新任务、双方 predecessor/successor 和 CandidateReceipt 共同记录，不伪装成原任务的 scope-expansion control；expanded 另外追加上述 control fact，证明主人批准边界为何扩大。

### 7.5 批准

TaskApprovalBinding 固定字段：

- status：not-required、waiting、bound、withdrawn；
- approval_request_id；
- requested_scope_digest；
- approval_id、approval_version、approval_revision_digest；
- bound_route_id、bound_configuration_generation、bound_consent_generation、bound_disclosure_version；
- expiry_utc 可选。

bound 只在 core 重新读取 Ticket 114 当前 ExecutionScopeApproval，并逐项匹配 owner/install、task/effect request、assignee、purpose、资料、接收方、effect kind、attempt/contact bounds、expiry 与 route/config/consent/disclosure 后成立。

撤回、过期或任一绑定域漂移使任务进入 waiting-approval 并清 claim；不自动 failed/cancelled。internal-only 合同为 not-required。

### 7.6 阶段与 claim 完整矩阵

active phase 只有 waiting-owner、waiting-approval、planned、in-progress、awaiting-result。terminal 映射固定为 solved/accepted，failed/closed，cancelled/closed。

| 当前 phase | trigger | 权限/事实 | 下一 phase/label | claim 处理 |
|---|---|---|---|---|
| new | establish internal/current-approved | admitted candidate | planned/active | 无 |
| new | establish needs owner | admitted candidate | waiting-owner/active | 无 |
| new | establish needs approval | admitted candidate | waiting-approval/active | 无 |
| planned 或 in-progress | claim | CoreCommandCapability + task CAS | phase 不变 | 建立/接管唯一 claim |
| planned | work.start | live TaskClaimCapability | in-progress/active | 同 CAS 刷新 claim revision/head |
| in-progress | work.progress | live TaskClaimCapability | in-progress/active | 同 CAS 刷新 claim |
| in-progress | work.await-result | live TaskClaimCapability + formed result/effect ref | awaiting-result/active | 清 claim |
| in-progress | worker.replan | live TaskClaimCapability + next_step | planned/active | 清 claim |
| awaiting-result | result.incomplete | current typed result | planned/active | 无 |
| 任一 active | owner.defer | current owner control | waiting-owner/active | 清 claim |
| waiting-owner | owner.resume | current owner control | planned 或 waiting-approval | 无 |
| 任一 external active | approval.withdraw/stale | current approval fact | waiting-approval/active | 清 claim |
| waiting-approval | approval.bind | current exact approval | planned 或 waiting-owner | 无 |
| 任一 active | owner.cancel | current owner control | closed/cancelled | 清 claim |
| 任一 active | acceptance.complete | current typed result + 全部 criteria | accepted/solved | 清 claim |
| 任一 active | deterministic.no-path | 第 7.8 节事实 | closed/failed | 清 claim |
| 任一 active | delivery.unknown | exact effect unknown | awaiting-result/active | 清 claim |

release、expiry 或旧 epoch 只清 claim，不自动改变 phase。非法矩阵边拒绝；不保留任意 advance_phase(to_phase) 公共接口。

### 7.7 typed 结果与 solved

TaskResultBinding 由 core 从当前业务事实构造，字段为 result_ref、kind、status、producer_id、producer_contract_version、producer_generation、revision_digest、transition_id、observed_at_utc。

kind 必须等于 task.contract.expected_result_kind。首发 resolver 固定为：

| kind | 允许 status | 唯一 producer |
|---|---|---|
| portrait-update | portrait-committed | Ticket 112 portrait authority |
| evidence-maintenance | evidence-assessment-committed | Ticket 112 evidence authority |
| owner-inquiry | owner-answer-admitted | 唯一准入主人事件 authority |
| literature-result | qualified-result、no-qualified-result | Ticket 113 governed knowledge result authority |
| reminder-delivery | delivered | 注册渠道 receipt authority |
| owner-action | owner-action-admitted | OwnerActionFact |

solve 必须同时满足 exact current task/contract、result kind、全部 criteria 当前证据、producer manifest、current source/evidence revision、无 unresolved unknown、当前控制和批准。accepted、formed、attempted、interface-accepted、read 或任意 owner 文本不能替代。

### 7.8 failed 的确定性规则

不存在 wire/task.fail 或调用者自签 TaskFailureProof。只有 core 在以下集合全部成立时形成 NoReasonablePathFact：

- task 仍 active 且目标仍 current；
- 当前批准范围内全部允许 producer path 都有 terminal capability fact；
- 没有 waiting owner、waiting approval、defer、live claim、pending result 或 unresolved unknown；
- 每条 path terminal fact 均由注册 producer 验证；
- fixed policy 计算 alternatives_remaining = 0。

NoReasonablePathFact 绑定 task version、contract digest、全部 terminal fact IDs、current evidence/settings digest 和 transition ID。只有它可触发 failed。

## 8. 当地日复盘

### 8.1 有效时区绑定

core 必须读取未经过 _project_current_owner_settings 清除 transition 的原始持久 OwnerSettingsState，再构造 EffectiveTimezoneBinding：

- owner_id、installation_id；
- raw_settings_version、raw_settings_digest；
- timezone；
- source_kind：current-setting 或 timezone-transition；
- source_transition_id 可选；
- transition_settings_version 可选；
- effective_at_utc 可选；
- first_review_local_date 可选；
- phase：current、pre-effective、effective；
- binding_digest。

算法固定：

1. raw timezone_transition 为 None：使用 raw timezone，phase = current。
2. transition 存在且 observed_at_utc < effective_at_utc：使用 previous_timezone，phase = pre-effective。
3. transition 存在且 observed_at_utc >= effective_at_utc：使用 new_timezone，phase = effective。
4. binding_digest 覆盖全部字段和完整 transition wire。

因此 Ticket 114 内存投影在激活后清除 transition，不会丢失 Ticket 115 的时区 revision；重启前后得到同一 binding。

### 8.2 key、state digest 与 ledger

LocalDayKey 固定为 owner_id、installation_id、EffectiveTimezoneBinding.timezone、local_date，不加 owner generation。

ReviewStateDigest 固定覆盖当前 TaskRuntimeState digest、portrait/evidence authoritative revision digest、raw OwnerSettingsState digest、independent control digest、notification/contact-window digest、EffectiveTimezoneBinding.binding_digest。

DailyReviewPending 绑定 LocalDayKey、ReviewStateDigest、action_refs、prepared_at_utc、pending_digest。

DailyReviewLedger 是唯一新复盘完成权威，包含 committed records、current pending 和 ReviewCompletionTombstone。每个 LocalDayKey 至多一个 committed record。

ReviewCompletionTombstone 只含 legacy_key_value、source_settings_version/digest、authority_ceiling = prevent-repeat-only、imported_at_transition_id。它只在 legacy_key_value 精确等于 LocalDayKey.value 时阻止重复，不生成 review result、时间、action 或 outbox。

d468 OwnerSettingsState.completed_review_keys 在首次 v2 normalization 时一次性导入 tombstone。此后该设置字段只作只读兼容投影，不再参与业务决定，也不写新 key。

### 8.3 固定复盘算法

Cron、startup、Plugin tick 只唤醒 core。core：

1. 构造 EffectiveTimezoneBinding 与 current LocalDayKey。
2. 若已有 committed record 或精确 tombstone，返回 already-complete。
3. 丢弃旧日 pending；当前日 pending 若 ReviewStateDigest 变化则重算。
4. 纯决策产生 quiet 或 action_refs。
5. quiet 仍提交 record，但无 outbox。
6. action review 在同一 Ticket115 mutation 中完成当前来源重读、task dedupe/merge、review record、mandatory 更新和按当前普通通知偏好形成 OutboxIntentV2。

不使用服务器日期、固定 24 小时或 missed-day replay。时区变更不补旧日、不改旧 key。

## 9. 四聚合提交与兼容 bootstrap

### 9.1 启动门

新二进制在开放任何 Plugin/core 公共操作前按固定顺序运行：

1. verify-existing：按现有密钥验证数据库、row integrity 和当前 manifest。
2. manifest classify：精确 v2 manifest 继续；精确 d468 manifest 只允许预声明的新表不存在或为空；其他 fingerprint、未知受管数据或 MAC 不符 fail closed。
3. schema bootstrap：一个 SQLite 事务创建空 v2 表并把 manifest 从精确 d468 fingerprint 升为精确 v2-bootstrap fingerprint；不改旧聚合，并保存可验证的 pre-bootstrap manifest digest。
4. legacy pending recovery：用冻结的 LegacyTicket115V1Codec、原 canonical wire、原 base/target/mutation digest 恢复唯一 ticket115_mutations_v1。
5. legacy auxiliary recovery：以 d468 原语只完成 local finalize、精确 readback、lease lookup/release 和已耐久 completion 的业务恢复；Adapter/model 调用次数为 0。
6. 只有证明不存在 unresolved v1 prepared、pending effect result、active/orphan owner-delivery ExecutionLease 或未分类 v1 marker，才进入 normalization barrier。
7. normalization barrier 用第 12 节 ceiling 一次构造完整四聚合：task 只含 v2 current task 与 typed legacy history；review 含精确保留 record/tombstone；delivery 含 v2 current outbox 与 typed legacy history；mandatory 从空状态开始且不倒造历史请求。
8. 以独立 Ticket115PreparedMutationV2 对四聚合做第一次 v2 CAS/finalize；同一 finalize 把 schema-generation 从 v1-compatible 改为 ticket115-v2。
9. 重新验证 v2 manifest、四聚合、current-head target 和无 pending journal 后才开放公共操作。normalization 失败时保持关闭，不得退回 v1 路径继续服务。

v1 prepared 真值表：

| 强读结果 | 动作 |
|---|---|
| 精确 transition/operation 已选中 | 用原 v1 codec 和原 target 只做 v1 finalize |
| head 仍是精确 base，transition 不存在 | 重放同一 v1 CAS，再只做 v1 finalize |
| 强读证明另一 transition 从同一 base 胜出，且本地 current v1 聚合仍等于 prepared base | 删除不可见 v1 prepare |
| terminal/fence/authority 漂移、读回未知、base/current 不一致 | 保留现场并 fail closed |

v1 recovery 后，normalization 是下一次独立 v2 CAS，不能重算或覆盖原 v1 target。schema bootstrap 只增加空结构；第 9.1 节第 8 步才是语义不可逆点。

### 9.2 Ticket115PreparedMutationV2

固定字段：

- prepared authority：base head、target head、transition_id、operation_digest；
- owner_id、installation_id；
- base_task_digest、base_review_digest、base_delivery_digest、base_mandatory_digest；
- next TaskRuntimeState、DailyReviewLedger、DeliveryOutboxState、MandatoryRequestState；
- next_state_digest；
- health_command_receipt 可选；
- compatibility_archive_entries 可选。

next_state_digest 只覆盖四聚合。receipt 与 archive 在同一 finalize 事务可见，但不改变聚合数量。

### 9.3 固定提交顺序

1. core 在唯一 write lane 读取 current head/fence、四聚合、raw settings、controls、approvals、route 和业务来源。
2. 纯计算完整 next 四聚合；不允许部分写。
3. storage 写加密 local prepared，外部读不可见。
4. core 对完整 target 做一次 current-head CAS。
5. CAS unknown 时按 transition_id + operation_digest 强读：精确选中只 finalize；head 仍为精确 base且 transition 不存在则重放；冲突、terminal、fence 漂移或无法强读则保留 pending并停止健康写、模型和效果。
6. local finalize 在一个 SQLite 事务中使四聚合、receipt、authority、compat archive 同时可见并清 pending。
7. finalize 后才允许下一个业务操作或 DispatchPlan。

current-head target 不含健康正文，只含既有不透明 installation/generation、revision digest、transition ID、fence、site 和 terminal 标记。

## 10. 投递状态机

### 10.1 effect、intent 与 attempt 身份

EffectId = H(owner_id, installation_id, causal_request_id, effect_ordinal)。首个 E0 ordinal = 0；unknown 后主人承担重复风险产生 E1，ordinal 由 OwnerDecisionFact 稳定派生；PONR 前 route 漂移仍是同一 effect_id，只替换 projection intent。

OutboxIntentV2 固定字段：

- intent_id、effect_id、effect_kind；
- owner_id、installation_id；
- causal_request_id、business_fact_ref、business_revision_digest、source_ref；
- recipient_ref；
- route_id、route_generation、configuration_generation、consent_generation、disclosure_version、disclosure_digest；
- payload_ref、payload_digest；
- max_attempts、minimum_attempt_interval_seconds；
- semantic_digest、idempotency_key、formed_at_utc。

intent_id 与 idempotency_key 覆盖完整字段。route/config/consent/disclosure 漂移产生新 intent；同一 intent 的已知安全 retry 使用同一 idempotency_key。

OutboxAttempt 固定字段：

- attempt_ordinal；
- attempt_ref = H(intent_id, attempt_ordinal)；
- status：reserved、execution-bound、dispatch-armed、known-terminal、unknown；
- execution_id 可选；
- reserved_at_utc；
- previous_terminal_attempt_ref 可选。

attempt_ref 只在 Ticket115 reserve CAS 分配一次，begin 不再次分配。只有上一 attempt 有权威 interface-rejected/not-left 证明且间隔/max attempts 允许时，才能 reserve 下一 ordinal。armed/unknown 不允许同 effect 自动新增 attempt。

### 10.2 事实层

DeliveryFactV2 层级为 formed、business-committed、reserved、dispatch-armed、may-have-left、attempted、interface-accepted/rejected/unknown、delivered、read、actual-action。

事实 append-only。dispatch-armed 与 may-have-left 不推出 attempted；accepted 不推出 delivered；delivered 不推出 read；read 不推出 actual-action。

每个 fact 绑定 fact_id、effect/intent/attempt/execution、producer、producer contract、evidence digest、occurred_at_utc 和 source transition。低层 producer 无法形成高层 fact。

### 10.3 Plugin 只见两个深操作

core 对 Plugin 只暴露：

- begin_owner_delivery(intent_id, CoreCommandCapability) → DispatchPlan；
- complete_owner_delivery(execution_id, OwnerDeliveryCompletion, completion_capability) → DeliveryExecutionResult。

旧 issue/prepare/execute 与 Plugin.claim_effect_execution 从 v2 路径移除，不保留第三个 public reserve。

begin 在同一 core write lane 内固定执行：

1. 恢复该 intent 已有 journal；存在未清 execution 则不开始新的。
2. 没有 current reserved attempt 时，通过 Ticket115 CAS reserve 下一 attempt_ref；finalize 后重读。
3. 重读 owner/install/head/fence、intent、证据、批准、独立控制、联系窗口、当地日、route/config/consent/disclosure、attempt bounds。
4. 写 journal lease-requested，保存可重建的 Ticket110 ExecutionLeaseRequest identity 和 acquisition operation digest。
5. core 内部调用现有 Ticket110 acquire/lookup seam；Plugin 不提供 grant。
6. 持久化精确 ExecutionLease 为 lease-bound。
7. 再次验证 lease authority 与 current intent；本地 journal 原子写 dispatch-armed。
8. 返回最小 DispatchPlan 与不可序列化 completion_capability。

execution_id = H(intent_id, attempt_ref, lease_id)。DispatchPlan 只含 recipient、payload、idempotency_key、execution_id 和 Adapter contract version。

Plugin 收到 plan 后不得排队、缓存、重试或二次调度；必须立即调用注入 Adapter 恰好一次，并立即回交 completion。Plugin 不生成 delivered/read/action。

### 10.4 completion 与 journal

OwnerDeliveryCompletion 固定字段：

- execution_id、intent_id、attempt_ref；
- adapter_contract_version；
- invocation_status：returned、raised；
- interface_status：accepted、rejected、unknown；
- provider_receipt_id 可选；
- result_digest、evidence_digest；
- completed_at_utc。

completion 必须匹配不可序列化 completion_capability。core 先把完整 completion wire/digest/producer/time 写 journal，再进行 lease release 或业务 CAS。

OwnerDeliveryExecutionJournal 每项固定保存 owner/install、effect/intent/digest/attempt/idempotency、ExecutionLeaseRequest identity、lease identity 可选、acquisition/release operation digest、head/fence、holder binding、execution_id 可选、phase、strict completion 可选、ArmedUnknownFact 可选。

phase 固定为 lease-requested、lease-bound、dispatch-armed、completion-pending、release-pending、released-awaiting-reconcile、cleared。

ArmedUnknownFact 固定为：

- unknown_id = H(effect_id, intent_id, attempt_ref, execution_id, dispatch-armed-journal-digest)；
- reason = completion-missing-after-dispatch-armed；
- may_have_left = true；
- armed_journal_digest；
- detected_at_utc。

它不含 attempted。

### 10.5 lease release 与恢复

active ExecutionLease 存在时禁止 Ticket115 current-head CAS。无论 completion 或 armed unknown，都必须：

1. journal 写 release-pending 与固定 release_operation_digest；
2. 调 Ticket110 release；
3. lookup_execution_lease 强读；
4. 只有 receipt 精确匹配 lease、released = true、released_operation_digest 相同，才进入 released-awaiting-reconcile；
5. 未证明时保留 journal并停止，禁止 CAS、清理或再调用 Adapter。

| 最后耐久点 | 恢复动作 | 恢复期 Adapter 调用 |
|---|---|---|
| prepare 前 | 无 | 0 |
| v2 prepare 后、CAS 前 | 第 9.3 节重放/强读 | 0 |
| CAS 已选中、finalize 前 | 只 finalize | 0 |
| business committed、reserve 前 | 可重新调度 | 0 |
| attempt reserved | 重读当前性后继续同 attempt | 0 或随后 1 |
| lease-requested | lookup；不存在则重取同 request，存在则绑定 | 0 |
| lease-bound | 未 armed，可 release 后重新 begin | 0 |
| dispatch-armed、无 completion | ArmedUnknownFact → release → CAS 写 may-have-left + unknown | 0 |
| Adapter 返回但 completion 未耐久 | 只有 provider readback 可证明；否则 armed unknown | 0 |
| completion-pending | release；随后 CAS 写 attempted/interface result | 0 |
| release-pending | 强读 release receipt | 0 |
| released-awaiting-reconcile | 重放同一 Ticket115 reconciliation CAS | 0 |
| 业务 finalize、journal 未清 | 幂等 clear | 0 |

dispatch-armed 无 completion 时真实历史调用可能为 0 或 1；表中 0 表示恢复不得再次调用。后续 provider readback 可追加证明，但不删除 unknown/may-have-left 历史。

### 10.6 unknown 与新效果

unknown-risk request 披露 E0 可能已离站及重复风险。只有 OwnerDecisionFact affirmative 才建立 E1：

- E1 effect_id、intent、payload、idempotency 由 decision_id 稳定派生；
- replay 同一 decision 返回同一 E1；
- E0 永远保持 unknown；
- decline 只关闭 request，不把 E0 改为 not-delivered。

## 11. 状态与 MandatoryRequest

### 11.1 主动 status refresh

storage 把 Ticket 114 remember_business_status 扩展为同一 SQLite 事务：写 current projection；三态真正变化时 append 唯一 StatusTransition；未变化不追加；返回 previous 与至多一个 transition。transition log 无 processed 标志，不是第二状态真相。

统一 refresh_status_and_reconcile：

1. 用 Ticket 114 StatusProjector 计算当前投影；
2. 原子 remember projection/transition；
3. 读取当前 causal facts 与未闭合 transition；
4. 纯派生 request create/supersede/resolve/projection；
5. 有变化时以一次 Ticket115 mutation 提交 mandatory 与 outbox；
6. 返回当前 BusinessStatusResult。

必须触发于 core startup 恢复后、每次 Plugin tick、current-head/fence/terminal 变化、每次 task/review/delivery/settings/control/approval/route mutation finalize、delivery recovery finalize、主人 business_status 查询。查询不是唯一触发点。

单个 outbox 事实不得把 delivery core capability 误判；若 reconciliation 暴露存储不一致，记录 capability fault并在下一轮 refresh 形成 transition，不递归发送。

### 11.2 capability producer

沿用 Ticket 114 CapabilityFactEnvelope/Authority/manifest：

- tasks core：聚合可解码、合同有效、writer/current-head 一致；
- daily-review core：ledger/tombstone 合同有效；今天未复盘不是 fault；
- delivery core：outbox、journal、Adapter capability 整体一致；单次 effect unknown 只形成 non-core isolated fact；
- current-head 非健康始终优先。

legacy ceiling 对象不能作为 active/recovered producer proof。

### 11.3 MandatoryRequest 形状

request kind 只有 status-change、authorization-request、unknown-risk-decision、capability-gap。

MandatoryRequest 固定字段为 request_id、owner/install、kind、causal_state_id、payload ref/digest、required_owner_action 可选、disclosure version/digest、created transition/time。

request_id = H(owner_id, installation_id, kind, causal_state_id)。causal_state_id 固定为：

- status-change：StatusTransition.transition_id；
- authorization-request：task_id + requested_scope_digest；
- unknown-risk-decision：unknown_id + E0；
- capability-gap：gap/terminal capability fact id + affected task/capability。

MandatoryProjection 固定为 projection_id、intent_id、route/config/consent/disclosure binding、status、formed_transition_id。status 只有 active、retired-pre-ponr、armed、known-terminal、unknown。

MandatoryRequestRecord 固定为 request、lifecycle、projection_history、resolution_fact_ref 可选、superseded_by 可选。lifecycle 只有 pending-route、projected、frozen-unknown、resolved、superseded。

MandatoryRequestState 是 obligation/dedupe 唯一真相；不得新增 MandatoryDeliveryLedger。

### 11.4 当前因果复核

投影前重读：

- authorization：task 已批准、取消、terminal 或 scope 变化则 resolved/superseded；
- unknown-risk：provider readback 已解决 E0 则 superseded；
- capability-gap：能力恢复或安装 terminal 则 superseded；
- status-change：未 PONR 且更新 transition 使旧通知不再代表当前状态，则旧 request superseded-by 最新 transition；
- owner/install/terminal/consent 不再允许时不投影。

普通通知 disabled 和 proactive support paused 不抑制 mandatory；terminal deletion、owner/install 不匹配、非 private entry、缺 consent 或 route 不当前仍是硬门。

### 11.5 route 漂移与生命周期

同一 request 可有多个历史 intent，但同时至多一个 active projection。

1. route/config/consent/disclosure 不可用：pending-route，不构造 recipient/intent。
2. route 可用：同一 Ticket115 mutation 形成 intent并记 projected。
3. active intent 在 dispatch-armed 前变 stale：标 retired-pre-ponr，request 回 pending-route；当前 route 下同 request/effect 形成新 intent。
4. 已 armed 且 outcome unknown：禁止替换，request = frozen-unknown；另建 unknown-risk request。
5. 有权威 interface-rejected/not-left：projection = known-terminal，可按当前 route 重投影同一 request，仍受 bounds。
6. status-change 在 interface-accepted 或更高层证明后 resolved。
7. authorization、unknown-risk、capability-gap 只有精确 OwnerDecisionFact 或 verified resolution fact 才 resolved；投递成功不等于主人决定。

request dedupe 按 request_id；intent dedupe 按完整 route/config/consent/disclosure/payload；attempt dedupe 按 intent_id + ordinal。

## 12. d468e0a 兼容升级

### 12.1 decoder result 与 authority ceiling

storage.py 只有一个版本化 decoder seam。认证后返回 LegacyDecoderResult：classification、original canonical wire/digest、normalized 或 historical value、CompatibilityFact、authority_ceiling。

CompatibilityFact 固定为 compat_id、object kind/ref、source schema/digest、decoder contract、classification、authority ceiling、normalized digest 可选。

| old object | v2 representation | ceiling | core 可做 | core 禁止 |
|---|---|---|---|---|
| active/terminal ManagedTask v1 | LegacyTaskRecord exact wire | historical-visible-only | managed read、owner cancel disposition、link successor | claim、advance、solve、批准、外发、status proof |
| candidate receipt triple | LegacyCandidateReceipt exact triple | exact-replay-only | 同 id+digest 返回原 task_id | 推断新 goal/contract |
| TaskLease v1 | LegacyClaimRecord | audit-only | 显示已失效 | current claim、holder 权限 |
| approval v1 | LegacyApprovalRecord | historical-only | 显示原 status/id/version | current scope authorization |
| review committed v1 | 精确现有 record | retain-exact-layer | 阻止同 key 重复 | 补造 action/result |
| settings completed key | ReviewCompletionTombstone | prevent-repeat-only | 精确 key 阻止重复 | 伪造 record/time |
| delivery formed/submitted | LegacyDeliveryHistory | historical-visible-only | 显示旧层 | 发送/任务结果 |
| delivery attempted v1 | history + may-have-left | frozen-effect | unknown 历史、风险链 | 证明 attempted、自动重试 |
| accepted/delivered/read v1 无 attestation | LegacyDeliveryHistory | historical-unverified | 审计显示 | v2 高层 fact/solve/status |
| old unknown | LegacyDeliveryHistory | frozen-effect | 保持 frozen | 改写 not-delivered |
| old business status projection | business_status_v1 | retain-current-projection | Ticket114 起点 | 倒造 transition |

candidate admission、claim、result resolver、mandatory policy、delivery sendability、capability producer 每个消费点都检查 ceiling。compat archive 永不作为授权输入。

### 12.2 task 逐字段处理

d468 ManagedTask 不转换为 v2 ManagedTask。LegacyTaskRecord 原样保存旧全部字段、original digest 和 CompatibilityFact。

缺失的 goal_anchor_ref、goal_key、expected_result_kind、authority_transition_id、requested_scope_digest、approval revision 保持 absent，不生成摘要。

继续目标只能由当前准入源重新形成 candidate，建立完整 v2 task，并显式 predecessor 指向 legacy task_id。legacy task 不恢复 authority。

旧 receipt (candidate_id, digest, task_id) 精确保留：同 pair 返回原 task_id/legacy-replayed；同 ID 不同 digest 拒绝；不得创建 v2 task。

旧 terminal 不丢失；旧 active 在 managed view 标 compatibility-limited，不能宣称可执行。主人 cancel 只追加 LegacyTaskDispositionFact，不改原 wire。

### 12.3 review、delivery、status

- review v1 合法 record 保留；旧 pending 只按当前日算法处理。
- settings.completed_review_keys 只导入 tombstone，原字段只读。
- delivery v1 attempted 全部降为 may-have-left；无注册 attestation 的高层事实 historical-unverified。
- old DeliveryLease 归档，不进入 current claim。
- old unknown 永久 frozen；继续只走新 E1。
- business_status_v1 projection 保留；不倒造历史 transition。
- mandatory 只从升级后当前 causal facts 派生，不按时间/task version 补历史催促。

### 12.4 首次 v2 写与回滚

第一次 v2 normalization mutation finalize 是不可逆边界。此前若要回退，必须由新二进制验证空 v2 表并原子恢复 pre-bootstrap manifest，再交给 d468；不能让 d468 直接打开 v2-bootstrap manifest。不可逆边界之后：

- storage 写 durable schema-generation = ticket115-v2；
- d468 二进制必须 fail closed 为 offline/cannot-confirm；
- 之后只能由理解 semantic manifest/current generation/writer fence 的前向版本恢复；
- compat archive 不是 rollback authority；
- 恢复旧业务 wire 必须由新版本走新的 current-head CAS，不能直接覆盖 SQLite。

部署备份、二进制切换和生产 rollback 演练属于 Ticket 118；删除、跨 installation 迁移和密钥销毁属于 Ticket 117。

## 13. 固定实施检查点

每个 checkpoint 必须先红测、最小实现、定向和累积回归、独立 commit。不得并行修改同一权威聚合。

### CP0：共享形状、受信入口与升级门

只实现第 6 节值/codec、capability bootstrap、manifest、v1 exact recovery gate、空四聚合、PreparedMutationV2。

证明 populated d468 store、tamper fail closed、v1 CAS 崩溃恢复、未解 v1 lease/effect 阻止 v2、四聚合可见性、request/capability 分离、d468 binary 对 v2 fail closed。不得发送。

### CP1：任务、权限与 legacy task

实现三条准入、goal/contract relation、related task 不猜、typed control、phase matrix、TaskClaimCapability、exact approval、typed result/no-path、legacy replay/successor。

停止条件：第二 claim truth、caller 自签、legacy task 获得 current authority。

### CP2：当地日与四聚合提交

实现 raw settings timezone binding、DST/跨日/切换、tombstone、同日并发、quiet/current-day/no-backlog、全部 prepare/CAS/finalize 崩溃点、四聚合可见、finalize 前无 plan。

停止条件：owner generation、服务器日期、第五聚合、未来类型依赖。

### CP3：投递、渠道权限与 unknown

实现唯一 attempt allocation、begin 内部 reserve→reread→lease→arm、ExecutionLease 不变、全部 journal/recovery、release 未证明无 CAS、Adapter 至多一次、层级权限、删除 raw observe authority、E0/E1。

停止条件：第三 reserve 接口、unknown 自动重试、Adapter 写高层事实、真实 Weixin/凭据。

### CP4：主动状态与 mandatory

实现 transition log、全部主动触发、capability/单项结果分离、四 request identity、causal supersede、route pending/reproject/unknown、硬门、decision/action 分离。

停止条件：business_status 依赖 route、missing-today=fault、task failed=core fault、第二 mandatory ledger。

### CP5：最终集成

只修 fidelity 缺口，不接受新架构。运行 Ticket 110—115 targeted、全量、compileall、diff check，核对未跟踪文件、环境和 commit/tree。

## 14. 验收追踪与测试

| Acceptance | 设计条款 | 首次证明 |
|---|---|---|
| A1 | §4、§7、§12.2 | CP1 |
| A2 | §7.7—§7.8 | CP1 |
| A3 | §8、§12.3 | CP2 |
| A4 | §9 | CP0 + CP2 |
| A5 | §10.1—§10.4 | CP3 |
| A6 | §4.2、§7.6、§10.3—§10.5 | CP1 + CP3 |
| A7 | §11.1—§11.2 | CP4 |
| A8 | §4.5、§11.3—§11.5 | CP4 |

不固定 Case 数量。每条不变量、合法/非法边、权限边界、compat ceiling 和崩溃表行至少一个可独立失败的行为测试。schema 构造测试不冒充端到端行为。

测试文件按职责：

- test_ticket115_upgrade.py；
- test_ticket115_tasks.py；
- test_ticket115_review.py；
- test_ticket115_storage.py；
- test_ticket115_delivery.py；
- test_ticket115_health_commands.py；
- test_ticket115_plugin_delivery.py；
- test_ticket115_status.py；
- test_ticket115_integration.py。

上游 sentinel 至少包括 Ticket110 prepare/CAS/finalize 与 ExecutionLease schema/readback/release、Ticket112 候选无写权/唯一提交/SkillUseProof、Ticket114 stale approval/route/config/disclosure/TimezoneTransition/status、test_114_a5_c21_status_transition_is_deduplicated_across_restart。

最终命令：

- python -m unittest discover -v -s tests -p "test_ticket115_*.py"
- python -m unittest discover -v -s tests -p "test_ticket11[0-4]*.py"
- python -m unittest discover -v
- python -m compileall -q partner_health_steward tests
- git diff --check

## 15. salvage 使用规则

禁止 cherry-pick da4d43c、7bb5017、46c26fc、8ceb964 或 23d4827。

单项人工移植必须：在 d468 稳定复现本文违反；不依赖 contracts/registry/第二 claim/owner generation/WIP API；字段完全一致并在指定模块重写；不携带平行状态/权限。证据记录 source commit/path、条款、原因、目标 path。

## 16. 冻结、偏差与 amendment

冻结记录必须包含 frozen content commit/tree、implementation base、六轴最终 verdict、第一版 findings 关闭记录、主人确认。只有写入 Ticket 后才改 ready-for-agent。

编码 Agent 只能按 CP0→CP5 实施、写要求测试、修 fidelity、记录证据。不得改本文、票的技术路线、状态机、schema、模块职责或验收解释。实现 reviewer 只查 fidelity、回归和证据真实性。

只有可复现的新事实证明路线不可实现、不安全或破坏 d468 兼容才可 amendment：

1. 停工保存干净 checkpoint；
2. Ticket 退 needs-info；
3. 新 design content commit/tree；
4. 标出受影响轴；
5. 重审全部受影响轴和必选跨轴一致性；
6. 主人再次确认；
7. 从最早受影响 checkpoint 起，全部下游测试/review/fidelity 失效并重跑。

风格、可选重构、另一可行偏好和不影响合同的 P2/P3 进后继 backlog，不触发 amendment。最终 fidelity 后任何产品代码、测试、schema、配置变化都使 verdict 失效；只允许 Ticket/Map 元数据关票。

## 17. 第一版 findings 关闭索引

| Finding | 第二版位置 |
|---|---|
| legacy task/receipt 缺字段 | §12.1—§12.2 |
| candidate/scope relation | §7.1—§7.2 |
| phase/claim/terminal | §7.6—§7.8 |
| result kind/producer | §7.7 |
| timezone revision | §8.1—§8.2 |
| attempt 两次分配 | §10.1、§10.3 |
| lease 阻塞 unknown CAS | §10.4—§10.5 |
| journal 数据不足 | §10.4 |
| caller 自报权限 | §4.1 |
| claim 无 holder proof | §4.2 |
| candidate 绕过 Ticket112 | §4.3 |
| receipt trust root | §4.4 |
| owner decision/action | §4.5 |
| checkpoint 循环 | §6、§13 |
| begin/reserve 第三 seam | §10.3 |
| v1 pending recovery | §9.1 |
| completed review 第二真相 | §8.2、§12.3 |
| 主动 status 缺失 | §11.1 |
| projected route 漂移 | §11.4—§11.5 |
| manifest/rollback | §9.1、§12.4 |
| ceiling 不执行 | §12.1 |
| amendment 失效规则 | §16 |

## 18. 明确拒绝的路线

- 从 salvage 继续修补；
- 先大面积实现再开放式重审；
- 固定测试数量或全局 Case registry；
- owner generation、ticket115_contracts.py、dual claim；
- peer_id 字符串或 caller wire 自报权限；
- Caller/Skill/模型自签 source/fail/approval/delivery proof；
- 猜测升级 d468 task authority；
- codec-only compatibility；
- MandatoryDeliveryLedger；
- business_status 依赖 issuer/route；
- Plugin 第三个 reserve/prepare seam；
- Adapter 调用前写 attempted；
- unknown 自动重试；
- 任意 owner 回复当决定/action；
- 单个 task failed、delivery unknown 或今天未复盘直接判核心 fault。
