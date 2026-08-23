# 健康管家首发 TO、CAN 与 HOW 决策闭合路线

Type: wayfinder:map

## Destination

在目标 Partner Hermes 中实际部署并稳健运行一个健康管家 Plugin。插件固定承担两项核心职责：为唯一真实主人维护一份长期、可追溯且由主人控制的健康画像；依据当前健康画像与会话信息，自动生成、安排、派发并跟踪健康任务。健康任务可以用于需关注事项、提醒、完善健康画像、受隐私边界约束的搜索以及以后由 TO 明确的其他健康目的，而不是只限于定时提醒。

产品要把分散的健康信息持续转化为主人可控制、可追溯的健康理解与行动，让主人得到有依据的回答、判断、问题和支持。具体主人可见结果、产品边界、失败结果与首发成功条件由本 Map 的【TO】Tickets 闭合；【CAN】只核验现实能力与约束，【HOW】只在完整 TO/CAN 后选择并落实达到该部署结果的路线。

## Notes

- 每次显式调用 `$wayfinder` 并传入本 Map 时，必须先从磁盘完整重读当前 `map.md` 的五个顶层部分和全部 Notes，不得用先前对话、摘要或记忆中的 Map 代替；完成读取后才能查询 Frontier、认领 Ticket 或修改票据。每次工作同时读取 [`CONTEXT.md`](../../CONTEXT.md)：`Destination` 定义最终抵达点，`CONTEXT.md` 维护技术无关的现行领域语言与产品边界；`健康画像` 是统一领域词，历史票中的旧称“健康档案”仍指同一对象。
- 本 Map 是唯一权威 Wayfinder Map，并保留 `Destination`、`Notes`、`Decisions so far`、`Not yet specified`、`Out of scope` 五个原生顶层部分。Map 只是索引，不保存完整决定或阶段报告；完整内容只存在于对应 Ticket 的 `## Answer` 或其明确链接的派生资产中，Map 只写一行 gist 与链接。
- `issues/` 中缺少当前原生 `Type:`、`Status:`、`Parent:`、`Blocked by:` 与 `## Question` 元数据的旧 Markdown 只作为历史实施证据保留，不参与当前 Frontier、依赖、决定或完成状态；已经标为 `wontfix` 或被取代的规划票同样不得恢复为当前权威。需要复用其中事实时，必须由当前 Ticket 明确引用并重新判定其证据边界，不能靠旧标题或旧完成勾选取得权威。
- `Destination` 固定 Partner Hermes 中的 Plugin 产品载体、稳健运行结果、健康画像与健康任务两项核心职责，以及把分散健康信息转化为主人可控制且可追溯的理解与行动这一价值；完整【TO】继续拥有具体产品结果、边界、不变量、失败结果和成功条件，【CAN】和【HOW】不得反向替代或缩小。实现与目标 Hermes 部署仍在本努力的抵达范围内，但关闭 TO、CAN、HOW 或交接 Spec 都只是中间条件；到达显式 Matt 阶段边界时必须停止，等待主人启动下一流程，所有后续产物继续返回同一条权威链。
- `【TO】`、`【CAN】`、`【HOW】` 表示 Ticket 实际 `Question` 的性质；`research`、`prototype`、`grilling`、`task` 表示解决该 Question 的原生 `Type`。两者完全正交，任一 TO、CAN 或 HOW 都可以按问题需要使用任一原生 Type。每张 Ticket 只能有一个性质前缀；不新增 `Stage:`、混合 `TO-CAN`、新 Type、新 Status 或第二套 Frontier。
- 本 Map 另外执行项目级工作门禁 `TO → CAN → HOW`。门禁通过原生 `Blocked by`、Ticket 状态和延迟出票落实，不靠新的脚本、字段或 Frontier 算法；后继阶段只有在前一阶段的闭合 Ticket 已 `resolved` 后才能工作或解决。
- 完整 TO 原已由[【TO】闭合首发健康管家的完整产品合同与成功条件](issues/75-close-first-release-health-steward-product-contract.md)闭合，完整 CAN 原已由[【CAN】闭合完整能力与约束事实并形成当前 CAN 报告](issues/77-close-complete-capability-and-constraint-report.md)审计 C01—C17，旧统一 HOW [【HOW】选择健康管家的统一技术路线、权威职责与分层验证架构](issues/98-choose-unified-health-steward-technical-route-and-authority-architecture.md)已因后继 TO 变更失效。后继的[【TO】确定健康 Skill 的必经使用、主人可见披露与回复结果](issues/99-define-required-health-skill-use-visible-disclosure-and-reply-contract.md)、[【TO】确定七个健康 Skill 的主人交互入口、文档结构与能力边界](issues/100-define-seven-health-skill-interaction-entry-document-and-capability-boundaries.md)与[【TO】确定危险升级时主人提示、预设支持联系人通知、记录与失败结果](issues/101-define-danger-escalation-owner-prompt-and-support-contact-alert-contract.md)实质改变了 Skill 交互、接收方、安全和失败合同；[【CAN】重建七个健康 Skill 交互合同后的完整能力链与追溯关系](issues/102-rebuild-complete-capability-chain-after-seven-health-skill-interaction-contract.md)和[【CAN】闭合七个健康 Skill 与支持联系人重建后的当前 CAN 能力与约束审计](issues/108-close-current-can-after-seven-skill-contact-investigations.md)已完成当前 TO/CAN 交接，HOW 109 现已闭合并形成新的路线权威。开放票与当前 Frontier 只通过本地 tracker 查询，实施与验收 Spec 继续暂停。
- 一个可出票的 `Question` 必须明确对应的目标或上游节点、要解决的决定或事实、直接前提、可判定的解决条件，并能在一个 Ticket 会话内完成。问题尚不能如此准确表述时留在 `Not yet specified`，不得用宽泛标题预生成空票。对 HOW 而言，只有 CAN 已给出有证据的候选能力与约束后，其技术路线问题才算准确；CAN 闭合前不生成、认领或解决 HOW Ticket。

