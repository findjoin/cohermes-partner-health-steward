# Ticket 128：default 非诊断部署唯一增量设计候选

状态：**characterization / pre-code design candidate，未冻结、未获编码授权、未部署、未验收**。日期：2026-10-24。唯一归属：[128](../issues/128-deploy-and-complete-owner-product-acceptance.md)；该票现为 `claimed`。本文件承接原119的固定完整验收与128既定两阶段增量，不重开130，不建立另一份Spec、Map、业务状态或验收账本。独立 verifier 合同、同 checkpoint 的 fresh Spec/Standards pre、生产实施和执行证据均仍待形成。

读取基线：仓库 `b5c73f5b681858568d3428aa18c2052514e57330`，产品仍为精确 `f21e8ad43bc92954da0a0ed5322cf421e48d0828`。130已由root闭合；其原20组件、801全量、root30和双轴审查证明该版本的离线产品，不证明实际default安装、凭据隔离、JOJO/Weixin调用、主人同意或本票验收。历史设计文件中的candidate字样与当时行号只作历史；当前代码与各票闭合证据决定现状。

## 1. 固定目标、范围与不变量

唯一安装目标为用户自己的 default `/root/.hermes`、root **用户级** `hermes-gateway.service`。任何partner路径/service、其他profile或动态target，在读取其业务配置、创建备份、provision、stage、service调用之前拒绝。Core和ordinary worker的专用私有目录不是第二Hermes画像或第二微信目标。

阶段A只启用非诊断：130真实受控记录/证据/画像、固定治理回答、明确单次提醒、当地日复盘、独立控制、权利/附件、固定最低帮助与实际已审阅的有限安全规则。BMI与全部诊断仍staged；无KnowledgeRelease时知识集合为空，literature如实返回缺口；不承诺任意医学问答、普遍自然语言危险识别或自动诊断。没有真实联系人与当前批准时联系人不可用，不猜身份，不向partner或任何联系人发送。

阶段B仍须127当前有效的真实权利、医学专业审核与严格模型容量依据，然后新的 `full` run 按原G01—G12、原五项G12 receipts和active-path readback验收。阶段A的技术通过、初始化enabled、owner feedback或ND里程碑均不替代这些事实；阶段A完成后128仍 `claimed`。

健康状态权威仍只有HealthCore + 原认证加密SQLite + 129 HostSQLiteCurrentHead；原source、grant、model journal、outbox、rights registry、lifecycle与唯一CAS不改权威。Core无JOJO/Weixin/Hermes token及AF_INET能力；网络由可信Plugin承担。普通Agent无健康凭据、Core路径或CorePort准入。131仍固定最终请求65536 UTF-8 bytes、输出2048 tokens、无自动切换/重试、不完整停止、**不提供共同上下文保证**。DMIT整机旧快照可能恢复旧资料/密钥/撤销状态的既有接受限制原样披露，不写防整机回滚已证明。

## 2. 当前characterization与必须补齐的现实差额

本轮只读源码及纯合成内存/临时目录characterization，不读实际default配置/凭据/正文、不连接外部模型/微信、不改实际service。

| 当前事实与定位 | 本票必须消除的差额 |
| --- | --- |
| `acceptance_run.py:20,210,284`：只有固定G01—G12、exact context无scope、首非passed停止、不可变report；119薄工具明确fixture-only | 在同Module/同report/同GateExecutor Seam内增加固定ND分支，不能在文档跳过G07或直接调用未来gate。 |
| `release_deployment.py:395–408,424,473`：真实Python被收集，但七Skill及四bundle仍staged占位；current-successor只加runtime attestation | 同Publisher接真实项目自有ND资源并重算原内容闭包；不得复制test publication或手工重算manifest成为第二发布器。 |
| `production_core_service.py:723,973,1855–1903`：typed LiveHealthRuntime可用，CLI实际未传live_runtime | 补同服务入口的真实typed factory/绑定和首次bootstrap；probe/三类RPC存在不等于业务入口已装配。 |
| `live_health.py:162–245`、130 runtime：七asset完整性、Core依赖、Plugin、两个schema及模型/投递链已可复用 | 目标装配真实admission、route/budget、attestors、资源与状态事实authority，不能导入fixture executor/key。 |
| `initialization.py:487–575,1346–1375`：executor返回的披露仍必须精确等于内置版本 | 新ND/host-only版本必须沿原matches/HMAC/challenge绑定，不能只换executor或另发补充消息后冒称同意已覆盖。 |
| `safety_diagnosis.py:89,243`：constructor接受scope=None，scope_wire却无条件解引用 | 明确无诊断scope的staged/unavailable投影，状态查询可读且不虚构BMI scope/hash/医学门。full的严格验证不变。 |
| `FilesystemManagedReplicaAdapter:369–399,524`：14个binding全文件存在，或已有真实purge receipt才可构造 | 首次真实“无外部受管副本”不能靠14个空假文件或假purge receipt启动；同Adapter需表达可核验absence。 |
| 120安装器是staged-only，备份/恢复仅plugins与metadata；controller已经 `systemctl --user` | 补本票固定current/live资源集合的安装/回滚，绑定root用户XDG/DBus；不误说现controller是system scope。 |
| `hermes_host.py:199–236`原注册/arm、pinned discover/start_gateway可复用 | 新启动根须同进程核验当前release并arm后进入原Gateway；不能用fixture bootstrap或启动第二poller。 |
| `live_weixin.py:_ordinary/send`已有普通上下文Seam；production delivery对象没有send_ordinary | 真正装配普通回复出站，不能把普通回复伪成健康grant，也不能只验入站handler便声称普通聊天可用。 |
| 原Core在初始化前禁止model-work；唯一preconsent效果仅当前初始化披露 | G11先于ND12，需119 target-local固定技术canary，不能假初始化/伪造Core authorization。 |
| 现HostReleaseContract credential observation要求 `synthetic-contract-only`；普通root local工具可达私有资源 | 生产隔离观测必须来自真实进程/OS，不重标synthetic；按第8节单一路线补齐。 |

