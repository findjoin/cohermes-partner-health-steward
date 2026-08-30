# Ticket 123 冻结实施设计

> 状态：pre-code candidate。产品基线为 commit `17851080f9a5df1ad9d15187d1cc7fd93ce4f976`、tree `17bdb993958b171e64d30d5ede63769a5b011478`。本设计只闭合生产 `health-core` 组合根、AF_UNIX CorePort、本机 lifecycle 文件 Adapter 和固定 Python 3.11 运行闭包；不接通 Hermes 消息、模型、微信，不部署 default/partner，也不执行真实 AWS G08。

## Characterization

- `HealthCore`、`EncryptedStateStore`、`HealthPlugin` 和 command／managed-read／controlled-effect 业务语义已经由 Tickets 110—117 实现并回归；不得在 123 重写状态机。
- Ticket 121 已提供 `HostPrivateKeyProvider`、`HostPrivateWriterFenceVault` 与 `HostPrivateExecutionCapabilityVault`；Ticket 122 已提供 `DynamoDBCurrentHead`。两者是本票必须组合的生产 Adapter，`StaticKeyProvider`、`InMemoryCurrentHead` 和两个 InMemory vault 不能进入生产组合根。
- Ticket 120 的发布物只安装了 `StagedCorePortServer`：它使用 loopback self-check 并统一返回 `health-core-staged`，没有生产组合根、AF_UNIX peer enforcement、systemd 进程、真实 lifecycle 文件 Adapter 或完整 Python 3.11 闭包。
- Ticket 117 的 `managed_replica_adapter` 与 `migration_artifact_adapter` 只有 verifier synthetic Adapter；生产文件对象的枚举、原子写入、清理、缺失读回和重启恢复尚不存在。
- 目标 default 主机当前系统 Python 是 3.10.12；Ticket 123 不允许依赖它、在线 pip 或未声明 site-packages。

## 唯一增量架构

新增一个深 Module：`ProductionCoreService`。它的外部 Interface 只有：

1. 用一个不可变、严格字段的本机 binding 和一个已经绑定的 `DynamoDBCurrentHead` 打开服务；
2. 返回现有 `ticket118-core-port-v1` AF_UNIX endpoint；
3. 关闭并排空服务。

Module 内部一次性完成：release/runtime 闭包验证 → 主机私有设施验证 → 加密 SQLite 打开 → current-head 强读与 writer holder 取得 → execution capability vault → 本机 lifecycle Adapter → `HealthCore`／`HealthPlugin` 组合 → AF_UNIX 监听。任何步骤失败都不得留下可接受健康请求的 socket；已经启动后失去 key、writer proof、current head 或完整终态时，现有 Core 语义返回 `unavailable/unknown`，模型与外发为零。

`ProductionCoreService` 不成为第二业务权威、Provider DAG、通用 RPC 或部署器。删除它会使 release、密钥、current-head、SQLite、lifecycle、socket 和进程恢复规则重新散落到调用者，因此其深度成立。

## 固定依赖方向

```text
systemd / fixed Python closure
  -> ProductionCoreService
       -> HostPrivate* (Ticket 121)
       -> EncryptedStateStore
       -> DynamoDBCurrentHead (Ticket 122)
       -> filesystem lifecycle Adapters
       -> HealthCore -> HealthPlugin
       -> AF_UNIX CorePort
  <- Hermes Plugin（Ticket 124 才接线）
```

- `ProductionCoreService` 可以依赖现有 Module；`HealthCore`、storage、121/122 Adapter 不反向依赖它。
- DynamoDB SDK client/credential 由目标本机运行身份注入 Ticket 122 Adapter；123 不创建凭据 loader，不把凭据值写入 binding、日志或 release。
- Plugin 只能跨 CorePort，不能取得 SQLite、主机私有路径、Dynamo client 或 concrete `HealthCore`。

## Binding 与发布闭包

启动 binding 只含非秘密引用：同一 content-addressed release root/digest、runtime closure root/manifest、installation/site、SQLite path、socket path 与 owner/group/mode/allowed peer UID、四个 Ticket 121 路径、本机 managed-replica root、migration-artifact root，以及 Ticket 117 既有 lifecycle release/registry 声明。未知字段、绝对路径越界、symlink/non-regular、错 owner/mode、release/runtime hash 漂移或 installation/site/current-head 错绑均在监听前拒绝。

运行闭包必须由同一 release digest 内容绑定，并满足：

- 实际执行解释器位于闭包内且 `3.11.x`；
- manifest 逐文件列出解释器、标准库、完整 `partner_health_steward` 和 `cryptography` 依赖文件 hash；
- 启动时重算闭包，禁止 PATH/system Python、在线安装、用户 site、未声明 `PYTHONPATH` 和额外 site-packages；
- systemd `ExecStart` 指向闭包内解释器和固定 launcher；依赖漂移形成新 release digest，不能复用旧 evidence。

当前知识、诊断和七 Skill 资产仍为 staged 时，进程可以提供无正文运行状态，但必须报告 `unavailable`，不得退回 `StagedCorePortServer` 或生成健康业务结果。后续 Tickets 124/125/127 使同一发布链的对应资产 current；123 不提前激活。

## CorePort

只保留 `command | managed-read | controlled-effect` 三类 tagged union，复用 4-byte big-endian length、canonical JSON、64 KiB 和 exact-field 规则。

