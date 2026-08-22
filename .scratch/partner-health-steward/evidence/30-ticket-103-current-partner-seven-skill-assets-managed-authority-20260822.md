# Ticket 103 当前 Partner、七个健康 Skill 资产与受管权威底座核验（2026-08-22）

## Answer

本 Evidence 只核验仓库快照、现行产品合同和已链接的历史 Evidence；没有读取或上传真实健康资料、聊天正文、联系人、密钥、Token、服务器配置值、运行数据库、日志或备份，没有安装、启停、修改或部署正式 Partner，也没有进行真实健康实验。仓库 `HEAD` 与 `origin/main` 均为 `a9d55445be7692b5a4a12d0db9e4f624efd50bb9`；这证明当前快照可定位，不证明正式 Partner 正在运行相同内容。

### 证据边界

- **当前仓库静态事实（已证明）**：[`HANDOFF_START_HERE.md`](../../../HANDOFF_START_HERE.md) 明确 `ops/partner-health-steward` 是历史实现和审计输入，不是当前 HOW 或部署证明。仓库有三个候选 Plugin manifest，只有一份候选运行文档 [`health-steward/SKILL.md`](../../../ops/partner-health-steward/skill/health-steward/SKILL.md) 及其医疗参考文件；Windows 工作树换行差异不能被当作运行版本证明。
- **固定源码事实（有界可继承）**：[Evidence 19](19-current-partner-hermes-baseline-plugin-lifecycle-trust-20260820.md) 的 Hermes `v0.20.0`/commit `3c27eb…` 只证明普通 Plugin 的 allow-list、`register(ctx)` 和有限扩展面；没有统一 `unregister`、`teardown`、状态迁移或跨对象提交合同，加载、注册、Hook/Middleware 异常默认可继续（67-101 行）。[Evidence 29](29-hermes-seven-health-skill-context-loading-and-token-efficiency-20260821.md)只证明该固定源码下的 Skill 索引、`skills_list`/`skill_view`、slash 全文加载、Plugin Skill 的 `plugin:name` 命名空间、描述截断和无可确认 `auto_skill`（39-57 行）。这些都不能证明 2026-08-22 当前 Partner 的安装、发现、选择、使用或结果提交。
- **历史现场（需要重新核验）**：Evidence 19 的 2026-08-20 现场曾记录 Partner ordinary/user/project Plugin enabled 为 0、profile 没有 manifest、文件树有 80 个 `SKILL.md` 而管理视图有 7 个 local-enabled 项，并同时配置 Telegram 与 Weixin（44-65 行）。这些日期和现场值不升级为 2026-08-22 当前事实。
- **产品权威（已证明）**：[`CONTEXT.md`](../../../CONTEXT.md)和[Ticket 100 Answer](../issues/100-define-seven-health-skill-interaction-entry-document-and-capability-boundaries.md)固定七个规范名及 A/B 角色；`CONTEXT.md` 同时固定旧 `medical` 不属于现行七项、不是别名、并行入口或回退。产品决定已经成立，不等于物理隔离或运行时不发现已成立。

### 当前静态资产指纹

下表指纹来自仓库 [`SHA256SUMS.txt`](../../../SHA256SUMS.txt) 的 LF 快照内容；它们只标识本仓库历史候选，不能外推正式 Partner 的运行资产。

| 候选资产 | 声明版本 | SHA-256 |
|---|---:|---|
| `plugin/health-autonomy/plugin.yaml` | `0.2.0` | `873bf3d0fd8bceb4aa98d938b5955fa11fb26f845b86b5097e80113ae17d71f8` |
| `plugin/health-guard/plugin.yaml` | `0.1.0` | `5318a497c5f0da1927efa69c69ef8027c6aa7328e692e8e3eed605fd69acf80b` |
| `plugin/health-steward/plugin.yaml` | `1.0.0` | `30ca80e30f05daa154be79d6a004d389087551eb83b478e5d6cc6bebc95c58a7` |
| `skill/health-steward/SKILL.md` | 文本称 `v0.2` | `bd3a73e3a9d334877ad3d02a66616debd6ab324a2e8b0c67965baee4de9d2179` |
| `skill/health-steward/references/medical-safety-sources.md` | 无独立版本 | `a25f84bd9eb14f642a0d11c7ba6c5a71ecc4612ec1da97bf85a64ba501d09151` |

### K01：当前 Partner、Plugin 生命周期与信任根

仓库可以证明候选 manifest、候选注册代码和可复现的静态文件版本；不能证明任何候选已被目标 Partner profile 允许、加载、注册、持续运行或与当前进程同生共停。候选 `health-autonomy` 和 `health-steward` 的 `partner` 条件、Hook/Tool/Platform 注册只是源码表面，不是现场加载证据。Evidence 19 的“普通 Plugin 异常继续、部分注册不回滚”是固定版本的负向约束，不能被包装成健康 fail-closed。

因此 K01 分类为：**已证明**（仓库候选和固定 Hermes 扩展表面）；**需要重新核验**（当前 Partner 版本/提交、profile allow-list、实际加载、权限、可信前提、停用和恢复）；**尚未实现或尚未证明**（正式健康 Plugin 的生命周期闭包、可信根观测和失败关闭）。这些结论覆盖 Ticket 102 的 T01、T02、T34-T36 前置事实，但不选择 HOW。

