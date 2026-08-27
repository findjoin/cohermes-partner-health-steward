# Ticket 116 冻结验证合同

> 状态：verification-repair-candidate，尚未重新冻结。原 characterization 基线为 `1249734ef7aa10205b3852ad21a049a88a5e19a3`，tree 为 `eacf11a1ee3c7297368afa676cebe1e57ba031da`；原 pre-code 合同和十二门历史保留。当前候选只把实现审查在 `70e507408add13273b651d15d9bf73b03b5592a7` 上以公开 Seam 复现的既有 A1/A2/A3/A4/A5/A6/A9 漏洞收回原十二门，不新增产品功能、架构或 Gate 数量；经 fresh Spec/Standards 预审形成新 checkpoint 后方可再次标记 frozen。

## 测试权威、可观察面与既有绿灯

独立 verification Agent 独占 `tests/test_ticket116_integration.py`。编码 Agent 不得修改该文件、本合同或 [冻结增量设计](116-frozen-implementation-design.md)；认为测试错误时必须停止并返回冻结阶段。

验收只穿过生产公开 Seam：Weixin 健康入口、受管 health command、controlled effect、bounded managed read、business status，以及 fake model/owner/contact Adapter 的调用记录。测试不得把私有 SQL、表、内部字段、helper、文件布局或某种特定恢复算法当作通过证据。

本合同使用并冻结的新增公开面仅为：Core 构造时的 `safety_diagnostic_assets` 与可选只读 `acceptance_evidence_provider`（唯一方法为 `read(receipt_ref) -> canonical fact | None`），受管 action `safety.evaluate`、`safety.correct`、`diagnosis.prepare`、`diagnosis.commit`、`diagnosis.correct`、`diagnosis.activate`，controlled effect `contact-alert.execute`，以及 bounded read `managed_safety_diagnosis_read`。`contact_alert`/`contact_correction` 唯一 wire 为 `{intent_id, effect_intent}`，后者复用既有 EffectIntent wire；bounded read 只公开 `scope`、`diagnoses`、`owner_results`、`safety_events`、`current_judgment_status`。其余入口、模型执行、设置读取、投递和状态均复用现有公开接缝；不得为测试增加专用 override、可写 Provider、多个 contact wire 或隐藏 prepare/issue 旁路。

characterization 基线保持：Ticket 113 `99/99`、Ticket 114 `210/210`、Ticket 115 `135/135`。它们证明既有模型、设置/控制、任务、outbox 和状态行为，不替代本票红灯。由于受管安全/诊断资产是所有行为门的真实共同前置，本票采用依赖展开：编码前 V01 必须真实失败，V02—V12 必须明确报告被 V01 阻塞而 `skipped`；它们的完整源码和下游 oracle 同时封存。V01 转绿后，后继门自动执行，不修改测试。最终完成只接受 `12 passed / 0 skipped`，任何 skip 都阻止完成。

实现后审查没有改变上述产品目标。它证明旧门只覆盖了状态标签或正向形状，却没有杀死七类现实错误：minimum-help、安全规则和诊断 scope 三类内容地址资产都只校验声明 hash 的格式而不校验内容；route-down 时无规则匹配或规则能力不可用吞掉最低提示；模型候选可伪造四类批准引用；scope 失效后只临时投影修订并在恢复时复活旧 current；联系人专门暂停误撤销独立批准；专门暂停还会阻断可能已经离站警报所需的纠正；以及受管安全决定不推进 current-head 导致旧 generation 的第二写仍成功。它们分别归并回 V01/V04/V05、V03、V06、V08、V09、V10、V07；测试仍只有十二个方法，等价输入仅用 subTest 表达。

## 冻结产品门

