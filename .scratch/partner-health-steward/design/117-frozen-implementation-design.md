# Ticket 117 增量架构冻结设计

> 状态：frozen。当前冻结内容 checkpoint 为 `d671d7b5440e58168698a71f9314d05fdbbac7c8`，tree 为 `4ae2eda4ad13218c595649f0c3905312a9b9a924`；fresh-context Spec 与 Standards 编码前预审均 PASS。该 checkpoint 只修正 V01 的合法 active-scope 测试前置，架构内容相对首次冻结点不变。characterization 产品基线为 `63a6a2333e0a7584aa51492035d3b4ca981d40c0`，tree 为 `b90a610efa7fc4597c90dd95193ca694d0998573`。本设计只冻结 Ticket 117 的难逆增量决定，适用 [`AI 编码架构治理`](../../../docs/agents/architecture-governance.md)。

## 目标与非目标

在 Tickets 110—116 已验收的 Plugin/core 上增加一个受管生命周期 Module，使永久删除和计划迁移共享同一 freeze、generation、semantic registry 与 current-head 恢复边界。删除必须防旧快照复活；迁移必须在一次 writer-fence CAS 后只留下一个可写实例。

本票不执行真实删除、真实密钥销毁、真实备份或旧 VM 清理、真实 DynamoDB 转移或生产迁移；不召回站外已交付内容，不支持源丢失后的灾难恢复，不增加第二主人确认、第二数据库、第二 current head、第二 outbox 或第二业务状态权威。真实 Provider 绑定和生产证据留给 Ticket 119。

## Characterization 与保留架构

- 当前全量基线 `720/720` 通过；Tickets 110—116 的健康命令、受控效果、bounded managed read、prepared → CAS/readback → finalize、writer-fence proof、execution lease、terminal observation latch、任务、诊断和分层投递均保留。
- `HealthPlugin.health_operation(...)` 已是受管 semantic command Seam；`controlled_effect(...)` 和 bounded managed read 是另外两类稳定 Interface。117 不建立第四类业务 Interface。
- `CurrentHeadPort` 当前只能普通 revision advance；`AppliedTransition` 明确拒绝 terminal、site 和 fence 变化。`InMemoryCurrentHead.mark_terminal()` 没有 writer proof、operation digest 或 exact lookup，只是既有低层测试辅助，不能作为产品删除协议。
- 当前 store 的 integrity manifest 证明物理行完整性，但没有覆盖全部 Tickets 110—116 语义对象、派生副本、清理规则和迁移等价关系的版本化 semantic registry。
- 当前 `KeyProvider` 没有 destroy/readback；代码也没有删除/迁移编排、目标离线验证或 writer-fence transfer。

因此本票只补四项可定位差额：一个生命周期 Module、一份 semantic registry、一个 typed lifecycle current-head transition、三个外部 Adapter 角色。没有 characterization 证据的现有 Module 不重写。

## 唯一增量架构

```text
HealthPlugin
  ├─ health_operation("lifecycle.execute", tagged request)
  ├─ existing controlled_effect（仅删除前一次不可召回说明）
  └─ managed_lifecycle_read(operation_ref)
          │
          ▼
HealthCore（唯一裁决、唯一写入、既有 lifecycle lock）
          │
          ▼
LifecycleCoordinator（一个深的内部 Module）
  ├─ immutable SemanticRegistry
  ├─ existing encrypted state + prepare/CAS/finalize
  ├─ CurrentHeadPort lifecycle transition
  ├─ DestroyableKeyAdapter
  ├─ ManagedReplicaAdapter
  └─ MigrationArtifactAdapter
```

### 冻结的公共 Seam

1. 复用 `HealthPlugin.health_operation(...)`，只新增 action `lifecycle.execute`。payload 是严格 tagged union：
   - `delete-all`：`operation_ref`、绑定当前主人命令的 `owner_command_ref`、精确语义 `permanent-delete-all-health-data`；owner/generation/scope/causal identity 继续只来自现有 trusted context。
   - `prepare-migration`：`operation_ref`、`target_site`、`target_writer_fence_ref`、`artifact_sink_ref`；只允许当前源 writer 的受管迁移 scope。
   - `accept-migration`：`operation_ref`、`package_ref`、`manifest_digest`；只在目标 offline 模式验证并暂存，不取得写入、模型或发送权。
   - 同一 `operation_ref` 与 causal identity 的重入只恢复原决定；caller 不能提交 phase、terminal、current site 或 writer-fence 成功事实。
2. 删除前的“一次站外不可召回说明”只复用 Ticket 115 已有 owner-delivery controlled effect。它在 freeze 前形成并最多尝试一次；accepted、rejected 或 unknown 都结束该说明尝试，运行时以同一 operation 自动续做，不索取第二次主人确认。freeze 后不允许任何外部效果例外。
3. 新增同属 bounded managed read 的 `managed_lifecycle_read(operation_ref | None)`，只返回无健康正文的 mode、phase、authority binding、manifest ref/digest、目标 offline/active、reason code 和逐项 `remains_unproven`。它不返回表名、密钥、snapshot 正文、Provider 凭据或私有清理步骤。