### K02：七个 Skill 资产、发现、加载、版本与旧入口隔离

现行七项名单与角色如下；“产品规范”不等于“仓库已有运行资产”：

| 规范名 | 现行角色 | 仓库运行 `SKILL.md` | 当前状态结论 |
|---|---|---|---|
| `health-init` | A，可明确请求初始化 | 不存在 | 尚未证明已安装、发现、加载、真实使用或形成初始化提交 |
| `health-steward` | A，初始化后统一协调 | 只有历史候选 `ops/.../skill/health-steward/SKILL.md` | 只能证明历史候选存在；当前 Partner 绑定版本、加载和真实使用未证明 |
| `health-settings` | A，可明确请求设置 | 不存在 | 尚未证明运行资产或真实使用 |
| `health-portrait` | B，仅由 steward 按需采用 | 不存在 | 尚未证明运行资产、按需选择或候选回传 |
| `health-evidence` | B，仅由 steward 按需采用 | 不存在 | 尚未证明运行资产、证据候选或权威提交 |
| `health-owner-inquiry` | B，仅针对一个必要缺口 | 不存在 | 尚未证明运行资产、最小补问或使用披露 |
| `health-literature` | B，仅针对允许的知识缺口 | 不存在 | 尚未证明运行资产、来源边界或合格资料回传 |

固定产品边界要求 A/B 区分、职责不直接写入或回复、实际使用与业务提交分层、使用事实由系统证明；固定 Hermes 源码只能证明可能的索引和全文加载路径，不能证明自然语言一定选择正确 Skill，也不能证明 Plugin Skill 自动进入平面索引（Evidence 29:39-57）。当前快照没有七份同代际主文档、共享规则绑定、动态最小上下文绑定、实际使用记录或提交/披露/交付证据。

旧 `medical` 的**现行产品地位已证明退出**；其物理删除、隔离、不可发现、不可作故障回退仍为**需要重新核验**。仓库保留 `medical-safety-sources.md` 和历史 Evidence 只能说明审计材料存在，不能证明旧入口仍有效或已经物理清除。

K02 的结论覆盖 T03-T14、T24、T31、T35、T36；其中产品名单与交互角色已证明，运行能力、同版本绑定和失败关闭尚未证明。

### K05：单一受管状态、保护、提交与结果事实底座

[Evidence 22](22-managed-health-state-plane-protection-and-single-authority-20260820.md)只证明 Python/SQLite、`cryptography`、systemd 等一般原语，以及旧 sidecar 的局部候选校验、单文件替换、tombstone 和清理构件；它同时明确没有已部署、可定位的健康状态平面，旧候选对象模型不匹配当前六域画像、三类证据、四标签任务、批准、诊断修订和联系人合同，跨对象提交、恢复、单一当前权威和完整副本闭包未证明（5-17、145-154 行）。

普通 Session、FTS、Memory、日志、cache、Cron、备份、模型服务或站外快照是否含健康正文及能否删除仍是未知；本轮按边界不读取其内容（Evidence 22:201-207）。因此当前不能宣称存在统一对象清单、唯一引用、候选/最终隔离、完整提交、崩溃恢复，或“未提交／处理结果无法确认／已提交但披露或交付未知”的可判定恢复。

K05 分类为：**已证明**（平台有一般原语、历史候选有局部构件和明确反例）；**需要重新核验**（当前正式 Partner 的全部状态面、版本绑定、普通历史边界、提交/恢复和副本闭包）；**尚未实现或尚未证明**（当前六域及相关对象的单一受管权威底座）。这覆盖 T01、T03、T04、T07、T14-T19、T21、T23、T24、T27、T29、T31-T36 的底座前置，但不把未实现误写成平台不可行。

### K20/K21 前置与未来验证义务

K20 服务 T04、T24、T35、T36；其所需的“文档、七 Skill、画像、证据、任务、批准、控制、诊断、安全、未知、联系人、历史的完整迁移”没有当前资产清单或同代际闭包证明。K21 服务 T01、T14、T36；其所需的版本绑定、真实使用、提交、披露、删除、防复活和未来真实验收可观察性也没有运行证据。未来必须在不接触真实健康资料的批准隔离实验中，分别证明资产指纹与运行版本绑定、缺失/冲突/部分加载的停止结果、每个 Skill 的真实使用事实、跨对象提交和崩溃恢复、删除后不复活，以及主人可观察的三态结果。这里只记录义务，不选择实现方式或执行实验。

### 总结分类

- **已证明**：现行七名及 A/B 产品词汇；仓库中三个历史 manifest、一份历史 Skill 和参考文件；固定 Hermes 版本的有限 Skill/Plugin 机制；普通基座不是天然健康 fail-closed。
- **需要重新核验**：2026-08-22 正式 Partner 版本、profile 资产、七 Skill 的安装/发现/加载/使用/版本绑定、旧 `medical` 物理隔离、可信前提、Plugin 私有状态、普通状态面与提交恢复。
- **已经失效为当前权威**：`ops/` 候选实现、2026-08-20 现场快照的当前性、旧完整 CAN/HOW 以及旧 `medical` 入口假设。
- **尚未实现或尚未证明**：七个规范 Skill 的完整运行资产、A/B 运行区分、必经真实使用、系统披露、统一受管权威、失败关闭、迁移和真实验收。
