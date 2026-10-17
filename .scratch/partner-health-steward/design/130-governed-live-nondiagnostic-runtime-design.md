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

新增纯typed `NonDiagnosticIntakeCandidate`，schema根字段精确为`operation/facts/question`。operation固定`record/question/mixed/clarify`；facts最多8项，每项精确`start/end/quote/topic_ref/time_start/time_end`；time_start/time_end为同一事实内原文时间片段的成对offset，未提供时两者均null；question为null或精确`start/end/quote`。record要求非空facts且question为null，question要求facts为空且question非null，mixed要求两者均非空，clarify只允许空facts及原question/null，矛盾组合拒绝。offset按Python Unicode code-point索引，Core从原admitted body重新切片验证quote完全相同、范围合法、非空且不交叉；fact span必须覆盖确定性分句的完整陈述（含否定/条件/时间限定），不能截取“没有失眠”中的“失眠”或从“是不是糖尿病”取疾病词作事实；疑问/祈使诊断语句只进入question/clarify。分句/疑问guard是来源防升级验证，不能代替模型intake并称NL抽取。模型不能给出改写、证据ID、draft/record/proof ID、诊断、药物建议或自由最终答复。topic_ref为null或现有PORTRAIT_TOPIC_REFS的45项；它只是归档建议，不是医学结论。

时间只从time_start/time_end指向的原文和原protocol timestamp/主人时区按固定可重算规则解析：明确ISO日期以及今天/昨天/昨晚/今早/今晚；不能可靠重算时固定unknown，不接受模型自由日期。原文未提供的次数、时长、原因、趋势、测量方法和可靠性都保持unknown。数值句在本票仅作主人陈述，不自动升级为verified measurement、BMI/full或clinical conclusion。

Core-owned的纯生产executor据已验证candidate生成StewardPlan和PersonalHealthFields(owner-statement)，证据内容为原文quote，source/purpose/uncertainty/limitations使用固定受限规则；问题句、请求诊断句和假设句不得自动变成主人事实，不能凭原文确切子串就升级其陈述属性；无法确认是事实时归question/clarify。不是将整条消息机械记账当作NL。模型负责有限抽取及record/question/mixed/clarify选择，Core负责逐字来源与能力边界。证据Skill仍实际执行、生成自己的use proof，并经旧Core校验提交。

PortraitDecision只允许从当前已提交或本轮Core验证证据精确生成：current_understandings为带“主人原文”标记的原quote或现有已提交理解，保留否定和限定；proof_links精确指向证据。禁止模型自由摘要、病因、趋势、诊断、severity或跨topic推论。clinical-and-safety主题只允许原文明确所述事项；不能把归档主题变成主人已患某病。不能确定归档时保留evidence并将topic设null/提出固定补问，不伪造画像覆盖率。StewardResolution只选择本轮已存在的证据/主题/原reply atom，七Skill实际执行和Core attestor继续是提交条件。

answer沿原NonDiagnosticCandidate/current owner-card与governed KnowledgeRelease/approved claims/templates路径；support/opposition等文本必须经原pipeline的批准atom验证。模型无权写数据库、批准、proof、draft、record IDs或free final reply；唯一owner_reply继续由已验证原子和approved template确定性渲染。

## 组合根与有限公开API候选

新增纯typed `GovernedNonDiagnosticRuntime(intake_llm, answer_llm, measurement_strategy, *, bundle, attestor, clock=None)`；两LLM必须为真实StrictHealthLLM，profile为相同concrete NonDiagnosticOperationalBudget，策略为同budget的真实NonDiagnosticBudgetInputMeasurementStrategy，bundle/attestor分别是同release实际DailySkillBundle/DailySkillAttestor。该类内部从Core已验证candidate构造纯executor和真实DailySkillRuntime，不能接受任意DailySkillRuntime.callback再改名为生产executor。构造重验两个schema、route和strategy，不接受可替换HTTP callback/任意executor作为生产批准。approved claims/templates、知识release和当前owner设置沿现Core依赖装配，不另建资源truth。

`LiveHealthRuntime(admission_policy, health_init_runtime, coarse_router, daily_skill_runtime=None, *, asset_paths, core_options=None, governed_nondiagnostic_runtime=None)`显式装配该纯运行时。生产governed配置必须提供真实GovernedNonDiagnosticRuntime且daily_skill_runtime为null，由其内部构造的真实runtime装配Core；不能要求调用方另交dummy/任意executor。旧无governed配置仍要求原真实typed DailySkillRuntime，保留冻结兼容；两者同时提供或生产governed缺失依赖均拒绝。Core不持模型凭据/HTTP adapter。公开Module固定为`partner_health_steward.governed_nondiagnostic`（纯typed候选/运行时）和`partner_health_steward.live_nondiagnostic`（Plugin短RPC/model Bridge）。Hermes Plugin进程装配`LiveNonDiagnosticModelBridge(core_port, adapter)`，adapter为已绑定同budget/strategy的真实ProductionModelAdapter；网络替身只能在125现有transport边界。公开`async advance_source(source_causal_id) -> dict`只驱动Core指定的下一固定阶段，不决定另起source或第三次调用。

