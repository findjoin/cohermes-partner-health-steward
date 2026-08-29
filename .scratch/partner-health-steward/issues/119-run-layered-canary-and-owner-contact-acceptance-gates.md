# 119 - 执行分层 canary 与主人联系人验收门槛

Type: task
Status: claimed
Parent: [健康管家首发 TO、CAN 与 HOW 决策闭合路线](../map.md)
Blocked by: [118 - 完成 Hermes/Weixin 宿主合同发布与回滚准备](118-complete-hermes-weixin-host-contract-release-and-rollback-preparation.md)

**What to build:** 建立并执行从静态 release 到获准真实主人/联系人验收的分层门槛。每层都必须记录可定位的通过、失败或无法确认事实；未通过项保持不可用或 staged，不得把安装、测试通过、接口接受或模型自述宣传为稳定运行。

**Blocked by:** 118 - 完成 Hermes/Weixin 宿主合同发布与回滚准备

- [ ] 按静态 manifest、合成 core、本机 socket/SQLite/认证加密、崩溃/未知故障、宿主合同、StrictHealthLLM、知识/医学审核、current-head、删除/迁移 canary 的顺序建立门槛。
- [ ] 医学内容权利、冻结中文版本、专业审核、诊断范围激活和外部服务资源均有独立证据；缺失时 BMI 保持 staged，健康路径如实显示不可用或无法确认。
- [ ] 真实模型、真实 Weixin、真实联系人、主人和联系人验收只在单独批准、合成/脱敏前置测试通过且不把凭据/资料写入仓库后执行。
- [ ] 分层结果严格区分业务形成、提交、发送尝试、接口接受、送达、已读/实际行动和未知；未知效果不自动重做。
- [ ] 任何验收失败、可信前提丢失、current-head 不一致、旧 fence 活跃或删除/迁移未闭合都阻止 active/稳定运行声明，并保留回滚路径。
- [ ] 产出可定位的验收报告和剩余硬门槛，未读取或上传真实健康资料、密钥、Token、服务器配置或运行数据库。

## Implementation contract

### Start gate and authority to load

只在 Ticket 118 已 `resolved` 且 110—118 的 release manifest、验证入口和完成记录均可定位后开始。执行前必须读取：

- [当前实现 Spec](../spec.md)的完整 Testing Decisions、“分层验收”和 Out of Scope；
- [ADR 0022](../../../docs/adr/0022-select-current-health-steward-route-after-seven-skill-can-closure.md)的“验证与非承诺”；
- [当前 HOW 证据](../evidence/36-how-route-after-current-can-closure-20260822.md)的“Validation boundary and dependencies”；
- [`CONTEXT.md`](../../../CONTEXT.md)中的“完整首发健康管家”“产品级验收”“健康管家运行状态”和“稳定运行”；
- Ticket 110—118 的最终 `## Answer`、release digest、测试证据和明确未验证项。

若 Ticket 118 未闭合，只能检查验收设计，不得 claim、运行后续 canary 或用旧 `ops/`/历史部署证据替代当前 release。

### Scope and ownership

本票完整拥有一条**有序验收账本**：为当前 release 建立每层 gate、执行获准层、保存可定位证据、在首个阻塞层停止，并把 product acceptance 与单项技术通过严格分开。

本票不是继续开发功能的容器。发现实现缺陷时记录失败证据并回到对应 Ticket 修复；发现路线存在性冲突时回 CAN；发现需要外部许可、医学签字、真实模型/微信、主人或联系人参与时，取得明确批准后才执行该层。未批准不是通过，也不是失败，只是尚未执行的硬门槛。

