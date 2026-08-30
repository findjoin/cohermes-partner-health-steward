# Ticket 123 冻结验证合同

> 状态：verification-authority refreeze checkpoint（2026-08-30）。产品基线为 `d29041bc5b52db2228acc6c08ac2e1aaaf2fd3e5`；测试接缝已经由 Ticket 123 与 ADR 0022 约定：`ProductionCoreService` 的 start/endpoint/close、三类 AF_UNIX CorePort、以及 Ticket 117 的两个 lifecycle Adapter Interface。测试不读取私有 helper、表结构、线程布局或摘要实现。
>
> 本次重冻权威：仅按已复现的 Linux 机械缺陷修复 V02 的错误 peer 拒绝生命周期、V04 的 temporary-directory 变量绑定、V05 的 fixture authority transition 接线、V06 的 transient child runtime/process-root 接线，以及 V07 fixture/runtime 的 bytecode 漂移；不改变产品目标、架构、门数量或断言语义。冻结 verifier：`tests/test_ticket123_production_core_service.py`，blob `e677632ee73aeb09c41299d030987de7611e0c31`。

## Verifier ownership

- verifier-owned 文件：`tests/test_ticket123_production_core_service.py`。
- 实现 Agent 不得修改本合同、冻结设计或 verifier-owned test；若门错误，停止并交回 verification authority。
- Windows 编码前唯一接受形状：`1 failure / 6 skips / 0 errors`，唯一根失败为 `partner_health_steward.production_core_service` 尚不存在。
- Linux 完成形状：`7/7 PASS / 0 skip / 0 error`。正式环境必须显式提供 `TICKET123_RUNTIME_ROOT`，测试进程本身由该闭包内 Python 3.11 启动；所有 verifier 及其 child Python 调用必须禁用 bytecode 写入；V06 还要求可用的 systemd transient-unit 环境。缺失不得写成 PASS。

## 公开 Interface

`partner_health_steward` 只新增导出 `ProductionCoreService`。Interface 为一个严格 start binding、只读 endpoint 和 `close()`；endpoint 精确为既有 `ticket118-core-port-v1` 的 AF_UNIX wire。`health-runtime` 投影只增加无正文的 `current_head_provider=dynamodb` 与 `managed_lifecycle_ready` 组合证据；不导出 release validator、Provider registry、数据库或通用 method dispatcher。

生产 module 内的 filesystem Adapter 按 Ticket 117 既有 Interface 接受验证：

- `enumerate(request) / purge(request) / absence(request)`；
- `put(package_ref, package) / get(package_ref) / remove(package_ref)`。

它们是已经存在 synthetic + production 两个 Adapter 的真实 Seam，不构成第二生命周期。

## 七门

| ID | 可观察断言 | 受影响回归 |
|---|---|---|
| 123-V01 | 构造使用 product `DynamoDBCurrentHead`、Ticket 121 host-private paths 与两个生产 lifecycle Adapter；投影观察 Dynamo 强读/lifecycle ready，服务期第二 writer holder 失败而 close 后成功，预置 effect 的正向 grant 与 execution-master 删除后的拒绝证明 execution vault；当前 staged release 只给无正文 unavailable；digest、closure、path、provider、设施、lifecycle root 或 installation/site 错误时 socket/DB 零创建 | 121、122、120 release |
| 123-V02 | 真实 AF_UNIX + `SO_PEERCRED`；为错误 UID 开放 pathname traverse/socket connect 后只接受 listener EOF/reset，timeout 明确失败；正确 UID可读，symlink 与活动旧 listener 不被替换，当前进程 TCP listener inode 集合不增加 | 118 CorePort/host |
| 123-V03 | 逐字兼容现有 Hermes `health-runtime-probe`、`health-runtime` read、effect claim/terminal wire；加密预置 Core receipt 经 typed CommandEnvelope 精确重放；重复 key、noncanonical、未知 field/kind、截断、尾随、空/超长 frame 无业务响应，caller intent/incomplete terminal 不成功 | 110、115、118 |
| 123-V04 | 同一 DB/head 重启精确返回同一 receipt；prepared record + remote-attempted journal + 已推进 product current-head 的重启 tracer 只 finalize 并精确 replay，恢复期间 Dynamo transaction 为零；head timeout/unknown、key loss、stale fence typed fail-closed，external model/delivery 为零；进程 SIGKILL 由 V06 负责 | 110、115、117、122 |
| 123-V05 | 使用 `lifecycle.py` 真实传入的 exact `operation_ref/authority_binding/transition_id` 和完整 opaque migration package；首次 immutable put 的并发 reader 必须实际观察 absence 与完整对象，线程异常回传；重启读回，遍历、symlink、hardlink、错 owner/mode/installation、内容冲突拒绝，purge/remove 后读回 absence | 117 |
| 123-V06 | runtime manifest 逐项 hash、实际 `sys.executable` 和未声明文件负测证明封闭 3.11 closure；renderer 精确输出 closure Python、`-I -m`、生产 module、binding path，CLI 在同一解释器只解析参数；transient unit 以 verifier-owned product `DynamoDBCurrentHead` 注入实际运行同一服务，正常 stop 清理，SIGKILL 后 socket 不可连接且同根重启取得 holder并清旧 socket | 120 release、121 holder |
| 123-V07 | 通过公开 store seam 持久化且读回合法 synthetic `SourceEnvelope.body`；数据库原始字节及 release/runtime/socket/lifecycle/ordinary roots 无 marker/key/credential，close 不改非目标 sentinel | 110 storage、117 lifecycle、120 secret scan |

