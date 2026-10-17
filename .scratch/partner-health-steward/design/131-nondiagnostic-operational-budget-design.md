# Ticket 131 — 非诊断模型操作预算唯一增量设计候选

本票承接 [ADR 0024](../../../docs/adr/0024-allow-owner-selected-nondiagnostic-model-operational-budget.md) 的主人决定。基线 `58453bf` 已闭合 124／125／129；执行证据 [44](../evidence/44-ticket124-125-129-formal-execution-20261018.md) 与双轴终审 [45](../evidence/45-ticket124-125-129-postimplementation-review-20261018.md) 证明旧严格路径通过，不证明 JOJO 共同容量、真实请求、部署或主人验收。本文件当前是设计候选；产品修改须等待同一 checkpoint 的独立合同、预期红灯及 fresh Spec／Standards 预审。

## 当前事实、现实差额与非目标

- `model_contract.py:151–249` 的 CapabilityProfile 必须有正整数共同容量下界；StrictModelRequest 的旧 codec 使用 input token 上界，不能诚实表示仅本地字节预算。StrictHealthLLM:555／583／640、ProductionModelAdapter:366 和 Core:5679 的 concrete type 检查不会接受随意 callback 或子类。
- 已有最终 canonical wire builder（model_adapter.py:210）、单次 BoundResponsesTransport:272、raw terminal decoder:405、request／authority digest 和 Core exact source／grant／attempt journal:5668–5835 可以复用。没有必要建立第二模型路由器、CorePort kind、批准 ledger 或业务库。
- Core 的真实 `diagnosis.prepare`（core.py:7106–7240）从同一 authority resolver 取得 profile；仅给 ND schema 改名不能阻止该入口借用预算形成诊断 intent。必须在该源操作形成任何 model intent 前识别并拒绝 ND authority。
- 131 只增加一个当前可验证 schema：现有 NonDiagnosticCandidate 的非诊断回答候选。不实现证据前自然语言抽取、画像 executor、跨进程完整 model session 或主人最终界面；这些继续由 130／128 承接，不能把本票通过称为完整自然语言产品已可用。Budget 的固定用途边界是 non-diagnostic-health，后继 130 可在同一 Module 经其独立冻结扩展固定 ND 阶段／schema 关系，无需第二预算类型；131 不预建任意 schema／purpose registry。

## 不变量与有限预算

旧 CapabilityProfile、ProfileBoundInputMeasurementStrategy 和 synthetic／严格 request／report 的 wire、摘要及失败关闭行为保持不变。full／诊断继续使用严格证明模式。新增模式明确叫 `non-diagnostic-operational-budget`，用途边界固定 `non-diagnostic-health`，共同上下文保证固定 `not-provided`，公开中文说明固定为“不提供共同上下文保证”。

本地技术预算固定为最终 canonical UTF-8 JSON wire **65536 bytes**，`max_output_tokens`／输出预留 **2048 tokens**。两个值只是本地请求上限，不是可证明 token 计量或服务端容量。预算对象没有 common_context_lower_bound、wrapper-token 证明或 tokenizer evidence 字段，不接受将配置 `240000`、catalog、usage 或风险接受转换为这些字段。超限请求停止，不截断、删证据、自动分拆或重调；`completed` 不升级保证。

同意、route/provider/base/API/requested model/config generation、current head、writer fence、exact request、当前性与一次效果继续绑定。allowed actual models 是当前明确允许的身份集合，不能被描述为已经穷尽或证明上游路由集合；actual model 必须来自 raw terminal，缺失不能补 requested。Plugin 进程执行网络；Core 继续无模型凭据和网络。无工具、跨首跳 fallback、自动重试或 unknown 后的新调用。

## 公开 API 与 wire

以下公开接口供独立 verifier 使用；不冻结 dataclass 内部存放、private helper、局部 hash／SQL 或测试组织。

`model_contract.NonDiagnosticOperationalBudget(budget_id, budget_version, route, allowed_actual_models, owner_decision_ref, issued_at, expires_at)` 是不可变、重新校验的 concrete value。route 是既有 FirstHopRoute；allowed_actual_models 是非空唯一 tuple；owner_decision_ref 是当前主人决定的非空 opaque ref，不是新批准系统。时间使用 UTC ISO-8601，要求 issued_at < expires_at。公开 `to_wire()`、`from_wire(value)`、`digest` property 与 `model_use_disclosure` property；方法返回脱离内部可变值的规范副本。

