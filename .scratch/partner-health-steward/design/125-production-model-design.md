# Ticket 125 生产模型 Adapter 唯一增量设计候选

状态：pre-code candidate，尚未冻结，尚未修改产品代码。Characterization 基线为 19417da；本设计只实现 Ticket 125 的生产模型效果 Adapter、可核验输入计量接缝，以及既有不可变治理知识工件的装配验证。它不改变 HealthCore、诊断、证据、同意或任务业务语义；不执行真实模型、网络、微信、AWS 或部署。

## Characterization 与真实差额

1. model_contract.py 的 FirstHopRoute、CapabilityProfile、StrictModelRequest、ModelTransportResult 和 StrictModelAdapter 已有严格 wire 合同。StrictHealthLLM.preflight 已检查 route/provider/base URL/API/model/config generation/owner consent/profile/schema/output reserve；resolve_transport_result 已拒绝 actual-model drift、fallback、truncated、未知终态和不合格结构。保留其既有行为。
2. model_contract.py:765—780 目前对 synthetic=False 无条件返回 capacity-unavailable，只承认两种 synthetic 字节计量方法。因此提供生产 HTTP client 本身不能使合法生产调用通过 Core；不得把真实 profile 标 synthetic。
3. HealthCore.execute_strict_health_model 在产生外部效果前先调用 StrictHealthLLM.canonical_copy 和 preflight，并以 model_authority_digest 授权。计量能力只挂原对象会被 canonical_copy 丢弃；生产计量必须经过同一 canonical authority 复制、验证和副作用前门禁。Core 的 current head、writer fence、exact effect grant、幂等和 unknown 恢复均继续拥有唯一权威。
4. 当前诊断内部 request builder 只计算 messages JSON 的 UTF-8 字节数；生产最终 Responses body 还包含 schema 与包装。不得在 Adapter 内静默缩小或补写请求的已授权上界；调用方必须先用本票测量接缝形成精确 request，再形成 effect digest。未完成该调用方接线时生产请求安全拒绝。非诊断阶段不激活或绕过诊断。
5. 提供的固定 Hermes 源码中，agent/transports/codex.py:299—320 生成 Responses 的 model/instructions/input/store=False；其 normalize_response:467—513 只输出通用 content/tool/finish_reason，usage=None。agent/codex_responses_adapter.py:1029—1037 的通用 preflight allowlist 不含 text.format，因此不能经该 helper 保证 JSON schema 仍在最终请求中。
6. agent/codex_runtime.py:1152—1185 可观察 raw response.completed/incomplete/failed 及 usage/id，但其组装结果把 model 写为调用时传入的 model；run_codex_stream:1250—1275 还含重试循环。本票不能把这种 requested-model 回填或普通重试当作 actual model 与一次健康效果的证明。只借用固定 Responses 协议形状，不调用普通 Agent、ctx.llm、通用 normalize 或 fallback。
7. KnowledgePublisher、KnowledgeRelease、ImmutableKnowledgeRegistry 已有无主人资料的治理输入、内容寻址、不可变 staged release、withdrawal 和有效期语义；没有生产发布工件装配接缝。不得再建一套知识数据库或治理权威。
8. 目标已知 provider/API/model 只是候选绑定；配置中的 240000、API 成功或少数 usage 样本不证明整条路线的共同容量下界。真实 profile 的批准、tokenizer/上界依据和有效期仍是 G10/G11 前提；本票不得伪造这些事实。

本轮实测 characterization（禁网络、无真实资料）：PYTHONDONTWRITEBYTECODE=1 python3 -m unittest tests.test_ticket113_strict_port → 32/32 OK。用该套合成 request 仅把 profile.synthetic 改为 False，既有 preflight 返回 failed-closed/not-started/capacity-unavailable；model_adapter Module 尚不存在。这是待补差额，未借此调用模型。

