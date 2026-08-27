# 118 - 完成 Hermes/Weixin 宿主合同发布与回滚准备

Type: task
Status: ready-for-agent
Parent: [健康管家首发 TO、CAN 与 HOW 决策闭合路线](../map.md)
Blocked by: [110 - 建立 Plugin/core 受信边界与合成验证骨架](110-establish-plugin-core-trust-boundary-and-synthetic-harness.md), [111 - 实现唯一准入与主人初始化](111-implement-unique-admission-and-owner-initialization.md), [112 - 实现七 Skill 协调与日常证据画像处理](112-implement-seven-skill-coordination-and-daily-evidence-portrait-turn.md), [113 - 实现 StrictHealthLLM 治理知识与非诊断回答](113-implement-strict-health-llm-governed-knowledge-and-nondiagnostic-answer.md), [114 - 实现主人设置数据权利与业务状态](114-implement-owner-settings-data-rights-and-business-status.md), [115 - 实现任务当地日复盘与分层主人投递](115-implement-tasks-local-day-review-and-layered-owner-delivery.md), [116 - 实现安全诊断门禁与支持联系人链](116-implement-safety-diagnostic-gates-and-support-contact-chain.md), [117 - 实现终止删除防复活与 writer-fence 迁移](117-implement-terminal-deletion-nonresurrection-and-writer-fence-migration.md)

**What to build:** 把已实现的 Plugin/core 行为接到获准的 Partner Hermes/Weixin 宿主合同，并形成可重复的发布、升级重核验和回滚准备。历史 `ops/` 只提供行为反例和测试思路，不直接成为当前部署实现。

**Blocked by:** 110 - 117 全部完成

- [ ] 锁定并可验证 Plugin、core、七 Skill bundle、适配器、模型接口、知识/安全/诊断 release 和迁移 manifest 的版本摘要。
- [ ] 宿主合同验证 Plugin 生命周期、唯一入口、原生路径前 envelope、无旁路、受限 Unix socket、适配器完整终态回交和异常时健康失败关闭。
- [ ] 旧 `medical`、历史多 Plugin split、普通 Session/Memory 写入和通用状态 RPC 不会被当前 release 重新启用。
- [ ] 建立不含真实健康资料、密钥或 Token 的部署前检查、升级重核验、回滚和旧 fence 停止清单。
- [ ] 只在获准的合成环境执行宿主合同和故障测试；任何当前 Partner 运行绑定、真实资源或服务配置未知都保留为待核验，不写入仓库。

## Implementation contract

### Start gate and authority to load

只在 Ticket 110—117 全部 `resolved` 后开始。实现前必须读取：

- [ADR 0022](../../../docs/adr/0022-select-current-health-steward-route-after-seven-skill-can-closure.md)中的 topology、stable boundaries 和 validation；
- [当前实现 Spec](../spec.md)的“产品和权限边界”“版本、发布和历史代码边界”“宿主合同”“分层验收”；
- [当前 HOW 证据](../evidence/36-how-route-after-current-can-closure-20260822.md)的 selected topology、validation boundary 及固定 Hermes v0.20.0/commit `3c27eb6234bf91b8ceee9e9071591b31e9b148cb` 来源边界；
- Ticket 110—117 的最终 `## Answer`、公开协议、版本和 manifest，以已验收实现而不是历史 `ops/` 路径为准。

任一 blocker 未闭合时只能做只读 inventory；不得 claim、生成“最终”release、连接当前 Partner 或将未知宿主事实写成已验证配置。

### Scope and ownership

本票完整拥有：

1. 当前 Plugin/core/七 Skill/adapter/model/capability-profile/knowledge/safety/diagnostic/migration 产物的可重现 release manifest 与摘要；
2. 固定 Hermes artifact 上的 Plugin 生命周期、唯一 pre-native `health_weixin` 入口、受限 Unix socket、完整终态回交和失败关闭宿主合同；
3. 部署前、升级重核验、回滚准备和旧 fence 停止的无凭据检查包。

本票不部署到真实 Partner、不读取或写入真实服务器配置、不登录微信、不调用真实模型、不接受医学/许可审批，也不执行真实回滚。历史 `ops/` 只可用于提取反例，不能成为 release 输入或生产路径。

release 只绑定 Ticket 117 migration 协议、schema、builder、semantic-registry 版本和 synthetic fixture hash；包含实例语义状态、资源身份或 current-head 值的 migration manifest 是加密受管运行对象，不进入 Git 或可重现 release digest。目标 Partner 的实际 artifact/version/dirty patch、Plugin 绑定和服务配置留给 Ticket 119 的 target-binding gate。

