# 【CAN】重建七个健康 Skill 交互合同后的完整能力链与追溯关系

Type: task
Status: resolved
Parent: [健康管家首发 TO、CAN 与 HOW 决策闭合路线](../map.md)
Blocked by: [【TO】确定七个健康 Skill 的主人交互入口、文档结构与能力边界](100-define-seven-health-skill-interaction-entry-document-and-capability-boundaries.md)

## Question

[【TO】确定健康 Skill 的必经使用、主人可见披露与回复结果](99-define-required-health-skill-use-visible-disclosure-and-reply-contract.md)、[【TO】确定七个健康 Skill 的主人交互入口、文档结构与能力边界](100-define-seven-health-skill-interaction-entry-document-and-capability-boundaries.md)与[【TO】确定危险升级时主人提示、预设支持联系人通知、记录与失败结果](101-define-danger-escalation-owner-prompt-and-support-contact-alert-contract.md)已实质改变现行完整 TO 的 Skill 必经使用与披露、七项交互合同、两级路由、最低安全例外、支持联系人接收方和失败结果，因此旧 C01—C17、CAN 闭合与统一 HOW 不能继续整体冒充当前权威。本票须针对**完整最新 TO**重建或重审技术能力链和双向追溯，不只为新增功能补一个发送接口。

至少完成：

1. 遍历当前全部 TO 的目标、主人结果、边界、不变量、失败结果和首发成功条件，尤其逐项纳入上述 Skill 必经使用、七项交互和危险支持联系人三项后继 TO；把每个 TO 节点映射到可调查的能力节点、链内依赖和所需证明事实，并从能力节点反向链接到 TO。
2. 逐项重审旧 C01—C17、全部现行 CAN Evidence 与[【HOW】选择健康管家的统一技术路线、权威职责与分层验证架构](98-choose-unified-health-steward-technical-route-and-authority-architecture.md)，分别标明“可继承、需要重查、已经失效”，不得按票号或旧 resolved 状态默认继承。
3. 显式覆盖七个健康 Skill 的发现、明确与自然入口、确定性加载、版本绑定、目的最小上下文取得与注入、零／一／多职责组合、真实使用披露、普通健康结果失败关闭，以及最低安全结果例外；同时覆盖初始化对预置联系人／联系方法／自动警报的实际披露与批准、资料范围和首跳边界变化后的重新说明／同意，以及时区切换从下一有效当地自然日继续且不补做旧复盘的能力。
4. 显式覆盖唯一消息准入后的粗分流、`health-steward` 完整路由、非 Skill 安全最终裁决和 steward 不可用时的最低安全兜底；验证它们不会回退旧 `medical`、不会让职责 Skill 越权，也不会把普通 Hermes 或模型自述冒充受管健康结果。
5. 显式覆盖单一支持联系人、初始化披露与主人批准、最小警报／必要纠正、发送与到达分层、失败／未知／有限重试冻结、独立控制、停止记录、永久删除和旧状态防复活所需能力。
6. 显式覆盖六域主题视图、三类证据卡与四类关系、待澄清候选、近期五张明细、受保护例外、滚动历史摘要、画像与证据的候选回传／权威提交，以及任务三类候选来源、统一建档门槛、任务框架权威和自动事件上下文。
7. 为已经能够准确表述且共享连贯技术表面和证据链的能力节点，创建并接线最少的后继 CAN 调查 Tickets；尚不能准确形成调查问题的 fog 留在 Map 的 `Not yet specified`。本票不执行调查实验、不选择组件组合或 HOW，也不预建 CAN 闭合或 HOW 修订票。

完成条件：完整最新 TO 的每一项均有双向 CAN 追溯；旧能力事实与 HOW 逐项完成继承／重查／失效分类；后继调查票、直接依赖和当前 Frontier 均准确；尚未能出票的 fog 清楚；本票形成唯一 `## Answer`，且不选择技术路线。

## Answer

本票以[【TO】闭合首发健康管家的完整产品合同与成功条件](75-close-first-release-health-steward-product-contract.md)为原完整 TO，并以[【TO】确定健康 Skill 的必经使用、主人可见披露与回复结果](99-define-required-health-skill-use-visible-disclosure-and-reply-contract.md)、[【TO】确定七个健康 Skill 的主人交互入口、文档结构与能力边界](100-define-seven-health-skill-interaction-entry-document-and-capability-boundaries.md)和[【TO】确定危险升级时主人提示、预设支持联系人通知、记录与失败结果](101-define-danger-escalation-owner-prompt-and-support-contact-alert-contract.md)为后继实质修订；后继 Answer 与旧 TO 冲突时以后继为准。完整最新 TO 归一为 T01—T36，技术能力链归一为 K01—K21。能力节点只定义 CAN 必须证明什么，不预选实现组件、接口组合或 HOW。

### 权威与当前状态

- **已证明但只能有界继承**：固定版本源码、特定日期脱敏现场、一手医学来源和其明确证据边界内的事实；继承不等于当前现场、完整链或产品已经成立。
- **需要重新核验**：会随 2026-08-22 当前 Partner、七 Skill 交互合同、支持联系人接收方或集成边界变化的能力结论。
- **已经失效**：旧报告或路线作为“完整当前 CAN／HOW 权威”的地位；其中个别原语只能降级为历史调查输入。
- **尚未实现或尚未证明**：正式健康 Plugin、七 Skill 的当前安装与真实使用、两级路由、统一受管状态、联系人外部效果和真实主人／联系人验收。CAN 不把“尚未实现”误写成路线不可行，也不得把历史候选冒充已经部署。

当前处于 **CAN 阶段**。TO 已闭合；旧 CAN 闭合与统一 HOW 已因最新 TO 实质变更而失效。本票只建立新的调查结构，未执行调查实验、HOW、实现、部署或验收。