- `【TO】Target Outcome` 必须先完整对齐这个产品最终要成为什么样，包括目标、价值、产品功能、主人可见结果、必须成立的边界与不变量、失败结果和成功条件。除 Destination 已固定的产品载体、核心职责与价值外，TO 不得选择或预写候选工具、供应商、版本、接口、存储、算法、模块职责、部署方法或其他技术细节，也不得让当前工具能力静默缩小目标。
- TO 的 HITL 对齐必须以具体场景和实例为主要方法，不得先用主人尚未理解的抽象术语、分类名或数据结构要求主人确认。每个根决定先用至少一个贴近产品使用的例子说明触发信息、健康管家应做什么、主人会看到什么、哪些内容会被记录或形成任务，以及什么结果不得发生；边界容易混淆时使用对照场景。句式不必固定为“当……时……”，但必须让主人能够按真实场景选择或纠正；主人确认场景含义后，AI 才能归纳规范术语并写回 Ticket 与 `CONTEXT.md`。主人一旦表示没有听懂，相关问题及基于该问题作出的先前选择立即回到未决定，不能继续据此推导、关闭 Ticket 或写入 Map 决定摘要。
- TO 阶段可以使用全部原生 Type；科学、法律或领域事实也可以由 `Type: research` 的【TO】Ticket 支撑。只有当全部 TO Tickets 已解决、产品目标相关 fog 已清空，并由一张 HITL TO 闭合 Ticket 经主人确认后，TO 阶段才闭合。该 Ticket 的 `## Answer` 或链接资产形成一份不含技术选型与实现细节的完整产品报告；Map 只索引其摘要。
- 已确认 TO 只要发生会改变目标、价值、产品功能、主人可见结果、边界、不变量、失败结果或成功条件的实质变更，就必须由后继 TO Ticket 重新闭合；纯标题修正或 Question 的等价重述不算实质变更。新 TO 经主人确认后，先前 CAN 闭合状态自动失效，必须新建一张后继【CAN】能力链拆分 Ticket，针对完整的最新 TO 重新生成或重审全部技术能力链、节点依赖和追溯关系，不能只补改动的局部节点。旧能力链、CAN 证据和 HOW 决定保留为历史输入，但必须逐项标明仍可继承、需要重查或已经失效；新的 CAN 闭合完成前，任何受影响 HOW 都必须暂停且不得继续冒充当前权威。

- `【CAN】Capability and Constraint Facts` 只在 TO 闭合后调查真实世界当前允许什么、限制什么、已经证明什么和尚未证明什么。进入 CAN 阶段的第一张当前权威 CAN Ticket 必须把完整 TO 的每项目标、结果、边界、不变量和成功条件拆分为可调查的技术能力链，建立 TO 节点到能力链的追溯关系、链内依赖和每个节点所需证明的事实；这是调查结构，不是实现组合或技术选型。
- CAN 能力链拆分 Ticket 必须检查全部 TO 节点。解决该票时，AI 为已经能够准确表述的能力节点创建并连接同一 Map 下的 CAN Tickets；尚不能形成准确调查问题的节点留在 `Not yet specified`，不得编造技术链。后续 CAN 结果暴露缺失链条时，AI 继续创建后继 CAN 拆分或调查 Ticket，并保留旧 Answer 作为历史输入。
- 能力节点是 TO 追溯和完整性审计的单位，不等于必须“一节点一调查票”。若多个节点共享同一候选技术表面、证据链与代表性场景，并且能够在一个 Ticket 会话内逐节点给出可判定结论，应优先用最少的连贯 CAN Tickets 合并调查；只有候选边界、直接前提、实验批准、研究轮次或完成条件实质独立时才拆票。合并不得删除节点、隐藏负向结果、重置研究轮次或提前选择 HOW。
- 每张 CAN Ticket 必须指明其服务的 TO 节点、能力链节点、本轮调查的候选平台、工具、接口或能力、需要证明的事实以及证据边界。CAN 结论只报告候选的已证明能力、限制、未知项及其能否支撑相应 TO；区分官方保证、固定源码、目标现场和获准实验，不推荐、不承诺也不选择最终工具、接口组合或 HOW 路线。CAN 同样可以使用全部原生 Type。
- **CAN 防循环：**CAN 把 TO 的最终成功条件转换成可实施性事实、硬约束、外部前提和未来验证义务，不要求尚未实现的健康管家已经部署、初始化、激活或通过产品级验收。例如画像更新功能尚未编写时，CAN 应核验 Hermes 是否存在可承载它的扩展面、受管状态与安全边界，并记录 HOW、实现和验收必须完成的条件；不能仅因当前没有该功能就判定路线不可行。
- TO 中“至少一个诊断范围通过全部门槛并由真实主人微信验收”仍是完整上线硬条件。CAN 对内容使用权、中文来源版本、医学专业审核和范围验收只核验适用要求、候选取得或审核入口、现实限制、已知 No-Go 与验证可观察性；HOW 选择具体来源许可、审核和验收路线，之后才对实际工件取得授权、完成专业审核与产品验收。找到申请页、审核入口或验收场景分别不等于已经取得授权、通过审核或完成验收，尚未执行这些后继工作本身也不是负向 CAN。
- 单个候选得到负向 CAN 时，默认保持 TO，先由 AI 判断失败属于候选能力、能力链拆分还是更根本的可行性问题；优先在 CAN 内重构能力链并调查实质不同的替代候选，不得自动降低目标。研究次数绑定同一个 TO 节点，不能通过改名、拆票或改能力链重置；普通搜索、补引用、工具故障或同一证据改写不计为新一轮。
- 只有一条实质不同的候选能力或支持路线被一手证据排除，才形成负向 CAN 并计入研究轮次。更换病种却重复“健康 Plugin 尚未实现、项目许可尚未取得、医学审核尚未执行、产品尚未验收”等共同后继缺口，不构成新的候选路线，也不计新一轮；这些结果应记录为 HOW、实现或上线前的硬门槛。只有会实质改变 HOW 是否存在可实施路线的未知，或已经排除候选支持路线的事实，才能继续阻塞 CAN 闭合。
- 同一 TO 节点在能力链调整后累计三张实质不同、证据完整且 `resolved` 的负向 CAN Research Tickets，仍没有可靠支持方案时，AI 必须在开启第四轮研究前停止并向主人提交可行性说明：列出失败原因、已排除路线、剩余可能性、继续研究的价值以及可能需要修改的 TO 和影响；由主人决定保持、改变或放弃 TO。若证据已提前证明根本矛盾，可以早于三轮上报；AI 永远不得自行修改 TO。
- 只有全部 TO 节点都已映射到能力链、相关能力事实与未知边界已闭合、没有未处理的 CAN fog，并由一张 CAN 闭合 Ticket 完成审计后，CAN 阶段才闭合。其 `## Answer` 或链接资产形成完整 CAN 报告，描述调查过的候选、证据、能力、限制、未知项和对 TO 的覆盖，不描述“最终要使用什么”，Map 只索引其摘要。

