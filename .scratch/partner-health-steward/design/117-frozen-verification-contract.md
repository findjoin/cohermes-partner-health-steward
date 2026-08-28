# Ticket 117 冻结验证合同

> 状态：frozen candidate，等待同一 pre-code checkpoint 的 Spec / Standards 预审。characterization 产品基线为 `63a6a2333e0a7584aa51492035d3b4ca981d40c0`，tree 为 `b90a610efa7fc4597c90dd95193ca694d0998573`。本合同与 [`117-frozen-implementation-design.md`](117-frozen-implementation-design.md) 共同约束编码 Agent；二者任一变化都必须重新冻结和预审。

## 测试权威、公开 Seam 与依赖展开

独立 verification authority 独占 `tests/test_ticket117_integration.py`。编码 Agent 不得修改该文件、本合同或候选冻结设计；认为门错误、公开 Seam 客观不可实现或需要新产品决定时，必须停止并返回冻结阶段。

验收只通过以下公开观察面：

- `HealthPlugin.health_operation("lifecycle.execute", ...)`；
- bounded `HealthPlugin.managed_lifecycle_read(operation_ref | None, peer_id="plugin")`；
- Tickets 114—116 已有 managed read、`health_writes_allowed`、`model_effects_allowed`、`outbound_effects_allowed`、strict-model 与 owner/contact delivery Seam；
- current-head、synthetic key、configured replica 与 migration artifact 等真实系统边界的 fake Adapter 调用和返回值。

测试不得查询私有 SQL、表、helper、内部阶段对象、私有 runner 名称或清理算法。terminal confirmed 后，普通 HealthCore 健康 Interface 必须永久关闭；后续观察只允许 `managed_lifecycle_read` 和 fake Adapter 的无正文 readback。目标 Core 只以 `offline-staging` 模式构造；CAS 确认前除精确 `accept-migration` 与 bounded lifecycle read 外，所有健康读取、写入、任务、模型与外发均关闭。一个 fake 可以同时承担 artifact 与 replica 角色，但两个角色的调用记录和权限断言保持分离。

为让冻结门可执行且不建立第四类业务 Interface，测试只冻结一个构造期 Mapping `lifecycle_config`，用于注入 immutable release/semantic registry、`DestroyableKeyAdapter`、`ManagedReplicaAdapter`、`MigrationArtifactAdapter` 和 `source` / `offline-staging` 模式；它没有业务方法，也不能返回健康正文。fake SDK 只需提供幂等 destroy/purge/absence 与 artifact put/get/remove 边界，具体产品类型、内部字段、codec 和 runner 名称不冻结。

公开 `lifecycle.execute` payload 采用严格 `kind` tagged union，字段来自冻结设计；caller 不能提交 phase、terminal、active site、generation 或 writer-fence 成功事实。bounded lifecycle read 只允许无正文的 `mode`、`phase`、authority binding、manifest ref/digest、target offline/active、`reason_code`、`remains_unproven`。公开结果状态只允许 `notice-pending`、`manifest-ready`、`completed`、`replayed`、`rejected`、`unknown`。

当前产品没有 Ticket 117 公共 lifecycle 前置。测试因此采用一个真实依赖红灯：V01 必须因 `managed_lifecycle_read` / lifecycle construction / `lifecycle.execute` 尚未实现而 `FAIL`；V02—V09 明确 `SKIP` 并说明依赖 V01。九门的完整源码和下游 oracle 同时封存；V01 转绿后自动展开，不修改测试。编码前唯一接受的形状是 `1 failure / 8 skips / 0 errors`；最终只接受 `9 passed / 0 skipped / 0 errors`。

## 九个 verifier-owned Gate

