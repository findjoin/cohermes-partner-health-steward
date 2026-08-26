# Ticket 115 冻结验收测试合同

> 状态：verification-frozen。适用基线为 `d1b29e4ebbdcdcfcc7d86077290d9cced40cc02a`。本文件只把 Ticket 115 已确认的七项产品验收和五类冻结故障翻译成可重复测试，不新增功能、不指定私有实现，也不重开架构。

## 1. 测试权威与边界

验收采用分层证据，不要求把所有纯状态逻辑重复写成端到端测试：

- Task、Review、Delivery 的纯状态机由对应组件测试证明。
- 跨模块原子性、当前性、权限和恢复由 Plugin → Core 的健康操作、受控效果与受管读取证明。
- 任何声称“已外发”的正例必须完整经过 `prepare → issue → claim → execute`，并以 fake Adapter 的精确调用次数和受管结果为最终观察面。
- 数据库、私有 helper、marker 和内部集合只可用于安排故障，不得单独作为产品通过结论。
- fake Adapter 只证明本地边界；真实 Hermes、Weixin、到达、已读和生产幂等仍属于 Tickets 118—119。

下列测试代码及本文件由独立测试工程师持有。编码 Agent 不得删除、重命名、跳过、`xfail`、改变前置条件、放宽期望或重写 fixture：

- 整个 `tests/test_ticket115_integration.py` 相对测试门 commit 必须零修改；
- 本验证合同相对测试门 commit 必须零修改。

若编码 Agent 认为门本身错误，必须停止并交还测试工程师；不能一边改产品代码一边改门。

## 2. 七轴可追踪验收门

### 115-A：任务权威与主人控制

必须证明：

1. Skill、模型和 Plugin 只能提交候选；TaskEngine 决定新建、合并、阶段、claim/lease、验收和终态。
2. 同一业务目标不会因命令重放、不同候选 ID 或重启产生第二个当前任务。
3. 主人取消会关闭 active 任务并清除旧 claim；延期期间不推进，到期后仍是同一任务，旧 intent 永久不可发，新的当前 intent 可按仍有效的批准继续。
4. 范围内调整原位升版并使旧 claim 失效；扩大目的、资料、接收方、效果或验收时形成关联 successor 并等待当前授权。
5. `active / solved / failed / cancelled` 是唯一主标签；低层投递、Cron、模型文本或旧验收不能关闭或重开任务。

权威证据来自 `test_ticket115_tasks.py` 的候选、查重、claim/lease、终态与验收测试，以及 `test_ticket115_integration.py` 的主人取消、延期、调整、successor、current evidence 和命令重放测试。跨边界结论必须同时观察受管任务视图。

### 115-B：主人当地日复盘

必须证明：

1. owner + installation + 生效时区 + local date 同日最多一份 committed review；并发唤醒、精确重放和重启不增加第二份。
2. 时区变化从下一有效当地日生效；DST fold/gap 不重复；跨日 pending 不补旧日，只处理当前日。
3. 无 action 的复盘仍可记录完成，但不形成 owner delivery，也不调用 Adapter。
4. commit 时 local day 或状态摘要已过期则拒绝，不把调用者提供的 `changed/action_refs` 当裁决。

权威证据来自 `test_ticket115_tasks.py` 的 local-day、时区、DST、静默和恢复测试，以及 `test_ticket115_integration.py` 的 stale-day、state-change、receipt/replay 和 wake-only 测试。

### 115-C：业务事实、复盘和 outbox 原子性

必须证明：

1. 同一决定的业务事实、review 和 outbox intent 在 finalize 后同现；任一 prepare、CAS/readback 或 finalize 故障时不得部分可见。
2. CAS 结果未知或进程重启时只能恢复原决定或停止；不得形成第二份业务结果。
3. finalize 前 Adapter 调用为 0；finalize 后 Adapter 在 SQLite 事务外精确调用一次。

权威证据来自 `test_ticket115_storage.py` 的原子写入/回滚、`test_ticket115_integration.py` 的 current-head/CAS/finalize 恢复和事务外 Adapter 测试。故障 hook 只负责触发，结论以受管读取和 Adapter 为准。

### 115-D：每次外发的当前性与批准消耗

每个因素独立失效时都必须在 Adapter 前拒绝：当前证据 revision、批准、主人控制、普通通知/主动支持、联系窗口、当地日/时区、route/recipient/config/disclosure、current head、writer fence。正例必须证明所有因素 current 时精确发送一次。

改变 opaque intent ID 不得重置同一任务当前批准的 `max_attempts` 或 `min_contact_interval_seconds`。实现可以按权威绑定拒绝非当前 intent，或对已绑定的当前 intent 正确累计，但不能用 `effect_request_id` 的前缀、后缀或命名约定代替权威关系；跨延期、跨新当地日和重启仍不能重置消耗。

Ticket 114 精确绑定的是主人批准的外部效果根；Ticket 115 的每个当前 outbox/idempotency intent 是该效果根下的执行实例。只有经 `intent → current review/action → task → exact approval_id/version/approved effect root` 权威链形成的 opaque intent 才可消费该批准；仅同 task、仅同字符串前缀或没有该批准绑定的 intent 必须拒绝。批准修订前后的 attempts 不得串账。

