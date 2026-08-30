# 123 - 实现生产 health-core 与 CorePort 服务

Type: task
Status: claimed
Parent: [健康管家首发 TO、CAN 与 HOW 决策闭合路线](../map.md)
Blocked by: [121 - 实现主机私有健康密钥与能力权威](121-implement-host-private-health-authorities.md), [122 - 实现 DynamoDB current-head 生产 Provider](122-implement-dynamodb-current-head-provider.md)
Unblocks: [124 - 接通 pinned Hermes 的真实健康入口](124-connect-pinned-hermes-live-health-entry.md), [125 - 实现 Partner 首跳模型与治理知识 Adapter](125-implement-partner-model-and-governed-knowledge-adapter.md)

**What to build:** 用已有 `HealthCore`、`EncryptedStateStore`、Ticket 121 主机权威和 Ticket 122 current-head 构造一个生产组合根，并把三类既有 CorePort 请求通过受限 AF_UNIX socket 暴露给同机 Plugin。组合根同时绑定 Ticket 117 已要求的受管 replica/migration-artifact Adapter 与内容寻址 Python 3.11 依赖闭包；服务是低权限、无普通聊天入口、无模型／微信凭据的 systemd unit。

## Bounded acceptance

- 组合根只接受内容寻址 release 中的当前 admission、七 Skill、状态、知识／安全资产和 Provider；任一缺失、digest 错绑或 staged 资产不满足时服务保持 unavailable。
- AF_UNIX socket 固定 owner/group/mode，验证 peer credential，只允许 Plugin service identity；TCP、其他用户、symlink 路径、宽权限和旧 socket 均拒绝。
- command、managed-read、controlled-effect 三类 v1 framing 映射到现有 HealthPlugin/HealthCore 行为；未知 kind/field、重复 key、非 canonical、截断、尾随和超长 frame 关闭连接且不形成业务事实。
- 重启恢复只读取加密 SQLite 与外部 current head；prepared/finalize、unknown、旧 fence、密钥缺失和 provider 不一致时停止健康写入、模型与外发。
- systemd 启停、崩溃恢复、socket ACL、SQLite 认证加密和 ordinary Session/Memory 无副本边界在隔离 Linux 环境通过 Ticket 119 G03/G04；不得用 `StagedCorePortServer` 或 InMemory Provider 冒充生产健康。
- 运行时必须明确提供并校验 Python `>=3.11,<3.12` 与冻结依赖 hash；不得依赖目标机当前 Python 3.10、在线 pip 或未声明 site-packages。
- lifecycle 的 `managed_replica_adapter` 与 `migration_artifact_adapter` 必须绑定本服务实际受管对象；不能继续注入 Ticket 117 synthetic fake。

## Not in this ticket

不实现 Hermes 消息方法、真实模型／Weixin Adapter、医学审核或激活；不改变三类 CorePort 接口和 HealthCore 业务状态机。

## Delivery discipline

先冻结组合根、进程边界和故障矩阵；冻结门只测试外部行为，不绑定内部类布局。实现、双轴审查、验证通过后普通提交并推送，不部署到 default。

## Pre-code freeze candidate

- Characterization 基线：commit `17851080f9a5df1ad9d15187d1cc7fd93ce4f976`、tree `17bdb993958b171e64d30d5ede63769a5b011478`。
- 当前唯一产品差额：`partner_health_steward.production_core_service` 不存在；当前发布 runtime 仍是统一拒绝的 `StagedCorePortServer`，且没有 production lifecycle 文件 Adapter 或 Python 3.11 dependency closure。
- 冻结实施设计：`../design/123-frozen-implementation-design.md`。
- 冻结验证合同：`../design/123-frozen-verification-contract.md`。
- verifier-owned 门：`../../../tests/test_ticket123_production_core_service.py`。
- 七门只覆盖组合根、AF_UNIX、三类 CorePort、重启/未知、lifecycle 文件 Adapter、systemd/runtime closure 与无副本；不执行真实 AWS、部署、Hermes 消息、模型或微信。