- `【HOW】Chosen Approach` 只在 CAN 阶段闭合后生成和解决。HOW 根据完整 TO 与 CAN 已证明的能力和约束，自行选择技术路线、工具与平台组合、所用接口、设计职责、验证方法和实施依赖；不得借 HOW 重新改写产品承诺，也不得把未验证候选冒充可用能力。HOW 可以使用全部原生 Type。
- HOW 若暴露新的产品目标、边界或风险接受取舍，立即暂停并建立后继 TO；若暴露缺失能力事实，立即暂停并回到 CAN。TO 被主人改变后，所有受影响的 CAN/HOW 必须重新审计和接线；旧 Ticket 与旧证据保留为历史输入，但失效决定不得继续冒充当前权威。

- Research Ticket 必须在同一 Map 下保存可定位、带引用的 Markdown 证据，在 Ticket 中追加 `## Answer`，并通过 `Blocked by` 连接其直接前提与后继决定。静态证据不得冒充真实主人微信、真实模型、故障注入或破坏性实验；这些实验必须另行取得主人批准。

## Decisions so far

<!-- 这里只索引真正解决的当前 Ticket；标题前缀按实际 Question 性质分类。 -->

### TO

- [【TO】闭合首发健康管家的完整产品合同与成功条件](issues/75-close-first-release-health-steward-product-contract.md) — 主人以八个真实旅程场景整体确认：首发是初始化后才启动的单人专用健康 Plugin，以紧凑六域画像、三类证据、四项流程职责和自动健康任务共同提供问答、范围内辅助诊断、每日复盘、主动支持、数据权利与真实三态结果；完整上线至少包含一个通过全部门槛并由真实主人微信验收的诊断范围，失败、未知、删除、信任与不承诺边界均已闭合。
- [【TO】确认首发健康管家的基础产品能力与不可妥协边界](issues/53-confirm-foundational-product-capabilities-and-boundaries.md) — 首发服务单人专用 Hermes 的唯一画像主人，并提供可发现入口、自然聊天、辅助诊断、每日复盘、可追踪补问、数据权利、安全边界和真实主人微信验收；其原七域画像导航后来由后继健康任务合同修订为六域，原恢复准备条款由后继信任边界合同取代，其他基础结果继续有效且不得因当前工具而降低。
- [【TO】确定健康任务的自动生成、派发与生命周期合同](issues/73-define-health-task-generation-dispatch-and-lifecycle-contract.md) — 健康任务以支持同一六域健康画像及证据为共同使命，按明确目的和验收自动建档，由任务框架与画像维护、证据维护、主人询问、文献查找四项职责推进；固定简洁任务卡、四标签、范围批准、未知不盲重试、主人控制与数据权利，并在暂停、停止记录、删除及全局三态下保持真实可追溯结果。
- [【TO】确认首次主人绑定、消息准入与首发信任边界](issues/74-confirm-owner-binding-message-admission-and-trust-boundary.md) — 单人专用 Hermes 的唯一私聊准入使用者即为画像主人，产品不核验现实身份；健康管家仅在初始化成功后启动，启动后健康、混合及无法排除健康风险的消息不得回退普通聊天，重投歧义与未知结果不得盲目重复；长期权威状态显式存在文档、画像、证据、任务、控制记录与 Skill 中，不依赖 LLM 记忆；不承诺对抗恶意最高权限主体。该决定取代旧聊天身份迁移、一次性恢复权、不可恢复锁定及身份防回滚上线 No-Go。
- [【TO】确定主人永久删除健康画像的产品结果与边界](issues/39-define-permanent-deletion-backup-promise.md) — 主人要求永久删除后，全部受管健康画像内容不再可读取、推断、复盘、主动联系或恢复；产品不增加倒计时、回执、失联自动清理或管理员代删承诺。
- [【TO】确定健康管家诊断性判断与持证医生正式诊断的责任边界](issues/40-define-diagnostic-physician-handoff-boundary.md) — 首发不接入医生工作流；健康管家可给出带不确定性的 AI 辅助诊断，主人可提供有来源和时间的医生结论，健康画像始终区分 AI 推断与正式医学诊断。
- [【TO】确定稳定运行及主人可见运行状态的产品承诺](issues/41-define-stable-operation-observation-promise.md) — 稳定运行不由固定观察天数定义；主人可查询“活跃、异常、无法确认”、最近确认时间和受影响能力，并只在转为非活跃或恢复时各收到一次不含健康正文的通知。
- [【TO】核验生理与心理健康画像的科学结构](issues/54-research-scientific-health-portrait-structure.md) — 一手科学框架没有给出可直接照搬的完整 AI 健康画像标准；研究形成覆盖临床事实、身心体验、功能参与、行为环境、主人目标及来源、时间、不确定性分层的单一长期画像结构，并由后继基础产品合同纳入最终 TO。
- [【TO】决定健康模型接收方锁定缺口下的产品承诺边界](issues/58-decide-health-model-recipient-lock-gap-boundary.md) — 健康 Plugin 使用同一 Hermes 当前配置的首跳模型服务路线及其正常内部路由与故障切换；只有首跳路线变化才暂停健康处理并重新取得同意，不要求事前枚举或逐次披露服务内部全部最终下游。
- [【TO】决定医学来源缺口下是否保留辅助诊断目标及上线边界](issues/60-decide-medical-source-gap-boundary.md) — 保留同一 Hermes 提供有依据的 AI 辅助诊断；在取得内容使用权、建立实际诊断范围对应的中文来源与版本清单并完成相应资质的医学专业审核前，该能力不得通过验收或上线。
- [【TO】确定辅助诊断覆盖、范围外行为与安全未知或故障时的主人可见结果](issues/64-define-diagnostic-scope-and-safe-unavailable-result.md) — 辅助诊断仅在逐项闭合内容权利、中文来源版本、医学审核和产品验收的可查询范围内启用；归属不确定、存在重要范围外方向或准入失效时停止个体诊断，危险升级优先，危险未明只作最小安全澄清，安全能力不可用时仅发送非个性化最低求助提示并失败关闭。
- [【TO】确定辅助诊断中的个人证据最小化、外部医学接收方与持久保留边界](issues/65-define-diagnostic-evidence-recipients-and-retention-boundary.md) — 每次诊断只使用目的限定、默认排除且实质相关的最小个人资料；路线外不得发送主人派生医学查询，长期只保留受管的结构化诊断或安全结果、最小证据和不含回复正文的交付事实，不保存原始提示、模型草稿、整份外部记录或完整回复，停止新增记录时也不得新增长期健康内容。
- [【TO】确定诊断性判断的变更、纠正与可追溯产品合同](issues/66-define-diagnostic-judgment-change-and-traceability-contract.md) — 同一健康问题、事件和适用时期只形成一条可追溯修订链，并至多有一个可证明的当前 AI 判断；只有实质依据变化或已确认缺陷才能改判，依据失效即退出当前，旧判断不得原位覆盖，主人纠正或异议、必要纠错、状态无法确认及永久删除边界均保持可见。
- [【TO】确定辅助诊断上下文不完整、超限或截断时的产品结果与上线边界](issues/70-decide-diagnostic-launch-boundary-under-unverifiable-context-capacity.md) — 只有能够证明必要个人上下文和完整输出均未缺失或截断时才可形成诊断结果；否则该次诊断明确不可用且不保存、不发送部分结果。完整首发必须至少有一个诊断范围通过全部产品门槛与真实主人验收，零诊断范围不得冒充完整上线。
- [【TO】确定健康 Skill 的必经使用、主人可见披露与回复结果](issues/99-define-required-health-skill-use-visible-disclosure-and-reply-contract.md) — 初始化须真实使用获准 `health-init` 并在全部步骤成功后形成持续启用事实，初始化后的普通健康处理须真实使用 `health-steward` 和本轮必要职责 Skill；系统按可证明事实显示实际使用，处理前无法证明必需 Skill 时不形成普通结果，业务已提交但披露或交付未知时不盲目重做，并只保留最小使用事实。后继七 Skill 交互合同只为不可被 Skill 故障吞掉的最低安全结果增加窄例外。
- [【TO】确定七个健康 Skill 的主人交互入口、文档结构与能力边界](issues/100-define-seven-health-skill-interaction-entry-document-and-capability-boundaries.md) — 固定三项主人可发现 Skill 与四项内部职责 Skill、每项主合同及目的最小上下文，以消息粗分流和 `health-steward` 完整路由统一协调候选、权威提交、主人回复与真实披露；画像／证据／任务／设置结构、旧 `medical` 退出及 Skill 不可用时的最低安全例外均已闭合。
- [【TO】确定危险升级时主人提示、预设支持联系人通知、记录与失败结果](issues/101-define-danger-escalation-owner-prompt-and-support-contact-alert-contract.md) — 只有可信证据成立危险升级时，系统才在固定主人紧急提示之外向单个预置且经主人启用的支持联系人发送不含诊断、原话、症状、位置、画像或证据的最小警报；联系人无画像权利，失败／未知不盲重发、不自动换人，必要纠正、独立控制、停止记录、最小留存与永久删除边界均已闭合，该新增接收方仍待后继 CAN/HOW 重审而非已经实现。

