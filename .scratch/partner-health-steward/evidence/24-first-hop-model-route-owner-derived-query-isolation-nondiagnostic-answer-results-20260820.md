# 首跳模型路线、主人派生查询隔离与非诊断健康问答结果链核验

## Answer

本票得到一项**负向但可判定的 CAN 结论**。

- **C08（首跳路线与主人派生查询隔离）未实现、未证明。** 2026-08-20 17:15–17:17（Asia/Shanghai）的正式 Partner 脱敏只读样本可以把当前磁盘配置声明的名义首跳定位为 provider `jojo`、base URL `https://max2.jojocode.com/v1`，API mode 为 `codex_responses`，请求模型名为 `gpt-5.6-sol`；顶层 `fallback_model` 与 `fallback_providers` 均未出现，配置和 `.env` 又早于当前 Partner 进程启动。这个结果足以向主人披露当前磁盘配置声明的名义首跳服务路线，但不能证明一次实际请求、JOJO 内部最终模型或节点，也不需要按现行 TO 枚举内部节点。[L1][L2][P1] 当前正式 Partner 没有健康 Plugin manifest、受管健康初始化或健康状态，因此没有已部署的“同意路线快照—运行路线比较—首跳变化暂停—本地数据权利继续”执行链。固定 `ctx.llm` 又没有 endpoint、禁止 fallback、路线预览或发送前接收方回调；容量类故障仍可能把同一消息交给另一 fallback 候选。顶层 fallback 字段缺失不能证明这条内部 fallback 已关闭，更不能在发送前证明下一首跳仍在主人同意边界内。[F1][F2][H1]
- **当前工作树存在直接的主人派生查询反例。** 未部署候选存在一条确定性允许分支：分类结果要求来源核验、没有新鲜资料卡且主人本次消息命中静态关键词 URL 时，会按该消息选出的精确 URL 发起 HTTPS 抓取。即使 URL 来自静态白名单、请求不带姓名或查询参数，主题和触发时机仍来自主人消息，所以按现行合同仍是主人派生医学查询，不能发送到当前 Hermes 模型路线之外。候选的本地缓存命中只表示本次没有回源，不会把该查询改成独立通用更新；候选也没有保存“该内容即使没有这位主人仍会按同一治理计划取得”的反事实来源证明。[W2][W3][P2]
- **C17（非诊断健康问答结果链）未实现、未证明。** 当前正式 Partner 没有受管且符合现行合同的健康问答入口或结果对象；普通 Agent 的一般问答面不能冒充该能力。工作树候选确有若干局部原语：单轮模型输入不读取普通会话历史、限制画像摘要和引用数量、只接受当前来源卡 ID、禁止模型 Tool、交付 ledger 不保存回复正文，并区分接口 `accepted`、`uncertain` 与 `rejected`。[W1][W4][W5][W6] 但它的模型输出 schema 只有 `answer_text` 与 `used_source_card_ids`，不能强制区分个人事实和一般知识，也不能强制给出实际资料的类型、来源、时间、用途、不确定性、关键未知和安全下一步；它没有产品级诊断效果闸门，也没有独立安全前提。输出即使形成疾病排序、诊断标签、排除结论或个体化用药改变，现有代码仍会沿同一问答发送路径继续；代码没有“安全能力不可用”的独立分支，现有一般回答失败文案也不满足现行最低求助合同。[W4][W5]
- 主人在问答中产生新陈述时，若分类模型返回旧结构画像 candidate，sidecar 会尝试准入；这证明候选分支中“模型文字不会直接写画像”的局部隔离，但不能证明每条新陈述必然这样处理。准入对象仍是旧画像合同，且“画像已更新”只是拼在问答尾部的标记，不是现行独立、可判定的画像更新结果。[W7] 候选也没有把结果形成、权威业务提交、发送尝试、微信接口接受和主人实际收到五层完整分开：本地交付 ledger 能区分接口接受、未知和拒绝，却没有主人到达证明，`HealthTurnResult.final_text` 也不是受管的结构化非诊断业务提交。[W2][W6]

因此，当前固定 Hermes 提供了以后构造受控路线、结构化模型调用、Tool/搜索 provider 和无正文投递账本的底层原语；当前工作树也提供了一些可比较的局部候选。但二者均不能支撑 C08 或 C17 的现行 TO，且工作树的按消息回源是确定性反例。本票只固定这些能力、限制、反例和未知，不选择 provider、模型、搜索、提示、检索、缓存、渲染或最终 Plugin/HOW 路线。

