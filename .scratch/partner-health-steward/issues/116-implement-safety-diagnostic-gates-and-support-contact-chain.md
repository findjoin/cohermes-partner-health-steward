# 116 - 实现安全诊断门禁与支持联系人链

Type: task
Status: ready-for-agent
Parent: [健康管家首发 TO、CAN 与 HOW 决策闭合路线](../map.md)
Blocked by: [113 - 实现 StrictHealthLLM 治理知识与非诊断回答](113-implement-strict-health-llm-governed-knowledge-and-nondiagnostic-answer.md), [114 - 实现主人设置数据权利与业务状态](114-implement-owner-settings-data-rights-and-business-status.md), [115 - 实现任务当地日复盘与分层主人投递](115-implement-tasks-local-day-review-and-layered-owner-delivery.md)

**What to build:** 让健康管家在非诊断回答之外拥有独立、确定性的最低安全和 staged 诊断路径，并在可信危险且主人批准有效时向唯一支持联系人生成最小警报。安全不可用、危险未明和范围外必须失败关闭；联系人外发不能替代给主人固定的求助提示。

**Blocked by:** 113 - 实现 StrictHealthLLM 治理知识与非诊断回答; 114 - 实现主人设置数据权利与业务状态; 115 - 实现任务当地日复盘与分层主人投递

- [ ] 安全不可用、可信危险、危险未明、范围外和范围内按固定优先级产生 truthful 结果；最低安全结果不依赖 Skill、steward 或医学范围可用。
- [ ] 首发 BMI 诊断范围保持 staged，只有内容权利、冻结中文 bundle、医学专业审核、实现兼容、安全审查和真实主人验收全部通过后才可激活。
- [ ] 诊断执行模型前、模型后、提交前三段门禁，独立重算确定性 BMI；同一问题/事件/时期最多一个 current 判断，依据失效或主人纠正先退出 current 再形成修订。
- [ ] 初始化披露一个当前支持联系人、方法、目的和最小警报，联系人/方法变化使旧批准失效且不配置备用联系人。
- [ ] 最小警报只含主人可识别称呼、事件时间和固定求助语义；不含诊断、原消息、症状、位置、画像、证据或模型草稿。
- [ ] 停止新增记录期间仍可临时判断危险和产生最小警报，但不得新增健康事件或健康正文，只保留无正文防重复和投递未知事实。
- [ ] 合成测试覆盖危险未明、能力不可用、范围失效、批准撤回、纠正、未知联系人投递和不盲重试。

## Implementation contract

### Start gate and authority to load

只在 Ticket 113、114、115 均 `resolved` 后开始。实现前必须读取：

- [当前实现 Spec](../spec.md)的“模型、知识、诊断与安全”“非诊断回答与诊断门禁”“支持联系人和投递”“Testing Decisions”；
- [当前 HOW 证据](../evidence/36-how-route-after-current-can-closure-20260822.md)的“Model, query, non-diagnostic answer, and medical route”“Support contact, deletion, and migration”与 validation boundary；
- [`CONTEXT.md`](../../../CONTEXT.md)中的“已激活诊断范围”“范围外诊断请求”“结构化诊断记录”“诊断判断修订链”“危险升级”“危险未明”“安全能力不可用”“最低安全结果优先级”“处方药边界”和“停止新增记录”；
- Ticket 111 的初始化联系人披露、`SupportContactBoundary` 和主人同意证据，Ticket 113 的 StrictHealthLLM/knowledge/non-diagnostic 合同、Ticket 114 的控制/状态事实、Ticket 115 的 outbox/交付账本，以最终已验收接口为准。

任一 blocker 未闭合时只能做只读审计；不得 claim、预先激活诊断范围、写临时安全文案或建立第二投递通道。

### Scope and ownership

本票完整拥有三个安全关键子系统，但整票统一验收：

1. 独立、确定性的最低安全裁决和固定主人结果；
2. staged BMI 诊断范围、模型前/后/提交前三段门禁及诊断修订链；
3. Ticket 114 单一支持联系人设置/批准的 currentness 校验、最小警报、纠正和分层投递接线。

本票不取得医学内容权利、不替代合格医学专业审核、不调用真实模型/联系人/微信，也不宣称 BMI 已激活。仓库缺少真实权利、冻结中文 bundle、专业审核、安全审查或主人验收时，真实 capability 不得为 `active`；其中原复选项的“保持 staged”是 **non-active staged family** 的总称：前置未齐为 `staged`，除主人验收外的精确前置齐全可为 `activation-ready`，取得一次隔离验收授权后可为 `acceptance-authorized`。合成 fixture 只能证明状态机可处理“全部前提成立”，不能把 fixture 结果写成当前批准事实。