### K01—K21 能力节点、反向 TO 与调查归属

| 能力节点 | 必须证明的事实与负向边界 | 直接调查前提 | 反向服务的 TO | 当前调查归属 |
| --- | --- | --- | --- | --- |
| **K01 当前 Partner 基线、Plugin 生命周期与信任根** | 当前版本／提交／定制、健康资产现状、Plugin 启停卸载、全部人类入口、权限和可信前提可定位；安装或进程存活不等于健康能力，受控最高权限主体不在主动对抗承诺内。 | 无 | T01、T02、T34—T36 | [【CAN】核验当前 Partner、七个健康 Skill 资产加载与受管权威底座](103-verify-current-partner-seven-health-skill-assets-loading-and-managed-authority-foundation.md) |
| **K02 七 Skill 资产、发现、加载、版本与旧入口隔离** | 七个规范名与 A/B 角色、明确／自然入口、主文档／共享规则加载、版本指纹和真实使用分别可证明；动态状态不写入 Skill；旧 `medical` 不成为现行入口、别名或回退。 | K01 | T03—T14、T24、T31、T35、T36 | [【CAN】核验当前 Partner、七个健康 Skill 资产加载与受管权威底座](103-verify-current-partner-seven-health-skill-assets-loading-and-managed-authority-foundation.md) |
| **K03 唯一准入、初始化门禁、粗分流、来源与重投** | 唯一私聊准入及其他入口封闭；初始化前仅把明确初始化请求路由至 `health-init`，其他健康内容不识别、不读写、不进入健康或安全分流；初始化后明确非健康进普通 Hermes，健康／混合／未知只进 K04；来源不伪造，重投不静默吞掉或重复效果。 | K01；与 K02 共同支持 K04 | T02—T05、T13、T30、T33—T36 | [【CAN】核验唯一准入、两级健康路由、职责组合、权威结果与独立最低安全能力](104-verify-admission-two-stage-routing-duty-composition-authoritative-result-and-minimum-safety.md) |
| **K04 steward 协调、最小上下文、职责组合、使用证明与唯一回复** | 按目的取得最小投影，组合零／一／多职责；B 类不互调、不写入、不直接回复；候选回 steward；真实使用由系统证明；提交、披露、发送和到达分层；steward 不可用时普通结果失败关闭。 | K02、K03、K05 | T04—T15、T19、T20、T23、T31、T33、T35、T36 | [【CAN】核验唯一准入、两级健康路由、职责组合、权威结果与独立最低安全能力](104-verify-admission-two-stage-routing-duty-composition-authoritative-result-and-minimum-safety.md) |
| **K05 单一受管状态、保护、完整提交与结果事实底座** | 全部权威对象及副本清单、唯一引用、候选／最终隔离、完整提交、崩溃恢复和单一当前权威；普通 Session、Memory、日志或明文副本不成为第二真相；失败与未知可区分。 | K01 | T01、T03、T04、T07、T14—T19、T21、T23、T24、T27、T29、T31—T36 | [【CAN】核验当前 Partner、七个健康 Skill 资产加载与受管权威底座](103-verify-current-partner-seven-health-skill-assets-loading-and-managed-authority-foundation.md) |
| **K06 六域画像、预算化视图、更新与导出** | 单一六域画像及固定基础主题、主题变更批准、每主题唯一当前视图、忠实预算化显示、画像只链接证据和任务、更新真实结果及不成为第二权威的导出。 | K05、K07 | T01、T09、T16、T19、T20、T34—T36 | [【CAN】核验受管领域状态、任务时序、主人控制、删除、观测与迁移能力](105-verify-managed-domain-state-tasks-controls-local-day-deletion-observation-and-migration.md) |
| **K07 三类证据、四类关系、待澄清与有界历史** | 三类证据不可互换；独立主张一张卡；四类关系可追溯；未准入材料不支撑结果；近期五张、保护例外、至少三张旧卡摘要门槛和滚动谱系不抹去转折与不确定性。 | K05 | T09—T12、T16—T20、T26—T29、T34—T36 | [【CAN】核验受管领域状态、任务时序、主人控制、删除、观测与迁移能力](105-verify-managed-domain-state-tasks-controls-local-day-deletion-observation-and-migration.md) |
| **K08 任务候选、建档、四职责、批准、四标签与验收** | 三类候选来源和完整建档门槛；任务框架独占建档／阶段／验收／标签；职责只回传候选；批准按当前有效性重判；未知外部效果冻结；终态以链接后继承接。 | K04、K05、K06、K07、K10 | T01、T11、T20—T24、T34—T36 | [【CAN】核验受管领域状态、任务时序、主人控制、删除、观测与迁移能力](105-verify-managed-domain-state-tasks-controls-local-day-deletion-observation-and-migration.md) |
| **K09 当地日调度、时区切换、通知、投递未知与恢复** | 每当地自然日一次；时区变化显示生效时间并从下一有效当地日继续，不补做、堆积或重复；无行动安静；普通通知分类、必要结果不被吞；发送层级和未知恢复不盲重做。 | K03、K05、K08、K10 | T21—T24、T29、T32—T36 | [【CAN】核验受管领域状态、任务时序、主人控制、删除、观测与迁移能力](105-verify-managed-domain-state-tasks-controls-local-day-deletion-observation-and-migration.md) |
| **K10 设置、独立控制与数据权利真实提交** | 时区、偏好、普通通知、停止记录、暂停支持、任务取消、批准撤回、联系人控制彼此独立；“关闭但保留”先澄清；查看／纠正／导出／删除和首跳变化时的本地权利成立。 | K03、K04、K05 | T04、T06、T08、T21—T25、T31、T32、T34—T36 | [【CAN】核验受管领域状态、任务时序、主人控制、删除、观测与迁移能力](105-verify-managed-domain-state-tasks-controls-local-day-deletion-observation-and-migration.md) |
| **K11 首跳路线、出站隔离与有依据非诊断问答** | 可定位并监视首跳；路线变化先暂停并重新同意；主人派生查询不进入路线外搜索／API／普通 Tool；问答有依据、不跨入残缺诊断且不长期保存完整回复。 | K01、K04、K05、K07、K10 | T12、T19、T25—T27、T34—T36 | [【CAN】核验首跳路线、查询隔离、医学治理、诊断完整性、安全与修订能力](106-verify-first-hop-query-isolation-medical-governance-diagnostic-integrity-safety-and-revision.md) |
| **K12 医学内容治理、范围候选与失效入口** | 有一手证据支撑内容权利路线、中文来源版本、审核入口、范围候选和撤回／过期观察；CAN 不要求已取得许可、完成审核、激活范围或通过主人验收。 | K05、K07、K11 | T12、T26—T30、T34—T36 | [明确诊断范围候选形成、准入与诊断全链能力核验](../evidence/25-named-diagnostic-scope-governance-and-full-chain-capabilities-20260820.md)与[成人疑似原发性高血压规范测量确认与同日转诊分流的完整诊断链核验](../evidence/27-adult-hypertension-measurement-confirmation-and-urgent-referral-chain-20260820.md)中的医学事实有界继承；当前状态与 Skill 集成由[【CAN】核验首跳路线、查询隔离、医学治理、诊断完整性、安全与修订能力](106-verify-first-hop-query-isolation-medical-governance-diagnostic-integrity-safety-and-revision.md)重核 |
| **K13 诊断资料选择、容量完整性、结构终态与最小留存** | 最小资料不漏关键项；处理前可证明输入、依据、安全条件和完整输出可容纳；静态窗口、粗估或事后 usage 不足；部分／截断候选不记录、不发送，临时资料闭合后清除。 | K04、K05、K06、K07、K11、K12 | T26—T29、T33、T35、T36 | [【CAN】核验首跳路线、查询隔离、医学治理、诊断完整性、安全与修订能力](106-verify-first-hop-query-isolation-medical-governance-diagnostic-integrity-safety-and-revision.md) |
| **K14 非 Skill 安全裁决与最低安全结果** | 初始化后，三分支严格区分；固定主人提示不由 LLM 临场生成；不形成普通业务或虚假 Skill 使用。最低求助结果不得依赖任何 Skill／steward／医学范围可用，只有可信危险升级才产生联系人警报候选。 | 硬依赖 K03、K05；确认危险的治理规则条件依赖 K12 | T13、T26、T28—T36 | [【CAN】核验唯一准入、两级健康路由、职责组合、权威结果与独立最低安全能力](104-verify-admission-two-stage-routing-duty-composition-authoritative-result-and-minimum-safety.md)核验独立最低安全路径；[【CAN】核验首跳路线、查询隔离、医学治理、诊断完整性、安全与修订能力](106-verify-first-hop-query-isolation-medical-governance-diagnostic-integrity-safety-and-revision.md)核验可信危险治理集成 |
| **K15 诊断修订链、依据失效、单一当前与必要纠错** | 合法改判原因、模型漂移不改判、一个问题／事件／时期至多一个当前或明确无当前、旧判断不覆盖、依据失效传播、权威未知不猜测、必要纠错只尝试一次。 | K04、K05、K07、K09、K12—K14 | T24、T28、T29、T33—T36 | [【CAN】核验首跳路线、查询隔离、医学治理、诊断完整性、安全与修订能力](106-verify-first-hop-query-isolation-medical-governance-diagnostic-integrity-safety-and-revision.md)；联系人纠正接口由[【CAN】核验危险支持联系人的批准、最小警报、分层交付、纠正、删除与防复活能力](107-verify-support-contact-approval-minimal-alert-delivery-correction-deletion-and-non-resurrection.md)接续 |
| **K16 单联系人配置、初始化披露、批准、路线当前性与最小负载** | 只允许一个当前联系人且无备用；初始化显示具体联系人／方法／作用；整体启用才授权；身份或路线变化使旧批准失效；联系人无健康权利且回复不回流；无联系人不阻断主人提示或产品。 | K02—K05、K10、K14 | T04、T06、T08、T23—T25、T30—T32、T35、T36 | [【CAN】核验危险支持联系人的批准、最小警报、分层交付、纠正、删除与防复活能力](107-verify-support-contact-approval-minimal-alert-delivery-correction-deletion-and-non-resurrection.md) |
| **K17 联系人外部效果、分层状态、有限重试、纠正与控制** | 仅确认危险且联系人／路线／批准有效才发送；未尝试至实际行动不越级；只有未发／明确拒绝才有限重试，可能已发即冻结且不换人；纠正只发同一有效联系人且未知不重发。 | K05、K09、K10、K14、K16 | T24、T25、T30—T36 | [【CAN】核验危险支持联系人的批准、最小警报、分层交付、纠正、删除与防复活能力](107-verify-support-contact-approval-minimal-alert-delivery-correction-deletion-and-non-resurrection.md) |
| **K18 全对象删除、防复活与空白再初始化** | 删除立即停止未来动作并清除全部本地健康状态、联系人、批准、未知和历史；无审计例外；旧备份／实例不得复活；不等待站外结果；以后只可由主人主动经 `health-init` 建立空白状态。 | K02、K05—K10、K15—K17 | T04、T23、T24、T32、T35、T36 | [【CAN】核验受管领域状态、任务时序、主人控制、删除、观测与迁移能力](105-verify-managed-domain-state-tasks-controls-local-day-deletion-observation-and-migration.md)核验通用底座；诊断对象由[【CAN】核验首跳路线、查询隔离、医学治理、诊断完整性、安全与修订能力](106-verify-first-hop-query-isolation-medical-governance-diagnostic-integrity-safety-and-revision.md)补完；联系人对象由[【CAN】核验危险支持联系人的批准、最小警报、分层交付、纠正、删除与防复活能力](107-verify-support-contact-approval-minimal-alert-delivery-correction-deletion-and-non-resurrection.md)补完 |
| **K19 三态业务观测、故障隔离与转换通知** | 状态来自业务事实而非进程存活；显示最近确认及影响；最后诊断范围、任务核心、唯一入口或当前权威失效准确传播；单项隔离故障和无联系人不误报全局异常；转换只通知一次。 | K01、K03、K05—K18 的业务状态 | T01、T02、T08、T22、T26、T34—T36 | [【CAN】核验受管领域状态、任务时序、主人控制、删除、观测与迁移能力](105-verify-managed-domain-state-tasks-controls-local-day-deletion-observation-and-migration.md)核验通用底座；模型／诊断状态由[【CAN】核验首跳路线、查询隔离、医学治理、诊断完整性、安全与修订能力](106-verify-first-hop-query-isolation-medical-governance-diagnostic-integrity-safety-and-revision.md)补完；联系人状态由[【CAN】核验危险支持联系人的批准、最小警报、分层交付、纠正、删除与防复活能力](107-verify-support-contact-approval-minimal-alert-delivery-correction-deletion-and-non-resurrection.md)补完 |
| **K20 权威文档、七 Skill 与受管状态完整迁移** | 文档、七 Skill、画像、证据、任务、批准、控制、诊断、安全、未知和历史完整；来源不改写；不依赖 LLM；失败时无双当前；批准和未发动作重判；删除／撤回不复活。 | K01、K02、K03、K05 及 K06—K19 的资产清单 | T04、T24、T35、T36 | [【CAN】核验受管领域状态、任务时序、主人控制、删除、观测与迁移能力](105-verify-managed-domain-state-tasks-controls-local-day-deletion-observation-and-migration.md)核验通用底座；模型／诊断资产由[【CAN】核验首跳路线、查询隔离、医学治理、诊断完整性、安全与修订能力](106-verify-first-hop-query-isolation-medical-governance-diagnostic-integrity-safety-and-revision.md)补完；联系人资产由[【CAN】核验危险支持联系人的批准、最小警报、分层交付、纠正、删除与防复活能力](107-verify-support-contact-approval-minimal-alert-delivery-correction-deletion-and-non-resurrection.md)补完 |
| **K21 端到端可观察性与未来真实验收承载面** | 未来可逐层观察初始化、Skill 使用、业务提交、发送、接口接受、主人／联系人到达、任务、安全和三态；明确官方保证、固定源码、当前现场与另批实验。当前只核验承载面，不执行真实验收。 | K01—K20 | T01、T14、T36 | 五张后继 CAN 调查票分别记录其链路的未来验证义务；不另建验收票 |

