# 128 - 部署并完成主人产品验收

Type: task
Status: claimed
Parent: [健康管家首发 TO、CAN 与 HOW 决策闭合路线](../map.md)
Blocked by: [130 - 受控自然语言与主人操作真实入口](130-connect-governed-natural-language-daily-runtime.md), [122 - 实现 DynamoDB current-head 生产 Provider](122-implement-dynamodb-current-head-provider.md), [124 - 接通 pinned Hermes 的真实健康入口](124-connect-pinned-hermes-live-health-entry.md), [125 - 实现 Partner 首跳模型与治理知识 Adapter](125-implement-partner-model-and-governed-knowledge-adapter.md), [126 - 实现真实 Weixin 与支持联系人投递 Adapter](126-implement-live-weixin-and-support-contact-delivery-adapter.md), [131 - 明确标识的非诊断模型操作预算](131-support-explicit-nondiagnostic-model-operational-budget.md)

**What to do:** 对一个新内容寻址 release 在用户的 default Hermes 上分两阶段完成真实部署与验收。阶段 A 在诊断范围保持 staged 时完成 target binding、最小 canary、主人初始化和非诊断能力验收，使主人可以先使用健康记录、画像、非诊断问答、提醒、任务、安全提示、控制和数据权利；阶段 B 仅在 Ticket 127 闭合后完成 BMI 诊断激活、完整 G12 和完整首发验收。明确禁止访问或部署女友的 partner Hermes。

## Required orchestration delta

当前 Ticket 119 `AcceptanceRunContract` 只有完整首发的固定 G01→G12 路径，并在 G07 医学审核未通过时阻断 G10—G12；因此不能靠文档跳过 G07 实现阶段 A。本票在任何真实部署前，先为同一个 Module、同一份不可变报告和同一 GateExecutor Seam 增加两个固定 `run_scope`：

- `non-diagnostic`：固定执行 G01—G06 → `128-ND07` → G08—G11 → `128-ND12`。`128-ND07` 必须证明 BMI 保持 staged、普通入口不能调用诊断、非诊断运行只加载项目自有或已明确授权的固定最低安全／治理文案；`128-ND12` 只形成初始化和非诊断主人验收证据，不写 active、G12 passed 或 product acceptance passed。
- `full`：保持 Ticket 119 已有 G01→G12 顺序、gate ID、批准、报告和完成语义不变。

`run_scope` 绑定 release/run/target 且不可在同一 run 改写；两个分支共用现有 ledger、重放、unknown、批准和无正文规则。不得建立第二验收账本、第二产品状态、任意 gate 列表或可配置 DAG。该增量必须先完成 characterization、冻结设计、独立 verifier-owned 门和双轴预审；旧 Ticket 119 七门及完整分支回归必须保持绿色，随后才允许执行阶段 A。

## Fixed target and safety boundary

- 唯一目标：用户自己的 default `/root/.hermes` 与 `hermes-gateway.service`。partner `/root/.hermes-partner`、`hermes-gateway-partner.service` 及其他 profile/service 永久为 pre-write rejection。
- 每个真实 AWS、模型、微信、联系人、部署、删除、迁移和主人动作分别使用 Ticket 119 的 target/release/run/gate-bound opaque approval；批准不能跨 gate 借用。
- collector 不读取或返回凭据、完整配置、健康正文、联系人身份、运行数据库、模型 transcript 或可逆摘要；只保存无正文 opaque refs。

## Bounded acceptance

### 阶段 A：非诊断主人可用

