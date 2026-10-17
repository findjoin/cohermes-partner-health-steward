# Ticket 124 唯一增量设计候选：真实 Hermes 健康入口

状态：characterization / pre-code candidate，尚未冻结或通过预审。本文件不授予真实微信、模型、AWS、部署或主人验收权限。整合基线为 `19417da`，已包含 Ticket 123 的 `c9b0d64` 与非诊断阶段 A 的 `b32649c`。本文件同时拥有 Hermes 侧 Adapter 与 core 侧有限装配的设计；不再建立第二份接线设计。

## 1. 固定源码与已观察事实

调查对象为 Hermes commit `3c27eb6234bf91b8ceee9e9071591b31e9b148cb` 的只读 Git 源码导出；没有读取运行凭据、账号文件、聊天或健康资料。

旧 Ticket 118 常量保存 Windows CRLF 文件摘要；官方 Git blob / 本轮导出是 LF。以下四文件逐一仅转换 LF→CRLF 后，完全匹配旧常量，不能把这种字节约定差异当作 commit 漂移，也不能无声明地放宽 hash 校验。后续发布须明确 extractor 与原始/生成字节摘要，既有旧 release 的摘要不可改写。

| 相对源码 | 原始 LF SHA-256 | 旧 CRLF SHA-256 |
| --- | --- | --- |
| `hermes_cli/plugins.py` | `2cb8c309ce7747331669f22060a7e357e9c7a865f07cc779f30f17f8ce90daf5` | `2f74ddb96ed024cd2e085c2181751c610811e47f79f66a1ba7ce205c766664d8` |
| `gateway/platform_registry.py` | `22950c20edac9be90840e5ded37f932d29b25fd0f8d20c2b73d6efd86240d1cf` | `f7ebc66c09d40e883617f1a1a6700f621b4b14f94849b131bfacf0a80a623c4b` |
| `gateway/run.py` | `0b749a90ff5740b5c8ce9d138f869aca19295f4c458e3b680e9be9fd7b0fb2ec` | `328950c2369af1ca62b9cb8c97aaf1c931e8020b2535078bc84a9de258c4dfb5` |
| `gateway/platforms/weixin.py` | `e745f2bc7faaa6bbbdd8615fbfc79ca327ca6d0e7700620f37fc21fed14a178a` | `9c0650b68acf5847ded1eb16c42f5d10dd37d0bddb17b65dcb7ff9c9d37857e5` |

另核验 `gateway/platforms/base.py` LF 摘要为 `67262c97333b9e8274d269229ae6d0adecee104eaf5729208d0ea9b0ae8b814c`。

### 宿主实际调用

- `gateway/run.py:10974–10982` 在 connect 前调用 Adapter 的 message/fatal/session/busy/topic/authorization setters；只有 `connect/disconnect` 的 Ticket 118 探针类不满足实际 Gateway。
- `gateway/platforms/base.py:3471–3514` 的必要异步方法是 `connect(*, is_reconnect=False) -> bool`、`disconnect() -> None`、`send(chat_id, content, reply_to=None, metadata=None) -> SendResult`。`set_message_handler` 在 `3302–3309`；该 handler 只供被 core 明确判为 ordinary 的来源使用。
- `gateway/run.py:13613–13635` 优先 platform registry；返回 Adapter 后宿主设置 `gateway_runner`。`Platform._missing_` (`gateway/config.py:305–329`) 支持已注册插件平台。继续只注册 `health_weixin`；现有 hash-bound patch 继续排除旧/native 健康入口。

### 不能直接复用的 native 高层路径

- `weixin.py:1415–1421` 先保存 `get_updates_buf`，再 create_task 分派消息：这会在健康提交前越过 cursor。
- `weixin.py:1445–1455` 在准入和 core 之前做 message-ID/content dedup 并读取正文；两条同文不同 ID 会被丢弃。
- `weixin.py:1469–1507` 持久 context token、下载媒体、构造普通 MessageEvent 后做 text batching/handle_message；健康入口不能进入这条路径。
- `weixin.py:1794–1877` 自动重试，且 session-expired 后去掉 context token 重发；`send:1931` 生成随机 client ID。不能将其当作健康幂等、unknown-safe Transport。

