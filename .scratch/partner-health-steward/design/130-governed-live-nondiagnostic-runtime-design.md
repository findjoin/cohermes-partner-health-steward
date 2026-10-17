# Ticket130 唯一增量设计候选：受控自然语言日常 Runtime

状态：pre-code candidate，未冻结、未实现。设计作者deployment_audit，独立verification authority为implementation_audit；仅本文件承接130。前置124/125/131已闭票；126真实投递仍在执行验证，不能把其候选产品或本设计称为主人验收完成。医学审查/full诊断仍归127，实际网络/主人canary归128。

## 已验证边界与具体差额

131已通过真实隔离789全量及双轴实施后审查，只增加非诊断操作预算和原NonDiagnosticCandidate；预算为最终canonical wire 65536 bytes、输出2048 tokens，公开“不提供共同上下文保证”。这既不是完整NL抽取，也不是诊断许可。

当前DailySkillRuntime要求外部callable产生StewardPlan、EvidenceDecision、PortraitDecision和StewardResolution；已有synthetic executor不能作为生产实现。Plugin.receive_weixin会连续推进证据与完整日常阶段。Core._handle_effect_request/execute_strict_health_model只准evidence-finalized源，store.model_effect_for_source要求同一源只有一个model effect。现Core lifecycle lock跨adapter.execute、daily_turn_runtime_preparation跨yield执行executor；串行CorePort在该锁里反向等Plugin会互锁。125只承接exact已准request，不能在executor里暗用HTTP。

已有复用资产是同一admitted SourceReceipt、原effect/claim/executing.model_attempt_started/terminal journal、ModelTransportResult完整codec、StrictHealthLLM纯resolve、当前ND budget/strategy、NonDiagnosticReplyPipeline、DailySkillRuntime.complete的model_answer_resolution/model_reply_atoms以及原唯一prepare/commit/finalize。authority_for_digest只恢复route/profile/schema四元组，不能恢复measurement strategy；组合根必须给Core真实typed策略，不能拿digest冒充配置。原live接口尚无主人任务、暂停、停止记录和权利入口，单独提供证据executor不足以完成130。

## 唯一路线与两个固定阶段

每个真实自然语言源最多两个外部attempt：`intake`在证据提交前，只产生受限抽取；`answer`只在该源证据阶段已finalized后，产生原NonDiagnosticCandidate。record-only经真实intake后可只提交确定性记录回执，不强加第二次模型调用。question/mixed在有足够当前批准资料时走answer；clarify只用固定补问，不推断遗漏事实。两个阶段的purpose均为原`non-diagnostic-health`，共用同一个当前budget/route/owner decision/期限；不增加任意purpose或schema registry。

intake不能通过更换source/causal ID绕过旧单效果限制。只在原effect journal中加入固定stage关系：同一business_source_causal_id最多一个intake和一个answer；旧strict/131未标stage的单次回答保持旧wire及唯一性语义。typed EffectIntent/ExecutingEffect/TerminalEffect携带可规范重验的可选阶段标记，阶段纳入intent/request及报告绑定；旧序列化不凭空增加字段。存储内部如何索引可逆，不冻结新的表或第二ledger。answer永远不能用intake effect/grant/report完成，反向同样拒绝。

131同一budget/request/strategy实现只扩固定二元schema关系：原answer schema名称、实际schema与digest不变；新增`nondiagnostic-intake-v1`及其真实schema digest。strategy的`prepare_request(messages, *, stage="answer")`只允许intake/answer，旧无stage调用仍构造answer。StrictHealthLLM和125 Adapter按明确阶段/schema组合重验精确最终wire、固定预算和当期authority；诊断源操作仍拒绝ND profile。任何通用schema参数、升额、截断、自动分拆或retry都不进入生产。

## intake 的有限语义和后续真实七Skill

新增纯typed `NonDiagnosticIntakeCandidate`，schema根字段精确为`operation/facts/question`。operation固定`record/question/mixed/clarify`；facts最多8项，每项精确`start/end/quote/topic_ref/time_start/time_end`；question为null或精确`start/end/quote`。offset按Python Unicode code-point索引，Core从原admitted body重新切片验证quote完全相同、范围合法、非空且不交叉；模型不能给出改写、证据ID、draft/record/proof ID、诊断、药物建议或自由最终答复。topic_ref为null或现有PORTRAIT_TOPIC_REFS的45项；它只是归档建议，不是医学结论。

