# 允许主人选择 JOJO 非诊断模型操作预算并公开上下文限制

状态：技术实现候选；产品范围与残余风险已由主人于 2026-10-18 明确接受。唯一后继为 [Ticket 131](../../.scratch/partner-health-steward/issues/131-support-explicit-nondiagnostic-model-operational-budget.md)。本记录不证明实现、G10/G11、真实模型调用或主人验收已经完成。

## 决定输入与事实

本会话主人明确选择继续使用当前 JOJO，接受仅用于非诊断、固定请求长度、禁止自动切换和自动重试、不完整即停止，并接受目前无法保证服务端完整接收请求上下文。此决定只接受所列残余风险，不是供应商容量或模型完整性的技术证明，也不是任意真实请求的批准。

对 default 当前 `jojo / gpt-5.6-sol / codex_responses` 的只读 characterization 仅做了一次已配置 HTTPS origin 的 `GET /models`，未推理、未发送健康输入、未访问 partner，禁跳转与环境代理。HTTP 200 的八条目录记录中，该 model 精确出现一次，但目标记录未提供共同上下文容量、tokenizer、实际可路由模型集合或相应证明来源。无正文观测摘要位于执行环境 `/tmp/dmit-connection-audit/default-model-metadata-evidence.json`；响应摘要为 `sha256:655deb102be66c3d49477d26b973dd56f51fd78b09acad5a8a97dc3dbdf3ddbc`，只定位这次目录观测，不证明能力。配置中的 `240000`、目录列出、少数 usage 或主人风险接受均不能成为 `proven common_context_lower_bound`。

## 已确认的产品边界与候选增量

在同一模型 Module 和同一 Core exact intent 内，后继可增加明确标识的 **非诊断模型操作预算**：对最终序列化 wire 的字节长度使用固定上限，同时限定输出预留，绑定当前 route、provider、requested model 和配置代际。数值、公开 codec、最小跨进程接缝与独立验证须在 Ticket 125 闭票、当前代码可 characterization 后由 Ticket 131 唯一设计冻结；本 ADR 不提前选择字段或另建预算／批准账本。

该预算只控制本地允许发送的请求范围，必须公开并记录“**不提供共同上下文保证**”。它不证明 tokenizer、服务端实际窗口、上游路由集合、完整接收或模型实际考虑了全部输入。即使收到 `completed`，也不能把这一限制写成已经消失；主人不能被告知“完整上下文已保证”。超预算请求停止，不静默截断、移除证据或拆成自动重试。

仅非诊断候选可使用此显式模式；七 Skill、typed 候选、证据准入、安全、治理知识、唯一提交和确定性回复继续有效。疾病排序、诊断标签、排除结论、个体化处方调整及 BMI 激活不能借此进入产品。既有严格 capability profile／可核验共同容量证明模式继续保留给 full／诊断，不能降低旧 Ticket 125 的冻结合同或把操作预算塞入严格 profile 的共同容量字段。

首跳同意、current head、writer fence、route/provider/model/config currentness、有效期和 exact request 绑定继续生效；Plugin 执行网络，Core 不持模型凭据或发起网络。禁止跨 provider/base URL 自动切换、隐藏工具、自动重试及发送未知后的重新调用。必须回交实际观察的 response identity、actual model、usage、完整 raw 终态和结构事实；actual model 未知时不得填成 requested model。`incomplete`、`failed`、不完整／畸形结果和 `unknown` 不提交候选；发送后失效仍保留真实 attempt／终态，不能改写成未调用。

## 与现行权威的关系

[ADR 0022](0022-select-current-health-steward-route-after-seven-skill-can-closure.md) 的唯一 Module、三类 CorePort、Core 业务权威、首跳隔离、无 fallback、治理知识、unknown 和医学激活边界保留。现行 Spec 的共同容量门与 Ticket 125 的严格模式继续如实有效。本次主人决定为非诊断提供一个公开较弱保证的后继输入；Ticket 131 冻结时必须在同一 Spec／验收 Module 中准确区分两种保证，不能静默删掉原容量要求，也不新增第二模型路由器、批准 ledger 或产品状态。

部署仍在 Ticket 128 的 default 阶段 A；full／诊断仍受严格证明及 Ticket 127 的医学权利、审核和真实验收门禁。产品取舍不等于 G10/G11 passed，不替代同一 target/release/run/config 的实际验证和批准。凭据、完整配置、响应 body 和健康资料不进入本记录。

## 重新评估触发条件

主人要求诊断／完整首发、供应商给出可核验容量／tokenizer／实际模型依据、首跳或配置代际变化、预算失效、实际终态或 usage 无法确认时，按相应现有门重新判断。非诊断操作预算不会自动升级成严格证明模式。