### CAN

- [【CAN】重建完整 TO 的能力链与追溯关系](issues/76-rebuild-complete-to-capability-chain-and-traceability.md) — 2026-08-20 旧 TO 曾拆为 C01—C17 并建立当时的双向追溯；七 Skill 与支持联系人合同生效后，该十七节点链不再是当前完整能力链，仅作为[【CAN】重建七个健康 Skill 交互合同后的完整能力链与追溯关系](issues/102-rebuild-complete-capability-chain-after-seven-health-skill-interaction-contract.md)的历史输入。
- [【CAN】按连贯技术问题压缩并重接剩余能力调查](issues/94-consolidate-current-can-investigations-by-coherent-route.md) — 2026-08-20 旧 TO 下曾把 C01—C17 的剩余调查压缩为三张连贯票；其调查粒度与依赖已被最新 K01—K21 链和五张后继调查票取代，旧票只保留为历史编排输入。
- [【CAN】核验当前 Partner Hermes 基线、Plugin 生命周期与可信执行边界](issues/78-verify-current-partner-hermes-baseline-plugin-lifecycle-and-trust-boundary.md) — 2026-08-20 现场仍为带定制的 Hermes v0.20.0 / `3c27eb…` root 基座：原生 Plugin 扩展与基础资产枚举能力存在，但健康 Plugin/Cron 尚不存在，加载、Hook/Middleware、卸载、权限与日志也不保证失败关闭或隔离，完整权威资产迁移闭包仍未证明。
- [【CAN】核验健康能力入口、初始化门禁与真实结果返回能力](issues/79-verify-health-capability-entry-initialization-gate-and-result-contract.md) — 当前 Hermes 提供 Skill、Tool/Command、Platform、自然语言和内部调用承载面；通用入口及历史候选不天然保证旁路收敛、完整初始化、权威业务结果或主人实际到达。正式 Partner 尚无健康入口是待实现状态，固定源码限制和未执行 canary 构成 HOW 约束与未来验证义务，不单独证明路线不可行。
- [【CAN】核验唯一微信准入、排他分流、逐次来源与重投结果能力](issues/80-verify-unique-weixin-admission-routing-provenance-and-replay-results.md) — 当前 Weixin 静态配置已收敛为单值私聊 allowlist、关闭全开放且 `group_policy=disabled`，同时仍有 Telegram configured/enabled；内置路径在准入前读取正文并去重、在业务前推进 cursor、合批丢失后续来源，接口成功也不证明主人看到。这些确定性事实约束入口接管、重投和交付 HOW；健康 Plugin 尚不存在只形成实现义务。
- [【CAN】核验受管健康状态数据平面、保护隔离与单一权威能力](issues/81-verify-managed-health-state-plane-protection-and-single-authority.md) — 固定栈具有 Plugin、标准 SQLite、密码学库与一般 systemd 候选原语；未部署旧候选的明文投影、跨文件非原子和恢复闭包不完整是 HOW 必须避开的反例。正式 Partner 尚无受管健康状态不等于平台无可实施路线，后继需选择并验证完整对象、唯一引用、崩溃恢复、单一当前权威与副本闭包。
- [【CAN】核验紧凑六域健康画像与三类证据卡的维护追溯能力](issues/82-verify-six-domain-portrait-and-three-class-evidence-capabilities.md) — 现行六域画像与三类证据语义已可准确验收，未部署旧 sidecar 只提供局部证据、版本和当前指针原语；其旧四类结论、三种个人来源、独立资料库和字符串引用不能直接继承。正式 Partner 尚未实现这些对象是后继设计与验证义务，不是功能测试失败。
- [【CAN】核验首跳模型路线、主人派生查询隔离与非诊断健康问答结果链](issues/85-verify-first-hop-model-route-and-owner-derived-query-isolation.md) — 当前配置可定位名义首跳；旧候选按主人消息触发路线外资料回源是必须排除的确定性反例，跨首跳 fallback、同意约束、非诊断输出、安全交接、最小留存、业务提交和真实到达均形成 HOW 约束或未来验证义务。正式 Partner 尚无受管健康问答链本身不是不可行证明。
- [【CAN】核验明确诊断范围候选形成、准入与诊断全链能力](issues/86-verify-medical-content-governance-and-diagnostic-scope-candidates.md) — 国家卫健委 2024 中文指南足以形成“成人可靠身高体重条件下仅基于 BMI 的超重、肥胖及程度辅助分类”审计候选，并暴露内容再利用、版本退出、专业审核、资料完整性、安全与修订要求；尚未取得授权、实现、审核、验收或激活属于后继硬门槛，不再作为完整 CAN 闭合阻塞或负向研究轮次。
- [【CAN】核验成人疑似原发性高血压规范测量确认与同日转诊分流的完整诊断链](issues/95-verify-adult-hypertension-measurement-confirmation-and-urgent-referral-chain.md) — 跨日/跨场景血压确认、来源规则差异、严重数值—急性症状/体征分流及判断修订事实继续约束未来路线；项目许可、医学审核、实现、验收与激活尚未发生，不再被归类为第二条不可行路线，也不要求继续更换病种才能闭合 CAN。
- [【CAN】核验健康任务与受管运行框架的生命周期、复盘投递、主人控制、三态观测及迁移能力](issues/83-verify-open-health-task-lifecycle-dispatch-acceptance-and-scope-approval.md) — 旧候选已有任务、当地日、投递未知、控制、组件监控和字节恢复的局部原语；暂停或停止记录直接取消任务、删除附加倒计时与回执、验收阻塞仍报告服务健康、恢复只覆盖主状态 blob 等确定性反例约束 HOW。正式 Partner 尚未实现统一受管运行框架只形成后继实现与验证义务。
- [【CAN】修正未实现系统的能力判定、诊断范围门禁与负向研究计数](issues/97-correct-can-preimplementation-feasibility-and-diagnostic-scope-gate.md) — 修正“未实现 → 零激活范围 → CAN 不能闭合”的阶段循环：CAN 判断是否已有足够事实支撑一条可交给 HOW 选择的实施路线，不验收已工作的产品；BMI 与高血压事实保留为路线约束，但不计负向轮次，第三个病种调查停止。
- [【CAN】闭合完整能力与约束事实并形成当前 CAN 报告](issues/77-close-complete-capability-and-constraint-report.md) — 2026-08-20 旧 TO 下的 C01—C17 报告；在七 Skill 与支持联系人 TO 实质变更后，已失效为当前完整 CAN 权威，只保留为历史事实索引。
- [【CAN】重建七个健康 Skill 交互合同后的完整能力链与追溯关系](issues/102-rebuild-complete-capability-chain-after-seven-health-skill-interaction-contract.md) — 最新完整 TO 已归一为 T01—T36 并双向追溯到 K01—K21；旧 C01—C17、Evidence 01—29、旧统一 HOW 与 ADR 0021 已逐项完成有界继承／重查／失效分类，后继压缩为 Skill 与权威底座、路由与独立最低安全、受管领域状态、模型／医学／诊断、支持联系人五张连续 CAN 调查票，并由后继闭合审计票完成当前 CAN 交接。
- [【CAN】闭合七个健康 Skill 与支持联系人重建后的当前 CAN 能力与约束审计](issues/108-close-current-can-after-seven-skill-contact-investigations.md) — Ticket 102 的 T01—T36／K01—K21 追溯、Evidence 30—34 的四类证据边界和五张连续调查已闭合；现有事实支持至少一类没有已知根本矛盾的可实施空间，后继技术路线选择转入新的 HOW Frontier，旧 Ticket 98 与 ADR 0021 仅保留为历史候选。
- [【CAN】核验当前 Partner、七个健康 Skill 资产加载与受管权威底座](issues/103-verify-current-partner-seven-health-skill-assets-loading-and-managed-authority-foundation.md) — 仓库仅证明历史候选资产与固定 Hermes 扩展表面；七 Skill 当前运行资产、实际加载/使用、旧 `medical` 物理隔离和统一受管权威仍需现场重核，未实现不等于平台不可行。
- [【CAN】核验唯一准入、两级健康路由、职责组合、权威结果与独立最低安全能力](issues/104-verify-admission-two-stage-routing-duty-composition-authoritative-result-and-minimum-safety.md) — 固定入口与 Skill 扩展原语存在，但唯一准入、初始化门禁、两级路由、steward 职责组合、权威提交、唯一回复和独立最低安全结果仍未实现或未证明；历史现场与候选需重核或已失效。
- [【CAN】核验受管领域状态、任务时序、主人控制、删除、观测与迁移能力](issues/105-verify-managed-domain-state-tasks-controls-local-day-deletion-observation-and-migration.md) — 固定原语和局部历史机制可有界继承；当前六域状态、三类证据、任务控制、业务三态、全对象删除防复活与完整迁移闭包仍未实现或未证明，模型／诊断与联系人专属对象交给后继调查。
- [【CAN】核验首跳路线、查询隔离、医学治理、诊断完整性、安全与修订能力](issues/106-verify-first-hop-query-isolation-medical-governance-diagnostic-integrity-safety-and-revision.md) — 固定扩展面和历史医学候选可有界继承；当前首跳同意与出站隔离、医学权利/审核/范围激活、诊断完整终态、可信危险治理、修订链及诊断侧删除/观测/迁移均未实现或未证明，联系人对象交给后继调查。
- [【CAN】核验危险支持联系人的批准、最小警报、分层交付、纠正、删除与防复活能力](issues/107-verify-support-contact-approval-minimal-alert-delivery-correction-deletion-and-non-resurrection.md) — 产品合同已固定单一联系人、主人批准、可信危险门、最小警报、分层交付、未知冻结、必要纠正、独立控制和删除边界；当前 Partner 仅有有限平台/历史传输与删除原语，K16、K17 及联系人侧 K18—K21 仍未实现或未证明。