独立verification在同基线的最高公开Interface补证见 `/tmp/ticket128-characterization-summary.md`、`ticket128-characterization-public-seams.py/.log`、`ticket128-characterization-results.json`：原119七门与111四门均绿；原full report同run重放executor零调用，fixture总结仍evidence-required；真实HealthPlugin的scope=None managed/status两条均复现异常；披露旧v1及任意新version标记仅改notice均被Runtime与Plugin拒绝且仍uninitialized。该本机解释器为Python3.12.3，与下面作者局部char均**不是正式Python3.11门**，两次结果不合算为生产通过。

### 已实际复现的三个有限反例

在上述基线用现有public类型与纯合成输入运行，未修改产品/测试：

- 旧 `InitializationDisclosureContent.for_initialization(...).matches(...)` 为True；只替换一条notice后matches为False；经原HealthInitRuntime.executor形成披露被拒绝为 `AuthorityValidationError: health-init-execution-failed`。
- `validate_assets`接受 `diagnostic_scope_bundle=None`；同资产传 `scope_wire` 得 `AuthorityValidationError: invalid diagnostic scope bundle`。这证明absence投影有差额，不证明任何真实安全内容已经批准。
- 私有临时root内14个目标路径确实均不存在，未建任何文件或receipt；原FilesystemManagedReplicaAdapter拒绝为 `ValueError: managed replica purge receipt is unavailable`，目录仍空。此为真实absence差额，不能以fixture的 `object-xx.managed` 规避。

root的现场无值原语观察只作输入：`/tmp/dmit-connection-audit/ticket128-default-isolation-primitives-readonly.log`（systemd249；setpriv/unshare/nsenter有，Docker/bwrap/setfacl无；当前default无该隔离）；`ticket128-isolation-characterization-v3.log`（disposable unit：gateway UID0/caps0/NNP能连合成socket而读不了合成key；低UID ordinary可写自己的工作区而key/socket均拒绝；低UID Core能读key、INET拒绝、credential env absent）。初版/v2的身份/父路径前提错误与失败保留。v3既不是生产账户/真实Core/实际Hermes装配，也不是G10通过；不把daemon/nobody用于生产身份。

## 3. 同一个119 Module的两个固定scope

公开行为仍为 `AcceptanceRunContract.run(current_release_manifest, gate_executor, run_context) -> AcceptanceRunReport`。caller只能选择 `full` 或 `non-diagnostic`；无任意gate列表、callback、顺序、跳过、pass条件或DAG。

| scope | 固定顺序 | 最强允许声明 |
| --- | --- | --- |
| full | 原119-G01—G12原序、原ID、原批准及五receipt规则 | 仅原条件全满足才完整产品验收；stable_operation仍evidence-required。 |
| non-diagnostic | G01—G06 → **128-ND07** → G08—G11 → **128-ND12** | 真实ND12满足时仅 `non-diagnostic-owner-usable` 无正文里程碑；diagnostic scope staged、active不成立、product acceptance不passed、128不resolved。 |

**同一release有两个既有身份，必须同时绑定。**119输入仍是118 `ReleaseManifest`，其中 `release_digest` 是host manifest身份 **H**；120 current distribution另有分发身份 **D**，两者不同。setup须从实际current目录重算文件闭包、嵌套 `host-release-manifest.json`/host-release关系及runtime attestation，证明H与D确属同一发布，不能信caller的两个字符串。新scope生产的run/context/request/execution-key/approval/report/replay/current-binding都同时绑定H与D（并保原target/scope）；同H但runtime attestation或distribution不同一律不借permit/重放。D才是120包目录/部署permit所绑定的分发身份，不能把H当/opt目录名或D；许可文件自身hash也不是第三个release身份。旧v1 full七门、wire、摘要与重放字节原样保留；生产Executor只接受已显式绑定D的当前scope上下文，旧无D报告不能充生产current包证据。此增量不创建第三digest/Release权威。

新scope模式的公开wire字段以 `release_digest` 保留H、以 `distribution_digest` 明确D；`run_scope` 与D成对必需，固定prepare输出与执行request/report/replay均一致，不接受只有一项的部分新模式。

scope是当前release/run/target/逐gate执行与批准绑定的一部分；同一run不可换scope、target或release。旧full输入/报告/摘要/重放字节兼容，缺scope的旧合法输入只解释为full；新增ND的report必须明确scope，不通过新增第二report class/账本实现。内部版本标记/codec可逆，但不得让旧full报告按ND重放或反向借用。ND不能产生119-G07/G12 passed或虚构127事实。

两个分支共用原首非passed停止、后继blocked、existing report零执行重放、严格opaque facts和synthetic降格规则。fixture/deny-network永不生成真实deployment/接口/owner verdict；real report不能只因environment字符串含target-local而自证。target-local Adapter对真实来源、当前批准与当前安装负责。

128-ND07固定检查：诊断scope缺席/未激活、真实诊断源入口拒绝且model/发送为零；只加载第4节获权固定ND内容；无医学审核/知识时如实absence，不激活staged包。128-ND12具有本gate独立批准，不能借119-G12批准；只读回第11节真实主人事实，不调用diagnosis.activate、不形成full五receipt。

## 4. 同一Publisher的真实内容与runtime闭包

Publisher保持确定性源码收集、regular-file闭包、required patch、原host manifest与distribution digest算法；无显式ND资源输入时旧staged输出兼容。ND输入是固定资源类别与完整版本/source/rights/editorial引用，不能接任意脚本、类名、命令或动态loader。旧tests及synthetic source/review只证明接口，不能上线。

生产资源最小集合：

