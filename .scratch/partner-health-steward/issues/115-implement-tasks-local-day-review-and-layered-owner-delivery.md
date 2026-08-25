# 115 - 实现任务当地日复盘与分层主人投递

Type: task
Status: claimed
Parent: [健康管家首发 TO、CAN 与 HOW 决策闭合路线](../map.md)
Blocked by: [113 - 实现 StrictHealthLLM 治理知识与非诊断回答](113-implement-strict-health-llm-governed-knowledge-and-nondiagnostic-answer.md), [114 - 实现主人设置数据权利与业务状态](114-implement-owner-settings-data-rights-and-business-status.md)

**What to build:** 让健康管家根据主人目标、画像／证据变化和既有任务事件建立、推进和验收健康任务，按主人当地自然日复盘，并通过原子 outbox 和分层主人 Weixin 投递推进必要行动。

## 当前状态与门禁

- 产品代码基线固定为 `d468e0ac3e33a37efd53f03328f16dcbc42cff09`；当前 Ticket 115 专项测试为 `102/102` 绿色，先验收现有行为，不预设重写。
- `23d4827557b532f4eee4fe5511c458ed2b5d8e15` salvage 和 `3fa4d01c` 长设计只读保留。前者增加约 7,919 行仍未闭合，后者增长到千余行且四轮审查未通过，均不得整体采用。
- 唯一增量 HOW 是[Ticket 115 增量架构冻结设计](../design/115-frozen-implementation-design.md)，并受[`AI 编码架构治理`](../../../docs/agents/architecture-governance.md)约束。
- 主人已于 2026-08-26 确认两项残余风险处理。冻结候选 commit 为 `b0d104cde54072adb4bc1f7061d1dc7da68e7c24`，tree 为 `cdae4ace0aa967b3c19567d45ae68fc3e7f237e4`；本票现为 `ready-for-agent`。

## 产品验收

- [ ] TaskEngine 独占任务权威；Skill、模型和 Plugin 只提交候选。主人可以查看、取消、延期或调整普通任务；范围扩大等待当前授权；任务只按自身验收进入四类终态。
- [ ] 每个主人有效当地自然日最多一次复盘；时区变化按下一有效日生效；恢复不补旧日；无行动保持安静。
- [ ] 一次决定形成的业务事实、复盘结果和 outbox intent 原子可见；外部发送只在 finalize 后、SQLite 事务外发生。
- [ ] 每次外发前重新检查当前证据、批准、控制、时间窗、route/config、current head 和 writer fence；旧持有者不能提交或发送。
- [ ] 稳定投递身份以及 formed、business-committed、attempted、interface result、delivered、read、owner action 和 unknown 保持不同事实；低层不能提升为高层或关闭任务。
- [ ] 可能已离站的 unknown 冻结自动重试；状态变化和必要主人决定按当前因果事实至多主动请求一次，且不被普通通知关闭或主动支持暂停吞掉。
- [ ] task/review/delivery 的无正文事实进入既有 StatusProjector；单项失败不自动冒充健康管家全局故障。

## 范围与实施

Ticket 116 的诊断安全和联系人投递、Ticket 117 的删除迁移、Ticket 118 的真实宿主／Weixin 接线、Ticket 119 的生产 canary 与主人验收均不属于本票。fake Adapter 只能证明本地 Plugin/core 行为，不能证明真实渠道送达、已读或幂等能力。

实施 Agent 必须先对 `d468e0a` 做 characterization 差额盘点：已有正确行为保持不动；只有能独立复现的验收缺口才添加失败测试并作最小局部修复。实现后审查只检查产品验收、冻结一致性、回归和证据真实性；新 finding 按治理文件分类，不能直接扩写架构。

至少运行 Ticket 115 专项、受影响的 Ticket 110—114 回归、全量测试、`compileall` 和 `git diff --check`。满足产品验收、必要验证与一致性审查后追加 `## Answer`、设为 `resolved` 并更新 Map。

## 历史说明

旧实现提交 `d1450bc`、`5e94d3c`、`6a25954` 已完成任务、当地日、原子 outbox、分层 owner delivery、当前性重检和 unknown 冻结的主体。历史代码和失败候选均可由 Git 回溯；它们是差额验收证据，不自动构成当前关闭结论。