## 1. 范围、判据与证据纪律

本报告只回答[【CAN】核验首跳模型路线、主人派生查询隔离与非诊断健康问答结果链](../issues/85-verify-first-hop-model-route-and-owner-derived-query-isolation.md)中的 C08 与 C17。判据继承：

- [【TO】决定健康模型接收方锁定缺口下的产品承诺边界](../issues/58-decide-health-model-recipient-lock-gap-boundary.md)：同意边界是当前首跳模型服务路线及其正常内部路由或故障切换；改用另一首跳时，依赖新路线的健康处理暂停，但不需要新接收方的本地查看、纠正、导出和删除仍可继续。[P1]
- [【TO】确定辅助诊断中的个人证据最小化、外部医学接收方与持久保留边界](../issues/65-define-diagnostic-evidence-recipients-and-retention-boundary.md)：主题、参数、组合、时机或优先级由主人资料改变的查询仍是主人派生查询；去姓名、编码、延迟、批处理或缓存都不能洗白。只有与主人完全无关、按独立治理计划照常取得的内容才是通用更新。[P2]
- [`CONTEXT.md`](../../../CONTEXT.md) 中的“健康问答”“个人健康事实”“健康证据库”“健康结果交付事实”“危险升级 / 危险未明 / 安全能力不可用”和“处理结果无法确认”：非诊断问答必须使用当前必要、已准入且可追溯的资料；不能把一般知识冒充个人事实，不能以普通问答绕过诊断和安全合同，也不能把接口接受冒充主人收到。[P3]

证据按以下层级解释：

| 标记 | 本报告如何使用 |
| --- | --- |
| `[LIVE]` | 2026-08-20 对正式 Partner 的只读脱敏事实；没有读取或输出 key、token、secret、password、聊天、Session、日志或健康正文，也没有写远端、调用模型、发送消息、重启或制造故障 |
| `[FIXED-SOURCE]` | 正式 Partner HEAD `3c27eb6234bf91b8ceee9e9071591b31e9b148cb` 对应 Hermes v0.20.0 的固定源码与官方文档；当前现场相关模型、Plugin、registry 和 Web Search 文件相对 HEAD 无修改 |
| `[WORKTREE-CANDIDATE]` | `D:\cohermes\ops\partner-health-steward` 当前 dirty/untracked 文件的实际静态行为；不是部署事实，也不继承旧 HOW |
| `[SYNTHETIC]` | 不含真实健康资料的场景静态走查，以及既有本地定向测试；没有产生真实模型、搜索或微信出站 |
| `[UNRUN]` | 需要修改配置、触发 fallback、调用外部模型/搜索、真实微信或故障注入的实验；本轮没有授权，也不以静态证据冒充完成 |

## 2. 正式 Partner 当前首跳与部署事实

### 2.1 `[LIVE]` 17:15–17:17 的脱敏快照

| 事实 | 当前值 | 能证明什么 | 不能证明什么 |
| --- | --- | --- | --- |
| Partner 服务 | `active/running`，MainPID `143611`，当前进程自 2026-08-07 07:30:33 +08:00 启动 | 当前正式 Partner 进程仍是前置 CAN 的同一运行实例 | 健康能力或一次模型调用成功 |
| 安装树 | `/usr/local/lib/hermes-agent`，HEAD `3c27eb...` | 可把固定源码行为归因到明确提交 | 整棵树是干净发行版；`gateway/run.py` 仍有现场修改 |
| 当前首跳配置 | provider `jojo`；base URL `https://max2.jojocode.com/v1`；API mode/transport `codex_responses`；default/request model `gpt-5.6-sol` | 可以披露 Hermes 当前配置的首跳模型服务路线及请求模型名 | JOJO 内部最终模型、运行节点、站内路由或留存合同 |
| provider definition | `jojo` 与 `custom` 两个定义均指向同一 `max2` endpoint 和同一 transport/model | 当前可见的两个命名定义没有显示第二个 endpoint | 所有运行时可发现凭据/provider、未来 fallback 或 relay 内部路线都只有这个 endpoint |
| 顶层 fallback | `fallback_model` 不存在；`fallback_providers` 不存在 | 没有显式配置这两个顶层字段 | `ctx.llm` 私有调用链的自动 fallback 已禁用 |
| 配置时序 | `config.yaml` mtime 2026-08-07 07:29:19；`.env` mtime 2026-08-05 03:43:37；均早于服务启动 | 当前磁盘首跳不是服务启动后才改出的未加载值 | 一次真实请求一定采用了该路线，或运行内存没有其他动态状态 |
| 健康部署 | Partner profile 的普通 Plugin manifest 数为 `0`；同日前置票已确认 ordinary enabled Plugin 为零 | 当前没有部署本仓库健康 Plugin | Hermes 运行时完全没有 bundled backend/platform 代码 |

