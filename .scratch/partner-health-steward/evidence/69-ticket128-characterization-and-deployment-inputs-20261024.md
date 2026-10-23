# Ticket128 characterization与真实部署隔离输入

2026-10-24。130已在root元数据提交 `b5c73f5b681858568d3428aa18c2052514e57330` 闭合并普通推送；产品基线仍精确f21e8ad，详[Evidence68](68-ticket130-final-execution-review-and-closure-20261024.md)。128现claimed，唯一设计为[128 default ND设计](../design/128-default-nondiagnostic-deployment-design.md)。本页只记录实际输入/工程选择，不是冻结、编码、G10/G11或主人验收通过；没有执行生产安装。

## 独立公开接口characterization

`/root/verification128` 以本机原Python3.12.3运行公开接口，明确仅characterization；不冒充实际3.11正式闭包。网络audit hook拒绝connect/bind/DNS，全部synthetic/内存/自有临时资源，无真实owner、secret或provider。

原119七门7 passed/0 error/0 skip，旧111四关键回归同绿；原full固定序、逐gate批准、摘要与深拷贝、原报告精确重放零执行以及fixture不冒充部署/产品通过均保留。独立反例：真实HealthCore允许诊断scope=None且probe healthy，原Plugin managed scope/status随后均报 `invalid diagnostic scope bundle`；旧v1和任意新version中替换VM/JOJO/BMI三种notice各自被matches及最高Plugin披露入口拒绝，仍uninitialized。故ND需要有限absence投影与严格新内容版本，不能伪造BMI包或关闭旧匹配。脚本、log、结构化结果及原119报告位于 `/tmp/ticket128-characterization-*`，summary说明重现命令和未改变的旧test hashes。

作者另在纯合成路径复现：原FilesystemManagedReplicaAdapter不能表达首次实际空的外部副本集合，缺purge receipt时拒绝。14空假文件或假purge receipt不是解决办法；唯一设计承接同Adapter的真实absence和后续受管对象闭环。此结果不是全机无副本证明。

## 现场无值基线与独立原语试验

只读目标：default root用户unit仍loaded/active/running；systemd249，setpriv/unshare/nsenter可用，Docker/bwrap/setfacl没有。当前无proxy或有效sandbox。目标脚本在私有边界内只提取少量配置布尔值；未向会话返回完整配置、秘密值、健康正文、联系人或运行DB。SSH凭据仅由既有memfd连接设施使用。容量为1逻辑CPU、约2GB RAM和1GB swap。

root只在自有 `/opt/t128-*` 临时目录与唯一随机名的transient用户unit进行合成试验，结束停止unit并删临时目录。v1/v2真实失败保留：前者私有父目录不能由低UID遍历且socket测试目录受umask影响，后者Core数字UID不存在触发217；它们不是产品绿灯，未改121/123保护来绕过。v3改正fixture前提后三个role全部执行成功：

- Gateway UID0、effective capabilities全零、NNP：普通自有文件写入成功，合法合成Core socket可连，合成Core私钥不能读。
- ordinary低UID、caps0、NNP：自有工作区写入成功，合成Core key/socket均不能访问。
- Core另一低UID、caps0、NNP：可读自己的合成key，AF_INET socket被OS拒，credential环境名称缺席。

这是systemd/OS能力证明，不是新生产账户/实际Core或G10；没有把daemon/nobody作为生产身份。源码和原始输出见下表。

另用actual pinned Hermes Python3.11 venv、独立低权限HOME和同类临时unit，直接调用原 `APIServerAdapter(PlatformConfig).connect()/disconnect()`：gateway_runner=None；本机health200、无key sessions401、有key200，全生命周期成功。未mock API、未构造AIAgent或请求真实模型，微信poller为零。它证明可复用现成ordinary执行Seam，不能宣称真实普通对话已经验收。

## 在既定HOW内部选择的必要技术装配