### T01—T36 到能力链的正向追溯

| TO 节点 | 当前产品结果 | 必须经过的能力链 |
| --- | --- | --- |
| **T01** | 产品目标、画像与任务两项核心、同一长期权威 | K01、K05、K06、K08、K19、K21 |
| **T02** | 唯一主人、唯一获准入口与信任边界 | K01、K03、K19 |
| **T03** | 初始化前只有初始化入口，健康内容不被识别、记录或倒填 | K02、K03、K05 |
| **T04** | 初始化、整体启用、正常重启／迁移持续及永久删除后空白重建 | K02、K03、K04、K05、K10、K16、K18、K20 |
| **T05** | 七 Skill 名单、A/B 角色、发现边界与旧 `medical` 退出 | K02、K03、K04 |
| **T06** | `health-init` 的最小披露、进度、提问与启用提交 | K02、K04、K10、K16 |
| **T07** | `health-steward` 的统一协调、候选与唯一回复 | K02、K04、K05 |
| **T08** | `health-settings` 的设置、控制、权利、状态与联系人入口 | K02、K04、K10、K16、K19 |
| **T09** | `health-portrait` 的最小读取、画像候选与禁止直接写入 | K02、K04、K06、K07 |
| **T10** | `health-evidence` 的证据候选、关系、纠正与压缩边界 | K02、K04、K07 |
| **T11** | `health-owner-inquiry` 的单一必要缺口、非诱导问题与候选回答 | K02、K04、K07、K08 |
| **T12** | `health-literature` 的知识缺口、来源边界与路线外查询禁止 | K02、K04、K07、K11、K12 |
| **T13** | 唯一准入后的保守粗分流、steward 完整路由与最低安全例外 | K02、K03、K04、K14 |
| **T14** | Skill 文档、版本、目的最小上下文、真实披露和主人回复结构 | K02、K04、K05、K21 |
| **T15** | 候选与最终隔离、权威提交和唯一当前真相 | K04、K05 |
| **T16** | 顶部当前状态、六域固定导航、预算化主题视图 | K05、K06、K07 |
| **T17** | 三类证据卡、唯一卡及四类关系 | K05、K07 |
| **T18** | 待澄清候选、近期五张、保护例外与滚动历史摘要 | K05、K07 |
| **T19** | 有依据问答、画像更新真实结果和非第二权威导出 | K04、K05、K06、K07、K11 |
| **T20** | 三类任务候选来源、统一建档门槛和画像锚点 | K04、K06、K07、K08 |
| **T21** | 任务框架、派发、批准、四标签、未知冻结和验收 | K05、K08、K09、K10 |
| **T22** | 当地日复盘、时区变化、主动支持与通知 | K08、K09、K10、K19 |
| **T23** | 设置、数据权利与彼此独立的控制 | K04、K05、K08、K09、K10、K16、K18 |
| **T24** | 永久删除、全对象防复活和空白重新初始化 | K02、K05、K08、K09、K10、K15—K18、K20 |
| **T25** | 首跳接收方、路线变化重新同意和主人派生查询隔离 | K10、K11、K16、K17 |
| **T26** | 医学内容权利、中文版本、审核、范围与失效门槛 | K07、K11—K14、K19 |
| **T27** | 诊断最小资料、容量完整性、结构终态与最小留存 | K05、K07、K11—K13 |
| **T28** | AI 判断、医生责任、正式诊断与处方边界 | K07、K12—K15 |
| **T29** | 判断修订链、依据失效、单一当前与必要纠错 | K05、K07、K09、K12—K15 |
| **T30** | 危险升级、危险未明、安全不可用三分支及固定主人结果 | K03、K12、K14、K16、K17 |
| **T31** | 单一联系人、初始化披露、主人批准与最小警报 | K02、K04、K05、K10、K14、K16、K17 |
| **T32** | 联系人交付层级、有限重试、纠正、独立控制与留存／删除 | K05、K09、K10、K14、K16—K18 |
| **T33** | 失败关闭、结果未知、重投和交付真实性分层 | K03、K04、K05、K09、K13—K15、K17 |
| **T34** | 活跃／异常／无法确认三态、故障隔离与稳定运行 | K01、K03、K05—K12、K14、K15、K17、K19 |
| **T35** | 文档、七 Skill 与全部受管状态的完整迁移 | K01—K20 |
| **T36** | 完整首发、真实主人微信端到端验收与明确不承诺 | K01—K21 |