为避免“必须先 active 才能验收、又必须先验收才可 active”的循环，non-active staged family 内的范围状态机必须区分：`staged` → `activation-ready`（精确 bundle 的权利/中文/审核/实现/安全门已通过但未取得主人验收）→ `acceptance-authorized`（主人针对精确 release/bundle 明确批准一次隔离验收），最终才可进入 `active`。`acceptance-authorized` 只允许 Ticket 119 的单次受控验收，不服务普通健康消息、不让 StatusProjector 显示 active；主人验收成功与 active transition 原子绑定，随后必须再验证一次 active-path。拒绝、失败或未知不进入 active。

优先把新职责放入聚焦模块，例如 `safety.py`、`diagnostics.py`、`contacts.py`；Ticket 113 的 model/knowledge 类型、Ticket 114 的 controls/status 类型和 Ticket 115 的 outbox/delivery 类型是唯一集成接缝。固定安全文案、规则、知识、诊断范围和模板必须作为版本化 hash-bound bundle，不散落为模型提示或无版本字符串。

### Required semantic contracts

- 安全裁决固定优先级：`safety-capability-unavailable` → `danger-escalation` → `danger-unknown` → `out-of-scope` → `in-scope`。每次只产生一个主分支，低优先级不能覆盖高优先级。身份、主人、私聊会话或唯一入口准入失败时不读取正文、不形成健康/安全结果、不回复、不联系联系人。
- 最低安全结果只在唯一消息准入成功且消息被接纳为健康/混合/无法确定后适用，不依赖 `health-steward` 或其他 Skill 可用。总路由不可用但非 Skill 安全边界可确定性确认危险时，仍生成固定主人提示，并在联系人、方法、route、generation、专门控制和批准全部当前时形成最小 alert intent；无法可靠确认危险时只给最低求助提示且不联系联系人。
- `MinimumHelpBundle` 是独立于诊断/危险规则的最小信任资产，包含固定通用求助模板并在 release/健康入口启动前校验版本、hash、中文状态、内容权利、批准审查状态和可解析性；缺失或任一项无法验证时不得注册/启动健康入口，状态为 `cannot-confirm`，也不得联系联系人。运行期 `safety-capability-unavailable` 专指诊断或确定性危险规则能力不可用，而已验证的 MinimumHelpBundle 仍存在，此时只渲染最低通用提示且不联系联系人。route/steward 故障但确定性危险规则仍 current 时，才可进入 danger 分支。其他安全文案同样由相应批准 bundle 的固定模板确定性渲染，不含个体化治疗、调药或模型临场生成内容。
- BMI 范围 registry 明确人群、包含/排除、最小输入、bundle/hash、权利、中文状态、专业审核、实现兼容、安全审查和主人验收；任何一项缺失、过期、撤回或无法确认都不是 active。
- BMI 计算合同明确 `height_m`（米）、`weight_kg`（千克）、`BMI = weight_kg / height_m²`（kg/m²）、输入有效域、测量发生时间/可靠性、年龄与妊娠排除字段、公式版本、比较精度和显示舍入。分类比较使用单位归一后的未显示舍入值；显示舍入不得改变阈值分支。生产阈值、测量时效与排除语义只来自精确 hash-bound 且已审核 bundle；synthetic bundle 使用明确标记的非医学测试阈值。
- 诊断模型前门禁验证初始化、控制、current head、首跳同意、最小当前证据、容量、安全、知识，以及 `active` scope；唯一例外是 core 签发的 `AcceptanceRunCapability`，它绑定 owner、release digest、bundle hash、generation、Ticket 119 run/gate ID、`issued_at_utc`、`expires_at_utc` 和单次消费状态，只能从隔离验收入口消费一次 `acceptance-authorized` scope，普通健康入口无取得或使用权。拒绝、失败、unknown、过期、重放或任一绑定 drift 后该 capability 终态失效且不能自动补发；主人验收成功才与 active transition 原子提交。模型后门禁只接受权威 completed、严格结构、当前证据、支持/反对/未知、紧急程度和独立 BMI 重算一致；提交前重读 generation、控制、证据、bundle hash、同意、scope/capability 和删除状态。
- 同一问题/事件/时期最多一个 current 判断。依据失效或纠正先让旧判断退出 current，再形成修订、降级、撤回或替代；模型重跑本身不是改判依据。
- in-scope 成功结果必须形成结构化诊断记录：当前判断、支持/反对证据、关键缺失、未知/不确定性、紧急程度、允许下一步、适用时期，以及精确 evidence/knowledge/safety/template/model capability/bundle 引用；core 从批准原子确定性渲染，模型草稿不成为最终记录或回复。
- 只允许消费 Ticket 114 的一个 current 支持联系人权威。批准绑定联系人身份、联系方法、用途、最小模板、route 和 generation；联系人或方法变化使旧批准失效，Ticket 116 无 grant/revise/revoke 写权。
- 主人固定求助提示永远不依赖联系人可用；联系人最小警报只含主人可识别称呼、事件时间和固定求助语义，不含诊断、原消息、症状、位置、画像、证据或草稿。
- 联系人交付复用 Ticket 115 的分层 ledger；可能已离站的 unknown 冻结重试。必要纠正只在原警报已经或可能离站，且原接收身份、方法、route 与纠正专用 authority 仍可证明 current 时，向原警报的同一联系人/方法追加一次；明确未离站不发送，旧批准/纠正 authority 撤回、联系人或方法变化、旧 route/generation 无法确认时记录 `correction-undeliverable`，既不发旧联系人也不转发新人，纠正 unknown 不重试。
- 停止新增记录期间只保留临时安全计算、固定主人结果、无正文防重复、批准引用和投递未知；不持久化当前消息健康正文、个人证据、诊断、安全事件或新任务。