1. 用冻结后的 `non-diagnostic` 分支对同一 release digest 依次运行 G01—G06、`128-ND07`、G08—G11、`128-ND12`；任何非 passed 立即停止。不得由 caller 跳过 gate 或直接调用 G10—G11。
2. G10 验证 default 的 pinned artifact/dirty digest、required patch、Plugin discovery、唯一入口、CorePort service、peer/ACL、current-head、密钥/vault、capability profile、co-stop 和可回滚安装。
3. G11 仅用不含诊断内容的最小合成／脱敏输入验证真实 Partner 首跳模型和用户自己的 Weixin；interface accepted 不冒充 delivered/read，unknown 冻结同 run。
4. 取得精确阶段 A 授权后，由主人在微信中完成真实 `health-init`；Core 读回 initialization enabled、current head 和 writer fence 当前后，才显示“健康管家已初始化”。初始化结果必须同时显示 BMI 诊断未启用，不能写 G12 passed、诊断 active 或完整首发。
5. 按冻结主人测试序列验收非诊断能力：普通健康记录、画像／证据、一般健康问答、明确拒绝范围外诊断、当地日复盘、任务、主人控制／权利、失败／unknown 状态、最低安全、危险升级和已获准的最小联系人警报／纠正。使用的最低安全与非诊断文案必须是项目自有或具有明确使用权的固定版本，不得复制尚未获权的诊断内容。
6. 主人确认上述范围“有用、清楚、可信”后，只能记录 `non-diagnostic-owner-usable` 里程碑；它是无正文验收结论，不是新的产品状态、G12 passed 或完整首发声明。

### 阶段 B：诊断激活与完整首发

7. Ticket 127 对同一 release/bundle digest 闭合后，建立新的 `full` run，按 Ticket 119 原顺序重跑 G01—G12 并取得规定的一次性 acceptance authorization；完成真实 BMI 范围验收、五项 G12 receipts 和 active-path readback 后，才允许 G12 passed。
8. 主人对包含已激活 BMI 范围的完整序列明确确认“有用、清楚、可信”后，才可记录完整产品验收并解决本票；拒绝、超时、无法确认或 Ticket 127 失效时保持 staged，不自行激活。
9. 任一阶段的 post-check 失败均按 release-bound backup 回滚 default，重新启动并确认普通 Hermes 可用；不得触碰 partner。

## Completion claim

阶段 A 证据齐全时只能记录“非诊断健康管家已初始化并可供主人使用”，并列出诊断仍 staged；此时本票保持 `claimed`。只有 Ticket 127 当前有效、G01—G12 对同一 release/run 全部 passed、五项 G12 receipts 和 active-path readback 齐全，才可在 Ticket 119/128 记录“完整首发／产品验收通过”并解决本票。这不等于已经证明长期稳定；上线后稳定性另以真实无正文运行证据观察，不在本票预设新的架构或功能。

## Delivery discipline

部署前分别冻结阶段 A 与阶段 B 的精确 release、target、run、回滚点和测试序列；阶段授权不得互相借用。每个阶段完成后提交无正文证据、更新 Ticket/Map、普通 push；不得把批准、秘密或主人资料写入 Git。

## 2026-10-18 verified implementation inputs

- 用户已明确选择仅DMIT并接受整机旧快照恢复限制；129实现该Provider，部署不再以AWS账号为前提，不伪造历史DynamoDB证据。真实初始化披露必须说明当前受管删除与整机旧快照限制，并显示诊断未启用；可用既有HealthInitRuntime executor形成该已批准内容，不改写旧frozen111披露历史。
- Ticket130记录真实生产typed executor/受控自然语言候选阶段缺口，是本票非诊断产品可用性的前置实现，不将fixture或124装配单独宣称为完整产品。
- 主人已选择继续 JOJO 并接受非诊断操作预算／不提供共同上下文保证，见 ADR 0024 与 Ticket131。阶段 A 需经该票验证并如实披露；该决定不是 G10/G11 passed，full／诊断继续需要严格 profile／容量证明及原医学门槛。


## 2026-10-18 read-only startup and rollback characterization

以下为当前源码事实与128待绑定输入，不是下游详细设计、部署授权或验收通过；130唯一设计保持`5722e2d`停改，126产品仍按`6752fad`正式验证。