#### 历史事实输入（当前权威边界以能力链重建 Answer 为准）

- [【CAN】核验目标 Hermes 基线与受支持的健康扩展面](issues/42-verify-target-hermes-baseline-and-supported-extension-surface.md) — 2026-08-16 目标现场固定为带未提交定制的 Hermes v0.20.0 / commit `3c27eb…`；Skill 是按需知识文档，Plugin 才是受支持的执行扩展面，现场尚无健康 Plugin/Cron，通用 Hook/Middleware 的默认失效语义也不能视为安全失败关闭。
- [【CAN】核验聊天接口、主人身份与逐条消息来源能力](issues/43-verify-channel-owner-identity-and-message-provenance-capabilities.md) — 内置微信路径的单值 allowlist 可承担唯一技术消息准入，但不能代替健康管家初始化；其在健康入口前按正文去重、合批并丢失逐次来源的缺口仍是有效历史事实，接口无报错也不等于主人真实收到，完整 iLink 契约由后继微信接口能力核验补充。
- [【CAN】核验每日复盘、发送恢复与运行状态能力](issues/44-verify-scheduling-delivery-recovery-and-runtime-status-capabilities.md) — v0.20.0 Cron 能按时区触发、静默并折叠错过周期，但不保证主人当地自然日业务级恰好一次；崩溃、重启和在途发送会留下漏执行或未知态，Gateway/Ticker 存活不能证明健康核心活跃。
- [【CAN】核验健康画像、数据权利与保护能力](issues/45-verify-health-record-data-rights-and-protection-capabilities.md) — 普通 Session/Memory 既不是独立最小健康画像，也不提供主人数据权利或健康专用静态保护；正式 Plugin 仅保留自建专用状态与控制路径的空间，2026-08-16 现场尚无对应实现，接收方边界由后继模型路由事实与产品承诺接续处理。
- [【CAN】核验健康画像数据平面的可用工具与接口](issues/56-verify-health-data-plane-tools-and-interfaces.md) — 目标现场已证实标准 SQLite、`cryptography`、一般 OS/systemd 及部分不自动写普通历史的 Plugin 接口可用；没有受管 Plugin 数据、密钥或备份服务，`ctx.llm` 不能预检全部下游，通用备份也不满足健康恢复与删除，接收方差距及数据平面路线已分别由后继产品合同与 HOW 闭合。
- [【CAN】核验健康模型调用与全部实际接收方事前锁定能力](issues/57-verify-health-model-routing-and-recipient-preflight-capabilities.md) — `ctx.llm` 不自动写普通 Session，却不能禁用 fallback 或事前锁定 JOJO 内部全部下游；该负向事实继续保留，但后继接收方产品合同已把当前同意边界改为首跳模型服务路线及其正常内部路由，因此本票不再代表当前产品合同或阻塞 HOW。
- [【CAN】核验辅助诊断、医学知识与安全边界能力](issues/46-verify-diagnostic-reasoning-knowledge-and-safety-capabilities.md) — v0.20.0 提供 Plugin 自建最小输入、结构化模型调用和检索/Tool 扩展面，但不内置健康证据语义、医学来源质量保证或失败关闭安全闸门；Skill、提示词及通用 Hook/Middleware 均不能单独证明辅助诊断安全成立，具体缺口由后继医学工具核验与产品边界决定接续处理。
- [【CAN】核验医学知识来源、检索接口与安全强制工具](issues/59-verify-medical-knowledge-and-safety-enforcement-tools.md) — 各权威来源只能分别承担术语、临床指南、患者解释、文献发现或药品标签职责，目标现场虽有本地强制校验构件，却尚无同时闭合中文诊断内容、项目许可、版本和可用性的生产组合；后继产品决定允许继续 HOW，但把内容权利、中文来源版本清单和专业审核设为上线硬门槛。
- [【CAN】核验微信 iLink 与目标 Hermes 的真实接口能力](issues/52-verify-weixin-ilink-and-target-hermes-interface-capabilities.md) — 腾讯 iLink v2.4.6 与目标 Hermes v0.20.0 只证实单一微信技术身份的私聊收取、回复和主动发送入口；消息字段、重投、逐条确认、游标恢复、恰好一次及主人真实到达均无公开保证，内置路径还会先推进游标再去重合批，真实微信实验尚未执行。
- [【CAN】核验主人身份迁移与恢复所需的身份、凭据和持久化能力](issues/61-verify-owner-identity-migration-and-recovery-capabilities.md) — 本票核验的是现已取消的账号迁移、一次性恢复权与永久身份锁定目标；目标栈缺少对应状态机的事实作为历史输入保留，但不再是当前初始化或上线能力要求，后继完整能力链重审统一分类。
- [【CAN】核验抵抗旧状态恢复的身份权威锚点能力](issues/68-verify-non-rollback-owner-identity-authority-anchor-capabilities.md) — 本票围绕现已取消的身份防回滚 No-Go；旧状态可复活过期本地集合、现场缺少域外代际锚的事实仍可能影响永久删除和撤回批准防复活，具体能力归属由后继完整能力链重审，不再直接阻止初始化或上线。
- [【CAN】核验域外身份代际权威候选的强一致与防回滚能力](issues/71-verify-external-owner-generation-authority-candidates.md) — 本票研究的是现已取消的身份代际权威目标；强一致原语及其未核验账号、地域、权限、费用和现场 canary 的事实作为历史输入保留，是否支撑永久删除或撤回批准防复活由后继完整能力链重审，不再构成当前身份初始化 No-Go。
- [【CAN】核验每日复盘、主动投递恢复与跨故障域状态观测工具](issues/62-verify-daily-review-delivery-recovery-and-cross-fault-status-tools.md) — Hermes、Python/SQLite、systemd 与可选外部观察路径能承载自然日账本、未知态恢复和无正文核心自检，但现场尚无健康任务、业务账本、跨主机观察与主人通知；任务、提交、接口接受、主人到达和真实核心状态必须分层证明。
- [【CAN】核验健康能力发现、调用与结果返回契约](issues/63-verify-health-capability-discovery-invocation-and-result-contract.md) — v0.20.0 提供 Skill、Plugin Tool/Command、Cron 和内部 dispatch 扩展面，但注册、模型可见、主人发现、调用开始、业务成功与真实返回互不等价，接口也不自带健康主人身份或旁路收敛；2026-08-16/17 现场七项健康能力均未实现或未证明。
- [【CAN】核验健康模型路线的有效上下文上限、token 计量与超限行为](issues/69-verify-health-model-context-capacity-token-accounting-and-overflow-behavior.md) — 目标 JOJO / codex_responses 路线的 240,000 只是 Hermes 静态配置值，不是全部实际上游的容量合同；当前 Plugin 调用无法在请求前证明共同窗口或可靠 token 上界，真实输出上限、结构化格式与完整终态也未完整透传，调用后不能证明未截断，因此辅助诊断 HOW 继续失败关闭。

