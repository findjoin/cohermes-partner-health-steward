# 115 - 实现任务当地日复盘与分层主人投递

Type: task
Status: ready-for-agent
Parent: [健康管家首发 TO、CAN 与 HOW 决策闭合路线](../map.md)
Blocked by: [113 - 实现 StrictHealthLLM 治理知识与非诊断回答](113-implement-strict-health-llm-governed-knowledge-and-nondiagnostic-answer.md), [114 - 实现主人设置数据权利与业务状态](114-implement-owner-settings-data-rights-and-business-status.md)

**What to build:** 让健康管家根据主人目标、画像/证据变化和既有任务事件建立可验收任务，并按主人当地自然日运行复盘、生成 outbox 意图和分层主人 Weixin 投递。任务、业务提交、发送尝试、接口接受、送达、已读和未知必须保持不同事实。

**Blocked by:** 113 - 实现 StrictHealthLLM 治理知识与非诊断回答; 114 - 实现主人设置数据权利与业务状态

- [ ] `TaskEngine` 独占任务目的、承担者、允许资料、阶段、批准、验收、四类主标签、查重和后继关系；Skill 和模型只能返回候选。
- [ ] 每个主人当地自然日最多一次复盘；时区变化从下一有效当地日开始，不补做、堆积或重复旧日；无行动保持安静。
- [ ] 任务在发送前重新检查当前证据、批准、控制、时间窗、重复关系和 writer fence；失效或撤回不生成旧效果。
- [ ] 业务事实和 transactional outbox 意图原子提交；发送在事务外执行并记录形成、提交、尝试、接口接受、送达/已读和未知层级。
- [ ] Weixin 发送使用稳定幂等标识；未知或可能已离站的效果冻结自动重试，不能把接口无错改写为主人已看到或任务 solved。
- [ ] 合成测试覆盖复盘恢复、任务 claim/lease、控制竞态、outbox 崩溃、重复投递、未知回查和状态投影。

