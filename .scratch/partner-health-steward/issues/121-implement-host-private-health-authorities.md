# 121 - 实现主机私有健康密钥与能力权威

Type: task
Status: ready-for-agent
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

- 实施设计：`../design/121-frozen-implementation-design.md`
- 独立验证合同：`../design/121-frozen-verification-contract.md`
- verifier-owned 门：`../../../tests/test_ticket121_host_authority.py`
- 编码前机械结果：`1 failure / 5 skips / 0 errors`；唯一红灯为 `partner_health_steward.host_authority` 尚不存在。
- 实现 Agent 不得修改上述三件套；若需改变既有 Interface、共享 fence 合同或增加 capability ledger，按停止规则返回，不自行扩票。
