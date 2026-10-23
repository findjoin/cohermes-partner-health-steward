# Ticket 128 独立验证合同候选

状态：**冻结候选，尚待同 checkpoint 的 fresh Spec/Standards pre；不表示编码获准或生产 gate passed**。独立 verification authority 独占本文件、`tests/test_ticket128_default_deployment.py` 与 `tests/fixtures/ticket128_{default_deployment_inputs.json,namespace_runner.py}`。产品基线 `b5c73f5b681858568d3428aa18c2052514e57330`（130 产品 `f21e8ad43bc92954da0a0ed5322cf421e48d0828`）；唯一设计为 `128-default-nondiagnostic-deployment-design.md`，当前候选 SHA-256 `c0d942c89aec085e8837ebd2d942c78eb28d2128542486e4d630f2689a2976e2`。实施者不得改本合同、verifier-owned 测试、旧119测试或旧冻结文件；认为门错则返回同一冻结阶段，由 verifier 修订后形成新 checkpoint。

## 权威与观察面

本合同只承接128既定验收和唯一增量设计，不新增业务状态/账本、架构、任意 gate、任意 sender/command、替代 provider 或审批来源。健康权威仍为原 Core/认证加密 SQLite/129 head；编排仍为 `AcceptanceRunContract.run` 的同 report/同 GateExecutor Seam。report只含opaque事实，不能含身份、正文、秘密、完整配置、绝对私有路径或可逆摘要。

新增具名公开行为仅两个：`load_default_live_runtime(release_root,binding) -> LiveHealthRuntime`；无参 `DefaultAcceptanceGateExecutor().execute(request) -> dict`，后者返回119 strict observation wire，不能复用120 staged value object/schema。现Publisher可接显式固定ND资源输入、原Service CLI与Gateway/worker进程入口可补有限装配；内部参数名、codec、helper、文件/测试组织均可逆，不因测试偏好成为架构约束。生产无参executor只能定位固定default的当前私有操作输入，不能接测试mode/任意目标/回调；逻辑target始终default。

最高观察面为：原Publisher build/current与真实内容闭包；新factory→原Service start/close→真实三种AF_UNIX RPC；原Plugin初始化/status/rights能力；原Head/HostPrivate与replica lifecycle；原pinned discover/start_gateway/registry与APIworker lifecycle；原Weixin Adapter connect/poll_once/send/disconnect及raw HTTP边界；实际unit与进程/子进程的OS行为。测试不用私有handler/codec/缓存/SQL布局作为主要断言，也不fake自有Core、Publisher、model/governed runtime或loader来填绿。

## 既有绿灯与已复现差额

独立只读 characterization 见 `/tmp/ticket128-characterization-{summary.md,public-seams.py,public-seams.log,results.json}`：本机Python3.12.3未伪装，网络socket/DNS被audit hook拒绝。

- 原119七门 **7 passed/0 skipped/0 errors**；固定顺序/首非passed停止、摘要/深拷贝、同run零执行replay/unknown、原五receipt、G08 no-go、逐gate批准、fixture诚实声明仍绿。原测试SHA-256 `978069af0dec6731111c49c9804c49982a96026e628ad60a413deb058d261642`。
- 原111披露先行持久、错误asset/伪proof拒绝、executor失败不初始化、无联系人仍可初始化四项原测试全绿。
- 真实HealthCore接纳 `diagnostic_scope_bundle=None` 且probe healthy，但最高Plugin managed scope与business status均报 `invalid diagnostic scope bundle`；存在完整合法scope时仍可读staged/activation-ready且非active。
- 旧v1及任意新version下，VM旧快照、JOJO无共同上下文、BMI未启用三类单notice替换都可构造content，却matches=False；原Plugin披露报 `health-init-execution-failed` 并保持uninitialized。旧版本严格性是绿灯，不是应移除的限制。
- 原replica Adapter不接受真实首次全空集合；无真实purge receipt时失败，不能用14空/假内容文件规避。

