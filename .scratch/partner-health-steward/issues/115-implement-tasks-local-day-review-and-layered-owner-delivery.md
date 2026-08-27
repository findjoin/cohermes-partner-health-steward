# 115 - 实现任务当地日复盘与分层主人投递

Type: task
Status: resolved
Parent: [健康管家首发 TO、CAN 与 HOW 决策闭合路线](../map.md)
Blocked by: [113 - 实现 StrictHealthLLM 治理知识与非诊断回答](113-implement-strict-health-llm-governed-knowledge-and-nondiagnostic-answer.md), [114 - 实现主人设置数据权利与业务状态](114-implement-owner-settings-data-rights-and-business-status.md)

**What to build:** 让健康管家根据主人目标、画像／证据变化和既有任务事件建立、推进和验收健康任务，按主人当地自然日复盘，并通过原子 outbox 和分层主人 Weixin 投递推进必要行动。

## 当前状态与门禁

- 历史 characterization 基线为 `d468e0ac3e33a37efd53f03328f16dcbc42cff09`；当前有界恢复代码与旧测试基线为 `d1b29e4ebbdcdcfcc7d86077290d9cced40cc02a`。旧的 `122/122` 绿色只证明旧测试通过，不再作为闭票门。
- `23d4827557b532f4eee4fe5511c458ed2b5d8e15` salvage 和 `3fa4d01c` 长设计只读保留。前者增加约 7,919 行仍未闭合，后者增长到千余行且四轮审查未通过，均不得整体采用。
- 唯一增量 HOW 是[Ticket 115 增量架构冻结设计](../design/115-frozen-implementation-design.md)，并受[`AI 编码架构治理`](../../../docs/agents/architecture-governance.md)约束。
- 独立测试权威为[Ticket 115 冻结验收测试合同](../design/115-frozen-verification-contract.md)。编码 Agent 不得修改其中列出的 verifier-owned 测试；只能让测试门从红转绿。
- 测试门在 `d1b29e4` 上确认六个既有合同缺口：opaque intent 不能绕过批准次数或最小联系间隔；状态下降请求在后续投影后仍须可发送；`abnormal/cannot-confirm → active` 均须请求一次；unknown 的必要主人决定请求必须实际可发送。Ticket 保持 `claimed`，这些门与全量回归全部通过前不得闭票。

## 产品验收

- [x] TaskEngine 独占任务权威；Skill、模型和 Plugin 只提交候选。主人可以查看、取消、延期或调整普通任务；范围扩大等待当前授权；任务只按自身验收进入四类终态。
- [x] 每个主人有效当地自然日最多一次复盘；时区变化按下一有效日生效；恢复不补旧日；无行动保持安静。
- [x] 一次决定形成的业务事实、复盘结果和 outbox intent 原子可见；外部发送只在 finalize 后、SQLite 事务外发生。
- [x] 每次外发前重新检查当前证据、批准、控制、时间窗、route/config、current head 和 writer fence；旧持有者不能提交或发送。
- [x] 稳定投递身份以及 formed、business-committed、attempted、interface result、delivered、read、owner action 和 unknown 保持不同事实；低层不能提升为高层或关闭任务。
- [x] 可能已离站的 unknown 冻结自动重试；状态变化和必要主人决定按当前因果事实至多主动请求一次，且不被普通通知关闭或主动支持暂停吞掉。
- [x] task/review/delivery 的无正文事实进入既有 StatusProjector；单项失败不自动冒充健康管家全局故障。

## 范围与实施

Ticket 116 的诊断安全和联系人投递、Ticket 117 的删除迁移、Ticket 118 的真实宿主／Weixin 接线、Ticket 119 的生产 canary 与主人验收均不属于本票。fake Adapter 只能证明本地 Plugin/core 行为，不能证明真实渠道送达、已读或幂等能力。

characterization 与独立红测已经完成。实施 Agent 必须从测试门 commit 开始，只修复已冻结的六类缺口（七个红灯）；不得重新盘点全票、不得新增或修改 verifier-owned 测试，也不得扩写架构。实现后审查只检查产品验收、冻结一致性、同一组 hidden variants、回归和证据真实性；新 finding 按治理文件分类，不能自动延长本票。

至少运行 Ticket 115 专项、受影响的 Ticket 110—114 回归、全量测试、`compileall` 和 `git diff --check`。满足产品验收、必要验证与一致性审查后追加 `## Answer`、设为 `resolved` 并更新 Map。

## 历史说明

旧实现提交 `d1450bc`、`5e94d3c`、`6a25954` 已完成任务、当地日、原子 outbox、分层 owner delivery、当前性重检和 unknown 冻结的主体。历史代码和失败候选均可由 Git 回溯；它们是差额验收证据，不自动构成当前关闭结论。

## Answer

独立 reviewer 复核结论：Ticket 115 已满足冻结增量设计、115-A—G 验收合同与五类冻结故障，可标记为 `resolved`。

- `TaskEngine`、当地日复盘、主人取消／延期／调整、范围扩大 successor、当前批准与外发前重检均通过既有 Plugin → Core 受管接缝验证；任务四类主标签、复盘静默与低层交付事实保持各自边界。
- 业务事实、复盘、outbox 与状态变化请求复用既有 `prepared → current-head CAS/readback → local finalize` 路径；`StatusProjection` 和对应 status-transition outbox 同成同败，故障恢复只完成原决定一次，Adapter 仅在 finalize 后于 SQLite 事务外执行。
- 历史 v1/v2 与当前 v3 状态请求纳入同一后继关系；无法可靠识别的旧请求失败关闭，被后继取代的请求不会因状态循环复活。unknown 冻结、必要主人决定、双向状态变化请求、批准次数／联系间隔和 mandatory identity 防伪均通过冻结门。
- 已核验实现提交 `761fcdfe404f4c94191e2339d1bde643c076e097`：冻结门 `16/16`、Ticket 115 `135/135`、Ticket 114 `210/210`、项目全量 `708/708` 均通过；`compileall` 与 `git diff --check` 通过。冻结测试、验证合同和本 Ticket 在实现提交中均保持零修改，Spec 与 Standards 双轴审查没有 P0/P1/P2。

本结论只覆盖本地合成 Plugin/core、fake Adapter 与持久化／恢复合同；不代表真实 Hermes、Weixin、模型、内容权利、医学审核、部署或生产 canary 已验收。后继 Ticket 116 承接诊断安全门禁与支持联系人链。
