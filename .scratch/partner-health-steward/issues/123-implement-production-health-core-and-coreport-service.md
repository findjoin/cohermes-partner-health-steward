# 123 - 实现生产 health-core 与 CorePort 服务

Type: task
Status: resolved
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

## Frozen implementation authority

### 历史编码前 authority（保留为历史，不是当前验收权威）

以下内容是原始编码前冻结：

- 经审查内容提交：`5711af79414cc051c684f4521f31ee5a8051eccf`；tree：`70077046c1b5642142daff0c9e5afb29ad5c8000`。
- 冻结实施设计 blob：`f464be479f51a0d03d9cf33e964bcd2e7d190e03`。
- 冻结验证合同 blob：`ec2b03b8a8d71b0cc182b878da39d1907ec9c5f0`。
- verifier-owned 测试 blob：`be32fb3b70ae0c2dadb7b3ec535ec551694680e6`。
- 编码前机械门：`Ran 7 tests`，结果为 `1 failure / 6 skips / 0 errors`；唯一根失败是 `partner_health_steward.production_core_service` 尚不存在，符合冻结合同。
- 受影响既有回归：Ticket 122 与 Ticket 120 共 `14/14 OK`（另有一个按既有环境条件跳过）；`compileall` 与 `git diff --check` 通过。
- 新鲜 Spec 预审：PASS；新鲜 Standards 预审：PASS。两轴审查均针对上述同一 commit/tree，且未修改文件。

### 历史 verification-authority refreeze（`b41b678`，不是当前验收权威）

- 普通 refreeze 提交：本段与其 verifier/合同一并提交的 `fix(ticket-123-verifier): refreeze review findings`；提交 SHA 以该提交本身为准。
- 冻结实施设计 blob 保持：`f464be479f51a0d03d9cf33e964bcd2e7d190e03`（零修改）。
- 冻结验证合同 blob：`5dfa7c8fa32d81c79507a85433c98dd7d25cc01f`。
- 当前 verifier-owned 测试：`../../../tests/test_ticket123_production_core_service.py`；blob `7aec1af838e0cf67e23dda79bbf78da9af149214`。
- 只补入独立双轴审查原始 finding 的 V01 current release、V03 request-side EOF/延迟 tail、V06 canonical closure/release binding 与 V06 close drain 等价类；仍为七门，不增加产品目标、架构、CorePort wire 或 Tickets 110—122 状态机。

### 历史 verification-authority checkpoint（`26fa1d4`）

- 普通 refreeze 提交：`26fa1d4` 的 `fix(ticket-123-verifier): extend V06 drain observation`。
- 冻结实施设计 blob 保持：`f464be479f51a0d03d9cf33e964bcd2e7d190e03`（零修改）。
- 历史冻结验证合同 blob：`49b8fba41b5a7331dcfa49b4c2aa6f364fa14a42`。
- 历史 verifier-owned 测试 blob：`b31ffd31c56e9bc4e29e13f35e806d113f105304`。
- 唯一增量是 V06 blocked-exchange observer 的 5 秒读取窗口，明确大于产品既有 2 秒 drain timeout；不改产品 drain timeout、断言、Gate 数量或其他测试。

### 历史 frozen verification authority（`aceb6fd` handoff）

- 内容冻结提交：`9fe4bff88e07a47a9656b3b1bd556da6b103e452`；tree：`4a73a52d18daf02b31ea5355600640abfac78be8`。它冻结经独立 Spec PASS 与 Standards PASS 的 candidate `930113ddde1a8a2d95ee2e1cff857cc427a25237` 内容。
- 冻结实施设计 blob 保持：`f464be479f51a0d03d9cf33e964bcd2e7d190e03`（零修改）。
- 当前冻结验证合同：`../design/123-frozen-verification-contract.md`；blob `77962b5a14b8457097ab4fb6bd5ef996369c38fd`。
- 当前 verifier-owned 测试：`../../../tests/test_ticket123_production_core_service.py`；blob `11e6da49a117338bef8a3f86acbdabe7d42ea68f`。
- Linux 编码前形状为 V01–V05/V07 `6 PASS / 0 skip / 0 error`，V06 `1 expected FAIL / 0 error / 0 skip`；唯一红灯是 `HermesReleasePublisher.publish_current_successor` 尚未实现。
- 实施只允许关闭上述 current-successor runtime-closure attestation 红门：在 Ticket 120 `HermesReleasePublisher` 增加该唯一窄公开入口，并使 Ticket 123 按冻结合同验证其 release-owned attestation；不得改写冻结设计、verifier、Gate 数量、Ticket 状态或其他业务范围。

