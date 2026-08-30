# Ticket 123 冻结验证合同

> 状态：verification-authority final refreeze checkpoint（2026-08-30，独立双轴审查原始 finding 的唯一当前权威）。产品基线为既有产品提交 `a06988d8173bda0e7beb2ffaf147527ea0297cf2` 与此前 runner checkpoint `3e8f9ef0db1e073587a29956e2632922cfc1b3d9`；测试接缝已经由 Ticket 123 与 ADR 0022 约定：`ProductionCoreService` 的 start/endpoint/close、三类 AF_UNIX CorePort、以及 Ticket 117 的两个 lifecycle Adapter Interface。测试不读取私有 helper、表结构、线程布局或摘要实现。
>
> 本次重冻只将独立双轴审查已复现的四个可观察产品缺口写入既有七门：V01 current release 的同一完整发布链、V03 request-side EOF/延迟 tail、V06 canonical closure digest 与同一已验证 release digest 绑定、以及 V06 的 close 排空超时。没有新增 Gate ID、产品目标、架构或 CorePort wire。冻结 verifier：`tests/test_ticket123_production_core_service.py`，blob `7aec1af838e0cf67e23dda79bbf78da9af149214`。

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
| 123-V01 | 构造使用 product `DynamoDBCurrentHead`、Ticket 121 host-private paths 与两个生产 lifecycle Adapter；投影观察 Dynamo 强读/lifecycle ready，服务期第二 writer holder 失败而 close 后成功，预置 effect 的正向 grant 与 execution-master 删除后的拒绝证明 execution vault；同一完整发布闭包的 staged 资产只给无正文 unavailable，合法 current release 才可使资产 current；digest、closure、path、provider、设施、lifecycle root 或 installation/site 错误时 socket/DB 零创建 | 121、122、120 release |
| 123-V02 | 真实 AF_UNIX + `SO_PEERCRED`；为错误 UID 开放 pathname traverse/socket connect 后只接受 listener EOF/reset，timeout 明确失败；正确 UID可读，symlink 与活动旧 listener 不被替换，当前进程 TCP listener inode 集合不增加 | 118 CorePort/host |
| 123-V03 | 逐字兼容现有 Hermes `health-runtime-probe`、`health-runtime` read、effect claim/terminal wire；每个合法 request 由客户端 `shutdown(SHUT_WR)` 的 request-side EOF 定界，服务只在 `recv(1)` 返回 EOF 后分派；未 half-close 至 socket timeout、任何 trailing byte（包括超过旧 30ms 窗口后到达）均在业务分派前关闭；加密预置 Core receipt 经 typed CommandEnvelope 精确重放；重复 key、noncanonical、未知 field/kind、截断、尾随、空/超长 frame 无业务响应，caller intent/incomplete terminal 不成功 | 110、115、118 |
| 123-V04 | 同一 DB/head 重启精确返回同一 receipt；prepared record + remote-attempted journal + 已推进 product current-head 的重启 tracer 只 finalize 并精确 replay，恢复期间 Dynamo transaction 为零；head timeout/unknown、key loss、stale fence typed fail-closed，external model/delivery 为零；进程 SIGKILL 由 V06 负责 | 110、115、117、122 |
| 123-V05 | 使用 `lifecycle.py` 真实传入的 exact `operation_ref/authority_binding/transition_id` 和完整 opaque migration package；首次 immutable put 的并发 reader 必须实际观察 absence 与完整对象，线程异常回传；重启读回，遍历、symlink、hardlink、错 owner/mode/installation、内容冲突拒绝，purge/remove 后读回 absence | 117 |
| 123-V06 | runtime manifest 的 `files` 必须按 POSIX relative path 严格升序，`closure_digest` 精确为 `sha256(canonical-json(files))`；`canonical-json` 为 UTF-8、`ensure_ascii=false`、`sort_keys=true`、逗号和冒号无空白。服务逐项重算实际 closure，并在同一严格 start binding 中重新验证同一 release root/digest；重排 files、同步自重算 manifest/binding 仍拒绝。实际 `sys.executable` 和未声明文件负测证明封闭 3.11 closure；renderer 精确输出 closure Python、`-I -m`、生产 module、binding path，CLI 在同一解释器只解析参数。transient unit 以 verifier-owned product `DynamoDBCurrentHead` 注入实际运行同一服务；停止 accept 后等待已进入 exchange，超时必须报错并保留 Core/store/current socket、禁止第二次 start，排空后重试 close 才清理；正常 stop 清理，SIGKILL 后 socket 不可连接且同根重启取得 holder并清旧 socket | 120 release、121 holder |
| 123-V07 | 通过公开 store seam 持久化且读回合法 synthetic `SourceEnvelope.body`；数据库原始字节及 release/runtime/socket/lifecycle/ordinary roots 无 marker/key/credential，close 不改非目标 sentinel | 110 storage、117 lifecycle、120 secret scan |

