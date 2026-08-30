# Ticket 121 冻结实施设计

> 状态：freeze-candidate。characterization 产品基线为 commit `52d569dc487b3bbc8023a797bd67b70a30cab0cb`、tree `5cfe065de74f6a86696a7a7fc79923d1f28ab8b1`。最终 frozen checkpoint 和 reviewer identity 只在本轮复审通过后写入。本票只把既有三个主机权威 Interface 换成 Linux 生产 Adapter，不改变 `HealthCore` 状态机、SQLite 事实模型或 ADR 0022。

## 目标与已确认差额

当前 `KeyProvider` 只有 `StaticKeyProvider`，`WriterFenceVault` 与 `ExecutionCapabilityVault` 只有内存实现。`HealthCore` 已在写入、effect claim、恢复、probe 与 orderly close 的正确位置消费这些 Interface；缺口不是业务架构，而是进程重启后仍可恢复、但不能随 SQLite 一起复制的主机私有能力。

Ticket 117 的删除链还要求同一数据密钥设施提供 `destroy(request)` 与 `absence(request)`。因此 `HostPrivateKeyProvider` 同时承担这个既有 duck-typed role；这不是第四套权威，也不新建公开 Protocol。

## 唯一产品增量

新增深 Module `partner_health_steward/host_authority.py`，公开一个不可变路径 binding `HostPrivateFacilityPaths(data_key, writer_master, execution_master, lock_directory, destruction_receipt)` 和：

- `HostPrivateKeyProvider(paths, installation_id)`，实现 `KeyProvider`，并提供 Ticket 117 已消费的 `destroy/absence`；
- `HostPrivateWriterFenceVault(paths)`，实现 `WriterFenceVault`，并提供迁移 preflight 所需的 `public_fence_ref(installation_id, site)`；
- `HostPrivateExecutionCapabilityVault(paths)`，实现 `ExecutionCapabilityVault`。

可在 `partner_health_steward/__init__.py` 做必要 export。禁止修改 `core.py`、`storage.py`、`authority.py`、`current_head.py` 及三个既有 Protocol。路径 binding 是 Ticket 123 组合根的配置输入，不规定私有目录布局或文件名。主机设施由部署层预置；本票不提供 root provisioning CLI、daemon、通用 secret backend 或在线轮换。

三个 secret path 的内容各为 32 个随机字节。它们的父目录和 lock directory 必须是当前 service uid/gid 所有的 `0700` regular directory，secret file 必须是同 uid/gid 的 `0400` regular file。构造时用 directory fd、`O_NOFOLLOW | O_CLOEXEC` 打开；验证 owner、group、mode、size、device/inode。每次取用前重新核对 pathname 与 pinned handle；缺失、替换、symlink、FIFO、hard-link 数异常或权限漂移后，该实例永久失败关闭。原始字节不得出现在 repr、异常、日志、环境变量、配置、SQLite、CorePort 或 Git。内部 helper、lock 文件名和 canonicalization 实现保持可逆，不属于冻结 API。

## 数据密钥与删除

`key_id` 固定为 `key:v1:<sha256(data-key)>`，只公开摘要。`get_key()` 返回进程内 32-byte copy。

`destroy(request)` 只接受 Ticket 117 的 exact terminal cleanup shape：字段精确为 `operation_ref`、`authority_binding`、`transition_id`；authority 的 installation 必须等于构造绑定、`terminal=true`，且 transition 与 request 一致。它对 pinned data-key 做身份复核后删除并 fsync directory，再原子持久化一个只含 contract/version、key id 与 exact request digest 的非秘密 destruction receipt。相同 exact request 在进程重启后仍返回 `{"status":"confirmed"}`；不同 operation/authority 不得借已删除状态取得 confirmed。`absence(request)` 用同一 binding 与 receipt 核验后只返回 `absent | present | unknown`。删除数据密钥不删除 writer/execution master；生命周期协调器仍独占 terminal 顺序。receipt 不是健康业务事实或 capability ledger，其私有编码不冻结。

## Writer holder 与 122 的共享 fence 合同

同一 `(installation_id, site)` 在 lock directory 内持有 Linux `flock(LOCK_EX | LOCK_NB)` 到 Session `release()` 或进程退出。另一活进程不能得到 Session；崩溃由内核释放锁。holder claim 只参与恢复一致性检查，不写 capability ledger。lock 的私有命名不冻结。

