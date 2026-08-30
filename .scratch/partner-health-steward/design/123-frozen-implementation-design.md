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

启动 binding 只含非秘密引用：同一 content-addressed release root/digest、runtime closure root/manifest（含 closure digest）、installation/site、SQLite path、socket path 与 owner/group/mode/allowed peer UID、四个 Ticket 121 路径、本机 managed-replica root、migration-artifact root，以及 Ticket 117 既有 lifecycle release/registry 声明。未知字段、绝对路径越界、symlink/non-regular、错 owner/mode、release/runtime hash 漂移或 installation/site/current-head 错绑均在监听前拒绝。传入对象必须是 Ticket 122 `DynamoDBCurrentHead`；缺失 lifecycle 根、synthetic/InMemory Provider 或设施对象同样在创建 socket/DB 前拒绝。

运行闭包必须由同一 release digest 内容绑定，并满足：

- 实际执行解释器位于闭包内且 `3.11.x`；
- manifest 逐文件列出解释器、标准库、完整 `partner_health_steward` 和 `cryptography` 依赖文件 hash；
- 启动时重算闭包，禁止 PATH/system Python、在线安装、用户 site、未声明 `PYTHONPATH` 和额外 site-packages；
- systemd `ExecStart` 指向闭包内解释器和固定 launcher；依赖漂移形成新 release digest，不能复用旧 evidence。

当前知识、诊断和七 Skill 资产仍为 staged 时，进程可以提供无正文运行状态，但必须报告 `unavailable`，不得退回 `StagedCorePortServer` 或生成健康业务结果。后续 Tickets 124/125/127 使同一发布链的对应资产 current；123 不提前激活。

## CorePort

只保留 `command | managed-read | controlled-effect` 三类 tagged union，endpoint 必须逐字兼容既有宿主客户端：`{"transport":"af-unix","path":...,"protocol":"ticket118-core-port-v1"}`；frame 复用 4-byte big-endian length、canonical JSON、64 KiB 和 exact-field 规则，response 精确为 `protocol_version/kind/request_id/status/payload`。

- `command` 必须接受现有 Hermes 宿主握手 `{"operation":"health-runtime-probe"}`；健康业务命令只接受 `{"interface":"command-v1","command":<CommandEnvelope wire>}`，并把现有 `HealthCore.handle()` 的 typed response 放入 payload。caller 不能提交 current-head、业务成功或终态事实。
- `managed-read` 必须接受现有 `{"projection":"health-runtime"}`，只允许冻结 allowlist 的无正文投影；禁止任意 method/table/path 查询。该投影公开 `current_head_provider=dynamodb` 与 `managed_lifecycle_ready`，用于证明 121/122、两个生产 lifecycle Adapter 和真实 Core 已在同一组合根，而不是暴露私有对象。
- `controlled-effect` 必须兼容现有 Hermes 宿主的 `{"phase":"claim"}` 与 `{"phase":"terminal","terminal":...}`。claim 只能由 Core 取当前 intent 并生成 grant，caller-supplied intent 是未知字段并在分派前拒绝；当前 staged/unavailable 无 intent 时返回 `intent=null/grant=null/current_authority`。完整 terminal 才能回交 Core；缺 terminal、旧 generation/fence、连接中断或无法确认均沿用既有 unknown/fail-closed 语义。

每个连接只处理一个 request/response。未知 kind/field、重复 key、非 canonical、空 frame、截断、尾随、超长、无效 UTF-8 在业务分派前关闭连接且不返回成功。禁止 TCP listener。

## AF_UNIX 与进程边界

- socket parent、socket 自身和 binding 全部 `lstat/openat` 风格验证；拒绝 symlink、hardlink/non-socket、旧监听者和目录替换。
- socket owner/group/mode 与 binding 精确一致，mode 只能是 `0660`；Linux `SO_PEERCRED` 的 UID 必须等于唯一 Plugin service UID。文件 ACL 放行也不能替代 peer credential。
- systemd unit 使用固定低权限用户、共享 Plugin group、`UMask=0077`、`NoNewPrivileges=yes`、`PrivateTmp=yes`、只读 release/runtime、仅写精确 state/socket/lifecycle roots；无普通聊天、模型、微信或 Hermes credential 环境。
- stop 顺序：先停止 accept → 排空已进入 Core 的 exchange → `HealthCore.close()` 释放 writer/execution holder → 关闭 SQLite → 移除且只移除当前 inode 的 socket。无法排空时返回不可确认，不清理别的路径。

## Lifecycle 文件 Adapter

实现 Ticket 117 已有两个真实 Seam，不改变其 Interface：

- managed replica Adapter 只接受固定 `LIFECYCLE_PURGE_BINDINGS` 到本机受管对象的完整映射；`enumerate` 接受 Ticket 117 的 exact installation 请求，`purge/absence` 接受 exact `operation_ref/authority_binding/transition_id`。它拒绝 symlink、错 owner/mode、未知 binding 与根外路径；删除后 fsync 并读回 absence，无法证明保持 unknown。
- migration artifact Adapter 只在精确根下按 `lifecycle-package:<operation_ref>` 原子 `put/get/remove` Ticket 117 的完整 `ticket117-opaque-migration-package-v1`（manifest + semantic_state），拒绝遍历、覆盖不同内容、symlink/hardlink/non-regular 和非 canonical wire；写入、目录 rename 与删除均 fsync，重启后读回同一对象。