`create_live_nondiagnostic_model_bridge(core_port, *, route, budget, credential_provider)`是唯一生产模型factory：重建真实FirstHopRoute/NonDiagnosticOperationalBudget和同budget的真实measurement strategy，以`BoundResponsesTransport(route, credential_provider=...)`构造125 ProductionModelAdapter，再构造Bridge；不接受executor、任意HTTP callback、caller模型结果或任意schema factory。Live Adapter的受信Python组合配置`extra.nondiagnostic_model_binding`精确为`{route, budget, credential_provider}`，前二项为原wire，credential_provider为当前已批准Hermes profile的短寿命取密钥能力，只能由受信启动组合注入，不是JSON/native消息可提供的callback。实际registry factory存在该配置时调用上述公开factory并显式选择governed receive/wake；缺少任一依赖、route与budget不符或Core未装配该runtime时失败关闭，不退回旧typed/synthetic executor或普通Session。密钥能力不进入Core、wire、发布物或日志；128负责把实际profile资源绑定到该已有能力，不能借别的profile/default环境补配置。

真实入站Facade固定为`HealthPlugin.receive_governed_weixin(message: RawWeixinMessage, *, peer_id) -> dict`，经同原admission/safety/coarse/init；enabled来源的上述闭集主人命令先派发到Core有限owner入口，其余健康/混合源只held供本票两阶段推进。普通source仍须原coarse明确非健康证明，不能因模型/分片失败转普通。Core必经公开短方法为：

- `prepare_nondiagnostic_stage(source_causal_id, stage) -> {stage, state, request, effect_intent}`；request为canonical StrictModelRequest wire或null，effect_intent为真实typed EffectIntent或null。intake必须原源仍held且无已完成intake；answer必须同源evidence-finalized且intake结果已被本Core验证并提交使用。重复、错阶段或当前批准失效返回无新intent。
- `start_nondiagnostic_stage(source_causal_id, stage, grant) -> {stage, state, request, attempt_ref}`；Core重验真实typed grant、当前head/fence/route/budget/schema与exact request，先持久原ExecutingEffect.model_attempt_started，再返回一次性attempt引用和request。它不执行网络，不持Core lock等待Plugin。
- `complete_nondiagnostic_stage(source_causal_id, stage, grant, attempt_ref, result: ModelTransportResult) -> {stage, state, reason_code}`；Core规范重验完整结果，自己调用StrictHealthLLM.resolve_transport_result生成report，绑定原grant/request/source/stage并经原effect.result终态/lease释放。不能接受Plugin提供ModelEffectReport、candidate digest或“成功”布尔值代替完整结果。
- `abort_nondiagnostic_stage(source_causal_id, stage, grant, attempt_ref, *, reason_code) -> {stage, state, reason_code}`；只承接下节闭集传输/adapter异常观察，未start不伪造attempt，已start无完整结果沿原unknown；已有完整terminal不可覆盖。
- `advance_governed_source(source_causal_id) -> {response, next_stage, model_use_disclosure, delivery_refs}`；只用本Core已经观察的候选推进原typed日常阶段/唯一提交，返回原Response wire及intake/answer/null。最终response沿原turn_result，可交126受控投递，不直接网络send。
- `nondiagnostic_source_status(source_causal_id) -> {source_causal_id, next_stage, state, reason_code, model_use_disclosure}`；投影无健康正文/凭据，不能补造候选或report。

公开短方法返回state闭集为`ready/attempted/completed/failed-closed/unknown/owner-decision-required/finalized`，只是原source/effect/daily事实的投影，不新增持久状态机。attempt_ref来自原effect/lease的单次关联，不是第二个批准、重试令牌或跨服务私有session ledger。

## 同三kind的精确CorePort与有限分片候选

interface沿`health-entry-v1`；未知op/field拒绝。command/controlled-effect仍`{interface,operation,payload}`，managed-read仍`{interface,projection,payload}`。同ProductionCoreService原_effect_sessions保存真正typed intent/grant/capability。上节Core进程内短方法仍处理完整StrictModelRequest/ModelTransportResult；下列wire只解决跨进程有限传输，不能把chunk、caller digest或buffer当candidate/report权威。

