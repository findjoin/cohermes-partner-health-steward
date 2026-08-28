# Ticket 117 冻结验证合同

> 状态：frozen candidate，等待同一 pre-code checkpoint 的 Spec / Standards 预审。characterization 产品基线为 `63a6a2333e0a7584aa51492035d3b4ca981d40c0`，tree 为 `b90a610efa7fc4597c90dd95193ca694d0998573`。本合同与 [`117-frozen-implementation-design.md`](117-frozen-implementation-design.md) 共同约束编码 Agent；二者任一变化都必须重新冻结和预审。

## 测试权威、公开 Seam 与依赖展开

独立 verification authority 独占 `tests/test_ticket117_integration.py`。编码 Agent 不得修改该文件、本合同或候选冻结设计；认为门错误、公开 Seam 客观不可实现或需要新产品决定时，必须停止并返回冻结阶段。

验收只通过以下公开观察面：

- `HealthPlugin.health_operation("lifecycle.execute", ...)`；
- bounded `HealthPlugin.managed_lifecycle_read(operation_ref | None, peer_id="plugin")`；
- Tickets 114—116 已有 managed read、`health_writes_allowed`、`model_effects_allowed`、`outbound_effects_allowed`、strict-model 与 owner/contact delivery Seam；
- current-head、synthetic key、configured replica 与 migration artifact 等真实系统边界的 fake Adapter 调用和返回值。

测试不得把私有 SQL、表、helper、内部阶段对象、私有 runner 名称或清理算法作为通过 oracle。唯一例外是 V04 用 SQLite connection serialize/deserialize 复制真实 pre-terminal DB，以及 V05 `CREATE` 一个未登记 managed object；二者只制造故障，最终判定仍只看构造拒绝、public probe/gates、managed read 与 Adapter 零形成。terminal confirmed 后，普通 HealthCore 健康 Interface 必须永久关闭；后续观察只允许 `managed_lifecycle_read` 和 fake Adapter 的无正文 readback。目标 Core 只以 `offline-staging` 模式构造；CAS 确认前除精确 `accept-migration` 与 bounded lifecycle read 外，所有健康读取、写入、任务、模型与外发均关闭。一个 fake 可以同时承担 artifact 与 replica 角色，但两个角色的调用记录和权限断言保持分离。

为让冻结门可执行且不建立第四类业务 Interface，测试只冻结一个构造期 Mapping `lifecycle_config`，用于注入 immutable release/semantic registry、`DestroyableKeyAdapter`、`ManagedReplicaAdapter`、`MigrationArtifactAdapter` 和 `source` / `offline-staging` 模式；它没有业务方法，也不能返回健康正文。fake SDK 只需提供幂等 destroy/purge/absence 与 artifact put/get/remove 边界；migration package 对 verifier 完全 opaque，具体产品类型、manifest 内部字段、digest 算法、codec 和 runner 名称均不冻结。

公开 `lifecycle.execute` payload 采用严格 `kind` tagged union，字段来自冻结设计；caller 不能提交 phase、terminal、active site、generation 或 writer-fence 成功事实。bounded lifecycle read 只允许无正文的 `mode`、`phase`、authority binding、manifest ref/digest、target offline/active、`reason_code`、`remains_unproven`。公开结果状态只允许 `notice-pending`、`manifest-ready`、`completed`、`replayed`、`rejected`、`unknown`。

当前产品没有 Ticket 117 公共 lifecycle 前置。测试因此采用一个真实依赖红灯：V01 必须因 `managed_lifecycle_read` / lifecycle construction / `lifecycle.execute` 尚未实现而 `FAIL`；V02—V09 明确 `SKIP` 并说明依赖 V01。九门的完整源码和下游 oracle 同时封存；V01 转绿后自动展开，不修改测试。编码前唯一接受的形状是 `1 failure / 8 skips / 0 errors`；最终只接受 `9 passed / 0 skipped / 0 errors`。

## 九个 verifier-owned Gate

