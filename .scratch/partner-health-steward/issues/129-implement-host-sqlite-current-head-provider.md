# 129 - 实现 DMIT 宿主 SQLite current-head Provider

Type: task
Status: claimed
Parent: [健康管家首发 TO、CAN 与 HOW 决策闭合路线](../map.md)
Blocked by: [121 - 实现主机私有健康密钥与能力权威](121-implement-host-private-health-authorities.md)
Unblocks: [128 - 部署并完成主人产品验收](128-deploy-and-complete-owner-product-acceptance.md)

## Question

主人已选择仅使用 DMIT 并接受整机旧快照恢复限制后，如何实现现有九方法 CurrentHeadPort 的真实宿主 Provider，在正常运行、并发、进程重启、崩溃、未知响应、删除及 writer transfer 下保留当前权威合同，并以明确的 `host-sqlite` 身份接入生产而不冒充 DynamoDB 或域外新鲜性？

## Authority and accepted boundary

2026-10-18 主人在本会话明确选择“仅用 DMIT，接受旧快照恢复限制”。见[主人决定证据](../evidence/38-owner-host-current-head-choice-20261018.md)与[原始决定记录](../design/deployment-storage-choice-20261018.md#主人决定2026-10-18)。不再等待 AWS 账号，也不再次询问同一取舍。

采用同机不透明 current-head 后，整机旧快照若同时恢复旧健康数据库、head 与秘密材料，无法自动证明其后的删除、批准撤销或 writer transfer。恢复后须离线，由主人决定丢弃旧安装并重新空白初始化；这是操作限制，不是自动检测或技术防复活保证。正常进程/服务重启、当前受管数据删除、未知冻结、旧 holder fencing、受控效果、同意及加密不放宽。旧 DynamoDB 代码/冻结测试保留为历史与独立可选 Provider，不改其合同。

## Required delta

- 一个实现九方法 CurrentHeadPort 的 `HostSQLiteCurrentHead`，只持久不透明 head、transition/lifecycle/lease receipts 及当前 lease 约束；不持久健康正文、凭据、writer capability 或第二业务 ledger。
- 明确的新 installation bootstrap 与普通打开分别提供；打开缺失/损坏/错绑/terminal head 不得自动新建或覆盖。
- 同一事务原子提交 head 与 receipt；跨进程 CAS、lease、terminal/transfer 与 typed recovery 保持当前语义。
- 使用 Ticket 121 的公开 fence 及 SHA-256 capability proof 验证，不将 writer capability 放入 head 文件。
- 生产组合根显式允许该 concrete Provider，状态/报告准确声明 `host-sqlite` 及整机快照限制；不能声称 DynamoDB/G08 外部证明通过。

## Bounded acceptance

| ID | 必须证明的结果 |
| --- | --- |
| 129-A1 | 仅显式 bootstrap 新安装；private directory/file、无 symlink/hardlink、schema/namespace 验证；重复或错绑 bootstrap 零覆写 |
| 129-A2 | 两个独立进程竞争同一 expected head 只有一个 CAS 成功；head+exact receipt 原子且重启后可读回；冲突/错误 identity 不得冒充成功 |
| 129-A3 | proof 验证 binding/site/current authority 与公开 fence 的 capability hash；伪造 capability、旧 generation、旧 fence、transfer 后旧 holder 与 terminal 写入均拒绝 |
| 129-A4 | lease acquire/lookup/release 保持 exact identity、当前 HEAD 检查、独占与既有受信 overlap；terminal 不越过 active lease，transfer 只使旧 lease 失去活体权限而保留恢复 receipt |
| 129-A5 | 崩溃/提交后响应未知以 exact lookup/readback 恢复；损坏、DB busy/IO 失败、被替换文件或 namespace 错绑失败关闭，不重新 bootstrap、重放外部效果或盲重试 mutation |
| 129-A6 | 存储/日志无正文或 capability secret；生产投影准确 provider 身份与已接受快照边界，正常删除与受管 purge 没有被降级；DynamoDB 既有合同不变 |

唯一设计：[129-host-current-head-design.md](../design/129-host-current-head-design.md)。ADR 候选：[0023](../../../docs/adr/0023-allow-owner-selected-host-current-head-with-snapshot-limit.md)。独立 verification Agent 持有有限门与实现前红灯，实施 Agent 不修改它们。冻结设计/门与 fresh-context Spec/Standards 对同一 checkpoint 预审完成后，才修改产品。

## Not in scope

不实现另一画像/业务数据库、通用 event store、备份框架、远程 Provider 或自动旧 VM 检测；不修改 Hermes/模型/微信授权；不读取真实健康资料、不运行真实删除/迁移、不以本票代码通过冒充已部署或主人验收。

## Completion evidence

实现后记录 finite gates、独立进程 CAS 与恢复结果、受影响回归、源码/依赖 identity、两轴独立复核及诚实 provider/快照声明。只有这些证据完整才可追加 Answer 并解决；当前只是设计候选。

## 2026-10-18 pre-code checkpoint candidate

独立 verification authority 为 implementation_audit；候选合同 `../design/129-frozen-verification-contract.md`，verifier-owned `../../../tests/test_ticket129_host_current_head.py`。6个有限门当前是缺公开Module的6个明确failure、0error/skip；并发、真实HostPrivateVault、SIGKILL/readback、typed overlap、terminal/transfer和生产身份均使用离线合成安装，不接触真实健康数据。产品实现仍待同一commit/tree新鲜双轴预审。

## Frozen implementation authority (2026-10-18)

- reviewed pre-code commit: `fe9c058fcf634ebe624f98c1c72adde90a86032a`; tree: `858f0cd397853138c226f35a968d1deef014dd28`.
- Fresh-context Spec: PASS；Fresh-context Standards: PASS；证据 `../evidence/40-ticket124-129-precode-review-20261018.md`。
- `.scratch/partner-health-steward/design/129-host-current-head-design.md` blob: `ce191ff936b75ab7171a3a7aab792c2732b835b2`.
- `.scratch/partner-health-steward/design/129-frozen-verification-contract.md` blob: `c8f30f68c6fb520a5dc43b0a01b09176a4dadec6`.
- `tests/test_ticket129_host_current_head.py` blob: `40ee8f1fae15beaefaae63e803ad9f07fed0ad76`.
- 允许严格按上述冻结设计实施；产品实施者不得修改冻结三件套或自行闭票。真实部署/外部效果仍按后继既有门，未被本次预审冒充通过。
