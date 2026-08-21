# 健康能力入口、初始化门禁与真实结果返回能力（Ticket 79）

日期：2026-08-20

目标现场：正式 Partner Hermes，继承 Ticket 78 于 2026-08-20 12:41–12:49（Asia/Shanghai）的同一时点只读指纹

固定基线：Hermes Agent v0.20.0，提交 [`3c27eb6234bf91b8ceee9e9071591b31e9b148cb`](https://github.com/NousResearch/hermes-agent/commit/3c27eb6234bf91b8ceee9e9071591b31e9b148cb)

## Answer

**结论是“基础扩展原语存在，但 C02 产品能力当前为负向／未证明”。** `[FIXED-SOURCE]` Hermes v0.20.0 能注册 Skill、Plugin Tool、Plugin Command、Platform、Hook，并能从 Plugin 或 Cron 走内部调用；这些原语足以让后续实现继续接受 CAN 调查。可是 Hermes 没有原生的“健康管家已完整初始化”状态机、不可旁路的健康总门禁、跨入口统一业务事务，也不会把接口字符串自动提升为权威健康结果。Skill 只是按需知识；模型可以不选 Tool；Command 只收到 `raw_args`；`ctx.dispatch_tool` 绕过普通 Agent Tool 桥接；Cron 没有当前对话主人上下文；通用 Hook/Middleware 异常默认继续基础流程。注册、模型可见、主人可发现、调用开始、业务提交、权威状态改变、接口返回和主人真正收到因此是八个不同事实。[F1][F2][F3][F4][F5][F6]

`[LIVE]` 当前 Partner 没有 ordinary/user/project 健康 Plugin、没有 profile Plugin manifest、没有业务 Cron；Telegram 和 Weixin 同时处于 configured，CLI/chat、Cron、`send` 与 Gateway 内部 dispatch 等代码入口仍存在。因而现场没有可查询的初始化结果，也没有一项真实健康入口可证明已经由初始化门禁保护。服务存活、80 个 `SKILL.md`、7 个 local-enabled 管理项或普通 Plugin enabled 为零，均不能补出这项产品能力。[L1]

`[WORKTREE-CANDIDATE]` 当前仓库候选也不能作为正向答案。候选 `health-steward` Plugin 没有注册初始化 Skill、初始化 Tool 或初始化 Command；它注册两个面向每日复盘／到期任务派发的 Tool、一个只读投影 Hook 和 Weixin Platform。Weixin ingress 只把“启用健康记录”“我同意启用健康记录”两句精确文本当作启用，并调用一个只保存 recording consent 的接口。状态层明确允许 `recording_enabled` 先于第一份画像存在；初次画像在以后第一条候选健康消息写入时才创建，并直接默认 `owner_timezone=Asia/Shanghai`、`proactive_contact.paused=false`。这没有把资料范围、每日复盘、任务自动化、主动支持、首跳接收方、通知选择、主人权利、明确同意、主人确认的时区与偏好、初始画像封成一个完整初始化结果；连接在两步之间中断时，候选甚至已经显示 recording enabled。[W1][W2][W3][W4]

该候选还含 `expected_viewer`、身份恢复码与旧 Telegram Skill/自治代码；当前仓库的部署脚本候选虽显式排除 legacy `health-guard`/`health-autonomy` Plugin，`health-steward` 本身仍引用 viewer/recovery 控制。它们属于被当前 TO 取消或改变的旧合同，不能整体继承为当前初始化与唯一主人能力。[W5][W6]

所以当前只能确认：**有继续实现和验证所需的扩展空间；没有证据证明初始化是唯一可发现健康入口、部分初始化不会启用、初始化前所有健康效果为零且以后不倒填、初始化后所有自然语言／Skill／Tool／Command／内部 dispatch／自动路径进入同一受管边界，或任何入口返回了真实业务结果并让主人实际收到。** 本票不选择四项职责是否实现成四个 Skill，也不选择 Skill／Tool／Command／Platform 的最终映射。

## 1. 本票检验的场景，而不是技术名称

以下场景是当前产品合同的可证伪解释；它们来自 `CONTEXT.md` 的“健康管家未初始化”“健康能力入口”“健康管家初始化”“最终健康处理结果”和“健康结果交付事实”。[P1]

1. **初始化前谈健康。** 主人说“我最近睡不好”。基础 Hermes 可以按自己的普通聊天合同回复；健康管家不得分类这条消息、保存接收事实、读取或写入画像、形成证据、任务、诊断或危险处理。以后初始化成功也不得把这段普通聊天自动补进健康状态。
2. **初始化做到一半。** 主人已经同意，但时区、基础偏好或初始画像尚未成功创建，随后连接中断。此时产品仍必须是“未初始化”，每日复盘、任务、主动支持、健康读写和健康安全处理都不能启动。
3. **初始化后自然聊天。** 主人说“把昨晚只睡四小时记下来”。无论模型有没有想到某个 Tool 或 Skill，都不能直接给出一个貌似“已记录”的普通回答；只有统一门禁后的权威更新和真实更新结果才成立。
4. **自动任务运行。** 每日复盘、任务生成或内部 dispatch 没有当前聊天主人对象，也仍须验证同一初始化、权威状态、批准和安全边界；调度器 `success` 不能冒充任务业务已经完成。
5. **提交与回复分离。** 更新已经写入权威状态，但微信回复失败或结果未知时，画像仍可能已经更新，未知的是交付；不得改写成“更新失败”并盲目重试。
6. **接口接受与主人收到分离。** Weixin Adapter 返回成功或 Hermes 生成了 client id，只能证明接口调用层接受；没有展示／到达／已读证据时，主人实际收到仍是未知。[F8]

第 1 个场景允许基础 Hermes 继续普通聊天；它不等于“健康管家已经处理得很安全”。即便一个候选 Health Adapter 只为识别初始化短语而加载并读取门禁状态，也仍需证明它没有形成上述任何健康效果或健康接收事实。

## 2. 八层结果阶梯

| 层级 | 必须证明的事实 | 不能拿什么替代 |
| --- | --- | --- |
| 1. 资产被发现／加载 | loader 找到目标扩展且加载的是预期版本 | 文件存在、manifest 存在 |
| 2. 接口已注册 | 预期名称、schema、handler 已完整进入 registry，且没有部分注册 | Plugin 清单出现、Gateway active |
| 3. 模型可见 | 本轮实际工具集或 Skill 索引已把接口交给模型 | 接口已注册 |
| 4. 主人可发现 | 主人所在真实渠道能看到用途与入口，不必猜隐藏名称 | 模型知道、文档在仓库 |
| 5. 调用开始 | 本次请求确实进入预期 handler／受管自然语言路径 | 模型写出相似文字、slash 被解析 |
| 6. 业务提交／权威状态变化 | 唯一健康权威完成了预期原子变化，或明确没有变化、拒绝、失败、未知 | handler 未抛错、Cron success |
| 7. 接口返回真实结果 | 返回忠实映射第 6 层，并保留“可能已提交但无法确认” | 任意非空字符串、HTTP/Adapter accepted |
| 8. 主人实际收到 | 有足够证据证明主人真正收到；否则只记录到接口接受层 | send 无报错、本地 client id |

`[FIXED-SOURCE]` Tool registry 捕获异常并返回错误字符串，却不理解健康事务；Plugin Command 把 truthy 值 `str()` 化、空值不回复；Cron 的 `success/failed/unknown` 是调度层状态。框架均不能代替第 6–8 层的产品证明。[F3][F4][F6]

## 3. 当前入口能力矩阵

| 候选入口 | 已证明的发现／调用能力 | 当前结果与留痕 | 对初始化硬门禁的结论 |
| --- | --- | --- | --- |
| 普通 profile Skill | Agent 可从摘要索引按需 `skill_view`；知道名称的主人可用 Skill slash，自然语言只让模型**可能**选择 | 回到普通 Agent 回合；不是健康事务结果，普通 Session/FTS/Memory 边界仍适用 | **不能单独承担。** 模型可不加载、不遵循并直接回答。[F1][F5] |
| Plugin Skill | 用限定名注册，知道精确 `plugin:skill` 后可 `skill_view` | 不进平面 Skill 树或系统提示 `<available_skills>`，没有内建主人发现面 | **不能单独承担。** 只注入文档，不是强制执行门禁。[F2] |
| Plugin Tool | 注册名称、JSON schema、handler、toolset；只有进入本轮工具集才对模型可见 | 标准 Agent 路径把 tool call/result 写入普通 transcript；registry 不证明业务提交 | **原语存在，门禁未提供。** 模型可以零 Tool call 直接回答。[F3][F7] |
| Plugin Command | 知道名称的主人可显式调用；Gateway 固定基线在普通 Session 前处理 Plugin Command | handler 只收到 `raw_args`；truthy 结果字符串化，异常只记 warning；各渠道菜单发现能力不一致 | **原语存在，门禁未提供。** 没有初始化状态、主人健康权利或业务结果合同。[F2][F5] |
| 自然语言／普通 Gateway | 基础 Hermes 总能继续普通 Agent 回合；Skill/Tool 是否采用由模型与本轮工具集决定 | 普通会话会保存历史；初始化前消息没有原生健康阶段标记 | **不能依靠模型选择收敛。** 标准路径也没有“不倒填”保证。[F1][F3][F7] |
| Plugin Platform / Adapter | v0.20.0 允许 Plugin 注册 Platform；同名 Plugin Adapter 可优先于内置 Adapter，被选中后能够自建前置路径 | 这是截获目标渠道的正向扩展原语，不自动覆盖 CLI、另一聊天平台、Command、Tool、Cron 或其他 Plugin | **有候选空间，当前未证明。** 当前现场没有健康 Plugin；自定义 Adapter 的具体门禁仍需独立证明。[F2][F9][L1] |
| `ctx.dispatch_tool` / registry direct dispatch | 进程内代码知道名称即可直接调用同一 handler | 不经标准工具 schema 校验、模型选择和普通 Tool 桥接；Gateway PluginContext 不传渠道主人身份 | **旁路风险成立。** handler 自己的强校验可能弥补，但框架不保证。[F2][F4] |
| Cron Agent / Plugin 自动流程 | 能按计划启动新 Agent 回合，或由 Plugin 直接调用 handler | 有任务／执行账本；没有当前对话主人身份，调度状态不是健康业务状态 | **必须另证统一门禁。** 当前现场业务 Cron 为零。[F6][L1] |

`[FIXED-SOURCE]` `pre_gateway_dispatch` 只处理 user-originated event，internal event 会跳过；正常返回时它能够 skip/rewrite/allow，Hook/Middleware 也可包裹部分调用。callback 异常会记录后继续基础流程，Plugin `register()` 失败也不终止 Hermes，已写入共享 registry 的部分项不自动回滚。它们因此不能被原样称为“不可旁路、失败关闭的初始化总闸门”。[F10]

目标 `gateway/run.py` 属于 `[LIVE]` dirty 路径，所以固定提交中的 Gateway 顺序只作为基线；本票没有把固定行号冒充现场逐字一致。这个不确定性不会改变现场负向结论，因为当前根本没有已部署健康 Plugin、健康初始化状态或健康业务 Cron。[L1]

## 4. 初始化完整性核验

### 4.1 固定 Hermes 没有现成健康初始化事务

Plugin 注册表只管理接口对象；Session 只管理普通对话；Cron 只管理调度。`[FIXED-SOURCE]` 没有一个原生记录同时拥有“披露版本、明确同意、时区、基础偏好、初始画像、启用状态”的健康产品语义，也没有原生规则禁止 Tool、Command、direct dispatch 或 Cron 在某个业务状态前运行。[F2][F4][F6][F7]

`[INFERENCE]` 因此不能从“Python Plugin 可以写数据库”推导“初始化已经原子成立”。正向能力必须由一个实际候选的可查询状态转换、崩溃边界和所有入口的拒绝证据证明；具体如何实现属于后续 HOW。

### 4.2 工作树候选明确是两段式，且过早启用

`[WORKTREE-CANDIDATE]` 当前候选以两个精确短语触发 `enable_health_recording(subject, owner_sender_id, message_id, message_utc, verification_token)`；参数中没有披露版本、每日复盘／任务自动化／主动支持说明、首跳接收方、通知选择、主人权利、主人确认时区、基础偏好或初始画像。[W2][W3]

状态层注释和实现更直接：

- `enable_health_recording()` 的 docstring 是“Persist explicit consent **without creating or binding a health profile**”；
- 当 profile 还不存在时，`health_recording_status()` 仍返回 `recording_enabled`；
- 只有以后 `admit_consented_profile_candidate()` 收到第一条可写候选时才用 `_empty_profile(sender_id)` 创建画像；
- `_empty_profile()` 直接填入 `Asia/Shanghai` 和未暂停主动联系，而不是保存主人在初始化中确认的值。[W3][W4]

因此它无法通过“同意后、画像前崩溃”的反例。它证明的是旧“健康记录 consent → 后续首条资料建画像”候选，不是当前“完整结果整体成立后才启用”的初始化合同。

### 4.3 初始化前零健康效果与不倒填仍未证明

候选 Weixin Adapter 在每条消息进入基础 Hermes 前先调用 `prepare()`，检查精确启用短语、当前 owner 与 recording 状态；未启用且不是启用短语时，它不运行健康分类，随后消息可进入基础 Hermes。[W2] 这与“初始化前允许基础 Hermes 普通聊天”方向兼容，但不能单独证明：

- 其他已加载 Hook、Command、Tool、Cron 或 Plugin 没有健康副作用；
- Adapter 的所有失败、重试、日志和状态读都不会保存健康接收事实；
- 初始化后的标准 Agent 不会把同一普通 Session 中的初始化前消息用于健康更新；
- 旧任务、旧 consent、普通 Memory、历史 Skill 或其他状态不会被当成当前初始化结果。

`[FIXED-SOURCE]` 普通 Session 会保存 user/assistant/tool call/tool result，并建立全文索引；标准 Agent 后续回合仍携带会话历史。Hermes 没有原生“初始化时间之前不得作为健康证据”的语义，因此采用标准 Agent 自然语言/Tool 路径时，不倒填必须由实际健康实现另行证明。[F7]

## 5. 初始化后的统一边界仍缺什么事实

产品要求自然语言、明确入口、内部自动流程与四项职责最终都落到同一画像、证据、任务、数据权利和安全边界。当前固定接口分别缺少不同上下文：

- Skill 缺强制执行；
- Tool 受模型选择影响；
- Command 缺调用者对象和健康业务结果语义；
- direct dispatch 缺标准桥接、schema 与渠道身份；
- Cron 缺当前对话身份，并把调度结果与业务结果分开；
- Platform Adapter 只覆盖它实际接管的渠道；
- 同进程的另一个受信 Plugin 仍可直接调用 Python 或 registry，Hermes 没有健康专用进程隔离或总策略层。[F1][F2][F3][F4][F6][L1]

`[INFERENCE]` 这些缺口不证明 Hermes 绝对无法实现统一边界；它们证明**统一边界必须属于被验证的实际健康能力自身，而不能由某一种入口的注册成功或模型遵循推得**。本票不预选它应落在哪种技术机制。

## 6. 四项职责与任务框架的边界

当前产品把画像维护、证据维护、主人询问、文献查找定义成四项流程职责；任务框架拥有目标、阶段、验收与四标签。是否恰好实现为四个 Skill 及如何调用，明确留给 CAN/HOW。[P2]

- `[LIVE]` 当前没有健康 Plugin 或健康业务 Cron，因此四项职责和任务框架均未实现／未证明。[L1]
- `[FIXED-SOURCE]` Hermes 能承载 Skill、Tool、Command、Plugin 内部函数和 Cron，但这些名称不自带“职责只能返回结果、不能自行改任务／降验收／标 solved”的产品约束。[F1][F2][F6]
- `[WORKTREE-CANDIDATE]` 两个已注册 Tool 名为 `health_daily_review` 与 `health_dispatch_due_tasks`，不是四项职责，也不是主人初始化入口；不能从两个 Tool 推断任务框架已经满足当前 TO。[W1]

所以本票只保留“入口必须能发现、调用并返回真实职责／任务结果，且所有路径共享初始化门禁”的要求，不把四项产品职责提前固化成四个技术 Skill。

## 7. 可证伪的能力判定

当前 C02 若要从负向提升为正向，任何后续候选都至少要用可复现证据同时击败以下反例；这是一组验收事实，不是实现路线选择：

1. 对初始化的每个步骤制造中断；除“全部完成”外，重启后仍只允许初始化引导，健康画像、证据、任务、诊断、危险处理、每日复盘和主动联系均为零。
2. 在初始化前放入可识别的普通聊天哨兵；初始化后从自然语言、Skill、Tool、Command、direct dispatch、Cron/自动流程逐一路径尝试，哨兵不得成为画像、证据或任务。
3. 在每条入口分别证明八层阶梯；特别是必须用权威状态证明业务提交，用独立交付事实区分接口接受与主人收到。
4. 让模型不调用 Tool、错误加载 Skill、直接回答、直接调用 Command／registry、由 Cron 触发、由另一 Plugin 触发；所有可能产生健康效果的路径仍须得到同一个初始化与健康边界判定。
5. 对更新、删除、任务变化和初始化在“提交前、提交中、提交后但回复前”中断；返回必须区分未提交、已提交、失败和结果无法确认，未知时不得盲重试。
6. 查询初始化结果时，必须能同时定位披露版本、明确同意、主人时区、基础偏好、初始画像和启用状态，并证明旧／部分／损坏状态不能冒充当前完整结果。

本票没有执行上述写入、模型、微信、崩溃或故障实验；它们需要在能力实现后按项目批准边界单独进行。当前现场结论因此保持为：**扩展原语可用；完整初始化门禁、入口收敛与真实结果合同未实现或未证明。**

## 8. 证据层级与来源

### `[LIVE]` 当前目标现场

- **[L1]** [Ticket 78 同一时点现场报告](19-current-partner-hermes-baseline-plugin-lifecycle-trust-20260820.md)：第 2–6、8–10 节记录版本／dirty 路径、ordinary enabled Plugin 0、profile manifest 0、业务 Cron 0、80 个 Skill 文件与 7-item 管理视图、Telegram/Weixin configured、CLI/chat/Cron/send/internal dispatch 仍存在，以及默认 Plugin/Hook/Middleware 失败语义。采样没有读取凭据、聊天或健康正文，也没有改变生产。

### `[FIXED-SOURCE]` Hermes v0.20.0 官方提交

- **[F1]** [Skill 是按需知识、slash 与自然语言使用](https://github.com/NousResearch/hermes-agent/blob/3c27eb6234bf91b8ceee9e9071591b31e9b148cb/website/docs/user-guide/features/skills.md#L7-L80)；[渐进发现与平台过滤](https://github.com/NousResearch/hermes-agent/blob/3c27eb6234bf91b8ceee9e9071591b31e9b148cb/website/docs/user-guide/features/skills.md#L111-L174)。
- **[F2]** [Plugin Tool 注册](https://github.com/NousResearch/hermes-agent/blob/3c27eb6234bf91b8ceee9e9071591b31e9b148cb/hermes_cli/plugins.py#L377-L428)；[Command 注册与 `raw_args` handler](https://github.com/NousResearch/hermes-agent/blob/3c27eb6234bf91b8ceee9e9071591b31e9b148cb/hermes_cli/plugins.py#L503-L550)；[`ctx.dispatch_tool`](https://github.com/NousResearch/hermes-agent/blob/3c27eb6234bf91b8ceee9e9071591b31e9b148cb/hermes_cli/plugins.py#L553-L578)；[Platform 注册](https://github.com/NousResearch/hermes-agent/blob/3c27eb6234bf91b8ceee9e9071591b31e9b148cb/hermes_cli/plugins.py#L865-L914)；[Plugin Skill 命名空间与隐藏索引](https://github.com/NousResearch/hermes-agent/blob/3c27eb6234bf91b8ceee9e9071591b31e9b148cb/hermes_cli/plugins.py#L1108-L1147)。
- **[F3]** [模型零 Tool call 时直接返回文本](https://github.com/NousResearch/hermes-agent/blob/3c27eb6234bf91b8ceee9e9071591b31e9b148cb/agent/conversation_loop.py#L6202-L6208)；[标准 Agent Tool 调用与持久化顺序](https://github.com/NousResearch/hermes-agent/blob/3c27eb6234bf91b8ceee9e9071591b31e9b148cb/agent/conversation_loop.py#L5937-L5999)。
- **[F4]** [Tool registry 直接 dispatch、无 schema 校验、异常转错误字符串](https://github.com/NousResearch/hermes-agent/blob/3c27eb6234bf91b8ceee9e9071591b31e9b148cb/tools/registry.py#L673-L735)。
- **[F5]** [Gateway 通用授权](https://github.com/NousResearch/hermes-agent/blob/3c27eb6234bf91b8ceee9e9071591b31e9b148cb/gateway/run.py#L13397-L13465)；[slash 访问判断](https://github.com/NousResearch/hermes-agent/blob/3c27eb6234bf91b8ceee9e9071591b31e9b148cb/gateway/run.py#L13901-L13960)；[Plugin Command 与 Skill slash 分支](https://github.com/NousResearch/hermes-agent/blob/3c27eb6234bf91b8ceee9e9071591b31e9b148cb/gateway/run.py#L14374-L14408)；[Command 返回／异常／CLI helper 30 秒边界](https://github.com/NousResearch/hermes-agent/blob/3c27eb6234bf91b8ceee9e9071591b31e9b148cb/hermes_cli/plugins.py#L2147-L2218)。
- **[F6]** [Cron 执行、恢复和 `unknown` 是调度层语义](https://github.com/NousResearch/hermes-agent/blob/3c27eb6234bf91b8ceee9e9071591b31e9b148cb/website/docs/user-guide/features/cron.md#L234-L273)。
- **[F7]** [普通 Session 持久字段、消息与 API 内容](https://github.com/NousResearch/hermes-agent/blob/3c27eb6234bf91b8ceee9e9071591b31e9b148cb/website/docs/developer-guide/session-storage.md#L2-L27)；[完整消息字段](https://github.com/NousResearch/hermes-agent/blob/3c27eb6234bf91b8ceee9e9071591b31e9b148cb/website/docs/developer-guide/session-storage.md#L75-L123)。
- **[F8]** [Weixin 发送使用本地生成 client id，接口无报错即 `SendResult(success=True)`](https://github.com/NousResearch/hermes-agent/blob/3c27eb6234bf91b8ceee9e9071591b31e9b148cb/gateway/platforms/weixin.py#L1799-L1815)。
- **[F9]** [Plugin Adapter 优先于内置 Adapter](https://github.com/NousResearch/hermes-agent/blob/3c27eb6234bf91b8ceee9e9071591b31e9b148cb/gateway/run.py#L12727-L12770)；[同名 Platform 后注册覆盖](https://github.com/NousResearch/hermes-agent/blob/3c27eb6234bf91b8ceee9e9071591b31e9b148cb/gateway/platform_registry.py#L209-L225)。
- **[F10]** [Plugin load/register 失败后继续](https://github.com/NousResearch/hermes-agent/blob/3c27eb6234bf91b8ceee9e9071591b31e9b148cb/hermes_cli/plugins.py#L1611-L1689)；[Hook/Middleware callback 异常隔离并继续](https://github.com/NousResearch/hermes-agent/blob/3c27eb6234bf91b8ceee9e9071591b31e9b148cb/hermes_cli/plugins.py#L1744-L1806)；[`pre_gateway_dispatch` 固定调用点](https://github.com/NousResearch/hermes-agent/blob/3c27eb6234bf91b8ceee9e9071591b31e9b148cb/gateway/run.py#L13355-L13396)。

### `[WORKTREE-CANDIDATE]` 当前仓库候选（不是部署事实）

当前仓库 HEAD 为 `5f358137309d7670e7ad615c8af9d1aa679a49e3`，且 `plugin/health-steward/__init__.py` 为 dirty；下列 SHA-256 固定本次实际读取内容，不能用仓库 HEAD 单独复原候选。

- **[W1]** [`plugin/health-steward/plugin.yaml`](../../../ops/partner-health-steward/plugin/health-steward/plugin.yaml) 与 [`plugin/health-steward/__init__.py`](../../../ops/partner-health-steward/plugin/health-steward/__init__.py)：`:373-443` 注册 `health_daily_review`、`health_dispatch_due_tasks`、只读投影 Hook 与 Weixin Platform，没有初始化 Skill/Tool/Command。`__init__.py` SHA-256 `1748ec7c76cb59a78539375f6ca51d3a21fe66e36e84e945ad7590eb34334a60`。
- **[W2]** [`weixin_ingress.py`](../../../ops/partner-health-steward/weixin_ingress.py)：`:27` 只有两个精确启用短语；`:259-315` 的 `prepare()` 先保存 recording consent／检查 recording state，未启用时不运行分类；`:317-550` 才进入分类和候选写入。SHA-256 `b2fce5ae5fc44110424ff37e812fdac980120f05a3913d3adec2adb7b61dbad5`。
- **[W3]** [`sidecar/store.py`](../../../ops/partner-health-steward/sidecar/store.py)：`:1708-1750` 明确允许 consent 已启用而 profile 不存在；`:1806-1895` 的 `enable_health_recording()` 只保存 consent，且 docstring 明说不创建／绑定画像。
- **[W4]** [`sidecar/profile.py`](../../../ops/partner-health-steward/sidecar/profile.py)：`:550-567` 的空画像默认时区／主动联系；`:872-1003` 的首条候选准入才在画像不存在时创建 `_empty_profile(sender_id)`。
- **[W5]** [`plugin/health-steward/__init__.py`](../../../ops/partner-health-steward/plugin/health-steward/__init__.py)：`:87-141, 184-193` 仍要求 owner 以外的 `expected_viewer`；[`owner_controls.py`](../../../ops/partner-health-steward/owner_controls.py)：`:262-344, 501-595, 794-812` 仍含 viewer、身份迁移／恢复码路径。
- **[W6]** [`deployment.py`](../../../ops/partner-health-steward/deployment.py)：`:1539-1555, 1651-1654` 只启用 `health-steward` 并禁用／排除 legacy `health-guard`、`health-autonomy`；[`skill/health-steward/SKILL.md`](../../../ops/partner-health-steward/skill/health-steward/SKILL.md)：`:44, 55` 仍描述旧 Telegram 合同；[`plugin/health-autonomy/__init__.py`](../../../ops/partner-health-steward/plugin/health-autonomy/__init__.py)：`:147-219` 也是旧 Telegram 路径。它们不能作为当前完整候选或部署事实。

### `[HISTORICAL]` 与项目合同

- **[H1]** [Ticket 63 旧入口研究](15-health-capability-discovery-invocation-result-contract-20260818.md)：只继承固定提交下 Skill/Tool/Command/direct dispatch/Cron 的接口事实与“各层不等价”结论；旧七入口范围和 2026-08-16/17 现场状态不作为当前答案。
- **[P1]** [`CONTEXT.md`](../../../CONTEXT.md)：`:15-16, 77-80, 91-103, 186, 225, 228` 给出未初始化零健康效果、不倒填、完整初始化、更新结果、交付分层与未知／失败关闭合同。
- **[P2]** [`CONTEXT.md`](../../../CONTEXT.md)：`:142-143` 定义任务框架与四项流程职责，并明确是否恰好实现为四个 Skill 留给 CAN/HOW。

## 9. 本票明确没有做的事

- 没有重复 SSH 现场采样；沿用同日 Ticket 78 的当前只读指纹，并保留其时间边界。
- 没有读取 secret、聊天／健康正文、数据库正文或日志正文。
- 没有安装／启用 Plugin 或 Skill，没有建立 Cron，没有调用模型或微信，没有发送消息、重启服务或制造故障。
- 没有把工作树候选、旧 Telegram Skill、viewer／恢复路径或历史 HOW 冒充部署事实。
- 没有选择四项职责、初始化、自然语言、Tool、Command、Platform 或任务框架的最终技术映射。