### Acceptance matrix

| ID | Required observable result | Forbidden substitute | Required test evidence |
|---|---|---|---|
| 116-A1 | 准入成功后五分支按固定优先级产生唯一 truthful 结果；route/steward 故障且危险可确定时仍给固定主人提示并按当前批准形成最小联系人 intent，危险不可确定时不联系联系人；MinimumHelpBundle 缺失/权利或审查无效时入口不启动 | 未认证正文安全解析、关键词缺失=安全、模型裁决优先、Skill 故障吞提示、用失效模板回复或无可靠危险就触发联系人 | 每一分支、分支冲突、准入失败读取/回复/联系人全禁止、MinimumHelpBundle hash/中文/权利/审查启动前失败、运行期规则能力不可用，以及 route-down × danger-confirmed/unknown × approval current/invalid 测试 |
| 116-A2 | BMI registry 以 staged→activation-ready→acceptance-authorized→active 单向门禁绑定精确 release/bundle；当前仓库默认 staged | 合成测试、公开网页、模型自述、代码存在或 acceptance mode 冒充 active | 缺失/过期/撤回/错 hash/审核失效、状态非法跳转、授权一次性、主人拒绝/失败/unknown、active 原子提交和 synthetic 隔离测试 |
| 116-A3 | 模型前、模型后、提交前三门逐次重读当前事实；普通消息只接受 active scope，Ticket 119 隔离验收只接受精确绑定且一次性的 acceptance token；任一失败不形成诊断业务结果 | 一次预检通行到底、acceptance token 服务普通消息/重放、partial output、旧证据或旧 consent 提交 | 各门每个输入的 drift/unknown、scope/token 模式与一次消费、BMI 重算不一致、结构/终态错误和原子回滚测试 |
| 116-A4 | 诊断修订链始终保持至多一个 current；纠正/失效先退出旧 current 再形成合法后继 | 原位覆盖、多个 current、重跑模型直接替代或撤回=安全 | revision/degrade/withdraw/replace/no-change、主人异议、权威 unknown 和恢复测试 |
| 116-A5 | 主人固定提示与联系人附加警报独立；只消费 Ticket 114 绑定当前联系人/方法/route/generation 的 current 批准 | 无联系人时吞掉主人提示、预置联系人=批准、Ticket 116 自批或旧批准沿用 | 无联系人、联系人更换、方法变化、撤回、专门暂停、旧 generation、批准重放和消费者无写权测试 |
| 116-A6 | 最小警报只含三个允许字段，交付层级/unknown/纠正复用 Ticket 115 合同；纠正仅在原警报已/可能离站且原纠正 authority 仍 current 时向原接收者一次 | 症状/诊断/位置/原文/证据泄露、accepted=送达、明确未离站仍纠正、使用撤回/旧 authority、转发给新联系人或 unknown 自动重发 | 严格 schema、额外字段拒绝、unknown freeze、原 authority current/撤回、原接收者/更换联系人/route-generation drift/明确未离站、一次纠正和乱序/重复回交测试 |
| 116-A7 | 停止记录期间仍能给允许的临时最低安全/危险结果，但长期状态只留下无正文防重复和交付未知 | 写个人证据、诊断、安全事件、任务或恢复后倒填 | stop-recording 各分支、崩溃恢复、正文扫描、恢复后不倒填和旧 effect 去重测试 |
| 116-A8 | safety/diagnosis/contact typed facts 正确进入 StatusProjector；staged/失效范围不会让完整产品 active | 代码实现=active、一个无关单项故障让全局状态失真 | 最后范围 staged/失效、联系人不可用但主人安全可用、核心安全故障和 cannot-confirm 测试 |
| 116-A9 | in-scope 成功时原子形成完整结构化诊断修订和确定性主人结果，所有结论逐项引用当前证据/bundle | 只有 gate flags/revision ID、模型草稿直接回复、遗漏反对/未知/紧急程度/下一步 | 正向 schema、支持/反对/缺失/不确定性/紧急程度/下一步、引用 currentness、确定性渲染和原子提交测试 |