1. 七个真实Skill全文与相配HealthInitAsset/DailySkillAsset metadata，确切名称与角色沿124/130，真实文件SHA-256与runtime逐一相等。内容描述当前typed executor：settings no-change、inquiry gap、literature无批准知识均如实说明，不写模型能自动诊断。
2. 五种固定治理claim（support/opposition/unknown/limitation/next-step）和一个确定性模板，按真实ApprovedClaimAtom/ApprovedReplyTemplate重验。文字仅说明资料来源、缺口、不能补事实、非诊断范围及澄清。类名中的Approved不构成批准来源；适用的实际编辑记录须可定位。
3. MinimumHelpBundle四模板，使用现有字段/256 UTF-8 byte限制、实际内容hash与中文/rights/review/parse事实；不靠截断满足上限。root将实际逐字审阅并发布本项目自有的纯治理/最低求助文案及有限非医学SafetyRuleBundle：只响应**全文明确的固定求助表达**，不从症状、数值阈值或用药推断危险。其权威是相称的真实编辑/执行边界审阅，**不要求冒充127医师审核**，也不因缺127而循环阻塞这种非医学最低求助。规则/文案正式字节、版本/hash和编辑记录在实施时由root实际确认，不能现在填approved常量。未实际审阅则保持safety unavailable；有有限规则也不宣称普遍危险识别，无联系人就零联系人外发，适用安全验收仍须真实通过。
4. `diagnostic_scope_bundle=None`，knowledge集合为空/absence声明。不得填假BMI阈值、假professional_review、过期approved-synthetic或借旧ops/partner包。
5. 新版本初始化披露全文及来源/版本；真实route/budget/default无联系人事实在装配时绑定，不把秘密、身份或最终实例值放进内容release。

`/tmp/ticket128-nd-content-draft.md`及editorial-review是root已编辑过的一轮**未发布输入**，非获批生产包。来源明确为本项目新写，最低帮助四文案183/192/201/225 UTF-8 bytes；八topic文本共2668 bytes。实际资源生成后仍须重新核对版本/hash、文本适用性和真实编辑事实；不复制其draft状态为approved。KnowledgeRelease进入仍需原KnowledgePublisher权利、中文、专业审核与currentness全部真实满足。

所有生产内容、组合源码与required shadow patch进入同一内容闭包。先build，再用现成 `publish_current_successor(staged_root, verified_runtime_manifest)`形成current；不要将最终release_digest反写到已hash资产造成自引用。SafetyAssets/lifecycle的实例外层release绑定由组合根在验证后形成。runtime使用原固定Python3.11 closure validator/attestation，不能把系统Python3.10、本机3.12或未声明pip包当生产闭包。一次性closure构造须来自固定可重建输入并被同validator核验；不把旧formal临时runtime直接改名为生产。123对runtime_root与release_root真实要求当前Core euid/egid及无group/other写，须正常provision该身份与可遍历祖先、通过unit只读保护代码；子文件仍原全量hash/no-symlink规则。代码/依赖非秘密可受限0755/group读，私有key/DB/head不放宽。原base闭包已有aiohttp；pinned完整Hermes在旁树而不在旧123 runtime manifest，API listener绿不证明三角色全部AIAgent/工具import来源，须沿原full-file canonical/Publisher attestation/HostContract proof实际验证（输入见 `/tmp/ticket128-runtime-identity-inputs.md`）。实际Hermes3.11 venv在低UID/空环境/独立HOME/OS限制下已真实import run_agent、terminal/file/MCP tools及api_server且来源为固定Hermes树（`/tmp/dmit-connection-audit/ticket128-ordinary-import-characterization.sh/.log`）；audit拦截到1次socket.bind，不能说零网络尝试，0模型构造/POST/微信poller。它只证明现有安装依赖可复用，不能充新sealed closure或完整turn，后续builder从固定已有字节构造，无需在线装包/换解释器。

## 5. 有界typed生产factory与披露/status差额

新增一个固定生产composition factory，供原Service CLI与default可信Gateway启动根使用。它只接已验证release、目标私有无secret绑定及进程内secret capabilities，不接任意导入路径、业务body、executor callback或通用配置字典来挑模块。Core侧与Gateway侧依赖分开创建，避免导入Core factory就加载Hermes credentials/network。

Core侧构造现有AdmissionPolicy、HealthInitRuntime、CoarseMessageRouter、六DailySkillAsset bundle/DailySkillAttestor、131同一budget strategy、固定intake/answer StrictHealthLLM、GovernedNonDiagnosticRuntime、LiveHealthRuntime、CapabilityFactAuthority及原批准文案/最低帮助资产。HealthCore仍仅由ProductionCoreService建立，继续负责lifecycle/SQLite/资源关闭/peer与effect session。Core不加载模型/Weixin token。

Gateway侧构造现有真实model bridge、Weixin ingress/delivery/export bridge、initialization template与唯一owner私聊admission；credential provider只在可信Plugin内存。ordinary出站沿现 `_ORDINARY_SEND` 的同adapter/同conversation上下文Seam补实际固定Weixin transport，账号与会话必须来自当前binding，离开该上下文仍health-controlled-delivery-required。普通回复不进健康outbox/grant、不启动第二poller；健康/导出仍完整走126/130。

**生产coarse的来源与保守判定是本次真实composition输入。**使用本项目release-owned、版本/hash固定且有实际编辑来源的确定性当前消息规则，通过原CoarseMessageRouter的classifier Seam装配；不加载fixture lambda，不调用任何模型/ordinary Agent或历史session来分类。先判健康命令/记录、症状/诊断/资料/用药/提醒等健康或混合信号；有此信号始终health，无法确定/解析失败始终uncertain。只有全文符合明确非健康规则的事件才ordinary；未识别绝不默认为ordinary。固定普通问候与明确非健康聊天/工具请求须分别有实际例子证明，不能从一个“你好”绿灯外推普通功能完整可用。规则无法证明某输入为非健康时宁可留在受管链，不把它发到worker。此为粗分，不是疾病/危险识别器，不扩130的领域/模型schema。

有限技术语法只有两种：G11连接测试action的固定前缀加固定长度hex challenge，以及第11节ND12反馈的固定前缀、独立challenge与明确固定反馈选择。两者**全文无自由正文/额外token**，可被确定为无健康内容；混合/健康/uncertain不能借技术capability走该规则。当前challenge/授权/重投是否有效仍由各自gate的同一有限handler独立核对，coarse的ordinary结论本身不生成canary或产品反馈事实。

