# Ticket 119 冻结验证合同

> 状态：candidate，等待与 [`119-frozen-implementation-design.md`](119-frozen-implementation-design.md) 绑定到同一 checkpoint，并由 fresh-context Spec／Standards reviewer 完成编码前预审。characterization 产品基线为 commit `dc6b26b03aa076b405a7b28d440de058b783f135`，tree `d69e2b698848eae28e0245d07f28847583711877`；verifier-owned 测试为 `tests/test_ticket119_integration.py`，当前 SHA-256 `b4c45d8265819e21fed3d614243ae89d4a76783d498836b530d28524b64f14ec`。本合同冻结后，编码 Agent 不得修改本文件、实施设计或 verifier-owned 测试。

## 测试权威与唯一行为 Seam

独立 verification authority 独占 `tests/test_ticket119_integration.py`。自动门只穿过包公开导出的一个深 Module：

```python
AcceptanceRunContract.run(
    current_release_manifest,
    gate_executor,
    run_context,
) -> AcceptanceRunReport
```

- `current_release_manifest` 使用当前 `HostReleaseContract.build()` 实际返回的 `ReleaseManifest` 对象；普通 Mapping、摘要字符串和手写 manifest 不可替代。
- `GateExecutor` 是唯一外部 Seam，公开方法为 `execute(gate_request) -> GateObservation`。verifier fake 只记录调用并返回合成 observation，不访问网络、真实 Partner、Linux、模型、Weixin、联系人、主人、凭据或健康资料。
- `run_context` 只携带固定 run identity、显式时间、环境分类、opaque target ref、G08/G10/G11/G12 各自的 opaque approval ref，以及可选的同 run 既有不可变 report。caller 不能输入 gate 顺序、通过条件或最终声明。
- `AcceptanceRunReport.to_wire()` 是完整观察面。测试观察固定 G01—G12 顺序、执行停止、gate result、opaque refs、分层 verdict 和 report digest，不读取 helper、缓存、内部表、codec 或文件布局。

GateExecutor 的正常 observation 只允许当前 release/run/gate/execution-key identity、环境和执行时间、executor/step/fixture digest、`passed | failed | cannot-confirm`、opaque evidence/no-go/rollback/impact/next refs，以及 G12 精确四项 opaque receipt refs。未知字段或身份／正文 payload 使该 observation `cannot-confirm`；原值不得抄入报告。

G08/G10/G11/G12 缺本 gate approval ref 时由 Module 直接形成 `not-authorized`，且不得调用 executor。opaque ref 的实际签发、撤回和 target-local currentness 由获准目标权威验证；自动门不伪造批准，也不把“存在一个字符串”写成真实批准已取得。

## 七个 verifier-owned Gate

| Gate | 验收 | 唯一可观察结果 | 必须杀死的独立现实错误 |
|---|---|---|---|
| 119-V01 | 119-A1 | Module 内固定 G01→G12；代表性 `failed`、`cannot-confirm` 和无授权 frontier 后 executor 不再调用，所有后继精确为 `blocked` 并指向同一 `blocked_by_gate` | 跳层、继续执行、漏记后继或把 blocked 写成 frontier 状态 |
| 119-V02 | 119-A2 | GateObservation 必须绑定当前 release/run/gate/execution key；跨 release 的 observation 失败关闭；report 有内容摘要且 `to_wire()` 修改不反写对象 | 旧 digest／伪证据复用，或调用者修改报告后改写验收事实 |
| 119-V03 | 119-A3 | 同 run/release 的既有 report 重放原样返回且 executor 零调用；外部 unknown 只形成一次 `cannot-confirm` 并阻断后继，每个执行请求使用唯一稳定 key | 重放再次执行外部 gate、unknown 自动重做或换 key 制造第二副作用 |
| 119-V04 | 119-A4 | G07 passed 只得到 `activation-ready` 且 product acceptance 未通过；G12 缺任一 run／owner／contact／active-path receipt 时 cannot-confirm；四项齐全且全部十二门 passed 才允许 product acceptance passed | 医学/合成门直接激活，或缺主人验收／active-path 证据仍宣布产品验收 |
| 119-V05 | 119-A5 | G08 observation 即使自报 passed，只要存在 blocking no-go ref，整体不得 passed，G09 不执行 | current-head、旧 fence、删除/迁移或 rollback no-go 被降格成局部告警后继续上线 |
| 119-V06 | 119-A6 | G08/G10/G11/G12 缺各自 approval ref 时本 gate `not-authorized` 且 executor 零调用；G12 observation 多带 owner identity 等非合同字段时 cannot-confirm，报告不保留原值 | 未授权真实动作，跨 gate 借用批准，或 collector 保存主人/联系人身份和正文 |
| 119-V07 | 119-A7 | G01—G09 本地/合成通过只支持 technical verdict，不支持 target binding、真实接口、部署、product acceptance 或 stable；全部十二门通过后 stable 仍为 `evidence-required` | 把本地绿灯或一次验收宣传为已部署、active、已验收或稳定运行 |