验收报告写入当前权威链 `.scratch/partner-health-steward/evidence/`，使用实施时下一个可用序号和固定 release digest；Ticket `## Answer` 只汇总并链接该报告，不复制第二份结果。原复选项“未读取真实健康资料/服务器配置/运行数据库”约束验收 Agent、collector 及其产物：它们不得接收、复制或保存原始健康正文、凭据、完整配置、运行数据库、联系人身份或模型 transcript。获准的 G10 target-local probe 可在目标边界内以最小权限核验必需 artifact/config/ACL/socket，但只返回绑定 target/release/run 的无值证明；G12 产品运行时可在既定私有边界内处理主人输入，但 collector 只接收无正文 opaque event/result identity 与主人验收事实。原始值、正文或可逆摘要均不得离开目标边界或进入报告、fixture、日志、聊天和仓库。

### Required gate ledger

每个 gate 记录：gate ID、release digest、前置 gate、环境分类、授权引用、执行时间、执行者、命令/步骤版本、输入 fixture 摘要、结果、证据路径、失败/未知影响、回滚状态和下一步。允许结果仅为：

- `passed`：该 gate 的全部验收在声明边界内有证据；
- `failed`：已执行且至少一项明确不满足；
- `cannot-confirm`：已执行但权威终态或证据不足；
- `not-authorized`：该 gate 已成为当前 frontier，但所需外部/真实行动尚未获批，因此未执行；
- `blocked`：前置 gate 未 `passed`，本 gate 未执行；必须记录 `blocked_by_gate`，不能借用 `not-authorized` 或 `cannot-confirm` 表示。

`failed`、`cannot-confirm`、`not-authorized`、`blocked` 都不解锁依赖该 gate 的后续层，也不能支持 active/稳定/已验收声明。历史截图、模型自述、服务存活、安装成功、接口接受或旧 release 测试不能替代当前 digest 的 gate 证据。

### Ordered acceptance gates

| Gate | Required scope | Pass condition |
|---|---|---|
| 119-G01 | 静态 release/manifest | 当前 digest 的 Plugin/core/七 Skill/adapter/model/capability-profile/MinimumHelpBundle/knowledge/danger-rules/diagnostic/migration/ACL 需求完整且 hash 验证；旧入口未声明，MinimumHelpBundle 缺失时健康入口不能启动 |
| 119-G02 | 合成 core | 初始化、日常 turn、证据/画像、设置/权利、任务/review/outbox、模型候选、安全/诊断、联系人、删除/迁移的当前测试全部通过 |
| 119-G03 | 本机进程边界 | 真实本机 Unix socket、SQLite/认证加密、peer/权限、密钥缺失和普通 Session/Memory 副本边界通过；平台不具备时为 cannot-confirm |
| 119-G04 | 崩溃/未知故障 | prepare/current-head/finalize、outbox、model/delivery unknown、重启、旧 snapshot 和 stale fence 故障矩阵通过 |
| 119-G05 | 固定 Hermes 宿主合同 | 当前 pinned artifact 上 lifecycle、pre-native entry、无旁路、co-stop、升级失效通过 |
| 119-G06 | StrictHealthLLM 合同 | 合成 payload 下首跳身份、容量、严格结构、completed/incomplete/failed/unknown、actual model、无 fallback 通过；真实模型另受批准 |
| 119-G07 | 知识/医学/安全准入 | MinimumHelpBundle、知识、危险规则和诊断内容的实际权利、冻结中文 bundle、精确 hash 的相称专业/安全审核、实现兼容和撤回/过期规则有独立证据；通过只使 BMI 对当前 digest `activation-ready`，不产生 active/主人验收事实 |
| 119-G08 | current-head/删除/迁移 canary | 使用预先解析、无真实主人状态的 disposable installation/current-head/storage/key namespace，并取得针对精确目标的破坏性动作批准；身份/IAM/配额、CAS/readback、terminal delete、purge registry 的 key/index/export/backup/staging provider、old VM、writer-fence transfer/unknown 和回滚全部通过 |
| 119-G09 | 合成渠道 canary | 仅用 deny-network loopback/fake delivery port 验证 Weixin/adapter 形状的 ingress、reply、send、replay/restart 和分层终态；禁止真实 Weixin 凭据、账号、API 或网络，任何真实渠道动作只能在 G10 通过且 G11 获批后执行 |
| 119-G10 | 目标 Partner binding | 单独批准后，用合成数据核验目标 Partner artifact/version/dirty digest、required patch/native-disable assertion、真实 Plugin lifecycle、pre-native 入口、无旁路、服务身份/ACL/socket、current release digest 和回滚绑定；并用 Ticket 118 固定 builder 生成及独立批准绑定 provider/canonical base URL/API/requested model、允许的 actual-model identity/alias 精确集合、config generation、输入 token 保守上界方法、包装开销（token）、输出预留（token）、共同上下文下界（token）、证据和失效条件的真实 capability profile；未通过不得进入真实渠道/模型 |
| 119-G11 | 真实模型与微信 | 单独批准后，以最小合成/脱敏数据验证当前首跳、真实模型终态、真实微信和未知边界；只可消费 G10 对同一 target/release/config generation 批准的 current capability profile，实际 model 未被 profile 覆盖或任一失效条件触发时调用前停止；凭据/载荷不进仓库 |
| 119-G12 | 主人/联系人产品验收 | 单独批准后先把精确 release/bundle 置为一次性 `acceptance-authorized`，完成隔离 BMI 验收；主人接受后原子写入验收事实并转 active，再复验 active-path。同时逐项完成初始化、自然聊天更新画像、健康问答、每日复盘、任务自动生成/受控派发、任务失败或未知后的状态重判、必要主动支持、主人数据权利、危险升级、最小联系人警报/纠正，并取得“有用、清楚、可信”的主人确认 |

