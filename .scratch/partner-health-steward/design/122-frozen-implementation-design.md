# Ticket 122 冻结实施设计

> 状态：frozen。候选基线为 commit `52d569dc487b3bbc8023a797bd67b70a30cab0cb`、tree `5cfe065de74f6a86696a7a7fc79923d1f28ab8b1`。本票只实现现有九方法 `CurrentHeadPort` 的 DynamoDB Adapter，不改变 Interface、`HealthCore`、`InMemoryCurrentHead` 或 ADR 0022。

## 唯一产品增量

新增 `partner_health_steward/dynamodb_current_head.py`，公开不可变 `DynamoHeadBinding(region, table_name, table_arn, table_id, installation_id, local_site, local_writer_fence_ref)` 与 `DynamoDBCurrentHead(client, binding)`。表 key 名固定为 `PK/SK`，因此不是调用者可配置项。binding 的 `runtime_iam_policy()` 只生成 verifier 可比较的最小策略声明，不应用策略、不访问 AWS。client 是由 Ticket 123 组合根创建的低层 DynamoDB client；本票不读取环境变量、不加载凭据、不创建 SDK Session。

构造时只调用 `DescribeTable`，验证 ACTIVE、region/account/ARN/TableId、固定 key schema 与 attribute definitions。缺表、同名重建、错区域/账号/schema/状态都在业务读写前失败。Adapter 不建表、不 bootstrap HEAD、不迁移 schema。

运行时动作 allowlist 只有 `DescribeTable`、强一致 `GetItem` 与 `TransactWriteItems`。禁止 Query、Scan、Batch、Streams、TTL、auto retry worker 和动态 table。所有 HEAD、receipt、lease lookup 必须显式 `ConsistentRead=True`。

## 固定 item 模型

单表 partition key 固定为 `installation_id`，sort key 固定为 opaque `record_key`。只允许五类：

- `HEAD`：仅 installation、generation、revision digest、transition id、public writer fence、terminal、site 与 schema version；
- `TRANSITION#<transition_id>#<operation_digest>`：exact `AdvanceIdentity` 与 applied head；
- `LIFECYCLE#<operation_ref>#<operation_digest>`：exact lifecycle identity 与 applied head；
- `LEASE#<effect_id>`：exact lease identity、lease id、released 与 release operation digest；
- `LEASE-GUARD`：当前活 effect id 集合及 generation/fence guard。

不得存 raw writer capability、completion capability、主人/联系人身份、健康正文、prompt、模型输出、医学值、凭据或任意 diagnostic text。decoder 对未知字段、类型、版本或不透明值失败关闭。

每个 advance/lifecycle/lease acquire/release 使用一个 `TransactWriteItems`：条件必须合并在同一 HEAD 或 LEASE-GUARD 的 Put/Update `ConditionExpression` 中；DynamoDB 禁止在同一事务对同 item 再放独立 ConditionCheck。状态更新与 exact receipt 原子形成。成功返回前强读 HEAD/receipt；响应丢失或结果未知时不重做新 identity，只由 `HealthCore` 调用 exact lookup。

可使用稳定且不超过 36 字符的 `ClientRequestToken` 降低 SDK 的短时重送风险，但其 10 分钟窗口不是持久恢复证据；永久恢复只能依赖事务内 receipt 的强读。

## Writer fence 与 lifecycle

Ticket 121/122 共享 public ref：

```text
fence:v1:<base64url-128-bit-nonce>:<sha256-hex(raw-writer-capability)>
```

Adapter 只从 `WriterFenceProof.capability` 计算 SHA-256 并 constant-time 比较当前 HEAD ref 的摘要；不保存 raw capability。普通 advance 保持 fence/site。terminal-delete 设置 terminal 且保留历史 receipt；活 lease 存在时拒绝。

writer-transfer 验证旧 writer proof 后，必须在同一事务把 HEAD 的 site/fence 精确设置为 request 的 `target_site/target_writer_fence_ref`、generation +1、形成 lifecycle receipt并清除 live guard；保留旧 lease 历史。不得自行生成 fence。旧 site/fence 从事务提交起失效；target raw capability 仍只存在目标 Ticket 121 facility。

## typed 结果与重试边界

- 条件表达式明确失败：`HeadConflict`；
- terminal：`HeadTerminal`；
- 已证明 exact receipt 不存在：`TransitionNotFound` / `ExecutionLeaseNotFound`；
- read/lookup transport deadline 且未可能写入：`HeadTimeout`；
- 任何 mutating response 不可判定：`HeadUnknown`；
- resource/schema/permission/未知 SDK 错误：`CurrentHeadError`。

Adapter 不复制 `HealthCore` 的 prepared/finalize/unknown 状态机，不在 ambiguous mutation 后自动换 token/key 重试，不把 SDK 默认 retry 或 ClientRequestToken 当业务确认。

## 本地七门与真实 G08

冻结 verifier 为 `tests/test_ticket122_dynamodb_current_head.py`：编码前 `1 failure / 6 skips / 0 errors`，唯一红灯是 Adapter Module 缺失；实现后 local fake `7/7 PASS`。

真实 Ticket 119 G08 是独立外部门：必须由用户明确批准 dedicated account/region/table/TableId、最小 IAM role、费用/配额、disposable prefix 和 destructive cleanup，并绑定当前 release/run/gate/target。顺序固定为身份/IAM → 外部预置初始 HEAD → strong read/CAS/concurrency/readback → response-loss lookup → lease/overlap/release → terminal/old snapshot → 两 site transfer/旧 fence → 精确 cleanup/absence → 非目标服务状态对照。缺批准时产品代码可完成，但 G08 只能是 `not-authorized/cannot-confirm`。

IAM 固定 table ARN、action allowlist、attribute allowlist，并以 `ForAllValues:StringLike dynamodb:LeadingKeys` 限定 installation partition。真实 canary 不读取或保存 credential 值。

## 复杂度上限与停止规则

最多一个 Adapter Module、必要 export、一个 verifier 文件和一个薄 G08 工具；禁止第二 current-head、ORM/repository、多云抽象、缓存、后台 retry、自动建表/head、SDK 凭据加载、Query/Scan，以及冻结阶段访问 AWS。

若既有九方法 Interface 必须改变、单次 DynamoDB 事务不能原子形成状态与 exact receipt、需要把 secret/body 写入远端，或共享 fence 合同无法由 121 产生，立即停止并返回可复现冲突，不改业务架构。