这些 Adapter 不扫描普通 Hermes Session/Memory、日志、任意备份或整个文件系统；未配置的真实 provider 继续列入 `remains_unproven`，不能伪装已清理。

## 七个冻结验收门

| Gate | 现实结果 | 必须杀死的错误 |
|---|---|---|
| 123-V01 | 同一 release/runtime/binding 构造真实 121/122 + SQLite + HealthCore + 两个生产 lifecycle Adapter；投影观察 Dynamo 强读/lifecycle ready，第二 writer holder 在服务期失败、close 后成功；预置 effect 只有执行密钥在位才取得 host grant；staged 资产只报告 unavailable；错 digest、installation/site、InMemory Provider、缺设施/根在监听前失败 | 用 staged server／内存 vault/Adapter 冒充生产，忽略 121/122/lifecycle 注入，或先建 socket 后发现配置错误 |
| 123-V02 | Linux AF_UNIX owner/group/0660 与 `SO_PEERCRED` 同时执行；错误 UID 已有 pathname/connect 权限仍由 listener EOF/reset 拒绝且 timeout 算失败；symlink 与活动旧 listener 不被替换，进程 TCP listener 集合不增加 | 只靠父目录权限、自报 peer、悬挂连接或 loopback TCP 冒充本机权限边界 |
| 123-V03 | 既有 Hermes 握手 wire 与三类 request 真实穿过 canonical byte stream；预置的加密 Core receipt 经 typed CommandEnvelope 精确重放；严格错误在分派前关闭，forged effect 无 grant，不完整 terminal 不成功 | 只做回显外壳、任意方法 RPC、宽松 JSON 或 socket 旁直调 Core |
| 123-V04 | 同一 DB/head 重启精确重放同一 receipt；另以 prepared + remote-attempted journal + 已推进 current-head 构造重启恢复，只 finalize 既有决定且无第二次 transaction；head unknown、key loss、stale fence 失败关闭，模型/外发为零；进程 SIGKILL 由 V06 证明 holder/socket 恢复 | 重启生成第二结果、把已发生 CAS 重做、旧 fence 继续写或未知时盲目重做 |
| 123-V05 | 两个生产 filesystem Adapter 使用 Ticket 117 的 exact request/package 形状完成原子 put/read/remove、enumerate/purge/absence 与重启读回；首次 immutable put 的并发 reader 只观察 absence 或完整对象且异常必须传回，遍历、symlink、hardlink、错 mode/installation 和内容冲突失败关闭 | 继续注入 Ticket 117 fake、自创 wire、部分写、路径遍历/链接删除或清理未读回就宣称完成 |
| 123-V06 | 内容寻址 Python 3.11 闭包逐项 hash 且拒绝未声明文件；正式 renderer 精确固定 closure Python + `-I -m partner_health_steward.production_core_service --binding ...`，同一解释器验证 CLI 参数；hardened systemd transient 通过 verifier-owned 已绑定 122 Adapter 实际启动同一 `ProductionCoreService`，正常 stop 清 socket/holder，SIGKILL 后旧 socket 不可连接且同一根可重启取得 holder | 只在 systemd 中 import 包、renderer 不可执行、依赖目标 Python 3.10/用户 site/额外包，或崩溃后服务不能恢复 |
| 123-V07 | 用公开 `EncryptedStateStore.save_source_envelope` 写入可读回的合法 synthetic health body；SQLite 原始字节、release/runtime/socket/lifecycle/ordinary roots 无明文或密钥，关闭只移除本服务对象 | 先拒绝 marker 再宣称加密、明文副本、秘密日志或普通 Hermes 状态成为第二健康库 |

每门只使用一个正向 tracer 和能杀死该现实错误的等价类，不按字段、崩溃点或请求种类做笛卡尔积。实现 Agent 按 V01→V07 纵向 red→green；每个 checkpoint 只重跑当前门及已绿门。

## 允许复杂度、禁止项与停止规则

允许：一个深 `ProductionCoreService`、两个既有 lifecycle Seam 的本机 Adapter、一个严格 CorePort server、一个固定 launcher/unit、一个 runtime-closure builder/validator。内部可按 locality 分文件，但不增加新的业务 Interface。

禁止：第二 current-head、第二数据库或 activation ledger、Provider framework、通用 RPC、TCP、后台自动 retry、在线依赖安装、自动 AWS 建表、真实部署、Hermes 消息、模型、微信、医学激活、读取真实健康资料或 partner profile。

V06 只证明正式 launcher 形状/参数解析和由同一 `ProductionCoreService` 承担的真实 systemd 生命周期；隔离门中的 current-head 仍由 verifier 注入已绑定的 product `DynamoDBCurrentHead`。真实 launcher + AWS 身份/资源接线属于获准部署票，不得由本票报告为已通过。

冻结后 finding 只按 `architecture-governance.md` 处置。若 121/122 或现有 CorePort Interface 无法承载本设计，以可复现证据停止；不得在 123 更换 ADR 0022。七门、受影响回归、全量测试与双轴实施审查通过后立即停止，不因另一种实现偏好扩大本票。