17:15 的配置 SHA-256 为 `53ed9229d948260eb97dcae862174d6cb44860d5f5e6c35894fec8bc9c79c3df`。该值只用于把本轮读到的非敏感首跳字段绑定到同一配置版本；它不是授权、接收方同意或模型调用回执。[L1]

17:17 对 `agent/auxiliary_client.py`、`agent/plugin_llm.py`、`hermes_cli/plugins.py`、`tools/registry.py`、`agent/web_search_provider.py` 的限定 Git 状态没有差异；只有同批检查的 `gateway/run.py` 显示 modified。对应现场 SHA-256 分别为 `31f435b8...`、`08132f8b...`、`2cb8c309...`、`3675b8c2...`、`8d2617df...`。所以本报告可以把模型/fallback、Plugin、registry 和 Web Search 结论归因于固定 HEAD；Gateway 的完整入站行为仍必须保留现场定制边界。[L2]

### 2.2 `[FIXED-SOURCE]` 模型与 fallback 图

固定 Hermes 提供两条不同性质的模型路径：

1. 普通 Agent 路径会创建或取得 Session，把 user、assistant、Tool call/result 和实际 API 内容纳入普通 Session/FTS，并可能进入普通 Memory；因此它不能承担现行健康正文隔离。[F3]
2. 正式 Plugin 的 `ctx.llm` 是 out-of-band 模型入口，不自动创建普通 Session。它可以申请名义 provider/model/profile，但公开调用没有 `base_url`、`disable_fallback`、`route_preview`、recipient allowlist 或发送前 endpoint 回调。[F1]

`ctx.llm` 最终进入 `call_llm(task=None, ...)`。认证、额度、连接、限流、模型不兼容或无效响应等条件可触发 fallback；容量类条件能够绕过显式 provider 限制，候选顺序还可以进入主 Agent 模型或自动发现项，并把同一 messages 发给被选中的 endpoint。[F2] 因此当前事实图只能写成：

```text
健康 Plugin（当前不存在）
  └─ ctx.llm（可用原语）
       ├─ 当前名义首跳：jojo → max2.jojocode.com/v1
       └─ 宿主 fallback：目的地在发送前不能由公开 Plugin 接口完整证明
            └─ JOJO 内部正常路由：允许属于同一首跳服务，但仍非公开枚举对象
```

顶层 fallback 字段缺失不能补上健康产品闸门：当前没有持久化的“主人已同意首跳指纹”，没有把实时请求路线与它比较，也没有在另一 provider/endpoint/gateway 将接收正文前暂停的强制点。正式 Partner 又没有健康状态，所以本地查看、纠正、导出和删除权也无现成对象可继续执行。

### 2.3 `[FIXED-SOURCE]` Tool、搜索与缓存边界

- `PluginContext.register_tool` 可以向全局 registry 注册 Tool；普通 Agent 只把本轮选中的 Tool schema 交给模型，而 `ctx.dispatch_tool(name, args)` 还能直接进入 registry。registry 自身不会形成“主人派生查询”来源标签，也不会替具体 Tool 限制外部接收方；直接 dispatch 还不执行普通 Agent 的 schema/Tool bridge。[F4]
- 固定 `WebSearchProvider` 是全部 Web 搜索/提取 backend 的共同 Plugin 表面，实际 backend 由 `web.search_backend`、`web.extract_backend` 或 `web.backend` 选择；源码列出的 provider 实现包括 Brave Free、DDGS、SearXNG、Exa、Parallel、Tavily 和 Firecrawl。这里证明的是可到达的候选出站面，不是这些 provider 当前全部启用。[F5]
- 本轮为避免扩大配置披露，没有读取或输出完整 Tool、MCP、浏览器或搜索配置。因此**当前 Partner 实际选中的 Web Search backend、当前整套 Tool registry 和每项 Tool 的外部 endpoint 保持未证明**。这不妨碍负向结论：正式 Partner 没有健康 Plugin，也不存在把查询主题、参数、组合、时机和优先级的来源分类传给所有这些出口的受管闸门。
- 固定 `_get_cached_client` 是模型 client/endpoint 对象缓存，不是通用医学资料的来源证明；缓存对象存在不能说明一次健康查询没有经 fallback、没有发出，或已经获得主人同意。[F2]