本轮只读源码快照位于 /tmp/health-steward-hermes-pinned；该提取目录没有 .git，以上协议结论只绑定实际阅读的文件，不自行声称已重新验证 upstream commit。SHA-256：agent/transports/codex.py = ec90aa8124d993a8dfc52a0526ac5ae5c10e88937871968d7a1f7a8b726558d0；agent/codex_responses_adapter.py = 362d46bdb7e3c8b567d0404a8301fdbbb16d09efb86026564b3551e48a6d05f7；agent/codex_runtime.py = 27a855ed55a36ac63083bdae66c995365cfdb848b562e6a898ddfdf2e28692d8。发布仍由既有 pinned artifact 来源/patch/hash 门验证。

## 唯一增量与依赖方向

新增 model_adapter.py，公开 ProductionModelAdapter、ProfileBoundInputMeasurementStrategy、BoundResponsesTransport，以及 load_governed_knowledge_artifact。只对 model_contract.py 增加可选的具体生产计量依赖；既有 synthetic 测试与 wire schema 保持兼容。

依赖方向固定为：生产组合根/Plugin → StrictHealthLLM/Core → StrictModelAdapter → 受控、单一路线 BoundResponsesTransport。生产计量使用与 Adapter 相同的固定最终 wire builder；知识装配继续调用 KnowledgePublisher 和 ImmutableKnowledgeRegistry。Adapter 无 SQLite、current-head、任务、诊断或投递写权，不建立网络工具、模型路由器、通用 HTTP 接口、额外 ledger 或后台 worker。

## 公开调用合同

- ProfileBoundInputMeasurementStrategy(profile, *, schema, measurement_evidence, clock=None)。profile 必须是当前 nonsynthetic CapabilityProfile；schema 为 exact JSON-schema dict，其 stable_digest 必须等于 request.strict_schema_digest。measure(request) 返回最终模型 wire 的 input token 保守上界整数，不含已单独声明的隐式 fixed_wrapper_tokens 或 output_reservation_tokens；缺依据或失效抛 ModelContractViolation。
- StrictHealthLLM(route, profile, strict_schema_name=..., strict_schema_digest=..., *, measurement_strategy=None)。synthetic 分支沿用原算法；nonsynthetic 分支只接受本票具体 ProfileBoundInputMeasurementStrategy。canonical_copy 对其调用类定义上的重新验证/复制，不能信任实例同名方法；其证据 hash 已纳入 profile.evidence_refs，因而仍由既有 model_authority_digest 绑定，无第二 authority digest/ledger。无策略、策略无效或 measure 拒绝时，preflight 保持返回既有 failed-closed/not-started/capacity-unavailable Outcome，不向调用方抛异常。
- ProductionModelAdapter(route, profile, *, transport, measurement_strategy)。execute(payload) 接受既有 StrictModelRequest.to_wire()，返回既有 ModelTransportResult。route/profile/策略/schema/output reserve 必须精确匹配。最终 wire 计量超过 request 声明或容量时零 send，不改变 request、intent digest 或批准。transport 的只读 route 必须等于绑定 route；只调用一次 send(body)。
- BoundResponsesTransport(route, *, credential_provider, timeout_seconds=...) 是唯一生产网络实现；credential_provider 是目标可信组合根注入的凭据读取能力，不接受模型或消息中的凭据/URL。测试可在相同 send(body) Seam 注入标记明确的离线 fake，fake 通过不是 G11 真实效果证据。构造不发网。
- load_governed_knowledge_artifact(artifact, *, expected_digest, at) 接收 release builder 读取的固定工件 dict，返回既有 KnowledgeRelease 或 KnowledgeGap；结构/hash 伪造抛 KnowledgeContractViolation。它不检索、不接收主人输入、不扫描普通文件，也不将 staged 诊断改为 active。