新disclosure-version只对应本次真实ND/host-only资产：原八topic与实际模板绑定，显示诊断未启用、功能实际边界、独立停止/暂停、JOJO固定预算和无保证、未知不重试、无联系人、受管删除/外部平台副本及旧整机快照限制。旧111版本仍精确匹配旧内容；新版本也须原matches、HMAC、先行持久challenge、实际披露交接、独立原生确认及current route重验，不开放任意executor文本或事后补通知替代同意。

无诊断scope时，原managed safety/status读取必须返回明确absence与staged/unavailable，可展示“诊断未启用”。不制造scope_id、BMI formula或审核事实去满足codec；ND状态可读不等于所有能力confirmed-ok。full scope存在时原严格字段、activation/currentness及已绿路径不变；ND authority在真实diagnosis.prepare仍拒绝。

## 6. 首次bootstrap、真实absence与不可回滚材料

仅真正新installation可bootstrap：专用Core身份拥有的私有目录、data key/writer master/execution master各32随机bytes及原0400/0700约束；init/daily attestor、status事实HMAC能力也必须真实稳定私有输入。三类设施及HMAC是秘密能力，不是业务/批准账本；不复制fixture常量，不把raw bytes放env/config/release/report/Git。普通worker不持有，Gateway不持Core key/master/HMAC。

用原writer `prepare_fence_ref`、真实新namespace与genesis operation形成公开fence；初始HeadSnapshot gen1、非terminal、site/installation/fence严格一致；同一真实空store的初始authority通过现seed接口锚定，再由129 `bootstrap` 的O_EXCL和原Service打开校验。genesis revision/transition须来自真实空状态/安装操作的规范事实，不抄测试fake hash或宣称已有健康记录。两SQLite并非跨库原子事务：中途崩溃只留下未开放的部分安装并失败关闭；恢复只核对同一首次操作与实际仍空的材料，绝不正常启动时补建丢失head/重签历史或重新创建密钥。任何既有、已推进、terminal或无法证明全新namespace都不能重bootstrap。

**唯一副本增量**仍在123的FilesystemManagedReplicaAdapter及原lifecycle binding：区分真实已配置对象与实际空的外部副本集合。允许首次无外部副本时用完整固定family覆盖声明加实际受管root/对象清单的absence核验；不需要也不允许先写一张“已purge”的receipt。固定受管root中有对象时必须枚举并绑定真实regular files/实际迁移artifact；无法归属、未声明文件、symlink/替换/权限漂移或清单不完整使其unavailable，不能把空清单当覆盖全机磁盘。以后新建受管副本只能沿原registry/Adapter，不能绕过该枚举。

现加密SQLite及130加密export blob属于同一store的原受管表集合；它们由原purge覆盖，不再复制成14文件。migration/backup/staging如实际产生则必须纳入原受管对象范围；只有实际清理后再原absence确认才能confirmed。删除仍原freeze→terminal→销钥→真实replica/purge→原最小terminal投影；空集合只表示实际无对象，不表示删除过不存在的副本。部分清理/unknown保留，不造completed。

`remains_unproven/unbound_real_providers`持续说明实际无法证明的VM快照、微信/CDN/主人已取副本；不编造远端删除。生产不能以“同一VM”推断没有其他受管备份，G10须核对实际数据出口及受管目录范围。受管备份也不得纳入程序回滚来恢复旧健康状态。

## 7. 原宿主启动、普通消息与唯一poller

default启动根使用release-owned shadow Hermes运行树：pinned commit、必须patch、实际用户dirty差异各有hash证明，全局四个用户dirty文件保留，不reset。加载时验证同release/Python closure/实际shadow/endpoint/current head/实例无值binding；使用pinned公开 `get_plugin_manager()/discover_plugins()`，取得原registry条目和原process-local arm Seam，在真实production host/ACL/currentness验证后arm，再调用原 `load_gateway_config_for_runner()/start_gateway(config)`。不伪造process capability、不持久化arm对象，不以验证fixture临时runner充正式启动。

HostReleaseContract现有synthetic credential observation不接受被改label的生产结果；生产入口须使用同验证Module内明确的真实无值观察形状，并保留旧synthetic合同不降格。生产当前性不能只凭JSON active:true或is-active。Plugin/registry只有health_weixin一个入口，原native Weixin不同时poll；普通chat同样由该单一poller→原ordinary handler→第8节worker→原ordinary出站Seam，不能另起native Weixin补普通回复。

R27已绿行为是兼容底线：preinit普通消息走原live wrapper/ordinary handler一次；preinit健康仍initialization-required、无健康source/model/send/facts；/health-init和独立confirm照旧；enabled后held/unknown与大record固定一次续接原样保留。不得在生产factory的fallback中重新导回native健康入口或把ordinary健康数据交给普通worker。

## 8. 根已选定的OS隔离路线及可观察结果

root已根据既定隔离不变量选定此一技术路线；不是新的风险接受，也不再候选Docker/bwrap/只sandbox terminal。生产账户/有效unit/实际Hermes与Core仍须真实门证明，当前default尚未改变。

| 角色 | 生产职责和可见能力 | 必须拒绝 |
| --- | --- | --- |
| default Gateway：原root用户unit | 唯一I/O+可信health Plugin；持实际Weixin及健康首跳provider能力，使用原CorePort、普通turn强制原proxy | caps全部drop、NNP；隐藏Core密钥/SQLite/head/HMAC/私有目录；不构造本地AIAgent，不执行普通Agent工具。root UID不是绕过隔离的理由。 |
| Core：新专用非root身份 | 原ProductionCoreService/HostSQLiteCurrentHead/私有设施/三个CorePort kinds；与Gateway有限plugin group共享socket | 无JOJO/Weixin/Hermes credential env、无AF_INET；不可成为网络sender/Agent。 |
| ordinary worker：另一专用非root身份 | 独立ordinary工作区、普通模型配置及必要provider token，整个AIAgent及全部子进程树在此身份；pinned APIServerAdapter原session/runtime | 无health Plugin、Core目录/密钥/DB/head/socket group/route、Weixin或health/HMAC/vault能力；任何terminal/MCP/browser/plugin子进程也不能提升回Gateway身份。 |

