# Ticket 118 增量架构冻结设计

> 状态：candidate，等待 verifier-owned 门与 fresh-context 双轴预审。characterization 基线为 `169cf6cdba421cc628de435cea8cb284e2d8ec94`，tree `64334c675cf32eb950c5b19779d4a1965c863304`。本设计只冻结 Ticket 118 难以逆转的增量决定；内部字段、helper、文件布局和测试组织保持可逆。

## 目标与非目标

把 Tickets 110—117 已验收的 Plugin/core、七个 Skill、模型与投递 Adapter、知识／安全／诊断 bundle 和迁移协议编译为可重复核验的 release；在固定 Hermes v0.20.0／commit `3c27eb6234bf91b8ceee9e9071591b31e9b148cb` 的真实 Plugin lifecycle／platform registration Interface 上证明唯一 `health_weixin` 宿主合同；形成不会执行部署或回滚的 install／upgrade／rollback readiness 判断。

本票不部署或读取真实 Partner，不登录微信、不调用真实模型、不接受医学／内容权利／许可审批、不执行 systemd、迁移或回滚，不支持多 Hermes 版本、多宿主、多聊天平台、热升级、蓝绿发布或自动部署。真实 target binding 和 canary 只属于 Ticket 119。

## Characterization 与保留行为

- 基线全量 `729/729` 通过；Tickets 110—117 的健康命令、受控效果、bounded managed read、current-head、writer fence、删除和迁移语义全部保留，不重写业务状态机。
- 当前 `HealthPlugin` 仍直接调用多个 `HealthCore` 方法；现有 `contract.py` 的 protocol v1、64 KiB 长度前缀 canonical JSON frame 只覆盖部分 command Interface。给每个方法机械生成 RPC 会形成庞大浅 Interface，不能作为冻结路线。
- 当前没有 release compiler、宿主合同 Module、无凭据 preflight Module、当前 release declaration 或 Ticket 118 验证入口；历史 `ops/` 不能成为 release 输入。当前 release 的 Hermes 接入必须由新建的 `partner_health_steward.hermes_host` 公共 Module 提供 `register(ctx)` 与 `health_weixin` Adapter factory，并由 release 自有的 `release_assets/hermes-v0.20.0.patch` 和 `release_assets/native-health-disabled.assertion.json` 提供相互独立、内容寻址的宿主变换与禁用声明；它们不得用同一 Python 文件复制冒充多个 artifact，也不复用历史 `ops/` Plugin。
- 固定 Hermes 源码实际提供 `PluginContext.register_platform(...)`、`PluginManager.discover_and_load(...)` 与 `PlatformRegistry`。platform 注册是逐项生效且同名 last-writer-wins；Plugin 部分注册失败不会天然回滚，因此入口必须默认关闭，只有完整宿主核验后才可获得进程内 activation proof。
- 固定源码先查 plugin platform registry、实例化失败时不会回退同名 builtin，但 builtin 与普通处理仍存在；required patch／disabled-native assertion 必须证明健康消息在原生正文去重、合批和 cursor 前进入唯一入口，并且 Plugin 缺失或失败时不会落到旧 `medical`、native health 或普通健康处理。

现实差额只有三类：可重现 release、实际 pinned-host 合同、无凭据变更 readiness。没有 characterization 证据的现有业务 Module 不是本票重构范围。

## 唯一增量架构

```text
thin tool / tests / Ticket 119 observation Adapter
                    │
                    ▼
HostReleaseContract（一个深 Module）
  ├─ build(ReleaseSources) -> ReleaseManifest
  ├─ verify(ReleaseManifest, PinnedHermesSource) -> HostContractReport
  └─ assess(TransitionAssessment) -> ReadinessReport
       ├─ internal ReleaseCompiler
       ├─ internal HermesHostVerifier
       └─ internal ReadinessEvaluator

Pinned Hermes lifecycle / health_weixin Adapter
                    │
                    ▼
CorePort（remote-owned Seam，仅三类语义）
  ├─ command(command wire) -> outcome
  ├─ managed_read(read wire) -> bounded projection
  └─ execute_effect(effect exchange) -> terminal outcome
       ├─ InProcessCoreAdapter（现有合成环境）
       └─ UnixCoreAdapter -> CoreRuntimeServer -> HealthCore
```