| Gate | 对应验收 | 唯一可观察结果 | 必须杀死的现实错误 |
|---|---|---|---|
| 116-V01 | A1、A8 | 版本绑定的最低求助资产缺失、不可解析、权利或审核无效时，健康入口在读取正文前不可用，联系人调用为零，状态如实为 `cannot-confirm`；声明 hash 必须通过项目既有内容地址边界绑定移除声明字段后的完整 bundle，内容变化而声明不变同样失败关闭，具体内部 codec 不在本票冻结 | 入口先读正文、只校验 hash 字符串格式，或用未批准/被替换模板继续运行 |
| 116-V02 | A1 | 五个安全分支按固定优先级只产生一个主人结果；代表性冲突由较高优先级胜出 | 低优先级覆盖高优先级或一次返回多个主结果 |
| 116-V03 | A1、A5 | route/steward 不可用但危险可确定且联系人批准当前时，仍给主人固定提示并形成 alert intent；危险不能确认、当前规则无匹配或规则能力不可用时均给固定最低提示且联系人调用为零 | Skill/route 故障吞掉最低提示，把无匹配交给不可用普通路由，或无可靠危险/无批准仍联系联系人 |
| 116-V04 | A2、A3 | durable state 只持久化 `staged`/`active`，公开 effective phase 仍依次派生 staged/activation-ready/acceptance-authorized/active。诊断 scope 声明 hash 必须绑定完整 bundle，内容变化而声明不变时 effective phase 不得越过 staged。普通入口不能运行 staged；caller 只提交 opaque receipt ref，Core 经只读 AcceptanceEvidenceProvider 验证精确 owner/release/bundle/generation/run/gate/expiry/diagnosis。有效 run 只隔离一次，重放和普通入口失败；同一 run 诊断完成且真实主人验收 receipt 当前时，durable `active` 与证据引用原子同成 | caller 自造 run/`owner_acceptance=success`、scope 内容与声明 hash 脱钩仍进入 readiness、把派生 phase 写成第二持久状态/ledger、验收权限被普通请求使用、重放或验收失败仍激活 |
| 116-V05 | A3 | 初始化、控制、head/fence、同意、证据、容量、安全、知识或 scope 的代表性模型前漂移通过真实 authority provider、当前 head、控制或证据 revision 触发，并在调用模型前失败，model Adapter 调用为零；安全规则内容变化而声明 hash 不变属于同一模型前安全资产漂移 | 测试专用 `authority_overrides`、只做一次早期预检、接受内容/hash 脱钩的安全规则或失败后仍调用模型 |
| 116-V06 | A3、A9 | incomplete/failed/unknown、结构缺失、旧证据、BMI 物理量或未舍入比较不一致均不提交诊断；候选的 knowledge/safety/template/model capability 引用必须分别等于构造时当前且已批准的权威资产；正例保留完整结构与当前引用 | 接受部分模型输出、接受任一伪造/旧引用、显示舍入改变分类或模型草稿直接成为记录 |
| 116-V07 | A3、A9 | 提交前 authority 漂移以及 prepare/CAS/finalize 故障均同成同败；恢复只得到原决定一次；会形成持久安全/诊断业务结果的受管 action 必须推进 current-head，使携带旧 generation 的第二个不同命令失败关闭 | 旧事实提交、只做本地 receipt 写入、同一 head 接受两个不同业务决定、部分可见、finalize 前外发或恢复产生第二决定 |
| 116-V08 | A4、A9 | 同一问题/事件/时期最多一个 current；纠正、失效和 authority unknown 通过持久追加后继退出/替代，保留语义与精确引用；scope 资产恢复和进程重启不得删除失效后继或复活旧 current | 只在 read 时临时合成失效、恢复后复活、原位覆盖、多个 current、仅因重跑模型而替代 |
| 116-V09 | A5 | 联系人缺失、更换、方法变化、明确撤回或专门暂停时主人提示仍存在，contact Adapter 调用为零；暂停只阻断当前使用，不撤销独立 alert/correction authority，resume 后无需重新批准即可恢复当前资格；Ticket 116 只有 consumer 权限 | 联系人故障吞提示、把 pause 当 revoke、resume 后静默丢批准、旧对象批准沿用或本票自行写批准 |
| 116-V10 | A6 | alert 只接受称呼、事件时间、固定求助语义；额外字段拒绝。unknown 冻结；若警报可能已经离站，之后的专门 support pause 不得吞掉必要纠正；纠正只在独立 authority 仍 current 时向原接收身份一次，否则 truthful no-send | 泄露正文/症状/位置，unknown 自动重发，pause 吞掉必要纠正，纠正改投新人或重复发送 |
| 116-V11 | A7 | 停止新增记录时仍给允许的临时安全结果和获准最小 alert；重启/重放至多一次，长期读取中没有健康正文、诊断、证据、任务或安全事件，恢复后不倒填 | 为安全计算持久化敏感正文或恢复后补写 |
| 116-V12 | A8 | staged、核心安全失败和联系人不可用分别投影为 truthful 状态；联系人不可用不移除最低安全，staged 永不冒充完整 active | 代码存在即 active，或单项联系人故障冒充全局安全故障 |