优先把宿主边界放入聚焦模块，例如 `host_contract.py`、`release.py`，并把验证入口放入 `tools/` 下单一可重复脚本；manifest/schema/fixtures 放在当前 release 自有目录。不得把开发机绝对路径、密钥、Token、联系人或真实健康资料写入产物。

### Required semantic contracts

- release manifest 至少绑定 Hermes artifact、required patch、disabled-native-entry assertion、Plugin/core、七 Skill bundle、health_weixin adapter、三类深接口、schema、模型 interface、capability-profile schema/builder/validator、MinimumHelpBundle、知识/危险规则/诊断 bundle、migration protocol/schema/builder/registry、Python/依赖约束、服务身份/ACL 需求和每项版本/内容 hash；不绑定实例 migration manifest 或真实 Partner profile 值。
- manifest 区分“仓库内已验证产物”“需要目标 Partner 重新核验的绑定”“外部权利/审核/批准”“禁止进入仓库的秘密”，不能把后两类填成默认通过。
- host contract 至少有一组测试把实际 Plugin/Adapter 加载到 pinned Hermes commit 的真实 lifecycle/registration interface；健康入口在原生去重/合批/cursor 前取得 envelope，native/ordinary path、旧 `medical`、其他平台、普通 Agent/Tool/Command 无法到达 health core。手写 stub/fixture 只用于负向故障注入，不能单独满足宿主通过。
- pinned source/fixture 记录 upstream commit、allowlisted 相对路径、每个原始文件 SHA-256、required patch hash、提取器版本和生成后 hash，并提供离线重复 verify；来源或提取器变化使宿主证据失效。
- Plugin/core socket 合同绑定固定 framing、peer/service identity、权限范围、超时/截断/额外字段/重放处理和完整终态；core 单独运行不能发送或调用模型，Gateway/Plugin/core 任一不可信时健康路径共同失败关闭。
- adapter 只能执行 core 发出的受控 model/delivery intent，并把完整结果交回；adapter、Session、Memory、FTS、日志、observer 和通用 RPC 无健康写权。
- 升级必须重新验证 artifact、manifest、schema、Skill/adapter/model/bundle hash、ACL、current head 和旧入口禁用；不兼容升级保持 offline/cannot-confirm。
- 回滚只允许回到仍满足 semantic manifest、current generation 和 writer fence 的版本。代码回退不能恢复旧数据、旧批准、旧入口或旧 fence；无法证明时保持关闭。
- 所有部署前/回滚清单只保存无内容事实和需要由操作者在目标环境核验的项目，不保存真实值或凭据。

### Acceptance matrix

| ID | Required observable result | Forbidden substitute | Required test evidence |
|---|---|---|---|
| 118-A1 | 同一源码和声明环境重复生成相同 release manifest/hash，required patch/native-disable/capability-profile builder/MinimumHelpBundle/migration schema 等任一受管产物变化都会使摘要变化，实例 manifest/真实 profile 不影响 release digest | 手写版本号、目录存在、安装成功、部分文件 hash 或主人/目标 profile 状态混入 release | deterministic build、单文件/依赖/Skill/bundle/patch/assertion/profile schema-builder-validator/MinimumHelpBundle/schema drift、实例 manifest/真实 profile 隔离、缺项和 secret/path scan 测试 |
| 118-A2 | 实际 Plugin/Adapter 在来源可复现的 pinned Hermes checkout/package 上通过 lifecycle、registration 与唯一 pre-native entry 合同 | 手写 fixture、当前桌面 checkout、历史 `ops/`、普通 Hook/Skill 加载冒充宿主合同 | upstream file/hash/extractor 离线 verify、actual load/register/start/stop、partial registration、callback failure、native fallback 和入口顺序测试 |
| 118-A3 | Unix socket/peer/framing/权限/终态合同严格，Gateway/Plugin/core 任一故障使健康路径关闭 | core 单独可外发、普通 RPC、进程存活或连接成功冒充业务可用 | wrong peer、ACL、截断/额外字段、timeout、core/gateway co-stop 和 probe 不一致测试 |
| 118-A4 | adapter 只有受控 intent 执行权，完整 model/delivery 结果回 core；所有旁路写入被拒绝 | adapter/Session/Memory/observer 直接写状态或发送自由文本 | forged intent、旧 fence、结果缺项、普通状态 RPC、Session/Memory 写入和 observer 权限测试 |
| 118-A5 | 当前 release 以 hash-bound disabled-native-entry assertion 和实际 pinned host 加载证明旧 `medical`、历史多 Plugin split 和 native health fallback 未被声明/可达 | 仅在文档写“禁用”、手写 fixture 无旧入口、旧文件仍注册或故障时回退 | patch/assertion hash、manifest/registry/entrypoint 扫描、旧名字调用、Plugin 缺失/失败和 upgrade 回归测试 |
| 118-A6 | 部署前、升级和回滚检查在无秘密合成环境可重复运行，并真实区分 pass/fail/cannot-confirm | 把待核验目标配置写死、跳过未知、rollback=复制旧文件 | missing binding、schema drift、stale fence、rollback incompatibility、无凭据运行和报告测试 |
| 118-A7 | 所有真实 Partner/资源/服务事实保持外部待核验，仓库产物不含真实资料、凭据或配置值 | 合成 fixture 冒充当前 Partner 已验证 | secret/PII/config scan、manifest classification 和“unknown stays unknown”测试 |

