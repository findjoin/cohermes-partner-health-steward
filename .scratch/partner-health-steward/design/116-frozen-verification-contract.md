# Ticket 116 冻结验证合同

> 状态：frozen。characterization 基线为 `1249734ef7aa10205b3852ad21a049a88a5e19a3`，tree 为 `eacf11a1ee3c7297368afa676cebe1e57ba031da`。本合同翻译 Ticket 116 既有产品验收，不增加产品功能或内部实现要求；冻结 commit/tree、三件套 blob 和预审身份记录在 Ticket。

## 测试权威、可观察面与既有绿灯

独立 verification Agent 独占 `tests/test_ticket116_integration.py`。编码 Agent 不得修改该文件、本合同或 [冻结增量设计](116-frozen-implementation-design.md)；认为测试错误时必须停止并返回冻结阶段。

验收只穿过生产公开 Seam：Weixin 健康入口、受管 health command、controlled effect、bounded managed read、business status，以及 fake model/owner/contact Adapter 的调用记录。测试不得把私有 SQL、表、内部字段、helper、文件布局或某种特定恢复算法当作通过证据。

本合同使用并冻结的新增公开面仅为：Core 构造时的 `safety_diagnostic_assets` 与可选只读 `acceptance_evidence_provider`（唯一方法为 `read(receipt_ref) -> canonical fact | None`），受管 action `safety.evaluate`、`safety.correct`、`diagnosis.prepare`、`diagnosis.commit`、`diagnosis.correct`、`diagnosis.activate`，controlled effect `contact-alert.execute`，以及 bounded read `managed_safety_diagnosis_read`。`contact_alert`/`contact_correction` 唯一 wire 为 `{intent_id, effect_intent}`，后者复用既有 EffectIntent wire；bounded read 只公开 `scope`、`diagnoses`、`owner_results`、`safety_events`、`current_judgment_status`。其余入口、模型执行、设置读取、投递和状态均复用现有公开接缝；不得为测试增加专用 override、可写 Provider、多个 contact wire 或隐藏 prepare/issue 旁路。

characterization 基线保持：Ticket 113 `99/99`、Ticket 114 `210/210`、Ticket 115 `135/135`。它们证明既有模型、设置/控制、任务、outbox 和状态行为，不替代本票红灯。由于受管安全/诊断资产是所有行为门的真实共同前置，本票采用依赖展开：编码前 V01 必须真实失败，V02—V12 必须明确报告被 V01 阻塞而 `skipped`；它们的完整源码和下游 oracle 同时封存。V01 转绿后，后继门自动执行，不修改测试。最终完成只接受 `12 passed / 0 skipped`，任何 skip 都阻止完成。

## 冻结产品门