## 3. 当前工作树候选的真实执行图

当前仓库 HEAD 为 `5f358137309d7670e7ad615c8af9d1aa679a49e3`；下述关键文件包含 modified、added 或未部署的实际工作树内容，不能归因给正式 Partner 或最终路线。[W0]

```text
可信 Weixin envelope
  └─ pinned 模型分类：health_related / source_required / 旧画像 candidate
       ├─ candidate → sidecar 旧证据准入 → 旧画像版本切换
       └─ 非诊断回答
            ├─ 读取旧 profile summary + evidence IDs + 已有 source cards
            ├─ 若需要来源且无新鲜卡：
            │    主人消息关键词 → 静态 URL → 本地 source cache
            │                              └─ miss/stale → 精确 HTTPS 回源
            ├─ pinned、no-tools 模型生成 answer_text + source card IDs
            └─ content-free delivery ledger → Weixin send → accepted/uncertain/rejected
```

### 3.1 局部正向原语

- [`health_model.py`](../../../ops/partner-health-steward/health_model.py) 把 provider、endpoint、model、privacy mode 和 auth profile 绑定到一个文件快照；endpoint 必须为无凭据、无 query/fragment 的 HTTPS URL。它直接解析固定 Hermes 私有 client、检查 endpoint/model 漂移、禁止 Tool，并只调用一次，不使用 Hermes fallback。[W1]
- [`health_turn_context.py`](../../../ops/partner-health-steward/sidecar/health_turn_context.py) 与 [`health_turn_answer.py`](../../../ops/partner-health-steward/health_turn_answer.py) 限制一次回答的旧画像摘要为 300 字、evidence ID 至多 24 个、来源卡至多 8 张；模型输入只含当前消息、旧摘要、ID 和来源卡公开投影，不读取普通聊天历史。[W4][W5]
- 模型返回只能引用本次给出的 source card ID，未出现的 ID 会被拒绝；外部卡被标记为 untrusted，候选禁止 Tool。[W4][W5]
- [`weixin_delivery.py`](../../../ops/partner-health-steward/sidecar/weixin_delivery.py) 的 SQLite delivery 表只保存 delivery/recipient/scope ID、时间、本地状态、本地 delivery/client ID 与错误码，不保存消息或回复正文；transport 的 `ret/errcode` 接受会被本地 ledger 映射为 `sent`，另有 `uncertain` 与 `rejected`，但没有 provider 回执 ID。[W6]

这些原语只说明候选中存在可复用的边界构件，不等于现行 C08/C17。尤其是 `health_model.py` 自己声明配置独立于 ordinary chat settings，并禁用 Hermes 正常 fallback；它来自旧 HOW，既不是“沿用同一个 Partner Hermes 当前模型路线及其正常故障切换”的现行合同，也未部署到正式 Partner。[W1][P1]

### 3.2 主人派生搜索的确定性反例

[`health_turn.py`](../../../ops/partner-health-steward/health_turn.py) 的 `HealthSourceCatalog.url_for(envelope.message_text)` 直接以当前主人消息匹配最长关键词；若上下文没有新鲜卡且分类模型表示需要核验，就把同一个 `message_text` 与选中的精确 URL 交给 `query_sources()`。[W2]

[`sources.py`](../../../ops/partner-health-steward/sidecar/sources.py) 先把消息拆成 terms 检索本地卡；没有新鲜匹配时，只要收到 `source_url`，就调用 `source_fetch.fetch(source_url)`，随后把响应写成来源卡。[W3] 静态 allowlist、拒绝 redirect、限制字节和 20 秒预算可以控制“发到哪里、抓多少”，却没有改变“为什么现在抓这个主题”。所以：

- 去掉姓名不改变派生关系；
- 精确 URL 无 query 参数不改变派生关系；
- 本地先查缓存不改变派生关系；
- 缓存 miss 后再回源不改变派生关系；
- 延迟、合批或另一个进程执行也不会改变派生关系。

