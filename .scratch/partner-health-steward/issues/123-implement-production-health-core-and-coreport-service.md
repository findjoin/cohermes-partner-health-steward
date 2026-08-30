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

### 当前唯一 verification-authority checkpoint（`26fa1d4`）

- 普通 refreeze 提交：`26fa1d4` 的 `fix(ticket-123-verifier): extend V06 drain observation`。
- 在后续 candidate 完成独立双轴预审 PASS 前，本段是唯一当前执行验收权威；不存在并列的 candidate authority。
- 冻结实施设计 blob 保持：`f464be479f51a0d03d9cf33e964bcd2e7d190e03`（零修改）。
- 当前冻结验证合同 blob：`49b8fba41b5a7331dcfa49b4c2aa6f364fa14a42`。
- 当前 verifier-owned 测试 blob：`b31ffd31c56e9bc4e29e13f35e806d113f105304`。
- 唯一增量是 V06 blocked-exchange observer 的 5 秒读取窗口，明确大于产品既有 2 秒 drain timeout；不改产品 drain timeout、断言、Gate 数量或其他测试。

### 提议 verification-authority refreeze candidate（非权威，待独立双轴预审）

- 普通 candidate 提交：本段、冻结验证合同与 verifier 一并提交；它只记录待审提议，在独立双轴预审 PASS 前不替代上段唯一当前 checkpoint。
- 冻结实施设计 blob 保持：`f464be479f51a0d03d9cf33e964bcd2e7d190e03`（零修改）。
- candidate 冻结验证合同：`../design/123-frozen-verification-contract.md`；blob `1246c89c051ea75d1de67ebaf597c714a9e00a2b`。
- candidate verifier-owned 测试：`../../../tests/test_ticket123_production_core_service.py`；blob `11e6da49a117338bef8a3f86acbdabe7d42ea68f`。
- 唯一增量是 V06 的完整 runtime-closure attestation：attestation 是已验证 release `files` 中的 content-addressed artifact，不反写最终 release digest；完整 runtime 重新计算后必须与其 expected closure digest 精确相等。staged release 仍 truthful unavailable，只有带该 attestation 的 current successor 才可激活。
- V06 新增一个等价负例：篡改未被旧四项映射覆盖的 `production_core_service.py`，并同步更新 runtime file hash、closure digest 与 binding、但保持 release-owned attestation/release 不变时，服务必须在 socket/Core/分派前拒绝；正例验证同一 attestation 对应的完整 runtime 可启动。该门只约束已验证 release 与 runtime 两个信任域的绑定，不对可改写 release root 的 root/SSH 主体作防御承诺。
- 实施最小 seam 仅允许 Ticket 120 publisher 增加由已验证 runtime manifest 形成 current successor 的单一窄入口，或语义等价入口；禁止第二发布系统、审批账本、自动部署框架或通用 attestation registry。

实施停止规则：冻结测试若与冻结设计自相矛盾，或实现必须改写 Tickets 110—122 的业务状态机、三类 CorePort wire、引入第二 current-head/ledger/database、访问真实 AWS/Hermes/模型/微信或执行部署，立即停止并报告一个具体阻断。正常实施完成后运行七门及受影响回归，创建普通提交并普通推送，报告 commit/tree 与逐门证据；Ticket 保持 `claimed`，等待独立完成审查。