普通Agent整个进程树移到专用低UID工作区，复用原Gateway proxy与公开API Adapter；原default Gateway保留唯一I/O与可信health Plugin，caps0/NNP且隐藏Core私有资料；Core专用非root身份/有限共享socket group，空credential环境与无INET。没有第二健康Agent、第二微信poller、第二健康数据库或新RPC协议。

因为pinned proxy仅覆盖主turn，本地自动/手动压缩、background、quickexec及维护命令仍会运行在Gateway，必须在release-owned shadow中有限拒绝本地Agent构造和危险命令，正常turn强制原proxy。普通聊天/工具在其工作区；微信直接root服务器维护不再开放，维护继续通过已有SSH。此为满足Evidence36既定凭据隔离的必要可逆技术工作，不接受新的隔离降级、VM或JOJO风险；具体路径/unit/helper可逆。真正OS边界仍须正式128门及目标实际G10证明，不能只验配置字符串。

G11和ND12只需要同119技术工件的两个固定purpose：连接测试行动、ND主人体验反馈。先原Core将全文严格有限技术表达确认ordinary，才由本gate许可的handler核对挑战/native来源并持久无正文receipt，随后原poller ACK；不进入ordinary Agent、不伪造健康grant/同意，也不允许observer自行推进cursor。八stage keys中未发生unknown/correction保留None，只有非None refs不得重复。两个gate不得借批准/挑战/receipt，真实人类消息不能由fixture或工程授权代写。

同一actual venv下另在低UID/空环境/独立HOME中导入run_agent、terminal_tool、file_tools、mcp_tool和api_server，全部成功且来源位于固定实际Hermes树。audit hook拦截connect/bind/DNS，观察到一次socket.bind被拦截；没有模型构造/真实POST或Weixin poller。该试验不证明最终sealed闭包和完整Agent turn，只说明现有依赖可作为后续正常构建输入。日志 `/tmp/dmit-connection-audit/ticket128-ordinary-import-characterization.log`。

当前scope生产执行还须同时绑定原118 host digest与原120 distribution digest，并实算包内嵌关系；相同host但不同runtime attestation/distribution不能借报告或permit。固定default私有准备binding只作操作输入，不是业务/审批权威，详唯一设计；这些准备选择尚未成为代码或部署事实。

## 空间整理

为后继新闭包腾空间，root验证旧eff03ae formal副本无live进程/FD依赖、原closure及postcheck身份后，只清理其runtime与pinned Git重复副本；源码、独立verifier、完整manifest及所有执行日志保留。receipt `/tmp/dmit-connection-audit/prune-finished-formal-eff03ae.log`，保留manifest SHA256 `71206bb03cafc55d8f25b00790dd962fa29eb00a5c2ecc42dd890898b8a63ebc`，可用空间约988MB。精确最终f21正式副本及真实服务均未动。

## 独立部署测试环境的实际原语验证

root在DMIT实际systemd249上运行 `/tmp/ticket128_namespace_primitive_probe_v10.py`，只创建自有 `/opt/t128ns-probe-gn61xksh` 和随机**系统级**transient fixture unit `t128ns-probe-a0ef5c7ebb18`。其内部为独立PID/mount/network/cgroup namespace、owned chroot、空default HOME/账户/程序可写根、私有root用户manager/bus；公开系统二进制只读绑定，实际Hermes树被遮蔽。它不使用宿主root用户bus，不操作default/partner unit，也没有运行产品、模型、微信或主人动作。

r10实际exit0：真实UID0；私有manager PID29与控制器同mount namespace、区别于私有PID1；内核mountinfo精确证明 `/root/.hermes` 来源于本次owned backing；network仅lo且无default route；真正由该manager运行合成服务，systemd-run exit0且owned输出中精确marker完整行只出现一次。短transient结束已GC时InvocationID如实null，不据此伪造存活进程。后续产品三角色仍须实际MainPID/UID/权限与完整门，不能借此probe判G10通过。probe使用系统Python仅验证OS前提，不冒称产品Python3.11正式执行。