旧118/123单frame的65536-byte上限不变。131最终HTTP请求65536-byte预算与StrictModelRequest.to_wire大小是不同量；已纯内存复现合法HTTP body 1527 bytes而request wire 67067 bytes、合法ModelTransportResult wire 66004 bytes，所以不能在prepare/start直接回full request、在complete直接塞full result，或靠2048 output tokens猜测帧一定够。固定两种模型传输内容，仅为canonical UTF-8 JSON的原StrictModelRequest.to_wire和原ModelTransportResult.to_wire：JSON参数为ensure_ascii=False/sort_keys=True/separators=(",",":")/allow_nan=False，解析拒绝重复键、尾随内容及非canonical字节。

每份完整传输上限固定8388608 bytes（8 MiB），原始bytes每片固定32768 bytes，只有末片可更短。切片按bytes，允许在UTF-8多字节字符中间切开；单片仅严格base64解码，不独立UTF-8/JSON解析，拼齐后才进行完整解码。request/result方向各自固定，在该grant下不能互换，即使digest相同也不跨用途拼接。descriptor/receipt精确为`{size_bytes,digest,chunk_count}`；digest为全部canonical bytes的`sha256:<64hex>`，chunk_count为ceil(size_bytes/32768)，范围1..256。所有片之外的完整CorePort envelope元数据（把bytes_b64置为空串后）最多16384 canonical bytes，实际完整frame仍须先编码确认不超过65536 bytes；不放宽旧framing。若request本体、descriptor或该grant所需控制元数据不合上限，start前失败关闭，模型attempt=0。8 MiB不是新HTTP预算：125原4 MiB raw-terminal限制、原字符串上限和完整typed转换仍成立；本票验证该125边界合法结果规范化后的上界，不通过接受更大raw响应绕过。

同一grant只允许一份request传输和一份result传输，分别固定从index=0按next-index顺序递增；最后next_index为null。grant沿原`session_id/lease_id/effect_id/intent_digest/generation/writer_fence`，每步必须与同source/stage的原typed session逐字段相符；不存在独立transfer ID、上传token、可续传任务或新批准。错序、重复片、metadata变化、非法base64、长度不符或错digest均拒绝并关闭该传输，不能覆盖旧片、跨grant拼接或用另一source/stage完成。一次request读片响应丢失可使本次关闭，但不会产生模型attempt；start之后传输不完整则保持原attempt未知冻结，不能自动重调模型。

| kind / op | 精确payload | 精确返回payload |
|---|---|---|
|command `governed-receive`|`{message}`，同现RawWeixinMessage wire|`{response,next_stage,model_use_disclosure,delivery_refs}`；只准入/纯计算，不HTTP|
|command `governed-advance`|`{source_causal_id}`|同advance_governed_source|
|controlled-effect `nondiagnostic-prepare`|`{source_causal_id,stage}`|`{stage,state,request_transfer,intent,grant}`；request_transfer为descriptor或null，intent/grant为原service metadata或null；不回full request|
|controlled-effect `nondiagnostic-request-chunk`|`{source_causal_id,stage,grant,index}`|`{request_transfer,index,bytes_b64,next_index}`；仅该session下一片|
|controlled-effect `nondiagnostic-start`|`{source_causal_id,stage,grant,request_receipt}`|`{stage,state,request_digest,attempt_ref}`；不回full request|
|controlled-effect `nondiagnostic-result-chunk`|`{source_causal_id,stage,grant,attempt_ref,result_transfer,index,bytes_b64}`|`{stage,state,next_index}`；result_transfer为上述descriptor，首片建立有限短内存buffer|
|controlled-effect `nondiagnostic-complete`|`{source_causal_id,stage,grant,attempt_ref,result_receipt}`|`{stage,state,reason_code}`；Service收齐并规范重验全部bytes后，才调用Core完整typed complete|
|controlled-effect `nondiagnostic-abort`|`{source_causal_id,stage,grant,attempt_ref,reason_code}`|`{stage,state,reason_code}`；attempt_ref为start前null或原start引用；reason_code仅`request-transfer-aborted/result-transfer-aborted/adapter-precall-unconfirmed`|
|managed-read `health-entry-nondiagnostic`|`{source_causal_id}`|同nondiagnostic_source_status，无正文或分片|

prepare在原service claim后产生唯一grant/descriptor；Service在首次输出前检查可安全传输。Plugin必须收齐request全部片，独立验证descriptor/规范bytes并以StrictModelRequest.from_wire重建exact request，才发送start和相同request_receipt。Service同时验证自己已按序交出全部片、该receipt等于原Core request；Core再查当前head/fence/route/schema/budget并持久model_attempt_started。start成功才可在Core之外`await asyncio.to_thread(ProductionModelAdapter.execute, adapter, exact_request_wire)`一次；不在Core/executor/socket锁内网络，不反向RPC callback。start响应丢失时不执行模型，原持久attempt仍按未知收口，不重start。