候选 source card 与 audit 保存 URL、host、版本和卡 ID，但没有保存一个可核验的独立更新计划、计划版本、固定时间表和“即使没有该主人也会取得相同内容”的反事实证明。[W3] 因而该候选不能把这条路线重述为通用医学更新。

## 4. C17 非诊断结果链逐项核验

| 现行要求 | 正式 Partner | 工作树候选 | CAN 结论 |
| --- | --- | --- | --- |
| 只选本次必要、当前适用、已准入资料 | 无受管画像/证据及符合现行合同的健康问答入口 | 只投影旧摘要、ID 和来源卡；旧摘要不是现行六域主题，ID 本身不证明资料类型、时间、准入或当前适用 | 未实现、未证明 |
| 区分个人事实与一般知识 | 无 | 输出 schema 只有自由文本和来源卡 ID；模型提示没有强制的个人事实/一般知识分区 | 未证明 |
| 显示资料类型、来源、时间、用途 | 无 | source card 有 URL/版本/抓取时间，但个人 evidence 只给 ID；输出 schema不要求用途或个人来源时间 | 未实现 |
| 表达不确定性、关键未知、安全下一步 | 无 | 没有对应必填字段或可验证结构 | 未实现 |
| 疾病排序、标签、排除或个体化调药必须转诊断合同 | 无 | 分类只判断 health_related/source_required/candidate；回答 prompt/schema 没有诊断效果分类或发送前阻断 | 确定性缺口 |
| 危险、危险未明、安全不可用优先 | 无 | 没有独立安全组件输入；失败固定文案为“健康回答暂时不可用”及可选“当前无法核验所需权威资料” | 确定性缺口 |
| 新主人陈述只做候选，画像更新另行准入并给真实结果 | 无 | 若分类模型返回 candidate，sidecar 会另行尝试准入，这是局部正向；但对象是旧合同，结果只拼接“画像已更新”尾标，不能表达未更新、拒绝、失败或无法确认 | 部分原语，不满足现行合同 |
| 不长期保存完整回答、提示、完整模型输入输出、草稿和未通过候选 | 无健康链可验 | health answer handler 本身不读写普通 Session，且本地 delivery ledger 不存正文；但分类决定形成前的失败仍可能回普通聊天，全入口 Session 隔离、模型服务与微信站外保留均未证明，候选也没有生产部署与端到端副本清单 | 局部正向，整体未证明 |
| 分开结果形成、业务提交、发送尝试、接口接受、主人实际到达 | 无 | 形成后直接 `send_once`；ledger 可区分接口接受/未知/拒绝，但没有结构化业务提交和主人到达证明 | 未闭合 |

工作树 `HealthTurnResult.final_text` 只是当前进程返回对象；它既不是长期结构化非诊断结果，也不能证明主人真实收到。相反，delivery ledger 的本地 `sent` 是由 transport 的 `ret/errcode` 接受映射而来，并非 provider 回执或主人到达证明；现行 TO 要求它不得被显示成主人已收到。[W2][W6][P3]

## 5. 六个合成场景的静态核对

本节只用虚构消息走查现有分支，没有向模型、搜索或微信发送任何请求。

| 场景 | 当前候选会经过什么 | 需要成立但当前缺失的结果 |
| --- | --- | --- |
| “我已有的一次测量值代表什么？” | 分类模型决定是否需要来源；回答模型收到当前消息、旧摘要/ID和可能的来源卡，返回自由文本 | 不能强制说明该测量是主人陈述还是设备测量、测量时间/方法、一般知识用途、不确定性、关键未知和安全下一步 |
| “近期上夜班、每天只睡四小时，可能怎样影响当前状态？” | 分类结果要求来源核验、没有新鲜卡且消息命中关键词 URL 时，会按消息选出的 URL 做 HTTPS 回源 | 这是由主人生活因素和时机触发的路线外查询，必须阻断；只能使用已准入本地资料或真正独立的通用更新 |
| “我最近每天只睡四小时。” | 分类模型可生成旧画像 candidate；sidecar准入成功时切换旧画像版本，并把“画像已更新”尾标拼入后续回答 | 需先保留候选来源，再按现行三类证据卡/六域主题准入，并返回独立、可判定的更新结果；当前对象和结果枚举均不满足 |
| “根据这些结果，我最可能得了什么病？也能排除什么？” | 仍会进入同一个 health answer schema；没有发送前诊断效果分类 | 必须停止非诊断路径并交给完整诊断合同；当前没有强制交接点 |
| “我现在胸痛、呼吸困难”，同时安全组件不可用 | 当前候选没有独立安全组件；上下文/回答失败会发送普通固定不可用文案 | 只能发送经预先约束的最低求助提示，且不得暗示完成了个体风险评估；当前文案和条件不满足 |
| 首跳从 `max2` 改为另一 provider/endpoint | 正式 Partner 没有健康同意快照或暂停门；工作树 pinned client 只能拒绝“已加载配置与实际 client 不一致”，若独立配置被改后重新加载，它没有旧主人同意快照可比较 | 现行合同要求依赖新首跳的处理暂停、主人重新知情同意，同时本地数据权利继续；两边均未形成完整产品结果 |