工具脚本只是薄 Adapter：解析参数、调用上述 Interface、渲染机器可读报告和退出状态；它不计算摘要、不决定兼容性、不采集真实目标事实，也不拥有完成 verdict。

## 冻结 Interface 与依赖方向

### `HostReleaseContract.build`

输入只包含仓库根、版本化 release declaration、仓库相对 artifact allowlist、本地 pinned Hermes 来源和非秘密环境约束。根路径仅用于定位，绝不进入产物。

输出是 immutable、canonical、content-addressed `ReleaseManifest`。同一内容与声明环境重复 build 必须得到相同 manifest 和根摘要；缺项、额外项、路径逃逸、绝对路径、符号链接逃逸、不可规范化文本或秘密扫描失败时不得产生部分有效 release。

manifest 固定区分四种事实：

1. `repository_verified`：仓库内实际内容及 hash；
2. `target_binding_required`：Ticket 119 必须在目标核验的要求名，当前值不得进入；
3. `external_approval_required`：权利、医学审核、许可和主人批准，只能是未证明要求；
4. `forbidden_secret_classes`：只声明禁止保存的秘密类别，不保存值。

release 至少内容绑定：固定 Hermes commit、逐文件来源 hash、extractor version、声明环境和三类 CorePort 版本；独立的 required patch/native-disable assertion；Plugin/core；七 Skill bundle；health_weixin、模型和投递 Adapter Interface；schema；capability-profile schema/builder/validator；MinimumHelpBundle；知识／危险规则／诊断 bundle；Ticket 117 migration protocol/schema/builder/semantic registry 及其 synthetic fixture；Python 与依赖约束；服务身份／ACL requirement。上述声明或 artifact 任一漂移都必须改变 release digest。实例 migration manifest、owner/profile/current-head 值、联系人、服务资源 ID、时间戳和开发机路径不参与 release digest。每个 `repository_verified` 项必须公开仓库相对路径、语义角色和内容 hash；验证者逐项重算，而不是相信实现自报的摘要闭包。

### `HostReleaseContract.verify`

顺序固定：

1. 离线验证 upstream commit、allowlisted 原始文件逐项 SHA-256、extractor 版本、required patch hash、生成物 hash 和 native-disable assertion；
2. 由真实 `PluginManager.discover_and_load(...)` 加载当前 release 的 `partner_health_steward.hermes_host`，运行真实 `register`、platform registry、factory、`connect(is_reconnect=False)`／`disconnect()`；`verify` 返回前必须完成全部 lifecycle 并关闭验证实例，测试从宿主调用记录和 registry reachability 独立观察，不得以实现自报字段、动态伪装类或历史 Plugin 代替；
3. 证明 `health_weixin` 是唯一 pre-native 健康入口；
4. 证明 CorePort socket peer／service identity、ACL、frame、timeout 和完整终态；
5. 证明模型／Weixin／联系人 Adapter 只能执行 core 已授权 intent 并完整回交；
6. Plugin、Gateway、core、入口或 probe 任一不可信时先关闭入口，再返回 verdict。

返回只允许 `pass | fail | cannot-confirm`。`fail` 表示已有证据证明不匹配；`cannot-confirm` 表示来源、超时或必要证据不能确认。后两者均不产生 activation proof。activation proof 只在本次进程、当前 manifest 和当前 host verification session 内有效，不持久化，不成为第二权威。纯离线、无需真实目标绑定的兼容性判断必须存在可达 `pass` 路径；只要判断依赖 Partner、Linux 服务身份或目标资源，即使合成 observation 自称 verified 也最多为 `cannot-confirm`。

### `CorePort`

跨进程只冻结三类现有语义：command、bounded managed read、controlled effect exchange。不得把任意 method name、SQLite、Session、Memory、FTS、日志、observer 或通用状态 RPC 暴露到 socket。