Budget wire 精确字段为 `contract`（`nondiagnostic-operational-budget-v1`）、`budget_id`、`budget_version`、`route`（原 FirstHopRoute wire）、`allowed_actual_models`（list）、`owner_decision_ref`、`issued_at`、`expires_at`、`mode`、`purpose`、`max_final_wire_bytes`、`output_reservation_tokens`、`context_guarantee`、`context_disclosure`。其中 mode／purpose／limits／guarantee／说明只能为本文固定值，不能由 caller 升额或改成有上下文保证。缺字段、额外字段、无效类型、无效时段或固定值漂移拒绝。

`model_adapter.NonDiagnosticBudgetInputMeasurementStrategy(budget, *, clock=None)` 接受该 concrete budget，公开 `prepare_request(messages)` 与 `measure(request)`。messages 是既有 ModelMessage 非空 tuple；prepare_request 计算最终 wire、精确字节与消息 digest，返回**同一个 StrictModelRequest class**；measure 重新验证该请求并返回最终 canonical wire bytes。两者在预算未生效／到期、超 65536 bytes、authority／schema／output 漂移或非法消息时抛固定 ModelContractViolation，无 I/O。

ND StrictModelRequest 的 `to_wire()/from_wire()` 使用精确且独立识别的形状：`contract`（`nondiagnostic-operational-request-v1`）、`route`、`operational_budget`、`messages`、`final_input_digest`、`final_wire_bytes`、`output_reservation_tokens`、`strict_schema_name`、`strict_schema_digest`。route 必须等于 budget.route；消息 digest 保持原规则；final_wire_bytes 必须等于最终 wire 实测值且在预算内。此形状不包含 capability_profile 或 final_input_upper_bound_tokens；旧严格 request 的 wire 完全不变。canonical_copy、from_wire 和 digest 对两个明确形状分别重验，不把 byte 数写成 token 声明，也不允许 ND／严格字段混搭。

固定 ND schema 公开为 `model_adapter.nondiagnostic_operation_schema()`（返回副本），`NONDIAGNOSTIC_OPERATION_SCHEMA_NAME = "nondiagnostic-operational-candidate-v1"` 与 `NONDIAGNOSTIC_OPERATION_SCHEMA_DIGEST`（该实际 schema 的 stable_digest）。结构只承接现存 NonDiagnosticCandidate 的九项：owner_fact_refs、knowledge_refs、support、opposition、unknowns、limitations、next_steps、claim_ids、template_id；对象拒绝额外字段，引用角色分别固定 owner-fact／general-knowledge。数组和字符串沿用原 typed parser 的合法范围，candidate 仍由 NonDiagnosticCandidate.from_wire 重验，再由既有 pipeline 验证当前卡、批准 claim／template 和确定性渲染。不得接受 caller 注入任意 schema、诊断 JSON、自由模型回复或只因 schema 名字相同就放行。

构造保持同一模型接口：`StrictHealthLLM(budget.route, budget, request.strict_schema_name, request.strict_schema_digest, measurement_strategy=strategy)`；`ProductionModelAdapter(budget.route, budget, transport=transport, measurement_strategy=strategy)`；后者仍是 `execute(request.to_wire()) -> ModelTransportResult`。LLM 和 Adapter 只接受新的 concrete budget／strategy 配对或原严格配对；canonical_copy 调用类定义上的重验，不信任实例 shadow。LLM 的 `model_authority_digest` 绑定完整规范 budget、route、固定 schema；request.digest 绑定完整 ND request。二者进入原 Core effect intent／grant，不另发“预算批准”。authority_for_digest 仍返回原四元组；ND 时第二项是 concrete budget，用于源操作的明确模式识别。

## 公开说明与既有报告留存

`budget.model_use_disclosure` 与 `llm.model_use_disclosure` 都是 **property**，ND 时返回同一规范 dict 的副本；严格 LLM 返回 None。dict 精确八项为 `mode`、`purpose`、`budget_digest`、`owner_decision_ref`、`max_final_wire_bytes`、`output_reservation_tokens`、`context_guarantee`、`context_disclosure`。固定值同上，budget_digest 为完整 budget.digest。它不包含健康输入、凭据、响应 body 或“容量已证明”。