| Gate | 对应验收 | 唯一可观察结果 | 必须杀死的现实错误 |
|---|---|---|---|
| 116-V01 | A1、A8 | 版本绑定的最低求助资产缺失、不可解析、权利或审核无效时，健康入口在读取正文前不可用，联系人调用为零，状态如实为 `cannot-confirm` | 入口先读正文或用未批准模板继续运行 |
| 116-V02 | A1 | 五个安全分支按固定优先级只产生一个主人结果；代表性冲突由较高优先级胜出 | 低优先级覆盖高优先级或一次返回多个主结果 |
| 116-V03 | A1、A5 | route/steward 不可用但危险可确定且联系人批准当前时，仍给主人固定提示并形成 alert intent；危险不能确认或批准失效时仍给主人提示但联系人调用为零 | Skill/route 故障吞掉最低提示，或无可靠危险/无批准仍联系联系人 |
| 116-V04 | A2、A3 | durable state 只持久化 `staged`/`active`，公开 effective phase 仍依次派生 staged/activation-ready/acceptance-authorized/active。普通入口不能运行 staged；caller 只提交 opaque receipt ref，Core 经只读 AcceptanceEvidenceProvider 验证精确 owner/release/bundle/generation/run/gate/expiry/diagnosis。有效 run 只隔离一次，重放和普通入口失败；同一 run 诊断完成且真实主人验收 receipt 当前时，durable `active` 与证据引用原子同成 | caller 自造 run/`owner_acceptance=success`、把派生 phase 写成第二持久状态/ledger、验收权限被普通请求使用、重放或验收失败仍激活 |
| 116-V05 | A3 | 初始化、控制、head/fence、同意、证据、容量、安全、知识或 scope 的代表性模型前漂移通过真实 authority provider、当前 head、控制或证据 revision 触发，并在调用模型前失败，model Adapter 调用为零 | 测试专用 `authority_overrides`、只做一次早期预检或失败后仍调用模型 |
| 116-V06 | A3、A9 | incomplete/failed/unknown、结构缺失、旧证据、BMI 物理量或未舍入比较不一致均不提交诊断；正例保留完整结构与当前引用 | 接受部分模型输出、显示舍入改变分类或模型草稿直接成为记录 |
| 116-V07 | A3、A9 | 提交前 authority 漂移以及 prepare/CAS/finalize 故障均同成同败；恢复只得到原决定一次 | 旧事实提交、部分可见、finalize 前外发或恢复产生第二决定 |
| 116-V08 | A4、A9 | 同一问题/事件/时期最多一个 current；纠正、失效和 authority unknown 通过追加后继退出/替代，保留语义与精确引用 | 原位覆盖、多个 current、仅因重跑模型而替代 |
| 116-V09 | A5 | 联系人缺失、更换、方法变化、撤回或暂停时主人提示仍存在，contact Adapter 调用为零；Ticket 116 只有 consumer 权限 | 联系人故障吞提示、旧批准沿用或本票自行写批准 |
| 116-V10 | A6 | alert 只接受称呼、事件时间、固定求助语义；额外字段拒绝。unknown 冻结；纠正只在 authority 仍 current 时向原接收身份一次，否则 truthful no-send | 泄露正文/症状/位置，unknown 自动重发，纠正改投新人或重复发送 |
| 116-V11 | A7 | 停止新增记录时仍给允许的临时安全结果和获准最小 alert；重启/重放至多一次，长期读取中没有健康正文、诊断、证据、任务或安全事件，恢复后不倒填 | 为安全计算持久化敏感正文或恢复后补写 |
| 116-V12 | A8 | staged、核心安全失败和联系人不可用分别投影为 truthful 状态；联系人不可用不移除最低安全，staged 永不冒充完整 active | 代码存在即 active，或单项联系人故障冒充全局安全故障 |

表内的代表性漂移使用等价类和边界值，不把字段、标点或故障步骤做笛卡尔积。每个 Gate 恰好证明一项独立产品结果；多个输入仅在它们共享同一决策点、同一错误机制时用 subTest 表示。

## 防止假绿与防止测试膨胀

- 红灯必须来自调用当前生产 Interface 后的错误结果、缺失行为或非法 Adapter 调用；不得使用无条件 `fail`、导入不存在的测试专用 symbol、mock 掉被验收逻辑或先复制一套生产算法。共同真实前置尚未实现时，后继门只能明确 skip 并说明依赖，不能把同一异常复制成多个 failure。
- 正向路径必须走到公开主人结果、managed read/status 或 fake Adapter；只断言异常类型、内部行被执行或私有对象变化不算验收。
- 只在同时满足“不同可观察产品结果、真实失败链、独立 mutation 不会被现有 Gate 杀死”时增加 Gate；否则合并为已有 Gate 的等价类。理论风险、另一种实现偏好和字段组合不增加 Gate。
- 冻结后 Gate 数量固定为 12。发现验收遗漏只能停止、给出可复现证据并返回冻结阶段，不得由编码 Agent 边改测试边实现。

## 执行、完成和停止

编码前必须运行并记录：

- `python -m unittest -v tests.test_ticket116_integration`：编码前预期 V01 `1` 个失败、V02—V12 `11` 个依赖 skip、`0` 个错误；V01 实现后所有后继门自动展开；
- `python -m unittest discover -v -s tests -p "test_ticket113*.py"`：预期保持全绿；
- `python -m unittest discover -v -s tests -p "test_ticket114*.py"`：预期保持全绿；
- `python -m unittest discover -v -s tests -p "test_ticket115*.py"`：预期保持全绿；
- `python -m compileall -q partner_health_steward tests` 与 `git diff --check`：预期通过。

编码完成的充分条件仅是同一冻结测试文件 `12/12` 通过、受影响旧票和项目全量回归通过、静态检查通过，且冻结三件套相对 test-gate commit 的 blob 零变化。fresh-context Spec/Standards reviewer 只检查实现是否忠实通过这些门及证据是否真实，不再提出替代架构或新增验收。

需要真实医学权利/审核、真实模型/Weixin/联系人、主人验收或 Ticket 117—119 能力时立即停止并报告为外部门；这些事实不得用 synthetic fixture 伪造，也不扩成本票代码。
