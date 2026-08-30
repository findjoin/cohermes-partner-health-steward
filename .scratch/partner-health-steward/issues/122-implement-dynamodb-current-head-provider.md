# 122 - 实现 DynamoDB current-head 生产 Provider

Type: task
Status: resolved
Parent: [健康管家首发 TO、CAN 与 HOW 决策闭合路线](../map.md)
Builds on: Ticket 120 staged release evidence at `777cc585bbda3e13385b73b9146c0d8f948838d1`
Unblocks: [123 - 实现生产 health-core 与 CorePort 服务](123-implement-production-health-core-and-coreport-service.md)

**What to build:** 严格实现现有 `CurrentHeadPort` 的单区域 DynamoDB Adapter，并以 disposable installation/table namespace 完成 Ticket 119 G08 所需的 current-head、lease、terminal、旧 fence 和迁移 canary。远端 item 不得包含健康正文、主人／联系人身份、凭据或医学值。

## Bounded acceptance

- 强一致 `read`、条件 `advance`、transition readback、lifecycle transition、execution lease acquire/lookup/release 与 writer-fence validation 一一实现现有 Interface。
- 超时、条件冲突、响应未知、重复 transition、旧 generation、旧 writer fence、terminal 和 lease overlap 保持既有 typed 结果；未知只按原 transition/execution identity 回查，不换 key 重做。
- DynamoDB item 字段和 IAM action 使用固定 allowlist；未知字段、区域／表／installation 错绑或一致性不可证明时在业务读写前失败关闭。
- disposable canary 覆盖 CAS/readback、terminal delete、旧 snapshot、writer-fence transfer/unknown 与回滚；销毁仅限预先解析并获批的 disposable namespace。
- Adapter contract 测试可用 local fake；G08 正向结论必须来自获准的真实单区域 disposable resource，fake 不得冒充通过。
- public writer-fence ref 严格使用 Ticket 121/122 共享 v1 格式；writer-transfer 必须采用 request 的 target ref，不得在 Provider 内另生成 fence。
- `GetItem` 全部强一致；状态与 exact receipt 由同一 `TransactWriteItems` 原子形成。SDK 的短时幂等 token 不能代替持久 receipt。

## External prerequisite

完成真实 G08 需要主人提供或批准一个专用 AWS account/region/table、最小 IAM 身份、费用／配额边界和针对 disposable namespace 的破坏性动作批准。Agent 不得读取或保存凭据值；缺少这些事实时可以完成代码但必须把 gate 保持 `not-authorized` 或 `cannot-confirm`。

## Not in this ticket

不实现本机密钥/vault、CorePort、Hermes、模型、Weixin、医学审核或真实主人迁移；不创建第二 current-head 或可配置多云抽象。

## Delivery discipline

编码前冻结一份 Provider 设计与 verifier-owned 测试门。只复用现有 `CurrentHeadPort`，不得为了通过测试改写状态机。通过后普通提交并推送当前任务分支。

## Frozen pre-code artifacts

- 冻结 checkpoint：commit `8de120d447c53848af2afbc9fce71a2afa71a642`、tree `0007c31f95a6712e2fefca1ff16790b53bee2da8`。
- 双轴共同审查内容点：commit `60121ea635b8cedc09556163bc9a6a6cb7294078`、tree `bcc4566d517155b720b28b5a8eb929bd8b6ddb3b`；Spec reviewer `PASS`，Standards reviewer `PASS`。
- 首次实施双轴审查发现 ordinary/terminal 推进未同步 LEASE-GUARD，且进程 lease cache 可遮蔽跨 Adapter release。verification authority 仅把既有 V02/V04 的 guard 同步与强读持久 receipt 要求机械化，没有增加产品能力或替代架构。修订 checkpoint：commit `1f6f55fe9930cbcfb3b59f9cc5def2cd09d089cc`、tree `d0b81b5208c15889558b08407d25bed095207d16`。
- 强读门首次执行后，verification authority 把 V04 的 scripted terminal HEAD 从“下一次任意 GetItem”队列移回真实 `HEAD` key，避免 lease key 读取到伪 HEAD；产品语义与断言不变。机械修订内容点：commit `ed165e1f1ffa33b2d6562533b0ac8e06eb3d7140`、tree `74d19c6056813f527511e601e771374d0b504c9a`。
- 修复复核确认 existing receipt 不能绕过 current HEAD：writer-transfer 后旧 lease acquire replay 必须 conflict，terminal 后历史 lease acquire replay 必须 terminal；历史 receipt 仍可由 exact lookup 读取。该既有顺序语义的修订 checkpoint：commit `4a51e8b278505ad5fcb5926b5804e9abd200d846`、tree `33a4f18c6a5e180c25733445e453b37009ca70c7`。
- 实施设计：`../design/122-frozen-implementation-design.md`
- 独立验证合同：`../design/122-frozen-verification-contract.md`
- verifier-owned 门：`../../../tests/test_ticket122_dynamodb_current_head.py`
- 当前冻结 blob：design `eec6f5a258030cea23e7f8e1d9bae0a116f0381c`；contract `278ea658fc694f88245ec04c4cd0401e42e53de0`；verifier `fccc0e7609755f9a386788aaeee32eaebfac9a7c`。原三 blob 已由上述既有语义机械化修订取代。
- 编码前机械结果：`1 failure / 6 skips / 0 errors`；唯一红灯为 `partner_health_steward.dynamodb_current_head` 尚不存在。
- 实现 Agent 不得修改上述三件套或既有 `CurrentHeadPort/HealthCore`；真实 G08 未获批准时只完成代码 checkpoint，不伪造 gate 通过。

## Answer

Ticket 122 的生产 Provider 代码已按冻结设计实现并通过本地冻结门与独立双轴审查，可供 Ticket 123 组合使用。

- 产品实现：`partner_health_steward/dynamodb_current_head.py`，最终实施提交 `d4c679b21a8d98692d4df0b1e6697b94b240d493`、tree `322111742db7929d049dea5184fb332e24e2414b`。
- 验证：Ticket 122 冻结门 `7/7 PASS`；项目全量 `763/763 PASS`（另有 7 项按环境合同跳过）；`compileall` 与 `git diff --check` 通过。
- 双轴终审：Spec 与 Standards 均为 `PASS`。最终修复保证历史 acquire receipt 不可绕过当前 HEAD：writer transfer 后返回 `HeadConflict`，terminal 后返回 `HeadTerminal`，exact lookup 仍保留历史 receipt。
- 外部边界：真实 AWS disposable G08 未获授权，状态保持 `not-authorized/cannot-confirm`；这不是代码通过的替代证据，后续获批后仍须单独执行并记录真实资源清理证据。