表内的代表性漂移使用等价类和边界值，不把字段、标点或故障步骤做笛卡尔积。每个 Gate 恰好证明一项独立产品结果；多个输入仅在它们共享同一决策点、同一错误机制时用 subTest 表示。

## 防止假绿与防止测试膨胀

- 红灯必须来自调用当前生产 Interface 后的错误结果、缺失行为或非法 Adapter 调用；不得使用无条件 `fail`、导入不存在的测试专用 symbol、mock 掉被验收逻辑或先复制一套生产算法。共同真实前置尚未实现时，后继门只能明确 skip 并说明依赖，不能把同一异常复制成多个 failure。
- 正向路径必须走到公开主人结果、managed read/status 或 fake Adapter；只断言异常类型、内部行被执行或私有对象变化不算验收。
- 只在同时满足“不同可观察产品结果、真实失败链、独立 mutation 不会被现有 Gate 杀死”时增加 Gate；否则合并为已有 Gate 的等价类。理论风险、另一种实现偏好和字段组合不增加 Gate。
- 冻结后 Gate 数量固定为 12。发现验收遗漏只能停止、给出可复现证据并返回冻结阶段，不得由编码 Agent 边改测试边实现。

## 执行、完成和停止

原 pre-code checkpoint 必须运行并记录：

- `python -m unittest -v tests.test_ticket116_integration`：编码前预期 V01 `1` 个失败、V02—V12 `11` 个依赖 skip、`0` 个错误；V01 实现后所有后继门自动展开；
- `python -m unittest discover -v -s tests -p "test_ticket113*.py"`：预期保持全绿；
- `python -m unittest discover -v -s tests -p "test_ticket114*.py"`：预期保持全绿；
- `python -m unittest discover -v -s tests -p "test_ticket115*.py"`：预期保持全绿；
- `python -m compileall -q partner_health_steward tests` 与 `git diff --check`：预期通过。

### 当前 verification-repair 候选的红灯证据

- 产品基线：`70e507408add13273b651d15d9bf73b03b5592a7`。修改验证资产前原十二门实跑为 `Ran 12 tests ... OK`。
- 只修改本合同与 verifier-owned `tests/test_ticket116_integration.py` 后完整执行十二门：`Ran 12 tests`，`failures=13`、`errors=0`。V01/V03/V04/V05/V06/V07/V08/V09/V10 九个方法均只在新增等价类处红：V01 minimum-help 内容/hash 脱钩 1 项；V03 route-down 的无匹配/规则能力不可用 2 项；V04 scope 内容/hash 脱钩仍进入 activation-ready 1 项；V05 safety-rule 内容/hash 脱钩仍形成 model intent 1 项；V06 四类未批准引用 4 项；V07 stale-generation 第二写 1 项；V08 scope 恢复复活旧 current 1 项；V09 pause 撤销独立 authority 1 项；V10 pause 吞掉 unknown 后必要纠正 1 项。
- V02/V11/V12 在同一完整执行中保持绿色，证明公共 fixture 和共享 authority 更新没有制造无关假红。修复产品后仍只接受完整十二门 `12 passed / 0 skipped / 0 errors`；不能通过删除 subTest、弱化公开 oracle 或修改本合同来转绿。

编码完成的充分条件仅是同一冻结测试文件 `12/12` 通过、受影响旧票和项目全量回归通过、静态检查通过，且冻结三件套相对 test-gate commit 的 blob 零变化。fresh-context Spec/Standards reviewer 只检查实现是否忠实通过这些门及证据是否真实，不再提出替代架构或新增验收。

需要真实医学权利/审核、真实模型/Weixin/联系人、主人验收或 Ticket 117—119 能力时立即停止并报告为外部门；这些事实不得用 synthetic fixture 伪造，也不扩成本票代码。