Plugin对每个实际返回的ModelTransportResult使用类级canonical_copy/to_wire保留全部字段及completed/incomplete/failed/unknown事实，分片传完后发送complete；不能截断structured_output、只传digest/report或把已观察completed改成unknown。Service拼齐后验证总长/SHA256/canonical codec，完整typed result才交Core纯resolve生成report并写原journal。任何已观察完整terminal都必须走这条路径；不得用旧generic-terminal跳过完整resolve。complete回复丢失只查同source状态及原terminal，不再次execute。若完整result违反已验证传输上界，属于关闭本次组合的实现/合同失败，保留已观察typed result到该短寿命结束并报告传输失败，禁止伪造替代ModelTransportResult或宣称模型未完成；不得据此放宽上限或重调。

125.execute在transport.send之前还会重新preflight/measure；该段异常目前在其try之外。Core start后若这一步抛异常、Plugin未得到typed result，Bridge调用固定adapter-precall-unconfirmed abort，Core按已持久attempt而未观察完整结果的事实关闭原effect/lease并冻结；不能退款、宣称not-started或第二次send。abort不是Plugin自报模型report，不接受模型status/candidate字段；若Core已有完整terminal，abort只读回原事实，不能覆盖completed。request未start的abort只释放原claim与buffer并failed-closed，模型attempt仍为0。

传输buffer只附着于同Service既有_effect_sessions/该stage的短寿命内存；请求本来就在Core内存，不另存持久正文，不新增transfer表、ledger或第四kind。每次RPC正常EOF只是一次短调用结束；真正peer进程退出、本票session内存持有上限到期、Service/Core关闭、explicit abort或任何校验失败都清理buffer。start后missing片/断开/重启沿原executing/terminal unknown恢复，不从digest补结果、不让Plugin缓存成为恢复权威。未知收口、失败或阶段完成及时释放buffer和其停止记录source的原transient持有，分片不得延长本票固定内存持有上限，原ExecutionLease与CurrentHead语义不变。

生产Live Adapter在上述配置存在时必须显式调用governed-receive；遇到held/next_stage时等待Bridge.advance_source，直到Core唯一finalized结果再交126，而不是继续要求receive立即有turn_result或回退ordinary。governed-wake返回的delivery_refs也须逐个交126 Bridge并读回handoff；不能只probe成功或忽略投递结果。原初始化/安全分支仍执行126既有准确业务引用。Core按stage选择两个真实LLM及各自不同schema authority digest，不能只用一个_model_authority_digest或authority_for_digest四元组冒充intake配置。actual registry和Publisher发布包必须证明整条组合可达。

## 重放、失败与正文寿命

只读characterization修正：`authority.ExecutionLease:475`只有lease_id/effect_id/intent_digest/authority/holder_id，无时间或TTL；Core现有300秒owner-delivery attempt marker及task lease期限不是model effect租约TTL。本票选择的是同effect session最多300秒的短内存持有上限，到期由Service调用既定abort按真实started/nonstarted收口，不新增CurrentHead过期语义或假定原租约随时间自动释放。

同原生事件重投只查同source及固定stage事实，不以换causal ID或第三stage重试。未开始时预算/route/profile/owner currentness失效是failed-closed/not-started；真正started后timeout/response-loss为unknown并冻结。已completed但候选仅存在于旧Core内存、重建后丢失时，沿旧unknown-owner-decision-required，无重调、无cursor，不能从digest恢复正文或相信Plugin缓存候选。

intake成功后只有本Core验证过的candidate可以驱动证据提交；可复用其已提交证据继续answer。已知failed/incomplete不写推测事实，可用原失败关闭atom形成明确限制提示，保留真实report和131说明。answer只有当前引用与批准链通过才产生正文。unknown/待主人决定不把“模型没抛异常”当完整上下文或业务完成；126投递仍需唯一提交及原ACK前handoff。

停止记录时，原source正文仅在现Core `_recording_excluded_sources` transient cache中，新intake前不得因一次receive返回就误清空，也不能补写SourceReceipt/WAL/临时文件。只由同source的原model effect/实际CorePort会话持有有界内存所有权，受130同effect session固定内存持有上限约束，最长300秒；结束/failed-closed/unknown/取消/Plugin holder退出/Core关闭即释放；每条RPC正常EOF不是业务session断开。复用原_effect_sessions及OS对真实peer进程生命周期的识别，不新建 durable session/正文ledger。Service既有空闲循环在该内存上限到期时调用既定abort，按原effect实际started/nonstarted事实收口后清理；不能靠休眠假定原model lease自动释放。超出内存持有上限后晚到的candidate也必须再查同source/currentness，不能恢复正文或写事实。重建只有body-free receipt/digest时停止，不能把Plugin缓存或模型回包当恢复权威。