- **验收编排现成边界。** `AcceptanceRunContract.run(manifest, gate_executor, run_context)`在`partner_health_steward/acceptance_run.py:210`可复用；`:20`仍固定119-G01—G12，`:284`严格run_context没有run_scope，`:230`遇任一非passed即阻断后续。`tools/ticket119_acceptance.py:42`只接受synthetic/fixture/deny-network/test环境，不能用它驱动真实target。`DefaultOnlyGateExecutor.execute`（`release_deployment.py:902`）是120独立staged安装协议而非119完整目标GateExecutor；仍需本票既定ND/full有限增量与真实target-local Adapter，不可直接重命名fixture证据。
- **发布器与资源现状。** `HermesReleasePublisher(repository_root).build(output_root)`（`release_deployment.py:424`）按内容寻址生成staged package，并在`:404`收集产品全部Python源码；`:395`仍给七份Skill写入staged/unavailable占位、`:399`给minimum-help/knowledge/safety/diagnostic写占位bundle。`publish_current_successor(staged_root, verified_runtime_manifest)`（`:473`）只复制原stage、加入runtime closure attestation后生成新current digest（`:501`），不自动替换这些资源。故单独build→publish_current_successor不能冒称真实Skill/批准bundle就绪。当前124正式门在`tests/test_ticket124_live_entry.py:196`显式另制合成资源并重算manifest后装配；这是fixture事实，不能把其替换过程当现成生产资产/发布命令。
- **真实Python构造已存在，CLI未装配live。** `ProductionCoreService(binding, *, current_head, live_runtime=None)`（`production_core_service.py:667`）已接受真实typed LiveHealthRuntime；后者构造和`validate_release/core_dependencies/plugin`在`live_health.py:150/179/204/211`，会重验七份asset bytes与digest并拒绝staged标记。service.start在`:894`实际加载这些依赖；而当前`_main --binding [--head-binding]`在`:1467`最后`:1504`只传binding/current_head，无live_runtime。`render_health_core_systemd_unit`在`:1413`生成的ExecStart（`:1449`）恰指该CLI。因此现rendered unit只证明Core底层服务入口，不能证明真实初始化/日常主人路径；130实现后的GovernedNonDiagnosticRuntime/真实七Skill/attestor与Plugin模型Bridge仍须本票在实际startup绑定，不能以probe green代替。
- **129与密钥资源可复用。** 同CLI从非秘密`health-current-head-binding-v1`选择`host-sqlite`（`:1474—1486`），构造`HostHeadBinding(database_path, installation_id, local_site, local_writer_fence_ref)`及真实HostSQLiteCurrentHead，不自动bootstrap。唯一新installation的公开`HostSQLiteCurrentHead.bootstrap(binding, initial_head)`在`host_current_head.py:135`，只准generation=1、非terminal且身份/site/fence匹配，文件以O_EXCL建立（`:172`）；已有head不能覆写或丢失后当新装。service由binding.host_private_paths构造`HostPrivateFacilityPaths(data_key, writer_master, execution_master, lock_directory)`及三真实provider/vault（`:791—794`）；目录0700、文件0400、同euid/egid、非symlink/单硬链与pinned identity由`host_authority.py:76/143/171`核验，密钥为32bytes或已绑定tombstone（`:344`）。renderer没有自动生成这些设施或LoadCredential条目；需真实当前资源绑定，不能用测试key/vault。CurrentHead当前采用主人已选DMIT限制，不重新引入AWS为前提。
- **安装/回滚表面是staged-only。** `DefaultOnlyGateExecutor`先固定target为default `/root/.hermes` + `hermes-gateway.service`（`release_deployment.py:33`），按release/run/G10/有效期permit及消费检查后backup→stage→install→restart→is-active（`:902—964`）；partner或其他target在任何操作前拒绝。backup只复制plugins与ticket120-release-metadata（`:786`）；install仅替换health-weixin plugin与metadata（`:815`），不应用Hermes patch、不配入口/模型、不建Core unit或真实资源。restore（`:858`）恢复这两项，再重启/is-active（`:980`）；不恢复健康DB/head/密钥或旧整机快照。current release不能直接交这个stage-only installer，因`:576`严格要求state=staged。`HostReleaseContract.assess(mode=rollback)`（`host_contract.py:1129`）始终restore_instance_state=False，缺实际target authority只得cannot-confirm，不能据此跳过回滚证据。
- **最小现场核查输入。** 后继必须分别核实：同release/运行时闭包/真实pinned source+patch/七assets当前；Core head与本地finalized revision、site/fence/key/vault/managed lifecycle当前；AF_UNIX peer uid/ACL及唯一health_weixin registry/禁用native与失效co-stop；真实初始确认与outbox交接；回滚后的原plugin tree/metadata身份、default服务重启及普通Hermes可用，且不触partner。现is-active只证明进程活跃，不能单独证明普通对话、模型或微信可用；真实外部核查仍需同一验收run的精确授权。未读取任何实际profile配置、密钥、健康/聊天内容，也未执行部署、网络、模型或渠道动作。