公开上游lifecycle已有一次真实隔离证明（非mock runtime）：`/tmp/dmit-connection-audit/ticket128-public-api-worker-characterization.sh/.log`在实际Hermes3.11 venv、disposable root用户unit内以低UID/caps0/NNP/ProtectHome/ProtectSystem、独立测试HOME构造standalone APIServerAdapter，`gateway_runner=None`；connect→/health200→无key/api/sessions401→有key200→disconnect成立，0真实model POST、0微信poller，临时unit/目录已清理，未改default。它证明可复用公开lifecycle，不证明生产专用账户、普通chat actual-model或最终factory已通过。

worker仅有一个有界launcher：调用pinned APIServerAdapter的公开connect/disconnect、signal与原session；不复制AIAgent/RPC/ordinary ledger，不启动Gateway/微信poller。proxy复用原 `/v1/chat/completions` 及必要API key，不是health首跳；只听已限定loopback，真实API自身的其他surface/认证与有效工具集合须在目标核对，不能把公开constructor等同只暴露chat。worker需要的ordinary provider能力只授其自身用途；不能把额外health或Weixin秘密顺带复制进去。

由于pinned proxy只覆盖主turn，required shadow patch在**relay-only已绑定启动模式**须拒绝本进程构造任何AIAgent，包括自动/手动compress、background、cron等，异常不本地fallback；正常turn强制原proxy。关闭本地session自动压缩；固定relay命令只允许已证明安全的native操作或明确拒绝，至少/background、/compress、/update、quickexec及任意plugin命令不可在Gateway root执行。健康原生命令仍由既有Adapter先消费。普通对话和工具经worker运行；微信直接root维护命令不暴露。guard保证可信Gateway不启动Agent，真正普通Agent隔离由低UID及OS权限承担，不能只凭配置开关宣布安全。

具体身份名/路径、unit/drop-in和私有helper布局可逆，但须可安装：Core/runtime/secret路径不能依赖nonroot无法穿越的 `/root`0700祖先；socket单独可遍历受限目录。现123要求socket owner=Core euid、group=其egid、mode0660，socket_parent可0750但不可group-write；可由有限plugin group提供Gateway准入，ordinary无该group。秘密仍Core0700/0400，Gateway无读权且路径隐藏；不用放宽原121身份/pin规则换取共享。

G10真实证明必须涵盖：三角色有效UID/GID/caps/NNP、ordinary子进程实际执行身份和工作区、普通文件写/工具正向可用、ordinary读/连接健康路径失败、Gateway读Core私有资源失败但合法CorePort成功、Core凭据env无值absence且AF_INET失败；旧head/key身份/peer/lease/文件替换拒绝保持。也要真实证明所有root本地Agent/exec触发面被阻断、ordinary主turn无fallback且健康消息未进入worker。不能仅is-active、0400、allowed_peer_uid=0或disposable probe字符串充证。

复杂度增量明确为两个专用OS身份、一个独立ordinary工作区/worker unit与其proxy配置、原Gateway drop-in、Core unit及有限shadow guard，均纳入第9节可回滚资源。删除worker/OS分离会使普通工具重新共享健康capability；删除relay guard则本地AIAgent绕过proxy；二者均有实际触发链，故保留。另建健康Agent、第二poller、第二RPC实现/业务库或再套通用sandbox框架不减少当前差额，删除。

## 9. 固定default安装与rollback事务边界

**固定公开setup输入。** 无参 `DefaultAcceptanceGateExecutor` 只从 `/root/.hermes/.ticket128-deployment-binding.json` 读取root-owned0600、regular/nonlink的非秘密操作binding；固定default profile/home/service不由该文件改写。它只选择已经实算验证的current distribution/runtime/shadow及同run/scope/H/D，不能以JSON passed/active字段产生权威。一个薄 `tools/ticket128_deploy.py prepare` 接当前release/run/scope及有限非秘密目标事实，验证fixeddefault/current内容并写该binding及原permit设施中的具体技术授权；**不安装、不provision健康key/attestor/head、不创建健康权威或声称角色已建成**。`run`仍调用原AcceptanceRunContract→固定Executor，不提供跳gate方式。最少CLI为 `prepare --release <currentdir> --run-id <opaque> --run-scope non-diagnostic [--input <nonsecret typed facts>]`；raw只用于admission/route/budget及需实算的runtime/shadow定位，不含approved/current/read/feedback verdict、secret/token/body、任意command/import/callback。raw如直接请求另一profile/service，或其定位路径间接转向partner/profile外目标，须在业务读取/backup/provision前拒绝，不因文件自称default而放行。具体字段/路径布局与内部helper可逆，测试从真实准备输出/原公开Interface取得必要定位；本地target操作输出可含非secret的计划binding/角色定位与run_context，不能把尚未provision的UID当观测事实，也不将路径/配置值送119collector/report。loader的live依赖输入与原123 exact service-binding分开，不为测试添加字段/alternate target/test-mode。

permit继续原120 root-private文件/当前核验/一次消费边界，只增加本票固定scope/gate和H/D绑定所需有限字段；操作binding本身不是批准、业务真相或第二审批DB。同119最小技术receipt工件继续是唯一执行恢复事实。独立测试可经既有外部filesystem/service/HTTP Seam把default逻辑路径隔离映射到自有namespace；这种物理隔离不是生产可选target。

真实执行只经同119 target-local GateExecutor；120原staged public路径与verifier保持，不能把current release直接送staged validator或改state字段绕过。G10固定current/live Adapter复用原backup/stage/install/service/restore Seam，扩展的资源集合在permit消耗前以存在/不存在、owner/mode、原字节/树digest记录到同release-bound私有backup。不得由caller给任意path/command/target。root用户systemctl执行须有真实XDG/DBus上下文；Core/worker有效unit归属与依赖明确，不混淆system和user scope。