公开结果只区分 `notice-pending`、`manifest-ready`、`completed`、`replayed`、`rejected`、`unknown`；内部阶段不能由 caller 选择。

HealthCore 构造期只增加一个不可变 `lifecycle_config` Mapping，注入 release/semantic registry、三个 Adapter 角色与 `source | offline-staging` 模式。它只是装配边界，不是第四类业务 Interface，不含业务方法、健康正文、秘密或可变阶段；内部可立即解析为实现自选的强类型配置。

### Module 职责与权威

- `LifecycleCoordinator` 独占删除/迁移阶段、freeze、manifest、terminal/transfer 请求、unknown 恢复、key/purge 顺序和完成投影；它没有独立线程、入口、数据库或发送权。
- terminal confirmed 后普通 HealthCore Interface 已永久关闭；同一 LifecycleCoordinator 的 body-free cleanup runner 只凭 terminal current-head、installation namespace、release registry 与 Adapter readback 续做销钥/清理。它不能重开或解密健康状态，`managed_lifecycle_read` 的 terminal 后视图也只能由这些无正文事实派生。
- HealthCore 仍是唯一业务裁决和写入者；所有 lifecycle 事实写入同一加密状态域并复用既有 prepared → CAS/readback → finalize。允许增加同库 lifecycle 记录，但不得复制画像、任务、投递或诊断为第二份状态。
- 一份不可变、版本化 `SemanticRegistry` 同时服务 migration snapshot、语义等价和 terminal purge。它声明语义 object family、snapshot codec、purge/absence hook、来源连续性规则和 Provider binding；它不保存对象当前值。
- registry 必须覆盖 authority/receipt/guard、初始化、来源、画像、证据、权利、设置、控制、批准、任务、复盘、模型、诊断、安全、联系人、状态、outbox、投递、unknown、删除和迁移暂存。store 的实际受管 inventory、registry exact set 和 configured Adapter set 不一致即失败关闭；新增受管对象未登记必须使 probe、健康读写、模型、任务和外发不可用。
- 现有 physical integrity manifest 继续证明存储行完整性；SemanticRegistry 在其上提供语义枚举，不在本票整体替换 storage integrity 或重写旧 schema 迁移链。

### Current-head 增量

保留现有 `conditional_advance` 和历史 receipt。`CurrentHeadPort` 只增加一组内部 Interface：

```text
conditional_lifecycle_transition(request)
lookup_lifecycle_transition(identity)
```

request 是严格 tagged union `terminal-delete | writer-transfer`，统一绑定 expected authority、operation/transition identity、operation digest、frozen revision digest 和当前 writer proof；transfer 另外绑定 target site、target fence reference 与 verified manifest digest。Adapter 不接收健康正文或目标私密 capability。

- terminal transition 只把当前 installation 推进到不可逆 terminal generation；已存在 active execution lease 时拒绝。
- transfer transition 一次推进 generation 并轮换 site/fence；目标 capability 由 Adapter 的受管配置绑定，不能由 request 携带或由源端复制。
- response unknown 只允许 `lookup_lifecycle_transition(identity)`；禁止第二次 mutable call、换 causal ID 或猜测结果。
- terminal/transfer 已确认后，旧 generation、旧 site、旧 VM 和旧 fence 继续被现有 read/write/model/effect 门拒绝。

### 三个 Adapter 角色

- `DestroyableKeyAdapter`：对 exact installation/terminal generation/operation 执行幂等 destroy 与 absence readback。没有 terminal-confirmed proof 时必须拒绝。
- `ManagedReplicaAdapter`：枚举并幂等清理 configured synthetic primary state、index、export、backup 和 staging，再 live 证明不存在；无业务写权，未绑定的真实 Provider 只能进入 `remains_unproven`。
- `MigrationArtifactAdapter`：保存加密临时 package、离线读取和清理；package 不是 current truth，不能激活目标。临时目录 fake 与未来生产 Adapter 共用此 Seam。

一个具体 Adapter 可以同时满足 migration artifact 与 managed replica 两个角色，但角色 Interface 和权限不合并；不得因此保存第二份 current 状态。

manifest/hash/secret scan/semantic comparator 是 in-process Implementation，不新增 Adapter。current head 是既有 remote-owned Port；真实 key/backup/cloud 是 true external，本票只用 synthetic/fake Adapter。

## 冻结协议

### 永久删除