生产组合根在当前 target/release/config generation 下构造 route/profile/策略/transport，主机配置、同意或批准变化即撤销旧绑定并重新验证；Adapter 不读取完整 Hermes 配置或凭据文件来猜测 currentness。Profile 的到期在每次 Core preflight 与 send 前用可信 clock 检查。若组合根不能证明绑定仍 current，则不签发 effect。

## 输入计量与批准证据

本票只实现一种受限、离线、确定性的生产方法：responses-final-wire-utf8-upper-bound-v1。它把固定最终 body 的 canonical UTF-8 bytes 作为保守输入 token 上界。该方法只有在相同首跳、允许的全部 actual-model identity、tokenizer/服务包装都存在相称依据、证明此 bound 保守且共同窗口下界有效时才能被 G10 批准。不能仅从模型名、tiktoken 猜测、240000 配置、中文字符数、事后 usage 或少数探测外推该前提。证据缺失时不支持生产计量并保持不可用，测试 fixture 只证明处理合同。

measurement_evidence 是 G10 已批准 profile 的静态无正文工件，不是新批准系统。固定语义字段为：contract=ticket125-model-measurement-evidence-v1；profile_binding_digest；schema_digest；wire_builder_version=responses-fixed-wire-v1；method_id；issued_at；expires_at；capacity_evidence_ref；tokenizer_evidence_ref；approval_ref。后面三个必须是当前 G10 绑定的非空 opaque refs。时间为带时区 ISO-8601 UTC；有效区间为 issued_at <= now < expires_at。

profile_binding_digest 对 CapabilityProfile.to_wire() 除 evidence_refs 外的全部事实作 stable_digest，避免证据 hash 自引用；measurement_evidence 的 stable_digest 必须逐字出现在 profile.evidence_refs 中。schema hash、方法、profile 绑定、证据版本、ref、窗口或配置任一漂移均拒绝；不接受 approved=True、自报“已审核”或未知算法名。源依据与批准由 G10 现有 target-local 边界核验并注入；本票只消费已批准、hash-bound 工件，不能凭 opaque 字符串创造批准事实。profile/策略和批准不是健康正文，仍只能在既定私有运行绑定中保存，不将真实目标值提交 Git。

最终 wire 明确包含 model、instructions、input、store=False、stream=True、max_output_tokens 和 text.format={type:json_schema,name,schema,strict:True}。messages 角色与内容转换是固定、确定的；不注入默认普通 Agent identity、历史、工具或隐式知识。空白/未知角色、schema 不合格、hash 不符均拒绝。tools、tool_choice、parallel_tool_calls、MCP、Web、reasoning history、previous_response_id、请求 overrides、自定义 extra_body/headers/URL、跨 provider fallback 均不接受。

计量覆盖这个 exact body，包括 schema、JSON 转义和固定字段。fixed_wrapper_tokens 只覆盖已批准且已量化的服务隐式包装，不用其掩盖未知 body。容量门保持 input_upper_bound + fixed_wrapper_tokens + output_reservation_tokens <= common_context_lower_bound_tokens；最终网络字节必须是已计量 body 的 canonical JSON，不经过会删 schema/增加内容的普通 Hermes helper。

## 一次外部效果与 raw 终态

生产 transport 只向 route.canonical_base_url 的固定 Responses endpoint POST；禁重定向、SDK/HTTP 自动重试、环境代理自动替换、自动 auth refresh 后重放与 fallback。限定超时及响应大小；credential 仅存在该一次请求的 auth header，不进入 body、异常文本、CorePort、release、报告或日志。不记录 prompt、raw response 或 transcript。

传输可接收 raw JSON response 或 SSE。SSE 只在取得唯一匹配 response ID 的 raw terminal event 后形成已知终态；delta 结束、EOF、HTTP 无错误或拼接出的 JSON 均不证明 completed。允许使用权威 output_item.done 的完整输出配合 terminal event；不把不完整 delta 当最终输出。冲突/重复不一致 terminal、响应 ID 不一致、工具输出或额外健康效果皆拒绝/unknown。