| Gate | 验收 | 唯一公开结果 | 必须杀死的独立现实错误 |
|---|---|---|---|
| 117-V01 | 117-A1 | current owner 的 delete-all 说明完成后、freeze 前通过既有 Ticket 115 public path 实际建立一个可运行 task、owner-delivery intent 和尚未调用 Adapter 的 execution grant；freeze 后原 grant 执行、同 intent 再 claim、task advance、diagnosis model prepare、四类既有 managed health read、健康写入、模型与外发全部关闭，两个 fake Adapter 调用为零；重启仍关闭 | 用不存在 intent/无效 grant 冒充在途工作，只停 UI 或部分写入，或让已取得但未开始的 grant、真实 task、模型或 managed read 越过 freeze |
| 117-V02 | 117-A2 | 正常 registry purge bindings 与 fake Adapter 自枚举 configured binding exact set 相等；新增一个未登记 configured replica 后 probe/三类 gate 必须失败关闭且零清理。正常删除在 terminal confirmed 前 key destroy/replica purge mutable 调用为零；确认后严格为 `destroy < key.absence < replica.purge < replica.absence`；terminal 后不重开健康 DB，bounded read 只由无正文 terminal/release/Adapter 事实投影，真实未绑定 Provider 逐项 `remains_unproven` | 同一常量生成 registry/Adapter 两侧造成假绿，先毁钥、软删除、漏 configured 对象、次序错误、terminal 后为继续清理重开健康 DB，或把未证明真实 Provider 宣称已清除 |
| 117-V03 | 117-A3 | terminal mutable call 丢失响应时只保留原 operation/transition 为 `unknown`；重启只 exact lookup，不发第二次 mutable call，不 destroy、不 purge、不宣称完成或失败 | unknown 被猜成成功/失败、换 causal ID 重做 CAS，或终态未证实时提前不可逆清理 |
| 117-V04 | 117-A4 | 先经公开诊断、任务/outbox 和 unknown delivery path 建立可定位旧状态，再仅作为 fault fixture 用 SQLite serialize 封存真实 pre-terminal encrypted DB。terminal 后以旧 key 将该 DB deserialize 到全新 `EncryptedStateStore`，并与同一个真实 terminal current-head 重建 Core；构造以 `AuthorityValidationError`/`ProtocolViolation` 拒绝，或构造成功但 public probe/三类 gate unavailable，均证明无 active Core，其他异常不吞。另用既有 public initialization fixture 构造全新 installation/head/key 的 enabled 空白状态，Tickets 114—116 managed views 不含旧设置批准、task、diagnosis 或 unknown ref | 把摘要/字符串塞进 fake 当作恢复，使用独立 rollback active head 制造假刺激，规定只能在某一层拒绝真实旧库，或把重新初始化链接到旧状态 |
| 117-V05 | 117-A5 | baseline `lifecycle_config` 明列产品 release、ADR、七 Skills、Plugin/Core、Adapter/Model、knowledge/safety/diagnostic、Hermes artifact、required patch、disabled-native、schema、observer、ACL service、secret requirements，registry purge bindings 与 configured Adapter 基线一致，source 只形成 opaque package。私有 `CREATE` 未登记 managed object、registry missing/extra 与 source secret-policy violation 均只能得到 public probe/三类 gate fail-closed 且 artifact 零形成；target 以三个逻辑分组制造 release/bundle/schema drift，ADR/七 Skills/Hermes/required patch/disabled-native governance-artifact drift，以及真实 foreign current-head + observer/ACL drift。foreign authority 先绑定匹配 writer capability，排除 writer proof 缺失假拒绝；三组均拒绝同一 opaque package且不 active。wrong-hash 只通过 public accept payload 提交错误 digest | 解析/改写 manifest 私有字段或复制 digest 算法，用硬编码 public-view family 字典冒充 store inventory，让 foreign head 因未绑定 vault proof 假拒绝，所有坏包只因 hash mismatch 被拒，或漏校验 governance artifact/head/observer/ACL/secret policy |
| 117-V06 | 117-A6 | target 在 offline-staging 中只接受精确 migration package；完整验证 receipt 后 source 只发一次 writer-transfer CAS。成功子场景在迁移前取得真实旧 writer-fence proof 并建立 task/outbox，确认后 current-head 与旧 Plugin task/model/outbox 入口直接拒绝旧权威，只有 target 新 site/fence gates 可用。独立 CAS-conflict 子场景只发一次 transfer mutable call，source 保持 frozen/关闭、target 保持 offline/关闭 | 只检查 source/target 布尔标志，目标预启用、双写窗口、把 CAS conflict 当成功或隐式 unfreeze，或旧 VM/fence 在成功迁移后继续写、调用模型或发送 |
| 117-V07 | 117-A7 | writer-transfer response loss 时 source/target 均关闭，重启只 exact lookup；迁移前后 fake Artifact readback 的 opaque package 对象完全不变，用原 spent grant 再走旧 VM outbound Seam 时新 fake transport 调用为零；测试不解析 package 内部 unknown/outbox 字段 | 任一端猜测自己获胜、response loss 改写 package，或把原 possibly-sent effect 再送到 transport |
| 117-V08 | 117-A8 | 迁移前真实制造 unknown owner delivery，并在 Tickets 110—116 全部 public semantic views 中封存 exact unknown ref、真实 task/关系、安全来源 ref 与发生时间；成功迁移后目标 managed view 必须保留 exact unknown ref，全部公开业务语义等价，来源和发生时间不改写 | 只比较 settings/tasks/diagnosis 子集或 opaque/file hash，迁移丢失 unknown/task 关系，或把旧来源和发生时间重写成目标站点时间 |
| 117-V09 | 117-A9 | 先真实调用既有 owner mutation public path 分别暂停主动支持、停止记录、取消真实 task、撤回真实 execution approval，每次只允许 owner/managed state 按原控制变化而 lifecycle state 不变；模糊“关闭但保留”、wrong owner、旧 generation、missing scope 与 wrong scope 均经 `lifecycle.execute` 拒绝且 lifecycle state 不变。只有 current owner、current generation、精确 `lifecycle:delete` scope 和 `permanent-delete-all-health-data` 才形成且重放仍只有一次不可召回说明 | 把相邻控制伪造成 lifecycle payload 来测试、把缺失/错误 scope 当成授权、用关键词误触发永久删除、旧命令进入 freeze，或重复给主人发送不可召回说明 |