G01—G06、G09 的测试通过不替代 G07、G08、G10—G12。G08 永远不顺带删除/迁移当前 Partner 的真实主人状态；任何真实主人删除/迁移仍需针对精确对象的独立批准。完整首发/产品级验收只有在所有强制 gate 对同一 release digest `passed` 时成立；“稳定运行”仍需要上线后的持续业务证据，不能由本票预设天数或一次验收直接宣布。

### Acceptance matrix

| ID | Required observable result | Forbidden substitute | Required evidence |
|---|---|---|---|
| 119-A1 | gate ledger 严格执行依赖，首个未通过层把所有后继标记 `blocked` 并阻止 active/accepted 宣称 | 跳层、漏掉未执行 gate、用 not-authorized/cannot-confirm 代替 blocked、旧 digest 证据复用 | gate dependency 单元测试和含 failed/cannot-confirm/not-authorized/blocked 的合成报告 |
| 119-A2 | 每个结果绑定同一 release digest、环境/授权和可定位原始证据，报告可重复验证 | 截图、聊天总结、模型自述或人工勾选无证据 | report schema、hash、路径、授权缺失和篡改检测测试 |
| 119-A3 | 业务形成/提交/尝试/accepted/送达/已读/行动/unknown 分层贯穿 owner/contact canary | accepted=送达、发送无错=主人已看到、unknown 自动重做 | 分层结果、乱序/重复回交、unknown freeze 和一次纠正 canary |
| 119-A4 | BMI 按 staged→activation-ready→acceptance-authorized→active 推进；G07 不激活，G12 的一次验收成功与 active 原子绑定并复验 active-path | 合成测试/代码存在/公开来源冒充权利/审核/主人验收，或 acceptance mode 服务普通消息 | 权利/中文 bundle/reviewer/hash/撤回/expiry、一次授权、主人接受/拒绝/unknown、active transition 和复验测试 |
| 119-A5 | disposable canary 中 current-head 不一致、旧 fence、purge registry 缺项、删除/迁移未闭合和 rollback 不可用均形成明确 no-go | 使用当前主人 namespace、本地 DB 可读、进程重启或手工选实例冒充恢复 | target isolation/approval、CAS/readback/old VM/terminal/provider purge/transfer unknown/rollback canary 证据 |
| 119-A6 | target binding、真实 capability profile、模型、Weixin、主人、联系人仅在明确授权和前置通过后执行；target-local probe/产品运行时最小处理不向验收 Agent 或仓库暴露原值，仓库只保存无内容结果 | 未授权试跑、空白/旧/未批准 profile、把完整配置/正文/运行库或可逆摘要返回 collector、真实资料/配置/凭据入库、synthetic/pinned fixture 冒充目标 Partner | approval preflight、target-local least-privilege/attestation、target artifact/dirty digest、actual lifecycle/ACL/entry、profile 全字段/计量/下界/失效/actual-model drift、collector input schema、fixture/data scan、redacted evidence 和 revocation 测试 |
| 119-A7 | 报告分别给出技术 gate 结果、product acceptance verdict、稳定运行尚需证据和剩余硬门槛 | 一项测试通过=已部署/已验收/稳定运行 | 报告 schema、truthful claim linter 和不同 gate 组合的 verdict 测试 |