## 七个独立 family

门数不是充分性证明。每组以杀死独立现实错误的最少代表例展开；不做字段/平台/十二gate位置的笛卡尔积，不为ND重复119全部七门。

| 门 | 本票验收与必须杀死的现实错误 | 最高可观察结果 |
| --- | --- | --- |
| 128-V01 固定scope/报告/identity | 文档跳G07、caller改序、跨scope/target/run借report、借G12批准给ND12、unknown再次执行 | 原119七门单独保持绿；旧缺scope合法full输入/report/摘要/replay字节兼容。ND恰为G01–G06→ND07→G08–G11→ND12，首非passed精确block后继；`run_scope` 与 `distribution_digest` 成对必需，原 `release_digest` 保留H，D为同current distribution；prepare/request/report/replay/实际逐gate批准同绑H/D/target/run/scope，current实际重算H/D与嵌入关系；同H不同D不可借permit/report。scope绑定execution；同run有效replay零调用，错误identity失败关闭。合成all-pass仍fixture/staged，不生真实technical/deployment/product/active。 |
| 128-V02 同Publisher/真实factory/披露/status | staged/test资产伪装当前；资源hash漂移仍启动；任意executor文本替代同意；scope缺席崩溃或为补codec虚构BMI | 同Publisher显式ND发布→原current successor→新loader→Service→RPC/原生初始化；实际七asset、claims/template/minimum-help/source/review匹配；无KnowledgeRelease/诊断scope如实absence。一项实际closure/content漂移阻止live/arm。新固定版本可披露/签名/确认，旧v1仍精确；篡notice/版本/proof失败。无scope状态可读且明确staged/unavailable，非法full资源仍拒绝。生产coarse普通例真正走ordinary，健康/混合/uncertain preinit零worker/model。 |
| 128-V03 首次bootstrap/真实absence/lifecycle | 把丢失head/key当全新装、重签历史；先造假purge事实/假副本文件掩盖真实对象 | 真实新namespace经生产bootstrap形成同一gen1 authority、原随机稳定私有能力及严格owner/mode；restart不重建。gen1已有head却缺一个私有能力、已有健康却缺head两种代表性残缺均失败关闭，不重bootstrap或重签历史。真实空外部受管root可构造/枚举absence但不写假purge receipt；V07保留原Core加密SQLite导出blob及完整附件的真实正向验证，导出后外部root仍实际为空并可经原Adapter枚举，不为导出复制外部文件。未声明对象拒绝；既有真实外部files/purge及原删除终态/销钥/恢复由必跑旧123等回归保持，不对当前主人合成额外删除批准。 |
| 128-V04 固定default/完整程序回滚/安全恢复 | partner写入；只还plugins；程序backup回滚健康；旧root普通Agent重启后读到保留健康资料 | 非default在配置/备份/provision/service前拒绝。安全baseline代表例恢复本次config/plugin/metadata/unit/drop-in/enable/program资源原字节/权限/存在状态，并核普通功能。健康head/key/fence/consent/outbox/cursor不恢复/删除。已有健康而旧baseline不安全时拒启旧rootAgent、保留权威并rollback cannot-confirm；只有严格genesis/零健康/零在途或已证安全隔离baseline才可按设计恢复。 |
| 128-V05 真实三角色OS/relay | 只render看似隔离，普通子进程能读健康；root Gateway绕proxy构造Agent/exec；Core仍可联网/带credential | 实际发布入口/unit下三角色真实UID/GID/caps/NNP及import来源；worker ordinary turn/工具子进程正向写自身工作区，反向读健康资源/连CorePort均失败；Gateway读Core私有资料失败而合法CorePort成功；Core credential env absence且AF_INET失败。实际消息触发background/compress/update/quickexec/plugin等有限旁路拒绝；正常proxy成功、失败无本地fallback。单generic probe/静态unit/布尔isolation不可代替。 |
| 128-V06 G11单次终态/native因果/cursor | accepted冒充送达；换key重发unknown；任意消息当挑战回应；技术handler绕Core/抢ACK | 真实生产Adapter+原pinned/model raw边界固定请求；known exact replay零新POST/send，lost/unknown不通过新run/key重发。全文固定前缀+hex且当前G11挑战/批准匹配的后续独立native event，必须先原Core accepted/ordinary同causal再写同119receipt，最后原poll_once ACK；错误/额外正文/错source不receipt且不进ordinary模型。实际Core停止拒绝时gate保持未完成、无可用action结论、零额外效果/零ACK；不把允许的拒绝审计写入误判为成功receipt。实际执行工件目录与文件拒写时不ACK，恢复权限和入口后精确重投才形成持久receipt并交原poller ACK，模型/canary不重发；混批unresolved健康source继续阻ACK。八stage keys齐全，未发生值None，非None不得重用；accepted而delivery/read-action缺失仍cannot-confirm，行动推断不伪成provider receipt。 |
| 128-V07 ND12真实反馈/仅ND里程碑 | 技术绿灯冒主人同意/体验；G11action借作反馈；未完成序列即验收；强制provider失败而拒绝真实全成功序列；未resolved unknown仍验收；生产无定时接线被verifier主动wake掩盖；ND当full | 同一原V07父方法依次运行三个有限等价类：A真实全成功（failed0/unknown0）完成原native序列和独立ND12反馈；B保留真实known-failed后新source恢复的原全链和独立ND12反馈；C先完成同真实序列并取得当前ND12挑战，再由raw边界lost terminal产生实际持久unknown，合法反馈仍不ACK/不pass，无resolve/重试/新run绕过。复用同一业务序列helper，在同Core自然推进、不清空健康状态；每run独立native ID与当前source绑定，A首次独立init确认经当前新披露/HMAC/route/head/fence形成enabled，B/C的G11不得改变既有初始化。各序列均逐步运行记录/画像、发布claim问答、诊断拒绝；实际startup在空native poll下自然完成当前当地日review及真实到期单次提醒/原126投递/任务solved，随后真实安静观察零重复，不由verifier调用wake RPC或另建bridge代办；实际task_id取消、两种独立control、实际object_ref纠正与完整JSON附件导出、最低帮助/实际固定安全规则保持。不伪造clock、SQL、ready、receipt、grant或sequence_complete，不冻结私有timer实现或周期。失败如实缺席可验收；原V06单次/重投unknown断言不变，C是隔离负向观察，不是为真实主人凑序列制造未知外发。ND12独立批准/挑战绑定release/target/scope/已完成序列。固定全文 `验收反馈 <hex> 有用 清楚 可信` 经enabled Core ordinary同source后，同有限handler在Agent前写同119ND12receipt，原poller ACK；错挑战/缺项/拒绝/超时/额外正文不pass，不跑ordinary模型/新健康mutation。仅ND milestone、诊断staged、无full五receipt/active/product passed/闭128。无联系人必须unavailable/零发送。 |

