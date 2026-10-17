# Ticket 129 唯一增量设计候选：DMIT 宿主 current-head

状态：pre-code candidate。主人已经选择存储边界，本文件不是实现通过或上线证据。对应 [Ticket 129](../issues/129-implement-host-sqlite-current-head-provider.md)、[主人决定](../evidence/38-owner-host-current-head-choice-20261018.md)及 [ADR 0023 候选](../../../docs/adr/0023-allow-owner-selected-host-current-head-with-snapshot-limit.md)。

## Characterization 与已接受限制

现有 `CurrentHeadPort` (`current_head.py:446–471`) 已定义九方法，HealthCore 依赖 typed authority、transition receipt、execution lease、terminal delete 和 writer transfer。Ticket 122 的 DynamoDB 实现是生产实现，但目标没有 AWS 账号/已配资源；在用户本次明确取舍后，不以此阻止仅 DMIT 的非诊断部署。

Ticket 121 的 HostPrivateWriterFenceVault 由主机私有 master 生成 capability/public fence。DynamoDB `_proof_matches:415–429` 比较 proof.authority、local site、local public fence，并比较 `SHA256(capability)` 与 fence 内摘要。这一算法可用于宿主 Provider，无需在 head 文件保存 capability。不能把 InMemoryCurrentHead 的明文 `_writer_capability` 直接持久化或称为生产实现。

用户接受的唯一降低是：同时恢复健康库、head、密钥的整机旧快照不具备域外新鲜性，可能恢复已删除/撤销/迁移前状态。新 Provider 不承诺自动识别这种 VM，不把运维离线要求包装为技术检测。正常崩溃恢复、当前受管文件/备份 purge、当前活体 head 下的旧 holder fencing、明确同意和 unknown 不盲重做维持原合同。

## 最小职责与依赖

新增 `partner_health_steward.host_current_head`，仅拥有一个受限 SQLite 文件中的不透明 head 与必要 receipt；原加密健康 SQLite 仍由 HealthCore 独占。head 文件不是第二画像或第二业务 ledger，不能接受健康正文、任意 metadata、raw request、模型输出、联系人/接收方身份、数据密钥、writer/execution capability。

```text
生产 bootstrap（精确 Provider 选择，无默认 fallback）
  -> HostSQLiteCurrentHead / HostHeadBinding
  -> 同机受限 head SQLite：HEAD + exact transition/lifecycle/lease receipts
HealthCore -> CurrentHeadPort 九方法（保持原 typed 语义）
HostPrivateWriterFenceVault -> WriterFenceProof（仅在内存提供 capability）
```

公开 Module/API 候选：

- `HostHeadBinding(database_path, installation_id, local_site, local_writer_fence_ref)`：不可变、严格验证的本机引用；路径为固定绝对文件，不含 secret。
- `HostSQLiteCurrentHead(binding)`：只打开已存在且 schema/identity 完整的安装，缺失与损坏不创建。
- `HostSQLiteCurrentHead.bootstrap(binding, initial_head)`：仅显式新安装创建，要求 generation=1、非 terminal、installation/site/public fence 匹配；先独占创建新文件再原子写入 schema+HEAD。任何已存在文件（包括空/损坏/terminal/其他安装）均拒绝且零覆盖，不能以“幂等”为名重建。
- 九个 CurrentHeadPort 方法与显式 `close()`；`provider_kind = "host-sqlite"` 为固定只读身份。

不增加 credential loader、Provider 工厂框架、普通 HTTP/RPC 或任意对象存储。未来磁盘路径和 schema 内部布局可逆，不作为独立测试隐藏要求。

## 存储、事务与进程并发

SQLite 使用标准库、单个固定 schema 版本、显式写事务和 `synchronous=FULL`。每个 mutation 在同一写事务内读取当前 head、验证 expected/proof/live lease 约束、写入新的 HEAD 与唯一 exact receipt，然后 commit。跨进程由 SQLite 锁/CAS 仲裁，不能只用 Python RLock。事务失败回滚；commit 后无法确认时返回 typed unknown 并允许 exact lookup，而不是重试 mutation。

长期只保存：AuthoritySnapshot 字段、无 secret 的请求 identity、AppliedTransition/AppliedLifecycleTransition 与 ExecutionLeaseReceipt 所必需的字段、live lease guard。receipt 编码只取 `.identity()` 的显式字段，严禁序列化 request.__dict__/repr、WriterFenceProof 或 capability。typed decoder 必须重新构造并验证 exact field 集与 primitive 类型；未知 schema/字段、畸形 identity 或损坏 receipt 不作为成功。

读取必须反映当前已提交 head；每次 CAS 在持有写事务时重新检查全部 expected 字段，不能复用构造时或上次 read 的快照。读取历史 receipt 不意味着当前仍能执行效果。

head 路径与父目录由部署绑定，父目录 private（0700）、常规单链接文件 0600、owner 与服务身份相符。拒绝 symlink、hardlink、路径替换/错 owner/mode、非 SQLite 或错误 namespace。打开后校验固定文件 identity，普通运行不主动跟随替换路径；journal/临时文件受同一 private 目录与 umask 约束。不是对最高权限主机攻击者的保证。

正常打开不 `CREATE TABLE IF NOT EXISTS` 来修复缺项或默默迁移 schema。bootstrap 中途崩溃可能留下无效文件，普通启动必须失败关闭，由精确新安装恢复流程处理；不能把缺失 head 当作允许重初始化。