r1—r9失败原稿及本机 `/tmp/dmit-connection-audit/ticket128-namespace-primitive-probe-r*.log` 全保留：chroot根非mountpoint、私有bus未由manager启动、误套本机新版本Type=notify、同FS bind的ismount假阴性、短transient查询已GC及debug附加行的整文件相等假前提均被定位并修正；没有通过修改产品或放松隔离来变绿。r5只读现场vendor确认当前dbus.service默认simple，而非notify。最终冻结runner及V02—V07内部用例尚未执行，不能从这项基础能力通过推定产品或部署通过。

### 固定namespace runner的非冻结试跑

随后使用原f21 runtime的完整owned复制件和明确 `git_commit=null` / `UNFROZEN_COMPOSITE_OPERATOR_CHARACTERIZATION_ONLY` 的源码快照运行verifier候选helper（SHA256 `0235a2935af9174f220b7aa98e637a5a182adab8ec542635d5e38ec9e4983365`）。快照为f21原Git源码加当时三个候选test/raw/helper字节，不声称是最终冻结commit；archive SHA256 `3112eaa2e53e2af7b9ba05af4e0e12f8705df8d28b7ef4582de028ee9ea896d8`。试跑只选固定白名单V02，不接受任意命令。

真实Python3.11/source closure核对→fresh namespace/私有manager→原unittest method路径已可执行：实际1 test/1 failure/0 error/0 skip，失败精确为缺 `load_default_live_runtime` 与 `DefaultAcceptanceGateExecutor`，明确内部case执行0。helper报告 `original_method_executed=true`、`operator_cleanup_confirmed=true`；本次随机SYSTEM fixture unit `t128ns-family-e26a3e66afe1`结束。seed在最后重算原f21全部runtime文件及manifest，closure仍 `sha256:61db522c4106109c7e13505945290cb016f14b0972d6b754ddaea2dd5667434c` 且 `runtime_source_unchanged=true`。这证明helper自身真实expected-red与清理路径可达，**不是最终冻结测试内部通过、正式门通过、生产安装或真人验收**。

原始记录：本机 `/tmp/dmit-connection-audit/ticket128-operator-smoke-r1.log`；远端owned `/opt/t128-operator-smoke-c9u51wd2/logs` 与 `/opt/t128ns-family-vwwk61b0/data`。没有改动原正式f21副本或实际default服务。

### 最终候选字节与root独立本机characterization

独立verifier停止编辑后，root按 `/tmp/ticket128-verification-candidate-final-files.json` 逐项重算四文件SHA256和Git blob值，并独立原样运行最终候选：本机真实Python3.12.3，新七项均为上述两公开入口缺失的prerequisite failure，0error/skip、内部case0；旧119七项全部pass且原字节未变。仅collection发现808项、无执行全量之声明。记录 `/tmp/ticket128-root-precode-check.json` 及new/old119原始日志；这与之后实际Python3.11正式门分开。

试跑结束后root核完整7467文件原closure、同family cleanup已确认且无/proc活动cmdline/exe/cwd/FD引用，只删除owned smoke的runtime复制件，保留其源码、全部日志与完整manifest；原f21正式runtime、default和健康状态均未动。实际空间从677502976回升至900997120 bytes，receipt `/tmp/dmit-connection-audit/prune-finished-ticket128-operator-smoke.log`。这不是程序rollback或数据清理。

## 输入身份

