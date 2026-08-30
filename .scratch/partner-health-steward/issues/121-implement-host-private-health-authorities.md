# 121 - 实现主机私有健康密钥与能力权威

Type: task
Status: resolved
Parent: [健康管家首发 TO、CAN 与 HOW 决策闭合路线](../map.md)
Builds on: Ticket 120 staged release evidence at `777cc585bbda3e13385b73b9146c0d8f948838d1`
Unblocks: [123 - 实现生产 health-core 与 CorePort 服务](123-implement-production-health-core-and-coreport-service.md)

**What to build:** 在 ADR 0022 既定主机边界内，为 `KeyProvider`、`WriterFenceVault` 和 `ExecutionCapabilityVault` 提供 Linux 生产实现；同一 `HostPrivateKeyProvider` 还必须闭合 Ticket 117 已消费的 `destroy/absence` 数据密钥角色。它们只向当前低权限 `health-core` 进程提供最小能力；原始密钥和 capability 不进入 SQLite、日志、CorePort、Hermes 配置或 Git。

## Bounded acceptance

- 专用数据密钥由 root 预置的 host-private facility 提供，文件／handle 身份、owner、mode、symlink 和缺失状态在打开 SQLite 前验证；不得从普通环境变量、Hermes Session/Memory 或仓库读取。
- writer holder 在同一 installation/site 上排他；进程崩溃后可按既有 recovery binding 恢复，第二活实例不能取得 proof。
- execution completion capability 绑定当前 authority、writer proof 与 exact effect；重启可恢复原能力，复制数据库、旧 fence 或另一个进程不能恢复。
- 密钥、vault、权限或当前性不可确认时，Core 只能报告 unavailable/cannot-confirm，健康写入、模型和外发调用均为零。
- 使用临时 Linux 用户／目录和合成无正文数据验证重启、并发、权限、symlink、copy、revocation 与 crash recovery；不得触碰 default/partner 的真实健康目录。
- public writer-fence ref 严格使用冻结设计的 v1 epoch + nonce + capability digest 规则，与 Ticket 122 交叉验证；每次 bootstrap/transfer 的唯一 operation ref 通过目标设施 `prepare_fence_ref` 预生成目标 ref，回迁不得复活旧 fence。
- terminal 删除只把 exact installation 的数据密钥原子替换为非秘密 tombstone，`destroy/absence` 跨崩溃可恢复且不顺带删除 writer/execution master；非 terminal 或错 binding 请求拒绝。

## Not in this ticket

- 不实现 DynamoDB、CorePort server、Hermes 配置、模型、Weixin、医学 bundle 或部署。
- 不改变现有 Protocol 或 HealthCore 状态机；若现有 Interface 无法承载生产实现，先以可复现证据停止，不在本票换架构。

## Delivery discipline

编码前按 `docs/agents/architecture-governance.md` 完成 characterization、单一冻结设计和独立验证合同。冻结后只实现上述三个 Adapter；审查只判断冻结门是否落地。通过后普通提交并推送当前任务分支，不修改 main、不标记下游票完成。

## Frozen pre-code artifacts

- 冻结 checkpoint：commit `8de120d447c53848af2afbc9fce71a2afa71a642`、tree `0007c31f95a6712e2fefca1ff16790b53bee2da8`。
- 双轴共同审查内容点：commit `60121ea635b8cedc09556163bc9a6a6cb7294078`、tree `bcc4566d517155b720b28b5a8eb929bd8b6ddb3b`；Spec reviewer `PASS`，Standards reviewer `PASS`。
- Linux 首跑发现 verifier 外层字符串提前生成 NUL；verification authority 只修复源字符转义，未改变 Gate、产品输入或断言。修订内容点：commit `cfe3a58a1fadb9c1a9dd0639c15d1d7c0d9369fa`、tree `919e47a19f3ebda4caf8d3aab3737070ad3721df`；修订记录 checkpoint：commit `2878406f8f1e5178e10dbaf529c12870347d3f84`、tree `53d804735caa05e8369b38f951539970b0d93c76`。
- 实施设计：`../design/121-frozen-implementation-design.md`
- 独立验证合同：`../design/121-frozen-verification-contract.md`
- verifier-owned 门：`../../../tests/test_ticket121_host_authority.py`
- 当前冻结 blob：design `e6b1a132d99c38748cd91b897e75286f5fe951f1`；contract `1f969ce5fca374a0e9c3eceacb1f9c6ccb696ddf`；verifier `8760ee9dcd04a85fdf9cfe3a6db4e4195db32347`。原 verifier blob `cb8e383577b4ad62a35c05edc11e1bfd2a9faf22` 已被机械修订取代。
- 编码前机械结果：`1 failure / 5 skips / 0 errors`；唯一红灯为 `partner_health_steward.host_authority` 尚不存在。
- 实现 Agent 不得修改上述三件套；若需改变既有 Interface、共享 fence 合同或增加 capability ledger，按停止规则返回，不自行扩票。

## Answer

Ticket 121 已按冻结设计实现并通过独立双轴审查，可供 Ticket 123 组合使用。

- 产品实现：`partner_health_steward/host_authority.py`，实施提交 `edd8eea2183cc255bc489411df4540f01daf7a88`。
- Linux 正式冻结门：使用仅位于 `/tmp/ticket121-*` 的临时 CPython 3.11.16，在 default Hermes 主机完成 `6/6 PASS`；临时目录随后精确删除，default/partner 服务前后均保持 `active/enabled`，未修改服务或真实健康目录。
- 回归与审查：相关回归 `190/190 PASS`；最终 Spec 与 Standards 有界复核均为 `PASS`，没有阻塞 finding。
- 本票只证明主机私有权威 Adapter；CorePort、Hermes 接线与真实外部效果仍由后继 Tickets 验收。