## 九方法语义

1. `read()`：返回 typed HeadRead，错误 namespace/schema/IO 为 CurrentHeadError；无默认 head。
2. `conditional_advance()`：expected 必须等于事务内 live head；generation 加一；revision/transition/fence/site 和 exact AppliedTransition 同成同败。active lease 只允许现有 core 发出的 typed overlap，不能从 wire/durable bool 构造 overlap 权限。
3. `lookup_transition()`：只返回完全相同 AdvanceIdentity 的 receipt；同 transition ID 不同 operation digest/expected/request 不匹配不能冒充恢复。
4. `conditional_lifecycle_transition()`：terminal-delete 要求无 active execution lease，生成不可逆 terminal generation；writer-transfer 要求明确有效且不同的 target public fence/site，同事务轮换 authority 并撤销旧 live lease guard。历史 receipt 保留为恢复事实；不保留健康审计副本。
5. `lookup_lifecycle_transition()`：exact LifecycleTransitionIdentity 读回 terminal/transfer 已应用事实，不因当前头更进一步而伪造或丢弃既有 proof。
6. `validate_writer_fence()`：live authority、binding site/public fence、capability hash 全部匹配；terminal 抛 HeadTerminal。head DB 不含原 capability。
7. `acquire_execution_lease()`：先验证当前 live HEAD，再考虑已有 receipt。已存在的 exact receipt 不能绕过 transfer/terminal/current generation。默认独占，只有既有 core typed overlap 允许原合同中的有限并行；新 lease identity 与 guard 在一事务创建。
8. `lookup_execution_lease()`：只返回 exact identity 的历史/当前 receipt；不赋予重新执行权。
9. `release_execution_lease()`：校验 lease 原 authority 的 writer proof、exact lease、release operation digest，并验证当前 head 非 terminal 且仍为同一 writer fence/site。core 的合法 overlap advance 可以已经推进 generation，因此此项不把“generation 已前进但 fence 未变”误当 writer transfer；这沿用 DynamoDB 对既有 lease 的释放语义。只允许同 digest 的幂等重复 release，其他 digest 冲突；transfer 后旧 fence/terminal 不可恢复权限。guard 与 released receipt 原子更新。acquire/reacquire 仍必须匹配完整当前 authority，历史 receipt 只可 lookup。

现有 overlap 允许的业务场景属于 core 权威，Provider 仅执行原 typed permit 语义，不新增 unrestricted advance/parallel-send 开关。DynamoDB 旧合同与测试不为适应本 Provider 而放宽。

## 故障与恢复

已知事务冲突/锁等待超时在副作用前返回 HeadConflict/HeadTimeout；读写/损坏/文件身份问题为 CurrentHeadError；存在“可能已 commit 但调用方未获得确定终态”的路径返回 HeadUnknown，调用者走 exact receipt lookup/readback。错误消息只含固定 code，无 SQL 参数、文件内容、secret 或健康值。

不暴露生产 `set_failure` 或 synthetic success 开关。独立 verifier 可在隔离临时目录/子进程验证真实崩溃、两个进程 CAS、丢失响应后的 reopen/readback、旧 holder、文件/receipt 损坏与错误 binding。任何恢复不重放模型/发送，不以重新 bootstrap 消除 unknown。

terminal HEAD 保留为最小不透明墓碑；它不包含画像、联系人、批准或任务。正常删除仍由现有 lifecycle adapter 销毁 exact 数据密钥并 purge 受管 key/index/export/backup/staging/业务事实，不能只删 head DB，也不能把 head terminal 留存当作保留个人健康审计资料的理由。删除后新空白安装使用新的 installation namespace 和新秘密，不清除旧 terminal 以恢复原 identity。

## 生产组合与验收声明

生产 bootstrap 必须明确选择 `host-sqlite` 或原 `dynamodb`，没有自动 fallback；`ProductionCoreService` 接受该已验证 concrete Provider 并从 Provider 身份投影真实 `current_head_provider`，不能硬编码 `dynamodb`。新 release/manifest 记录 host Provider 的版本/schema 与本次接受限制，不绑定真实实例值或秘密。

本票只实现 Provider 与必要的具体类型/身份装配。真实目标 key/head provisioning、权限、健康安装、模型/微信与主人初始化继续由 128 的同一 run/gate 证明；涉及当前健康数据删除/迁移的动作不随 Provider 开发发生。验收报告对 host-sqlite 明确“整机快照防回滚不提供”，DynamoDB 外部资源/IAM/old-VM 证据应标不适用/已由主人接受边界取代，不能填 passed 或伪造 AWS 结果。

## 独立有限门与停止

独立 verifier 至少以最高九方法/API 验证：新安装 bootstrap/路径/错绑；跨进程唯一 CAS 与 exact receipt 重启；capability hash/旧 holder/terminal/transfer；lease/原 typed overlap/幂等 release；崩溃/unknown/坏文件失败关闭；存储无正文/secret及真实 provider/快照声明。保留受影响 110/117/121/122/123 回归，不以新增组合数量作为完成标准。

冻结后实现只修改 Provider 与已声明装配，不改测试或 core 业务状态机。需要第二业务真相、失去现有正常删除/unknown/并发隔离、伪造外部证据或更改已接受快照限制时，带具体触发证据返回顶层；不再次询问已决定的仅 DMIT 取舍。
