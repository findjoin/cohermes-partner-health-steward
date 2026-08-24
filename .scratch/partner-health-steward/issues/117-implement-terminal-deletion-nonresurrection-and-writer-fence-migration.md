# 117 - 实现终止删除防复活与 writer-fence 迁移

Type: task
Status: ready-for-agent
Parent: [健康管家首发 TO、CAN 与 HOW 决策闭合路线](../map.md)
Blocked by: [110 - 建立 Plugin/core 受信边界与合成验证骨架](110-establish-plugin-core-trust-boundary-and-synthetic-harness.md), [114 - 实现主人设置数据权利与业务状态](114-implement-owner-settings-data-rights-and-business-status.md), [115 - 实现任务当地日复盘与分层主人投递](115-implement-tasks-local-day-review-and-layered-owner-delivery.md), [116 - 实现安全诊断门禁与支持联系人链](116-implement-safety-diagnostic-gates-and-support-contact-chain.md)

**What to build:** 让主人能够永久删除全部受管健康对象并让已删除状态不可复活，同时让完整健康状态可以在 writer fence 下迁移到新实例。删除、迁移、模型、任务和外发必须共享冻结和代际边界；任何终态未知都保持健康关闭，不重放未知效果。

**Blocked by:** 110 - 建立 Plugin/core 受信边界与合成验证骨架; 114 - 实现主人设置数据权利与业务状态; 115 - 实现任务当地日复盘与分层主人投递; 116 - 实现安全诊断门禁与支持联系人链

- [ ] 永久删除先冻结健康读写、任务推进、模型调用、outbox 和外发，再条件推进不可逆 terminal generation。
- [ ] terminal 确认后销毁健康密钥并清除画像、证据、任务、批准、控制、诊断、安全、联系人、警报、outbox、未知、索引、备份、导出和迁移暂存；站外已交付内容不宣称可召回。
- [ ] 删除响应未知时健康保持关闭，不声明全部旧副本已阻止，也不允许旧快照复活启用、批准或撤回状态。
- [ ] 迁移生成覆盖 Plugin/core/Skill/适配器/模型接口/知识/安全/诊断 bundle、语义状态、控制、任务、投递、未知、删除和迁移事实的 hash-checked manifest；秘密只重新配置。
- [ ] 目标实例在 manifest、密钥、bundle、路线和 current head 验证前离线；一次 CAS writer-fence 转移后源端、旧 VM 和旧 fence 无法写入、调用模型或发送。
- [ ] 合成故障测试覆盖 terminal delete、旧快照、CAS 冲突、转移超时、双写竞态、旧 fence、密钥销毁顺序和未知转移。

## Implementation contract

### Start gate and authority to load

只在 Ticket 114、115、116 均 `resolved` 后开始。实现前必须读取：

- [当前实现 Spec](../spec.md)的“主人控制、删除和迁移”“受管状态与加密”“Current head、恢复和并发”“Testing Decisions”；
- [当前 HOW 证据](../evidence/36-how-route-after-current-can-closure-20260822.md)的“Support contact, deletion, and migration”“Local state plus opaque current head”与 validation boundary；
- [`CONTEXT.md`](../../../CONTEXT.md)中的“永久删除健康画像”“删除后空白初始化”“主人数据权利”“健康资料来源连续性”“健康管家权威载体”和“处理结果无法确认”；
- Ticket 110 的 writer-fence/current-head/terminal 原语，以及 Ticket 114—116 的全部受管对象、控制、任务、投递、诊断、安全和联系人状态，以最终已验收接口为准。

任一 blocker 未闭合时只能做受管对象清单的只读审计；不得 claim、提前删除、复制状态或执行任何真实迁移。

### Scope and ownership

本票完整拥有两条共享冻结与 generation 边界的协议：

1. **永久删除**：先冻结所有健康读写/模型/任务/outbox/外发，再条件推进不可逆 terminal generation，确认后销毁密钥并清除全部受管副本；
2. **writer-fence 迁移**：源端冻结并生成语义完整 manifest，目标离线验证后一次 CAS 接管，旧实例永久失去健康写入、模型和发送资格。

删除与迁移都必须覆盖 Ticket 110—116 已实现的每类受管对象；对象清单不是静态表名缓存，而是由版本化 semantic registry/manifest 声明并由测试证明无遗漏。真实备份提供者、云资源、旧 VM、密钥服务和生产迁移不在本票执行范围；只使用临时目录、合成密钥和 fake current-head。