1. 仅 current owner、current generation、精确 delete-all 语义和 `lifecycle:delete` scope 可登记 operation；暂停、停止记录、取消、撤回或“关闭但保留”零状态变化。
2. 同一决定先形成一次不可召回说明 intent；其一次终态尝试后，运行时以完全相同 operation/causal identity 自动续做。
3. HealthCore lifecycle lock 排空已准入操作，把 freeze 与 current-head revision 原子提交。freeze 后所有健康读取、写入、任务推进、模型、outbox claim 和外发关闭；已在途效果只能结算原 attempt，不能重做。
4. LifecycleCoordinator 发起 terminal lifecycle CAS。conflict 明确失败但保持 frozen；unknown 只 exact lookup，且不销毁 key、不 purge、不宣称完成。
5. terminal confirmed 后先 destroy synthetic key，再按 registry raw-purge 本地和 configured fake Provider，并逐项 absence readback。任何一步未知只得到 `terminal-confirmed-cleanup-pending`/`unknown`，健康永不重开。
6. 清理不保存“审计例外”或第二 ledger。重启只根据 terminal current head、installation namespace、release registry 与 Adapter 的幂等 destroy/purge/readback继续清理。
7. 全部 configured synthetic binding 已证明不存在才返回 `completed`；真实未绑定项逐项报告 `remains_unproven`。
8. 后续主动初始化必须使用全新 installation/current-head resource/key 和空白状态；旧 terminal resource 不可改回 active，旧 snapshot/package/key 不可成为 current。

### writer-fence 迁移

1. 源端在同一 lifecycle lock 下提交 freeze；随后从同一 finalized revision 和 registry 生成加密 semantic package/manifest。
2. manifest 绑定 release、Plugin/core/七 Skills、adapter/model interface、knowledge/safety/diagnostic bundle、Hermes artifact/patch、schema、所有 semantic state、source identity/time、unknown/replay relationship、current-head/observer identity及逐项 hash；秘密只保留 requirement/reference，secret scan 失败即拒绝。
3. 目标 Core 以 offline-staging mode 构造；除精确的 `accept-migration` 与 bounded lifecycle read 外，健康读取、写入、模型、任务和外发全部关闭。它校验 manifest、key reference、route/consent、bundle、semantic exact set/equivalence 和 source authority，并写不可见 staged import；验证不完整没有部分启用。
4. 源端只消费目标验证 receipt 发起一次 writer-transfer CAS。conflict 保持源 frozen、目标 offline；unknown 时两端关闭并只 exact lookup。
5. confirmed 后目标读到自己的新 generation/site/fence 并持有新 writer proof 才 finalize/active；源端、旧 VM 和旧 fence立即失去读写、模型和发送资格。
6. attempted/possibly-sent/unknown effect 原样迁移为 frozen unknown，不进入可重放队列；来源身份、发生时间和历史因果关系不改写。

迁移 freeze 后不增加隐式 abort/unfreeze 路线。若产品以后需要取消迁移，另开 Ticket 决定其语义，不能由编码 Agent补入本票。

## 核心不变量与现实故障

| 验收 | 冻结不变量与必须控制的现实故障 |
|---|---|
| 117-A1 | freeze revision 先完成；并发/in-flight、任务、模型、claim/send、重启不能绕过。 |
| 117-A2 | terminal confirmed 前绝不毁钥/清理；之后 key → registry purge → absence，漏对象或 Provider unknown 不冒充完成。 |
| 117-A3 | terminal response loss 只查原 transition；新 CAS、提前不可逆步骤和“unknown=成功/失败”均禁止。 |
| 117-A4 | 新初始化使用新 installation/head/key；旧 DB、manifest、ID collision 和旧 key 均不能复活。 |
| 117-A5 | registry/manifest exact-set、hash、version 与 secret policy 全部成立；缺项、多项、未知类型和 drift 失败关闭。 |
| 117-A6 | 目标离线全验后仅一次 transfer CAS；CAS 前目标不能 active，CAS 后旧 fence 不能 read/write/model/send。 |
| 117-A7 | transfer unknown 时两端关闭；unknown effect 不重排队，重启仍只恢复原 transition。 |
| 117-A8 | 各 semantic family round-trip 等价；来源身份、发生时间、current/unknown 和历史关系保持。 |
| 117-A9 | 只有明确 current-owner delete-all 命令可进入删除；相邻控制、模糊语义、旧 replay 均 no-state-change。 |

## 实施自由、复杂度上限与停止

冻结内容只包括权威、Module/Interface/Seam、事务与副作用顺序、核心不变量、semantic registry 完整性和上述现实故障。内部 dataclass、字段名、hash/codec、局部 SQL、helper、文件布局、测试 fixture 和 slice 顺序由编码 Agent 决定。

允许的产品范围优先为新 lifecycle Module、`current_head.py`、`storage.py`、`core.py`、`plugin.py` 及必要的 export；不得整体替换现有 integrity manifest、重写 Tickets 110—116、建立 Provider DAG、公开阶段 token、增加逐阶段业务方法或把真实生产接线塞入本票。

编码 Agent 只让冻结红灯转绿。若测试门错误、exact registry 客观无法从现有 store 形成、需要新的业务权威/状态机、真实外部授权或迁移取消产品决定，立即停止返回冻结阶段。理论风险、另一种实现偏好和非阻塞代码气味不扩张本票。