等价输入只在同一决策点使用 `subTest`；不对十二 gate 位置、字段、平台、故障和结果做笛卡尔积。V05 的一个 blocking ref 代表 G08 no-go 决策，不用自动测试伪造真实 current-head／删除／迁移 canary。V06 的一个额外身份字段代表严格 observation schema；实现应拒绝所有非合同字段，而不是只屏蔽测试字面量。

## 重放与无正文约束

既有 report 必须与当前 ReleaseManifest、run ID 和 report digest 全部一致，才能在 executor 零调用下重放；不一致时失败关闭，不能复用旧证据。报告尚未落成但 gate 可能已触发时，Module 只能把完全相同的稳定 execution key 交给具备幂等回读能力的 GateExecutor；executor 不能证明原终态时返回 `cannot-confirm`，不得建立新 key 或第二效果。

G12 canonical run／owner acceptance facts 仍留在目标私有边界和 Ticket 116 已有 `AcceptanceEvidenceProvider` 后面。AcceptanceRunReport 只保存四项 opaque receipt refs，不能解引用，也不能保存 owner/contact identity、健康正文、凭据、目标配置、运行数据库、模型 transcript、绝对路径或可逆摘要。Module 不写 `active`，不建立 activation/current-head/delivery ledger。

## 依赖展开、反假绿与停止

当前包没有公开 `AcceptanceRunContract`。测试采用依赖展开：

- 119-V01 必须真实失败于公共 Module 缺失或其可观察行为错误；禁止无条件 `fail`、导入虚构模块制造 error，或只断言常量。
- 119-V02—V07 只在同一公共 Module 尚不存在时 `SKIP`；V01 一旦能构造 Module，后六门全部自动展开。
- 编码前唯一接受形状为 `1 failure / 6 skips / 0 errors`；实现完成只接受 `7 passed / 0 skipped / 0 errors`，任何 skip 都阻止完成。
- fake executor 只位于真实外部 Seam，不 mock 自有 Module。测试的 ReleaseManifest 来自 Ticket 118 当前公共 build Interface，不手写产品对象。
- 测试不得访问网络、真实目标、秘密环境变量、服务器配置、运行数据库、健康正文、联系人或模型 transcript；不得执行真实部署、删除、迁移、模型、Weixin 或主人验收。
- 若实现需要可配置 gate DAG、通用部署器、第二 durable ledger、第二 current-head/delivery authority，或需要修改 Tickets 116—118 的既有业务权威，应停止并返回冻结阶段，不得弱化 Gate。

## 编码前命令与预期证据

- `python -m unittest -v tests.test_ticket119_integration`：预期 `1 failure / 6 skips / 0 errors`，唯一失败为包尚未公开 `AcceptanceRunContract`。
- `python -m compileall -q partner_health_steward tests`：必须通过。
- `git diff --check`：必须通过。
- `tests/test_ticket119_integration.py` SHA-256：`b4c45d8265819e21fed3d614243ae89d4a76783d498836b530d28524b64f14ec`。

冻结 checkpoint 还必须记录实施设计、验证合同和 verifier-owned test 的 blob。实现完成后重跑同一 7 门、Ticket 118 当前 release/preflight、受影响回归、Ticket 119 discovery、全量 discovery、compileall 和 diff check；三份冻结文件相对冻结 checkpoint 必须零变化。自动门全绿不替代 G01—G12 的真实获准证据，也不单独支持部署、active、产品验收或稳定运行声明。