`118-A1`—`118-A7` 是功能 verdict 和未来冻结门的追踪单位。验证使用能杀死独立现实错误的等价类，不把矩阵中的标点、字段或 artifact 组合展开成隐藏 Case registry，也不提前固定测试文件、fixture 或实现 slice。pinned fixture 必须满足来源复现规则，且永远不能升级成真实 Partner 证明。

### 编码前冻结与预审

以上范围、语义合同和验收矩阵是本票的冻结输入，不表示详细设计或测试门已经冻结。Ticket 117 闭合且本票被 claim 后，先由 characterization Agent 记录当前绿色行为、可复现差额、必须控制的现实故障和非目标；再由设计 Agent 形成一份唯一增量冻结设计，由独立 verification Agent 形成 verifier-owned 冻结测试门。

两份冻结产物必须绑定同一 commit/tree、预期红灯、既有绿灯和验证命令，并在生产实现修改前由 fresh-context Spec reviewer 与 Standards reviewer 对同一 checkpoint 预审通过。只有这时才能进入编码；现在不提前固定 pinned fixture、脚本路径或详细方案，避免上游实现变化使方案失效。

### 一致性实施、核验、停止与闭票

以通过编码前预审的冻结 checkpoint 为 `review_base`。编码 Agent 只可做使已封存红灯转绿所必需的最小实现修改，并保留既有绿色行为；不得修改冻结设计、冻结验证合同或 verifier-owned 测试，不得新增测试类别、产品功能或验收门。

若冻结门本身错误、冻结设计客观无法满足既有验收、需要新架构或外部决定/授权，立即停止并交回冻结阶段；不得由编码 Agent 边改门边实现。新功能必须另开 Ticket，不能扩入本票。

实现后重跑同一冻结门、受影响回归、本票单一 release/preflight 验证入口，以及 `python -m unittest discover -v -s tests -p "test_ticket118_*.py"`、`python -m unittest discover -v`、`python -m compileall -q partner_health_steward tests`、`git diff --check` 和冻结阶段确定的静态 secret/path 扫描，再形成 `reviewed_commit`/tree。fresh-context Spec reviewer 与 Standards reviewer 只核实实施是否符合冻结设计、冻结验收和证据真实性，不重新设计本票。finding 只有同时满足以下条件才阻塞：P0/P1/P2；有可重复命令或步骤；有可定位证据；明确指出被破坏的冻结验收 ID 或不变量。P3、理论可能、另一种合理偏好和新功能建议均不阻塞。

需要访问真实 Partner、真实服务、凭据、微信、模型、云资源或接受外部许可/审核时立即停止；固定 Hermes artifact 与所选 HOW 的必要宿主合同存在根本冲突时返回 CAN，不得静默 patch 成新路线。冻结设计或测试门变化必须返回编码前重新冻结和预审；最终 verdict 后的生产、配置、release 或迁移变化必须形成新 checkpoint 并重新核验。全部冻结验收通过且没有 blocker 后应停止继续扩写审查。

实施 Agent 记录 Gate 到实现位置、验证结果和 checkpoint identity；形成 `reviewed_commit` 前记录 `git status --porcelain=v1 --untracked-files=all`，不得遗留未提交或未跟踪的实现、冻结或证据文件。两轴均通过后只追加 `## Answer`、状态和 Map pointer，Answer 记录两轴可定位 verdict 及共同 base/commit/tree。确认相对 `reviewed_commit` 仅有闭票元数据后提交，并对当前分支执行普通 `git push`；推送被拒绝时停止，禁止 force push 或改写历史。