## 外部fixture与真实现场事实分开

Decision family在真实119 Seam使用boundary fake，只测固定决策。其余隔离门使用实际产品代码/原Core和原网络Adapter，只在真实外部OS/service/raw HTTP/原生事件Seam以隔离Adapter控制已知、拒绝和unknown。不能用内置fakeHealthCore、fixture executor、人工重算manifest、14假managed files、私自取activation capability/arm、fixture布尔approved/feedback/OS结果代替所述链。

隔离自有namespace中的逻辑target仍default；允许映射到disposable backing，不新增产品alternate target/testmode/任意root参数。正式fixture只提供必要原始非秘密绑定与合成凭据/事件，不能提供一个“本门passed”结论让测试照抄。实际生产G10/G11/ND12由之后同128 run另证。真实模型/微信/真人同意、已读/行动和体验反馈不能由本自动门制造。fixture report永不晋升production，环境名不自证target-local。

正式执行由原 full `unittest discover` 的同一父进程计数。V02—V07 的每个原 testmethod 调用冻结 `ticket128_namespace_runner.py`，只允许六个原方法白名单；runner每次新建自有SYSTEM scope、PID/mount/net/cgroup/chroot、独立root-user manager/DBus与default backing，child用真实closure重跑同一个方法，父方法以实际child exit/stdout/stderr判定。不是拆分全量计数、skip或拼造汇总。每family从零开始，不复用key/head/program，也不使用宿主userbus/default/partner。