审计结果：T01—T36 均至少映射一个能力节点，K01—K21 均反向服务至少一个 TO 节点，没有孤儿 TO 或孤儿能力节点。

### 链内依赖与调查图

- K01 是当前事实根；K02、K03、K05 和 K11 的当前性都以它为起点。
- K02 + K03 + K05 → K04。K04 调查协调、候选交接和提交接口，不要求先实现领域对象；K06/K07 调查领域语义，二者的完整运行反馈环留到 K21 的未来验证义务，避免为出票制造循环。
- K04 + K05 → K06、K07、K10；K04 + K06 + K07 + K10 → K08、K11；K03 + K05 + K08 + K10 → K09。
- K05 + K07 + K11 → K12；K04 + K05 + K06 + K07 + K11 + K12 → K13。
- K14 的硬前提只有 K03 与 K05；确认危险的治理规则可以条件使用 K12，但安全能力不可用时的最低求助提示不得依赖 K02、K04、K12 或任何 Skill 可用。
- K04 + K05 + K07 + K09 + K12 + K13 + K14 → K15。
- K02 + K03 + K04 + K05 + K10 + K14 → K16；K05 + K09 + K10 + K14 + K16 → K17。
- K02 + K05—K10 + K15—K17 → K18；K01 + K03 + K05—K18 → K19。
- K01、K02、K03、K05 以及 K06—K19 产生的完整资产清单 → K20；K01—K20 → K21。

