# 115 - 实现任务当地日复盘与分层主人投递

Type: task
Status: needs-info
Parent: [健康管家首发 TO、CAN 与 HOW 决策闭合路线](../map.md)
Blocked by: [113 - 实现 StrictHealthLLM 治理知识与非诊断回答](113-implement-strict-health-llm-governed-knowledge-and-nondiagnostic-answer.md), [114 - 实现主人设置数据权利与业务状态](114-implement-owner-settings-data-rights-and-business-status.md)

**What to build:** 让健康管家根据主人目标、画像/证据变化和既有任务事件建立可验收任务，按主人当地自然日复盘，并以原子 outbox 和分层主人 Weixin 投递推进必要行动。任务、业务提交、发送尝试、接口接受、送达、已读、主人行动和未知必须保持不同事实。

## 当前门禁

- 产品实现基线固定为 d468e0ac3e33a37efd53f03328f16dcbc42cff09。
- salvage 23d4827557b532f4eee4fe5511c458ed2b5d8e15 只读保留，不得合并或整体 cherry-pick。
- 唯一实施 HOW 为[Ticket 115 冻结实施设计](../design/115-frozen-implementation-design.md)。
- 本票保持 needs-info，直到该设计经六轴审查、记录精确 frozen content commit/tree，并由主人确认。此前不得修改产品代码。
- 冻结后只允许按设计分 checkpoint 实施；编码 Agent 无权另选状态机、事务、权限、兼容或模块路线。

## 产品验收

- [ ] TaskEngine 独占任务目的、承担者、允许资料、阶段、批准、验收、四类主标签、查重和后继；Skill、模型和 Plugin 只能提交候选。
- [ ] 每个 owner + installation + effective timezone + local date 最多一次复盘；时区从下一有效当地日起生效，不补做旧日；无行动保持安静。
- [ ] 任务和投递执行前重新检查当前证据、批准、独立控制、时间窗、route/config/disclosure、current head 与 writer fence。
- [ ] 业务事实、review、mandatory request 和 outbox intent 在同一 prepared → current-head CAS → local finalize 中可见；Adapter 只在 finalize 后、SQLite 事务外执行。
- [ ] 投递使用稳定身份，严格区分 formed、business-committed、attempted、interface result、delivered、read、actual-action 和 unknown。
- [ ] 可能已经离站但结果未知的效果冻结自动重试；主人承担重复风险只能建立新的有界因果效果。
- [ ] task、review、delivery 的无正文能力事实进入 Ticket 114 StatusProjector；状态变化和必要主人决定各 causal state 至多形成一次 request。
- [ ] 合成验证覆盖任务、当地日、权限竞态、CAS/readback/finalize、外部效果不可逆点、重复/未知、兼容升级、状态与 mandatory request。

## Acceptance matrix