runner仅对本次owned代码copy归一公开读取权限，实际逐字节核原manifest；不放宽宿主原closure或健康key权限。测试从kernel mountinfo核 `/root/.hermes` 精确mount与本次物理backing，核actual manager PID同namespace及仅loopback；同FS bindmount不使用 `os.path.ismount` 的dev/ino假阴性。OS门对实际generated unit附固定verifier ExecStartPost与owned append输出，独立核实际MainPID/InvocationID/UID与kernel允许/拒绝；不依赖宿主journal标签。低UID公开读取用真实Core解释器/部署release/runtime路径，并核同正式closure字节。

R7在精确`dd0faba145a4378ed8c7b2e6920e186f9693eb14`实际V02中，原G01–G06→ND07→G08–G10均passed后，verifier把`/proc/<Core MainPID>/exe` resolve所得外层`owned-rootfs/.../runtime/bin/python3`文本当chroot内路径读取，518.694秒child以FileNotFoundError结束（非timeout，cleanuptrue），尚未执行该次loader观察；日志`/tmp/dmit-connection-audit/formal-dd0faba-128-r7-v02.log` SHA256 `b06b58d27bdbd91675537d594936162697677d7dfcb1df2af1dee720b4e59233`。此是验证器locator缺陷，不是产品解释器/loader缺陷。统一修正Core公开读取、三角色closure观察及同unit ExecStartPost/ordinary工具三个同因果使用点：只读打开实际proc-exe FD与已绑定、chroot可见的declared-runtime/bin/python3 FD，核regular file、同dev/ino、实际hash一致及原同正式sys.executable字节一致，核观察期间FD和路径仍指向同一对象；之后只执行已核为同一对象的声明路径。actual PID/status/UID/GID/caps/NNP/cmdline、Python basename、closure containment及真实同unit/kernel行为断言保持。proc显示文本只可作basename/诊断，不能据其宿主前缀裁剪、复制、fallback、跳过身份或直接exec proc/fd路径。后两使用点是源码同因果差额，尚无本轮V05实际失败或新修订通过声明；本修订不改runner/raw/设计/旧门、产品、预算或测试计数。

R8在精确`ce6d9cc708aa8d6340168e83e9241edf70836b4c`实际V02中已越过上述实际解释器与loader三断言，随后initialized→verifier FramePort在读reply header时失败：child524.229秒/1failure、cleanuptrue，非timeout；非空原child日志`/tmp/dmit-connection-audit/ticket128-r8-v02-original-child-stderr.log` 2570字节、SHA256 `1055bb220ff67f9cc2e89e1484bd3b33fd4d11533424ed204bb501ab722e5c1e`。最初提供的formal-v02.log为空，不作为此trace来源；父528.461秒只来自已有toolstream，不冒称已封存parentraw。原123协议以完整单帧后的client写端EOF界定请求；Core在trailing EOF前不得dispatch，原123迟到tail与never-half-close负向保持。verifier `_FramePort.request` 与内嵌 `_KERNEL_PROBE` 同样漏发EOF，现仅在两处sendall完整frame后、recv前各加`shutdown(SHUT_WR)`，与真实CorePortClient/生产RPC/原123合法client一致。不改产品framing、1秒服务端边界、65536限额、canonical/peer/response/角色断言或任何既有timeout，不改旧123故意无EOF负向，不增重试。内嵌client为同因果源码漏项，不冒称本轮V05已失败；本修订尚无实际新门通过声明。

