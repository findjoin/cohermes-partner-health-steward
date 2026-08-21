# 辅助诊断、医学知识与安全边界能力核验

核验时间：2026-08-16（Asia/Shanghai）  
目标版本：Hermes Agent v0.20.0（2026.8.3），现场提交 `3c27eb6234bf91b8ceee9e9071591b31e9b148cb`  
对应票据：[核验辅助诊断、医学知识与安全边界能力](../issues/46-verify-diagnostic-reasoning-knowledge-and-safety-capabilities.md)

## 1. 范围与证据纪律

本报告只回答 CAN：目标 Hermes 是否提供足够的正式扩展空间，承接最小个人证据、辅助诊断、可追溯医学知识、缺失事实追问以及急症、自伤、危险用药和处方药边界。它不选择 Plugin、Adapter、模型、知识库、规则、阈值或部署方案，也不执行健康问答验收。

证据分为三层：固定提交的官方文档与源码、目标 Partner 当前现场的只读状态、从正式扩展契约得到的有限推断。旧 ADR、旧 Spec、旧 Tickets、旧 sidecar 与历史测试不作为当前能力证明。

现场核验为只读：没有修改文件、重启服务、发送微信消息、调用模型或执行网页搜索；没有读取聊天、Memory、数据库、日志正文、`.env`、认证材料或渠道身份值。

## 2. 结论

Hermes v0.20.0 提供 Plugin 自行构造最小输入并发起独立结构化模型调用、注册 Tool/Skill/Platform Adapter，以及通用网页搜索与提取的扩展面。这些能力保留了实现当前产品目标的空间。

Hermes 原生没有健康证据模型、AI 判断与医生诊断的领域分离、医学来源可信度策略、诊断质量保证、急症/自伤/危险用药分类器或处方建议强制边界。JSON Schema 只约束输出形状；URL 只说明资料来自哪里；Skill、Hook、Middleware 和工具权限均不能单独构成不可绕过的医疗安全闸门。

目标现场目前也没有健康 Plugin、受控辅助诊断流程、医学来源库或健康安全闸门。现有 community `medical` Skill 与当前 TO 冲突且存在明显缺陷，不能当作产品能力或验收证据。

因此本票不创建 TO-CAN 差距决策，也不降低 TO。这里的结论只是“正式扩展面仍有实现空间”，不是“目标模型已经具备医疗质量”或“健康管家已经实现”。

## 3. TO-CAN 矩阵

| 产品边界 | Hermes 原生事实 | 正式扩展空间 | 当前判定 |
|---|---|---|---|
| 只向模型提供当前问题所需的最小个人证据 | 普通 Agent 路径没有健康证据最小化保证 | Plugin 的 `ctx.llm` 由插件自行构造一次调用的消息与输入 | 可以承接，尚未实现 |
| 分开保存主人事实、主人转述的医生诊断与 AI 判断 | 没有这些健康领域字段或提交规则 | Plugin 可定义结构化字段和专用状态 | 可以承接，结构和真实性均未验证 |
| 给出可能诊断、支持/反对证据、缺失信息、紧急度和下一步 | 通用模型和 JSON Schema 没有医学正确性保证 | Plugin 可要求结构化结果并在自己的路径中处理 | 可以表达，诊断质量尚未验证 |
| 只询问缺失事实，不用疾病标签诱导主人 | 没有语义检查器或原生规则 | Plugin 可构造提示、字段与后续问题 | 可以表达，行为保证与验收尚未建立 |
| 使用可追溯且可信的医学知识 | Web 工具保留 URL、标题和正文；没有临床来源等级、版本或逐结论引用校验 | Plugin 可注册受控知识 Tool 或只读 Skill | 来源位置可追溯，医学可信度能力尚未实现 |
| 急症、自伤和危险用药时优先安全升级 | 没有医疗专用分类器或固定升级规则 | 正式 Adapter/Plugin 路径仍可在普通 Agent 前承接处理 | 有实现空间，当前无不可绕过控制 |
| 不擅自建议开始、停止或调整处方药 | `ctx.llm` 没有工具循环，但普通 Agent 可直接输出文字建议 | 专用健康路径可对生成与发送实行受控处理 | 原生不保证，当前未实现 |

## 4. 最小输入与结构化模型调用