优先把新职责放入聚焦模块，例如 `deletion.py`、`migration.py`；共享 freeze/generation/manifest 类型只能有一套。`storage.py` 提供枚举清除与认证完整性原语，`core.py` 编排状态机，所有 Plugin/model/delivery 入口继续通过已有 writer-fence 门。不得用复制数据库文件替代语义迁移。

### Required semantic contracts

- 删除阶段至少可区分 request accepted、effects frozen、terminal advance pending/confirmed/unknown、key destruction、controlled purge、completed；只有 terminal confirmed 后才执行不可逆 key destruction 和本地 purge。
- `request accepted` 只来自 owner-scoped、current-generation、明确语义为“永久删除全部健康画像”的命令；暂停主动支持、停止新增记录、取消任务、撤回批准或“关闭但保留资料”绝不能进入删除状态机。terminal CAS 前给主人一次性说明站外已交付内容不可召回，但不擅自增加 TO 未决定的多重确认流程。
- freeze 一旦进入，新的健康读取、写入、模型、任务推进、outbox claim 和外发都失败关闭；既有可能已离站效果不重试。
- terminal advance 绑定 installation、generation、transition ID、revision digest 和 writer fence；unknown 时健康保持关闭，只允许按原 transition 回查，不声明旧 VM 已全部阻止。
- purge registry 枚举画像、证据、任务、阶段、批准、控制、诊断、安全、联系人、警报、outbox、交付、未知、receipt、索引、导出、备份、迁移暂存和所有密钥材料；站外已交付内容明确不在可召回承诺内。本票只证明合成 registry 和 configured fake provider，真实 provider 绑定/清除证据留给 Ticket 119 的获准隔离 canary。
- 删除完成后的空白初始化使用新 installation/generation/key，不引用旧 ID、摘要、任务、批准、unknown 或历史；旧 snapshot 即使可解密/可读也不能恢复为 current。
- migration manifest 绑定产品/ADR/七 Skill/Plugin/core/adapter/model interface/knowledge/safety/diagnostic bundle、Hermes artifact、required patch、disabled-native-entry assertion、schema、所有语义状态、current-head/observer identity、ACL/服务身份和内容 hash；秘密只保留引用/需求，不进入 manifest。实例 manifest 是加密受管运行对象，不进入 release/Git；release 只绑定其协议、schema、builder 与 semantic-registry 版本。
- 目标在 manifest、schema、keys、route、consent、bundle、current head 和完整 semantic state 验证前保持 offline；验证不完整没有部分启用模式。
- writer-fence transfer 只有 confirmed 成功才能激活目标；冲突为明确失败，unknown 时源/目标都停止。旧源、旧 VM、旧 fence 在转移后不能写、调用模型或发送。
- 未知在迁移中保持未知，不能把 pending/possibly-sent effect 当成可重放队列；来源、原始时间和重投关系保持连续。

### Acceptance matrix

| ID | Required observable result | Forbidden substitute | Required test evidence |
|---|---|---|---|
| 117-A1 | 删除先原子冻结全部健康效果和推进，再发起 terminal CAS；freeze 后所有入口一致关闭 | 先删部分表、只停 UI、任务/模型/发送仍可运行 | 每类入口在 freeze 前后、并发 in-flight、outbox claim、effect release 和重启测试 |
| 117-A2 | terminal confirmed 后按顺序销毁 synthetic key 并清除合成 registry/configured fake provider 中全部登记对象；报告逐项列出尚未执行的真实 provider binding | 软删除、保留“审计例外”、只删主数据库、key 未销毁或宣称真实备份/旧 VM 已清除 | 对象清单逐项 seed/purge、fake key/index/export/backup/staging provider、raw scan 和真实 provider remains-unproven 测试 |
| 117-A3 | terminal unknown 保持健康关闭并只按原 transition 回查，不声明完成或自动重试不可逆步骤 | unknown=成功/失败、换 causal ID 重做、先销毁后确认 | timeout/response loss/readback、冲突、重启和永久关闭状态测试 |
| 117-A4 | 删除后主动初始化形成完全空白的新 installation/generation，旧 snapshot/manifest 无法复活 | 链接旧画像、恢复旧批准/任务/unknown、主动邀请重建 | 新空白初始化、旧 DB/备份/VM 回放、ID collision 和旧 key 测试 |
| 117-A5 | manifest 对所有代码/bundle/语义对象/状态和 current-head identity 完整、hash 可验证且不含秘密 | 只复制 DB/文档/Skill、未声明 schema、把 key/token 写 manifest | manifest 缺项/多项/错 hash/secret scan、round-trip 和版本 drift 测试 |
| 117-A6 | 目标离线全量验证后一次 fence CAS 接管；成功后仅目标可写/model/send | 双写窗口、先启目标后核验、旧源继续外发 | source/target 并发、旧 VM、旧 fence、CAS conflict、目标预启用拒绝测试 |
| 117-A7 | transfer unknown 时两端关闭，既有 unknown effect 保持原状态且不重放 | source/target 任一猜测胜出、重放 pending outbox | response loss、readback unavailable、restart、unknown effect 和恢复裁决测试 |
| 117-A8 | 状态/来源/证据/任务/控制/诊断/联系人语义在迁移前后等价，来源身份与发生时间不改写 | 仅比较文件 hash、丢失历史/unknown、重写来源为目标站点 | 语义快照逐类对比、来源连续性、投影等价和目标 current-head 绑定测试 |
| 117-A9 | 只有明确的当前主人永久删除命令可进入 freeze；其他控制或含义模糊请求保持原状态并返回相应控制/澄清结果 | 暂停/停止记录/取消/撤回/“关闭但保留”触发 terminal delete | owner/scope/generation、命令语义、模糊关闭、旧 replay、一次站外不可召回说明和 no-state-change 测试 |