R10精确`eb7a66cc99a724b267316e29a2550a2103c5f551`的V02在原12秒初始化无send观察处失败；保留日志的无正文trace与固定类别确认Adapter factory在BoundResponsesTransport构造时报`invalid Responses transport route`，合成binding的api_mode为`responses`、health_weixin平台未建成。证据`/tmp/dmit-connection-audit/ticket128-r10-route-reason-readonly.log` SHA256 `6ae8356869f35df4313d3a94b835c2aa49b2728e4a6486cdd095ae97da06e8e1`。原125/131/已闭130及当前生产transport均使用并严格要求`codex_responses`；唯一128design复用该契约，不要求产品接受别名。仅将test唯一合成健康route该字段修正为`codex_responses`，保持provider/base/route ID/model、所有其他test字节/断言/时限/计数与产品严格guard；不改design/raw/helper/旧冻结门，不新增诊断观测。R10红保留，新候选正式通过仍待实际执行。

自有chroot的普通OS前提包含仅本次mount/IPC namespace内的`/dev/shm` tmpfs：在chroot前创建，64 MiB上限、mode1777、nosuid/nodev/noexec，不绑定宿主`/dev/shm`。既有namespace-preconditions仅记录其实际kernel mount、mode与capacity，不形成产品gate verdict。原129 V02真实3.11配对probe已证：缺席时在原`ctx.Event()`→`SemLock`报FileNotFoundError（1error，0.033秒），挂载自有tmpfs后原测试1PASS/0fail/error/skip（0.043秒），9557份runtime字节均未改；日志`/tmp/dmit-connection-audit/ticket128-r5-original129-private-shm-probe.log` SHA256 `d9133bc9acdb83da2e558ca43f55130f868497bc1ae1dd3b5161e9c0ec34daf6`。这是已证的verifier OS前提修正，不是产品CAS缺陷或放宽旧129；本次新helper的完整门仍待实际执行。

自有chroot还须具备标准`/run/systemd/inaccessible/{dir,reg,fifo,sock,chr,blk}`六种mode000 mask节点（chr/blk均0:0），仅在本次owned root中创建，不绑定/复制宿主节点，不增`user0/inaccessible`，不改实际unit的InaccessiblePaths等隔离策略。namespace-preconditions只记录实际节点类型/权限，不形成产品gate verdict。独立OS配对probe在同一全新chroot、相同ordinary-shaped unit字节下，缺节点时启动为226/NAMESPACE、main及ExecStartPost正文未执行，原stderr明确缺少mask source `/run/systemd/inaccessible/dir`；仅创建六节点后main和ExecStartPost均实际成功，cleanup已确认。证据`/tmp/t128-mask-r2-evidence.json` SHA256 `ba04f2c9888c4d07595f33406a02ef871c7081cb0f03a8de8eb0a02ac0935c01`含12份named原始records及各自hash。R6原V07实际首失败是G10 ordinary226，未到ND12/自然trigger；这个普通OS前提已被配对证实，**不等于新helper或实际三角色G10通过**。

完整family与单个生产gate分别计时。V07在原同步G01—G10前置后，A/B/C各用新run原样重复前置，共四frontier；原V06有第二轮，bootstrap/rollback/G11家族最多四轮前置。R5原637项G02实际全PASS，G01→G02 receipt跨度344.464967832秒，至G04约400.114084037秒（均含准备/hash/工件，不冒称纯测试耗时）。因而第二轮尚未完成时用普通12秒等canary，及用480秒涵盖整个family，和源码可达的原样工作量不相容；此为源码加同一真实前置实证，**没有宣称实际发生timeout**。两处紧随`_run_background`的canary观察调用点仍采用1200秒frontier上限，线程提前结束立即传播原error或完整report；`_join_report`30秒、其余普通观察12秒不变。family child7200秒由四frontier各1200秒、三run各G11/ND12两个300秒原技术窗口及600秒fixture/序列余量组成；SYSTEM RuntimeMax7320秒、runner7350秒、父方法7410秒保持有限且为准备/清理留量。C仅用330秒观察原ND12自行终止，再原`_join_report`，不延长其300秒执行期限。原KillMode、cleanup和真实退出判定不变。生产local gate540秒、G11/ND12各300秒、V07到期后90秒与安静65秒均不变，不缓存前置、不跳gate或减少任何原测试/正负断言。R5首失败为原G04，R6为上述G10 OS前提；均未发生timeout，本修订不将旧结果冒称新门通过。

