# 110 - 建立 Plugin/core 受信边界与合成验证骨架

Type: task
Status: resolved
Parent: [健康管家首发 TO、CAN 与 HOW 决策闭合路线](../map.md)
Blocked by: None - can start immediately

**What to build:** 建立一个可被合成测试驱动的 Partner Health Plugin 与低权限 `health-core` 基础边界。Plugin 只能通过受限私有接口发送带来源、因果 ID、generation 和允许范围的健康命令；core 负责唯一受管写入、受控效果意图和 content-free contract probe。首发本地受管状态使用加密 SQLite，外部 current head 使用不透明的单区域 DynamoDB 条件写入抽象和 writer fence；本票只使用合成依赖，不配置真实资源。

**Blocked by:** None - can start immediately

- [x] 私有接口只接受允许的动作、字段、generation 和权限范围，错误 peer、未知动作、缺字段、截断帧和不完整结果均失败关闭。
- [x] core 建立加密 SQLite 受管状态域、专用密钥边界和候选/准备/最终/未知状态区分；普通 Hermes Session、Memory、日志、cache 和 transcript 不得成为写入者。
- [x] current-head 客户端以不透明 installation/generation、revision digest、transition ID、writer fence 和 terminal 标志表示条件读写，并能在合成冲突/超时/未知时停止健康读写、模型和外发。
- [x] Plugin/core contract probe 能报告健康路径可用、异常或无法确认；普通 Hermes 的非健康运行不被误报为健康可用。
- [x] 建立只含无内容合成数据的协议、幂等、崩溃和未知故障测试骨架。

## Answer

已建立可由纯合成依赖驱动的 Plugin/core 受信边界：严格协议与 action scope、完整 typed authority、加密 SQLite 单写状态、原子业务记录/receipt、带 writer-fence 证明和 transition 回查的 current-head 状态机、content-free probe，以及由 core 生成并经执行 lease 回交终态的受控 `model-work` intent。任何本地 finalized authority、installation、revision、writer fence、current-head 或完整性事实不一致时，健康写入、模型和外发均失败关闭。

本票只实现合成骨架，不配置真实 socket、DynamoDB、模型或投递资源。`owner-delivery` 和 `contact-delivery` 在具备业务提交、outbox、当前批准及投递 receipt 前保持禁止。

## Comments

- TDD red→green：补齐跨 installation prepare、writer-fence 持有、CAS 响应丢失回查、业务记录与 receipt 原子提交、等价 causal replay、临时故障恢复、严格字段类型、exact scope、受控 effect、transition/terminal、跨 clone 因果归属、close handoff 与端口输入变异等负向合成场景。
- TDD red→green：直接 `contact-delivery` intent 原可被构造、写入和领取；现已在 intent、存储、claim 与 capability binding 边界统一拒绝。
- TDD red→green：`prepare@F1` 原可被伪造成 `committed@F2` 并最终得到 healthy probe；现已在 `CommittedTransition`、存储重验证和 core authority 匹配三层拒绝。
- 最终验证：`python -m unittest discover -v`，135/135 通过；`python -m compileall -q partner_health_steward tests` 通过；`git diff --check` 通过。
- 仓库未配置且本机各 Python 环境均未安装 mypy/pyright，因此未引入新依赖；严格运行时类型回归与 compileall 已通过。Standards、Spec 与负向边界复审均无完成阻塞。