## 有限真实主人入口候选

主人操作先经同唯一owner/private/account/native admission；Core由原source和current head派生OwnerCommandContext/OwnerMutationContext及TrustedHealthCommand的source/scope，绝不接受caller提供health_operation context、owner_id、permissions、generation或批准。模型任务建议只可作为建议，不能当owner approval。

本票支持固定可见命令及一一对应中文别名（`帮助/当前状态/暂停主动联系/恢复主动联系/停止记录/恢复记录/提醒我/取消提醒/查看资料/导出资料/纠正资料/删除资料`）；Core回复实际显示示例，不要求主人构造JSON：`/health-status`、`/health-pause`、`/health-resume`、`/health-recording-stop`、`/health-recording-resume`、`/health-task-once <主人当地明确时间> <提醒原文>`、`/health-task-cancel <task_id>`、`/health-view [topic]`、`/health-export [object_ref...]`、`/health-correct <object_ref> <更正原文>`、`/health-delete`及本票对原typed lifecycle的独立native确认命令`/health-delete-confirm <operation_ref>`。暂停/恢复沿现OwnerControlCommand，停止记录沿现recording控制且不偷偷恢复；status无模型调用。

提醒时间按主人已设置时区解析当地日期时间，支持明确日期或今天/明天加时刻；缺日期/时刻、DST歧义或过时不猜，返回固定补问。`health-task-once`是主人明确请求的单次自有提醒：当前披露显示只向当前主人/当前Weixin route发送一次、固定目的/范围/期限和取消方式。Core从该原生显式命令生成现ExecutionScopeApproval与TaskCandidate，max_attempts=1、唯一当前接收方，不授权联系人或任意外部调用；自然语言intake本身不能生成该批准。重复native事件返回原task/approval，不新建第二任务。固定`command/governed-wake payload={}`由Core当前时钟推进现due任务并形成原outbox，返回`{delivery_refs,task_status}`；现调度/轮询实际调用它，126只投递Core返回的`owner-outbox`引用，不新建timer/后台队列或直接send。wake还按主人时区计算现LocalDayKey，实际接原DailyReviewEngine.prepare/commit以及现task claim/advance/solve；只处理当前due任务及当前当地日，复用completed review key/原outbox幂等，无补跑过期日、无模型第三阶段或新调度ledger。暂停/撤销/过期route或scope不投递，unknown维持原冻结。系统timer安装及运行target精确批准留128，但130必须交付可直接调用的真实当前wake。

Core公开`governed_owner_command(source_causal_id) -> {response,delivery_refs}`及`governed_wake_current() -> {delivery_refs,task_status}`分别映射上述owner/wake wire，不接caller context、任意callback或测试用预执行结果。`command/governed-owner-command payload={source_causal_id}`只解析该源实际原文和上述闭集，返回`{response,delivery_refs}`；不接自由action/payload/context。删除复用原typed lifecycle的当前target/operation绑定、purge/terminal/通知；本票新增独立native确认适配，普通“删掉”模型候选不能触发删除。资料查看、导出、纠正均是本票必需项：查看走managed_rights_read_current及原ManagedObject当前版本/撤销边界；纠正走managed_correction_draft→原PendingCorrectionDraft/OwnerMutationRequest与Ticket112完整原子链，引用实际admitted纠正source，replacement只来自主人明确更正原文/已验证有限抽取，受影响判断先降级，不写替代事实到另一个store。一般问答不能暗变成纠正；资料查看/导出不调用模型。

`/health-delete`先由Core生成当前主人本次明确删除范围（本安装受管健康资料delete-all）的原owner命令/回执与可见说明，只返回同一确认引用，不执行删除。固定可见语法为`/health-delete-confirm <operation_ref>`；operation_ref由Core从该原请求/回执派生并渲染，是opaque引用，不是模型或caller指定的scope/context。确认必须来自说明之后另一条独立admitted主人native消息；Core核验不同原生事件、原请求/回执及已受控交接的说明、当前owner/route与当前权威均匹配，才调用既有typed lifecycle delete-all。相同request重放只返回原确认，不删除；错ref、错owner、旧route、伪JSON或模型生成文本均不能触发删除。独立verifier可动态解析Core实际展示的固定前缀及opaque ref，再用新native消息确认，不固定内部hash/signature。该确认只适配原owner receipts/lifecycle，不另建批准ledger或第二删除协议。

