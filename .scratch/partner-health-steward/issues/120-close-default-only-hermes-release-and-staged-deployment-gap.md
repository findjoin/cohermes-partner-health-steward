# 120 - 闭合 default-only Hermes 真实发布与 staged 部署缺口

Type: task
Status: claimed
Parent: [健康管家首发 TO、CAN 与 HOW 决策闭合路线](../map.md)
Unblocks: Ticket 119 的 target-local G10 前置；不改写 Ticket 119 状态或 gate。

**What to build:** 从当前已实现的健康管家源码生成真实、版本化且内容寻址的 Hermes 发布目录，并提供一个仅允许 default Hermes 的目标本地 staged 安装门。发布物必须包含可由 Hermes 发现的 `health_weixin` Plugin、七个冻结职责的 Skill 资产、已有 release 声明所需的 bundle/schema/environment 资产，以及不伪造健康可用性的 CorePort staged runtime。安装只允许 `/root/.hermes` 与 `hermes-gateway.service`；Partner profile、任何其他 profile 或 service 必须在发生任何写入前拒绝。

## Scope and hard boundaries

- 复用 Tickets 110—119 的 HealthCore、HostReleaseContract、CorePort 三类语义和 staged 语义；不改写它们的业务目标、状态、冻结设计、冻结验证合同或 verifier-owned 测试。
- 当前仓库没有 `CurrentHeadPort`、writer-fence vault 或 execution-capability vault 的非 synthetic 生产实现。120 不得用内存替身伪造这些权威；发布的 CorePort runtime 只能在缺少外部注入时明确拒绝健康操作并保持 staged。
- default 实际安装是 Ticket 119 的 `119-G10` target-local 运维动作。本主任务的明确 default-only 授权只可在代码/审查通过后转换为 root-owned、`0600`、一次性短期 `DeploymentPermit`：它精确绑定 release digest、run、G10、default target 与 expiry，digest 是 opaque `approval_ref`。它不是健康业务授权、产品批准或通用 ledger；错误/过期/撤回/已消费 permit 必须零部署写入。
- symlink/non-regular release closure 仍是硬门：Windows 仅运行 V01—V06；V07 在 Linux target 的随机 `/tmp/ticket120-v07-*` isolated directory 真实创建 symlink/FIFO 证明 pre-write rejection。只有同 Git tree/verifier blob/run/release digest 的分平台证据才可聚合，过程中零触碰 Hermes root、partner profile 或服务。
- 120 不读取、复制或保存聊天、健康资料、联系人、凭据、Token、配置值或运行数据库；不启用真实模型、Weixin、主人、联系人或健康处理。
- 120 不修改 Map、main 或 Tickets 110—119，不标记任何票 resolved，也不建立通用部署框架、第二 current-head、第二健康状态或激活账本。
- 真实目标操作只在冻结门、实施双轴审查均通过后进行；本票唯一获准目标是 default `/root/.hermes` + `hermes-gateway.service`，且只可备份、staged 安装、重启该 service、检查与回滚。

## Frozen pre-code evidence

- Baseline commit: `4b90a4fe22d2d4acf674d76c732a9de765f03079`; tree: `c855edb43240882ac69008dcd08eac6db1a208b8`.
- Ticket 118 的 `HostReleaseContract` 与 Ticket 119 的 `AcceptanceRunContract` 均存在；仓库没有真实 `plugin.yaml`、七个发布 Skill、内容寻址发布目录、CorePort server 或 default-only 安装/备份/回滚入口。
- `partner_health_steward.hermes_host.register(ctx)` 已符合 pinned Hermes 的 `ctx.register_platform` 入口，但它是严格 CorePort client；现有 socket runtime 只在 Ticket 118 verifier 的临时 synthetic oracle 中存在。
- Pinned Hermes `3c27eb6234bf91b8ceee9e9071591b31e9b148cb` 的用户 Plugin 目录为 `~/.hermes/plugins/<name>/`，要求 `plugin.yaml` 与 `__init__.py`，由 `register(ctx)` 接入 platform registry。
- 当前非测试 `CurrentHeadPort` / writer-fence vault / execution-capability vault 均不存在；仅有标为 synthetic 的内存实现。因此 120 的唯一合法默认运行态是插件可发现、CorePort runtime 可部署但拒绝健康请求、health 仍 staged。任何要形成健康权威或 activation proof 的实现都超出本票并必须停止。

## Frozen artifacts

- [冻结实施设计](../design/120-frozen-implementation-design.md)
- [冻结验证合同](../design/120-frozen-verification-contract.md)
- `tests/test_ticket120_integration.py`（verifier-owned）