### 历史 mechanical refreeze candidate（`fcb1d42`，已通过双轴预审）

- 候选仅修正 V06 `--runtime-attestation-tamper` launcher 的第三个 argv 从 `str` 到 `Path` 的类型转换，使既有 `_run_runtime_attestation_tamper(..., Path)` 读取路径可执行；不改变 Gate、断言、fixture 或产品语义。
- 候选 contract blob：`0393b6cc21221cacf942a49b7a85fea92d81b573`；verifier blob：`ccb534abe36d3b5eab11a585b753bb3cfacdf1b3`；冻结设计保持 `f464be479f51a0d03d9cf33e964bcd2e7d190e03`。独立 Spec 与 Standards 均为 PASS，随后由内容冻结 `22c6a1194c8ca68bad04c22f21f99331ba8ae53a` 取代其 candidate 身份。

### 当前唯一 frozen verification authority

- 内容冻结提交：`22c6a1194c8ca68bad04c22f21f99331ba8ae53a`；tree：`10b4c82ae4cd007637f387dee7cc71f94dca5584`。它冻结已通过独立 Spec PASS 与 Standards PASS 的 mechanical candidate `fcb1d42d547c86f7257f1195f2b4cd98c8e35016`。
- 冻结实施设计 blob 保持：`f464be479f51a0d03d9cf33e964bcd2e7d190e03`（零修改）。
- 当前冻结验证合同：`../design/123-frozen-verification-contract.md`；blob `274bd672a7996cfa18c507d8e904f5a727a63aaf`。
- 当前 verifier-owned 测试：`../../../tests/test_ticket123_production_core_service.py`；blob `ccb534abe36d3b5eab11a585b753bb3cfacdf1b3`。
- Linux 编码前形状为 V01–V05/V07 `6 PASS / 0 skip / 0 error`，V06 `1 expected FAIL / 0 error / 0 skip`；唯一红灯仍是 `HermesReleasePublisher.publish_current_successor` 尚未实现。
- 实施只允许关闭 current-successor runtime-closure attestation 红门：在 Ticket 120 `HermesReleasePublisher` 增加该唯一窄公开入口，并使 Ticket 123 按冻结合同验证其 release-owned attestation；不得改写冻结设计、verifier、Gate 数量、Ticket 状态或其他业务范围。

实施停止规则：冻结测试若与冻结设计自相矛盾，或实现必须改写 Tickets 110—122 的业务状态机、三类 CorePort wire、引入第二 current-head/ledger/database、访问真实 AWS/Hermes/模型/微信或执行部署，立即停止并报告一个具体阻断。正常实施完成后运行七门及受影响回归，创建普通提交并普通推送，报告 commit/tree 与逐门证据；在独立完成审查前，Ticket 保持 `claimed`。

## Answer

Ticket 123 已完成并经最终定向 Spec/Standards 双轴审查 PASS（0 个阻塞项）。本票仅交付生产 `HealthCore` 组合根、受限 AF_UNIX `CorePort` 与 lifecycle 接缝、固定 Python 3.11 runtime 闭包，以及 release-owned runtime-closure attestation；不代表 Hermes 消息接通、真实模型或 Weixin Adapter、部署或主人验收已完成。

- 最终产品提交：`76bb054f8281e2edd5e75d51767e192d20fecd28`；tree：`83b1d401ff2287fe05c9ab1933140f4fb56a1f91`。
- 最终冻结权威：metadata `431ffe68775403ced3cde6e986e77d1b1e4106af`，内容冻结 `22c6a1194c8ca68bad04c22f21f99331ba8ae53a`；design `f464be479f51a0d03d9cf33e964bcd2e7d190e03`、contract `274bd672a7996cfa18c507d8e904f5a727a63aaf`、verifier `ccb534abe36d3b5eab11a585b753bb3cfacdf1b3` 均保持冻结内容。
- 验证：普通回归 `1 PASS`；default Linux V123 `7/7 PASS`；Ticket 121/122 `7 PASS + 6 platform skip`；Ticket 117/118/120 `22 PASS + 1 Linux-only skip`；项目全量 `757 PASS + 14 platform skip`，均为 `0 failure/error`；`compileall` 与 `git diff --check` 均 PASS。
- 运行边界：临时验证根与 transient units 均已清理；default/partner 服务前后均为 `inactive`；系统 Python 保持 `3.10.12`，专用 Python `3.11.16` runtime 保留且未改动。
- Ticket 124 与 Ticket 125 现在可将本票的生产组合根视为已满足的前置依赖；其各自入口、Adapter、部署和验收范围仍未解决。