可复用底层原语：`_get_updates(session, *, base_url, token, sync_buf, timeout_ms)` (`447–465`)；它只做一次 poll，空 poll timeout 返回原 cursor。`_send_message(..., context_token, client_id)` (`468–502`) 只做一次请求，真实发送由 Ticket 126 绑定当前 intent。`_api_post:418` 的原始异常可能包含 provider 正文，健康 Adapter 必须把异常转成固定 reason code，不将原异常/载荷写日志。

### 凭据位置只作运行边界说明

`WeixinAdapter.__init__:1196–1198` 的优先级为配置/extra/secret-env；缺 token 时 `1263–1267` 可按 account ID 读 `weixin/accounts/<id>.json`；`load_weixin_account:287–295` 是现有账号文件读取。Ticket 124 不执行登录，不复制账号文件或其内容到 core/release/证据。默认生产 Transport 仅在明确 live gate 通过后、Plugin 进程内读取当前 default 的既有配置；测试必须注入无网络 fake。

## 2. 当前产品接缝与现实差额

`HealthPlugin` 已有 `receive_weixin`、初始化披露/prepare/commit/finalize、native cursor、health_operation、managed reads、controlled_effect 等受信公开入口。`DailySkillRuntime` 已有 purpose-limited contexts、typed candidate、两段提交和真实 attestation，不重写这些业务状态机。

123 的 `ProductionCoreService` 已有真实 socket/peer、SQLite/vault/current-head/lifecycle。仍有三个可复现接线差额：

1. `start()` 只构造 lifecycle/vault，未注入 admission、初始化 runtime/verifier、七 Skill、route/model/knowledge/status 依赖；Plugin 没有这些依赖会失败关闭。
2. CorePort 的 command 只接受低层 CommandEnvelope，managed-read 只暴露 runtime，effect 只做合成 claim/terminal；真实消息、初始化及日常操作尚无跨进程公开映射。
3. 现有 `hermes_host` connect 强制消费一个 model-work 探针；没有待执行 intent 时不能成为正常连接流程。真实 connect 不应调用模型或发送健康内容。

## 3. 唯一职责划分与公开 Seam

新增一个真实宿主 Adapter `LiveHealthWeixinAdapter`，实现 pinned BasePlatformAdapter 必要 Interface。它拥有逐条 header 检查、CorePort client、poll/ordinary dispatch/cursor 适配和受控发送调用；不拥有 DB、current-head client、密钥、Skill 执行、业务成功决定或发送重试权。模块仅在 Hermes 插件工厂需要时加载真实宿主依赖，不以自制 Base stub 冒充 pinned API。

公开构造 Seam：`LiveHealthWeixinAdapter(config, *, core_port=None, ingress_transport=None, delivery_transport=None)`。公开可观察方法为 pinned lifecycle、`poll_once()` 和 `wake_current()`。测试用受控依赖；生产缺绑定保持 unavailable，不默认回落普通健康聊天。

Ingress Transport 的唯一必要公开形状：异步 `connect() -> bool`、`get_updates(cursor: str) -> dict`、`acknowledge_cursor(cursor: str) -> None`、`disconnect() -> None`。get_updates 返回 iLink 形状 `ret/errcode?/msgs/get_updates_buf`，不自行保存 cursor、dedup、batch、下载媒体或调用普通 Agent。acknowledge_cursor 只是 core 已批准 cursor 的传输持久化投影，不是第二权威。

Delivery Transport 由 126 提供异步 `send_committed(core_reply_intent: dict) -> dict` Seam，只接收 core 发出的 exact intent/grant，不接收任意聊天文本；124 只使用 deny-network fake。框架 `send()` 不能成为健康发送旁路。普通消息的正常宿主回复只在 core 明确 ordinary 的调用上下文中允许，不继承任何健康发送批准。

Core 侧新增 `LiveHealthCoreOperations(plugin, *, current_generation=callable, wake_current=None)`，公开 `dispatch(kind, payload)`。它是有限公开操作到既有 Plugin 方法的装配器，不是第二业务权威。generation callable 必须由生产组合根的 current-head/core 提供；不得信任 caller 写入的 phase、owner、consent、generation-current 或业务成功字段。内部配置和 helper 不冻结为测试要求。