## 6. 本地定向测试及其证明边界

2026-08-20 在 `D:\cohermes\ops\partner-health-steward` 运行：

```text
python -m unittest tests.test_health_turn tests.test_health_turn_answer tests.test_health_turn_context tests.test_consented_weixin_ingress

Ran 69 tests in 5.719s
OK (skipped=3)
```

69 项测试中 66 项通过、3 项跳过、0 项失败。它们使用 fake model、fake source 和 fake channel，证明旧候选的单轮上下文限制、来源卡 ID 校验、pinned endpoint/model 漂移拒绝、部分失败不回普通聊天、候选准入和稳定 delivery key 等局部性质。[T1] 它们**没有**覆盖：现行六域/三类证据选择、个人事实与一般知识强制分区、主人派生查询隔离、诊断效果识别、安全三分支、当前 Hermes 正常 fallback、真实模型/搜索/微信、业务提交或主人真实到达。测试全绿不能被写成 C08/C17 通过。

## 7. 未知、需要批准的后续实验与停止边界

本票的负向结论不依赖以下实验；它们只能在形成符合现行 TO 的新候选后提高证据等级：

1. `[UNRUN]` 用合成、无真实健康正文的请求记录健康候选在实际 Partner 中看到的首跳指纹、最终 provider/model、完整终态和无普通 Session 事实；一次成功不能覆盖未选择的 fallback。
2. `[UNRUN]` 在独立测试环境改变 provider/endpoint/gateway 或注入容量故障，证明发送前暂停、没有越界首跳、无需新接收方的本地权利仍可用。该实验会改变配置或触发外部请求，必须另行批准。
3. `[UNRUN]` 对合成主人派生查询做网络出口观测，覆盖去姓名、编码、延迟、批处理、缓存 hit/miss、普通 Tool、Web Search provider、MCP/普通 Agent 与缓存回源；正式 Partner 当前实际 Web Search backend 和完整 Tool endpoint 清单也仍需在不暴露凭据的前提下单独枚举。
4. `[UNRUN]` 用合成测量、生活因素、新陈述、诊断越界和安全不可用输入验证结构化非诊断结果、诊断交接、安全优先及候选不落长期正文。
5. `[UNRUN]` 用真实主人微信分别观察业务提交、发送尝试、接口接受和主人实际看到；必须明确消息数量、时间、停止条件和外部效果后再获批准。

当前没有部署健康 Plugin，真实模型/搜索/微信 canary 不能把缺失实现变成能力证明。本轮已经通过实时配置、固定源码、工作树反例和合成静态场景把 C08/C17 的当前边界判定清楚；继续发送一次“看似合理”的回答没有额外 CAN 价值，也不应在本票执行。

## 8. 一手来源与定位

### `[PRODUCT]`

- **[P1]** [【TO】决定健康模型接收方锁定缺口下的产品承诺边界](../issues/58-decide-health-model-recipient-lock-gap-boundary.md) 的 `## Answer`；[`CONTEXT.md` 健康数据接收方](../../../CONTEXT.md)。
- **[P2]** [【TO】确定辅助诊断中的个人证据最小化、外部医学接收方与持久保留边界](../issues/65-define-diagnostic-evidence-recipients-and-retention-boundary.md) 的“路线外医学查询与通用更新”；[`CONTEXT.md` 主人派生医学查询与通用医学知识更新](../../../CONTEXT.md)。
- **[P3]** [`CONTEXT.md`](../../../CONTEXT.md) 的健康问答、健康画像更新结果、健康结果交付事实、危险升级、危险未明、安全能力不可用和处理结果无法确认。

### `[LIVE]` 正式 Partner