后继调查按共享候选表面、链内直接前提和一个 Ticket 会话可判定范围压缩为五张连续 Research Tickets：

1. [【CAN】核验当前 Partner、七个健康 Skill 资产加载与受管权威底座](103-verify-current-partner-seven-health-skill-assets-loading-and-managed-authority-foundation.md)：K01、K02、K05。
2. [【CAN】核验唯一准入、两级健康路由、职责组合、权威结果与独立最低安全能力](104-verify-admission-two-stage-routing-duty-composition-authoritative-result-and-minimum-safety.md)：K03、K04 及 K14 不依赖 Skill 的独立最低安全路径。
3. [【CAN】核验受管领域状态、任务时序、主人控制、删除、观测与迁移能力](105-verify-managed-domain-state-tasks-controls-local-day-deletion-observation-and-migration.md)：K06—K10 及通用 K18—K20。
4. [【CAN】核验首跳路线、查询隔离、医学治理、诊断完整性、安全与修订能力](106-verify-first-hop-query-isolation-medical-governance-diagnostic-integrity-safety-and-revision.md)：K11—K15，含 K14 的可信危险治理集成及诊断侧 K18—K21。
5. [【CAN】核验危险支持联系人的批准、最小警报、分层交付、纠正、删除与防复活能力](107-verify-support-contact-approval-minimal-alert-delivery-correction-deletion-and-non-resurrection.md)：K16、K17 及联系人侧 K18—K21。

原生直接依赖按“本票 → [【CAN】核验当前 Partner、七个健康 Skill 资产加载与受管权威底座](103-verify-current-partner-seven-health-skill-assets-loading-and-managed-authority-foundation.md) → [【CAN】核验唯一准入、两级健康路由、职责组合、权威结果与独立最低安全能力](104-verify-admission-two-stage-routing-duty-composition-authoritative-result-and-minimum-safety.md) → [【CAN】核验受管领域状态、任务时序、主人控制、删除、观测与迁移能力](105-verify-managed-domain-state-tasks-controls-local-day-deletion-observation-and-migration.md) → [【CAN】核验首跳路线、查询隔离、医学治理、诊断完整性、安全与修订能力](106-verify-first-hop-query-isolation-medical-governance-diagnostic-integrity-safety-and-revision.md) → [【CAN】核验危险支持联系人的批准、最小警报、分层交付、纠正、删除与防复活能力](107-verify-support-contact-approval-minimal-alert-delivery-correction-deletion-and-non-resurrection.md)”串联。因此本票解决后唯一 Frontier 是[【CAN】核验当前 Partner、七个健康 Skill 资产加载与受管权威底座](103-verify-current-partner-seven-health-skill-assets-loading-and-managed-authority-foundation.md)。K21 不是验收执行票；真实微信、真实健康资料、真实联系人发送、破坏性故障和产品级验收均须以后另行批准。