### Current production content availability

只读tracked product/tools及资源清单未发现可正式装载的项目自有ND claim/template资源包或最低安全content bundle；不能把测试publication或历史ops资源当当前生产内容。已有的是`nondiagnostic.py:143/171`的ApprovedClaimAtom/ApprovedReplyTemplate类型、`knowledge.py:236`的KnowledgePublisher和`model_adapter.py:603`的exact artifact loader；Core当前从真实构造依赖接收这些值（`core.py:1095—1126`），没有自动从仓库装载生产内容的factory。产品确有`answer_resolution.py:106`的131上下文说明及`:133—136`的版本化失败关闭文案，它们可复用，但不是完整非诊断claims/最低安全模板发布包。Publisher生成的四份bundle仍只有staged/unavailable标记（`release_deployment.py:399`）。

`tests/test_ticket116_integration.py:181` publication明确使用synthetic source/review，且示例expires_at为2026-08-25；`:261`最低帮助为“[合成测试]”及approved-synthetic，顶层synthetic=True/production_approval=False。这些只能证明接口，不能复制或改布尔值后上线。KnowledgePublisher在`knowledge.py:243—248`要求真实rights approved、reviewed-chinese与professional_review approved；`safety_diagnosis.py:154`要求最低帮助rights/review/parse当前。项目自有固定非诊断治理/最低安全文案必须在128阶段A以实际内容、版本、digest、来源/使用权和真实适用审阅引用绑定同release，不能伪造医学审核，亦不能借ND去激活未授权诊断包。没有主人支持联系人配置时保持该能力unavailable，不猜身份、不借default/partner资料；联系人可选，不作为非诊断初始化的强制前提。


### Verified default service scope

2026-10-18 root只读现场核查已确认：DMIT实际default `hermes-gateway.service`属于root用户级systemd，而非系统级；只查系统级得到LoadState=not-found不能据此宣称实际网关已停止。既有无秘密metadata脚本为`/tmp/dmit-connection-audit/dmit_deployment_metadata.sh`；精确只读查询上下文为`env XDG_RUNTIME_DIR=/run/user/0 DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/0/bus systemctl --user show hermes-gateway.service`。2026-10-22独立源码复核更正此前controller判断：现有120 `_DefaultServiceController`在`release_deployment.py:635—645`已经调用`systemctl --user`，并非系统级。后继须绑定实际root用户总线/XDG上下文并验证真实执行，不能从已选用户scope直接推断SSH启动可用或业务健康。该记录仅更正事实，不执行service操作、不读取配置或秘密，不新增部署方案。


## 2026-10-24 当前设计认领与唯一引用

Status 已认领为 `claimed`。130已由root以 `b5c73f5b681858568d3428aa18c2052514e57330` 闭合，产品基线仍精确 `f21e8ad43bc92954da0a0ed5322cf421e48d0828`；这些离线绿色不代表128部署或主人验收。

本票唯一增量设计草稿：[128 default 非诊断部署设计](../design/128-default-nondiagnostic-deployment-design.md)。当前仅characterization/设计，未冻结、未编码、未部署。草稿沿原119两个固定scope、真实资源/typed factory、新披露/无诊断scope投影、首次bootstrap与真实副本absence、原宿主启动/普通出站、root已选OS隔离、可回滚安装、G11原生因果与ND12真实主人事实收敛；既有纯合成反例已记录在该唯一文件。

本文较早“可用HealthInitRuntime executor直接形成新披露”的输入经当前精确matches复核不成立：只换executor会被拒绝，须沿同Module增加严格新版本，旧111保持。普通出站目前仍缺真实send_ordinary装配；0400或allowed-root-UID也不证明普通Agent隔离。root已选择普通Agent整树低UID worker/原proxy API lifecycle、Gateway relay-only和独立无网络Core路线，临时原语probe不冒充生产通过。详细事实、最小新增Interface/状态、回滚与尚待真实来源的事实均只在上述唯一设计草稿维护；回滚启动前同样须证明普通Agent/健康私有材料隔离，已有健康状态时不得启动未隔离旧root基线，无法证明安全恢复则停入口并明确cannot-confirm。