### 主人实际可见的固定结果

所有governed receive/advance统一返回`{response,next_stage,model_use_disclosure,delivery_refs}`，owner-command返回`{response,delivery_refs}`；delivery_refs只含Core已提交的原`owner-outbox`引用，不能含caller text、任意to或裸发送callback。Core从该native source对应的真实command receipt、已finalized业务或原terminal事实确定性渲染固定中文结果，沿当前批准模板/同outbox/effect提交并交126 prepare/authorize/complete；结果需要的受管事实与outbox关联同成同败，不新增另一个result状态或持久ledger。重复native source或反复读取只返回同一个既有引用，不产生第二次业务/发送。

初始化独立confirm native source经过原consent/commit/finalize后，Live Adapter必须调用同`governed-advance {source_causal_id}`。Core重新核验该原confirm source与OwnerInitialization.workflow/disclosure/admission因果绑定，以及同一真实initialization finalized transition与enabled readback；仅仅UI读到enabled、收到ACK或caller声称成功均不能生成此结果。Core在原owner-outbox绑定该source/transition，唯一固定说明实际包含“健康管家已初始化；诊断未启用”及Core当前131模型使用/上下文限制。Adapter只交此outbox引用给126 Bridge并读回handoff后才推进该confirm source的native cursor；不自行send成功文案，不把Core enabled误写成主人已看到消息。重投相同confirm只复用原结果；初次披露和confirm成功结果保持两个实际独立native来源。

暂停/恢复、停止/恢复记录、提醒创建/取消、当前状态、查看/纠正/导出/删除结果，以及模型已知失败/限制/未知提示，均须实际形成Core授权主人可见结果；不能仅在RPC返回reason_code、内存回调或状态projection里存在。正文取原业务事实/固定模板，控制成功必须在同真实commit读回后才能说“已停止记录”等，失败/未知明确说无法确认，不夸大已执行；资料查看可含当前获准对象，导出结果另附下节文件，删除仍沿原lifecycle允许的最小无健康正文终止通知。

对模型unknown/候选丢失等尚未取得DailyTurnResult的来源，Core只依据已持久原model effect/report/receipt，沿原mandatory-owner-decision/status机制形成该来源的一次最小固定限制提示；不能重建模型答案、补证据或绕日常唯一提交。所需窄权威只覆盖该确切未知事实的当前owner/route、无健康正文的固定通知，不恢复一般health/model/outbound写入；current head/fence本身无法证明时仍不发送。该提示自己的网络结果若未知，保留原outbox unknown，不递归生成另一个“提示未知”的通知或自动重发。发出限制提示不将原未知模型来源改为成功，不凭此ACK原本仍需owner decision的NL来源。初始化/控制命令的cursor也仍须其原业务终态和Core handoff双条件，网络accepted永不冒称主人已读。

正式JSON导出走原managed_rights_export→ManagedExport.to_wire规范对象，保留snapshot/source_state/object版本/修订引用，不能让模型拼JSON或重新导入作为权威。Core生成canonical UTF-8 JSON，以现认证加密纳入同一store的原rights受管registry，标记server-export副本并由原lifecycle purge覆盖；当前纯ManagedExport还没有附件字节存取接缝，这是本票必需的有限增量，不能把现纯对象或opaque引用当文件已交付。不另开export DB或通用文件服务。固定上限8388608明文字节（8 MiB），超限明确“未导出，请选择更小资料范围”，不能静默截断、自动拆包或宣称文件完整。文件名固定为`health-export-<64hex>.json`（canonical文件SHA256去掉sha256:前缀），不接受调用者路径、文件名、扩展名或任意字节。导出对象与其原owner命令回执/outbox绑定同成同败；重投同native source只引用原snapshot和原效果，不能重新生成一个文件并补发。资料查看返回当前真实受管对象；单次文本不能完整表示请求内容时明确请缩小范围或导出，不把截断预览称完整资料。

### 唯一附件公开API与Core授权

主人必须实际能取得JSON附件，opaque工件引用或分页预览不算完成。唯一新增purpose为`export-artifact`，复用同Weixin provider/原owner outbox/effect/lease/registry。Core由真实admitted明确“导出资料”source形成精确snapshot及原`owner-outbox`引用；只有该显式命令授权当前owner/account/route的该exact artifact单次发送，不授权联系人、后续变更快照或任意外部存储。模型无权签发导出批准。