- completed：raw response 明确 completed，且 id、实际 model、usage.input_tokens/output_tokens 都存在且类型合法；取得完整严格 JSON object，无拒绝/工具/截断，才产生 completed ModelTransportResult。actual_model 只能来自 raw terminal metadata，不回填 requested_model。最终对象继续由现有 StrictHealthLLM 与领域提交边界校验。
- incomplete/failed：只在 raw terminal 明确证明对应状态、exclusive reason、identity、actual-model 与 usage 时映射；不携带 structured_output。reason 只映射成有界非正文代码，不传播自由文本错误。
- unknown：发送后网络异常、超时、EOF、缺 terminal/实际 model/usage、结构不完整或权威不一致均不产生候选。使用原 request digest 派生的本地 opaque unknown result identity；unknown 必要数值字段为未测得 sentinel，不解释为零 token 消耗或真实 model。已有 Core 把该效果保持 unknown，禁止自动第二次调用。
- 调用前的无效 route/profile/容量/schema/transport 绑定抛固定的合同异常，不能声称已调用。副作用开始后的错误不附 raw 响应/秘密，交回现有 unknown 语义；绝不为修复格式再次调用模型。

## 治理知识工件

工件固定为 contract=ticket125-governed-knowledge-artifact-v1、publication（既有 KnowledgePublicationInput wire）、release_version 和 release（既有 KnowledgeRelease wire）。exact-field 解析；expected_digest 为整个工件 stable_digest，必须来自当前内容寻址 release manifest。用现有 KnowledgePublisher 对 publication 重算并与声明 release 逐字比较，包括内容 hash、来源、用途/适用性、权利、中文、审核和时间；随后用 ImmutableKnowledgeRegistry.stage/resolve 检查当前有效、未撤回。

已有治理不足返回既有 KnowledgeGap，schema/hash 冲突拒绝；不能给未审核内容补 approved。工件只从 owner-independent release build 进入，拒绝 owner/session/message/context 等未知字段；本函数不声称能通过文字扫描鉴定任意 prose 是否含个人资料。真实个人输入根本不进入该构建路径。加载知识不赋予诊断范围 active，也不触发临时按主人问题回源。生产组合根只消费已核验工件，不自行复制第二知识正文真相。

## 冻结前验证范围候选

由独立 verification Agent 持有有限门，不以字段笛卡尔积扩张：

1. 真实标记 profile 经受限策略、canonical_copy 和现有 Plugin/Core exact grant 完成一次离线 transport；既有 synthetic 回归保持绿色。
2. 无证据/错 hash/过期/route或profile drift、容量不足、schema漂移均在 Core/Adapter前门零 transport；当前真实profile若无窗口/计量证据继续零调用。
3. exact wire 禁工具与 fallback；raw actual-model/usage/终态映射以及发送后 unknown 不重试；任意第二 send、requested冒充actual或delta冒充terminal必须使门失败。
4. owner-independent知识工件精确hash、重新发布一致性、失效/撤回/未知字段失败关闭；当前包进入同一生产组合根，staged医学不自动激活。

正式门、API fixture 与 mutation 由 verifier 独立维护；本候选未授权编码。待同一 checkpoint 的独立 Spec/Standards 预审通过后，再按有限门纵向实现。产品修改仅限 model_adapter.py 与 model_contract.py；生产组合根及发布装配接线由其现有文件负责人完成，双方共享公开合同而不并行改同一文件。

## 停止规则

需要跨首跳 fallback、任意工具/HTTP、改变 Core effect/grant 或 ModelTransportResult wire、把真实 profile 标 synthetic、伪造容量或许可、引入第二状态/批准ledger、修改冻结测试、访问真实模型/凭据/健康资料，立即带精确事实返回当前票。没有真实能力证据是尚未满足的外部门，不能用测试成功代替；也不能因此扩成新架构。