## 防假绿

- verifier 独立建立文件、socket、错误 peer、崩溃和 runtime closure oracle，不接受产品自报 `healthy/secure/atomic` 字符串。
- 正向 current-head 对象必须是 `DynamoDBCurrentHead`；其 SDK 边界可使用 verifier-owned deny-network Dynamo client，但不得改用 `InMemoryCurrentHead`。真实 AWS G08 保持 `not-authorized/cannot-confirm`。
- V02/V06 的正式 PASS 只能来自 Linux 内核与 systemd；Windows skip 不能用于闭票。
- staged release 的 truthful unavailable 是正向结果之一，不能替代同一完整 closure 的合法 current activation；也不能代替 V03 的 typed Core receipt 重放、V04 的实际重启/authority 故障或 V06 的真实进程崩溃恢复。
- V03 的 EOF 仅是既有单连接单 request CorePort 客户端的发送半关闭，不改变 response wire；V06 的 digest oracle 由 verifier 从文件表与实际 closure 独立重算，不能相信 binding 自报摘要。
- V06 不接触真实 AWS：正式 launcher 的 exact `ExecStart` 与 CLI parser、以及同一 `ProductionCoreService` 的 systemd 生命周期分别验证。真实 launcher + AWS binding 只在后继获准部署票验收。
- 测试不得 monkeypatch产品私有 helper、读取 SQLite 表断言业务成功、从 source 文本寻找关键词，或建立 test-only bypass。

## 验证命令

编码循环：

```text
python -B -m unittest tests.test_ticket123_production_core_service.Ticket123ProductionCoreServiceTests.test_v123_0N_* -v
```

交审门：

```text
python -B -m unittest tests.test_ticket123_production_core_service -v
python -B -m unittest tests.test_ticket121_host_authority tests.test_ticket122_dynamodb_current_head -v
python -B -m unittest tests.test_ticket117_integration tests.test_ticket118_integration tests.test_ticket120_integration -v
python -B -m unittest discover -s tests -v
python -B -m compileall -q partner_health_steward tests
git diff --check
```

正式 Linux V06 的一般合成 fixture 只可使用随机 `/tmp/ticket123-*`，并使用随机 transient unit 名和合成无正文 fixture；为使 `PrivateTmp=yes` child 可见，verifier 与最小测试闭包必须临时置于唯一 `0700` `/opt/t123v-<8hex>`，其 process root/socket 只可在该目录下短名 `p/r-*/n|c/run/health-core.sock` 中创建。启动 child 前 verifier 必须以 encoded byte length 逐一断言 normal/crash socket 路径均不超过 `90`（Linux `107`-byte 可用上限以下）；过长路径必须在启动产品前失败。V06 child 必须显式继承当前 `TICKET123_RUNTIME_ROOT`；所有 verifier/child Python 调用必须禁止 bytecode 写入，V07 不得通过重生成 manifest 或缩小扫描范围掩盖漂移。开始/结束记录 default/partner service 状态但不重启、不配置、不写入它们。测试完成必须精确清理临时 unit、`/tmp` 目录、`/opt/t123v-*` 闭包和进程。

## 审查与停止

编码前 Spec reviewer 只核对 Ticket 123/ADR/G03-G04 是否覆盖；Standards reviewer 只核对深 Module、三类 CorePort、权威/事务/副作用边界、复杂度上限和 verifier 防假绿。二者对同一 commit/tree PASS 后才冻结。

实施后先跑执行门，再由两个只读 reviewer 只核对冻结落地。只有可复现 P0—P2 且直接破坏 123-V01—V07 或既有回归才阻塞；理论风险、替代架构、未来 Hermes/model/Weixin/AWS 要求不扩入本票。