| 资源 | 安装与回滚边界 |
| --- | --- |
| release/shadow/plugin/metadata | 固定版本内容寻址、required patch及dirty绑定；失败恢复原指向/plugin/metadata，保留全局用户dirty成果。 |
| default config | 只改plugins allowlist、health_weixin入口、native禁用、proxy/relay及必要非secret引用；rollback精确恢复本次改的原字节/权限，不恢复整个profile/Session。 |
| unit/drop-ins/enable状态 | 记录default Gateway及新增Core/worker的原存在状态、ExecStart/依赖与enable；失败先停新入口/worker/Core，恢复、daemon-reload；**恢复目标先满足下述隔离安全前提**才重新启动default并最小验证普通chat真实可用。 |
| 专用用户/目录/私有binding | 可逆provision应拒绝重名错身份；没有业务事实且确证为本次新建时可移除纯部署材料。已经承载健康事实的namespace/keys/head不得因rollback删除或回到旧字节。 |
| 健康state/head/key/fence/consent/outbox/cursor | **从不被安装backup覆盖恢复**。一旦真实初始化/业务推进，失败只能停健康入口、保留原权威并按其recovery；不回滚旧DB/head/key或整机快照。 |
| 外部模型/Weixin/联系人/已下载附件 | 不可撤回或假装未发生；unknown保持原终态/执行key，不以重新部署、新run或restore自动重做。 |

**回滚的既有隔离安全前提优先于普通可用。** 当前首次安装前default实际是root local工具/full capabilities/无隔离；一旦已产生真实健康状态，精确恢复并启动该旧unit/config会重新使普通root Agent可读保留的key/DB/socket，因此“健康材料不回滚”本身不足。任何rollback启动之前必须核验恢复目标仍满足第8节普通Agent与健康私有资料隔离；不能为了恢复聊天而启动已知不安全旧基线。首次G10失败只有在严格证明本次全新namespace仍genesis、零健康业务且零在途/未知效果时，才可按原规则安全清理本次未用私有材料后恢复原default，且保留已知技术执行证据；不能把此条件硬编码成测试特例。已经承载健康状态时，只能恢复同原program backup中**已证安全的普通隔离基线**，不恢复health DB/head/key；若没有这样的可证安全基线，则保持入口停止，健康材料原样保留，rollback明确cannot-confirm并交同权威recovery/继续修复，零旧高权限Agent启动、不得报completed。后续正常升级的安全backup仍有正向恢复路径；首装ND12后故障不得偷换成自动恢复旧root Agent。这不新增第二rollback状态/普通fallback协议/daemon，也不声称降低可用性已获新风险接受。

Core/writer/effect session资源生命周期沿950已修复的显式close/ExitStack/drain，不再另建所有权器；排空超时不可提早释放仍活动Core使用的key/vault。startup任何依赖失败不留可收健康请求的socket；Gateway co-stop/失证不fallback。rollback失败/cannot-confirm必须如实记录影响和下一步，不能只因旧unit active标成功。模型/渠道恢复检查同样须本gate实际授权与无正文证据。

## 10. G11：初始化前固定技术canary及真实因果

顺序不可改：G10真实通过 → 精确G11授权 → 固定非诊断合成模型与主人自身Weixin canary真实终态/独立行动 → G11通过 → ND12。不能用未来初始化成功倒推G11；原Core的preinit guard不增加通用例外。

G11 target-local Adapter是119已有GateExecutor Seam的实际实现，不是新健康业务入口。它先核验本会话授权具象化的本gate/release/run/target/scope/expiry/currentness，固定request只含明确连接测试、无主人/诊断资料，复用125 ProductionModelAdapter/131预算和原单次raw终态校验；不调用ordinary Agent，不伪造Core grant，不将其结果写成健康model fact。Weixin只向当前获准自身路线发送有限连接测试，不能调用初始化披露sender改名、制造owner-outbox authorization或发送联系人。

已选定的有限新增Interface是同一可信Plugin的固定canary发送入口，以及同一个Ingress poller在**Core已确认ordinary以后**的技术action接入点。二者只允许当前G11 capability、固定测试内容和已绑定账户/owner，无任意收件人/正文/命令/第二poller。发送使用同pinned协议/credentials，但权限来自本G11技术授权，不伪装126健康authorization；ordinary出站仍其独立上下文。

真实action处理严格沿当前公开链，再补一个最小技术receipt：

1. 原poller取得native消息并按原_headers/preflight验证账户、唯一私聊/owner、原生身份与当前Core；body只按原边界materialize。第5节精确无自由正文技术语法才是候选，健康/混合/uncertain照原受管链。
2. 原 `receive-weixin` → `live_entry_receive_weixin` coarse wrapper必须先返回 **accepted/ordinary-hermes-route且同source causal ID**；Core unavailable/非ordinary/错source时不得由技术handler代批。当前wrapper没有持久技术receipt，这一事实不隐瞒；也不增加Core的preconsent健康例外。
3. Adapter在调用 `_ordinary`/普通Agent之前，仅对精确技术候选进入固定handler。handler验证本gate/target/release/run/scope当前capability、已实际发送的challenge及后续独立native event的message ID、时间、账户/会话、原生重投关系；同会话/任意消息不算证明。未知挑战、额外正文、过期/错批准均不生成receipt，不静默交ordinary Agent造成另一次模型调用。
4. 验证成功先持久同119 execution-key的最小、无健康正文技术action receipt，再向原_process交回普通已处理结果 `(None, True)`，由**原poll_once**决定ACK；handler/observer绝不直接移动cursor。混批其他health sources仍须全部Core cursor directives/已提交业务/handoff满足，任一失败整批不ACK；技术receipt或ACK结果不能覆盖它们。
5. receipt/回交/ACK不确定时保持原执行事实并停止，不重发模型或canary。真实native精确重投只回查同receipt、校验原Core admission并再次沿原poller推进，零新model/send；不制造健康source receipt，不把技术action写成初始化同意或主人产品反馈。未知挑战不授任意ordinary旁路。