权威证据来自既有 stale evidence/day/route/writer/defer 测试，以及独立门：

- `test_verification_gate_attempt_budget_counts_opaque_current_intents`
- `test_verification_gate_contact_interval_counts_opaque_current_intents`
- `test_verification_gate_revoked_approval_stops_before_adapter`
- `test_verification_gate_closed_contact_window_stops_before_adapter`
- `test_verification_gate_route_generation_drift_stops_before_adapter`

### 115-E：投递身份、层级与 unknown

必须证明：

1. intent/idempotency identity 跨重启稳定；相同 identity 不接受冲突 payload。
2. formed、business-committed、attempted、interface accepted/rejected、delivered、read、owner action 和 unknown 是不同事实；低层事实不提升层级、不把任务改成 solved。
3. Adapter 异常、响应丢失或发送后本地终态失败都只允许一次外部调用；恢复形成/保留 unknown，不能自动重发。
4. 后续独立 delivered/read 观察可以解除当前 unknown，但必须保留历史审计事实。

权威证据来自 `test_ticket115_delivery.py`、`test_ticket115_plugin_delivery.py` 和 integration 的 accepted/delivered/read、异常、orphan、completion-failure 与重启测试。

### 115-F：必要主人决定与状态变化请求

必须证明：

1. 普通投递 unknown 时形成一份独立、当前因果的主人决定请求；普通通知关闭和主动支持暂停不能吞掉它；请求本身完整到达 fake Adapter 一次。
2. unknown 已被独立观察解决时，尚未发送的旧决定请求保留历史但失去 currentness，重启后仍不能到达 Adapter。
3. Ticket 115 核心域从 `active` 进入 `abnormal/cannot-confirm`，以及从两种 nonactive 状态恢复 `active`，各形成一份可发送请求；nonactive→nonactive、active→active 和无变化不新增请求。
4. 请求形成后的同状态重投影与重启不能使它自我失效，也不能重复形成；相反方向的新 transition 会使旧方向请求失效。
5. 普通 review intent 伪造 mandatory ID 必须得到唯一明确拒绝，Adapter 为 0。

独立门：

- `test_unknown_owner_delivery_forms_one_independent_owner_decision_request`
- `test_verification_gate_unknown_request_expires_with_source_unknown`
- `test_ticket115_status_transition_forms_one_current_owner_decision_request`
- `test_verification_gate_mandatory_status_bypasses_persisted_ordinary_controls`
- `test_verification_gate_active_to_abnormal_requests_once`
- `test_verification_gate_opposite_status_transition_supersedes_old_request`
- `test_verification_gate_cannot_confirm_to_active_requests_once`
- `test_verification_gate_abnormal_to_active_requests_once`
- `test_nonactive_to_nonactive_status_change_is_not_mandatory`
- `test_review_delivery_cannot_forge_mandatory_owner_decision_identity`

### 115-G：StatusProjector 边界

必须证明 task/review/delivery 只提交无健康正文的受签事实；单项 unknown/rejected 不自动冒充全局 confirmed fault；confirmed fault 与 authority cannot-confirm 保持不同三态；投影重放不制造第二 transition 或第二请求。

权威证据来自 `test_ticket115_status_domains_are_sealed_and_unknown_is_not_fault`、Ticket 114 StatusProjector 合同测试和 115-F 的双向 transition 门。

## 3. 五类冻结故障的最小覆盖

| 冻结故障 | 必须覆盖的等价类 | 精确外部结果 |
|---|---|---|
| F1 重复/并发/重启 | causal replay 与 conflict、业务查重、同日唤醒、effect claim | 一份当前结果；Adapter 最多 1 |
| F2 prepare/CAS/readback/finalize | 各 checkpoint 单独失败或未知 | 全有或全无；finalize 前 Adapter 0 |
| F3 currentness 漂移 | 证据、批准/额度、控制/窗口、时区、route、head、fence | 每个失效子例 Adapter 0 |
| F4 外发结果未知 | 异常、响应丢失、发送后本地失败 | unknown；重启后 Adapter 总计 1 |
| F5 低层越权 | terminal/acceptance、层级、mandatory identity、全局状态 | 权威结果不变；Adapter 0 或仅合法 request 1 |

这里的“等价类”是停止边界：不做所有字段的笛卡尔积，不为另一种合理实现偏好新增测试。hidden 集合在测试门 commit 前一次性封存为 opaque ID、时间边界、重启、双向状态四类，每类最多一个变体；编码开始后不得新增类别，修复后只重跑同一集合。

## 4. 防假绿规则