每个 `117-A*` 是功能 verdict；`Required test evidence` 中以顿号、斜线、逗号或“分别/每类/全分支”列出的每个场景都是独立 Case。实现前按出现顺序登记 `117-Ax-Cyy`，每个 Case 必须映射到可单独失败、测试输出可见的 test/subTest 和独立断言；不能用一个整体断言覆盖多个 Case。purge/manifest registry 必须有“新增受管对象但未登记即失败”的守卫，完成条件是全部 Case `covered=green`。

### TDD execution slices

每个 slice 固定执行：登记本 slice 全部 Case → 添加红测并确认预期失败 → 最小实现转绿 → 运行本 slice 与全部前置 slice 回归。测试按 slice 拆为 `tests/test_ticket117_delete.py`、`test_ticket117_purge.py`、`test_ticket117_manifest.py`、`test_ticket117_transfer.py` 和 `test_ticket117_integration.py`。

1. **Red registries and state machines**：先建立受管对象完整性守卫、明确主人删除命令、删除阶段和迁移 manifest 严格构造测试。完成标准：117-A1—A9 的 contract Case 已登记并按预期失败，遗漏对象类别能稳定失败。
2. **Freeze and terminal delete**：实现 owner-scoped command gate、共享 freeze、terminal CAS/readback 和 phase persistence。完成标准：117-A1、A3、A9 通过，其他控制无法进入删除，崩溃/未知后无健康入口重新开放。
3. **Key destruction and purge**：实现 synthetic key provider destruction、全对象清除和空白重建。完成标准：117-A2、A4 通过，raw storage/索引/导出/备份 fixture 无旧内容。
4. **Semantic manifest**：实现完整、内容寻址、无秘密的 manifest 与 target preflight。完成标准：117-A5、A8 的 manifest/语义等价测试通过。
5. **Writer-fence transfer**：实现 source freeze、offline target validate、一次 CAS 接管、旧 fence 拒绝和 unknown 双端停止。完成标准：117-A6、A7 通过，无双写/双发窗口。
6. **Cross-capability fault matrix**：对 Ticket 110—116 的 write/model/task/outbox/contact 入口注入 delete/migration 并发故障。完成标准：每类入口在 stale/terminal/unknown 下都有拒绝证据。
7. **Regression and review**：运行本票及全量验证，并进行不可逆操作重点的 Standards/Spec 双轴审查。完成标准：所有原复选项和 117-A1—A9 有“测试 + 实现位置 + 结果”映射，真实 provider 仍明确待 Ticket 119 验证，Ticket 保持 `claimed` 等待独立审查。

### Verification and stop conditions

交审至少运行：

- `python -m unittest discover -v -s tests -p "test_ticket117_*.py"`
- `python -m unittest discover -v`
- `python -m compileall -q partner_health_steward tests`
- `git diff --check`

列出并审查全部未跟踪文件，记录实际 Python/关键依赖版本。任何需要真实删除、真实密钥销毁、真实 current-head/旧 VM、真实备份或生产迁移的动作都必须停止并等待单独批准；若无法完整枚举受管对象、需要复制部分状态后“以后补齐”，或发现 writer-fence 路线不可实施，立即报告并保持关闭。实现 Agent 不得标记 `resolved`。

实施 Agent 在交审前于本票末尾追加 `## Implementation evidence (unreviewed)`，逐 Case 记录测试名、实现 symbol、命令/结果摘要和 diff/commit identity；独立 reviewer 才能写 `## Answer` 并决定是否 `resolved`。

