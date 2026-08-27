# Ticket 116 增量架构冻结设计

> 状态：frozen。characterization 基线为 `1249734ef7aa10205b3852ad21a049a88a5e19a3`，tree 为 `eacf11a1ee3c7297368afa676cebe1e57ba031da`。本设计只冻结 Ticket 116 的难逆增量决定；测试门 commit/tree 与审查身份记录在 Ticket。本设计适用 [`AI 编码架构治理`](../../../docs/agents/architecture-governance.md)。

## 目标与非目标

在现有健康 Plugin/core 上闭合三项能力：独立、确定性的最低安全裁决；保持非 active 的 BMI 诊断实现及三段门禁；消费当前唯一支持联系人批准并形成最小警报、必要纠正和分层投递。

本票不取得医学内容权利或专业审核，不激活真实 BMI 范围，不调用真实模型、Weixin 或联系人，不执行 Ticket 117 的删除迁移、Ticket 118 的宿主接线或 Ticket 119 的真实验收。它不新建模型路线、联系人批准真相、投递账本、状态权威、服务或数据库。

## Characterization 与保留架构

- Tickets 113、114、115 已分别提供 StrictHealthLLM/知识与非诊断候选、主人控制/支持联系人只读视图/StatusProjector、transactional outbox/分层投递/current-head 恢复。
- 当前基线没有 Ticket 116 的安全裁决、诊断 scope/修订链、联系人警报消费链或专项测试；这是真实差额，不是重写前票的理由。
- Ticket 113、114、115 的专项基线分别为 `99/99`、`210/210`、`135/135`，现有绿色行为全部保留。

```text
已准入健康消息／受控命令
  -> Plugin
  -> HealthCore（唯一业务裁决与写入）
       -> 安全裁决／诊断权威／联系人 intent 内部 Module
       -> 既有受管状态 + current-head/writer-fence
       -> 既有 StrictHealthLLM controlled-effect Interface
       -> 既有 transactional outbox + StatusProjector
       -> 一项 Ticket 119 验收证据只读 Provider
  -> finalize 后的 Model / Owner-Weixin / Contact Adapter
```

Plugin/core 继续只暴露 health command、controlled effect 和 bounded managed read 三类业务 Interface。生产与 fake Model/Delivery Adapter 继续共用既有 Seam。安全规则、诊断规则和联系人规划留在 core 内部 Module，不变成第二业务入口。版本绑定的安全/诊断资产在 Core 构造时作为不可变受管依赖注入并完成启动校验；运行中没有写资产的命令。Ticket 119 隔离验收只增加一项只读证据 Provider，不增加新的业务写入口。

### 冻结的最小公共接缝

| 接缝 | 本票允许的最小形状 | 边界 |
|---|---|---|
| Core 构造依赖 | `safety_diagnostic_assets`；可选只读 `acceptance_evidence_provider` | 资产只在启动时验证并读取；Provider 只暴露 `read(receipt_ref) -> canonical fact | None`，没有发布、修改或激活方法。 |
| 既有主人入口 | `HealthPlugin.receive_weixin(...)` | 仍先做 admission；最低安全资产不可用时在读取正文前失败。 |
| 受管 health action | `safety.evaluate`、`safety.correct`、`diagnosis.prepare`、`diagnosis.commit`、`diagnosis.correct`、`diagnosis.activate` | 全部经过既有 `health_operation` authority/context；普通来源不能取得 Ticket 119 staged 例外。 |
| controlled effect | 既有 strict-model 执行接缝；`contact-alert.execute` | 只消费 Core 已形成的 effect intent/grant；Adapter 不参与裁决或写业务状态。 |
| bounded read/status | `managed_safety_diagnosis_read`；既有 `business_status` | 只返回本票公开 scope、判断、主人结果、安全事件和 typed status 投影；不暴露私有存储或正文。 |

受管 action 的公开最小 wire 固定如下；未列出的内部字段和编码不属于架构决定：