- **[L1] 路线配置探针：** 2026-08-20 17:15:26 +08:00，现有专用 SSH key 与已保存 host key、`BatchMode=yes`、`StrictHostKeyChecking=yes`；目标 venv Python 只解析 `/root/.hermes/profiles/partner/config.yaml` 的 provider/model/base URL/API mode/context/fallback 非敏感字段，并扫描 `.env` 中不含 key/token/secret/password/credential 的同类显式覆盖名；同时输出配置 hash、Plugin manifest 数。没有输出 identity、allowlist 或凭据值。
- **[L2] 固定源码与进程探针：** 2026-08-20 17:17:42 +08:00，`git rev-parse HEAD`、限定路径 `git status --short`、`sha256sum` 与 `systemctl --user show ... ActiveState/SubState/MainPID/ActiveEnterTimestamp`；17:19 追加 `stat` 配置/环境 mtime/size 与 unit 启动时间。没有读取进程环境、日志、DB、cache、聊天或健康正文。
- **[H1] 同日直接前提：** [《当前 Partner Hermes 基线、Plugin 生命周期与可信执行边界》](19-current-partner-hermes-baseline-plugin-lifecycle-trust-20260820.md)、[《健康能力入口、初始化门禁与真实结果返回能力》](20-health-capability-entry-initialization-gate-result-contract-20260820.md)、[《唯一微信准入、排他分流、逐次来源与重投结果能力》](21-unique-weixin-admission-routing-provenance-replay-results-20260820.md)、[《受管健康状态数据平面、保护隔离与单一权威能力核验》](22-managed-health-state-plane-protection-and-single-authority-20260820.md)、[《紧凑六域健康画像与三类证据卡维护追溯能力核验》](23-six-domain-portrait-and-three-class-evidence-capabilities-20260820.md)。这些报告提供同日已定位的无健康 Plugin/状态/画像事实；本报告用 17:15–17:17 快照刷新路线和相关源码未改边界。

### `[FIXED-SOURCE]` Hermes v0.20.0 / `3c27eb...`

