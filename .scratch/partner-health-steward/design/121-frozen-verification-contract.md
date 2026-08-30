# Ticket 121 冻结验证合同

> 状态：frozen。与 `121-frozen-implementation-design.md` 同属 commit `52d569dc487b3bbc8023a797bd67b70a30cab0cb`、tree `5cfe065de74f6a86696a7a7fc79923d1f28ab8b1` 的编码前 characterization。verifier-owned 文件固定为 `tests/test_ticket121_host_authority.py`；实现 Agent 不得修改三件套。

## 测试边界

测试只通过 `HostPrivateKeyProvider`、`HostPrivateWriterFenceVault`、`HostPrivateExecutionCapabilityVault` 三个公开 Adapter、已有 Interface 和 `HealthCore` 公共行为观察结果。fixture 直接在隔离目录预置三个 32-byte 标准向量，不调用产品 provisioning helper；预期摘要/HMAC 由 verifier 独立 canonical 算法和固定字面向量计算。

不得读取产品私有字段、真实 Hermes 目录、配置、凭据、聊天、健康资料或运行数据库。错误文本、repr 与公共返回递归扫描，不得包含 fixture 原始 secret、绝对 facility path 或健康正文。

## 六门

| Gate | 公共 Seam | 必须证明 |
| --- | --- | --- |
| 121-V01 | `KeyProvider` | 标准向量得到固定 `key_id/get_key`；missing、长度、owner/group/mode、symlink、FIFO、hard-link 和 inode replacement 均在 SQLite 打开前拒绝。 |
| 121-V02 | `WriterFenceVault/Session` | exact namespace 首进程得到符合 frozen fence 格式的 proof；第二进程拒绝；clean release 与真实子进程 crash 后恢复。 |
| 121-V03 | `proof_for` + 122 cross-contract | current exact fence 成功；wrong site、old/ref digest、terminal、master 删除/替换失败；raw capability 不出现在 SQLite/repr/error。 |
| 121-V04 | `ExecutionCapabilityVault/Session` | exact binding 幂等 mint；进程重启 recover 原值；authority/effect/intent/claim/holder/fence 任一变化失败；第二活进程失败。 |
| 121-V05 | key lifecycle | 非 terminal/错 binding 不能 destroy；exact terminal destroy/absence 幂等；writer/execution master 不被误删。 |
| 121-V06 | Linux 机械闭包 | 在随机 `/tmp/ticket121-*` 真实验证 permission、symlink、FIFO、flock、进程 crash 与清理；开始/结束只读服务状态一致，真实 Hermes 目录零接触。 |

V01—V05 可以在 Linux 普通 service uid 的隔离目录运行；owner/group 错配用不会读取内容的 stat case。需要 chown/setuid 的子例与 V06 只能在获准 Linux 环境运行。没有 Python 3.11、不能创建真实 symlink/FIFO/进程锁或无法证明服务未触碰时结论为 `cannot-confirm`，不能 skip 后宣称通过。

编码前动态 import 形成唯一红灯 `1 failure / 5 skips / 0 errors`。编码后同一文件必须 `6/6 PASS`，再运行 Tickets 110/111/117 中既有的 vault unavailable、SQLite copy、old fence、terminal cleanup 与 external-call-zero 回归、全量一次、`compileall` 和 `git diff --check`。这些既有回归而非本 verifier 的新私有 harness 负责证明 `HealthCore` fail-closed。实现后必须核对本设计、本合同和 verifier Git blob 相对冻结 checkpoint 零变化。

本合同不验证 DynamoDB、CorePort server、Hermes、模型、Weixin、医学 bundle 或部署；也不承诺防护已取得 service uid/root 与 host-private facility 的恶意操作者。