本轮V07补漏仅实现唯一design §11既有“失败/unknown按实际发生者核验；正向序列可用真实known-failed后恢复”的验收要求，不增产品范围。当前产品`_SEQUENCE_PROGRAM`无条件把当前ND12窗口的`known_failure`纳入`all(flags.values())`，合法provider全部成功时该项必为false；原V07只强制给出一次invalid候选，遮住了真实失败缺席的合法序列。这是源码因果反例，**尚无实际ND12 timeout或本轮新V07 red执行声明**；预算/长输入前置拒绝不生成合格known-failed报告，也不能让主人制造失联来凑项。保留原known-failed→恢复正向，并以A真实failed0/unknown0正向和C真实持久unknown负向覆盖相同公开边界。七个原父方法及全量计数不变；新候选必须实际全部展开/通过后才能作post/正式通过声明。

131预算的issued_at/expires_at参与完整budget与model-authority digest；V07在首次真实前置/初始化前建立一份三小时有效的合成fixture预算，A/B/C的prepare均传递同一wire，以覆盖7200秒family上限，避免观察中途变更已初始化的预算authority。route/owner-decision/65536字节与2048 tokens等固定预算语义不变；不重新确认初始化或绕过验证，不把合成决定冒充真实主人批准。其他family继续原默认预算输入。

唯一raw JSON是data-only：admission/raw消息和少量JSON pointer只定位当前public setup计划/真实私有能力，不提供判词、配置正文、批准、已读/反馈事实或任意命令。prepare允许固定default的 `--release/--run-id/--run-scope/--input`，输出有限非秘密planned/existing定位；这些定位要由真实kernel/字节/状态复核，不能当postchecked布尔。`execution_artifacts_root`只定位同119工件，不冻结其内部receipt codec。公开release/skill/rule路径允许可读；隔离断言只保护原host_private_paths、DB/head和真实init/daily/status HMAC，不能按字段拼写把所有path判为私密。

八stage不是八个必须发生的效果。unknown/correction没有发生须None，不为填字段生成纠正或未知外发。只有实际非None的不同事实ref才必须不同；独立回应推断送达/行动须保存真实因果和来源语义，不只是换前缀。

## 正式执行前提与反假绿