| action | 输入语义 | 输出语义 |
|---|---|---|
| `safety.evaluate` | causal ref、当前 safety bundle ref、确定性 safety facts；需要 alert 时可带事件时间与主人可识别称呼 | 唯一 `branch`、固定 `owner_result`、以及 `contact_alert` 或 `None` |
| `safety.correct` | 原 alert intent ref、依据变化 ref、纠正时间 | `contact_correction` 或 truthful no-send |
| `diagnosis.prepare` | causal/question/event/period/scope/current evidence refs；Ticket 119 例外只多一个 opaque run receipt ref | `rejected`，或 `model-ready` 加既有 strict-model request/effect intent |
| `diagnosis.commit` | causal ref、已终态 model effect ref；隔离验收时绑定同一 run receipt ref | `committed`/`replayed`/`unknown`/`rejected`，成功时返回 diagnosis ref |
| `diagnosis.correct` | current diagnosis ref、correction ref、时间、outcome 与 reason | `no-change` outcome 只返回 `no-change`；其余合法 outcome 追加后继并返回 `revised`，不原位覆盖 |
| `diagnosis.activate` | opaque run receipt ref 与 owner acceptance receipt ref | 原子 `committed` 或失败关闭，成功后 scope 为 `active` |
| `contact-alert.execute` | intent ref 与尝试/观察时间；执行权来自既有 effect grant | 分层 transport result；unknown 冻结重试 |

`contact_alert` 与 `contact_correction` 只有一种公开形状：`{intent_id, effect_intent}`；`effect_intent` 复用既有 `EffectIntent.to_wire_metadata()`。`managed_safety_diagnosis_read` 只公开 `scope`、`diagnoses`、`owner_results`、`safety_events` 与 `current_judgment_status` 这些本票观察面。上述名称和可观察语义由冻结验证文件约束；私有类型和实现文件仍可由编码 Agent 选择。若现有三类 Interface 无法承载其中一项，必须在写产品代码前返回冻结阶段，不能另建旁路业务入口。

## 冻结决定

| 方面 | 决定 |
|---|---|
| 权威 | HealthCore 仍是唯一业务裁决和写入者。安全 Module 独占五分支裁决；诊断 Module 独占 scope currentness、确定性 BMI 重算和修订链；联系人 Module 只消费 Ticket 114 的 current 联系人/方法/批准只读视图并提出 alert/correction intent；Ticket 115 outbox 独占投递事实。 |
| 安全优先级 | 一次处理只产生一个主分支：`safety-capability-unavailable` → `danger-escalation` → `danger-unknown` → `out-of-scope` → `in-scope`。低优先级不能覆盖高优先级；可信危险不运行诊断模型。固定主人结果来自当前、版本绑定且已批准的安全资产，不由 LLM 临场生成。 |
| 诊断范围 | 产品持久状态只区分 `staged` 与 `active`，但公开 effective phase 保留既有 `staged → activation-ready → acceptance-authorized → active` 语义：`activation-ready` 由当前权利、中文 bundle、审核、实现、安全和版本事实派生；`acceptance-authorized` 由当前有效的一次 run receipt 派生，二者都不是新 durable truth。普通健康入口只接受 `active`。Ticket 119 可在 durable staged 下做一次隔离验收，但 caller 只提交 opaque run/acceptance receipt ref；Core 通过一项只读 AcceptanceEvidenceProvider 取得 canonical 当前事实，验证同一 owner/release/bundle/generation/run/gate/expiry/diagnosis。有效 run 在模型 intent 形成事务内复用 health-command causal receipt/current-head 原子标记 consumed，失败、unknown、过期、漂移或重放不补发；不建立 acceptance ledger。只有同一 run 已完成诊断且 Provider 能证明真实主人验收 receipt，durable `active` 才与该证据引用原子同成。 |
| 三段门 | 模型前门在形成 model intent 前验证初始化、控制、head/fence、首跳同意、当前证据、容量、安全、知识和 scope；staged 例外只允许独立 Ticket 119 acceptance source/scope 携带 opaque run receipt ref，普通 diagnostic runtime 无法取得。模型后门只接受权威 completed、严格结构、当前引用和独立 BMI 重算一致的候选；提交前门再次读取 generation、控制、证据、bundle/route/同意和删除状态。 |
| 诊断记录 | 同一问题、事件和适用时期最多一个 current 判断。依据失效、主人纠正或范围失效时，旧判断先退出 current，再追加 revision/degrade/withdraw/replace 或 no-change 后继；权威 unknown 时旧判断和候选都不冒充 current。最终结构化记录保存语义和引用，不复制证据正文、模型草稿或完整回复。 |
| 事务 | 模型 intent 及诊断 revision、current 指针、主人结果 outbox、alert/correction intent 和 typed status facts 分别在其同一业务决定内复用 `prepared → current-head CAS/readback → local finalize`，必须同成同败。finalize 前不得调用任何外部 Adapter。 |
| 联系人与外发 | 固定主人求助提示不依赖联系人可用。联系人 current 且批准有效时才附加最小 alert；payload 只含主人可识别称呼、事件时间和固定求助语义。alert/correction 复用 Ticket 115 分层 ledger；unknown 冻结自动重试；纠正只追加给仍可证明的原接收身份和方法一次，不能覆盖原警报或改投新联系人。 |
| 停止记录 | 停止新增记录期间可以临时计算安全结果并形成获准的最小警报，但不持久化当前消息健康正文、个人证据、诊断、安全事件或新任务；只保留无正文防重复、批准引用和投递事实，恢复后不倒填。 |