| ID | Required observable result | Forbidden substitute |
|---|---|---|
| 115-A1 | 同一 goal 查重；完整保留任务目的、阶段、批准、验收、四标签和后继；延期/普通调整留痕；范围扩大建立 linked waiting-approval 任务并只消费 Ticket 114 当前精确批准 | 每个 Skill 步骤建任务；调用者自批；旧批准跨 scope；静默扩大原任务；任务标题冒充事实 |
| 115-A2 | solved、failed、cancelled 只按冻结设计的 typed business result 与确定性终态规则形成；等待、延期、能力缺口和 unknown 保持 active 的独立事实 | accepted、sent、Cron 完成、提醒形成或任意 owner 文本冒充 solved/failed/action |
| 115-A3 | 每个 LocalDayKey 至多一个 committed review；时区按 Ticket 114 transition 生效；恢复只重算当前日；quiet review 无 outbox | owner generation、服务器日期、固定 24 小时、旧日 backlog、每天强制通知、今天未跑即 fault |
| 115-A4 | task/review/delivery/mandatory 与 intent 原子可见；未知 CAS 强读回查；finalize 前无 DispatchPlan/Adapter | 先发送后落库、部分聚合可见、适配器直接写任务、CAS 未确认仍外发 |
| 115-A5 | 每个 effect 有稳定 intent/execution/attempt/idempotency；各层 append-only 且只接受该层权威证明；armed 不等于 attempted | no-error=送达、accepted=已读、Adapter 伪造 delivered/action、重复回交覆盖旧事实 |
| 115-A6 | TaskClaimLease 使用 runtime epoch/单调时钟/task CAS；Ticket 110 ExecutionLease 不变；发送前完成最后 currentness 检查；armed/unknown 后不自动重试 | 第二 claim 真相、跨 epoch 比较时间、claim 授权业务、改 ExecutionLease、过期 holder、unknown 盲重试 |
| 115-A7 | tasks/review/delivery capability facts 保持无正文；单项业务结果与核心能力健康分离；Ticket 114 business_status 的一次性跨重启 transition 保持 | heartbeat=active、task failed=task core fault、单次 delivery unknown=全局 fault、missing-today=review fault |
| 115-A8 | status-change、authorization、unknown-risk、capability-gap 各 immutable causal state 至多一个 MandatoryRequest；普通通知关闭/主动支持暂停不吞掉，route 不可用先 pending | 另建 mandatory ledger、按 task version/时间重复催促、假 recipient、绕过 terminal/owner/install/consent/route |

验收以可观察行为、不变量、权限边界和崩溃耐久点为单位，不固定测试总数，也不把标点拆成 Case registry。每条冻结设计不变量和崩溃真值表行必须至少有一个可独立失败的行为测试。

## 实施协议

1. 只有本票记录 frozen design content commit/tree 后，才把 Status 改为 ready-for-agent。
2. 编码 Agent 从该门禁提交开始，严格执行设计 CP1 → CP5；每个 checkpoint 先红测、最小实现、定向与累积回归、独立 commit。
3. salvage 只可按设计第 12 节人工选择；每项记录来源、采用条款和目标文件。禁止整体 cherry-pick。
4. 若出现冻结设计未覆盖的新事实，只能在它可复现且足以使路线不可实现、不安全或破坏 d468e0a 兼容时停工；保存 checkpoint，退回设计 amendment。不得在编码中自行改路线。
5. 实施 Agent 在本票追加 Implementation evidence (unreviewed)，记录 design identity、checkpoint commits、行为映射、测试与环境；不得自行把测试绿色解释为设计已通过。
6. 最终 fresh-context reviewer 只做 implementation fidelity、回归和证据真实性审查，不重新选择技术路线。风格、可选重构和另一种也可行的偏好不能阻止关票。
7. fidelity 通过后只允许追加 Answer、更新 Map 和 Status；任何产品代码、测试、schema 或配置变化都会使 verdict 失效。

## 验证

- python -m unittest discover -v -s tests -p "test_ticket115_*.py"
- python -m unittest discover -v -s tests -p "test_ticket11[0-4]*.py"
- python -m unittest discover -v
- python -m compileall -q partner_health_steward tests
- git diff --check

必须另外核对未跟踪文件、commit/tree、Python、SQLite 和 cryptography 版本。fake Adapter 只证明本地合成 Plugin/core；真实 Hermes、Weixin、模型、部署、医学审核、canary 和主人验收继续属于后继 Tickets。

## 历史基线，不构成当前验收

d1450bc、5e94d3c、6a25954 曾按旧六项宽合同实现任务、当地日、outbox 和 fake delivery；当时专项 102 项、全量 675 项为绿色。后来扩大合同后形成的 salvage 又增加约 7,919 行并仍有未闭合 finding，证明“先大面积实现、再开放式重审路线”不可继续。

历史代码与测试仍在 d468e0a，可由 Git 回溯；历史复审只证明当时合同，不替代本票 A1—A8 和冻结设计。当前恢复是以 d468e0a 为基线的有边界增量实施，不从 salvage 继续，也不宣称现有 Ticket 115 已完成。