- `command` 只承载现有 `CommandEnvelope` 或 `TrustedHealthCommand` 语义；caller 不能提交 current-head、业务成功或终态事实。
- `managed-read` 只允许冻结 allowlist 的无正文投影，至少包含 `health-runtime` 与既有 lifecycle/status 投影；禁止任意 method/table/path 查询。
- `controlled-effect` 只把 core-issued intent 转成当前 execution grant，并把完整 terminal 回交现有 Core。forged intent、旧 generation/fence、缺 terminal、连接中断或无法确认均沿用既有 unknown/fail-closed 语义。

每个连接只处理一个 request/response。未知 kind/field、重复 key、非 canonical、空 frame、截断、尾随、超长、无效 UTF-8 在业务分派前关闭连接且不返回成功。禁止 TCP listener。

## AF_UNIX 与进程边界

- socket parent、socket 自身和 binding 全部 `lstat/openat` 风格验证；拒绝 symlink、hardlink/non-socket、旧监听者和目录替换。
- socket owner/group/mode 与 binding 精确一致，mode 只能是 `0660`；Linux `SO_PEERCRED` 的 UID 必须等于唯一 Plugin service UID。文件 ACL 放行也不能替代 peer credential。
- systemd unit 使用固定低权限用户、共享 Plugin group、`UMask=0077`、`NoNewPrivileges=yes`、`PrivateTmp=yes`、只读 release/runtime、仅写精确 state/socket/lifecycle roots；无普通聊天、模型、微信或 Hermes credential 环境。
- stop 顺序：先停止 accept → 排空已进入 Core 的 exchange → `HealthCore.close()` 释放 writer/execution holder → 关闭 SQLite → 移除且只移除当前 inode 的 socket。无法排空时返回不可确认，不清理别的路径。

## Lifecycle 文件 Adapter

实现 Ticket 117 已有两个真实 Seam，不改变其 Interface：

- managed replica Adapter 只接受固定 `LIFECYCLE_PURGE_BINDINGS` 到本机受管对象的完整映射；`enumerate/purge/absence` 绑定 exact installation 和 operation，拒绝 symlink、错 owner/mode、未知 binding 与根外路径。删除后 fsync 并读回 absence；无法证明保持 unknown。
- migration artifact Adapter 只在精确根下按 bounded opaque ref 原子 `put/get/remove`，拒绝遍历、覆盖不同内容、symlink/hardlink/non-regular 和非 canonical wire；写入、目录 rename 与删除均 fsync，重启后读回同一对象。

这些 Adapter 不扫描普通 Hermes Session/Memory、日志、任意备份或整个文件系统；未配置的真实 provider 继续列入 `remains_unproven`，不能伪装已清理。

## 七个冻结验收门

| Gate | 现实结果 | 必须杀死的错误 |
|---|---|---|
| 123-V01 | 同一 release/runtime/binding 构造真实 121/122 + SQLite + HealthCore；staged 资产只报告 unavailable；错 digest、系统 Python、InMemory Provider 或缺设施在监听前失败 | 用 staged server／内存 Adapter 冒充生产，或先建 socket 后发现配置错误 |
| 123-V02 | Linux AF_UNIX owner/group/0660 与 `SO_PEERCRED` 同时执行；错误 UID、宽权限、symlink、旧 socket 均不能到达 Core；无 TCP | 只靠文件权限、自报 peer 或 loopback TCP 冒充本机权限边界 |
| 123-V03 | 三类 request 真实穿过 canonical byte stream；严格错误在分派前关闭；forged effect 不取得 grant，terminal 不完整不变成成功 | 只实现 probe、任意方法 RPC、宽松 JSON 或外壳 socket 旁直调 Core |
| 123-V04 | key/head/fence/prepare-finalize/unknown 与进程崩溃后只恢复既有事实；旧实例失效且模型/外发为零 | 重启生成第二结果、旧 fence 继续写、未知时盲目重做 |
| 123-V05 | 两个生产 filesystem Adapter 通过既有 Interface 完成原子 put/read/remove、enumerate/purge/absence 与重启读回；边界错误失败关闭 | 继续注入 Ticket 117 fake、路径遍历/链接删除或清理未读回就宣称完成 |
| 123-V06 | 内容寻址 Python 3.11 闭包和 hardened systemd transient 运行在隔离 Linux 临时根；系统 Python/在线 pip/未声明包不可达 | 依赖目标 Python 3.10、用户 site 或手工环境才能运行 |
| 123-V07 | SQLite 中健康 payload 认证加密，release/socket/log/Session/Memory/lifecycle 元数据无正文、密钥、credential；关闭只移除本服务对象 | 明文副本、秘密日志、普通 Hermes 状态成为第二健康库 |

每门只使用一个正向 tracer 和能杀死该现实错误的等价类，不按字段、崩溃点或请求种类做笛卡尔积。实现 Agent 按 V01→V07 纵向 red→green；每个 checkpoint 只重跑当前门及已绿门。

## 允许复杂度、禁止项与停止规则

允许：一个深 `ProductionCoreService`、两个既有 lifecycle Seam 的本机 Adapter、一个严格 CorePort server、一个固定 launcher/unit、一个 runtime-closure builder/validator。内部可按 locality 分文件，但不增加新的业务 Interface。

禁止：第二 current-head、第二数据库或 activation ledger、Provider framework、通用 RPC、TCP、后台自动 retry、在线依赖安装、自动 AWS 建表、真实部署、Hermes 消息、模型、微信、医学激活、读取真实健康资料或 partner profile。

冻结后 finding 只按 `architecture-governance.md` 处置。若 121/122 或现有 CorePort Interface 无法承载本设计，以可复现证据停止；不得在 123 更换 ADR 0022。七门、受影响回归、全量测试与双轴实施审查通过后立即停止，不因另一种实现偏好扩大本票。