### 旧 C01—C17 权威分类

“可继承（有界）”只表示原证据边界内的医学或固定事实仍可作输入，不表示对应能力、当前现场或完整 CAN 已成立。旧 C01—C17 作为一套“完整当前链”已经失效；仅 C09、C10 的医学来源与范围候选事实无需因本次 Skill／联系人 TO 变化而从零重做，其余节点均须按 K01—K21 重核。

| 旧节点 | 分类 | 可继承边界与当前处理 |
| --- | --- | --- |
| C01 当前基线、Plugin 生命周期与可信执行 | 需要重新核验 | 固定版本扩展面和 fail-open／部分注册反例可作输入；当前版本、七 Skill／Plugin 资产、权限与信任根由 K01/K02 重核。 |
| C02 能力入口、初始化门禁与真实结果 | 需要重新核验 | 入口种类及发现／调用／提交／返回／到达不等价可继承；`health-init`、`health-steward` 必经使用、版本、系统披露和最低安全例外由 K02—K04/K14 重核。 |
| C03 唯一微信准入、来源、重投与交付 | 需要重新核验 | 固定 iLink/Hermes 的 cursor、正文去重、合批、来源丢失和发送分层反例可作输入；当前粗分流、逐条来源、唯一回复与联系人链重核。 |
| C04 受管状态、保护隔离与单一权威 | 需要重新核验 | 存储／密码学／原子替换原语及普通 Session/Memory/旧 sidecar 不足可作输入；七 Skill 使用事实、联系人／批准／警报／纠正／未知等完整对象由 K05 重核。 |
| C05 六域画像与三类证据 | 需要重新核验 | 六域、三类证据和引用不复制仍相关；[【TO】确定七个健康 Skill 的主人交互入口、文档结构与能力边界](100-define-seven-health-skill-interaction-entry-document-and-capability-boundaries.md)的显示预算、四类关系、五张窗口、保护例外、滚动摘要与 B 类职责写权链由 K06/K07 重核。 |
| C06 开放任务与四项职责 | 需要重新核验 | 任务／dispatch／调度局部原语和旧状态反例可作输入；三类候选、统一门槛、A/B 职责交接、自动事件和四标签由 K08/K09 重核。 |
| C07 每日复盘、通知与投递恢复 | 需要重新核验 | 固定 Cron、当地日、接口接受／未知和防重原语可作输入；时区从下一有效当地日生效、不补做、Skill 披露与联系人控制隔离由 K09/K10 重核。 |
| C08 首跳路线与主人派生查询隔离 | 需要重新核验 | 固定配置／`ctx.llm`／JOJO 的 fallback 和路线外回源反例可作输入；当前首跳、全部出站、七 Skill 最小上下文和独立联系人接收方重核。 |
| C09 医学内容治理与范围候选 | 可继承（有界） | BMI／高血压一手来源、权利不确定性、许可入口和审核职责可继承；当前许可、中文版本、审核、Skill 集成、激活或上线均未证明。 |
| C10 明确诊断范围专属准入 | 可继承（有界） | BMI／高血压候选的适用人群、资料、输出、排除、危险、失效和验收边界可继承；当前未选中、未许可、未审核、未验收、未激活。 |
| C11 诊断资料、容量与结构终态 | 需要重新核验 | 静态窗口、粗 token 估算、事后 usage、`stop` 与旧 adapter 终态丢失等反例可作输入；当前模型／adapter 的容量、完整性和提交边界重核。 |
| C12 范围隔离与安全分支 | 需要重新核验 | 提示词／Skill／通用 fail-open Hook 不能充当安全闸门的负向事实可继承；非 Skill 最低兜底、固定主人提示和联系人只在确认危险时触发由 K14/K16/K17 重核。 |
| C13 诊断修订链与当前判断 | 需要重新核验 | 不可变版本、current pointer 和依赖失效原语可作输入；现行 Skill 交接、单一当前及已／可能外发警报后的必要纠正链重核。 |
| C14 主人权利、分离控制、删除和防复活 | 需要重新核验 | 控制分离和 CAS/current-head 防复活候选可作输入；联系人暂停／撤回／变更、批准失效、警报状态删除和旧状态不复活由 K10/K18 重核。 |
| C15 三态业务观测与故障隔离 | 需要重新核验 | 进程／Cron 存活不等于业务健康及外部观察表面可作输入；七 Skill、入口、权威和联系人状态传播由 K19 重核。 |
| C16 权威资产完整迁移 | 需要重新核验 | manifest、staging、hash、备份校验及“只复制部分资产不足”可作输入；七 Skill／共享规则／版本、联系人／批准／未知／删除状态的完整迁移由 K20 重核。 |
| C17 有依据的非诊断健康问答 | 需要重新核验 | 自由正文不足、个人事实／一般知识区分和交付分层可作输入；steward 必经使用、职责组合、真实披露、唯一回复和最低安全例外由 K04/K11/K14 重核。 |

### Evidence 01—29 权威分类