`ProductionCoreService(..., live_runtime: LiveHealthRuntime | None = None)` 显式注入 live operations 与 release-bound runtime：同一 AdmissionPolicy、HealthInitAsset/attestor/runtime、DailySkillBundle/attestor/runtime、route provider、知识/安全资产和 status authority。缺项、hash 漂移、错 owner/policy 或 staged-only 资产均保持原 unavailable。core 仍无模型/微信凭据或直接网络发送。

## 4. 三类 CorePort 内的固定操作

不新增 RPC kind，保留现有低层 command、runtime probe 和 123 request/EOF/framing/peer 规则。command 的新 payload 精确为 `{"interface":"health-entry-v1","operation":<固定操作>,"payload":<dict>}`；managed-read 精确为 `{"interface":"health-entry-v1","projection":<固定投影>,"payload":<dict>}`。只允许以下有限操作，禁止反射、任意 method/table/path 或普通状态写 RPC。

| Kind | Operation / projection | 映射与结果边界 |
| --- | --- | --- |
| managed-read | `health-entry-preflight` + headers（无正文） | 返回 `allowed/current_generation/initialization_phase/reason_code`；检查当前 core 活体与精确技术准入；失败时 Adapter 不读取 item_list/body |
| command | `receive-weixin` + message | 以真实来源元数据和 lazy body 形成 RawWeixinMessage，调用 `HealthPlugin.receive_weixin`；仅返回 `{"response":Response.to_wire()}`，不伪造业务成功字段 |
| command | `initialization-disclosure` | 调用 form_initialization_disclosure；返回真实 owner-visible 文本与 challenge，不自动同意或提交 |
| command | `initialization-consent` / `initialization-commit` / `initialization-finalize` | consent 仅将已准入且匹配真实 OwnerConsentEvidence 的 initialization 交 prepare；commit/finalize 为独立无额外字段操作。Adapter 按顺序调用并读回 enabled；任一 unknown 停止，不显示初始化成功 |
| command | `native-cursor-result` | 复用 record_native_cursor_result；caller 的“接口完成”不能替代业务提交 |
| command | `wake-current` | 只唤醒已有当前任务/当地日复盘/unknown 恢复；不创建独立 timer、补 backlog 或自由发送 |
| managed-read | `health-entry-initialization` / `health-entry-business-status` | 目的限定、无正文的当前状态；普通 Hermes liveness 不作健康成功 |
| controlled-effect | 既有 model/owner/contact effect operation | exact core intent/lease/grant 与完整终态，保留 stale-fence 拒绝及 unknown 冻结；不因 connect 自动执行 |

消息 payload 的 header 使用 SourceEnvelope 同名字段，正文为 `body`；generation 取 preflight 的 `current_generation`，caller 值仍由 receive 再核验。preflight 不含 `body/generation/requested_capability`；其余 header 字段为 `causal_id/channel/partner_id/sender_id/conversation_id/chat_type/entrypoint/message_id/protocol_timestamp/received_at/native_cursor`。Adapter 先以本机固定 admission 配置拒绝不匹配 header，再调用 core preflight；只有两者允许才取正文并判定明确初始化意图。不能用遍历/序列化完整 native message 的方式提前触碰 item_list。

已提交唯一回复从 `response.meta.turn_result` 的 `record_id/transition_id/owner_reply/skill_disclosures` 取得，作为 126 `send_committed` 的受控业务输入；不是 caller 自由传入的文本。126 必须以 record/source identity 形成或读回既有 core owner-reply intent，不因 native replay 再生成 effect。初始化披露返回 `disclosure.to_storage()`，初始化状态返回 `{"initialization":projection.to_storage()}`。

收到健康消息时不得构造普通 MessageEvent 或调用 ordinary handler、Base.handle_message、Session/Memory/FTS、媒体下载、通用日志。只有 core 明确返回 ordinary，才交还 pinned 的既有 ordinary handler；不能把 unavailable、unknown、解析失败或健康/混合/不确定消息作为 ordinary fallback。初始化前普通聊天和明确 health-init 仍按现有产品边界区分。

## 5. 初始化、回复、cursor 和重启不变量

### 披露与下一来源确认