- command 承载现有入站、设置、任务、诊断和 lifecycle semantic command；caller 不能提交业务成功、current head 或终态事实。
- managed read 只返回现有无正文、受限投影；不返回表、密钥、凭据或内部阶段。
- execute effect 由 core 先形成并授权 model／delivery intent，Plugin 侧 Adapter 执行后必须回交完整 terminal。execution grant 只绑定受认证会话，不作为可持久或可由 Adapter 构造的权威值。验证必须同时证明合法 core-issued effect 的完整回交，以及 forged intent、stale fence、缺项 terminal 和外部调用后 socket 中断的失败关闭；后者必须进入既有 `unknown`，不能盲目重发。

`InProcessCoreAdapter` 与 `UnixCoreAdapter` 是同一 Seam 的两个真实 Adapter。HealthPlugin 宿主可达路径必须只依赖 CorePort，不能一部分走 socket、一部分继续直接调用 concrete HealthCore。宿主合同验证必须让 command、managed-read、controlled-effect 三类请求都真实穿过 byte-stream framing，并由远端 runtime 的接收记录和终态接收记录作为独立 oracle；只发一个 probe command 不足以证明 Seam。

socket 复用 protocol v1 的 4-byte big-endian length + canonical JSON、64 KiB 上限和 strict exact-field 语义；新增 wire 只能是三类 tagged union。错误 peer、ACL、截断、尾随、重复字段、超长、未知 kind、超时或不完整 terminal 全部失败关闭。118 在本地合成环境验证 peer／service identity 与 ACL policy 的严格 Adapter 合同及真实 AF_UNIX framing；Linux `SO_PEERCRED`、systemd UID／mode 和目标 socket 路径的现场 enforcement 证据明确留给 119，Windows 上的合成身份 Adapter 不得冒充该现场证明。

### `HostReleaseContract.assess`

mode 只允许 `install | upgrade | rollback`。它消费已验证 release／host report 和 schema-validated 的外部 observation；不主动连接目标或修改配置。

- install 检查全部 target requirement 是否已有当前证据；缺失为 `cannot-confirm`。
- upgrade 直接比较由 `build` 产生的 current/candidate release manifest 和 host report，重新核验 artifact、schema、Skill／Adapter／model／bundle hash、ACL requirement、current head 和旧入口禁用；调用者提交的 `compatible` 字符串不构成证据。不兼容为 `fail`，不能确认保持 offline。
- rollback 直接比较候选旧 release 与当前 semantic manifest，并要求 target observation 中的 generation 和 writer fence 具有非 synthetic 的当前证据。rollback 只评价代码兼容性，绝不恢复旧数据、批准、入口、generation 或 fence；纯离线比较可以形成 `offline_compatibility=pass`，但不能把整体 target readiness 提升为 `pass`。

输出是无健康正文、无秘密的逐要求报告与总体 `pass | fail | cannot-confirm`。合成 observation 永远不能升级成真实 Partner proof。manifest、宿主报告和 readiness 报告都不得回显仓库／pinned root、Windows 或 Linux 绝对路径、环境秘密值或目标配置值；验证子进程只继承明确列出的无秘密环境。

## Hermes 宿主与失败关闭顺序

- release 中只包含一个 health Plugin 和一个 `health_weixin` platform registration；七 Skill 是 Plugin 内资产，不是七个 Plugin。
- platform registration 初始为 disabled。只有 manifest、pinned source、required patch、native-disable、CorePort probe 和 Adapter contracts 全部通过后才签发 activation proof 并打开入口。
- partial registration、factory/check/config/callback/connect failure、重复或覆盖注册、Plugin 缺失、core 不可达、probe 不一致均保持入口关闭；残留 registry entry 没有读正文、调用 core、模型或发送权。失败并撤销当前 entry 后必须再次主动探测 current、native Weixin、旧 medical/split 与 ordinary fallback，仍全部不可达；只在当前 entry 存在时屏蔽旧路由不合格。
- ordinary-forward 只能是健康入口在可信状态下对明确普通消息作出的显式结果。健康、混合、未知或宿主不可确认时不得落回普通 Agent、旧 `medical` 或 native health path。
- disconnect 顺序是先撤销 activation proof 和准入，再排空已开始的 CorePort exchange，最后关闭 Adapter／socket。无法证明排空时健康保持关闭；不承诺 Hermes 没有提供的热卸载。

