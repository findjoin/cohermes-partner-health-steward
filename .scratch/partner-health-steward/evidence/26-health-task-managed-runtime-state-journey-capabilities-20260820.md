# 健康任务与受管运行框架完整状态旅程能力核验

- 调查日期：2026-08-20
- 对应票：[Ticket 83](../issues/83-verify-open-health-task-lifecycle-dispatch-acceptance-and-scope-approval.md)
- 工作树基线：`5f358137309d7670e7ad615c8af9d1aa679a49e3`；本报告把其未提交候选统一标为 `WORKTREE`，不视为已部署能力
- 调查边界：只读固定源码、脱敏现场证据、当前工作树和合成测试；未发送真实微信、未调用真实模型、未使用真实健康资料，未做删除、旧 VM 恢复、时间边界、故障注入或源—目标迁移演练

## Answer

**不能。C06、C07、C14、C15、C16 在当前 `LIVE` 均未形成，当前 `WORKTREE` 也不能共同证明一套以同一受管权威状态为中心的健康任务与运行框架。** 现场 Partner Hermes 没有健康 Plugin、健康 profile manifest 或业务 Cron；因此工作树测试通过不能上升为现行能力。[LIVE 基线](19-current-partner-hermes-baseline-plugin-lifecycle-trust-20260820.md#answer)

工作树确有若干可复用但彼此独立的原语：有目的、证据、时间和策略校验的候选任务；当地日 04:00 复盘与一次 +10 分钟重试；微信发送 `accepted/rejected/uncertain` 账本且未知不盲重发；查看、导出、暂停、停止记录和两次确认删除；作业/服务监控；发布文件哈希与主状态备份恢复。但一条代表性旅程给出了四个确定性反例：

1. `pause_proactive_contact` 和 `stop_health_recording` 都会把全部未终结任务直接改为 `cancelled`，违反“暂停只停主动联系、停止记录与任务取消相互分离”；
2. 删除候选引入 10 分钟确认窗、固定 30 天备份清理和“永久删除”终态通知，而当前产品合同明确不得新增这些承诺；它也未证明所有受控副本与旧 VM 均不能复活；
3. 监控可在 `production_acceptance=blocked` 时仍报告 `service_health=healthy`，且不观察画像、任务、控制、入口、模型、安全、问答和诊断范围的统一业务三态；
4. `restore_backup()` 只替换主加密状态 blob，发布 manifest 只覆盖发布文件；两份投递账本、审计、投影、资料缓存、批准/未知/删除状态、产品文档和 Skill 没有作为同一语义代际迁移。

因此这张 CAN 票可用**负向结论**闭合：现有固定 Hermes 和工作树只能提供局部机制，不能证明完整 TO 能力，也不能据此选择状态机、调度器、存储、监控或迁移 HOW。后续若进入 HOW，必须显式消除上述合同冲突并建立统一状态与验收边界，而不是把现有工具拼接即视为实现。

## 1. 证据等级与继承事实

| 等级 | 本报告含义 | 本轮事实 |
|---|---|---|
| `LIVE` | 2026-08-20 已脱敏核验的正式 Partner Hermes | v0.20.0 固定提交 `3c27...`；健康 Plugin、profile manifest、业务 Cron 均为 0；普通 Telegram/微信通道存在不等于健康能力存在。[Evidence 19](19-current-partner-hermes-baseline-plugin-lifecycle-trust-20260820.md#answer) |
| `FIXED-SOURCE` | 固定 Hermes 官方源码/文档能证明的通用表面 | Plugin 失败可降级继续基础 Hermes；Cron 有运行尝试终态和 `unknown` 不自动重跑；这些是宿主机制，不是健康任务、每日业务复盘或三态产品合同。[Plugin 固定源码](https://github.com/NousResearch/hermes-agent/blob/3c27eb6234bf91b8ceee9e9071591b31e9b148cb/hermes_cli/plugins.py#L1611-L1689)、[Cron 固定文档](https://github.com/NousResearch/hermes-agent/blob/3c27eb6234bf91b8ceee9e9071591b31e9b148cb/website/docs/user-guide/features/cron.md#L234-L273) |
| `WORKTREE` | 当前未提交候选源码 | 下文逐项静态核验；不得冒充部署状态 |
| `TEST` | 合成、临时目录、无真实健康/微信/模型的本地测试 | 只证明被测候选分支在该输入下运行，不证明现场部署、主人真实到达或完整跨故障域语义 |
| `UNRUN` | 需另行批准且本轮未执行 | 真实微信、真实时间边界、故障注入、删除与旧状态恢复、密钥操作、双环境迁移/切换 |

本票还继承以下已解决前提：当前唯一微信准入只证明静态白名单，接口接受不证明主人到达；当前没有已部署受管健康状态平面；六域画像/三类证据、首跳模型链和完整诊断范围也未在现场形成。[Evidence 21](21-unique-weixin-admission-routing-provenance-replay-results-20260820.md#answer)、[Evidence 22](22-managed-health-state-plane-protection-and-single-authority-20260820.md#answer)、[Evidence 23](23-six-domain-portrait-and-three-class-evidence-capabilities-20260820.md#answer)、[Evidence 24](24-first-hop-model-route-owner-derived-query-isolation-nondiagnostic-answer-results-20260820.md#answer)、[Evidence 25](25-named-diagnostic-scope-governance-and-full-chain-capabilities-20260820.md#answer)

## 2. 一条代表性端到端状态旅程

| 旅程步骤 | 当前真正证明的效果 | 合同所需但缺失/相反的效果 | 判定 |
|---|---|---|---|
| 1. 依据画像/证据建立任务 | 候选校验目的、证据 ID、时间、策略和当前 source card，初始状态为 `candidate`。[tasks.py](../../../ops/partner-health-steward/sidecar/tasks.py#L809-L1021) | 没有承担者、可判定验收、阶段/批准、四项职责写权限、前后继关系和 `active/solved/failed/cancelled` 权威模型 | `WORKTREE-PARTIAL` |
| 2. 阶段推进与外发 | dispatch 可把候选推进到发送，并记录跳过、失败或 `sent`。[dispatch.py](../../../ops/partner-health-steward/sidecar/dispatch.py#L588-L634) | `sent` 是接口处理结果，不是任务验收、主人行动或健康改善；也没有主人延期/调整/取消单项任务的表面 | `WORKTREE-PARTIAL` |
| 3. 当地日边界复盘 | 04:00 当地日、同日一次完成、失败后一次 +10 分钟重试，无通用补积压。[tasks.py](../../../ops/partner-health-steward/sidecar/tasks.py#L535-L752) | 未证明五类可独立通知、不可关闭通知、主人查询最近结论、时区改变后的统一重判；现场业务 Cron 为 0 | `WORKTREE-PARTIAL / LIVE-ABSENT` |
| 4. 一次发送结果未知 | 投递账本把 `in_flight/uncertain` 保持为终态并阻止同键重发。[weixin_delivery.py](../../../ops/partner-health-steward/sidecar/weixin_delivery.py#L1077-L1095) | 未知没有贯穿任务验收、主人可见状态和全局三态；更不能证明主人真实到达 | `WORKTREE-PARTIAL` |
| 5. 主人暂停主动支持 | 控制命令可进入 paused 状态。[owner_controls.py](../../../ops/partner-health-steward/owner_controls.py#L75-L129) | 实现同时遍历全部未终结任务并改为 `cancelled`，与分离控制直接冲突。[store.py](../../../ops/partner-health-steward/sidecar/store.py#L2963-L3099) | `WORKTREE-CONTRADICTION` |
| 6. 主人停止新增记录 | 可等待当前写入并设 stopped | 同样取消全部未终结任务；未证明停止期间仅临时回答/危险处置、不新建任务、恢复不倒填。[store.py](../../../ops/partner-health-steward/sidecar/store.py#L2191-L2417) | `WORKTREE-CONTRADICTION` |
| 7. 主人取消任务/撤回执行批准 | 未找到单项取消、延期、调整或执行批准撤回的权威 API | 不能证明未开始动作不发、已发/未知动作不重试且保留真实外部效果 | `ABSENT` |
| 8. 一个核心故障发生 | operator monitor 读审计、日复盘和 dispatcher 心跳，并能发 firing/recovered 告警。[operations.py](../../../ops/partner-health-steward/sidecar/operations.py#L341-L467) | 没有跨画像、任务、控制、入口、模型、安全、问答、诊断范围的 `active/abnormal/unconfirmable` 传播；测试明确允许验收 blocked 而服务 healthy | `WORKTREE-CONTRADICTION` |
| 9. 源端搬到目标端 | release 文件可哈希；旧 Hermes profile 可 `copytree`；主状态 blob 可备份恢复 | 没有完整资产清单、状态语义代际、源目标单写权威、引用/批准/终态/未知保真和失败三态 | `WORKTREE-PARTIAL` |
| 10. 删除后尝试旧状态恢复 | 本地候选销毁 profile key、删除当前状态并保留无正文审计；合成测试覆盖旧备份不可解密和第 30 天清理 | 未覆盖产品控制的全部副本与完整 VM；无外部当前删除代际可阻止旧代码+旧 key+旧状态整体回滚；且当前倒计时/保留/回执语义违反票面合同 | `WORKTREE-PARTIAL / UNPROVEN` |

这条旅程的共同失败点是：任务、复盘、投递、控制、监控、部署和删除各自维护局部状态，却没有一个状态权威能够强制它们按同一批准、终态、未知、删除代际和业务健康规则推进。

## 3. C06：健康任务生命周期与四项职责

### 已证明

- `WORKTREE` 定义了任务类型、目的、证据、计划时间、策略、dispatch 尝试等局部字段，并校验 source card 当前性。[tasks.py](../../../ops/partner-health-steward/sidecar/tasks.py#L33-L73)、[tasks.py](../../../ops/partner-health-steward/sidecar/tasks.py#L809-L1021)
- dispatch 具有有限尝试、跳过、失败和接口接受后的 `sent` 记录。[dispatch.py](../../../ops/partner-health-steward/sidecar/dispatch.py#L225-L341)、[dispatch.py](../../../ops/partner-health-steward/sidecar/dispatch.py#L588-L634)

### 限制、反例与未知

- 当前状态集合围绕 `candidate/scheduled/due_for_render/sent/skipped/failed/cancelled`，不是四标签与附加事实；`sent` 也不能证明 `solved`。[tasks.py](../../../ops/partner-health-steward/sidecar/tasks.py#L33-L46)、[dispatch.py](../../../ops/partner-health-steward/sidecar/dispatch.py#L26-L38)
- 投递账本把外部效果保留为 `uncertain` 后，dispatcher 会把 `channel-send-uncertain` 或 `sent-state-unknown` 强制落成任务终态 `failed`；它不能表达现行合同要求的 `active + 结果未知`。[dispatch.py](../../../ops/partner-health-steward/sidecar/dispatch.py#L925-L984)
- 字段中没有承担者、接收方、可判定验收、阶段权威、批准/撤回和前序/后继；没有“一项独立验收结果一项任务”的强制条件。
- 未找到画像维护、证据维护、主人询问、文献查找与 Plugin 任务框架的分离输入/写权限/验收/终态协议；也未找到主人默认视图、展开视图和单项延期/调整/取消。
- pause/stop 对全部开放任务的批量取消，证明局部控制可绕过任务自身批准和终态语义。

**结论：`LIVE-ABSENT`；`WORKTREE-PARTIAL` 且存在确定性合同冲突。**

## 4. C07：当地自然日复盘、通知、投递与恢复

### 已证明

- `WORKTREE` 每当地日 04:00 形成一次 review，已完成日期不重复；失败允许一次 +10 分钟重试，过期不通用补跑。[tasks.py](../../../ops/partner-health-steward/sidecar/tasks.py#L22-L30)、[tasks.py](../../../ops/partner-health-steward/sidecar/tasks.py#L684-L752)、[tasks.py](../../../ops/partner-health-steward/sidecar/tasks.py#L1039-L1127)
- 固定 Hermes Cron 本身区分 attempt 的 `completed/failed/unknown`，`unknown` 不自动重跑；工作树微信账本也能把接口结果分为 accepted/rejected/uncertain 并阻止未知盲重发。[Cron 固定文档](https://github.com/NousResearch/hermes-agent/blob/3c27eb6234bf91b8ceee9e9071591b31e9b148cb/website/docs/user-guide/features/cron.md#L234-L273)、[weixin_delivery.py](../../../ops/partner-health-steward/sidecar/weixin_delivery.py#L38-L63)、[weixin_delivery.py](../../../ops/partner-health-steward/sidecar/weixin_delivery.py#L1316-L1433)

### 限制、反例与未知

- 现场业务 Cron 为 0；`cron 0 4 * * *` 只是计划表面，不证明业务复盘已完成。[hermes_jobs.py](../../../ops/partner-health-steward/hermes_jobs.py#L33-L60)
- 未找到新任务、普通阶段变化、关心/提醒、任务终态、复盘摘要五类独立偏好，也未找到危险升级、必要纠错、全局关键变化和一次行动请求的不可关闭分类。
- 未证明主人可查询最近复盘结论、无变化安静、时区变化/重启/恢复后以完整当前状态重判；当前复盘内容仍依赖旧画像/任务语义。
- `accepted` 只说明接口接受；既没有微信主人真实到达/已读证明，也没有把未知贯穿任务、控制和三态。[Evidence 21](21-unique-weixin-admission-routing-provenance-replay-results-20260820.md#answer)

**结论：`LIVE-ABSENT`；`WORKTREE-PARTIAL`。**

## 5. C14：主人权利、分离控制、永久删除与防复活

### 已证明

- `WORKTREE` 有查看、导出、暂停/恢复主动联系、停止/恢复记录和双消息确认删除命令；导出与删除已有局部访问校验。[owner_controls.py](../../../ops/partner-health-steward/owner_controls.py#L18-L30)、[owner_controls.py](../../../ops/partner-health-steward/owner_controls.py#L598-L877)
- 删除候选能删除当前 profile、销毁其 key、清理投影并保留无正文删除审计；这是局部防恢复原语，不是全产品永久删除证明。[store.py](../../../ops/partner-health-steward/sidecar/store.py#L3701-L3950)

### 限制、反例与未知

- 没有六域当前快照沿索引访问证据、任务、阶段、批准、未知、交付和诊断修订的统一视图；未找到画像纠正与 `updated/not-updated/rejected/failed/unconfirmable` 结果合同。
- 五种控制没有分离：暂停和停止记录都取消任务；单项任务取消和执行批准撤回缺失。
- 删除采用 10 分钟确认窗，产生“永久删除”终态通知，并固定 30 天清理备份；这些是当前票面明确排除的额外产品承诺。[owner_controls.py](../../../ops/partner-health-steward/owner_controls.py#L627-L667)、[store.py](../../../ops/partner-health-steward/sidecar/store.py#L50-L50)、[store.py](../../../ops/partner-health-steward/sidecar/store.py#L3867-L3950)
- 删除未证明覆盖普通 Hermes session/log、两份投递账本、全部临时缓存/导出、源资料、所有备份/快照和站内旧 VM；也未证明完整旧 VM 携带旧代码、旧 key、旧状态恢复后仍被当前删除代际拒绝。站外微信/模型/主人下载副本本来就不应承诺删除。

**结论：`LIVE-ABSENT`；`WORKTREE` 有局部数据删除原语，但不满足当前 C14，且包含相反的产品语义。**

## 6. C15：三态业务观测与跨故障域传播

### 已证明

- `WORKTREE` operator monitor 能检查审计读取、daily review 与 dispatcher 心跳，输出服务/作业状态并尝试 firing/recovered 通知。[operations.py](../../../ops/partner-health-steward/sidecar/operations.py#L341-L608)
- 这能支持组件级故障诊断，但不能单独证明健康管家业务活跃。

### 限制、反例与未知

- monitor 不读取画像、任务、主人控制、健康入口、模型路线、安全强制、问答结果和诊断范围状态；没有主人可查询的“活跃/异常/无法确认、最近确认时间、受影响能力、可依赖结果”统一表面。
- 合成测试明确断言 `production_acceptance="blocked"` 时 `service_health.state == "healthy"`，证明服务存活没有向业务可信状态传播。[test_operational_monitor.py](../../../ops/partner-health-steward/tests/test_operational_monitor.py#L148-L166)
- 已继承事实是当前激活诊断范围为 0；现有 monitor 未把“最后一个范围失效/范围归零”传播到全局。[Evidence 25](25-named-diagnostic-scope-governance-and-full-chain-capabilities-20260820.md#answer)
- 未证明可信前提失效/无法证明时停止相应处理，也未证明非活跃和恢复各一次、不含健康正文、无周期绿色心跳的主人通知；当前 alert sink 也未被证明等于主人微信到达。

**结论：`LIVE-ABSENT`；`WORKTREE` 只有 operator 组件监控，且存在“验收阻塞仍健康”的确定性反例。**

## 7. C16：权威资产和受管个人状态迁移

### 已证明

- `WORKTREE` 发布器枚举一组 release files 并生成哈希 manifest；部署前会检查部分运行输入。[deployment.py](../../../ops/partner-health-steward/deployment.py#L72-L93)、[deployment.py](../../../ops/partner-health-steward/deployment.py#L365-L471)、[deployment.py](../../../ops/partner-health-steward/deployment.py#L1632-L1653)
- 旧 Hermes profile 的迁移只是目录复制；`restore_backup()` 能验证并原子替换主 `state.sqlite.enc` blob，并留下 pre-restore 副本。[deployment.py](../../../ops/partner-health-steward/deployment.py#L695-L769)、[deployment.py](../../../ops/partner-health-steward/deployment.py#L1126-L1198)

### 限制、反例与未知

- release manifest 不枚举 TO/项目权威文档、全部 Skill、Map、Plugin 语义状态、六域画像/三类证据及其引用；状态路径还包含审计、投递账本、投影、模型证明、原始资料/缓存、secret/export 等多个对象，恢复却只替换主 blob。[deployment.py](../../../ops/partner-health-steward/deployment.py#L47-L65)
- 没有统一快照代际或语义 manifest 来保证批准/撤回、任务终态、未知、交付、删除状态和来源时间一起迁移；没有源端冻结、目标端接管和“只能一处继续变化”的证据。
- 静态 verify 主要检查文件、服务和两项 job 是否存在，不证明目标唯一入口、初始化、首跳同意、保护边界或故障进入业务三态。[deployment.py](../../../ops/partner-health-steward/deployment.py#L771-L1027)
- 没有在可丢弃双环境中做获准演练；缺项、密钥/权限错误、切换中断和结果未知是否失败关闭均为 `UNRUN/UNPROVEN`。

**结论：`LIVE-ABSENT`；`WORKTREE` 证明局部字节发布/恢复，不证明产品语义迁移。**

## 8. 被吸收旧票覆盖核对

| 被吸收票 | 原验收边界 | 本报告覆盖位置 | 是否遗漏 |
|---|---|---|---|
| [84](../issues/84-verify-local-day-review-notification-delivery-unknown-and-recovery.md) | 当地日复盘、五类通知、不可关闭消息、投递分层、未知与恢复 | 代表旅程 3–4；第 4 节 | 无；全部给出正/负/未知边界 |
| [90](../issues/90-verify-owner-rights-control-deletion-and-non-resurrection.md) | 查看/纠正/导出、更新真实结果、五种分离控制、完整删除、站外边界、防复活 | 代表旅程 5–7、10；第 5 节 | 无；明确指出当前额外删除承诺不合合同 |
| [91](../issues/91-verify-runtime-three-state-observation-and-fault-isolation.md) | 三态、最近确认、故障传播与隔离、诊断范围归零、可信前提、转态通知 | 代表旅程 8；第 6 节 | 无；继承诊断范围为 0 的前提 |
| [92](../issues/92-verify-authoritative-assets-and-managed-state-portability.md) | 资产/状态枚举、引用和终态保真、单一当前权威、失败关闭 | 代表旅程 9–10；第 7 节 | 无；未把账号/真人身份恢复带回范围 |

## 9. 合成测试与可复现边界

主调查在当前工作树运行：

```text
python -m unittest tests.test_daily_review tests.test_daily_retry_runner tests.test_dispatch tests.test_owner_controls tests.test_recording_lifecycle tests.test_profile_deletion tests.test_operational_monitor tests.test_linux_deployment tests.test_export_attachments tests.test_weixin_delivery
Ran 158 tests in 41.872s — OK (skipped=7)
```

即 151 passed、7 skipped、0 failed。主线程另独立运行相邻但不同的 9 模块集合（含 `test_proactive_contact`，不含本次的 daily retry/export attachments），结果为 157 total、150 passed、7 skipped、0 failed。两次结果不能相加，也不能证明现场能力；它们只支持上述 `WORKTREE/TEST` 静态判断。关键反例同时由源码和测试断言支撑，而非从“测试全绿”反推合同已满足。

## 10. 未运行实验与批准边界

以下仍须主人另行批准，并使用可丢弃、非真实健康数据环境：

1. 真实微信发送与在途断连，只验证接口接受/未知/重复抑制，不能要求主人行动或情绪改善；
2. 当地日边界、时区变更、重启/恢复，不得污染正式业务 Cron；
3. 画像、任务、控制、入口、模型、安全、问答、诊断范围逐域故障注入及跨故障域观察；
4. 删除后以旧 Plugin、备份和完整旧 VM 尝试恢复，含密钥和全部受控副本清单；
5. 可丢弃源/目标环境的完整迁移、失败切换与单一当前权威演练。

这些实验在批准并实际完成前均为 `UNRUN`，静态源码、哈希相等、进程存活、数据库行消失或测试全绿均不得冒充结果。