收到明确初始化意图只形成并呈现 disclosure。为该 workflow 预分配 callback causal ID；它与原生 message_id 是不同身份。界面必须让主人明确确认资料边界与实际首跳路线，不通过配置 booleans、LLM 自述、部署指令或第一次初始化请求推定同意。

`OwnerConsentEvidence:709–711` 已允许 Adapter 在呈现披露后构造 callback。下一条带 challenge 的明确确认到达后，才构造该既有 canonical evidence；保留此次真实 native message_id、协议时间与接收时间。只转换这种明确 consent callback，不篡改普通/健康正文。core 继续检查 challenge、配置、来源、披露先于确认、重投、prepare/CAS/finalize；没有足够时序证明不得猜测通过。重启后通过现有加密 challenge/初始化状态恢复，不能只依赖 Adapter 内存同意。

### 唯一已提交回复

健康回复来自 core 已提交结果，先取得现有受控发送权再让 126 Transport 执行；没有 intent/grant 不发送。披露送达、业务提交、发送尝试、接口接受、送达/已读是不同事实。响应丢失或回交失败进入现有 unknown，不重新生成自由文本、不盲重发、不将 interface accepted 当作主人已看到。

### Batch 与 cursor

对一份 getupdates 响应逐条处理，不合并同文。保留每条 message_id、来源与协议时间，因果 ID 不由正文 hash 去重。native cursor 只能在该 batch 所有需处理的来源均获得 core 已提交 directive 后 acknowledge；一条 unknown/failure 即不推进整个 cursor。外部准入排除可作为明确 ignored 处理，但不得触碰正文或伪造健康 receipt。空 batch 可无内容推进；重启从 core 已批准 cursor 恢复，不把先前 native sync 文件当作单独业务真相。

同一 source replay 只能读回已有业务/发送状态，不能产生第二条业务事实或第二次未知发送。ack 完成后把 native cursor result 回交 core；必须由同一Core receipt的native_cursor_state=advanced证明回交完成，裸transport ack不是该证明。沿既有112隐私规则，advanced后daily result可以被清除；重放可仅返回accepted/daily-turn-result-redacted及已finalized的无正文terminal身份，不重建已释放的reply、turn result或再次调用delivery bridge。record/transition及terminal身份仍须保持相同。结果未知时保留可恢复状态。wake/reconnect/disconnect 使用同一规则。失去 core/peer/required asset/current head 时关闭健康接收和效果，不让 Gateway 普通存活掩盖故障。

## 6. 模型候选阶段的具体阻塞与实现边界

不能把 `DailySkillRuntime.executor` 随手换成直接 HTTP 模型：`plugin.py:480–483` 在证据阶段调用 executor；`core.py:5361–5374` 仅允许已 evidence-finalized 的来源取得现有 model-work intent。若把自然语言抽取放进该 executor，触发链为“主人正文 -> 无 core intent 的外部模型调用 -> 接收方/consent/unknown 绕过”。这是已定位的现实差额。

124 只装配现有 typed executor 与七 Skill 使用证明，证明实际调度和提交；不借有界 parser 或 fake 回答宣称完整自然语言产品已完成。125 必须先闭合已有 evidence-finalized -> core-issued exact model intent -> StrictHealthLLM -> 完整 terminal -> 非诊断候选/唯一回复的路径。若通用自然语言抽取还要求证据阶段前的模型，必须用此调用位置证据提出同一 controlled-effect 内的受控候选阶段增量，由顶层决定并交独立 verifier 冻结；不能静默扩大当前授权接缝。

## 7. 独立验证输入与停止条件

验证 Agent 独立拥有最高公开 Interface 的门，至少证明：真实 pinned Base/registry lifecycle 可调用；poison item_list 在拒绝 header/preflight 时零读取；两条同文不同 ID 不丢失、同来源 replay 无重复；batch 内 unknown 不推进 cursor；真实披露后下一来源明确同意才能 enabled；健康正文不进入 ordinary handler/Session；wake/restart/co-stop 不盲重复；staged/缺 hash/缺 runtime 不被探针伪装成功。测试不锁 private helper 或增加第二账本。