## 依赖与 Adapter

| 依赖 | 类别 | 冻结处置 |
|---|---|---|
| canonical manifest、hash graph、分类、兼容与扫描 | in-process | HostReleaseContract 内部，无 Adapter |
| 仓库文件、临时提取目录、AF_UNIX | local-substitutable | 使用真实本机原语和临时目录；文件系统 Seam 不公开 |
| health-core 进程 | remote but owned | CorePort；InProcess 与 Unix 两个 Adapter |
| pinned Hermes 来源 | true external | 本地只读 PinnedHermesSource Adapter；正向必须运行真实 interface |
| current head | remote but owned | 复用既有 CurrentHeadPort；本票不建目标资源 |
| 模型、Weixin、联系人 | true external | 复用现有 synthetic Adapter；本票不真实调用 |
| Partner、凭据、审核和许可 | true external | 仅列 target/external requirement；Ticket 119 绑定 |

## A1—A7 不变量与现实故障

| 验收 | 冻结不变量与必须杀死的现实错误 |
|---|---|
| 118-A1 | allowlist 闭包内任一受管 artifact 漂移会改变摘要；实例值／路径／时间不改变。杀死“漏 hash 仍同摘要”和“target profile 混入摘要”。 |
| 118-A2 | 正向证据来自可复现 pinned source 的真实 lifecycle／registration Interface；partial registration 后入口不开放。杀死“手写 stub 冒充宿主”和“注册半成品可读正文”。 |
| 118-A3 | 所有宿主可达 core 调用通过三类 CorePort；错误 peer／frame／终态或任一进程故障共同关闭。杀死“socket 外壳旁仍直调 core”和“effect 后超时冒充成功”。 |
| 118-A4 | Adapter 不能自造 intent、提升 terminal 或通过 Session／Memory／observer／通用 RPC 写状态。杀死 forged intent、stale fence 或缺项 result 被接受。 |
| 118-A5 | required patch、native-disable 与 registry/entry reachability 同时证明唯一入口；Plugin 失败无 old medical/native fallback。杀死“只写 disabled 文档”和“失败回退健康处理”。 |
| 118-A6 | install／upgrade／rollback 区分 pass/fail/cannot-confirm；schema/hash/current authority 不兼容时不能靠复制旧文件通过。 |
| 118-A7 | repo release、target requirement、external approval、secret class 严格分类；缺目标事实保持 unknown，secret/PII/绝对路径不进入 bundle、digest 或报告。 |

## 复杂度上限与停止规则

允许的必要复杂度只有：一个深 HostReleaseContract、一个三类 CorePort、一个 pinned Hermes source Adapter、两个 CorePort Adapter，以及薄工具入口。内部可以按 locality 分文件，但不得增加公共 validator、artifact plugin framework、Provider DAG、部署器、第二 release database、第二 current head、第二业务 ledger 或新的健康业务 Interface。

删除 HostReleaseContract 后，artifact 闭包、来源证明、失败关闭与兼容判断会散回调用者，故它有真实 depth；删除 CorePort 后跨进程权限与 unknown 语义会散回 Plugin 方法，故 Seam 有现实依据。相反，删除 durable activation ledger、通用 RPC 或自动部署框架不会让本票核心风险回流，因此这些机制禁止进入。

冻结门错误、pinned Hermes 与选定 HOW 根本冲突、需要真实目标决定或新增架构时立即返回冻结阶段；不得边改门边实施。局部注册或 Adapter 差额只在上述 Seam 内修复，不更换架构。A1—A7 通过且无经举证的 P0/P1/P2 后停止扩写本票。