| Evidence | 分类 | 精确继承边界或重核原因 |
| --- | --- | --- |
| [01 Partner Hermes 真实服务器基线](../evidence/01-live-partner-baseline-20260807.md) | 需要重新核验 | 仅是 2026-08-07 运行现场快照和观察方法；不能证明 2026-08-22 当前版本、资产、渠道或健康能力。 |
| [02 目标 Hermes 扩展面基线](../evidence/02-target-hermes-extension-baseline-20260816.md) | 可继承（有界） | 只继承 Hermes v0.20.0／`3c27…` 下 Skill 为按需文档、Plugin 为执行扩展面及 Hook/Middleware 非天然 fail-closed；不证明当前版本或七 Skill。 |
| [03 渠道、主人及来源能力](../evidence/03-channel-owner-provenance-capabilities-20260816.md) | 可继承（有界） | 固定 v0.20.0 的渠道准入、来源、去重／合批和接口接受≠主人到达；不证明当前 allowlist、两级路由或联系人链。 |
| [04 调度、投递、恢复与运行状态](../evidence/04-scheduling-delivery-recovery-runtime-status-capabilities-20260816.md) | 可继承（有界） | 固定版本 Cron、时区、未知、接口接受和恢复语义；不证明当前 jobs、当地日账本或联系人投递。 |
| [05 健康记录、权利与保护](../evidence/05-health-record-data-rights-and-protection-capabilities-20260816.md) | 可继承（有界） | 固定版本 Session/Memory/Plugin/普通备份的边界和反例；不证明当前统一状态、对象清单或永久删除。 |
| [06 诊断推理、知识与安全](../evidence/06-diagnostic-reasoning-knowledge-safety-capabilities-20260816.md) | 可继承（有界） | 固定版本 fail-open 限制及当时 `medical` 缺陷；不证明七 Skill、非 Skill 最低安全或联系人全链。 |
| [07 iLink 入站与重放语义](../evidence/07-weixin-ilink-inbound-contract-and-replay-semantics-20260816.md) | 可继承（有界） | 腾讯 iLink v2.4.6 文档／源码下 cursor、可选字段、重投与逐条确认边界；不证明当前版本或端到端到达。 |
| [08 iLink—Hermes 接口能力](../evidence/08-weixin-ilink-target-hermes-interface-capabilities-20260816.md) | 可继承（有界） | iLink v2.4.6 + Hermes `3c27…` 的 merge/dedupe/cursor/send-result 边界；不证明当前健康路由、唯一回复或联系人到达。 |
| [09 科学健康画像结构](../evidence/09-scientific-health-portrait-structure-20260817.md) | 可继承（有界） | 引用的一手科学构念与结构事实可继承；当时七域综合不是当前权威，当前以六域 TO 和[【TO】确定七个健康 Skill 的主人交互入口、文档结构与能力边界](100-define-seven-health-skill-interaction-entry-document-and-capability-boundaries.md)预算为准。 |
| [10 健康数据平面工具与接口](../evidence/10-health-data-plane-tools-and-interfaces-20260817.md) | 可继承（有界） | v0.20.0 已确认原语及确定性限制；不证明当前依赖、服务可用、统一状态路线或合同成立。 |
| [11 模型路线与接收方事前锁定](../evidence/11-health-model-routing-and-recipient-preflight-20260817.md) | 可继承（有界） | 相同 commit/config/relay 下 `ctx.llm` 与当时 JOJO 路线不能事前证明全部首跳／fallback；不证明当前路线或接收方合同。 |
| [12 医学知识与安全强制工具](../evidence/12-medical-knowledge-and-safety-enforcement-tools-20260817.md) | 可继承（有界） | 一手医学来源角色、许可 caveat 和固定安全工具 fail-open 事实；不证明当前许可、中文版本、审核、激活范围或联系人集成。 |
| [13 主人身份迁移与恢复](../evidence/13-owner-identity-migration-recovery-capabilities-20260818.md) | 已失效（目标） | 配对、备份、SQLite 等通用原语仅作历史输入；已取消账号迁移／恢复目标不能恢复为当前链。 |
| [14 每日复盘、投递恢复与跨故障状态](../evidence/14-daily-review-delivery-recovery-cross-fault-status-tools-20260818.md) | 可继承（有界） | 固定调度、systemd、状态和外部观察原语；不证明当前任务、当地日账本、三态、自动事件或联系人警报。 |
| [15 能力发现、调用与结果契约](../evidence/15-health-capability-discovery-invocation-result-contract-20260818.md) | 可继承（有界） | Skill/Tool/Command/Cron/dispatch 的发现、调用、提交、返回、到达不等价；不证明当前七个规范 Skill 已安装或经 steward 协调。 |
| [16 模型上下文容量与超限](../evidence/16-health-model-context-capacity-token-accounting-overflow-20260818.md) | 可继承（有界） | 相同 `codex_responses` 适配器／路线下 token、输出终态和 incomplete/failed 丢失缺陷；不证明当前容量或 Skill 上下文完整性。 |
| [17 主人身份权威锚点](../evidence/17-owner-identity-authority-anchor-capabilities-20260818.md) | 已失效（目标） | CAS／代际／anti-rollback 原语只能作删除防复活历史候选；身份代际目标已经取消。 |
| [18 域外主人代际权威候选](../evidence/18-external-owner-generation-authority-candidates-20260818.md) | 已失效（目标） | 强一致 KV／generation 条件对象等只能作通用候选；不能证明实际账号、地域、权限、费用、canary 或已选外部权威。 |
| [19 当前 Partner 基线、Plugin 生命周期与信任](../evidence/19-current-partner-hermes-baseline-plugin-lifecycle-trust-20260820.md) | 需要重新核验 | 2026-08-20 现场和固定源码失败语义只作起点；不证明 2026-08-22 当前基线、七 Skill／旧 `medical` 隔离或完整信任根。 |
| [20 入口、初始化门禁与结果](../evidence/20-health-capability-entry-initialization-gate-result-contract-20260820.md) | 需要重新核验 | 旧入口类别和分层反例可作输入；未覆盖 Skill 必经使用、系统披露、版本绑定和最低安全例外。 |
| [21 唯一微信准入、路由、来源与重投](../evidence/21-unique-weixin-admission-routing-provenance-replay-results-20260820.md) | 需要重新核验 | 旧微信链固定反例可作输入；未覆盖当前粗分流、steward 完整路由、唯一回复和联系人外发。 |
| [22 受管状态、保护与单一权威](../evidence/22-managed-health-state-plane-protection-and-single-authority-20260820.md) | 需要重新核验 | 已发现原语和旧反例可作输入；未覆盖七 Skill 使用事实、联系人／批准／警报／纠正／未知等完整对象。 |
| [23 六域画像与三类证据](../evidence/23-six-domain-portrait-and-three-class-evidence-capabilities-20260820.md) | 需要重新核验 | 旧工作树局部原语可作输入；未覆盖[【TO】确定七个健康 Skill 的主人交互入口、文档结构与能力边界](100-define-seven-health-skill-interaction-entry-document-and-capability-boundaries.md)的显示预算、四类关系、五张窗口、保护例外、滚动摘要和 B 类职责权威。 |
| [24 首跳路线、派生查询与非诊断回答](../evidence/24-first-hop-model-route-owner-derived-query-isolation-nondiagnostic-answer-results-20260820.md) | 需要重新核验 | 旧 route/egress/free-text 反例可作输入；未覆盖当前首跳、最小上下文、七 Skill 使用／披露和唯一回复。 |
| [25 命名诊断范围治理与全链能力](../evidence/25-named-diagnostic-scope-governance-and-full-chain-capabilities-20260820.md) | 可继承（有界） | BMI／高血压候选名称、来源差异、医学约束和许可边界；不证明许可、审核、激活、七 Skill／联系人集成或部署。 |
| [26 健康任务与受管运行旅程](../evidence/26-health-task-managed-runtime-state-journey-capabilities-20260820.md) | 需要重新核验 | 旧任务／调度／控制／观测原语和反例可作输入；未覆盖三类候选、统一门槛、A/B 职责、时区新合同、联系人控制和完整迁移。 |
| [27 成人高血压测量确认与紧急分流](../evidence/27-adult-hypertension-measurement-confirmation-and-urgent-referral-chain-20260820.md) | 可继承（有界） | 指定一手来源下的测量、确认、紧急转诊和许可差异；不证明当前版本／权利／审核、激活范围或实现。 |
| [28 完整当前能力与约束报告](../evidence/28-complete-current-capability-and-constraint-report-20260820.md) | 已失效（完整当前权威） | 仅保留为 2026-08-20 旧 TO 下的历史 CAN 索引；不能再证明完整 CAN 已闭合、C01—C17 完整或可直接进入旧 HOW。 |
| [29 七 Skill 上下文加载与 token 效率](../evidence/29-hermes-seven-health-skill-context-loading-and-token-efficiency-20260821.md) | 可继承（有界） | Hermes v0.20.0 下 Skill index、`skill_view`、slash 全文加载、Plugin Skill 可发现性、描述截断、链接文件和重复 token 行为；不证明七 Skill 已安装、确定选择、取得正确上下文、实际使用或披露。 |