保留 118/120/123 和相关 111/112 回归。实测 Gate 必须绑定源码字节约定和同一 release；本轮 source export 无 `.git`，不能伪造 checkout identity 来满足旧 verifier，需由根代理准备可验证的固定 Git artifact 或形成显式 extractor 证据。

任何必须重写既有 core 状态机/第四 RPC、降低同意、用 ordinary path 承接健康正文、使用真实微信/model/AWS/partner 或部署的需求，停止该分支并报告具体差额。此候选没有把这种停止变成例行用户审批；缺少真实绑定继续开发可独立完成的 Adapter/装配与 deny-network 测试。

## 8. 目标现场待核验前提（只返回无值证明）

- default 的实际 commit/required patch 与唯一 platform 绑定、原生入口禁用；partner 不触碰。
- 固定 Python 3.11、aiohttp/crypto、runtime 内容闭包与 ACL；core 专用 UID/GID、660 socket、三个私有 32-byte secret 与锁目录。
- AWS runtime identity、单区域 PK/SK string table、精确 TableId/installation/site/public fence binding、最小 IAM、首次 HEAD 的一次条件 provisioning；当前无常用 AWS credentials/config，不能假装已有真实 Provider。
- default 既有微信凭据/account binding 与唯一 owner/private conversation 是否可用；只返回存在/权限/绑定检查，不复制值。
- 首跳元数据 jojo / gpt-5.6-sol / codex_responses 是待绑定输入；240000 的配置数字不证明容量下界。真实 profile/token measurement/actual-model 集合由 125/128 门核验。
- 外部门未获执行时保留不可用/无法确认；诊断内容权利与专业审核由 127 负责，仅门禁完整诊断阶段，不能用 staged bundle 伪装最低安全资产可用。

## 冻结公开构造与唯一 wire（本节消除候选讨论歧义）

Module 固定 `partner_health_steward.live_health`。`LiveHealthCoreOperations(plugin, *, current_generation, wake_current=None)` 公开 `dispatch(kind, payload)`，内部如何分派为可逆实现细节。以上三类 CorePort 的新入口统一包裹 payload，不同时接受扁平旧候选：

- command：`{interface: health-entry-v1, operation: <固定操作>, payload: <操作字典>}`。
- managed-read：`{interface: health-entry-v1, projection: <固定投影>, payload: <投影字典>}`。
- receive-weixin 操作字典只有 `message`（SourceEnvelope 同名十四字段）；结果只有 `response`，为既有 `Response.to_wire()`。唯一回复已在其 `meta.turn_result` 中，不额外生成任意文本 reply。
- preflight 投影字典只有 `headers`（上一节规定的十一项无正文 header）；结果精确为 `allowed/current_generation/initialization_phase/reason_code`。`current_generation` 在无法核实时为 null，allowed 为 false。
- initialization-disclosure 与 initialization-consent 操作字典只有 `initialization`（既有 OwnerInitialization storage）；disclosure 返回 `disclosure` storage，consent 只调用既有 prepare，不从 caller 布尔生成 OwnerConsentEvidence。
- initialization-commit/finalize 与 wake-current 操作字典为空；cursor-result 只有 source_causal_id/status，由 core 读回原 directive，不接受 caller 构造 directive。
- initialization/status 投影 payload 为空，分别返回 `initialization` storage / `business_status`（既有 to_wire/storage 投影）。

`LiveHealthRuntime(admission_policy, health_init_runtime, coarse_router, daily_skill_runtime, *, asset_paths, core_options=None)` 是唯一 typed 装配对象。asset_paths 是七个规范名到当前 release 内相对路径的完整映射；路径不得越界/符号链接，真实文件 SHA-256 必须与对应 runtime asset 相等，staged/unavailable 文档拒绝。core_options 只允许 HealthCore 已有的业务依赖（status/route/model/knowledge/安全资产及既有 acceptance provider）；禁止 store/head/vault/lifecycle 或任意 factory/method。生产组合根保留这些原有权威的唯一所有权。None live_runtime 保持123 staged兼容，不表示健康已接通。

公开 `ProductionCoreService(binding, *, current_head, live_runtime=None)`；start 在启动 socket 前核验 live_runtime 对同一 verified release 的上述约束，再向同一个 Core/Plugin 注入同一依赖。测试不能用实例字段读取或任意反射代替这条装配链。