`119-A1`—`119-A7` 是功能 verdict 和未来冻结门的追踪单位。自动验证使用能杀死独立现实错误的等价类，不把矩阵中的标点、字段或 gate 组合展开成隐藏 Case registry，也不提前固定 collector/test 文件或实现 slice。人工批准和主人/联系人验收不能由自动测试伪造。

### 编码前冻结与预审

以上 gate ledger、G01—G12、语义合同和验收矩阵是本票的冻结输入，不表示详细 collector 设计或自动测试门已经冻结。Ticket 118 闭合且本票被 claim 后，先 characterization 当前 release/preflight 能力与真实 frontier，再形成一份唯一增量冻结设计和独立 verifier-owned 测试门；它们必须绑定同一 commit/tree、预期红灯、既有绿灯和验证命令，并在任何实现修改或 canary 执行前由 fresh-context Spec/Standards reviewer 预审通过。

本票当前保留既有 staged-family 状态术语作为未来冻结输入，不在上游尚未完成时预先改写。轮到本票冻结时若它与 Tickets 116—118 的已验收实现或权威 Spec 存在冲突，必须把差异和取舍交给主人确认；不得为保留旧术语重构已验收产品，也不得由 Agent 静默改写本票目标。

冻结自动测试门只验证 ledger、collector、依赖、授权和 no-go 行为，不能替代 G01—G12 的真实 gate 证据。获准 gate 仍按既定顺序执行；全部强制 gate 只有对同一 release digest `passed` 才支持产品验收。digest 变化后必须建立新 run，旧证据不得继续闭票。

### 一致性实施、核验、停止与闭票

以通过编码前预审的冻结 checkpoint 为 `review_base`。编码 Agent 只可做使已封存红灯转绿所必需的最小 ledger/collector 修改，并保留既有绿色行为；不得修改冻结设计、冻结验证合同或 verifier-owned 测试，不得新增测试类别、产品功能或验收门。119 的重点是验证真实环境和上线证据，不得借审查重构产品架构。

若冻结门本身错误、实现存在缺陷、需要新架构或外部决定/授权，立即停止：实现缺陷带证据退回对应 Ticket，路线存在性冲突退回 CAN，外部行动等待明确批准；不得在 119 中边改产品架构边验收。

实现后重跑同一冻结门、Ticket 118 的当前 release/preflight 入口、受影响回归，以及 `python -m unittest discover -v -s tests -p "test_ticket119_*.py"`、`python -m unittest discover -v`、`python -m compileall -q partner_health_steward tests`、`git diff --check`，再形成 `reviewed_commit`/tree。fresh-context Spec/Standards reviewer 只核实冻结设计、冻结自动门、真实 gate 证据和声明真实性，不重新设计产品。finding 只有同时满足 P0/P1/P2、可重复步骤、可定位证据和被破坏的冻结验收 ID/gate/不变量时才阻塞；P3、理论可能、替代偏好和新功能建议不阻塞。

每次 no-go、unknown 或未授权尝试只冻结一份 run record 并停止后继 gate。任何真实模型、微信、联系人、主人、current-head、删除、迁移、部署、许可或医学审核动作必须预先逐项获批；缺批准记录 `not-authorized`。不得把报告、自动测试、安装、接口接受或单次通过写成 active、产品验收或稳定运行。