时间只从time_start/time_end指向的原文和原protocol timestamp/主人时区按固定可重算规则解析：明确ISO日期以及今天/昨天/昨晚/今早/今晚；不能可靠重算时固定unknown，不接受模型自由日期。原文未提供的次数、时长、原因、趋势、测量方法和可靠性都保持unknown。数值句在本票仅作主人陈述，不自动升级为verified measurement、BMI/full或clinical conclusion。

Core-owned的纯生产executor据已验证candidate生成StewardPlan和PersonalHealthFields(owner-statement)，证据内容为原文quote，source/purpose/uncertainty/limitations使用固定受限规则；问题句、请求诊断句和假设句不得自动变成主人事实，不能凭原文确切子串就升级其陈述属性；无法确认是事实时归question/clarify。不是将整条消息机械记账当作NL。模型负责有限抽取及record/question/mixed/clarify选择，Core负责逐字来源与能力边界。证据Skill仍实际执行、生成自己的use proof，并经旧Core校验提交。

PortraitDecision只允许从当前已提交或本轮Core验证证据精确生成：current_understandings为带“主人原文”标记的原quote或现有已提交理解，保留否定和限定；proof_links精确指向证据。禁止模型自由摘要、病因、趋势、诊断、severity或跨topic推论。clinical-and-safety主题只允许原文明确所述事项；不能把归档主题变成主人已患某病。不能确定归档时保留evidence并将topic设null/提出固定补问，不伪造画像覆盖率。StewardResolution只选择本轮已存在的证据/主题/原reply atom，七Skill实际执行和Core attestor继续是提交条件。

answer沿原NonDiagnosticCandidate/current owner-card与governed KnowledgeRelease/approved claims/templates路径；support/opposition等文本必须经原pipeline的批准atom验证。模型无权写数据库、批准、proof、draft、record IDs或free final reply；唯一owner_reply继续由已验证原子和approved template确定性渲染。

## 组合根与有限公开API候选

新增纯typed `GovernedNonDiagnosticRuntime(intake_llm, answer_llm, measurement_strategy, *, bundle, attestor, clock=None)`；两LLM必须为真实StrictHealthLLM，profile为相同concrete NonDiagnosticOperationalBudget，策略为同budget的真实NonDiagnosticBudgetInputMeasurementStrategy，bundle/attestor分别是同release实际DailySkillBundle/DailySkillAttestor。该类内部从Core已验证candidate构造纯executor和真实DailySkillRuntime，不能接受任意DailySkillRuntime.callback再改名为生产executor。构造重验两个schema、route和strategy，不接受可替换HTTP callback/任意executor作为生产批准。approved claims/templates、知识release和当前owner设置沿现Core依赖装配，不另建资源truth。

`LiveHealthRuntime(..., governed_nondiagnostic_runtime=None)`显式装配该纯运行时。Core不持模型凭据/HTTP adapter。Hermes Plugin进程装配`LiveNonDiagnosticModelBridge(core_port, adapter)`，adapter为已绑定同budget/strategy的真实ProductionModelAdapter；网络替身只能在125现有transport边界。公开`async advance_source(source_causal_id) -> dict`只驱动Core指定的下一固定阶段，不决定另起source或第三次调用。

Core必经公开短方法为：

- `prepare_nondiagnostic_stage(source_causal_id, stage) -> {stage, state, request, effect_intent}`；request为canonical StrictModelRequest wire或null，effect_intent为真实typed EffectIntent或null。intake必须原源仍held且无已完成intake；answer必须同源evidence-finalized且intake结果已被本Core验证并提交使用。重复、错阶段或当前批准失效返回无新intent。
- `start_nondiagnostic_stage(source_causal_id, stage, grant) -> {stage, state, request, attempt_ref}`；Core重验真实typed grant、当前head/fence/route/budget/schema与exact request，先持久原ExecutingEffect.model_attempt_started，再返回一次性attempt引用和request。它不执行网络，不持Core lock等待Plugin。
- `complete_nondiagnostic_stage(source_causal_id, stage, grant, attempt_ref, result: ModelTransportResult) -> {stage, state, reason_code}`；Core规范重验完整结果，自己调用StrictHealthLLM.resolve_transport_result生成report，绑定原grant/request/source/stage并经原effect.result终态/lease释放。不能接受Plugin提供ModelEffectReport、candidate digest或“成功”布尔值代替完整结果。
- `advance_governed_source(source_causal_id) -> {response, next_stage, model_use_disclosure}`；只用本Core已经观察的候选推进原typed日常阶段/唯一提交，返回原Response wire及intake/answer/null。最终response沿原turn_result，可交126受控投递，不直接网络send。
- `nondiagnostic_source_status(source_causal_id) -> {source_causal_id, next_stage, state, reason_code, model_use_disclosure}`；投影无健康正文/凭据，不能补造候选或report。