### 冻结前补齐 cursor 读回接缝

managed-read 固定投影 `health-entry-cursor-directive`，payload 只有 `source_causal_id`；调用现有 `HealthPlugin.native_cursor_directive`，返回 `{"directive": <包含既有四字段的严格 dict 或 null>}`。这是同一 Core 的已提交 directive 只读投影，不产生第二 cursor 权威。Adapter 必须先读该投影、核验它绑定当前来源与候选 batch cursor，才执行 acknowledge_cursor；实际完成后才发 native-cursor-result。读取不到或未知时不 acknowledge，也不提前记录 accepted。

### 生产启动补装配边界

现有 systemd 的 `python -m ...production_core_service --binding ...` 在任何输入下都会抛出 DynamoDB injection required，故124的生产装配必须补齐可执行 bootstrap。继续复用唯一 DynamoDBCurrentHead：通过独立 canonical non-secret head-binding 工件提供 DynamoHeadBinding 七个字段，由受限宿主标准凭据链创建 boto3 low-level client，禁止业务重试、自动创建表或覆盖初始HEAD；没有真实资源/凭据时明确 unavailable。core 不取得模型/微信凭据。SIGTERM/SIGINT 走现有close并退出，不留下第二worker或socket。target binding和资源provision仍由G08/G10控制；此处不调用真实AWS或写目标配置。

完整日常自然语言抽取仍受已记录的候选阶段模型授权缺口约束；124可交付真实入口与合法 typed runtime 装配，不能把只支持固定解析/注入fake executor的路径宣传为整个健康产品完成。若后续需要最小受控候选阶段接缝，应在同一Map以精确实施差额和独立门承接，不放松已有model grant/提交语义。

### 唯一 registry 工厂选择

既有 `register()` 的 `adapter_factory` 在 `config.extra` 显式包含 `admission_policy` 时创建 `LiveHealthWeixinAdapter`；值必须是既有 `AdmissionPolicy.to_storage()` 的规范形状，无效配置失败且不得回落旧探针。可选 `core_port`、`ingress_transport`、`delivery_transport` 仅为宿主 Python 显式注入的测试/组合根对象；实际 endpoint 由 `core_port_endpoint` 固定提供。未提供 admission_policy 时保留118旧探针兼容；该探针不获得 live activation。独立门必须经真实 registry factory 取得 live 实例。

### 三项预审缺口的最小闭合（候选修订）

1. 生产socket门须在同一AF_UNIX服务完成真实初始化与一次typed日常提交，证明依赖真的注入同一Core/Plugin，不能只读uninitialized。
2. 实际registry-created Adapter必须走明确初始化和下一独立native确认：`/health-init`，随后 `/health-init-confirm <workflow_id> <disclosure_id>`。宿主 `config.extra.initialization_template` 是既有OwnerInitialization规范storage，两项consent必须false；首次来源只稳定派生workflow_id及预分配callback causal_id，不默认同意。确认来源保留实际native message_id和时间，绑定core读回的同一challenge后才转换既有OwnerConsentEvidence。模板、challenge不匹配或状态未知均不提交；不因首次请求自动确认。
3. Adapter重建后第一poll的cursor必须从同一Core的已接受source receipts派生读回；同一来源重放仍稳定，不靠内存保存身份或单独cursor账本。

为上述既有行为增加两个目的限定managed-read投影，仍使用相同health-entry-v1 wrapper：`health-entry-native-cursor` payload `{}` 返回 `{"native_cursor":<str|null>}`；`health-entry-disclosure` payload `{"workflow_id":<str>}` 返回 `{"initialization":<原OwnerInitialization storage|null>,"disclosure":<既有disclosure storage|null>}`。后者仅核验并读回既有加密challenge，前者从完整、已提交业务且native_cursor_state=advanced（外层Response为accepted）的既有receipt派生，不新增持久字段/表。Core/Plugin/storage可增加对应固定purpose getter，不能把通用SQL、所有source/body或任意store方法暴露给Adapter。初始无已接受cursor用空poll cursor；unknown不能推进。