| Gate | 验收 | 唯一公开结果 | 必须杀死的独立现实错误 |
|---|---|---|---|
| 117-V01 | 117-A1 | current owner 的 delete-all 说明完成后、freeze 前通过既有 Ticket 115 public path 实际建立一个可运行 task、owner-delivery intent 和尚未调用 Adapter 的 execution grant；freeze 后原 grant 执行、同 intent 再 claim、task advance、diagnosis model prepare、四类既有 managed health read、健康写入、模型与外发全部关闭，两个 fake Adapter 调用为零；重启仍关闭 | 用不存在 intent/无效 grant 冒充在途工作，只停 UI 或部分写入，或让已取得但未开始的 grant、真实 task、模型或 managed read 越过 freeze |
| 117-V02 | 117-A2 | terminal confirmed 前 key/replica 调用为零；确认后顺序固定为 synthetic key destroy/absence，再 registry/configured replica purge/absence；terminal 后不重开健康 DB，bounded read 只由无正文 terminal/release/Adapter 事实投影，真实未绑定 Provider 逐项 `remains_unproven` | 先毁钥、软删除、漏 registry 对象、保留审计例外、terminal 后为继续清理重开健康 DB，或把未证明真实 Provider 宣称已清除 |
| 117-V03 | 117-A3 | terminal mutable call 丢失响应时只保留原 operation/transition 为 `unknown`；重启只 exact lookup，不发第二次 mutable call，不 destroy、不 purge、不宣称完成或失败 | unknown 被猜成成功/失败、换 causal ID 重做 CAS，或终态未证实时提前不可逆清理 |
| 117-V04 | 117-A4 | 先经公开诊断、任务/outbox 和 unknown delivery path 建立可定位旧状态；terminal resource 重启、旧 snapshot/key 与 installation-ID collision 不能恢复 health gates。再用既有 public initialization fixture 构造全新 installation/head/key 的 enabled 空白状态，初始化 projection 证明 installation/key 均不同，Tickets 114—116 managed views 不含旧设置批准、task、diagnosis 或 unknown ref | 用默认空 fixture 冒充已清除旧状态，用旧备份/旧 key 复活启用、批准、任务、诊断/unknown，或把重新初始化链接到旧状态 |
| 117-V05 | 117-A5 | source 生成一份 encrypted package 与 hash-checked manifest；semantic registry exact set、release/bundle/schema/current-head identity、语义对象和 secret policy 全部通过才 `manifest-ready`；一个代表性缺项、额外 family、错 hash 或明文 secret 均使目标保持 offline 且 Adapter 不激活 | 只复制 DB/文档，漏 family 仍接受，hash 形同虚设，或把 key/token/capability 写进 manifest |
| 117-V06 | 117-A6 | target 在 offline-staging 中只接受精确 migration package；完整验证 receipt 后 source 只发一次 writer-transfer CAS。测试在迁移前从真实 writer-fence vault 取得旧 VM proof，并建立真实 task/outbox；确认后 current-head 直接拒绝旧 proof，旧 Plugin 入口的 task/model/outbox prepare 均拒绝，只有 target 新 site/fence 的 gates 可用 | 只检查 source/target 布尔标志，目标预启用、双写窗口、CAS 冲突仍激活目标，或旧 VM/fence 在成功迁移后继续写、调用模型或发送 |
| 117-V07 | 117-A7 | 迁移前通过真实 owner-delivery Adapter response loss 建立 public unknown delivery；manifest 保留其 exact ref。writer-transfer response loss 时 source/target 均关闭，重启只 exact lookup；用原 spent grant 再走旧 VM outbound Seam 时新的 fake transport 调用为零，artifact readback 证明 unknown ref 未消失、未改写也未进入可重放结果 | 用合成字符串冒充 unknown，任一端猜测自己获胜，或把迁移前 unknown/pending 当成可重放 outbox |
| 117-V08 | 117-A8 | 迁移前后同时比较 Tickets 110—116 全部可公开 semantic views：probe/三类 gates、initialization、daily state、rights、settings、business status、task/review/delivery 与 safety/diagnosis；另以真实 task、安全来源 ref 和发生时间证明来源连续性。除 lifecycle authority site/generation/fence 的合法变化外业务语义完全等价 | 只比较 settings/tasks/diagnosis 子集或文件 hash，迁移丢失旧票语义/unknown，或把旧来源和发生时间重写成目标站点时间 |
| 117-V09 | 117-A9 | 先真实调用既有 owner mutation public path 分别暂停主动支持、停止记录、取消真实 task、撤回真实 execution approval，每次只允许 owner/managed state 按原控制变化而 lifecycle state 不变；只有模糊“关闭但保留”、wrong owner 与旧 generation 通过 `lifecycle.execute` 拒绝。current owner、current generation、`lifecycle:delete` scope 和精确 `permanent-delete-all-health-data` 才形成且重放仍只有一次不可召回说明 | 把相邻控制伪造成 lifecycle payload 来测试、用关键词误触发永久删除、旧命令进入 freeze，或重复给主人发送不可召回说明 |

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
