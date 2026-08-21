# 明确诊断范围候选形成、准入与诊断全链能力核验

## Answer

**结论是负向，但已经形成了可审计的明确候选。** 固定来源清单中，证据链最完整、最适合进入本轮 C09—C13 深审的是：**“中国 18 岁及以上成人、非妊娠且近期身高体重测量可靠时，仅基于 BMI 的超重/肥胖症及肥胖程度辅助分类”**。国家卫生健康委《肥胖症诊疗指南（2024 年版）》是原生中文、具有发文字号和版本年的一手临床来源，正文给出了 BMI 计算方式、成人分类阈值、肥胖分级和 BMI 局限性，因此足以命名并限定一个窄候选。[M1][M2] 这只证明“有资格进入审计”，**不证明已经准入或激活**。

主候选当前不能通过任何一个完整节点：C09 只证明了中文医学内容与版本入口，项目的插件/AI 摘录改写和生产再利用权、冻结内容清单、更新撤回退出链及合格医学专业审核均未闭合；C10 虽可写清适用人群、包含和排除边界，但没有可查询的已激活范围注册、范围级医学审核签字或产品验收；C11 没有现行六域/三类证据上下文、可证明的 token 容量和完整结构化终态，也没有满足诊断表达合同的结果对象；C12 没有不可绕过且失败关闭的“范围内／范围外／危险升级／危险未明／安全能力不可用”收敛链；C13 没有诊断修订链、唯一当前判断、依据失效传播或纠错通知。[P1][P2][L1][L2][W1][W2]

因此，**当前已激活诊断范围数仍为 0**。本 Ticket 可以以“已命名候选、完成固定来源筛选并得到 C09—C13 全链负向矩阵”的负向 CAN 解决；但完整 CAN、HOW 入口、完整首发和稳定运行均**不能**按零范围闭合。TO 明确要求完整首发至少有一个范围同时通过内容权利、对应中文版本、医学专业审核、安全、上下文完整性、范围验收和真实主人微信端到端验收；安装、单元测试、候选代码或零范围都不能替代。[P1] 本轮只算一轮有明确对象的负向全链调查，不能冒充三轮实质不同候选均负向，也不选择最终病种、来源组合、规则引擎、模型、状态介质或其他 HOW。

## 1. 调查范围、判据与证据层级