同一126 `send_committed` bridge的有限输入区分：披露为 `{"kind":"initialization-disclosure","workflow_id":<str>,"disclosure":<storage>}`，日常为 `{"kind":"committed-turn","source_causal_id":<str>,"turn_result":<已提交meta.turn_result>}`。这些输入只请求126形成/读回已有受控发送授权，不是自行取得grant或任意文本发送权。124离线门可以记录core形成物并返回not-authorized；不得将此写成实际发送、接口接受、delivered或初始化成功。门中的第二合成owner确认只证明消息映射与Core同意边界，不替代126/128真实呈现/主人验收。框架send仍不能发送任意健康文本。

### 实施期返冻结：真实 registry activation 选择门

Pinned `platform_registry.create_adapter:293` 在factory前执行check_fn。独立门原先直接调用entry.adapter_factory，漏掉未arm导致真实Gateway仍选不到Live的现实路径。沿用118/120同process activation capability与release proof、`_ticket118_arm`，不新增持久批准或一刀将check_fn设True。未arm staged registration必须不能经registry创建；可信release-verified组合根arm后，实际registry.create_adapter在显式合法policy配置下取得Live，错误policy失败不回退旧probe。live factory也执行既有armed检查，不能通过直调绕过。无policy继续118旧probe兼容；真实default的验证/arm调用由既有128生产bootstrap装配，不把离线arm fixture当作真实上线证据。该返冻结只补实际registry路径门，不重开其他已通过finding，不暂停无关Core目的装配。

### 同次返冻结：发布物中的真实 Adapter 依赖闭包

现有Publisher仅在release-local Plugin package放__init__/hermes_host/host_contract，新增Live工厂的 `.live_weixin` 及typed依赖会在实际安装包中缺失。V03必须从实际Publisher.build产生的release-local包导入产品，不能靠仓库product路径掩盖缺文件。最小修复沿用当前Publisher/内容寻址file manifest，逐字包含现有项目Python模块作为同一发布物的完整代码闭包；不复制运行配置、健康库或秘密，不新建包管理器/第二release权威。Plugin只在其职责执行，包含Core的代码不授予其数据/密钥/网络权限。旧staged状态和七Skill unavailable标记保持原语义；缺生产运行绑定不被额外文件改成已激活。

游标“accepted”指既有外层Response.status；唯一已实现的receipt native_cursor_state为advanced。目的限定恢复投影只读advanced业务receipt，不增加accepted新状态或改111旧合同。

### 同次返冻结：初始化前 ordinary 的明确 Core 路由

既有Plugin.receive_weixin在未初始化时只允许health-init，因此Adapter把所有非初始化请求交health-steward会连普通聊天一起拒绝，违反本票已选行为。最小修复只在LiveOps的固定receive操作调用一个Plugin侧live-entry接缝：先在正文前核验同一技术policy；仅在当前phase为uninitialized且capability为health-steward时，允许既有CoarseMessageRouter对已准入正文明确返回ordinary，才形成accepted/ordinary-hermes-route。health/mixed/uncertain、classifier缺失/失败均不能ordinary fallback，也不写健康状态或触发未同意模型。其余来源继续既有receive_weixin。111旧公开receive的capability/零正文门不改，不新增RPC、状态或分类服务。门在真实未初始化Core的同一Adapter上观察一条明确普通消息进入ordinary handler，健康消息不能进入；独立确认/初始化原门不变。

### 有界返冻结：ACK 后沿用既有日常结果释放

正式V04已到实际重建/重投链，暴露验证假红：旧112的store._replace_source_receipt在native_cursor_state=advanced时释放daily.result正文，只留DailyTurnTerminalReceipt；Core.daily_turn_result可合法返回None，Plugin回accepted/daily-turn-result-redacted。这是已验证隐私行为，不能为124重放再重建旧reply。

因此ACK后的同事件重放只需证明既有finalized record/transition保持相同，不能要求再次返回已释放turn_result或再次调用发送bridge。未ACK且现有result仍可释放时继续原完整结果重放；unknown发送由126持有的已有effect/outbox事实保持冻结，不能靠重新构造旧reply或补做业务重发。此返冻结只修V04的相反预期，保留“无第二业务/无第二尝试/无第二状态账本”；不改变产品、111/112释放规则或真实投递验收。
