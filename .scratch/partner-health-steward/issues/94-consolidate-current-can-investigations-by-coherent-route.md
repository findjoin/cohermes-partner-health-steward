# 【CAN】按连贯技术问题压缩并重接剩余能力调查

Type: task
Status: resolved
Parent: [健康管家首发 TO、CAN 与 HOW 决策闭合路线](../map.md)
Blocked by: [【CAN】重建完整 TO 的能力链与追溯关系](76-rebuild-complete-to-capability-chain-and-traceability.md), [【CAN】核验当前 Partner Hermes 基线、Plugin 生命周期与可信执行边界](78-verify-current-partner-hermes-baseline-plugin-lifecycle-and-trust-boundary.md), [【CAN】核验健康能力入口、初始化门禁与真实结果返回能力](79-verify-health-capability-entry-initialization-gate-and-result-contract.md), [【CAN】核验唯一微信准入、排他分流、逐次来源与重投结果能力](80-verify-unique-weixin-admission-routing-provenance-and-replay-results.md), [【CAN】核验受管健康状态数据平面、保护隔离与单一权威能力](81-verify-managed-health-state-plane-protection-and-single-authority.md), [【CAN】核验紧凑六域健康画像与三类证据卡的维护追溯能力](82-verify-six-domain-portrait-and-three-class-evidence-capabilities.md)

## Question

在保持已经确认的 `TO → CAN → HOW` 规则、完整 TO 能力链和已完成 CAN 事实不变的前提下，怎样把当前按单一能力节点拆出的剩余 CAN 调查合并为少量、各自可在一个 Ticket 会话内完成的连贯技术问题，使 CAN 仍完整覆盖全部 TO 节点，但不再要求每个能力节点各自经历一张调查票？

本票只重组调查粒度和依赖：保留已经解决的 CAN Answer 与证据；用现有未解决票中的少量票承接合并后的核心框架、模型与非诊断问答、医学与辅助诊断三组调查；其余被吸收票保留为 `wontfix` 历史输入并明确后继；完整 CAN 闭合票只依赖重组后的现行调查。不得在本票调查能力、选择 HOW、修改 TO、删除历史票或让合并后的 Question 失去可判定的完成条件。

## Answer

`TO → CAN → HOW` 的阶段语义保持不变：TO 已定义完整产品；CAN 只调查当前事实、候选能力、限制与未知；完整 CAN 闭合后才由 HOW 选择最终技术路线。本次只把“能力节点”与“调查票”解耦，十七个能力节点及其 TO 追溯全部保留，不再机械要求每个节点一张票。

当前映射调整为：

| 能力节点 | 当前承接票 |
| --- | --- |
| C01 | [【CAN】核验当前 Partner Hermes 基线、Plugin 生命周期与可信执行边界](78-verify-current-partner-hermes-baseline-plugin-lifecycle-and-trust-boundary.md) |
| C02 | [【CAN】核验健康能力入口、初始化门禁与真实结果返回能力](79-verify-health-capability-entry-initialization-gate-and-result-contract.md) |
| C03 | [【CAN】核验唯一微信准入、排他分流、逐次来源与重投结果能力](80-verify-unique-weixin-admission-routing-provenance-and-replay-results.md) |
| C04 | [【CAN】核验受管健康状态数据平面、保护隔离与单一权威能力](81-verify-managed-health-state-plane-protection-and-single-authority.md) |
| C05 | [【CAN】核验紧凑六域健康画像与三类证据卡的维护追溯能力](82-verify-six-domain-portrait-and-three-class-evidence-capabilities.md) |
| C06、C07、C14、C15、C16 | [【CAN】核验健康任务与受管运行框架的生命周期、复盘投递、主人控制、三态观测及迁移能力](83-verify-open-health-task-lifecycle-dispatch-acceptance-and-scope-approval.md) |
| C08、C17 | [【CAN】核验首跳模型路线、主人派生查询隔离与非诊断健康问答结果链](85-verify-first-hop-model-route-and-owner-derived-query-isolation.md) |
| C09、C10、C11、C12、C13 | [【CAN】核验明确诊断范围候选形成、准入与诊断全链能力](86-verify-medical-content-governance-and-diagnostic-scope-candidates.md) |
| C01—C17 的最终覆盖审计 | [【CAN】闭合完整能力与约束事实并形成当前 CAN 报告](77-close-complete-capability-and-constraint-report.md) |

已经解决的五张基础 CAN Answer 与证据保持原样。原先尚未调查的八张细分票——当地自然日复盘、诊断上下文、诊断安全、诊断修订、主人权利、三态观测、完整迁移、非诊断问答——均保留原 Question，但标记为 `wontfix` 并明确当前承接票；它们没有 Answer，不构成负向 CAN，也不计研究轮次。

三张现行研究票各自限定了共享候选面、代表性场景、必须逐节点报告的事实矩阵和单会话停止条件，因此合并不会把问题变成不可判定的宽泛调查。当前唯一顺序是：先调查模型路线与非诊断问答，再调查明确范围与诊断全链，最后用前两组结果调查统一任务、控制、三态与迁移框架；之后由 CAN 闭合票综合全部节点。诊断全链票必须在同一票中尝试明确命名并深审一项范围候选，不再为了粒度另建范围专票；若固定清单无法产生候选或没有合格范围，该票可以形成完整负向事实，但完整 CAN 仍不得按零范围闭合，后继须调查实质不同的完整诊断链候选，累计三轮实质不同的调查仍为负向时才执行 Map 的可行性说明规则。

本次没有调查任何新能力、没有选择 provider、数据库、Plugin 组织、Skill 数量、模型、医学来源组合、监控或迁移 HOW，也没有删除或改写历史 Answer。当前剩余独立 CAN 研究票从十一张压缩为三张，之后仍由唯一 CAN 闭合票把事实汇总成不含技术选型的完整报告。

## Comments

### 2026-08-20 — 后继票修正病种研究循环

[【CAN】修正未实现系统的能力判定、诊断范围门禁与负向研究计数](97-correct-can-preimplementation-feasibility-and-diagnostic-scope-gate.md)保留本 Answer 对十七个节点和调查票粒度的压缩，但取代“没有已激活诊断范围就不能闭合 CAN、必须继续更换病种直至形成三轮负向研究”的阶段结论。尚未实现、取得许可、完成医学审核、验收或激活是后继条件；只有实质不同的支持路线被一手证据排除，才构成负向 CAN 轮次。
