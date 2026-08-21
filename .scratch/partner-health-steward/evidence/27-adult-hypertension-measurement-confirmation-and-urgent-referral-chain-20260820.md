# 成人疑似原发性高血压规范测量确认与同日转诊分流的完整诊断链核验

## Answer

截至 **2026-08-20（Asia/Shanghai）**，本轮已经把第二个实质不同的诊断范围候选准确限定为：**中国境内 18 岁及以上、非妊娠且非哺乳、尚无已知持证医生高血压诊断且当前或近期未使用降压药的成人，在血压测量来源、时间、方法和质量可确认，并先检查是否存在或是否无法排除紧急或重要范围外方向时，对疑似原发性高血压作规范复测确认状态与人工医疗分流的 AI 辅助判断；无法排除时即退出普通诊断或进入危险未明**。现行来源共同证明，诊室复测、家庭或动态监测需要保留跨时间、跨场景的测量条件；普通、未进入医生专属例外或严重分支的首次偏高，不能由健康管家仅凭一次读数确认。中国 2025 指南确有依赖医生判断、排除诱因和现场复测的立即确诊例外，这些例外全部属于本候选的医生专属范围外能力。只有命中某一已获权且经审核来源明确列出的严重数值—急性症状或体征组合时，才进入相应同日或更紧急人工医疗分流并停止普通诊断输出。[M1][M2][M3]

这只证明候选**可以被完整审计**，不证明它已准入。中文 2025 指南与 NICE 2026 现行版在诊室确认方式、家庭测量取值、双臂差异阈值和严重血压分流阈值上存在实质差异；两者面向医疗专业人员的规则也不能未经内容权利确认和项目级医学审核直接变成面向主人的 AI 产品规则。[M2][M3][R1][R2] 当前项目没有适用于这些内容的已记录生产/AI 使用权、冻结规则集、合格医学专业审核、范围级产品验收或失效退出链；正式 Partner 没有已部署健康 Plugin 或激活范围，工作树候选也没有完整诊断对象、安全五分支或修订链。[L1][L2][W1][W2][W3][W4]

因此 **C09、C10、C11、C12、C13 均未通过**。当前可证明的已激活诊断范围数仍为 **0**，[完整 CAN 闭合票](../issues/77-close-complete-capability-and-constraint-report.md)不能闭合，也不能进入 HOW。本轮是继 BMI 单次计算分类之后的**第二轮实质不同完整负向研究**：其新事实来自跨日/跨场景测量、白大衣与隐蔽性冲突、来源明确列出的严重数值—急性症状/体征组合的优先分流，以及“待确认—支持确认—仍未确认—撤回”的当前判断修订要求。医生结论必须独立保留并触发 AI 判断复核；AI 判断只能因实质依据变化而修订、降级或撤回，或由另一项通过相同门槛的 AI 判断替代。这不是重复第一轮的许可或未部署结论。[P1][P2]

## 1. 调查范围、证据层级与禁止动作