一次G11 execution key绑定一个随机challenge；先持久原最小attempt边界再调用，记录provider实际accepted/rejected/unknown。上述后续独立事件只证明有限canary行为，不能冒用/health-init或/health-init-confirm，也不形成ND acceptance。canary纯技术正文不保存为健康资料；目标私有技术证据仅保留证明因果所需的最小native关联，collector只取得opaque refs，不能收到联系人/owner标识、body或完整平台envelope。

provider只有accepted不能宣称delivered/read。精确主人回应若能证明其已见到并操作该canary，delivered与read_or_action分别保存**可解释的不同事实**及其来源关系，并注明来自独立行动推断，不伪装provider送达/已读事件；只是改同一字符串前缀不构成不同证据，来源不足则cannot-confirm。原119八stage keys齐全，但未发生的unknown/correction及其他非适用值为None，只有实际非None refs不得重复；不额外制造纠正或未知外发来填八项。accepted存在而delivered/read_or_action任缺，仍cannot-confirm。

119 report终态不可变。target executor可在有界等待真实action期间持有原gate；停止/超时/失联形成cannot-confirm并阻断ND12。报告未形成前按同execution key回查已知终态；unknown不换run/key重发。必要attempt/terminal/action关联和原poller处理事实只归**同119执行工件**，不另建审批DB、event bus、健康ledger或可编辑pending报告。上述是已选有限边界，当前尚未实现；独立门必须证明单次发送、真native因果、先Coreordinary承认/receipt后原cursor、混批/重投/unknown无旁路，不能拿本设计文字当通过。

## 11. ND12与原生主人事实

G11真实通过后才展示本次ND披露并开始真实初始化。主人必须实际从获准Weixin发送 `/health-init`，收到当前新版本完整披露，再用另一个native event发 `/health-init-confirm workflow disclosure`；原Core继续校验先后、签名、route、当前head/fence，prepare/commit/finalize并读回enabled；经原outbox交接显示“健康管家已初始化；诊断未启用”及131限制。工程部署授权、脚本、已读或按钮模拟不能替代这两条主人消息。

主人序列使用同release/target/scope与实际已启用配置：普通完整记录→证据/画像读回→固定治理问答与范围外诊断拒绝→当前当地日复盘/明确单次提醒及取消→暂停/恢复主动与停止/恢复记录相互独立→查看/更正/完整JSON附件导出→失败/unknown真实边界→最低帮助/实际已审阅安全规则。失败/unknown按实际发生者核验；正向序列可用真实known-failed后恢复的事实，不为凑序列制造未知外发，尚未解决的unknown仍阻断验收，不能伪造resolve或重试绕过；单次/冻结/重投的unknown反例由V06及相应负向观察证明。删除/迁移仅在该原权利批准内；G08 disposable destructive canary不是删除当前主人资料的许可。联系人无配置时验其不可用且零发送，不能宣称警报/纠正已验收；如后来确实配置，仍须独立当前批准、最小内容及真实接受/纠正来源。

ND12只消费原Core/outbox/rights/task/review/state facts和主人对已说明非诊断范围实际体验的“有用、清楚、可信”反馈。其唯一反馈来源明确为**同一获准Weixin的后续独立真实native owner event**，不由fixture、脚本或主任务Agent替主人填值：

- 本ND12 target-local executor先读回真实初始化/上述实际序列的原业务证据，证明当前head/fence/route，生成绑定release/target/run/non-diagnostic/序列digest的独立challenge；“sequence_complete=True”常量、G11回执或full五receipt均不足。
- 仅在当前ND12 permit内，同可信技术发送入口可一次发固定的非诊断范围说明/反馈challenge；无健康正文、不接受任意recipient/body，无联系人发送，不借G11许可或nonce。
- 主人实际回复全文固定的“验收反馈 <hex challenge> 有用 清楚 可信”；固定否定选择只记录未接受，拒绝/自由意见/缺项/过早消息都不能变成positive。必须为提示之后的独立真实native事件，不用outbound accepted或cursor推断其发生。
- enabled状态下先经原Core的ordinary分类与同causal accepted；再由第10节**同一个有限handler**在_ordinary/Agent前消费、验证本gate/序列绑定并持久同119 ND12 technical feedback receipt，最后交原poller ACK。零ordinary模型调用、零健康mutation，不新增Core读取/写入批准或preconsent例外；混批其他source仍原Core/handoff门，unknown及精确重投语义同第10节。

这是两种且仅两种技术事件（G11action、ND12feedback），共用同119技术receipt链且按各自gate隔离，不能跨用，不是通用dispatcher。技术测试、服务active、模型completed或Weixin accepted都不能生成主人反馈；拒绝、等待、超时或无法确认保持未passed。只记录无正文 `non-diagnostic-owner-usable` 里程碑，继续标明诊断staged；不新增产品第四态，不写full五receipt/active/G12或解决128。

## 12. 状态/Interface/成本的最小增量及预计文件范围

持久健康业务状态新增 **零套**：复用现state/head/source/effect/outbox/rights/lifecycle；无新健康DB、owner验收库、配置DAG或approval ledger。新增是同119 report的固定scope/ND无正文结论、必要的同run/execution-key技术attempt/终态/action绑定、实际release内容与版本、目标private bootstrap/bindings和release-bound运维backup。后者均不授权健康业务或恢复旧权威。HMAC/OS账户/worker配置是必要设施，不叫医学/主人批准。

新增行为Interface只限：同run的两scope选择；固定目标GateExecutor生产Adapter；固定typed live factory及Core/Gateway/worker三个有限进程入口；现Publisher固定ND资源输入；同Ingress的G11action/ND12feedback两种有限技术事件及ordinary发送Seam；同原replica Adapter的真实absence输入/核验。原CorePort仍三kind、64KiB，130 bytes/chunks/最长300秒transient及大record有限继续不改；无需通用RPC/dispatcher或新的健康能力注册表。