- 测试名称和数量不是完成证据；七轴逐项可追踪且全部通过才算通过。
- 正向外发测试必须观察对应目标 Adapter，不得只数 outbox 或只做到 prepare。
- 拒绝路径不得 `catch-and-pass`，也不得在合同只有一个结果时接受多个状态；应断言明确拒绝、Adapter 0 和无高层事实。
- ID、时间表示和 causal token 使用至少一个不共享生产命名模式的变体。
- helper 只能搭建前置状态，不得从私有生产状态重算或“修好”待提交的 Plugin wire。
- 编码 Agent 之后的 diff 只允许产品代码和实施证据；上述 verifier-owned 测试与合同必须相对测试门 commit 零改动。
- 闭票审查只运行测试门 commit 时已经封存的 opaque ID、时间边界、重启和双向状态 hidden variants；不得在看到实现后新增类别或产品目标。

## 5. 执行门与完成条件

测试门建立时的 characterization 结果如下；这是有意保留的红灯，不是测试基础设施错误：

| 门 | `d1b29e4` 的可重复结果 |
|---|---|
| unknown 必要决定请求完整发送 | request 已形成，但 issue 返回 `effect-result-unknown`，不能到达决定请求 Adapter |
| active→nonactive 请求重投影后发送 | prepare 返回 `owner-delivery-authorization-required` |
| opaque ID 的 `max_attempts` | 第二个当前 intent 未被拒绝 |
| opaque ID 的最小联系间隔 | 间隔未到的第二个当前 intent 未被拒绝 |
| cannot-confirm→active | transition 存在，但 status request 数量为 0 |
| abnormal→active | transition 存在，但 status request 数量为 0 |

十四个 verifier-owned 定向方法在该基线上为 `7 passed / 7 failed`。七个红灯对应上表六类缺口；通过项覆盖 mandatory ID 防伪、unknown 来源解决后旧请求失效、批准撤回、关闭联系窗口、route generation 漂移、持久普通控制旁路和 `active→abnormal`。红灯修复不得破坏这些既有绿色边界。

编码前先在测试门 commit 上单独运行 verifier-owned 门并保存红灯；这些红灯证明测试确实能抓住当前缺口。编码后必须依次通过：

```text
python -m unittest -v tests.test_ticket115_integration.Ticket115IntegrationTests.test_unknown_owner_delivery_forms_one_independent_owner_decision_request tests.test_ticket115_integration.Ticket115IntegrationTests.test_ticket115_status_transition_forms_one_current_owner_decision_request tests.test_ticket115_integration.Ticket115IntegrationTests.test_review_delivery_cannot_forge_mandatory_owner_decision_identity tests.test_ticket115_integration.Ticket115IntegrationTests.test_verification_gate_attempt_budget_counts_opaque_current_intents tests.test_ticket115_integration.Ticket115IntegrationTests.test_verification_gate_contact_interval_counts_opaque_current_intents tests.test_ticket115_integration.Ticket115IntegrationTests.test_verification_gate_revoked_approval_stops_before_adapter tests.test_ticket115_integration.Ticket115IntegrationTests.test_verification_gate_closed_contact_window_stops_before_adapter tests.test_ticket115_integration.Ticket115IntegrationTests.test_verification_gate_route_generation_drift_stops_before_adapter tests.test_ticket115_integration.Ticket115IntegrationTests.test_verification_gate_mandatory_status_bypasses_persisted_ordinary_controls tests.test_ticket115_integration.Ticket115IntegrationTests.test_verification_gate_active_to_abnormal_requests_once tests.test_ticket115_integration.Ticket115IntegrationTests.test_verification_gate_opposite_status_transition_supersedes_old_request tests.test_ticket115_integration.Ticket115IntegrationTests.test_verification_gate_cannot_confirm_to_active_requests_once tests.test_ticket115_integration.Ticket115IntegrationTests.test_verification_gate_abnormal_to_active_requests_once tests.test_ticket115_integration.Ticket115IntegrationTests.test_verification_gate_unknown_request_expires_with_source_unknown
python -m unittest discover -s tests -p "test_ticket115*.py" -v
python -m unittest discover -s tests -p "test_ticket114*.py" -v
python -m unittest discover -s tests -v
python -m compileall -q partner_health_steward tests
git diff --check
```

完成还要求：

1. `tests/test_ticket115_integration.py` 和本合同相对测试门 commit 没有被实现 Agent 修改；
2. 七轴各有可定位的通过证据，五类冻结故障各有至少一个明确、可定位的负例；七个红门保留 `d1b29e4` 红灯证据；
3. 独立 reviewer 的已封存 hidden variants、Spec 轴与 Standards 轴均通过；治理规则未认定为 blocker 的意见不得延长本票；
4. 没有把真实 Weixin、生产 canary 或 Ticket 116+ 冒充为本地已验证；
5. 只有以上全部满足，才可勾选 Ticket 115、写 `## Answer`、标记 `resolved` 并更新唯一 Map。

## 6. 明确不扩展

本合同不要求新服务、新数据库、新 ledger、新状态机、特定 schema/hash/helper、Case registry、覆盖率百分比或固定测试数量；也不接受“为了更安全”而新增未出现在 Ticket 115/冻结设计中的功能。发现实现缺陷时先作局部修复；只有现冻结架构客观无法满足既有验收时，才按架构治理停止并交还主人。