- `[PRODUCT]`：以 [Ticket 95](../issues/95-verify-adult-hypertension-measurement-confirmation-and-urgent-referral-chain.md)、[Ticket 86](../issues/86-verify-medical-content-governance-and-diagnostic-scope-candidates.md)、[Evidence 25](25-named-diagnostic-scope-governance-and-full-chain-capabilities-20260820.md)、[完整首发 TO](../issues/75-close-first-release-health-steward-product-contract.md)和 [C09—C13 能力定义](../issues/76-rebuild-complete-to-capability-chain-and-traceability.md#L32-L36)判定结果，不降低 TO。
- `[OFFICIAL-NHC]`：国家卫生健康委发布的现行推荐性卫生行业标准 `WS/T 872—2025`。[M1]
- `[FIRST-PARTY-NCCD-GUIDELINE]`：由受国家卫生健康委委托成立、在基层卫生健康司指导下工作的基层高血压管理办公室组织专家更新，并由国家心血管病中心办公室发布、在专业期刊刊载的 2025 指南及其发布页使用声明；它是一手专业指南，不是国家卫生健康委发文发布的卫生行业标准。[M2][R1]
- `[OFFICIAL-NICE]`：NICE `NG136` 现行建议、版本页和 NICE 自己的国际使用、AI 使用与许可页面。[M3][R2][R3]
- `[LIVE-INHERITED]`：只继承 2026-08-20 同日已完成的正式 Partner 脱敏核验；本轮不重新连接现场、不读取任何正文。[L1][L2]
- `[FIXED-SOURCE]`：Hermes v0.20.0 / commit `3c27eb6234bf91b8ceee9e9071591b31e9b148cb` 已定位的 Plugin、模型适配器和终态语义。[F1][F2]
- `[WORKTREE-CANDIDATE]`：`D:\cohermes\ops\partner-health-steward` 当前 dirty/untracked 候选的静态事实，仅作为未部署候选观察，不继承为 HOW 或生产能力。[W1][W2][W3][W4]

本轮没有读取、创建或输出真实健康正文，没有调用模型、微信或其他外部接收方，没有联系权利人或医学专业人员，没有接受许可、购买、部署、改配置、启停服务或注入故障。唯一新增文件是本报告；未修改 Ticket、Map、`CONTEXT.md` 或实现。

## 2. 候选的精确产品边界

| 边界 | 本轮可审计定义 | 不允许冒充 |
| --- | --- | --- |
| 候选名称 | 中国境内 18 岁及以上、非妊娠且非哺乳成人疑似原发性高血压的规范测量确认状态与同日或更紧急人工医疗分流 | “高血压常识”“看到一个数值就确诊”或任何正式医生诊断 |
| 必要个人输入 | 每次收缩压/舒张压、`mmHg`、发生时间、诊室/家庭/动态来源、测量序号、手臂、体位、休息和影响因素、设备验证/校准与袖带条件；来源明确列出的急性症状/体征、急性心脑肾/眼危险线索、妊娠/哺乳、疑似继发方向；既往持证医生高血压结论、当前或近期降压药及其来源和时间；主人陈述、测量、医生转述和旧 AI 假设必须分开 | 只有“今天血压 160/100”、把主人自述改写成医生测量，或把当前较低读数解释为既往诊断已消失 |
| 允许输出 | 命中某一已获权且经审核来源明确列出的数值—急性症状/体征组合时，只进入相应人工医疗分流并停止普通诊断输出；未命中但缺少会改变紧急行动的事实时进入危险未明。只有未进入危险升级且安全资料完整时，才可说明“资料不足待确认”“现有资料与某一已审定确认规则一致”“测量冲突/仍未确认”或重要范围外方向，并列支持、反对、关键未知和不确定性 | 危险升级后继续普通诊断、正式确诊/排除、替医生处理继发原因、独立决定处方药开始/停药/剂量 |
| 范围内 | 已获权利且经项目医学审核的规则集所定义的规范诊室复测、规范家庭血压或动态血压证据；同一事件/时期内可追溯地形成确认状态 | 任意设备、任意姿势、任意一次读数、来源或时间不明的平均值 |
| 重要范围外 | 未满 18 岁；妊娠或哺乳；既往已有持证医生高血压诊断或当前/近期使用降压药；疑似继发性高血压；需要专业查体/眼底/实验室/心电或靶器官损害判断；发作性症状、明显体位变化、显著双臂差异、严重合并症；正式治疗和处方调整 | 为了保留范围而隐藏这些方向、声称聊天已经排除需要检查的方向，或仍输出残缺个体诊断 |
| 危险优先 | 命中某一已获权且经审核来源明确列出的严重数值—急性症状/体征组合时，必须进入相应同日或更紧急人工医疗分流并停止普通诊断输出；未命中但缺少会改变紧急行动的事实时为危险未明 | 普通补问、平均值或“可能只是紧张”吞掉危险分支，或把任意非特异症状机械升级 |
| 失效退出 | 来源更新/撤回、使用权中止、医学审核过期或否决、规则集版本无法确认、必要测量来源/质量/时间不完整、冲突未解、范围安全能力不可确认时，不保留最终结构化诊断 | 继续沿用旧阈值、猜测当前版本或把范围不可用写成主人无风险 |

这个边界不选择最终病种或规则组合。它只是把候选的**人群、输入、允许输出、排除、危险和失效条件**精确到可以逐项验收。

## 3. 现行一手医学来源证明了什么，以及为什么还不能合并成产品规则

### 3.1 中国现行来源

国家卫生健康委发布的推荐性卫生行业标准 `WS/T 872—2025` 自 2026-03-01 实施，适用于基层医疗卫生机构对 18 岁及以上成人高血压患者的管理。它要求上臂式医用电子血压计、定期校准、规范休息/体位/袖带、首诊双臂测量、诊室重复测量和家庭早晚多次记录，并明确疑诊者须完成诊断流程，诊断标准参见《国家基层高血压防治管理指南》。[M1]

《国家基层高血压防治管理指南 2025 版》由受国家卫生健康委委托成立、在基层卫生健康司指导下工作的基层高血压管理办公室组织专家更新，由国家心血管病中心办公室发布并在专业期刊刊载；它不是国家卫生健康委发文发布的卫生行业标准。该指南面向基层医务人员，聚焦原发性高血压并要求识别不适合基层诊治者，给出以下候选特异事实：[M2]

- 诊室：首诊双臂；每次两次、约 1 分钟间隔，差异大时第三次；4 周内非同日 3 次规范诊室血压均达到 `140/90 mmHg` 为一种确认路径。
- 家庭：经准确度验证的设备，建议 5–7 天、早晚各一次、每次 2–3 遍，取所有测量值平均；无法完成时不少于 3 天且至少 12 个值。
- 动态：24 小时、白天或夜间平均值分别有阈值；白大衣与隐蔽性高血压要求结合诊室外结果处理冲突。
- 严重与转诊：首诊 `SBP ≥180 mmHg` 和/或 `DBP ≥110 mmHg` 且伴急性症状时建议立即转诊；指南另列急救车转诊的严重症状组合，以及疑似继发、妊娠/哺乳、年龄小于 30 岁起病、蛋白尿/血尿、低钾、阵发性血压升高伴症状和双臂差异等上转方向。

这些建议是**医疗专业人员工作流**。指南中的“医生认为不立即药物治疗有风险”、靶器官损害评估、诊断和处方处理都超出健康管家自主输出边界，不能原样转成主人端规则。

### 3.2 NICE 现行来源

NICE `NG136` 适用于 18 岁及以上成人原发性高血压识别与管理，页面显示 2019-08-28 发布、2026-02-26 最近更新；妊娠高血压走另一指南。当前建议要求受训人员、经验证并维护/再校准的设备、合适袖带和标准环境；诊室达到 `140/90 mmHg` 后复测，`140/90` 至低于 `180/120 mmHg` 时优先以 ABPM 确认，不适合 ABPM 时用 HBPM。[M3]

- ABPM：清醒时每小时至少两次，以至少 14 次清醒期读数平均值确认。
- HBPM：每次连续两次、至少间隔 1 分钟，早晚各一次，至少 4 天、最好 7 天；丢弃第一天，平均余下读数。
- 确认条件：诊室 `≥140/90 mmHg` 且 ABPM 白天平均或 HBPM 平均 `≥135/85 mmHg`。
- 同日专科评估：诊室 `≥180/120 mmHg` 且有视网膜出血/视乳头水肿，或新发意识混乱、胸痛、心衰征象、急性肾损伤等危及生命表现；疑似嗜铬细胞瘤也为同日评估方向。严重血压但没有同日转诊征象时走尽快靶器官检查和 7 日内复核的医疗流程。

### 3.3 不能由 CAN 擅自消除的差异

| 关键点 | 中国 2025 指南 | NICE `NG136` 2026 现行版 | 对候选的影响 |
| --- | --- | --- | --- |
| 诊室确认 | 可用 4 周内非同日 3 次规范诊室测量，亦可用 ABPM/HBPM | `140/90` 至低于 `180/120` 时先提供 ABPM，不能耐受时 HBPM | 不能只写一个“国际通用确认流程” |
| 家庭平均 | 5–7 天取所有值；不足时允许不少于 3 天、至少 12 值 | 至少 4 天、最好 7 天，丢弃首日后平均 | 同一原始序列可能得到不同产品状态 |
| 双臂差异 | 收缩压差 `>20 mmHg` 为上转排查方向 | 重复后仍 `>15 mmHg`，后续用较高侧 | 输入完整性与范围外条件不同 |
| 严重阈值与行动 | `≥180/110` 伴急性症状建议立即转诊，并列急救车症状组合 | `≥180/120` 加指定体征/危及生命症状同日专科评估 | 安全闸门不能未经审核拼接阈值 |
| 例外 | 医生可在特定 `160–179/100–109` 场景基于风险和复诊可行性立即确诊/治疗 | 不提供同一主人端例外 | 该例外依赖医生判断，明确排除在管家自主诊断之外 |

差异不表示任一来源错误；它证明项目必须先确定适用法域/人群和一套有权利、冻结版本、医学审核、更新与撤回负责人的内容集。CAN 只能记录该缺口，不能选择、拼接或改写为 HOW。

## 4. 与 BMI 第一轮的实质差异

| 维度 | BMI 第一轮 | 本轮疑似原发性高血压 | 为什么是独立研究 |
| --- | --- | --- | --- |
| 原始输入 | 一组近期可靠身高和体重，计算一个 BMI | 多次 SBP/DBP，跨诊室/家庭/动态、跨日、双臂及测量条件 | 单条测量对象不能复用为时间序列确认链 |
| 计算/确认 | 固定公式后按分界分类，同时保留 BMI 局限 | 复测、平均、读数数量、测量日、场景和来源规则共同决定状态 | 省略任一必要序列字段都可能改判 |
| 冲突 | 多为身高体重可靠性、时间变化或 BMI 不反映体成分 | 白大衣/隐蔽性、诊室与家庭冲突、双臂差异、设备/方法差异 | 必须保留支持、反对、限定和未知，不能覆盖写“最新值” |
| 安全优先级 | 分类本身没有同构的严重数值—急性症状/体征分流链 | 已获权且经审核来源明确列出的严重数值—急性症状/体征组合须先于普通确认进入相应人工医疗分流 | C12 必须验证候选专属且来源明确的数值—急性症状/体征组合 |
| 重要范围外 | 妊娠、未成年人、体成分特殊等 | 妊娠/哺乳、疑似继发、急性靶器官方向、体位问题、专业检查与治疗 | 范围外方向更多且会改变即时行动 |
| 当前判断修订 | 新身高/体重通常形成新时期分类 | 待确认、支持确认、仍未确认、冲突、撤回及来源失效；医生结论独立保留并触发 AI 复核，而不自动覆盖 AI 判断 | C13 需要同一问题/事件/时期的唯一当前状态和历史链 |

因此，本轮的正负证据即使继承相同平台，也不能由 BMI 矩阵机械推出。

## 5. C09—C13 完整矩阵

| 节点 | 已证明 | 负向证明 | 未知 | 需要另批实验或外部动作 | 对 TO 的覆盖 |
| --- | --- | --- | --- | --- | --- |
| **C09 医学治理** | `[OFFICIAL-NHC]` 已定位原生中文 `WS/T 872—2025`、适用人群、发布和实施日期；`[FIRST-PARTY-NCCD-GUIDELINE]` 已定位 2025 指南、版本与来源级专业审查；`[OFFICIAL-NICE]` 已定位 `NG136` 及 2026-02-26 更新、国际/AI 许可页面。[M1][M2][M3][R2] | NCCD 下载页声明 `All Rights Reserved` 且未经允许不得商业使用；公开下载不构成本项目 AI 摘录、翻译、规则化和生产使用授权。NICE 明确要求国际非个人研究用途取得书面许可和许可协议，所有 AI 用途均须审批/许可，国际使用收费；项目没有记录这些许可。来源级专家审查也不等于本项目对数字规则、边界和安全文案完成审核。[R1][R2][R3] | 中国来源的实际产品复用权、第三方内容权利、最终采用哪一来源集、如何解决规则差异、谁负责更新/撤回、项目医学审核是否通过均未知。 | 外部联系权利人并取得适用于实际 AI/生产用途的书面权利；冻结中文内容和版本清单；指定更新/撤回责任；由合格医学专业人员审核测量、确认、范围外、危险、文案和退出条件。以上动作均未获本票授权。 | **部分事实成立、节点未通过。** 覆盖“有当前中文来源和版本入口”，不覆盖内容权利、独立更新退出和项目专业审核；[医学来源缺口 TO](../issues/60-decide-medical-source-gap-boundary.md)仍不得视为满足。 |
| **C10 范围准入** | 候选名称、人群、必要输入、允许输出、重要排除、危险优先和失效条件已可查询；一手来源能支持进入范围审计。[M1][M2][M3] | `[LIVE]` 正式 Partner 没有健康 Plugin 或已激活范围。[L1] 当前工作树对 `diagnostic_scope`、`scope_registry`、`activated_scope`、`current_diagnosis` 等限定语义为 0 命中；没有范围级内容/安全清单、医学签字、产品验收、有效期或失效退出执行。[W5] | 最终适用规则集、专业排除是否充分、医生专属例外如何保持范围外、中文与 NICE 冲突时的优先级均未知。 | C09 外部动作完成后，另批纯合成边界验收：年龄、妊娠/哺乳、测量质量、诊室/HBPM/ABPM、白大衣/隐蔽性、严重症状、重要范围外、来源撤回和范围退出；真实主人/微信验收另须批准。 | **未通过。** 有名候选不等于激活；[医生责任 TO](../issues/40-define-diagnostic-physician-handoff-boundary.md)与[范围/不可用 TO](../issues/64-define-diagnostic-scope-and-safe-unavailable-result.md)只获得边界输入，没有获得生产范围。 |
| **C11 诊断完整性** | `[WORKTREE]` `health-autonomy` 可从明确“今天/现在”的一条 `血压SBP/DBP mmHg` 文字中解析数值和单位，并做宽泛物理界限；旧上下文可带最多 8 张来源卡，回答仅允许引用输入卡 ID。[W1][W2] | 解析器只写 `measurement.blood_pressure.latest`，没有设备、场景、手臂、体位、复测序列、HBPM/ABPM、测量质量、伴随症状或冲突；这不能组成规范确认链。[W1] 旧画像/三类证据与诊断结果对象未实现；回答 schema 只有 `answer_text + used_source_card_ids`，不能强制方向顺序、支持/反对、未知、紧急程度和下一步，第 9 张必要来源卡也无法进入现有上下文。[W2][L2] 固定 `codex_responses` 不透传结构化格式/输出 cap，并丢失不完整、失败或缺终态信号，不能证明完整最终结果。[F1] | 实际 relay 的共同上下文下限、tokenizer、最终模型、截断/断流行为及完整规则集所需最小容量未知；本轮未调用模型。 | 先有受支持合同后，再另批用纯合成多日、多场景、冲突、缺字段、8/9 卡、输出耗尽、`incomplete/failed`、断流和 fallback fixture 验证；真实健康数据和真实模型调用另须批准。 | **未通过。** [资料最小化 TO](../issues/65-define-diagnostic-evidence-recipients-and-retention-boundary.md)与[容量失败关闭 TO](../issues/70-decide-diagnostic-launch-boundary-under-unverifiable-context-capacity.md)均未被完整覆盖；不得形成最终结构化诊断。 |
| **C12 安全强制** | `[WORKTREE]` 未部署 guard 有通用健康/诊断/调药关键词和若干固定急症文案，说明局部拦截原语存在；TO 已固定 AI 只作辅助判断、医生负责正式诊断且管家不独立调处方药。[W3][P1] | guard 只把“血压/高血压”当通用关键词；当前工作树没有 `180/110`、`180/120`、候选专属数值—症状组合、`危险未明` 或 `安全能力不可用` 语义。[W3][W5] 正式 Partner 没有生产健康 Plugin；固定 Hermes 的 Plugin 加载、Hook 和 Middleware 异常默认继续，不能自动形成医疗 fail-closed。[L1][F2] 因而范围内、范围外、危险升级、危险未明和安全能力不可用五类结果均不可证明，普通补问也没有不可绕过的危险优先级。 | 隐晦/方言/图片/语音、部分状态不可读、来源版本未知、组件失效和消息重投时会落入哪个分支未知；不同医学来源的严重阈值尚未审定。 | C09/C10 完成后，另批纯合成阈值边界、症状组合、范围混合、绕过、组件不可用和最小留存测试；生产故障注入、真实危险输入、模型或微信均须单独授权。 | **未通过。** [范围/危险/不可用 TO](../issues/64-define-diagnostic-scope-and-safe-unavailable-result.md)和[医生责任 TO](../issues/40-define-diagnostic-physician-handoff-boundary.md)没有不可绕过的生产收敛链。 |
| **C13 修订与当前权威** | `[WORKTREE]` 旧画像可追加不可变版本并切换 `current_version_id`，通用资料卡可表达 `current/superseded_by`；这些只是可复用版本原语。[W4] | 单条血压候选写入 `measurement.blood_pressure.latest`，没有保留本候选所需的完整测量序列和同一问题/事件/时期诊断链。[W1] 当前没有诊断修订对象，画像 current pointer 不是当前诊断；来源后继不会传播为诊断降级/撤回。修订、降级、撤回、替代、复核无变化、唯一当前/明确无当前、权威未知停止、医生结论分离及曾影响主人后的一次必要纠错通知均未实现或未证明。[L2][W4] | 并发测量、部分提交、崩溃恢复、主人纠正、医生结论与 AI 冲突、来源撤回时哪个判断为当前及是否只通知一次均未知。 | 诊断链存在后，另批纯合成“新增测量—冲突—仍待确认—医生结论—来源失效—主人纠正—无变化复核—一次通知”及时序/恢复验收；故障注入与真实微信到达另须授权。 | **未通过。** [修订与追溯 TO](../issues/66-define-diagnostic-judgment-change-and-traceability-contract.md)没有当前权威或传播链。 |

前一节点失败没有使后一节点“免检”：本矩阵仍逐项证明了血压候选自己的测量、安全和修订缺口。局部解析、版本指针、固定文案或公开指南均不能跨节点冒充整条诊断链。

## 6. 当前技术事实的可复现定位

### 6.1 单条血压解析不是确认链

当前 [`autonomy.py`](../../../ops/partner-health-steward/plugin/health-autonomy/autonomy.py#L1715-L1739) 只在文字同时含“今天/现在”等标记时用正则提取一条 `SBP/DBP mmHg`，接受 `30≤SBP≤300`、`20≤DBP≤200` 且 `SBP>DBP`，写入 `measurement.blood_pressure.latest`。文件 SHA-256 为 `86AEE4C697079F46968927B3359D366CC60CD9735AB94920A26FB828523DCFEE`。[W1]

它没有保存决定本候选判断的诊室/HBPM/ABPM、设备验证、校准、袖带、手臂、体位、休息、复测序号、跨日序列、平均规则、症状或医生结论来源。宽泛物理边界只说明文本像一个数值，不能证明测量规范、确认成立或安全。

### 6.2 旧回答结构不能强制完整诊断

[`health_turn_context.py`](../../../ops/partner-health-steward/sidecar/health_turn_context.py#L19-L32) 固定最多 8 张来源卡；[`health_turn_answer.py`](../../../ops/partner-health-steward/health_turn_answer.py#L25-L36) 的模型输出 schema 只有 `answer_text` 与 `used_source_card_ids`。两个文件 SHA-256 分别为 `AE78DA65585A35DBBC33A82BE8510657294D078191C88ECF23916743288B04CD` 和 `EE64E44DCBCD9D898A6A13E82458CBB4357CD2C71F83F1CD178351D09EA40DC5`。[W2]

这不能强制表达：有顺序且带不确定性的方向、关键支持、关键反对、会改变判断的未知、紧急程度和安全下一步。固定模型路线对结构化格式、输出预留和终态信号的缺口见 [Evidence 16](16-health-model-context-capacity-token-accounting-overflow-20260818.md#L49-L90)和 [Evidence 24](24-first-hop-model-route-owner-derived-query-isolation-nondiagnostic-answer-results-20260820.md#L7-L12)。[F1][L2]

### 6.3 通用关键词不是候选专属安全规则

[`health-guard/guard.py`](../../../ops/partner-health-steward/plugin/health-guard/guard.py#L123-L192) 只把“血压”“高血压”列入一般健康/诊断词，候选文件 SHA-256 为 `9BA40D83F5FCB26074BB7F99075CD11EF67F90F09958542E7525CD4F0F6B6135`。2026-08-20 对 `ops/partner-health-steward` 限定搜索 `180/110|180/120|diagnostic_scope|scope_registry|activated_scope|current_diagnosis|diagnosis_revision|danger_unknown|safety_unavailable|安全能力不可用`，结果为 0 命中。[W3][W5]

这个搜索只证明当前工作树没有这些可定位语义，不证明所有可能的同义实现绝不存在；正式 Partner 未部署健康 Plugin及固定 Hermes fail-open 语义则由 [Evidence 19](19-current-partner-hermes-baseline-plugin-lifecycle-trust-20260820.md#L44-L50)和其[失败语义定位](19-current-partner-hermes-baseline-plugin-lifecycle-trust-20260820.md#L89-L101)独立证明。[L1][F2]

### 6.4 画像版本原语不是诊断修订链

[`profile.py`](../../../ops/partner-health-steward/sidecar/profile.py#L726-L829) 能在旧画像准入中追加个人证据和画像版本并切换 `current_version_id`，文件 SHA-256 为 `F134AF8060DC82E53678FEF090F4C8D426B08EC95CEE7A1593B6CD8F3EE77344`。[W4] 但 [Evidence 22](22-managed-health-state-plane-protection-and-single-authority-20260820.md#L20-L80)与 [Evidence 23](23-six-domain-portrait-and-three-class-evidence-capabilities-20260820.md#L1-L48)已经证明当前没有受管诊断当前权威，也没有现行六域/三类证据对象；画像 current pointer 不能冒充同一血压问题的诊断当前判断。

## 7. 当前范围数、研究轮次与闭合状态

| 项目 | 当前结果 |
| --- | --- |
| 第一轮完整候选 | BMI 超重/肥胖辅助分类；C09—C13 负向，未激活 [P2] |
| 第二轮完整候选 | 本报告的成人疑似原发性高血压规范测量确认与同日/更紧急分流；C09—C13 负向，未激活 |
| 实质不同的完整负向轮次累计 | **2** |
| 当前已激活诊断范围数 | **0** |
| 是否满足完整首发“至少一个合格范围” | **否** |
| 完整 CAN 闭合票能否解决 | **不能** |
| 是否可以选择 HOW | **不能** |

本轮没有触发“三轮实质不同候选均负向后、开启第四轮前提交可行性说明”的规则；它只把累计轮次从一轮推进为两轮。是否继续第三个候选由权威 Map/后继 Ticket 决定，本报告不创建票、不修改 Map，也不预选病种。

## 8. 一手来源与本地证据定位

- **[P1] 产品合同：** [Ticket 95](../issues/95-verify-adult-hypertension-measurement-confirmation-and-urgent-referral-chain.md)、[C09—C13 能力链](../issues/76-rebuild-complete-to-capability-chain-and-traceability.md#L32-L36)、[完整首发 TO](../issues/75-close-first-release-health-steward-product-contract.md)及[诊断责任边界](../issues/40-define-diagnostic-physician-handoff-boundary.md)。
- **[P2] 第一轮完整矩阵：** [Evidence 25](25-named-diagnostic-scope-governance-and-full-chain-capabilities-20260820.md#L79-L109)，证明 BMI 候选五节点负向、已激活范围为 0，并固定后继必须研究实质不同完整链。
- **[M1] 国家卫生健康委标准：** [发布通告，国卫通〔2025〕13 号](https://www.nhc.gov.cn/fzs/c100048/202509/2f3f7cce449145f8b361e70b3ed4ae9a.shtml)、[标准目录页](https://www.nhc.gov.cn/wjw/c100309/202509/b601cb822b25461f92f7aa66c03495a8.shtml)与 [`WS/T 872—2025` PDF](https://www.nhc.gov.cn/fzs/c100048/202509/2f3f7cce449145f8b361e70b3ed4ae9a/files/WS%20T%20872%E2%80%942025-20250930105429913.pdf)。发布于 2025-09-19，自 2026-03-01 实施；测量见第 5 章、疑诊与诊断见第 6–7 章、转诊见 8.4。
- **[M2] 国家心血管病中心 2025 指南：** [官方下载页](https://hbp-office.nccd.org.cn/download.html)、[发布说明](https://hbp-office.nccd.org.cn/news-19.html)及[《国家基层高血压防治管理指南 2025 版》PDF](https://hbp-office.nccd.org.cn/files/%E5%9B%BD%E5%AE%B6%E5%9F%BA%E5%B1%82%E9%AB%98%E8%A1%80%E5%8E%8B%E9%98%B2%E6%B2%BB%E7%AE%A1%E7%90%86%E6%8C%87%E5%8D%972025%E7%89%88.pdf)，DOI `10.3969/j.issn.1000-3614.2025.09.002`；测量/诊断见 4.1–4.2，转诊见第 7 章。
- **[M3] NICE 医学规则：** [`NG136` Recommendations](https://www.nice.org.uk/guidance/ng136/chapter/recommendations)及[2026 现行 PDF](https://www.nice.org.uk/guidance/ng136/resources/hypertension-in-adults-diagnosis-and-managementpdf-66141722710213)；测量/确认见 1.1–1.2，同日专科评估见 1.5，页面标明最近更新 2026-02-26。
- **[R1] 中国来源使用声明：** [NCCD 官方下载页](https://hbp-office.nccd.org.cn/download.html)页脚为 `All Rights Reserved` 并声明未经允许不得用于商业用途；本轮没有发现授予本项目 AI/生产再利用的肯定许可，因此只作“权利未证明”，不作超出证据的法律结论。
- **[R2] NICE 国际与 AI 使用：** [国际使用说明](https://www.nice.org.uk/reusing-our-content/use-of-our-content-internationally)、[NICE UK open content licence](https://www.nice.org.uk/reusing-our-content/nice-uk-open-content-licence)、[Terms and conditions 的 Notice of Rights](https://www.nice.org.uk/terms-and-conditions#notice-of-rights)。国际非个人研究用途要求书面许可/许可协议；AI 请求全部须审批和许可，国际使用收费。
- **[R3] NICE 接口许可：** [NICE syndication API](https://www.nice.org.uk/reusing-our-content/nice-syndication-api)及[AI permission form](https://www.nice.org.uk/forms/permission-to-use-nice-content-for-artificial-intelligence-ai-purposes)，进一步区分测试许可与可向用户提供内容的完整许可。
- **[L1] 正式 Partner 与 Plugin：** [Evidence 19](19-current-partner-hermes-baseline-plugin-lifecycle-trust-20260820.md#L44-L57)，同日正式 Partner ordinary enabled Plugin 与 profile manifest 均为 0，仓库健康候选未部署。
- **[L2] 当前模型/问答/状态：** [Evidence 24](24-first-hop-model-route-owner-derived-query-isolation-nondiagnostic-answer-results-20260820.md#L7-L12)、[Evidence 22](22-managed-health-state-plane-protection-and-single-authority-20260820.md#L1-L80)与 [Evidence 23](23-six-domain-portrait-and-three-class-evidence-capabilities-20260820.md#L1-L48)。
- **[F1] 固定容量与终态：** [Evidence 16](16-health-model-context-capacity-token-accounting-overflow-20260818.md#L49-L90)，固定 `codex_responses` 目标路线不下发结构化格式/真实输出 cap，且不保留足以证明完整性的终态信号。
- **[F2] 固定 Plugin 失败语义：** [Evidence 19 第 89–101 行](19-current-partner-hermes-baseline-plugin-lifecycle-trust-20260820.md#L89-L101)，Plugin 加载、Hook 与 Middleware 异常默认不能形成健康处理 fail-closed。
- **[W1] 单条血压候选：** [`autonomy.py`](../../../ops/partner-health-steward/plugin/health-autonomy/autonomy.py#L1715-L1739)及本报告记录的 SHA-256。
- **[W2] 旧问答结构：** [`health_turn_context.py`](../../../ops/partner-health-steward/sidecar/health_turn_context.py#L19-L32)、[`health_turn_answer.py`](../../../ops/partner-health-steward/health_turn_answer.py#L25-L36)及本报告记录的 SHA-256。
- **[W3] 通用 guard：** [`guard.py`](../../../ops/partner-health-steward/plugin/health-guard/guard.py#L123-L192)及本报告记录的 SHA-256。
- **[W4] 旧画像版本：** [`profile.py`](../../../ops/partner-health-steward/sidecar/profile.py#L726-L829)及本报告记录的 SHA-256。
- **[W5] 限定搜索：** 2026-08-20 对 `ops/partner-health-steward` 执行大小写不敏感限定搜索，关键词为 `180/110|180/120|diagnostic_scope|diagnosis_scope|scope_registry|activated_scope|active_scope|current_diagnosis|diagnosis_revision|danger_unknown|safety_unavailable|安全能力不可用`，结果 `NO_MATCH`；证明边界只限当前工作树。