公开短方法返回state闭集为`ready/attempted/completed/failed-closed/unknown/owner-decision-required/finalized`，只是原source/effect/daily事实的投影，不新增持久状态机。attempt_ref来自原effect/lease的单次关联，不是第二个批准、重试令牌或跨服务私有session ledger。

## 同三kind的精确CorePort候选

interface沿`health-entry-v1`；未知op/field拒绝。command/controlled-effect仍`{interface,operation,payload}`，managed-read仍`{interface,projection,payload}`。同ProductionCoreService原_effect_sessions保存真正typed grant/capability；Plugin只接有界metadata。

| kind / op | payload | 返回payload |
|---|---|---|
|command `governed-receive`|`{message}`，同现RawWeixinMessage wire|`{response,next_stage,model_use_disclosure}`；只准入/纯计算，不HTTP|
|command `governed-advance`|`{source_causal_id}`|同advance_governed_source|
|controlled-effect `nondiagnostic-prepare`|`{source_causal_id,stage}`|`{stage,state,request,intent,grant}`；原service exact intent/grant metadata或null|
|controlled-effect `nondiagnostic-start`|`{source_causal_id,stage,grant}`|`{stage,state,request,attempt_ref}`|
|controlled-effect `nondiagnostic-complete`|`{source_causal_id,stage,grant,attempt_ref,result}`，result为现完整ModelTransportResult wire|`{stage,state,reason_code}`|
|managed-read `health-entry-nondiagnostic`|`{source_causal_id}`|同nondiagnostic_source_status|

生产live receive选择已配置的governed路径；旧typed同步receive/executor仍供原冻结兼容，不作为生产NL授权后门。Bridge流程为receive→prepare/claim→start持久attempt→离开Core调用125一次→complete完整terminal→advance；全程无Core/executor锁内网络、无反向RPC callback。Core已有prepared/evidence/finalized事实均由相同Plugin/Core完成，不用测试port自报业务成功。actual registry和Publisher发布包必须证明整条组合可达。

## 重放、失败与正文寿命

同原生事件重投只查同source及固定stage事实，不以换causal ID或第三stage重试。未开始时预算/route/profile/owner currentness失效是failed-closed/not-started；真正started后timeout/response-loss为unknown并冻结。已completed但候选仅存在于旧Core内存、重建后丢失时，沿旧unknown-owner-decision-required，无重调、无cursor，不能从digest恢复正文或相信Plugin缓存候选。

intake成功后只有本Core验证过的candidate可以驱动证据提交；可复用其已提交证据继续answer。已知failed/incomplete不写推测事实，可用原失败关闭atom形成明确限制提示，保留真实report和131说明。answer只有当前引用与批准链通过才产生正文。unknown/待主人决定不把“模型没抛异常”当完整上下文或业务完成；126投递仍需唯一提交及原ACK前handoff。

停止记录时，原source正文仅在现Core `_recording_excluded_sources` transient cache中，新intake前不得因一次receive返回就误清空，也不能补写SourceReceipt/WAL/临时文件。只由同source的原model effect/实际CorePort会话持有有界内存所有权，最长沿原执行lease的300秒、结束/failed-closed/unknown/取消/Plugin holder退出/Core关闭即释放；每条RPC正常EOF不是业务session断开。复用原_effect_sessions及OS对真实peer进程生命周期的识别，不新建 durable session/正文ledger。Service既有空闲循环可清理到期内存；过期后晚到的candidate也必须再查同source/currentness，不能恢复正文或写事实。重建只有body-free receipt/digest时停止，不能把Plugin缓存或模型回包当恢复权威。

## 有限真实主人入口候选

主人操作先经同唯一owner/private/account/native admission；Core由原source和current head派生OwnerCommandContext/OwnerMutationContext及TrustedHealthCommand的source/scope，绝不接受caller提供health_operation context、owner_id、permissions、generation或批准。模型任务建议只可作为建议，不能当owner approval。