本报告只回答 [Ticket 86](../issues/86-verify-medical-content-governance-and-diagnostic-scope-candidates.md) 的 CAN 问题。固定筛选范围来自 [Ticket 59 及 Evidence 12](12-medical-knowledge-and-safety-enforcement-tools-20260817.md#L20-L30)：WHO ICD-11 MMS、CDDR/mhGAP、SMART Guidelines、NICE、MedlinePlus、PubMed、DailyMed/openFDA、RxNorm、国家卫生健康委官方发布目录，以及目标现场/仓库已持有的候选知识包。只对一项主候选深审；其他候选只做职责级入口筛选。

判据继承已经确认的产品合同，而不是由本报告重新决定：

- 明确范围逐项激活；范围归属不能确认或存在会实质改变诊断/紧急行动的重要范围外方向时，整次按范围外处理；安全五种结果彼此不可混用。[P2]
- 诊断前必须证明必要个人资料、医学依据、安全条件及输出空间完整；返回后不能证明完整结构化终态时，候选不得成为最终结果。[P3]
- 只有最终且通过全部门槛的诊断才保留最小结构化判断和证据/医学版本链接；未通过候选、完整提示、完整模型输入输出、整份外部记录和完整回复不得长期保留。[P4]
- 同一健康问题、事件和适用时期只有一条诊断修订链；当前权威可证明时至多一个当前 AI 判断，依据失效须传播，权威未知时不得猜测。[P5]

| 层级 | 本报告允许推出的事实 | 不能推出的事实 |
|---|---|---|
| `[OFFICIAL-MEDICAL]` | 发布机构自己的指南、手册、版本、语言、许可及适用职责 | 本项目已取得内容权利、规则化正确或完成专业审核 |
| `[PRODUCT]` | 已确认 TO 的范围、诊断、安全、留存、修订和首发门槛 | 当前实现已经满足 |
| `[FIXED-SOURCE]` | Hermes v0.20.0 固定提交的接口和失败语义 | 目标 LIVE 已接线或第三方 relay 完全等同官方 API |
| `[LIVE]` | 同日脱敏只读证据确认的正式 Partner 状态 | 工作树候选已部署、真实模型/微信结果已通过 |
| `[WORKTREE-CANDIDATE]` | 当前 dirty/untracked 候选的静态行为和局部单元测试 | 生产能力、医学有效性或主人端结果 |
| `[APPROVAL-REQUIRED]` | 只有另批后才能取得的外部联系、许可、专业审核或真实实验 | 本轮已经完成 |

本轮没有读取真实健康正文、发送模型或微信消息、联系发布机构/医生、接受许可、购买服务、改配置、部署代码、故障注入或执行破坏性实验。

## 2. 固定来源清单与有名候选

| 固定来源 | 可承担的职责与本轮入口结果 | 明确候选或淘汰结论 | 主审结果 |
|---|---|---|---|
| 国家卫生健康委官方目录 | 具体中文临床指南可支持诊断规则候选；《肥胖症诊疗指南（2024 年版）》具有正式通知、发文字号、中文 PDF 和可定位阈值。[M1][M2] | **候选 A：**中国 18 岁及以上成人、非妊娠且可靠测量条件下的 BMI 超重/肥胖及肥胖程度辅助分类。进入全链审计。 | **主候选**；内容/版本正向，其余准入链负向或未知 |
| NICE NG136 | 面向 18 岁及以上成人原发性高血压；有诊室、ABPM/HBPM 确认阈值和同日转诊分支，指南编号与更新记录清晰。[M3] | **候选 B：**18 岁及以上非妊娠成人疑似原发性高血压的规范测量确认与同日转诊分流。NICE 内容为英文；AI 使用需批准/许可，国际使用可能收费，项目未持有许可。[M4] | 可命名，但中文完整规则与内容权利门槛先失败，不替代主候选深审 |
| WHO CDDR / mhGAP | CDDR 是面向卫生专业人员的 ICD-11 临床诊断手册；WHO 页面当前列英文正文及意大利语版本。mhGAP 有中文材料，但中文 mhGAP-IG/执行摘要不能冒充 2024 CDDR 的中文完整诊断规则。[M5][M6] | **候选 C：**18 岁及以上、非孕产期、当前自伤/他伤紧急危险须先独立排除，且躁狂、精神病性、物质或躯体病因仍须鉴别的成人抑郁障碍辅助诊断方向。CDDR 为 CC BY-NC-ND；项目没有一致的中文完整规则、内容权利与审核闭包。[M5] | 可命名，但中文完整诊断规则与改编/规则化门槛先失败 |
| WHO ICD-11 MMS | `2026-01` release 有官方中文，可提供代码、术语、release、URI 和语言锚点；MMS 是统计分类/术语，不是临床诊断要求。[M7] | 不单独形成范围候选；可作为以后已准入范围的术语/版本锚点 | 职责级保留，不能补足 C09/C10 |
| WHO SMART Guidelines | 只对已发布的具体 DAK/Implementation Guide 提供机器可读流程/规则；固定清单未找到覆盖上述主候选且满足当前中文、许可和审核要求的现成包。[S1] | “SMART”不是病种范围；本轮淘汰为主诊断规则来源 | 负向入口 |
| MedlinePlus / PubMed | 分别承担患者解释和文献发现；都不负责生成或确认个体诊断，中文完整规则层也不成立。[S1] | 不形成诊断范围候选 | 职责级淘汰 |
| DailyMed / openFDA / RxNorm | 药品标签发现、核验和术语；不是诊断规则。RxNav 相互作用服务已停，openFDA 还明确不能依赖其作医疗决策。[S1] | 不形成诊断范围候选，也不能单独形成安全闸门 | 职责级淘汰 |
| 目标 LIVE / 仓库候选知识包 | 正式 Partner 没有健康 Plugin；仓库 `medical-safety-sources.md` 自己声明只作安全分流来源、不作诊断知识库，关键词会误报/漏报且 Hermes Plugin 异常默认 fail-open。[L1][W3] | 没有一个已持有、已部署、已准入的诊断知识包 | 确定性负向 |

这里特意区分了“**中文完整诊断规则**”与“中文摘要、患者事实页、术语或执行材料”。某来源存在中文页面或中文摘要，只能证明对应材料存在，不能自动补齐另一固定正文的完整中文版本、内容权利或范围审核。

## 3. 主候选的精确边界

### 3.1 名称与目的

**候选名称：**中国 18 岁及以上成人、非妊娠且近期身高体重测量可靠时，仅基于 BMI 的超重/肥胖症及肥胖程度辅助分类。

**只允许达到的目的：**使用 `BMI = 体重（kg）÷ 身高（m）的平方`，在输入和适用边界均成立时，表达“低体重／正常体重／超重／肥胖症”之一；若为肥胖症，再表达轻度／中度／重度／极重度之一，并明确这只是基于 BMI 的 AI 辅助分类、BMI 有局限、不能替代医生综合诊断。[M2]

### 3.2 适用人群与包含边界

- 年龄已确认 `≥18` 岁，采用中国成年人的 BMI 分类语境。
- 主人提供的是近期、单位明确且可追溯测量时间/方式的身高和体重；数值与单位换算没有冲突，测量可靠性没有重要未知。
- 本次只问 BMI 分类或肥胖程度，不要求解释病因、并发症、风险概率、处方、治疗或手术适应证。
- 本次没有重要范围外方向会实质改变是否可以使用 BMI 或改变紧急行动；独立安全链完整可用。

### 3.3 关键排除边界

- 未成年人、妊娠期，或年龄/妊娠状态不能确认。
- 没有有效身高/体重，单位、测量时间或可靠性未知，或不同测量明显冲突且未解决。
- 明显水肿、腹水、高肌肉量或其他使 BMI 明显失真的身体组成/测量场景。
- 腹型肥胖、体脂率或身体成分判断；肥胖病因、继发性肥胖、并发症、疾病风险、治疗选择、处方药、手术指征或疗效判断。
- 任何急症、自伤/他伤、危险用药或需要立即改变行动的情形。

后三类排除是本项目为了保持单一、可审计范围提出的**保守候选边界**；其中 BMI 局限由指南正文支持，但具体排除是否充分、是否过宽仍须合格医学专业人员审核，不能写成国家卫生健康委已经逐条批准本项目的边界。[M2]

### 3.4 本候选所需最小资料与最终表达

最小个人资料至少包括：年龄；妊娠/特殊身体状态是否触发排除；身高、体重、单位、测量时间和测量方式/可靠性；相互冲突的当前测量；只为独立安全分流所必需且不得自动进入 BMI 判断的安全事实。旧 AI 标签或旧 BMI 只能作为待复核假设，不能支持自身。

若最终成立，结构化结果至少要能表达：范围身份与医学版本；输入及其个人证据来源/时间；公式和分类；关键支持证据；关键反对或限定证据；会改变分类或适用性的关键未知；当前紧急程度；安全下一步；不确定性；AI 辅助判断身份。范围外、资料不完整、安全能力不可用或未通过完整性门槛时，不形成上述诊断记录。[P2][P3][P4]

## 4. 主候选 C09—C13 全链矩阵

| 节点 | 已证明 | 负向证明 | 未知 | 需另批实验/外部动作 | TO 覆盖结论 |
|---|---|---|---|---|---|
| **C09 医学治理** | `[OFFICIAL-MEDICAL]` 国家卫生健康委正式通知为 `国卫办医政函〔2024〕382号`，通知日期 2024-10-12；中文《肥胖症诊疗指南（2024 年版）》正文第 5 页给出 BMI 公式、成人阈值、肥胖分级和局限。[M1][M2] | `[LIVE]/[WORKTREE]` 当前没有已部署健康 Plugin、范围知识包、冻结内容清单或通用更新任务；仓库安全来源文件明确不是诊断知识库。[L1][W3] 发布机构组织专家制定指南，不等于本项目已经完成独立范围审核。 | 官网公开阅读不自动证明插件/AI 摘录、改写、规则化、生产再利用或再发布权；本轮未发现授予本项目这些用途的许可。逐条冻结内容、撤回/过期信号、更新责任和退出条件也未知。[S1] | 联系权利人并取得适用于实际用途的书面权利；形成冻结中文内容/版本清单；由合格医学专业人员审核内容、边界、危险和更新退出。外部联系、许可接受和专业审核均未获本票授权。 | **未通过。** 中文来源和版本入口成立，不覆盖内容权利、更新退出和项目专业审核 |
| **C10 范围准入** | `[OFFICIAL-MEDICAL]+[PRODUCT]` 本报告已把具体问题、人群、包含、排除、必要输入和输出目的写成可查询的有名候选；阈值可定位。[M2] | `[LIVE]` 正式 Partner 没有健康 Plugin或已激活范围；`[WORKTREE]` 对 `diagnostic_scope / activated_scope / 安全能力不可用 / current_diagnosis` 等范围/诊断注册语义的限定搜索为 0 命中，[R1] 且旧任务代码明确禁止 `diagnosis`。[W4] 没有范围级医学审核签字、内容与安全规则清单、产品验收或失效退出执行证据。 | 保守排除项是否足够、测量“近期/可靠”的医学判据、范围内外冲突优先级仍待专业审核；当前不能确认任何范围状态为 active。 | 许可和审核完成后，才可另批使用全合成边界案例验证范围内、边界值、范围外、混合方向、来源失效和状态退出；真实主人健康/微信验收另须批准。 | **未通过。** 有明确审计对象，不等于已准入或激活 |
| **C11 诊断完整性** | `[WORKTREE]` 旧候选有单轮上下文、最多 24 个个人 evidence ID、最多 8 张来源卡、ID allow-list 等局部原语；这只证明某些限制可表达。[W1] | `[LIVE]` 没有现行六域画像、三类证据卡或诊断结果对象。[L2] `[WORKTREE]` 回答链只传画像摘要、证据 ID 和来源卡公开投影，不传个人证据角色正文、来源时间和用途；输出 schema 只有 `answer_text + used_source_card_ids`。[W1] 第 9 张必要卡会被 `cards[:8]` 静默舍弃。[W2] 固定 `codex_responses` 路线不透传 `max_tokens`/`response_format`，并丢失 `incomplete/failed/incomplete_details/实际模型`，不能证明输入与输出完整终态。[F1] | JOJO 实际共同上下文下限、最终模型、tokenizer、隐藏包装和断流/截断实现未知；当前输出能否覆盖全部必要事实也无法证明。[F1] | 只有先具备可审计合同后，才可另批用纯合成中文、边界值、冲突测量、9 张必要证据卡、输出耗尽、截断、失败终态和 fallback fixture 验证；本票不运行真实模型或健康数据。 | **未通过。** 最小资料选择、来源角色、容量和结构化终态均未闭合；不得形成最终诊断 |
| **C12 安全强制** | `[WORKTREE]` 未部署 `health-guard` 候选声明 `pre_gateway_dispatch / pre_llm_call / pre_tool_call / transform_llm_output`，包含若干急症、自伤、调药和诊断关键词路径。[W3] | `[LIVE]` 当前没有健康 Plugin，故没有生产安全链。[L1] 固定 Hermes 的 Plugin 加载、Hook 和 Middleware 异常会继续基础流程，不能自动给出医疗失败关闭。[F2] 旧 guard 自己承认关键词会误报/漏报、运行期语义非医疗器械级硬闸门，且其产品边界明确“非诊断”；候选没有可查询的范围内、范围外、危险升级、危险未明、安全能力不可用五态收敛和各分支最小留存证明。[W3][R1] | 任何一个未命中是否真的无危险、隐晦/方言/语音/图片输入、Plugin 部分失败后的实际分支和微信交付结果均未知。 | 以后只有在内容权利、专业审核和强制路径存在后，才可另批做纯合成反例、旁路、组件失效和留存检查；真实危险、模型、微信和故障注入仍须单独授权。 | **未通过。** 不能强制五类结果，不能把关键词未命中、单元测试或免责声明当安全证明 |
| **C13 修订与当前权威** | `[WORKTREE]` 旧画像一次准入可追加个人证据和不可变画像版本并切换 `current_version_id`；资料卡可用 `current/superseded_by` 表达同 URL 后继。这是可复用原语。[L2] | `[LIVE]` 没有诊断记录或修订链。[L2] 旧 `current_version_id` 指向四类旧画像版本，不是同一健康问题/事件/时期的诊断当前判断；旧 sidecar 主路径禁止诊断。[L2][W4] `source superseded_by` 也没有向诊断判断传播失效，不能证明修订、降级、撤回、替代、复核无变化、单一当前/明确无当前、权威未知停止或一次必要纠错通知。 | 部分提交、恢复、并发或医学来源撤回时哪个判断为当前仍未知；主人转述医生结论与 AI 判断冲突的生产呈现未实现。 | 以后只有在诊断链存在后，才可另批用合成依据纠正、医生转述、来源撤回、无变化复核、部分提交/恢复和纠错通知案例验收；真实微信到达仍须单独授权。 | **未通过。** 画像/来源版本原语不能冒充诊断修订与当前权威 |

这张矩阵的状态不是五项“一票否决”的笼统复述：C09 的中文医学内容有正向证据，C10 的有名边界已经形成，C11—C13 也各有局部原语；但每一节点都存在足以阻止最终诊断的确定缺口。前一节点失败不会把后一节点写成“无须检查”，而是继续记录后继能力为什么仍不可证明。

## 5. 工作树局部测试为何不能改变结论

2026-08-20 同票并行审计在 `ops/partner-health-steward` 运行：

```text
python -m unittest tests.test_health_guard tests.test_health_turn_answer tests.test_health_turn_context tests.test_health_sidecar tests.test_weixin_delivery
```

结果为 `188` 项总计：`178 passed + 10 skipped + 0 failed`。[T1] 这些测试只能证明当前未部署旧候选中的关键词 guard、旧回答/context、旧画像和交付账本的局部行为；它们没有构造已获权利且经医学审核的 BMI 范围，没有现行范围注册、六域/三类诊断上下文、9 张全部必要证据不丢失、真实 `codex_responses` 完整终态、五态安全收敛、诊断修订链、生产部署或真实主人微信到达。因此 `188` 不是 C09—C13 通过数，也不能把零范围改写为已激活。

## 6. 零范围与本票停止边界

| 问题 | 当前答案 |
|---|---|
| 是否至少命名一个由一手来源支持进入审计的范围？ | **是。** 主候选为中国成年人的 BMI 超重/肥胖及肥胖程度辅助分类 |
| 是否有一个范围通过 C09—C13？ | **否。** 五个节点均有阻断性缺口 |
| 当前已激活诊断范围数是否大于 0？ | **否。** 当前可证明为 0 |
| Ticket 86 能否解决？ | **能，以负向 CAN 解决。** 固定清单、候选清单和主候选矩阵已经完成 |
| 完整 CAN/完整首发能否按零范围闭合？ | **不能。** TO 要求至少一个完整通过并经真实主人微信验收的已激活范围 [P1] |
| 是否已经达到 Map 的“三轮实质不同调查均负向”？ | **没有。** 本报告只记录本轮主候选，不能用职责级淘汰项凑数 |
| 本报告是否选择 HOW？ | **没有。** 不选择最终病种、来源组合、模型、规则、状态或部署路线 |

因此本轮停止在“可审计候选存在但未准入”的事实边界。任何后继若继续调查完整诊断链，必须是实质不同的候选及其完整 C09—C13 证据，而不是把同一 BMI 缺口拆成更多票或用中文摘要、测试通过、代码存在反复重述。

## 7. 一手来源与可定位证据

- **[P1] 完整首发合同：** [Ticket 75 `## Answer` 的诊断范围、完整性、安全与首发验收](../issues/75-close-first-release-health-steward-product-contract.md#L75-L111)，尤其第 111 行明确零范围、局部自动测试或单次演示不构成完整首发。
- **[P2] 范围与五类安全结果：** [Ticket 64 `## Answer`](../issues/64-define-diagnostic-scope-and-safe-unavailable-result.md#L74-L85)。
- **[P3] 容量失败关闭：** [Ticket 70 `## Answer`](../issues/70-decide-diagnostic-launch-boundary-under-unverifiable-context-capacity.md)及 [Evidence 16 的直接结论与终态损失](16-health-model-context-capacity-token-accounting-overflow-20260818.md#L8-L17)。
- **[P4] 个人证据、接收方与保留：** [Ticket 65 `## Answer`](../issues/65-define-diagnostic-evidence-recipients-and-retention-boundary.md#L120-L152)。
- **[P5] 诊断修订合同：** [Ticket 66 `## Answer`](../issues/66-define-diagnostic-judgment-change-and-traceability-contract.md)。
- **[M1] 国家卫生健康委正式通知：** [《国家卫生健康委办公厅关于印发肥胖症诊疗指南（2024年版）的通知》](https://www.nhc.gov.cn/yzygj/c100068/202410/18966b78087d44429f934a2ef028b027.shtml)，`国卫办医政函〔2024〕382号`，国家卫生健康委办公厅 2024-10-12，网站发布 2024-10-17。
- **[M2] 主候选医学正文：** [国家卫生健康委《肥胖症诊疗指南（2024年版）》PDF 第 5 页“基于体质指数的诊断标准”](https://www.nhc.gov.cn/yzygj/c100068/202410/18966b78087d44429f934a2ef028b027/files/1732873189749_61795.pdf#page=5)：BMI 公式；中国成年人 `<18.5 / 18.5–<24 / 24–<28 / ≥28 kg/m²` 分类；肥胖 `28–<32.5 / 32.5–<37.5 / 37.5–<50 / ≥50 kg/m²` 分级；同页随后说明 BMI 局限。
- **[M3] NICE 高血压候选：** [NICE NG136 overview](https://www.nice.org.uk/guidance/ng136)（18 岁及以上、2026-02-26 更新）及 [Recommendations 1.2](https://www.nice.org.uk/guidance/ng136/chapter/recommendations#diagnosing-hypertension)（诊室复测、ABPM/HBPM 确认和严重高血压同日转诊）。
- **[M4] NICE 内容权利：** [NICE reuse / syndication](https://www.nice.org.uk/reusing-our-content/nice-syndication-api)与 [NICE terms](https://www.nice.org.uk/terms-and-conditions)：AI 使用须取得批准/许可，国际使用可能涉及许可费用；本仓库/目标现场未持有相应许可资产。
- **[M5] WHO CDDR：** [WHO 2024 发布页](https://www.who.int/publications/i/item/9789240077263)说明其为临床诊断手册、面向卫生专业人员并列出语言版本；[正式 PDF](https://iris.who.int/bitstream/handle/10665/375767/9789240077263-eng.pdf)标示 CC BY-NC-ND 3.0 IGO。
- **[M6] WHO mhGAP 中文材料边界：** [WHO mhGAP-IG 2.0 出版记录](https://iris.who.int/handle/10665/250239)及其正式语言版本；中文 mhGAP 材料只能证明相应版本/摘要存在，不能替代 2024 CDDR 的中文完整诊断规则。
- **[M7] WHO ICD-11 MMS：** [官方支持版本与语言表](https://icd.who.int/docs/icd-api/SupportedClassifications/)列 `2026-01` MMS 中文；[Evidence 12 第 34–41 行](12-medical-knowledge-and-safety-enforcement-tools-20260817.md#L34-L41)限定其为术语、编码与版本锚点，不是诊断规则。
- **[S1] 固定来源职责/许可矩阵：** [Evidence 12 第 20–30 行](12-medical-knowledge-and-safety-enforcement-tools-20260817.md#L20-L30)及[国家卫生健康委、NICE、MedlinePlus/PubMed、药品来源、SMART 的逐项审计](12-medical-knowledge-and-safety-enforcement-tools-20260817.md#L53-L94)。
- **[F1] 固定模型路线：** [Evidence 16 第 47–88 行](16-health-model-context-capacity-token-accounting-overflow-20260818.md#L47-L88)：目标 `codex_responses` wire 不透传输出 cap/结构化格式，并在归一化中丢失失败/不完整终态与实际模型信号。
- **[F2] 固定 Plugin 失败语义：** [Evidence 19 第 89–101 行](19-current-partner-hermes-baseline-plugin-lifecycle-trust-20260820.md#L89-L101)：加载/注册/Hook/Middleware 不能自动形成医疗失败关闭。
- **[L1] 当前正式 Partner：** [Evidence 19 第 44–57 行](19-current-partner-hermes-baseline-plugin-lifecycle-trust-20260820.md#L44-L57)确认普通 enabled Plugin 与 profile manifest 均为 0、仓库健康候选未部署；[Evidence 24 第 7–12 行](24-first-hop-model-route-owner-derived-query-isolation-nondiagnostic-answer-results-20260820.md#L7-L12)确认当前名义首跳和非诊断结果链缺口。
- **[L2] 当前状态与证据面：** [Evidence 22 第 31–48、102–123 行](22-managed-health-state-plane-protection-and-single-authority-20260820.md#L31-L48)和 [Evidence 23 `## Answer`](23-six-domain-portrait-and-three-class-evidence-capabilities-20260820.md#L3-L15)：没有已部署诊断对象/修订链、现行六域画像和三类证据卡；旧 current pointer 只是局部画像原语。
- **[W1] 旧回答链：** [`health_turn_answer.py` schema 与输入投影](../../../ops/partner-health-steward/health_turn_answer.py#L22-L31)及[提示/context 组装](../../../ops/partner-health-steward/health_turn_answer.py#L145-L236)；[Evidence 24 第 95–130 行](24-first-hop-model-route-owner-derived-query-isolation-nondiagnostic-answer-results-20260820.md#L95-L130)。
- **[W2] 静默卡片上限：** [`health_turn_context.py` 固定最多 8 张并取 `cards[:MAX_HEALTH_TURN_SOURCE_CARDS]`](../../../ops/partner-health-steward/sidecar/health_turn_context.py#L19-L19)及[第 180–201 行的投影](../../../ops/partner-health-steward/sidecar/health_turn_context.py#L180-L201)。SHA-256 `AE78DA65585A35DBBC33A82BE8510657294D078191C88ECF23916743288B04CD`。
- **[W3] 未部署安全候选自限：** [`medical-safety-sources.md` 第 5、16–19 行](../../../ops/partner-health-steward/skill/health-steward/references/medical-safety-sources.md#L5-L19)及 [`health-guard/plugin.yaml`](../../../ops/partner-health-steward/plugin/health-guard/plugin.yaml#L1-L9)。`guard.py` SHA-256 `9BA40D83F5FCB26074BB7F99075CD11EF67F90F09958542E7525CD4F0F6B6135`；来源文件 SHA-256 `A25F84BD9EB14F642A0D11C7BA6C5A71ECC4612EC1DA97BF85A64BA501D09151`。
- **[W4] 旧候选非诊断边界：** [`sidecar/tasks.py` 第 46 行禁止 diagnosis 任务](../../../ops/partner-health-steward/sidecar/tasks.py#L33-L50)，SHA-256 `A90A618E6B21C4228F8FDBA85669553CC07AA38593AC748E37A65A2081FDD83D`；[`profile.py` 的个人证据、画像版本与 current pointer](../../../ops/partner-health-steward/sidecar/profile.py#L726-L829)，SHA-256 `F134AF8060DC82E53678FEF090F4C8D426B08EC95CEE7A1593B6CD8F3EE77344`。
- **[R1] 当前工作树限定搜索：** 2026-08-20 在 `ops/partner-health-steward` 对 `diagnostic_scope|diagnosis_scope|scope_registry|activated_scope|active_scope|诊断范围|安全能力不可用|danger_unknown|safety_unavailable|current_diagnosis|diagnosis_revision` 执行大小写不敏感 `rg`，0 命中。它只证明当前候选没有这些可定位语义，不证明其他未搜索系统绝对不存在同义实现；LIVE 缺口另由 [L1] 独立证明。
- **[T1] 旧候选局部测试：** 2026-08-20 同票并行审计运行正文所列五个 `unittest` 模块，`188 total = 178 passed + 10 skipped + 0 failed`；没有真实模型、健康正文或微信动作，证明边界见第 5 节。