最少两个新的具名公开入口固定为：`load_default_live_runtime(release_root, binding) -> LiveHealthRuntime`（原Service CLI消费固定typed ND依赖；Core侧不读网络凭据），以及无参固定default的 `DefaultAcceptanceGateExecutor().execute(request) -> dict`（119 strict GateObservation wire）。后者不是120的同名概念值对象/其staged wire，AcceptanceRunContract当前直接要求plain dict；不新增observation class或改变旧120构造/路径。Gateway/worker launcher由实际unit、原public lifecycle和最高消息入口观察，不冻结额外private helper名；Publisher固定ND输入的内部参数名/codec保持可逆。

| 预计实施位置 | 仅本票差额 |
| --- | --- |
| `acceptance_run.py`与原验收薄入口 | 固定scope/ND07/ND12、严格report/replay/current approval绑定、旧full兼容；fixture CLI不改成假production。 |
| `release_deployment.py`、`tools/ticket120_release.py`及一个固定default执行薄入口 | 同Publisher真实资源/current闭包；同default operations有限current安装、完整rollback、逐gate授权/观察。 |
| 一个固定production composition文件、原`production_core_service.py` CLI/renderer | typed live依赖、Core/worker固定启动/close、首次host bootstrap、真实replica absence；不重写Service/Core状态机。 |
| `initialization.py`、`safety_diagnosis.py`及Core相关投影的局部Seam | 新ND披露版本仍严格匹配；诊断scope实际absence/status可读；旧full不放宽。 |
| `host_contract.py`/`hermes_host.py`、required pinned shadow patch | production无值host/credential验证、同进程arm/relay-only、禁本地Agent/exec旁路、co-stop；保留旧synthetic合同。 |
| `live_weixin.py`/`live_delivery.py`/`weixin_transport.py`原Adapter | 真实ordinary出站、固定G11 canary/action与ND12 feedback/native观察；健康发送/正文/授权/unknown/ACK仍原126/130。 |
| 固定项目自有资源目录 | 七Skill、治理claims/template、最低帮助、实际审阅规则、ND披露及真实来源/编辑记录；无owner秘密/正文。 |

文件划分、helper、内部codec和测试组织在独立冻结后仍可逆；本表不是授权现在编码。若必须增加第二状态权威、任意sender/脚本/门或改已接受风险，带实际因果返回root，不借部署理由扩框架。

## 13. 批准、人类事实与冻结/执行停止点

用户已给补完default项目/DMIT部署的工程授权，并明确接受host-only整机快照限制、JOJO ND限制；不再重问路线。执行者在精确release/target/run/gate/scope/步骤准备好后，把这些**真实既有会话授权**具象化为原目标私有、限期、一次、可核验permit；来源如实，不虚构主人曾为未来digest签字。120消费机制仍限本次动作，不能跨gate借用；collector拿字符串不代表验证了批准。

仍只能等待真正来源的事实：原生主人初始化/独立确认及其时区/基础偏好；canary实际独立行动；ND范围体验反馈；联系人真实身份/用途/方法/当前批准及接受/纠正；root对固定非医学求助规则的相称实际编辑审阅；127医学权利/专业审核、full容量依据。没有的项保持缺失/不可用，不填approved/已读/active。纯治理/固定非医学求助由root实际编辑审阅即可作为该有限用途来源，不能与BMI/医学专业审核混淆。ND12等人时不把不可变report事后改pass；unknown也不通过新run重做。

编码前必须完成同一checkpoint的：本唯一设计收敛、独立verifier-owned合同/有限现实错误门、真实当前红/绿characterization、fresh Spec与Standards pre。上述范围/边界已选择；当前仍待**实施和独立验证**：真实ND资源与编辑引用、首次空副本/产生真实artifact后的原Adapter闭环、原Gateway bootstrap/arm生产证明、ordinary出站及全进程隔离、G11/ND12的单次执行/原生因果持久事实。原语存在、草稿文案、fixture资源或本稿表格均不等于该门通过。

现场容量输入为 `/tmp/dmit-connection-audit/ticket128-resource-capacity-readonly.log`：1 logical CPU、2GB RAM（读取时available约1.3GB）、1GB swap、opt可用约535MB。原closed eff正式runtime+pinned约450MB可在root按无活动/manifest守卫清理并保留全部证据后回收；不能为省空间删证据、牺牲闭包或引新云。生产最多上述三个角色进程，builder/CPU重套件顺序执行；实际内存/启动/排空仍须验证，原语probe不替代持续运行证据。

实施后在同一clean source/release/Python closure上完成必要旧119full七门与118/120—126/129—131受影响回归、独立新增有限门、全量/真实root边界和fresh双post；然后才按原scope逐层执行真实G01—G09→可回滚G10→最小G11→原生ND12。每个实际不可逆点分别是：授权消费/安装切换；模型POST；Weixin/API或CDN发送；主人原生确认形成enabled；真正资料更正/导出/销钥/transfer；原规则继续决定attempt/accepted/unknown/terminal，程序backup不反转它们。

## 14. 输入来源与单一权威

已读取仓库AGENTS、architecture-governance、issue-tracker、CONTEXT/ADR0022—0024、128以及119—123/124/125/126/129/130/131唯一设计与相应当前接口。输入还包括root提供的 `/tmp/ticket128-minimal-implementation-inputs.md`、`g11-preinit-causality-inputs.md`、`nd-content-draft.md`、`nd-content-editorial-review.md`、`credential-containment-inputs.md`、`existing-agent-isolation-inputs.md` 、独立characterization、公开API worker lifecycle与现场无值原语/资源日志。它们是本稿的可定位调查/编辑来源，不是第二设计、测试合同、批准或生产验收。当前临时输入无新执行权限，最终真实内容与事实应归到同一128产物链；128票只引用本文件，Map/其他票/旧冻结文件均未改。