### HOW

- [【HOW】选择首发健康管家 Plugin 的统一端到端实现路线](issues/109-choose-unified-end-to-end-how-route-after-current-can-closure.md) — 选择一个 `health_weixin` 前置准入、单一低权限 `health-core`、加密本地状态、单区域 DynamoDB 不透明 current head、严格同一 Partner 首跳模型接口、离线受治理知识、确定性安全／诊断门禁、事务 outbox、分层微信／联系人投递和 writer-fence 删除／迁移的统一 Plugin 路线；七个 Skill 是 Plugin 内部的交互／职责资源，不是独立插件；所有实现、外部许可、医学审核、真实模型／微信和验收仍是下游硬门槛，详见 [ADR 0022](../../docs/adr/0022-select-current-health-steward-route-after-seven-skill-can-closure.md)。

### 历史 HOW（当前失效）

- [【HOW】选择健康管家的统一技术路线、权威职责与分层验证架构](issues/98-choose-unified-health-steward-technical-route-and-authority-architecture.md) — 2026-08-20 旧合同下曾选择 Partner Health Plugin、`health_weixin`、`health-core`、SQLite、DynamoDB current head 与 `StrictHealthLLM` 等候选组合；在最新 TO 和本轮能力链重建后已失效为当前选定路线，只保留历史候选、设计理由和验证清单。

