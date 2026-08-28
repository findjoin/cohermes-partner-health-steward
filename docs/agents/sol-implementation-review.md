# SOL 有界实施审查

> 当实施 Agent 报告一个已冻结 Ticket 完成，准备由 SOL 做实施后审查或闭票时使用。本规则只审“是否忠实实现冻结合同”，不重新设计产品。架构风险分类与重开举证继续以 [`architecture-governance.md`](architecture-governance.md) 为准；Ticket、冻结设计和冻结验证合同仍是验收权威。

## 1. 审查目标

审查只回答一个问题：当前 `reviewed_commit` 是否完整、真实地实现了冻结设计和验收，且没有破坏既有绿色行为。

以下内容不改变本票 verdict：另一种也合理的架构、理论风险、未来增强、纯代码气味和真实外部环境中尚待后继 Ticket 验证的能力。

## 2. 执行门先于代码审查

SOL 先独立核对：

1. 实施分支有明确最终产品 commit/tree，工作树干净且无未跟踪文件；实现 Agent 已普通推送。
2. 冻结设计、验证合同和 verifier-owned 测试与 Ticket 记录的 blob 完全一致。
3. 原样运行冻结验证命令；全部冻结 Gate 必须通过，不能有 failure、error 或 skip。
4. 运行 Ticket 要求的受影响回归、全量测试、compileall 和 diff check。

任一项失败即返回实施阶段。SOL 只报告精确命令、失败现象和可定位位置，不启动 Spec/Standards 审查，不讨论替代架构，也不把连锁错误拆成多个臆测缺陷。

完成标准：存在一个可复核的绿色 `reviewed_commit`，冻结 blob 未变，全部规定验证通过。

## 3. 固定审查角色

执行门全绿后只启动两个只读 Reviewer：

- **Spec Reviewer**：核对冻结验收 ID、公开行为、现实故障、回归和证据真实性。
- **Standards Reviewer**：核对冻结架构边界、禁止结构、权限旁路、测试作弊和改动局部性。

顶层 SOL 独立运行验证命令并汇总 verdict。Reviewer 不修改文件。未经用户重新决定，不增加重复 Reviewer 或开放式风险搜索。

## 4. 有界阅读范围

Reviewer 阅读：

- 本票实际修改的产品文件；
- 这些修改的直接调用链和冻结文件；
- 为验证现有回归所必需的相邻代码。

Spec 轴只检查冻结验收是否真实成立。Standards 轴只检查实现是否保持已冻结的 Module、Interface、Seam、权威、事务和外部副作用边界，以及是否使用硬编码、测试专用旁路、放宽旧门禁或伪造证据让测试通过。

仓库级重构、旧 Ticket 再审、替代技术路线和与本票无直接因果关系的审计不属于本轮。

## 5. Finding 举证门

一个 finding 只有同时满足以下条件才阻塞：

- 严重度为 P0、P1 或 P2；
- 有可重复命令或最小步骤；
- 有当前代码中的可定位证据；
- 明确指出被破坏的冻结验收 ID、核心不变量或既有已验收行为；
- 现实触发链能够到达错误结果，不只是理论可能或实现偏好。

处理规则：

| Finding | 当前 Ticket 的处置 |
|---|---|
| 冻结 Gate 已复现的产品错误 | 返回实施 Agent，在冻结架构内做最小修复。 |
| Gate 未覆盖但可复现且直接违反既有验收 | 阻止闭票，交 verification authority 判断并形成新冻结 checkpoint；Reviewer 不直接扩门。 |
| 测试合同矛盾或假红 | 交 verification authority 修正并重新双轴冻结；产品门禁保持不变。 |
| 需要新架构、产品决定或外部授权 | 停止并交用户；不由 Reviewer 或实施 Agent自行决定。 |
| 真实 Provider、密钥、旧 VM、渠道或生产迁移证据 | 归既定后继 Ticket，不扩入当前本地实现票。 |
| P3、气味或未来优化 | 不阻塞；最多记录三条，不在本票实施。 |

## 6. 有界修复循环

- 实施 Agent 独占产品修复；Reviewer 始终只读。
- 修复后先重跑完整执行门，再只复核原阻塞 finding。
- 原 finding 关闭后不重新开放风险搜索；完整冻结门中新出现的失败仍按执行门处理。
- 如果修复必须改变冻结文件或架构，立即返回冻结阶段。

完成标准：全部原阻塞 finding 关闭，两轴对同一最终 commit/tree PASS，没有新增且通过举证门的 blocker。

## 7. 停止与闭票

同时满足以下条件后立即停止审查：

- 执行门全部通过；
- Spec Reviewer PASS；
- Standards Reviewer PASS；
- 最终 commit/tree、冻结 blob、测试证据和工作树状态可定位；
- 没有未处置的阻塞 finding。

实施 Agent 不自行闭票。顶层 SOL 只在上述条件成立后追加 Ticket `## Answer`、标记 `resolved`、更新 Map pointer，确认闭票差异仅为元数据，再提交并普通推送。

## 8. 最小审查报告

最终报告只包含：

1. 执行门 verdict 与命令结果；
2. Spec verdict；
3. Standards verdict；
4. 阻塞 findings，或明确“无”；
5. 最多三条非阻塞建议；
6. reviewed commit/tree、冻结 blob、远端分支和工作树状态；
7. 闭票动作或退回对象。

报告不得把未验证事实写成通过，也不得用测试数量代替行为证据。