Plugin 的 `ctx.llm` 是对话循环之外的一次模型调用。Plugin 自行提供 `messages`，或 `instructions + input`，所以能够只发送它已选择的必要字段；这不同于普通 Agent 自动携带会话上下文。[官方 Plugin LLM 合同](https://github.com/NousResearch/hermes-agent/blob/3c27eb6234bf91b8ceee9e9071591b31e9b148cb/website/docs/developer-guide/plugin-llm-access.md#L7-L84) [消息构造源码](https://github.com/NousResearch/hermes-agent/blob/3c27eb6234bf91b8ceee9e9071591b31e9b148cb/agent/plugin_llm.py#L374-L484)

`complete_structured` 可以要求 JSON 形状，但请求使用 `strict=false`；本地只有安装可选的 `jsonschema` 时才执行 schema 校验。即使校验通过，也只证明字段形状满足约束，不能证明诊断、证据、紧急度或来源是真实和医学正确的。[结构化调用源码](https://github.com/NousResearch/hermes-agent/blob/3c27eb6234bf91b8ceee9e9071591b31e9b148cb/agent/plugin_llm.py#L683-L773) [本地校验边界](https://github.com/NousResearch/hermes-agent/blob/3c27eb6234bf91b8ceee9e9071591b31e9b148cb/agent/plugin_llm.py#L897-L917)

以下常见模型参数没有医学含义：

- `temperature` 是生成采样的随机性；设为 0 只能降低随机性，不能保证诊断正确。
- `max_tokens` 是一次回答最多生成的 token 数，不是诊断覆盖范围或安全阈值。
- `timeout` 是等待模型响应的秒数，不是急症响应期限。

当前模型/provider 还可能因连接、限流或兼容性错误进入 fallback；结果对象能够记录实际 provider/model，但事后归因不能代替调用前的数据接收方同意，也不能证明医疗能力。[fallback 源码](https://github.com/NousResearch/hermes-agent/blob/3c27eb6234bf91b8ceee9e9071591b31e9b148cb/agent/auxiliary_client.py#L9012-L9111)

## 5. 医学知识与来源

通用 `web_search` 返回标题、URL、描述和排序位置，`web_extract` 返回 URL、标题、正文或错误；因此 Hermes 可以把资料位置带入后续处理。[Web 工具源码](https://github.com/NousResearch/hermes-agent/blob/3c27eb6234bf91b8ceee9e9071591b31e9b148cb/tools/web_tools.py#L558-L770)

但 URL 不等于可信医学证据。原生没有医疗来源白名单、临床证据层级、指南版本与发布日期、陈旧性判断、矛盾资料处理或逐条结论引用校验。`web_search.limit` 的物理含义只是最多返回多少条结果，源码限制为 1 至 100、默认 5；它不是证据质量分数。网页 `char_limit` 是每页进入处理的字符预算，过长正文可能被截断，也不是医学完整性保证。

Plugin 可以注册专用 Tool、Platform Adapter 或 Skill，因此存在建立受控来源入口的空间。[Plugin 扩展注册源码](https://github.com/NousResearch/hermes-agent/blob/3c27eb6234bf91b8ceee9e9071591b31e9b148cb/hermes_cli/plugins.py#L410-L446) [Skill 注册源码](https://github.com/NousResearch/hermes-agent/blob/3c27eb6234bf91b8ceee9e9071591b31e9b148cb/hermes_cli/plugins.py#L1217-L1230) 这仍然只是扩展合同，不是现成医学知识库。

## 6. 安全控制边界

固定提交中没有发现医疗专用的急症、自伤、危险用药或处方建议控制。现有通用控制也不能单独满足产品边界：

- `pre_gateway_dispatch` 可以停止或改写消息，但 Hook 调用异常时会记录警告并继续正常分发，属于 fail-open。[Gateway 调用点](https://github.com/NousResearch/hermes-agent/blob/3c27eb6234bf91b8ceee9e9071591b31e9b148cb/gateway/run.py#L13355-L13396)
- Plugin Hook 的异常会被隔离并继续执行；提示注入不是强制规则。[Hook 调用源码](https://github.com/NousResearch/hermes-agent/blob/3c27eb6234bf91b8ceee9e9071591b31e9b148cb/hermes_cli/plugins.py#L1911-L1977)
- Middleware 能包裹或改写模型/工具调用，但回调在调用下游前失败时会继续原始下游路径，不能天然作为 fail-closed 医疗门。[Middleware 源码](https://github.com/NousResearch/hermes-agent/blob/3c27eb6234bf91b8ceee9e9071591b31e9b148cb/hermes_cli/middleware.py#L234-L292)
- `pre_tool_call` 只在模型决定调用工具后生效。普通 Agent 可以完全不调用工具而直接形成文字回答，所以“没有改药工具”不能防止它输出擅自调整处方药的建议。[普通回答路径](https://github.com/NousResearch/hermes-agent/blob/3c27eb6234bf91b8ceee9e9071591b31e9b148cb/agent/conversation_loop.py#L5885-L5902)
- 输出转换失败时会保留原模型回复，不能视为安全否决机制。[最终输出处理源码](https://github.com/NousResearch/hermes-agent/blob/3c27eb6234bf91b8ceee9e9071591b31e9b148cb/agent/turn_finalizer.py#L543-L563)

这些事实否定的是“直接把 Skill/Hook/Middleware/工具权限当安全闸门”，并不否定受支持的 Plugin Adapter 与插件自有代码可以建立独占健康路径。后者是否能在所有故障情况下失败关闭，必须由 HOW 与验收继续证明。

## 7. 目标 Partner 当前现场（只读）

2026-08-16 03:08–03:17 +08 的只读核验确认：

| 项目 | 存在或配置 | 启用 | 真实验证 |
|---|---|---|---|
| Partner Gateway | v0.20.0，提交 `3c27eb...48cb`，profile `partner` | active/running/enabled | 只验证服务与版本状态 |
| 通用模型配置 | `gpt-5.6-sol`、provider `jojo`、`codex_responses` | 配置已被当前服务加载 | 本轮未发模型请求，实际下游和医疗质量未验证 |
| 通用工具 | Web、Browser、Clarify、Memory、Session Search 等列为 enabled | 配置层启用 | 本轮未调用，医学检索与追问行为未验证 |
| 健康 Plugin | profile `plugins/` 为空，`plugins.enabled=[]` | 否 | 不存在可验证健康路径 |
| community `medical` Skill v1.1.0 | profile 中存在且可被 Skill 索引发现 | 是 | 只验证静态文件与配置，不代表诊断能力 |

现有 `medical` Skill 不能承接当前 TO：

- 它明确要求不得 diagnosis、triage 或给出 treatment advice，与当前已确认的 AI 辅助诊断目标冲突；不得用它反向缩小 TO。
- 它把数据目录写为 `~/.openclaw/workspace/memory/health`，该目录在现场不存在。
- 其外部 URL 只有 ClawHub 项目和作者页，未发现 WHO、CDC、NICE、国家卫健委、临床指南、引用链、审阅日期或版本元数据。
- 唯一急症检查位于 `add_symptom.py`，只匹配 9 个英文子串，且只有主动运行该脚本才会执行；命中分支调用 `sys.exit(1)` 却未导入 `sys`，不能作为可靠全局闸门。
- 用药交互样例只有 6 个主药条目，另一个录入脚本只有 4 条提示，均无医学来源或更新时间；文档引用的两个脚本在现场缺失。

因此现场只具备通用模型、搜索、追问和 community Skill 的候选能力。最小健康证据选择、医生诊断与 AI 判断分离、可追溯医学来源、辅助诊断流程，以及不可绕过的急症、自伤、危险用药和处方建议控制，均未实现或未验证。

## 8. 差距判断与后续边界

当前不创建 TO-CAN 差距票。正式 Plugin、Tool、Skill 与 Platform Adapter 使专用健康路径具备可实现空间；但这是从支持的扩展 API 得到的推断，不能宣称当前模型、Skill、Hook 或现场已经满足产品目标。

后续 HOW 需要决定的只是实现路线，包括：最小证据选择与结构化诊断合同、事实/医生转述/AI 判断的状态权威、医学来源准入与逐结论引用、不可绕过的危险分流与处方建议阻断、正常健康回复的发送边界，以及故障时是否真正失败关闭。本报告不替这些问题选择答案。

若后续证明任一首发聊天接口无法在普通 Agent 前进入受控健康路径、Plugin 故障时无法阻止不受控健康处理或发送，或候选模型在产品级医学验收中无法达到已确认目标，则必须新建 TO-CAN 差距决策交给主人选择，不能静默降低诊断、安全或隐私要求。