只有 G01—G12 全部对同一 release digest `passed`、冻结验收全绿且两轴对同一 checkpoint `pass` 后，才可写 `product acceptance: passed`。形成 `reviewed_commit` 前记录 `git status --porcelain=v1 --untracked-files=all`，不得遗留未提交或未跟踪的实现、冻结、ledger 或证据文件。随后仅追加 `## Answer`、状态和 Map pointer，记录两轴可定位 verdict、共同 base/commit/tree、release/run/digest 及长期稳定仍需的证据；确认相对 `reviewed_commit` 仅有闭票元数据后提交，并对当前分支执行普通 `git push`。推送被拒绝时停止，禁止 force push 或改写历史。

## Pre-code freeze evidence

Ticket 119 已完成当前产品 characterization，并冻结实施设计和独立 verifier-owned 自动门；本节不是实施或真实 gate 证据，不构成 `resolved`，Map 未更新，也没有执行任何真实部署、模型、Weixin、联系人、删除、迁移或主人验收。

- 产品基线：commit `dc6b26b03aa076b405a7b28d440de058b783f135`，tree `d69e2b698848eae28e0245d07f28847583711877`；Ticket 118 `7/7 PASS`，Ticket 117 `9/9 PASS`，项目全量 `736/736 PASS`。
- 当前可复现差额：包未公开 `AcceptanceRunContract`，不存在 Ticket 119 自动门或工具入口；`hasattr(partner_health_steward, "AcceptanceRunContract") == False`。
- 冻结实施设计：`design/119-frozen-implementation-design.md`，SHA-256 `5846c573a251cf747e7e100ef4b8b57bbed1f7f5dc40e90a78b295e7c2d28d6b`。
- 冻结验证合同：`design/119-frozen-verification-contract.md`，SHA-256 `79ecbb7d96b642bc94ef975bf06ef39c7566b108b87993b7e24dc4b190a4ef97`。
- verifier-owned test：`tests/test_ticket119_integration.py`，SHA-256 `978069af0dec6731111c49c9804c49982a96026e628ad60a413deb058d261642`。
- 编码前 Gate：`1 failure / 6 skips / 0 errors`；唯一红灯是公共 Module 缺失，后六门只因同一前置缺失 skip。`compileall` 与差异检查通过。
- 当前真实 frontier 未执行。G03 的目标 Linux peer/ACL、G07 的权利与医学审核、G08/G10—G12 的 disposable/Partner/真实接口/主人联系人动作仍需各自事实或明确批准；候选自动门不能替代这些证据。
- 编码前双轴预审绑定 candidate commit `5f383842cea3cb7351663f89ebd5d1f28230b129`、tree `3238e7f9ce1d01a6637cc62ec37a1b00d581b746`：Spec PASS；Standards PASS。初审发现的 synthetic 假验收、A3 分层缺失、旧 report 重放与 approval/target binding 四类缺口均已在冻结阶段关闭；复核未重开风险搜索。
- 冻结元数据提交为 `84f2976f5b72df8efb41e7127b6a8cdd7a963a0f`、tree `2b7cdaa4ebd94b944b432da2d118a99049360e2a`；实施设计 blob `fc4332aa941a168b839bd0ec1d27911a5c46049a`、验证合同 blob `86bf462a8d3563081e5652ff753a09415bb03df1`、verifier test blob `9dbf49eee033cf1804a0ef0b2bec35db5d182b68`。原 Spec／Standards reviewer 对该提交完成 metadata-only 复核并均为 PASS，确认冻结语义和测试字节级未变，且未重开风险搜索。

编码 Agent 只能在预审通过的冻结 checkpoint 上实现一个深 `AcceptanceRunContract`、严格 `GateExecutor` Seam、不可变 report/value objects 和薄工具入口，使同一七门从 `1 failure / 6 skips` 变为 `7/7 PASS`。不得修改冻结三件套，不得改 HealthCore、HostReleaseContract、current-head、诊断激活或投递权威，不得执行未获批真实 gate。若冻结门错误或需要产品架构变化，立即返回冻结阶段。