| 本机可定位工件 | SHA256 |
| --- | --- |
| `/tmp/ticket128-characterization-public-seams.py` | `c214d89b3e5fe897ad9299e4e7152306a762dbe5f4cfb0aa6ea71d114e6a2733` |
| `/tmp/ticket128-characterization-public-seams.log` | `fd405ff3fef4a599d29a79271112d8261fb52c53007b0df16fdf94531042694c` |
| `/tmp/ticket128-characterization-results.json` | `0d03399f3e7693e92aad0b40017e482870b05d5c6c8b271ccc19542a2495854b` |
| `/tmp/dmit-connection-audit/ticket128-default-isolation-primitives-readonly.log` | `5079b52f079bf4415e39258ad760ca009412cf602b882606b048608df81f7d94` |
| `/tmp/dmit-connection-audit/ticket128-isolation-characterization-v3.sh` | `c4bad9f3b3e74d4ef744bc347ef69dad7b924c27e639057a102e81d51b915acf` |
| `/tmp/dmit-connection-audit/ticket128-isolation-characterization-v3.log` | `e0134e9b2bde5881d737740af04b80732edfee495365047472c72845ed7f9fb9` |
| `/tmp/dmit-connection-audit/ticket128-public-api-worker-characterization.sh` | `e02b50a7f08586ae7798aa535cb63af0ade7c4115300a15dd929c2eb4bc3bf6b` |
| `/tmp/dmit-connection-audit/ticket128-public-api-worker-characterization.log` | `7466e8d6f3bf4bd2c93a047064f8a038eed7014133201aa4ac6bbdf38248f9d8` |
| `/tmp/dmit-connection-audit/ticket128-ordinary-import-characterization.sh` | `50deaaff2ddafccf6a3ca482e8ce1ebc62cf7b922b404280faad99fef6ce8b94` |
| `/tmp/dmit-connection-audit/ticket128-ordinary-import-characterization.log` | `297af074d4d548852f317d32e505658e4d93a222ad39da3a39ee291e1869e9eb` |
| `/tmp/ticket128_namespace_primitive_probe_v10.py` | `a3fa93c7935f5aa8b32022b58ad034d4ef48f8bb2547bcd570f263b9315845b2` |
| `/tmp/dmit-connection-audit/ticket128-namespace-primitive-probe-r10.log` | `84a09232c635da6f86aaaaefa4eccc24290aedeb9396b083d96140d2e0de3e8e` |
| `/tmp/dmit-connection-audit/ticket128-namespace-r5-notify-readonly.log` | `941424c99f8610fac6916843b7e8fa54fbe4e29e833cdc528ba322acc4edafb1` |
| `/tmp/dmit-connection-audit/ticket128-operator-smoke-r1.log` | `351fc9d1a35bdd89c951e1ed259e92bc278575874ce6071624db5246a6fdb49a` |
| `/tmp/dmit-connection-audit/run_ticket128_operator_smoke.py` | `825695c9c3f90467bc10fa8e1353b1f49572a1c92238b78276cb408656618172` |
| `/tmp/dmit-connection-audit/ticket128-operator-smoke-provenance.json` | `fa2c849103f2bb03562e86a1922b0a94dc76af8696e7302fd91a40336cd68a49` |
| `/tmp/ticket128-root-precode-check.json` | `330ae011caf90b17b94e98b8427b67701eb3ea960bd6a7dd4a18b82861f4d0b8` |
| `/tmp/ticket128-root-precode-new.log` | `9df04fa70c75281f9ae04ab6a538de950ffd6bd9c0815e854520bd9e0152d8a1` |
| `/tmp/ticket128-root-precode-old119.log` | `fc6e61a2813b1b33974cc8570a6273f0fa1f24c9ad41740860ce7aa0e4a47764` |
| `/tmp/dmit-connection-audit/prune-finished-ticket128-operator-smoke.log` | `79ad465183951c888b73c9a0b86a235bfce8016cc27d04fc115cf85b25d03468` |

独立冻结合同/门、fresh双轴pre和root编码授权仍待形成。阶段A实际default部署、合成真实模型/微信canary、原生主人初始化/反馈仍待执行；医学专业审核与fullG12归127/阶段B，不能以本页代替。
