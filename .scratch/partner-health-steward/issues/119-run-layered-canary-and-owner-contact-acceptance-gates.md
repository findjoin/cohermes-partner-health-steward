# 119 - 执行分层 canary 与主人联系人验收门槛

Type: task
Status: ready-for-agent
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

每个 `119-A*` 是功能 verdict；`Required evidence` 中以顿号、斜线、逗号或“分别/每类/全分支”列出的每个场景都是独立 Case。实现前按出现顺序登记 `119-Ax-Cyy`，每个 Case 必须映射到可单独失败、输出可见的 report/ledger test 或实际 gate 证据；不能用一个整体断言覆盖多个 Case。人工批准和主人/联系人验收不能由自动测试伪造，完成条件是全部 Case 与强制 gate 对同一 digest `covered=green/passed`。

### Execution slices

每个自动化 slice 固定执行：登记本 slice 全部 Case → 添加红测并确认预期失败 → 最小实现转绿 → 运行本 slice 与全部前置 slice 回归。测试按 slice 拆为 `tests/test_ticket119_ledger.py`、`test_ticket119_collector.py`、`test_ticket119_preflight.py` 和 `test_ticket119_verdict.py`。

1. **Red ledger/report contract**：先建立 gate schema、依赖、release digest、五种结果、claim linter 和篡改检测测试。完成标准：119-A1、A2、A7 的全部错误报告 Case 稳定失败。
2. **Automated evidence collector**：实现只读、无秘密的 gate runner/collector，复用 Ticket 118 的单一验证入口。完成标准：G01—G06 的合成执行能生成可重复 ledger，不会越过失败层。
3. **Fault and external preflight**：实现 G07—G12 的证据/授权/target isolation preflight、no-go 和 rollback 状态检查。完成标准：前置未过为 `blocked`；当前 frontier 缺批准为 `not-authorized`；已执行但权威不足为 `cannot-confirm`；绝不误报 passed。
4. **Approved execution**：按顺序执行当时已经获得明确授权的 gate；每层完成即冻结证据和 digest。完成标准：每个已执行 gate 有完整 ledger，后续执行符合依赖与批准。
5. **Fresh-context acceptance review**：冻结最终报告、原始证据引用、产品声明和待审 checkpoint，再启动下面规定的 Standards/Spec 双轴 reviewer。完成标准：119-A1—A7 全部有证据，两个 reviewer 审查同一 release/run/commit identity，任何未执行或未通过 gate 都明确阻止相应声明。
6. **Ticket completion decision**：同一个顶层 Agent 可以编排闭票，但每次 no-go/未知/未授权尝试只冻结一份 run record，Ticket 继续保持未完成；只有同一 release digest 的全部强制 gate `passed` 且两个 fresh-context reviewer 均通过，顶层 Agent 才能写 `product acceptance: passed` 的 `## Answer` 并决定 `resolved`。

### Verification and stop conditions

交审至少运行：

- `python -m unittest discover -v -s tests -p "test_ticket119_*.py"`
- Ticket 118 提供的当前 release/preflight 验证入口
- `python -m unittest discover -v`
- `python -m compileall -q partner_health_steward tests`
- `git diff --check`

列出并审查全部未跟踪文件，记录实际 Python/关键依赖版本。任何真实模型、微信、联系人、主人、current-head、删除、迁移、部署、许可接受或医学审核动作必须在执行前取得对应的明确批准；缺批准就记录 `not-authorized` 并停止该分支。不得把报告生成、自动测试、安装、接口接受或单次通过写成 active、产品验收或稳定运行。

实施 Agent 先在本票末尾追加 `## Implementation evidence (unreviewed)`，逐 Case 记录测试/实际 gate、证据路径、命令/结果摘要和 release/run identity。直接编写实现或执行 canary 的上下文不能把自评当作审查证据，必须执行以下双轴门：

1. 首次实施修改前把包含本合同的当前 `HEAD` 固定为 `review_base`。同一 release digest 的全部强制 gate `passed` 后，提交无秘密的最终 ledger、证据引用和实施记录，确认工作区无未提交或未跟踪实现/证据文件，并记录 `reviewed_commit` 及其 tree hash；随后启动两个全新上下文的 reviewer Agent。reviewer 只读取权威合同、`git diff <review_base>...<reviewed_commit>` 的完整范围、相关文件最终状态、稳定证据引用和测试结果，不继承实施/canary 推理或完成判断，并在最终 verdict 中共同引用同一个 base、commit、tree、release digest 和 run identity。
2. **Spec reviewer** 逐项核对当前 Spec、`CONTEXT.md`、ADR 0022、本票 required semantic contracts、G01—G12、禁止替代物和每个 `119-Ax-Cyy`，为每项 finding 标注 P0—P3、给出文件/证据定位、A1—A7 verdict、全部强制 gate verdict、产品验收 verdict 和总 verdict。
3. **Standards reviewer** 独立核对适用 `AGENTS.md`、项目 agent 文档、ADR 0022、授权边界、目标隔离、最小披露、release/run 身份、证据真实性、claim linter、回滚和稳定性声明，为每项 finding 标注 P0—P3，并输出文件/证据定位和总 verdict。
4. 任一强制 gate 为 `failed`、`cannot-confirm`、`not-authorized` 或 `blocked`，任一 A Case 非绿、验证失败、硬规范违规、任一轴非 `pass` 或存在未解决的 P0/P1/P2 finding，都阻止 `product acceptance: passed` 和闭票。顶层 Agent 修复或在新授权下执行后必须形成新的 checkpoint、重跑受影响 gate 与验证，并让两个 reviewer 对同一新身份重新给出最终 verdict；任何生产代码、测试、配置、release、ledger 或证据引用在最终 verdict 后变化都会使两份 verdict 同时失效。P3 只有在明确证明不影响本票产品验收且记录为后继工作时才可保留。
5. 全部强制 gate 对同一 release digest `passed` 且两轴对同一个最终 checkpoint 给出 `pass` 后，顶层 Agent 只可追加 `## Answer`、把本票标为 `resolved`，并按 `docs/agents/issue-tracker.md` 在 Map 添加简明 context pointer；`## Answer` 必须记录两个 reviewer、共同的 `review_base`/`reviewed_commit`/tree/release/run identity、最终 Case/gate 映射、验证命令/结果、`product acceptance: passed` 以及仍不足以宣称长期稳定的证据。关票提交前确认相对 `reviewed_commit` 的变化只包含本票和 Map 的关票元数据，然后提交并推送。若无法启动两个 fresh-context reviewer 或任一强制 gate 未通过，本票保持 `claimed`。

