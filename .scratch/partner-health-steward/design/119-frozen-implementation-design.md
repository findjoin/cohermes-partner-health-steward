# Ticket 119 冻结实施设计

> 状态：candidate，等待 verifier-owned 测试门与编码前 Spec／Standards 预审共同冻结。产品 characterization 基线为 commit `dc6b26b03aa076b405a7b28d440de058b783f135`，tree `d69e2b698848eae28e0245d07f28847583711877`。本设计只增加验收编排与证据合同，不执行真实外部动作，也不改变 Tickets 110—118 的产品架构。

## 目标、当前差额与非目标

Ticket 118 已提供可重现 `ReleaseManifest`、固定 Hermes 宿主验证和 install／upgrade／rollback readiness；Tickets 110—117 已提供产品行为与合成门。当前包尚未公开 Ticket 119 验收 Module，也没有 `tests/test_ticket119_integration.py` 或 119 工具入口，因此还不能固定 G01—G12 顺序、授权前置、no-go 停止、不可变报告和诚实声明。

本票只补齐上述验收控制，并在获准时执行既定 gate。它不重写 core、HostReleaseContract、诊断激活、current-head、投递、删除或迁移；不建立部署框架、通用工作流、第二份业务状态或稳定运行判定器。真实许可、医学审核、Partner、Linux、模型、Weixin、主人和联系人事实只能由目标边界的获准执行者形成。

## 唯一公开 Module 与 Interface

新增一个深 Module：`AcceptanceRunContract`。包只公开一个行为 Interface：

```python
AcceptanceRunContract.run(
    current_release_manifest,
    gate_executor,
    run_context,
) -> AcceptanceRunReport
```

- `current_release_manifest` 必须是当前 `HostReleaseContract.build()` 返回的 `ReleaseManifest`，不能用普通 Mapping、旧摘要或自报字符串替代。
- `run_context` 只含显式 `run_id`、固定执行时间、环境分类、目标的 opaque ref、逐 gate 的 opaque approval refs，以及可选的同 run 既有不可变 report。caller 不能提交 gate 顺序、pass 条件、产品 verdict 或稳定声明。
- `GateExecutor` 是唯一外部 Seam。其 Adapter 以稳定 `(release_digest, run_id, gate_id)` execution key 执行或回查一个 gate，只接收该 gate 所需的 opaque approval ref，只返回严格 GateObservation。合成 Adapter 与目标本地 Adapter 证明该 Seam 真实存在。
- `AcceptanceRunReport.to_wire()` 返回无正文、可 hash 的不可变报告；调用者修改返回 Mapping 不得改变原报告。

固定顺序由 Module 内部独占：`119-G01` 至 `119-G12`。每次遇到第一个非 `passed` 结果，Module 立即停止调用 executor，并把所有后继记录为 `blocked`，精确指向 `blocked_by_gate`。caller、executor 和报告输入均不能改序、跳层或补写后继。

## 重放、崩溃和未知

同一 run／release 带有 hash 有效的既有 report 时，`run()` 原样返回该不可变 report，executor 零调用；已经停止的 run 不恢复执行，新证据必须建立新 run。

若先前 gate 可能已经触发但报告尚未形成，executor 只能用原 execution key 回查或完成自身幂等终态，不能换 key 重新产生副作用。executor 不能证明原终态时必须返回 `cannot-confirm`；Module 冻结该 run 并阻断后继。真实模型、Weixin、联系人、删除、迁移和主人动作的幂等／unknown 仍由各自既有 Adapter 或目标执行边界承担，119 不复制它们的业务 ledger。

## GateObservation、授权与报告

GateObservation 只允许：当前 release/run/gate identity、`passed | failed | cannot-confirm`、环境分类、执行时间、executor/step/fixture digest、opaque evidence refs、rollback ref/status、影响和下一步。它不能携带原始正文、身份、凭据、配置值、运行数据库内容、模型 transcript、可逆摘要、绝对路径或任意嵌套 payload。

G08、G10、G11、G12 在调用 executor 前必须各自提供 opaque approval ref；缺失或借用另一 gate 的 ref 时 Module 自行记录 `not-authorized`，executor 零调用。ref 是否真实签发、绑定当前 release/run/gate/target、当前有效且未撤回，由获准 target-local executor 在任何外部动作前验证；验证失败必须返回 `not-authorized` 且零外部动作。Module 不凭一个字符串伪造审批权威，也不建立第二审批 ledger。G07 只核验已存在的权利、冻结 bundle 和审核 attestation，不授权 collector 去实施医学审核。