本票支持固定可见命令及一一对应中文别名（`帮助/当前状态/暂停主动联系/恢复主动联系/停止记录/恢复记录/提醒我/取消提醒/查看资料/导出资料/纠正资料/删除资料`）；Core回复实际显示示例，不要求主人构造JSON：`/health-status`、`/health-pause`、`/health-resume`、`/health-recording-stop`、`/health-recording-resume`、`/health-task-once <主人当地明确时间> <提醒原文>`、`/health-task-cancel <task_id>`、`/health-view [topic]`、`/health-export [object_ref...]`、`/health-correct <object_ref> <更正原文>`、`/health-delete`及原独立delete confirm命令。暂停/恢复沿现OwnerControlCommand，停止记录沿现recording控制且不偷偷恢复；status无模型调用。

提醒时间按主人已设置时区解析当地日期时间，支持明确日期或今天/明天加时刻；缺日期/时刻、DST歧义或过时不猜，返回固定补问。`health-task-once`是主人明确请求的单次自有提醒：当前披露显示只向当前主人/当前Weixin route发送一次、固定目的/范围/期限和取消方式。Core从该原生显式命令生成现ExecutionScopeApproval与TaskCandidate，max_attempts=1、唯一当前接收方，不授权联系人或任意外部调用；自然语言intake本身不能生成该批准。重复native事件返回原task/approval，不新建第二任务。固定`command/governed-wake payload={}`由Core当前时钟推进现due任务并形成原outbox，返回`{delivery_refs,task_status}`；现调度/轮询实际调用它，126只投递Core返回的`owner-outbox`引用，不新建timer/后台队列或直接send。wake还按主人时区计算现LocalDayKey，实际接原DailyReviewEngine.prepare/commit以及现task claim/advance/solve；只处理当前due任务及当前当地日，复用completed review key/原outbox幂等，无补跑过期日、无模型第三阶段或新调度ledger。暂停/撤销/过期route或scope不投递，unknown维持原冻结。系统timer安装及运行target精确批准留128，但130必须交付可直接调用的真实当前wake。

`command/governed-owner-command payload={source_causal_id}`只解析该源实际原文和上述闭集，返回`{response,delivery_refs}`；不接自由action/payload/context。删除仍复用原lifecycle的独立新事件确认、当前target/operation绑定、purge/terminal/通知，普通“删掉”模型候选不能触发删除。资料查看、导出、纠正均是本票必需项：查看走managed_rights_read_current及原ManagedObject当前版本/撤销边界；纠正走managed_correction_draft→原PendingCorrectionDraft/OwnerMutationRequest与Ticket112完整原子链，引用实际admitted纠正source，replacement只来自主人明确更正原文/已验证有限抽取，受影响判断先降级，不写替代事实到另一个store。一般问答不能暗变成纠正；资料查看/导出不调用模型。

正式JSON导出走原managed_rights_export→ManagedExport.to_wire规范对象，保留snapshot/source_state/object版本/修订引用，不能让模型拼JSON或重新导入作为权威。Core生成导出工件时只使用现认证加密和原server-exports受管registry，删除/撤销清理范围必须包含该工件；路径/token不进入普通Session、模型或日志。原生导出命令至少真实生成该受管工件、返回精确artifact_ref与状态；受管read可按snapshot_ref与明确页范围读取原canonical JSON，不截断后冒称完整导出。当前126仅单次文本、无文件附件，因此主人拿到完整JSON工件的实际渠道必须在本候选冻结前明确：使用原受管工件读取入口，或另行固定并验证最小附件transport；不能把‘文件已生成’称为微信已交付，也不临时增加公共HTTP服务/共享链接。这是当前transport事实差额，待root在同一候选内定最小交付，不能以130闭票留待扩入。

## 主人可见限制与验收输入

组合根将131同一model_use_disclosure实际带入初始化显示和主人回复；record-only、failed-closed、known terminal和completed都不能移除“不提供共同上下文保证”。显示值取Core实际budget/报告，不接受Plugin自造较好说明；不把actual model/usage或配置240000写成保证。

候选有限outcome是：真实NL抽取且逐字来源/否定/时间边界；同源最多两stage的正确授权与跨进程单attempt；Core纯resolve和原七Skill唯一提交；unknown/候选丢失不重调不ACK；当前approved claims/templates与45topic边界；真实主人任务/控制/权利入口及模型非批准；published registry/socket/真实125 transport边界组合与131可见声明。由独立verifier按现实mutation收敛门，不按内部字段或SQL做笛卡尔积。唯一design/独立contract/tests同checkpoint fresh Spec/Standards通过前不实现、不闭票。