ND 的 ModelEffectReport 增加可选 `model_use_disclosure`，内容为上述 dict，完成／失败／不完整／unknown 均保留，`to_storage()/from_storage()` 严格重验并纳入原 report.digest。旧 strict report 该值默认为 None，序列化时不输出该 key，旧 digest／codec 保持不变。Core 仍只接受其既有受控执行路径观察、与 grant／source／request 摘要匹配的 report；caller 不能自报成功或移除／替换声明。

candidate 的领域形状不夹带模式 metadata。声明由同一 ModelEffectReport、ModelEffectRef.report_digest、request digest 和 ModelAnswerResolution.model_authority_digest 保留，不建立第二记录；Core.model_effect_report 可在原 effect terminal 提交后读回声明。131 证明该公开／可记录接口，不声称主人已经看到；130／128 须将固定说明接入真实整合回复／初始化展示，不能隐藏或由模型自由改写后宣称产品可用。

## 发送前后、unknown 与诊断源门

StrictHealthLLM.preflight 对 ND 模式返回原 StrictModelOutcome 形状，无 I/O；预算过期、缺策略、错绑定、超限或精确字节不符时为 failed-closed／not-started／`operation-budget-unavailable`。该 reason 仅加入 Core 现有 precall observation 闭集，使合法 source 可经原失败关闭结果链处理。Adapter 在单次 send 前再次校验预算与 exact wire；禁止发送后为了格式、expiry 或 unknown 再调用。

preflight／send 检查前已失效的预算不能产生网络调用。Core 的 durable attempt marker 是效果边界的现有事实；若其后、实际 send 前在 Adapter 内才发现失效，0 网络调用但不伪造 Core 能证明“从未尝试”：Core 按既有保守 unknown 处理，而非解除一次效果标记重新发送。这不改旧 125 的语义。

若有效期内开始且 send 期间到期，resolve 保留实际 completed／incomplete／failed、actual model、response identity、usage 与报告。completed 不产候选，返回 failed-closed、model_effect=completed、reason=`operation-budget-expired`；该 reason 只加入既有 completed-rejection 闭集。incomplete／failed 保留原终态与原因，不写 not-started、schema 错或 unknown。真正缺 terminal／model／usage、错误结构／工具、异常、EOF 或回交不能确认仍走旧 unknown 并冻结。发送后的事实不得因动态 preflight 被抹去。

真实 `HealthPlugin.health_operation("diagnosis.prepare", ...)`／Core `_execute_ticket116_diagnosis_prepare` 从当前已校验 authority 识别 concrete ND budget，在形成任何 model intent 前返回 rejected；即使 BMI scope 已由既有 strict 验收激活、知识／安全／当前证据／路线均有效也不能 model-ready。执行阶段也拒绝把 ND request 用于已存在的 Ticket116 diagnosis intent，避免只拦正常形成而留旧 grant 拼接。旧严格诊断正例和三段门保持不变；不能只在 schema parser、普通 UI 或新 helper 中模拟这个拒绝。

## 独立验证候选与实施边界

独立 verifier 持合同／门，按有限现实故障收敛：ND 同一 canonical wire 经真实 Core source／grant 单次完成并读回无保证声明；预算／route／owner decision／时效／精确字节或固定 schema 漂移在调用前停止；完整 raw 终态、缺 metadata、unknown 重放与在途到期保真；真实已激活 strict 诊断正向成立后换 ND authority，在原 diagnosis.prepare 源入口拒绝且无新 effect。现有 NonDiagnosticCandidate／pipeline 的 typed 和治理边界继续参与，不用离线 fake 冒充真实 JOJO。

既有回归为 125 四门、113 strict port／authority integration／contract／knowledge／nondiagnostic 与 116；若发布／验收装配受影响再运行现有 118／119，正式全量由 root 统一执行。旧测试文件和 125 冻结三件套不得修改。产品范围为 model_contract.py、model_adapter.py、answer_resolution.py 以及 Core 的模式源门／既有 reason 闭集／报告最小接缝；不改131之外的126或130实施。

真实模型调用、账户／凭据、健康资料、partner、G10/G11 与部署不属于本票离线实现授权。需要任意动态用途、自由 schema、第二 router／ledger、替换原严格模式、宽松 terminal 或绕过 Core grant 时停止并回同一票，不在编码中扩架构。