writer fence 的公开引用固定为：

```text
fence:v1:<base64url-128-bit-nonce>:<sha256-hex(raw-writer-capability)>
```

nonce 不是随机运行态输入，而是以 writer master、domain `partner-health-steward/writer-nonce/v1` 与 `(installation_id,site)` 确定性导出的 128 bit base64url 值；raw capability 再以 writer master、domain `partner-health-steward/writer-capability/v1` 与 `(installation_id,site,nonce)` 通过 HMAC-SHA256 导出为 lowercase hex。两者的 canonical message 都是 UTF-8 domain + NUL + `ensure_ascii=false,separators=(",",":")` 的 JSON 数组。`public_fence_ref()` 因而能在 transfer 前生成目标 ref，且重启稳定；它不返回 raw capability。`proof_for(authority)` 只在 Session active、authority 非 terminal、installation/site 匹配且 `authority.writer_fence` 严格符合上式时返回 `WriterFenceProof`，并 constant-time 比较公开摘要。raw capability 只在进程内。

Ticket 122 只能保存公开 fence ref，并按同一公式验证 proof。writer-transfer 必须把远端 head 原子设置为请求已有的 `target_writer_fence_ref`；不得自行生成另一个 fence。目标主机须预先持有能生成该 ref 的 writer master/nonce 组合。

## Execution completion capability

每个 `AuthoritySnapshot` 使用完整 canonical authority digest 命名独占 `flock`。第二活进程不能取得同一 authority Session；进程退出后可以恢复。

实现必须以 execution master、完整 `ExecutionCapabilityBinding` 和 writer proof 摘要确定性生成 opaque capability，并让 `recover(binding, holder_id)` constant-time 验证 `holder_id == holder_id_for(capability)`。具体内部 HMAC domain、canonical encoding 与 lock 命名不冻结。相同 exact binding/holder 在重启后恢复相同 capability；authority、effect、intent、claim、holder 或 fence 任一变化均不能恢复旧能力。只有 capability 值可在当前进程内返回，不写 JSON ledger、SQLite 或另一个数据库。

## 必须杀死的现实错误

| 验收 | 冻结控制 |
| --- | --- |
| 121-A1 | 打开 SQLite 前验证目录/三文件的类型、身份、owner/group/mode/size；路径替换后不继续使用旧 fd 冒充当前设施。 |
| 121-A2 | writer holder 由内核锁排他；clean release 和真实进程 crash 后可恢复，第二活实例不能得到 proof。 |
| 121-A3 | target `public_fence_ref()` 可在 transfer 前稳定生成，public ref 与 raw proof 可交叉验证，但 raw proof 永不进入 Dynamo/SQLite/输出；旧 fence、错误 site、terminal 均拒绝。 |
| 121-A4 | completion capability 绑定完整 authority + exact effect + holder；重启可恢复，任一字段变化与并发第二 holder 均拒绝。 |
| 121-A5 | terminal 删除 exact 数据密钥且可证明 absence；任意非 terminal、错 installation 或错 operation 请求不能删除。 |
| 121-A6 | 缺少/篡改设施、仅复制 SQLite 或权限不可确认时，HealthCore fail closed，current-head 写、模型和 transport 调用均为零。 |

## 复杂度上限与停止规则

最多一个新产品 Module、一个路径 binding、三个 Adapter、一个 verifier 文件和必要 export。只允许一份非秘密 destruction receipt；不新增数据库、capability ledger、secret daemon、KMS/TPM、多平台抽象、部署器或 Windows 生产实现；不改业务状态机。

冻结 verifier 为 `tests/test_ticket121_host_authority.py`，编码前预期 `1 failure / 5 skips / 0 errors`，唯一红灯是生产 Module 缺失；实现后 Linux 必须 `6/6 PASS`。Windows 只确认缺失红门，不能以 mock 代替真实 `flock`、symlink、FIFO、uid/gid 和进程 crash。

若既有 Interface 无法承载 exact binding、Ticket 122 不接受共享 fence 格式、或实现必须保存第二份可复制 capability ledger，立即停止并返回一个可复现冲突，不扩 Interface、不换架构。
