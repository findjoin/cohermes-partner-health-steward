# 114 - 实现主人设置数据权利与业务状态

Type: task
Status: ready-for-agent
Parent: [健康管家首发 TO、CAN 与 HOW 决策闭合路线](../map.md)
Blocked by: [111 - 实现唯一准入与主人初始化](111-implement-unique-admission-and-owner-initialization.md), [112 - 实现七 Skill 协调与日常证据画像处理](112-implement-seven-skill-coordination-and-daily-evidence-portrait-turn.md)

**What to build:** 让主人通过 `health-settings` 真实查看和控制健康管家，并看到由业务事实聚合出的 active、abnormal 或 cannot-confirm 状态。设置、停止记录、暂停主动支持、任务取消、批准撤回、查看、纠正和导出必须是相互独立的权威命令，不得由 Skill 或模型自行宣布生效。

**Blocked by:** 111 - 实现唯一准入与主人初始化; 112 - 实现七 Skill 协调与日常证据画像处理

- [ ] 支持时区、联系时间、表达方式、主动联系偏好和五类普通通知偏好的独立查看/修改，并显示时区生效时间和下一有效当地日规则。
- [ ] 暂停主动支持、停止新增记录、任务取消、外部批准撤回和联系人控制互不合并；停止记录期间不新增个人健康正文、不倒填恢复前缺口。
- [ ] 查看、纠正和导出只读取当前受管对象，保持证据引用、版本和权限边界，不经过普通聊天形成第二份权威。
- [ ] `StatusProjector` 只从入口、启用、密钥/状态、证据、任务、控制、模型、投递、安全和 current head 的业务事实聚合三态；进程存活、Cron 或 heartbeat 不能冒充 active。
- [ ] 设置请求缺少必需上下文、权限或当前代际时失败关闭，并给出可确认/无法确认而不是模型自述的结果。
- [ ] 合成测试覆盖控制并发、时区切换、停止记录与恢复、查看/导出权限、纠正版本和状态投影。

