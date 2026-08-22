# 110 - 建立 Plugin/core 受信边界与合成验证骨架

Type: task
Status: claimed
Parent: [健康管家首发 TO、CAN 与 HOW 决策闭合路线](../map.md)
Blocked by: None - can start immediately

**What to build:** 建立一个可被合成测试驱动的 Partner Health Plugin 与低权限 `health-core` 基础边界。Plugin 只能通过受限私有接口发送带来源、因果 ID、generation 和允许范围的健康命令；core 负责唯一受管写入、受控效果意图和 content-free contract probe。首发本地受管状态使用加密 SQLite，外部 current head 使用不透明的单区域 DynamoDB 条件写入抽象和 writer fence；本票只使用合成依赖，不配置真实资源。

**Blocked by:** None - can start immediately

- [ ] 私有接口只接受允许的动作、字段、generation 和权限范围，错误 peer、未知动作、缺字段、截断帧和不完整结果均失败关闭。
- [ ] core 建立加密 SQLite 受管状态域、专用密钥边界和候选/准备/最终/未知状态区分；普通 Hermes Session、Memory、日志、cache 和 transcript 不得成为写入者。
- [ ] current-head 客户端以不透明 installation/generation、revision digest、transition ID、writer fence 和 terminal 标志表示条件读写，并能在合成冲突/超时/未知时停止健康读写、模型和外发。
- [ ] Plugin/core contract probe 能报告健康路径可用、异常或无法确认；普通 Hermes 的非健康运行不被误报为健康可用。
- [ ] 建立只含无内容合成数据的协议、幂等、崩溃和未知故障测试骨架。
