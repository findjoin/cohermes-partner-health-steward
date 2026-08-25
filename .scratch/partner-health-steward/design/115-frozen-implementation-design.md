# Ticket 115 增量架构冻结草案

> 状态：等待主人确认。实现基线为 `d468e0ac3e33a37efd53f03328f16dcbc42cff09`；`3fa4d01c` 的长设计和 `23d4827` salvage 只作历史取证，不是实施路线。本草案适用 [`AI 编码架构治理`](../../../docs/agents/architecture-governance.md)。

## 目标与范围

在现有健康 Plugin/core 上闭合健康任务、主人当地日复盘和分层主人投递。Ticket 116 的诊断安全与联系人链、Ticket 117 的删除迁移、Ticket 118 的真实 Hermes/Weixin 接线以及 Ticket 119 的生产验收不在本票实现。

## 保留的现有架构

```text
健康命令／唤醒
  -> Plugin
  -> HealthCore（唯一业务裁决与写入）
       -> TaskEngine / DailyReviewEngine / OwnerDeliveryEngine
       -> 受管 SQLite + 既有 current-head/writer-fence 协议
  -> finalize 后的受控投递效果
  -> OwnerDeliveryWireAdapter
  -> 外部 Weixin
```

Task、Review、Delivery 是 core 内部 Module；Plugin/core 的健康命令、受控效果和受管读取仍是稳定 Interface。生产与 fake delivery Adapter 共用外部 Seam。不新增服务、数据库、第二写入者或第二份 durable truth。

## 冻结决定

| 方面 | 决定 |
|---|---|
| 权威 | TaskEngine 独占任务目的、承担者、允许资料／效果、阶段、验收、四标签、查重与后继；DailyReviewEngine 独占复盘记录；OwnerDeliveryEngine/outbox 独占本地投递意图与已知层级。Skill、模型、Plugin 和 Adapter 只能提交候选、执行获准效果或回交观察。 |
| 事务 | 一次业务决定同时形成的本地事实、复盘结果和 outbox intent 使用现有 prepared → current-head CAS/readback → local finalize 路径同成同败。finalize 前不得调用 Adapter。 |
| 任务 | `active / solved / failed / cancelled` 仍是唯一主标签；等待、延期、能力缺口和外部 unknown 是附加事实。主人可取消、延期或调整普通任务；扩大目的、负担、资料、接收方、外部效果或验收时建立关联任务并等待当前授权。终态只由当前任务验收证据形成。 |
| 复盘 | 每个 owner、installation、实际生效时区和当地自然日最多一次已提交复盘；恢复只处理当前日，不补旧日。无行动复盘不形成 outbox。 |
| 外发 | Adapter 在 SQLite 事务外执行。调用前重新检查当前证据、批准、独立控制、时间窗、route/config、current head 和 writer fence。formed、business-committed、attempted、interface result、delivered、read、owner action 与 unknown 不互相冒充。 |
| unknown | 可能已经离站但结果无法证明时保存 unknown 并冻结自动重试；新的尝试需要新的当前因果决定。明确证明未被接口接受的结果可在当前授权与控制内采用有界重试，具体策略保持可逆。 |
| 状态与请求 | task/review/delivery 只向 Ticket 114 StatusProjector 提供无正文业务事实；单项任务或投递异常不自动升级为全局故障。状态变化或当前推进确实需要主人决定时，按因果事实通过现有 outbox 至多主动请求一次，不另建 mandatory ledger。 |

主人经唯一准入入口明确报告自己已经行动，可作为 owner-action 层证据；它不证明健康改善，也只有在该行动正是任务验收时才能支持 `solved`。

## 本票必须控制的故障

- 重复命令、并发唤醒或重启不能为同一目标／当地日／因果效果生成第二份当前业务结果。
- prepare、current-head CAS/readback 或 finalize 崩溃／未知时，只恢复既有决定或停止；不能部分可见，也不能提前外发。
- 证据、批准、控制、时区、route/config 或 writer fence 在执行前失效时，旧任务持有者和旧 intent 不能提交或发送。
- Adapter 调用异常、响应丢失或发送后本地终态提交失败时，保留可能已离站的 unknown，不能再次自动调用 transport。
- 低层交付事实、Cron 完成、模型／Skill 候选和调用者文本不能越权关闭任务、提升交付层级或改变全局状态。

## 兼容、实施自由与停止

保留 `d468e0a` 已有 Ticket 110—115 持久事实、Plugin/core Interface 和 current-head/ExecutionLease 合同；只有实际 characterization 证明现有数据无法满足上述冻结决定时，才设计最小迁移。不得整体合并 salvage。

字段、hash、codec、私有 schema、claim 的具体实现、helper、文件布局、测试文件数量和实施 checkpoint 均未冻结。编码 Agent 先运行现有行为测试并做差额盘点；现有绿色行为直接保留，只为可复现缺口添加红测和最小局部修复。

行为验证以 Plugin → core Interface 和 fake Adapter 为主，覆盖产品结果及上述五类故障，不建立 Case registry，也不以测试数量作为完成标准。全部验收和必要回归通过、没有符合治理文件举证门的结构性 blocker 后进入一致性审查；另一种也合理的实现偏好不能重开架构。