不新设export prepare/start/complete协议：沿126 `delivery-bind(owner-outbox)`→`delivery-prepare`→首次`delivery-authorize`→固定受管读片→再次`delivery-authorize`→发送→`delivery-complete`和原OwnerDeliveryTransportResult三字段wire。首次authorize为同一次原effect持久attempt并允许读取；第二次只是发送前的currentness复核，不新建或追加attempt，不开放126文本purpose重复authorize/重发。原authorization外层字段不变，recipient_role必须owner，purpose为export-artifact，send_intent仍为原OwnerDeliverySendIntent，payload精确为`{artifact_ref,filename,size_bytes,digest}`；artifact_ref是Core受管引用而非路径，digest为canonical文件bytes SHA256，payload_digest仍为该最小metadata payload的canonical digest。Core独立核验原outbox/send_intent digest、批准的文件metadata、选中对象版本/撤销边界、当前head/fence/owner/account/route及原lease；不能拿caller digest证明文件。普通业务CAS造成整体state变化不自动重造快照，选中对象若已更正/撤销则拒绝旧文件。

唯一新增`controlled-effect / export-artifact-read`，payload精确`{intent_id,grant,index}`，返回精确`{artifact}`；artifact为null或`{artifact_ref,filename,size_bytes,digest,chunk_count,index,bytes_b64,next_index}`。对应Core公开`read_live_export_artifact(intent_id, grant, index) -> {artifact}`（进程内本片字段为bytes，由Service编码为bytes_b64）。size_bytes/digest指全部canonical文件，chunk_count/bytes片长/严格next-index/byte上限沿上节同一固定slice helper；这是export方向，不是模型result传输，错purpose/grant不能混片。不增加另一套ledger、generic文件读取或任意URL能力。

Service从同原_effect_sessions取真正typed grant；Core确认该exact export已首次authorize并持久原attempt，逐片重查当前批准、head/fence、对象版本/撤销和route，才能解密原受管bytes。在此之前、错grant、wrong purpose或读片顺序不符均返回null并关闭该传输。每attempt从0到末片只读取一次，每次完整envelope仍先量化受原65536-byte上限；metadata超界在首次authorize前失败关闭。Service只在这个export session的短内存保留解密副本/next-index，不写明文缓存、每片receipt或新表；读片丢失/失序不得重读/重新生成文件/自动send，原attempt按unknown收口。

`LiveWeixinDeliveryBridge(core_port, wire_adapter_factory, *, clock, export_wire_adapter_factory=None)`只增加这一可选factory，旧126文本factory及purpose不变。Bridge在首次export授权后按序读完，拼全并独立重验Core固定filename/size/digest/bytes；随后对同intent/grant再次调用原delivery-authorize。Core必须证明Service已完整交出该exact文件并重验当前head/fence/批准/route与未撤销对象，返回同原execution及exact metadata；当前性失效或无法证明时不构造网络adapter，不把先前授权继续当可用。仅完整读取且第二次authorize成功，Bridge才调用`export_wire_adapter_factory(authorization, plaintext_bytes)`构造单次adapter；不调用文本factory、不生成caption。缺factory、读回不确定或复核拒绝均不网络、不补发，原attempt保留真实未知/失败投影。返回仍为126 status/source/handoff/投递列表，不能吞附件complete结果或凭CDN成功推进cursor。

公开类固定为同`partner_health_steward.weixin_transport.PinnedWeixinExportArtifactAdapter(binding, authorization, artifact_bytes, *, token, context_token_provider, session_factory=None)`；实现同步`send(exact_send_intent, /) -> OwnerDeliveryTransportResult wire`。constructor持明确bytes，send检查与Core授权完全一致、filename无路径/换行、rawsize/digest相同且<=8388608，单次latch后只在自己的asyncio.run loop创建/关闭HTTP session；Bridge沿原asyncio.to_thread调用。生产autowire在当前已批准同WeixinTransportBinding/token/context资源上构造这一个export factory；不能另选账户、provider、profile或reader路径。HTTP替身只替session_factory边界，不能代替Core授权、受管字节读取或最终outbox。

字节只在Core原解密短内存及Plugin本次拼装/加密内存中存在，不落非受管明文缓存/普通Session/模型/日志；每个effect session只允许一个export buffer，全部buffer受130同effect session最长300秒固定内存持有上限约束，分片不得续期；这不是原ExecutionLease的TTL。到期沿该用途既定abort/原效果收口处理真实started/nonstarted事实并释放buffer，不更改CurrentHead。complete、unknown、读取/验证失败、撤销、删除、holder退出或Core关闭时立即清除；原registry的加密导出副本随rights purge清理。两种模型transfer和export共用纯byte-slice/长度/SHA256校验helper，彼此按purpose/source/grant强隔离；helper只做内存传输，不能增添第二业务真相。