## Not yet specified

- 统一 HOW 已完成路线选择；当前实现承接已发布为[首发健康管家 Plugin 实现 Spec](spec.md)，覆盖实现依赖、测试、真实微信验收、外部许可与医学审核、部署、迁移及回滚，不建立竞争计划。实现 Tickets 110—119 已按依赖顺序发布；[Ticket 110：建立 Plugin/core 受信边界与合成验证骨架](issues/110-establish-plugin-core-trust-boundary-and-synthetic-harness.md)已完成基础受信边界，[Ticket 111：实现唯一准入与主人初始化](issues/111-implement-unique-admission-and-owner-initialization.md)已完成 Plugin/core 精确入口绑定、读正文前活体门禁、真实且持久的 `health-init` 披露／同意证明、物理有界冲突解决，以及 finalize 后全来源 cursor 原子交接和配置漂移下的效果双门失败关闭；[Ticket 112：实现七 Skill 协调与日常证据画像处理](issues/112-implement-seven-skill-coordination-and-daily-evidence-portrait-turn.md)已完成单一 `health-steward` 协调、目的限定最小上下文、三类强类型证据、六域画像、实际 Skill 使用证明、唯一主人回复和两段原子提交的本地合成合同。下一张依赖票为 [Ticket 113：实现严格健康模型、受治理知识与非诊断答复](issues/113-implement-strict-health-llm-governed-knowledge-and-nondiagnostic-answer.md)。本 Map 不直接承载代码实现。

## Out of scope

- 本轮首发支持或验收微信以外的聊天接口；接口中立仍是产品边界，只有主人明确扩展 Destination 后才进入同一 Map。
- 多画像主人、多个同时使用者、多个同时有效的私聊入口、群聊，以及男朋友、家人、管理员、操作者或其他第三方共用或控制健康画像；现实身份核验、聊天账号迁移或恢复、一次性恢复权及不可恢复锁定流程。
- 真人医生直接接入、医生账户、自动转交医生材料、医生逐条复核或正式诊断回写；健康管家冒充持证医生给出正式确诊，或独立建议开始、停止或调整处方药。
- 本轮不核验产品整体的司法辖区适用、监管分类或运营合规，也不把这类核验做成 Plugin 功能或当前 Map 的闭合条件；因此本项目中的“验收”“正式上线”与“稳定运行”只表示产品与技术合同得到证明，不构成已经完成法律或监管合规核验的声明。该延期不取消当前 TO 已明确要求的内容使用权、来源许可、数据接收方边界和医学专业审核；以后若需开展整体合规核验，必须作为新的明确努力进入权威链。