1. Linux实际Python3.11闭包，真实sys.executable及产品/固定shadow/worker imports与最终source/manifest相符；不改sys.version、不fake importlib、不拿本机3.12或历史runtime hash称正式通过。原123验证器/同Publisher attestation继续权威。
2. 冻结runner实际输入为 `TICKET123_RUNTIME_ROOT`、`TICKET118_PINNED_HERMES_SOURCE` 与同source-snapshot的verifier-root，正式来源在独立/opt closure中。runner `0235a2935af9174f220b7aa98e637a5a182adab8ec542635d5e38ec9e4983365` 的实际源码绑定+白名单child smoke已由root单列于 `/tmp/dmit-connection-audit/ticket128-operator-smoke-r1.log`：明确未冻结composite/nullcommit输入、真实3.11/source clone/private namespace/manager→原V02 child一项精确missing-public failure、0error/skip，内部case0，实际cleanup已确认。该smoke使用其记录的较早候选test hash，不冒称最终test内部通过。此前实际primitive r10通过（`/tmp/dmit-connection-audit/ticket128-namespace-primitive-probe-r10.log`）只证明namespace/私有manager/owned mount/仅lo/真实synthetic unit输出前提，不是产品门。自有隔离root namespace，无真实profile/凭据/健康资料/外部网络；测试创建的私有能力真正随机、原0400/0700与owner/peer检查不放宽。低UID代码/解释器/祖先必须实际可遍历/只读可执行，且Service声明root满足原123 euid/gid检查；fixture父目录缺x不是产品红。
3. OS门必须actualKernel允许/拒绝和ordinary工具子进程身份；可在隔离实际unit的同有效权限下附verifier探针，同时核实际MainPID、CorePort与实际public入口。不能把之前disposable通用原语probe或unit字符串当三角色生产实现已通过。
4. 缺任一个新的公开前提时，每组必须真实失败于缺失接口；不得skip、无条件fail、导入虚构模块、只断言常量。此时**7 prerequisite failures只证明expected-red；内部case尚未执行**。接口存在后七组必须展开；正式前提缺失也failure，不以skip掩盖。
5. 完成只接受七组全部实际展开/通过、0skip/0error，原119七门及受影响旧回归通过；测试数量本身不能支持足够/部署/医学/主人验收声明。任何真实差额未被本合同覆盖时，按architecture-governance返回verification权威，不由实施者改门或重开架构。

## 命令与证据

8fa6edc冻结轮仅修V07的生产自然触发覆盖缺口：原门主动调用`self.wake()`，因此只能证明130公开wake与126投递能力，未证明128的实际startup会自然调用它。该轮只读候选`a3695c42cf64db833b8cefc6a175e6e040833405` / tree `5216652c4bd5053c3fb1c0d33dd4644d2780d1a0`中，`LiveHealthWeixinAdapter.connect`只启动poll loop，`wake_current`没有生产caller，default startup/unit也未装配调度；原130明确系统timer安装归128，不重开130。该修订保留同一V07及其余序列/负向，只将未来当地分钟的真实提醒改为由实际startup在无额外输入下推进：到期后最多90秒观察真实发送、任务solved与当前日ledger，再安静观察65秒零重复。上述时间是有限测试观察预算，不规定生产timer结构/周期。当时只有源码定位与修订，**未将静态差额或旧R2结果称为该轮已复现红/正式通过**。正式red须在其精确clean checkpoint及实际声明3.11闭包运行原V07 namespace方法；若失败在更早前提，须记录实际首失败，不能冒称已运行到自然触发断言。该轮设计、raw/helper、旧冻结门与产品均未改变；后续helper的独立OS/时间前提修订以本合同前文为准。

本机characterization/预期红：`python3 -B -m unittest -v tests.test_ticket128_default_deployment`；缺接口阶段预期7fail/0skip/0error，**不能标内部case green**。原119：`python3 -B -m unittest -v tests.test_ticket119_integration`，当前7pass，重跑日志 `/tmp/ticket128-verification-candidate-old119.log`。新门日志 `/tmp/ticket128-verification-candidate-local-red.log` 实测7fail/0error/0skip，全部停在两新入口缺失；最终test内部case尚未执行；helper自身smoke仅证明固定入口/隔离/原方法结果传播与cleanup路径可达。编译使用不写repo bytecode的明确临时pycache/编译输出；`git diff --check`必须通过。

正式命令必须由实际声明closure的 `bin/python3 -I -B` 在同clean candidate上运行；runtime/pinned/isolated namespace的输入原件、源码树/冻结文件hash、实际测试log、OS探针和zero-network原始计数均保留同128证据。执行前冻结checkpoint还应记录本文件/唯一design/test blob与双轴pre；执行后同最终candidate重跑七组、旧119/118/120—126/129—131受影响回归、全量、必要真实root边界及fresh双post。自动门通过后才允许按设计真实逐层128run；stageA完成仍claimed，127审核不造。
