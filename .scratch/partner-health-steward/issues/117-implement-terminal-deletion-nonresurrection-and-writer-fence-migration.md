# 117 - 实现终止删除防复活与 writer-fence 迁移

Type: task
Status: claimed
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

`117-A1`—`117-A9` 是功能 verdict 和未来冻结门的追踪单位。验证使用能杀死独立现实错误的等价类，不把矩阵中的标点、字段或故障阶段展开成隐藏 Case registry，也不提前固定测试文件、fixture 或实现 slice。受管对象完整性仍必须有“新增对象未登记即失败”的守卫。

### 编码前冻结与预审

以上范围、语义合同和验收矩阵是本票的冻结输入，不表示详细设计或测试门已经冻结。Ticket 116 闭合且本票被 claim 后，先由 characterization Agent 记录当前绿色行为、可复现差额、必须控制的现实故障和非目标；再由设计 Agent 形成一份唯一增量冻结设计，由独立 verification Agent 形成 verifier-owned 冻结测试门。

两份冻结产物必须绑定同一 commit/tree、预期红灯、既有绿灯和验证命令，并在生产实现修改前由 fresh-context Spec reviewer 与 Standards reviewer 对同一 checkpoint 预审通过。只有这时才能进入编码；现在不提前建立 117 的详细方案，避免上游实现变化使方案失效。

## 编码前冻结 checkpoint

Ticket 117 的实施设计和 verifier-owned 测试门已经在产品代码修改前冻结，可交给编码 Agent：

- characterization 产品基线：`63a6a2333e0a7584aa51492035d3b4ca981d40c0`；tree：`b90a610efa7fc4597c90dd95193ca694d0998573`；全量测试：`720/720 PASS`。
- 双轴审查的当前冻结内容 checkpoint：`f1fb2a698fc66af3f49748673b9e85f474add0ba`；tree：`5c93d5f8aae9726421c6518f8d33c885d03b8ea0`。
- 当前冻结元数据 commit：`ff17938f5f255e509f021656b6caa466541d1570`；tree：`1c0f8e17506574b3cc641bdad449bcec3f102e15`。
- 冻结设计 blob：`8e3a2b349d053aa550c7c4f155d63165b2c5926b`。
- 冻结验证合同 blob：`0c8a005accffed69601607a1557c05be2c56fda5`。
- verifier-owned `tests/test_ticket117_integration.py` blob：`cfc696007146962dd944d8309443ae4595ae1559`。
- 本次重新冻结仍只补原 V02/V03/V06：删除说明 unknown 不得进入 TaskEngine、形成普通 `delivery-unknown` 主人决定请求或重发；terminal exact lookup 确认后必须继续既有清理；writer transfer 必须轮换 fence 并使旧 source capability 无法形成有效 proof。Gate 总数仍固定为 9，架构和 A1—A9 不变。
- 对修复 checkpoint `f66f513513af80e64eb594c806c262928fab26fb` 的补强门实跑：只在 V02 因另形成一条绑定原 lifecycle notice 的 `delivery-unknown` 主人决定请求而 FAIL；这是冻结设计“一次说明、不索取第二次主人确认”的同一直接反例。编码前产品基线仍保持 `1 failure / 8 skips / 0 errors`。
- fresh-context Spec reviewer：PASS，无 P0/P1/P2；补强来自既有 A2/V02，不新增需求、架构或 Gate。
- fresh-context Standards reviewer：PASS，无 P0/P1/P2；断言只使用 public managed read，fixture 隔离，Gate 总数仍为 9。

编码 Agent 只能修改产品实现及必要 export，使上述同一 9 门从冻结红灯转为 `9/9 PASS`；不得修改冻结设计、冻结验证合同、verifier-owned 测试、本 Ticket、Map 或 Tickets 110—116。若必须改门、改架构、增加产品决定、接入真实 Provider，或无法用现有有界 Seam 实现，应立即停止并返回冻结阶段。完成后必须提交并普通推送自己的实现分支，报告 commit/tree、冻结 blob 零变化、117 专项、113—116 回归、全量测试、compileall 与 diff-check 结果；不得自行标记 `resolved` 或更新 Map。

### 一致性实施、核验、停止与闭票

以通过编码前预审的冻结 checkpoint 为 `review_base`。编码 Agent 只可做使已封存红灯转绿所必需的最小实现修改，并保留既有绿色行为；不得修改冻结设计、冻结验证合同或 verifier-owned 测试，不得新增测试类别、产品功能或验收门。

若冻结门本身错误、冻结设计客观无法满足既有验收、需要新架构或外部决定/授权，立即停止并交回冻结阶段；不得由编码 Agent 边改门边实现。新功能必须另开 Ticket，不能扩入本票。

实现后重跑同一冻结门、受影响回归，以及 `python -m unittest discover -v -s tests -p "test_ticket117_*.py"`、`python -m unittest discover -v`、`python -m compileall -q partner_health_steward tests`、`git diff --check`，再形成 `reviewed_commit`/tree。fresh-context Spec reviewer 与 Standards reviewer 只核实实施是否符合冻结设计、冻结验收和证据真实性，不重新设计本票。finding 只有同时满足以下条件才阻塞：P0/P1/P2；有可重复命令或步骤；有可定位证据；明确指出被破坏的冻结验收 ID 或不变量。P3、理论可能、另一种合理偏好和新功能建议均不阻塞。

任何真实删除、真实密钥销毁、真实 current-head/旧 VM、真实备份或生产迁移动作都必须停止并等待单独批准；无法完整枚举受管对象、需要以后补齐部分状态或 writer-fence 路线不可实施时保持关闭并报告。冻结设计或测试门变化必须返回编码前重新冻结和预审；最终 verdict 后的生产变化必须形成新 checkpoint 并重新核验。全部冻结验收通过且没有 blocker 后应停止继续扩写审查。

实施 Agent 记录 Gate 到实现位置、验证结果和 checkpoint identity；形成 `reviewed_commit` 前记录 `git status --porcelain=v1 --untracked-files=all`，不得遗留未提交或未跟踪的实现、冻结或证据文件。两轴均通过后只追加 `## Answer`、状态和 Map pointer，Answer 记录两轴可定位 verdict 及共同 base/commit/tree。确认相对 `reviewed_commit` 仅有闭票元数据后提交，并对当前分支执行普通 `git push`；推送被拒绝时停止，禁止 force push 或改写历史。

