# Ticket 129 冻结验证合同候选

状态：pre-code candidate，尚未冻结。独立 verification authority：implementation_audit。唯一增量设计：`129-host-current-head-design.md`；主人已明确接受的整机快照限制见同链 ADR 0023 与 Evidence 38，测试不重问或伪造域外保证。

## 接口与真实材料

公开 `host_current_head.HostHeadBinding`、`HostSQLiteCurrentHead.bootstrap(binding, initial_head)`、open-existing constructor、九个已有 CurrentHeadPort 方法及 close。测试使用隔离 private 目录里的真实 SQLite 文件、Ticket 121 的真实 HostPrivateWriterFenceVault/public fence/proof、两个独立进程及真实进程死亡；不把 InMemoryCurrentHead、静态 capability 文件或 fake success 注入生产。

Provider 的内部 SQL 表名、codec、行布局和 helper 不作测试隐藏要求。读取原始文件仅验证 capability 不落盘与损坏/替换的失败关闭。合法 overlap 使用现有 Core typed request permit，不新增 wire/durable bool；公开恢复 identity 不含 capability。

## 六个有限门

| Gate / Ticket 验收 | 必须观察的结果 | 独立现实错误 |
|---|---|---|
| 129-V01 / A1 | 普通打开缺失文件不创建；唯一显式 bootstrap 创建 generation1 并读回；既有文件/错误 installation 零覆盖；symlink/hardlink/公开 mode/非 private parent 拒绝。 | 丢文件或坏 namespace 被当作新安装，软链接/权限使 authority 失去唯一性 |
| 129-V02 / A2 | 两个独立进程竞争同一个 expected，只有一个 CAS 成功；live head、exact AppliedTransition 同时成立；错误 operation/失败竞争者无伪 receipt；重开读回一致。 | 只用进程锁或缓存 CAS，head/receipt 分开提交、恢复凭相似 ID 猜测 |
| 129-V03 / A3 | public fence 相等不能替代 capability hash；伪 proof 零推进；新 head 后旧 generation proof/请求拒绝，当前 holder proof 可用。 | 持公开字符串即可写、只验构造时的旧 head |
| 129-V04 / A3–A4 | lease exact acquire/replay/lookup、默认独占；现有受信 overlap 可推进，generation 进步但同 fence 的合法旧 lease 可释放；release digest 冲突拒绝；transfer 轮换到精确预配 target fence，旧 receipt 保留但旧 acquire/release 失去活体权限；active lease 不可越过 terminal。 | 历史 receipt 复活权限、释放门过严卡住合法 overlap、旧 holder 越过 transfer/terminal |
| 129-V05 / A5 | 实际子进程 commit 后、返回业务结果前 SIGKILL，重开靠 exact lookup/readback 恢复；真实 SQLite 写锁导致 typed conflict/timeout且无 receipt；已开文件换 inode及损坏失败关闭，不重新 bootstrap。 | 崩溃后盲重做、锁错误假成功、已替换文件继续作 authority、自动修复坏库 |
| 129-V06 / A6 | 文件/sidecar/错误与日志不保存 writer capability；真实生产 CorePort 组合接受 Host Provider，运行投影准确为 host-sqlite，staged 仍不可写；不伪造 DynamoDB 或域外保证。 | request/proof repr 入库、公开身份硬编码 DynamoDB、用内存对象或阶段探针冒充宿主生产 |

每门按可独立杀死的现实 mutation 取正例和必要等价类，不做字段/故障笛卡尔积。V04 区分 acquire replay（必须 exact live HEAD）与 release（同一 live writer fence 内的合法 overlap 可跨 generation）；不得将这两种 currentness 混成一项。

## 命令、环境与停止

```text
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest tests.test_ticket129_host_current_head -v
```

V01–V05 为普通 Linux 离线门；V06 的生产组合 tracer 要求 Ticket 123 既有完整 Python 3.11 runtime，通过隔离 bootstrap 只提供仓库 tests，产品必须从该 runtime 的 site-packages 导入，并设置 TICKET123_RUNTIME_ROOT。缺环境是未验证，不能 skip 或浅层 inspect 代替。产品尚不存在时六门均必须明确 prerequisite failure，0 error/skip。

回归保持 110/115/117/121/122/123 原合同和受影响生产装配；旧 DynamoDB 测试不为此 Provider 放宽。真实部署/provisioning/当前受管数据删除/迁移、模型、微信及主人验收属于同一后继上线链，不随此门自动发生。

整机旧快照同时恢复 head、健康库和秘密时仍可能复活旧状态，这是主人已经接受的边界。V05 仅证明正常崩溃与当前文件恢复，任何绿灯都不得写成域外防回滚、自动识别旧 VM 或真实备份已 purge。ADR 与部署证据继续拥有该限制，不创建第二产品状态。

编码前须对同一 commit/tree 完成 fresh-context Spec/Standards 预审并记录设计/合同/verifier blobs，之后才冻结与实施。实施者不修改 verifier。未覆盖但可复现的既有验收问题交回本 verification authority，形成新 checkpoint，不能静默扩门或放宽产品。
