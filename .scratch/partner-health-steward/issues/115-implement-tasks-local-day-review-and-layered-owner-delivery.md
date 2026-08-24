# 115 - 实现任务当地日复盘与分层主人投递

Type: task
Status: claimed
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

## Implementation evidence (unreviewed)

本节是实施 Agent 的交审证据，不是独立验收结论；本票保持 `claimed`，未操作服务器或真实 Weixin。

- `TaskEngine` 独占候选准入、目的/承担者/允许资料、阶段、claim/lease、批准、验收证明、四类主标签、查重和后继关系；验收绑定当前证据卡 revision digest，重启后仍保留完整终态证明。主人取消与任务状态在同一原子提交中闭合。
- `DailyReviewEngine` 以 owner、installation、时区和当地自然日形成账本；同日恢复只重算当前事实，旧日不补做，无变化不生成通知。复盘业务事实和 owner-delivery outbox 意图由 Ticket 115 prepared/commit/finalize 链原子提交。
- 发送前重新核验当前证据、批准、独立主人控制、联系窗口、当前当地日、route/disclosure 配置代际、重复尝试和 writer fence。合法 route generation 更新并重新同意后使用当前代际；旧代际意图失败关闭。
- Plugin 只通过 wire-shaped health command、controlled effect 和 managed read 接缝调用 core。适配器在 SQLite 事务外执行；稳定幂等键绑定完整权威意图，形成、提交、尝试、接口接受、送达、已读和未知保持独立事实。
- `prepared -> authorized-in-flight` 短时两阶段 marker 防止 managed read 把正常 handoff 误判为 orphan，也原子阻止并发/重复授权。适配器已发送但终态提交失败时保留 in-flight marker，TTL/重启恢复只冻结为 `unknown`，不会第二次调用 transport。
- 实现提交：`d1450bc`（任务、复盘和投递主体）、`5e94d3c`（发送前当前性加固）、`6a25954`（wire authority、原子恢复、路由代际和重复发送竞态闭合）。
- `python -m unittest discover -s tests -p "test_ticket115_*.py"` -> `Ran 102 tests in 73.756s ... OK`。
- `python -m unittest discover -s tests` -> `Ran 675 tests in 216.122s ... OK`。
- `python -m compileall -q partner_health_steward tests` -> exit `0`；`git diff --check` -> exit `0`，仅有既存 LF/CRLF 转换提示，无 whitespace error。
- 验证环境：Python `3.11.6`、SQLite `3.42.0`、`cryptography 3.3.1`。证据只覆盖本地合成 Plugin/core；真实 Hermes、Weixin、模型、部署和生产 canary 仍由后继 Tickets 验收。