### 固定pinned媒体wire与网络边界

固定源码为Hermes Git `3c27eb6234bf91b8ceee9e9071591b31e9b148cb`的`gateway/platforms/weixin.py`：原常量API为`https://ilinkai.weixin.qq.com`（91），CDN为`https://novac2c.cdn.weixin.qq.com/c2c`（92）；_get_upload_url(549)、AES128 ECB bytes helper(209)、_upload_ciphertext(581)与_api_post(399)可以全内存使用，文件wire见2144–2240/2298–2308。原高层_send_file会Path.read_bytes且无条件采用upload_full_url，不复用该高层路径、caption额外发送或native自动重试。

新附件adapter只允许binding.base_url精确等于上述API origin；HTTP wrapper只接受`https://ilinkai.weixin.qq.com/ilink/bot/getuploadurl`和`https://ilinkai.weixin.qq.com/ilink/bot/sendmessage`，不改变126文本wrapper已冻结行为。CDN只允许HTTPS无端口/userinfo/fragment的`https://novac2c.cdn.weixin.qq.com/c2c/upload`，query精确为不重复的encrypted_query_param/filekey，filekey必须等于该attempt本地产生的值。优先用有效upload_param经pinned _cdn_upload_url构造；若仅返回upload_full_url，只有它与同固定origin/path/query/filekey验证全部匹配才可用；任何HTTP/其他host/额外参数/编码别名/redirect均拒绝。全部session trust_env=False、allow_redirects=False，token只交固定API，CDN只接密文，不带账户API token。不能接受caller URL或pinned较宽的七host/HTTP允许集合。

一次原effect attempt固定顺序且每步最多一次：①_get_upload_url(media_type=3,to_user_id=Core主人,filekey=本次随机16bytes的32hex,rawsize=len(bytes),rawfilemd5=lowercase MD5仅协议字段,filesize=_aes_padded_size(rawsize),aeskey_hex=本次随机16bytes密钥的32hex)；已知非零ret/errcode拒绝，缺必要ticket也不上传。②_aes128_ecb_encrypt对本次bytes按pinned PKCS7加密，上传密文一次；8388608 raw上限对应最大8388624密文字节。③_upload_ciphertext一次POST只在HTTP200且有效x-encrypted-param时有CDN接受证据。④最后一次_api_post EP_SEND_MESSAGE，精确msg.from_user_id空串、to_user_id为Core主人、稳定client_id绑定原intent/attempt、message_type=2、message_state=2、item_list仅一个type=4 file_item；file_item.media精确encrypt_query_param/CDN返回、aes_key=base64(32 ASCII hex)、encrypt_type=1，file_name为Core固定名，len为rawsize十进制字符串，附当前同账户主人context_token。缺context token不tokenless补发，不发caption。

getupload API15秒、CDN120秒沿pinned超时；HTTP失败、部分上传/响应丢失或最终发送未确认均按原effect unknown冻结，零自动重试/第二sender。只有最终文件sendmessage明确0码可记provider accepted，明确非0码记rejected，其他记unknown；ticket或CDN成功绝不等于文件已发送。OwnerDeliveryTransportResult仍仅status/result_ref/evidence_ref，不新增delivered/read/主人已下载。主人实际导出说明固定包含“平台接受文件不代表你已经下载；导出到微信后的文件由你保管，管家删除资料不能撤回微信或CDN副本”。该pinned版本无CDN删除/撤回或下载确认API；原lifecycle只能确认本产品受管副本清理，已经交给Weixin/CDN/主人取得的副本不得声称已远程删除，其无法证明项沿原remains_unproven披露，不伪造purge证据。

## 主人可见限制与验收输入

组合根将131同一model_use_disclosure实际带入初始化显示和主人回复；record-only、failed-closed、known terminal和completed都不能移除“不提供共同上下文保证”。显示值取Core实际budget/报告，不接受Plugin自造较好说明；不把actual model/usage或配置240000写成保证。

候选有限outcome是：真实NL抽取且逐字来源/否定/时间边界；同源最多两stage的正确授权与跨进程单attempt；64KiB内有限分片完整request/result且Core纯resolve/原七Skill唯一提交；unknown/候选丢失不重调不ACK；当前approved claims/templates与45topic边界；真实due/localday review、主人控制/权利和可取得的受管附件且模型非批准；published registry/socket/真实125 transport边界组合与131可见声明。由独立verifier按现实mutation收敛门，不按内部字段或SQL做笛卡尔积。唯一design/独立contract/tests同checkpoint fresh Spec/Standards通过前不实现、不闭票。
