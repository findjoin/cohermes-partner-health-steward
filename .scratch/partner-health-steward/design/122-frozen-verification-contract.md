# Ticket 122 冻结验证合同

> 状态：freeze-candidate。characterization 产品基线为 commit `52d569dc487b3bbc8023a797bd67b70a30cab0cb`、tree `5cfe065de74f6a86696a7a7fc79923d1f28ab8b1`；最终 frozen checkpoint 和 reviewer identity 只在复审通过后写入。verifier-owned 文件固定为 `tests/test_ticket122_dynamodb_current_head.py`；实现 Agent 不得修改三件套。

## 测试边界

测试只调用 `DynamoDBCurrentHead` 的现有九个 `CurrentHeadPort` 方法，并给它一个 verifier-owned 低层 DynamoDB fake。fake 只实现 `describe_table/get_item/transact_write_items`，记录完整 request，按 AWS error shape 注入 conditional、timeout、permission 与 ambiguous response；测试不读取产品私有字段，也不调用产品 schema/canonical helper 计算 expected value。

fixture 使用固定无正文 opaque 字段与 Ticket 121 的公开 fence 标准向量。所有 public output、fake request 和异常文本递归扫描：不得出现 raw writer capability、completion capability、健康正文、主人/联系人身份、credential 或绝对路径。

## 七门

| Gate | 验收 | 必须证明 |
| --- | --- | --- |
| 122-V01 | resource + read | constructor 只 DescribeTable 并钉死 ARN/TableId/region/schema/ACTIVE；HEAD 缺失不自动创建；所有 GetItem 显式 `ConsistentRead=True`；同名重建/错绑/未知字段失败。 |
| 122-V02 | ordinary CAS | expected 全字段 + current fence condition，HEAD generation +1 且 site/fence 保持；HEAD 与 exact transition receipt 单事务原子形成；两并发只有一个成功。 |
| 122-V03 | typed faults/recovery | known conflict、terminal、timeout、permission 与 ambiguous mutation 精确映射；ambiguous 零业务重试，exact strong lookup 只返回原 receipt 或 NotFound。 |
| 122-V04 | execution lease | acquire/lookup/release exact identity 幂等；既有 bounded `_execution_overlap` permit 允许 1→2，第三个或错误 permit 冲突；release operation ownership；release 与 LEASE-GUARD exact effect 在同一事务清除，随后新 effect 可获得 lease；terminal 与 active lease 互斥。 |
| 122-V05 | lifecycle | 无 active lease 时 terminal-delete 成功、receipt/readback/lookup 完整且后续 old snapshot/lease 为 terminal；有 active lease 时拒绝；transfer、响应丢失 lookup；transfer 精确采用 target fence/site，旧 proof 即时失效，target proof 成功，旧 lease history 保留而 live guard 清除。 |
| 122-V06 | Interface closure | Adapter 精确暴露现有九方法，不提供 bootstrap/create-table/第二状态机入口；prepared→CAS→readback→finalize、response loss/restart、stale snapshot/fence 的 Core 语义由既有回归保持不变，真实组合属于 Ticket 123。 |
| 122-V07 | data/IAM/closure | request actions 精确 allowlist；无 Query/Scan/auto-create；item schema/字段 allowlist；远端 request/output 无 secret/body；生成的 IAM 声明固定 table/attributes/LeadingKeys 且不宣称已在 AWS 生效。 |

编码前动态 import 必须是 `1 failure / 6 skips / 0 errors`。实现后 local fake 必须 `7/7 PASS`，并重跑 Ticket 110/117 的 prepared/CAS/readback、unknown/restart、old-fence Core 回归，证明既有状态机未被改写；Provider 与生产组合根的端到端注入只在 Ticket 123 验收。随后运行全量一次、`compileall`、`git diff --check`，并核对本设计、本合同和 verifier Git blob 零变化。

## G08 外部证据边界

本地 7/7 不能关闭 G08。真实正向结论必须记录专用 account/region/table ARN/TableId、role policy digest、release/run/gate/target approval ref、开始/结束非目标服务状态、每步 opaque receipt 与精确 cleanup/absence；不得记录 credential、健康正文或真实主人资料。

当前目标主机只读 characterization 仅证明 `python3` 为 3.10.12、没有 `python3.11`/AWS CLI，不能作为 G08 运行环境。SDK/runtime 组合属于 Ticket 123；122 不得为此增加 credential loader 或更改 Adapter 架构。没有获批 AWS disposable resource 或兼容运行时，只能报告 `not-authorized/cannot-confirm`。