本次公开setup已收口为固定default私有操作binding与薄prepare/run；新scope生产链同时绑定118 host manifest与120 distribution两个已有digest，不能将旧无distribution报告借作current部署证据；旧v1 full字节不变。详细Interface及实算关系只在唯一设计维护。

阶段A即使达成 `non-diagnostic-owner-usable` 也保持本票claimed；127及完整full验收要求保留。未修改产品/测试/Map/其他票或其冻结文件，未commit/push。

## 2026-10-24 编码前R1审查与窄修

同一候选checkpoint `56d9e9010caa25bf4e6bd40442b8fbbd58898bcf` / tree `5499dada9e0f8e6f8322360c7e25fe682c12b7d8` 已普通推送，包含唯一设计、独立合同/test/raw/helper和[实际调查证据69](../evidence/69-ticket128-characterization-and-deployment-inputs-20261024.md)。fresh Standards pre PASS、无finding；fresh Spec pre FAIL，仅P2 `128-SPEC-01`：V07错误要求成功JSON导出后外部managed root非空，和唯一设计§6及当前原加密store/内存chunk发送链冲突。成功附件并不要求新增磁盘副本，不能为测试绿制造额外健康副本。

root将其分类为**测试oracle错误**，交独立verification仅修该断言及合同对应事实；不是产品缺陷、未知恢复豁免或架构变更。原记录 `/tmp/health-steward-reviews/128-pre-56d9e90-{spec,standards}.txt` 保留。需新同一checkpoint与fresh双pre再授权编码；当前尚未冻结授权、未改产品、未部署。原119full、七family的其他正/负向及真实来源要求不变。

## 2026-10-24 R2冻结与一致性实施授权

独立verification窄修 `128-SPEC-01` 后的新checkpoint `cb1435477aa4fc6c0e6062884984e60b00394dfb` / tree `215aa2a9fb1b67106be6e170199ac85f3ac29ee8` 已普通push，fresh-context Spec与Standards均PASS、无阻塞。五份当前冻结文件/旧18字节、真实R2 prerequisite-red与旧119绿、实际隔离/helper前提、root编码授权及停止边界见[Evidence70](../evidence/70-ticket128-precode-freeze-and-implementation-authority-20261024.md)。本票仍claimed；授权仅一致性实施，真实程序门、default部署/微信canary/主人原生同意和反馈未通过，127/full不激活。

## 2026-10-24 自然定时接线覆盖窄重冻

实际default启动没有调用已交付的wake能力，原V07由verifier主动wake代办。独立verification窄修V07及对应合同的新checkpoint `8fa6edc0f21490239ef31630ea17d0311c01bd68` / tree `123194d27b6723e3f21e2afd7608f90b3c1b7a05` 已普通push，fresh Spec/Standards pre均PASS。新冻结身份、其余21冻结文件逐字保持、R2实际先失败于G02依赖打包、新自然触发red尚未执行及root最小继续实施授权见[Evidence71](../evidence/71-ticket128-natural-wake-refreeze-20261024.md)。未部署或主人验收，阶段A仍claimed，130/127/full不重开或伪造。

## 2026-10-24 隔离OS与整family观察前提窄重冻

R5实际G02原637、G03原12通过，G04止于旧129V02的SemLock错误；真实3.11配对已证缺少隔离shm，补齐后原测试通过。独立verification仅修helper/test/合同的该前提与已证不相容的整family等待，新checkpoint `fd7e508b0438b4415842b948b2163aa61e5f7523` / tree `3c3abed3e8e768955ec7c43e8f356c5c20fe1d39` 已普通push，fresh Spec/Standards pre均PASS；身份、原生产预算和256断言保持、实际首失败/完整性及继续授权见[Evidence72](../evidence/72-ticket128-namespace-prerequisite-refreeze-20261024.md)。没有实际timeout，新helper完整门尚未执行，未到G10/自然trigger，不称部署或阶段A完成。