每门只杀死表中一个现实错误。等价输入只在同一决策点共享同一 mutation 时用 `subTest`；不对字段、对象 family、阶段和故障做笛卡尔积。对象完整性由 registry exact-set 守卫承担，不靠为每张表增加一个测试。

## 防假绿、完成与停止

- V01 红灯必须来自调用当前产品公开 Interface 后的缺失能力或错误可观察结果；禁止无条件 `fail`、导入不存在 symbol、测试专用 bypass 或复制生产生命周期算法。
- V02—V09 只因共同 lifecycle 前置未实现而 skip。V01 转绿后，任一后继缺失行为必须真实 fail，不得继续 skip。
- 正向证据必须到达公开 lifecycle result/read、既有 managed read/gate 或 fake Adapter；异常类型、私有行、内部阶段或 helper 调用不构成验收。
- terminal 后清理 runner 只能使用 terminal current-head、installation namespace、release registry 和 Adapter readback；若实现必须重开/解密健康 DB，设计客观不可满足，应停止而不是弱化 V02/V04。
- 真实 key、真实 Provider/backup/VM、真实模型/Weixin、生产迁移与主人验收不属于本票；fake 结果不得冒充这些外部事实。

pre-code checkpoint 必须运行并记录：

- `python -m unittest -v tests.test_ticket117_integration`：预期 `1 failure / 8 skips / 0 errors`；
- `python -m compileall -q partner_health_steward tests`：通过；
- `git diff --check`：通过。

实现完成后还需同一冻结文件 `9/9 PASS`、Tickets 113—116 受影响回归、`python -m unittest discover -v -s tests -p "test_ticket117_*.py"`、全量 discovery、compileall 与 diff check 全绿，且冻结设计、合同和 verifier-owned test blob 相对 test-gate checkpoint 零变化。若 public Seam 无法表达某项 Gate、registry 无法 exact enumerate、offline target 需要普通健康入口、terminal cleanup 必须重开健康 DB，或需要新授权/产品决定，立即停止并返回冻结阶段。