BMI 使用 `height_m`（米）、`weight_kg`（千克）与 `BMI = weight_kg / height_m²`（kg/m²）。分类比较使用单位归一后的未显示舍入值；生产阈值、有效域、测量时效和排除语义只来自精确版本绑定且已审核的 bundle，合成 fixture 必须明确标记为非医学测试资料。

## 本票必须控制的五类现实故障

1. scope、bundle、证据、同意、控制、generation/fence、联系人或 route 在任一门或发送前漂移时失败关闭。
2. 安全规则不可用、危险未明、范围外、模型非 completed/结构错误或 BMI 重算不一致时，只形成对应权限内的 truthful 结果。
3. prepare、CAS/readback 或 finalize 崩溃/unknown 时只恢复原 transition 或停止，不部分可见、不提前外发。
4. 模型或投递可能已经产生外部效果但终态 unknown 时不自动重做；纠正仍受原接收身份、当前 authority 和一次性约束。
5. 重投、并发、重启和停止记录不能产生第二份当前判断、重复警报或隐藏健康正文。

## 兼容、实施自由与停止

保留 Tickets 110—115 的持久事实、Plugin/core Interface、StrictModelAdapter、`SupportContactSettings.consumer_view()`、StatusProjector、outbox wire、health-command receipt、current-head 和 writer-fence。联系人效果只能作为现有 delivery Module 的受权变体接入；旧 owner intent/wire 语义不变。AcceptanceEvidenceProvider 只有读权，不能激活范围、提交诊断或写验收事实；Ticket 119 负责其真实 Adapter 与外部证据，Ticket 116 只消费验证结果。没有 characterization 证明时不做数据迁移，也不整体重构 `HealthCore`。

内部字段名、私有 schema、hash/codec、helper、文件布局、内部 Module 组合和测试组织保持可逆。必须稳定的业务 action、opaque receipt 输入、bounded read/status 结果和构造依赖只以冻结验证合同实际使用的最小公开形状为准，不得增加测试专用 override。编码 Agent 只修复冻结验证合同已证明的红灯。只有现实触发链证明现有唯一写入、model-effect、outbox、联系人 consumer view、AcceptanceEvidenceProvider 或 status Seam 客观无法满足某项冻结不变量，且局部门禁不足时，才按治理规则申请重开架构；外部许可、医学审核和真实验收缺失只阻止激活，不扩张本票本地实现。