## 防假绿

- verifier 独立建立文件、socket、错误 peer、崩溃和 runtime closure oracle，不接受产品自报 `healthy/secure/atomic` 字符串。
- 正向 current-head 对象必须是 `DynamoDBCurrentHead`；其 SDK 边界可使用 verifier-owned deny-network Dynamo client，但不得改用 `InMemoryCurrentHead`。真实 AWS G08 保持 `not-authorized/cannot-confirm`。
- V02/V06 的正式 PASS 只能来自 Linux 内核与 systemd；Windows skip 不能用于闭票。
- staged release 的 truthful unavailable 是正向结果之一，但不能代替 V03 的 typed Core receipt 重放、V04 的实际重启/authority 故障或 V06 的真实进程崩溃恢复。
- V06 不接触真实 AWS：正式 launcher 的 exact `ExecStart` 与 CLI parser、以及同一 `ProductionCoreService` 的 systemd 生命周期分别验证。真实 launcher + AWS binding 只在后继获准部署票验收。
- 测试不得 monkeypatch产品私有 helper、读取 SQLite 表断言业务成功、从 source 文本寻找关键词，或建立 test-only bypass。

## 验证命令

编码循环：

```text
python -m unittest tests.test_ticket123_production_core_service.Ticket123ProductionCoreServiceTests.test_v123_0N_* -v
```

交审门：

```text
python -m unittest tests.test_ticket123_production_core_service -v
python -m unittest tests.test_ticket121_host_authority tests.test_ticket122_dynamodb_current_head -v
python -m unittest tests.test_ticket117_integration tests.test_ticket118_integration tests.test_ticket120_integration -v
python -m unittest discover -s tests -v
python -m compileall -q partner_health_steward tests
git diff --check
```

正式 Linux V06 的一般合成 fixture 只可使用随机 `/tmp/ticket123-*`，并使用随机 transient unit 名和合成无正文 fixture；为使 `PrivateTmp=yes` child 可见，verifier 与最小测试闭包必须临时置于唯一 `/opt/cohermes/ticket123-verify-<verifier-blob>`，其 process root/socket 只可在该目录下新建的唯一 `0700` `process-root` 中。V06 child 必须显式继承当前 `TICKET123_RUNTIME_ROOT`；所有 verifier/child Python 调用必须禁止 bytecode 写入，V07 不得通过重生成 manifest 或缩小扫描范围掩盖漂移。开始/结束记录 default/partner service 状态但不重启、不配置、不写入它们。测试完成必须精确清理临时 unit、`/tmp` 目录、`/opt` verifier 闭包和进程。

## 审查与停止

编码前 Spec reviewer 只核对 Ticket 123/ADR/G03-G04 是否覆盖；Standards reviewer 只核对深 Module、三类 CorePort、权威/事务/副作用边界、复杂度上限和 verifier 防假绿。二者对同一 commit/tree PASS 后才冻结。

实施后先跑执行门，再由两个只读 reviewer 只核对冻结落地。只有可复现 P0—P2 且直接破坏 123-V01—V07 或既有回归才阻塞；理论风险、替代架构、未来 Hermes/model/Weixin/AWS 要求不扩入本票。