G08 只允许预先解析的 disposable namespace；任一 current-head、旧 fence、terminal delete、purge provider、迁移、transfer unknown 或 rollback no-go 都使整个 G08 非 passed。G09 只能由 deny-network synthetic Adapter 执行。G10—G12 的 executor 必须在目标边界内最小处理，collector 只取得无值 attestation。

## 与既有产品权威的关系

- Ticket 118 的 `HostReleaseContract` 独占 release、宿主和 readiness；119 只消费当前 `ReleaseManifest` 和可定位前置证据。
- HealthCore/current-head 继续独占健康业务、诊断、staged→active 和 writer authority；119 不写 active。
- Ticket 116 已有只读 `AcceptanceEvidenceProvider` Seam。G12 executor 在目标私有边界形成 canonical run／owner-acceptance receipts，119 报告只保存 `run_receipt_ref`、`owner_acceptance_receipt_ref`、`contact_acceptance_receipt_ref` 和 `active_path_receipt_ref`；collector 不解引用、不保存 owner/contact identity。Core 仍按既有 Interface 独立验证并原子激活。
- Ticket 115 继续独占形成、提交、尝试、accepted、送达、已读／行动和 unknown 的业务事实。119 只验证 gate observation 中这些层级没有被折叠。
- 验收报告是一份 release/run-bound 审计产物，不是业务状态、activation ledger、current-head、delivery ledger 或稳定运行权威。

## 产品声明

- G01—G06 或 G09 的局部通过只表示对应技术 gate 通过。
- G07 passed 最多支持当前 scope `activation-ready`，不表示 active。
- G10/G11 passed 才能分别说明 target binding／获准真实接口 gate 通过，不等于主人已验收。
- 只有同一 release/run 的 G01—G12 全部 passed，且 G12 返回可由目标 Provider 读取的四项 opaque receipts，报告才允许 `product_acceptance = passed`；Module 本身仍不写 active。
- `stable_operation` 在所有组合下均只能是 `evidence-required`。一次产品验收不能宣称稳定运行。

## 必须控制的现实故障

| 验收 | 冻结控制 |
|---|---|
| 119-A1 | 固定顺序；首个 failed/cannot-confirm/not-authorized 后零后继执行且全部 blocked。 |
| 119-A2 | 每项绑定当前 release/run/gate/environment/authorization/evidence；篡改、跨 run 或旧 digest 拒绝。 |
| 119-A3 | 稳定 execution key；既有报告重放零执行；外部 unknown 不能在同 run 重做；投递层级不折叠。 |
| 119-A4 | G07 只 activation-ready；G12 receipts 与 active-path 证据齐全才允许 product acceptance passed。 |
| 119-A5 | G08 任一代表性 no-go 使整个 gate 非 passed；禁止当前主人 namespace 和手工挑选恢复。 |
| 119-A6 | G08/G10/G11/G12 逐 gate 授权；collector/report 严格无正文、无身份、无配置、无秘密。 |
| 119-A7 | 技术 gate、target/deployment、product acceptance 与 stable operation 分别报告，不夸大。 |

## 复杂度上限与停止规则

允许新增：一个 `AcceptanceRunContract`、一个严格 `GateExecutor` Seam、不可变 report/value objects、一个薄 CLI，以及合成和目标本地两个 Adapter。内部字段、codec、helper、文件布局和测试组织保持可逆。

禁止新增：可配置 gate DAG、通用 workflow/deployer、第二数据库、durable activation ledger、第二 current-head、第二投递状态、复制 HealthCore 的主人验收事实、自动取得外部批准，或在报告中保存目标原值。删除 `AcceptanceRunContract` 后顺序、授权、停止和 truthful verdict 会散回十二个 gate 调用者，因此 Module 有足够 Depth；删除任何第二业务权威只会降低复杂度，故不得建立。

冻结门错误、当前 `ReleaseManifest` 无法支持固定 run、真实 gate 需要未授权动作、或必须改变 Tickets 110—118 架构时立即停止并返回相应权威；不得边改门边实施。119-A1—A7 通过且没有经举证的 P0/P1/P2 后停止扩写自动门。真实 gate 仍逐项获批、逐层执行，首个 no-go 后停止。