每个 `116-A*` 是功能 verdict；`Required test evidence` 中以顿号、斜线、逗号或“分别/每类/全分支”列出的每个场景都是独立 Case。实现前按出现顺序登记 `116-Ax-Cyy`，每个 Case 必须映射到可单独失败、测试输出可见的 test/subTest 和独立断言；不能用一个整体断言覆盖多个 Case。任何“all prerequisites pass”测试只能使用显式 synthetic fixture，完成条件是全部 Case `covered=green` 且没有当前 release/审核/主人验收事实被改写。

### TDD execution slices

每个 slice 固定执行：登记本 slice 全部 Case → 添加红测并确认预期失败 → 最小实现转绿 → 运行本 slice 与全部前置 slice 回归。测试按 slice 拆为 `tests/test_ticket116_safety.py`、`test_ticket116_scope_gates.py`、`test_ticket116_diagnosis.py`、`test_ticket116_contact.py` 和 `test_ticket116_integration.py`。

1. **Red safety table**：先在 `tests/test_ticket116_safety.py` 建立准入前不可读、五分支优先级、route-down 交叉矩阵、固定模板和非法信息外泄测试。完成标准：116-A1、A5、A6 的合同 Case 已登记并按预期失败。
2. **Deterministic minimum safety**：先实现并验证独立 MinimumHelpBundle 启动门，再实现危险规则 bundle、优先级和独立主人结果。完成标准：116-A1 通过；MinimumHelpBundle 缺失时入口不注册，运行期规则/Skill/模型故障时只有合同允许的固定最低结果。
3. **Staged scope and three gates**：实现四阶段 scope registry、带物理单位的 synthetic BMI bundle、独立重算和前/后/提交门。完成标准：116-A2、A3 通过，默认真实状态仍 staged，synthetic 阈值没有生产激活路径。
4. **Diagnostic revision authority**：实现完整正向诊断 schema/current 唯一性、确定性渲染、退出和后继链。完成标准：116-A4、A9 通过，权威 unknown 时无判断冒充 current。
5. **Support-contact chain**：消费/校验 Ticket 114 的单联系人批准，实现最小 alert intent、撤回/更换后的失败关闭、纠正和 Ticket 115 ledger 集成。完成标准：116-A5、A6 通过，无第二联系人批准真相，主人提示不受联系人失败影响。
6. **Stop-recording and status integration**：实现无正文临时安全边界和 typed facts。完成标准：116-A7、A8 通过，停止记录与 staged 范围不产生隐藏正文或虚假 active。
7. **Regression and review**：运行本票及全量验证，并进行安全重点的 Standards/Spec 双轴审查。完成标准：所有原始复选项和 116-A1—A9 有“测试 + 实现位置 + 结果”映射，外部权利/审核/验收仍真实标记，Ticket 保持 `claimed` 等待独立审查。

### Verification and stop conditions

交审至少运行：

- `python -m unittest discover -v -s tests -p "test_ticket116_*.py"`
- `python -m unittest discover -v`
- `python -m compileall -q partner_health_steward tests`
- `git diff --check`

列出并审查全部未跟踪文件，记录实际 Python/关键依赖版本。需要接受许可、医学签字、调用真实模型/联系人/微信、读取真实健康资料，或发现当前 BMI/安全路线不可实施时，立即停止并交还明确外部决定或 CAN 前提；不得伪造批准、用免责声明激活范围、降级安全验收或把合成证据冒充真实验收。实现 Agent 不得标记 `resolved`。

实施 Agent 在交审前于本票末尾追加 `## Implementation evidence (unreviewed)`，逐 Case 记录测试名、实现 symbol、命令/结果摘要和 diff/commit identity；独立 reviewer 才能写 `## Answer` 并决定是否 `resolved`。