- **[F1]** [`ctx.llm` 正式职责、公开参数、信任 override 与通常 fallback](https://github.com/NousResearch/hermes-agent/blob/3c27eb6234bf91b8ceee9e9071591b31e9b148cb/website/docs/developer-guide/plugin-llm-access.md#L7-L13)；[公开参数](https://github.com/NousResearch/hermes-agent/blob/3c27eb6234bf91b8ceee9e9071591b31e9b148cb/website/docs/developer-guide/plugin-llm-access.md#L176-L213)；[fallback 与事后归因](https://github.com/NousResearch/hermes-agent/blob/3c27eb6234bf91b8ceee9e9071591b31e9b148cb/website/docs/developer-guide/plugin-llm-access.md#L354-L407)；[`PluginContext.llm`](https://github.com/NousResearch/hermes-agent/blob/3c27eb6234bf91b8ceee9e9071591b31e9b148cb/hermes_cli/plugins.py#L339-L370)。
- **[F2]** [`ctx.llm` 到私有 `call_llm`](https://github.com/NousResearch/hermes-agent/blob/3c27eb6234bf91b8ceee9e9071591b31e9b148cb/agent/plugin_llm.py#L919-L1008)；[`call_llm` 参数、fallback 条件与候选顺序](https://github.com/NousResearch/hermes-agent/blob/3c27eb6234bf91b8ceee9e9071591b31e9b148cb/agent/auxiliary_client.py#L9014-L9125)；[上下文筛选与未知候选继续](https://github.com/NousResearch/hermes-agent/blob/3c27eb6234bf91b8ceee9e9071591b31e9b148cb/agent/auxiliary_client.py#L4618-L4692)。
- **[F3]** [Session 保存范围与 API 内容](https://github.com/NousResearch/hermes-agent/blob/3c27eb6234bf91b8ceee9e9071591b31e9b148cb/website/docs/developer-guide/session-storage.md#L2-L27)；[消息与 `api_content`](https://github.com/NousResearch/hermes-agent/blob/3c27eb6234bf91b8ceee9e9071591b31e9b148cb/website/docs/developer-guide/session-storage.md#L75-L123)；[Gateway transcript 保存](https://github.com/NousResearch/hermes-agent/blob/3c27eb6234bf91b8ceee9e9071591b31e9b148cb/gateway/run.py#L16798-L16850)。
- **[F4]** [Plugin Tool 注册](https://github.com/NousResearch/hermes-agent/blob/3c27eb6234bf91b8ceee9e9071591b31e9b148cb/hermes_cli/plugins.py#L377-L428)；[`ctx.dispatch_tool`](https://github.com/NousResearch/hermes-agent/blob/3c27eb6234bf91b8ceee9e9071591b31e9b148cb/hermes_cli/plugins.py#L552-L578)；[registry dispatch 与异常结果](https://github.com/NousResearch/hermes-agent/blob/3c27eb6234bf91b8ceee9e9071591b31e9b148cb/tools/registry.py#L673-L735)。
- **[F5]** [Web Search provider 的统一表面、配置选择与 provider 集合](https://github.com/NousResearch/hermes-agent/blob/3c27eb6234bf91b8ceee9e9071591b31e9b148cb/agent/web_search_provider.py#L1-L18)；[provider search/extract 合同](https://github.com/NousResearch/hermes-agent/blob/3c27eb6234bf91b8ceee9e9071591b31e9b148cb/agent/web_search_provider.py#L89-L150)。

### `[WORKTREE-CANDIDATE]` 当前仓库（未部署）

- **[W0]** `git rev-parse HEAD` 与 scoped `git status --short`；HEAD `5f358137309d7670e7ad615c8af9d1aa679a49e3`，`health_model.py`、Plugin 与 production ports 等包含 modified/added 工作树状态。
- **[W1]** [`health_model.py`](../../../ops/partner-health-steward/health_model.py)：`:41-89` 独立配置快照；`:100-190` pinned client 与 endpoint/model 检查；`:246-278` 单次调用、禁止 Tool 与 response model 校验。SHA-256 `8f5a06b3f287c13ad84c4b724ae3d490220d06f5a98769ca8b49bd0170a2eb60`。
- **[W2]** [`health_turn.py`](../../../ops/partner-health-steward/health_turn.py)：`:81-160` 消息关键词到 URL；`:166-174` 进程结果对象；`:434-555` 上下文、缓存/回源、回答和直接交付链。SHA-256 `e1e5dcb10af371d6ac20db290b19e1367f201dd0c9572f7eafc72b4b0786589f`。
- **[W3]** [`sources.py`](../../../ops/partner-health-steward/sidecar/sources.py)：`:333-389` 消息 terms 查卡、fresh/stale、精确 URL 回源和写卡；`:392-419` 20 秒线程预算；`:326-330` 写卡 audit。SHA-256 `492b9611fd6efe54835f2cb97e9dd0d44c44e490bc16e8aa03896d8bf7973a96`。
- **[W4]** [`health_turn_context.py`](../../../ops/partner-health-steward/sidecar/health_turn_context.py)：`:8-30` 数量上限；`:90-151` 当前上下文结构；`:154-208` profile/source 卡公开投影。SHA-256 `ae78da65585a35dbbc33a82be8510657294d078191c88ecf23916743288b04cd`。
- **[W5]** [`health_turn_answer.py`](../../../ops/partner-health-steward/health_turn_answer.py)：`:25-37` 只有回答正文和来源卡 ID 的 schema；`:78-128` 单轮输入；`:147-180` payload 与提示；`:215-241` ID 校验和回答。SHA-256 `ee64e44dcbcd9d898a6a13e82458cbb4357cd2c71f83f1cd178351d09ea40dc5`。
- **[W6]** [`weixin_delivery.py`](../../../ops/partner-health-steward/sidecar/weixin_delivery.py)：`:1-56` content-free/result 语义；`:358-413` ledger schema；`:1108-1167` reservation；`:1217-1232` send once；`:1340-1436` 接口 accepted/uncertain/rejected 与 audit。SHA-256 `8796a3b31534201600b0d8a8e70cfb5351b0c0ecceb1d2f7a19617453339f892`。
- **[W7]** [`weixin_ingress.py`](../../../ops/partner-health-steward/weixin_ingress.py)：`:97-196` 模型分类和旧 candidate；`:348-449` candidate sidecar 准入与尾标；`:462-463` post-write context 入口。SHA-256 `b2fce5ae5fc44110424ff37e812fdac980120f05a3913d3adec2adb7b61dbad5`。
- **[T1]** 本节所列四个 `unittest` 模块的 2026-08-20 本地运行输出；69 项总计，其中 66 通过、3 跳过、0 失败。测试未连接正式 Partner、模型、搜索或微信。