以上 29 份 Evidence 中，17 份可有界继承、8 份需要重新核验、4 份作为当前目标或完整权威已经失效。任何一份都不能单独证明实现、部署、正式上线、稳定运行或真实主人／联系人验收。

### 旧 CAN 闭合与统一 HOW

- [【CAN】闭合完整能力与约束事实并形成当前 CAN 报告](77-close-complete-capability-and-constraint-report.md)及[完整健康管家当前能力与约束报告](../evidence/28-complete-current-capability-and-constraint-report-20260820.md)作为“完整 CAN 已闭合”的当前权威已经失效，只保留 2026-08-20 旧 TO 下的历史报告和证据索引。
- [【HOW】选择健康管家的统一技术路线、权威职责与分层验证架构](98-choose-unified-health-steward-technical-route-and-authority-architecture.md)与[ADR 0021](../../../docs/adr/0021-use-one-plugin-owned-health-core-and-governed-authority-stack.md)作为当前统一 HOW／选定路线已经失效。`health_weixin`、私有 `health-core`、SQLite、DynamoDB current head、`StrictHealthLLM`、KnowledgePublisher、BMI 首发范围或旧 C01—C17 模块归属都不得继承为当前选择。
- 旧 HOW 中“单一权威、候选不等于提交、发送／接受／到达分层、unknown 不盲重试、防复活”等若继续成立，其权威来自最新 TO，而不是旧 HOW。旧组件和设计理由只能作为后继 HOW 的历史候选，不能证明实现、部署或验收。

### Fog、Frontier 与阶段停止线

- 当前没有无法准确表述的能力节点 fog：K01—K21 已全部出票、分配到连续调查或由有界医学 Evidence 承接；没有发现需要返回 TO 的产品冲突。
- 尚不能准确出票的是五张调查完成后的**完整 CAN 闭合审计**及其后的**统一 HOW 修订问题**；它们取决于调查产生的当前事实、No-Go、外部前提和未知，继续留在 Map 的 `Not yet specified`，本票不预建。
- 本票解决后唯一未阻塞且未认领 Frontier 是[【CAN】核验当前 Partner、七个健康 Skill 资产加载与受管权威底座](103-verify-current-partner-seven-health-skill-assets-loading-and-managed-authority-foundation.md)。没有 HOW Frontier。
- `ops/` 代码、旧 ADR、旧 Spec 和未部署工作树继续只是历史实现或审计输入，不是现行已选技术路线。
- 本票及其只读审计没有读取或上传真实健康资料、聊天正文、联系人、密钥、Token、服务器配置或运行数据库，也没有执行网络、正式状态修改、真实发送、部署或验收。到此停在 Wayfinder 的 CAN 能力链拆分边界。
