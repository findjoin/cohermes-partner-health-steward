# 【CAN】核验当前 Partner、七个健康 Skill 资产加载与受管权威底座

Type: research
Status: resolved
Parent: [健康管家首发 TO、CAN 与 HOW 决策闭合路线](../map.md)
Blocked by: [【CAN】重建七个健康 Skill 交互合同后的完整能力链与追溯关系](102-rebuild-complete-capability-chain-after-seven-health-skill-interaction-contract.md)

## Question

本票服务完整最新 TO 中 T01—T04 的 Partner Plugin 载体、可信基线、初始化隔离与持续启用，T05—T15 的七项 Skill 名单、A/B 角色、必经真实使用、文档分层、版本、披露与权威提交，T16—T18、T21、T23—T24、T27、T29、T31—T35 的单一受管状态、失败／未知、删除和迁移底座，以及 T36 的未来真实验收可观察性；对应能力节点 K01、K02、K05，并核验 K20、K21 的资产与权威状态前提。

针对当前目标 Partner 的脱敏版本与资产指纹、Plugin/Skill 注册和生命周期表面、普通 Skill 与 Plugin Skill、自然选择、明确入口、`skill_view`、支持文件／共享权威引用、旧 `medical` 资产，以及 Plugin 私有状态、候选／最终隔离、提交／恢复、日志与普通 Session/Memory 边界，核验：

1. 七个规范名能否被完整枚举且唯一，A 类可发现与 B 类仅按需采用能否区分，旧 `medical` 是否能被证明不再作为现行入口、别名或故障回退。
2. 被发现、主文档加载、共享规则加载、取得动态最小上下文、实际使用、业务提交、使用事实与回复交付能否分别证明；名称、文档、共享规则和加载结果能否绑定同一可核验版本。
3. 必需资产缺失、版本冲突、部分加载、Plugin 停止或可信前提无法确认时能否失败关闭；安装、进程存活、模型自述或文档存在均不得冒充实际使用或健康业务成立。
4. 六域画像、三类证据、任务、批准、控制、诊断、安全、联系人、未知、交付与历史能否拥有统一对象清单、唯一引用、候选／最终隔离和完整提交底座；动态主人状态不得进入 Skill 文档、普通长期上下文、通用 Memory、普通日志或明文第二真相。
5. 崩溃或提交结果不明时能否区分“未提交”“处理结果无法确认”和“已提交但披露／交付未知”，并为删除、防复活、迁移和未来分层验收留下可调查的权威边界。

[当前 Partner Hermes 基线、Plugin 生命周期与可信执行边界](../evidence/19-current-partner-hermes-baseline-plugin-lifecycle-trust-20260820.md)、[受管健康状态数据平面、保护隔离与单一权威能力核验](../evidence/22-managed-health-state-plane-protection-and-single-authority-20260820.md)与[Hermes 七个健康 Skill 的文档分层、加载与 token 成本核验](../evidence/29-hermes-seven-health-skill-context-loading-and-token-efficiency-20260821.md)只作其原日期、版本、源码和现场边界内的历史输入；须重新区分官方保证、固定源码、2026-08-22 当前脱敏资产事实、未部署候选和获准的非真实健康实验。不得读取健康正文、聊天正文、真实联系人、密钥、Token、运行数据库或服务器配置值，不得安装、启停或修改正式 Partner；`ops/` 仅作历史审计输入。

解决条件是在同一份带引用 Evidence 中，对 K01、K02、K05 及七个 Skill 逐项列出已证明能力、确定限制、未知、版本适用范围、对 TO 的覆盖和未来验证义务，并明确旧 `medical` 与普通状态面的当前边界。当前未部署不等于平台不可行。本票不选择普通／Plugin Skill、入口、加载器、文件布局、数据库、事务、密码学、上下文注入或其他 HOW。

## Answer

已完成 Ticket 103 的受限核验，详细证据见[Ticket 103 当前 Partner、七个健康 Skill 资产与受管权威底座核验（2026-08-22）](../evidence/30-ticket-103-current-partner-seven-skill-assets-managed-authority-20260822.md)。

- **K01**：仓库可定位三个历史候选 Plugin manifest、候选注册代码和静态指纹；固定 Hermes `v0.20.0` 的普通 Plugin 扩展面及非 fail-closed 失败语义可有界继承。2026-08-22 正式 Partner 的版本、profile allow-list、实际加载、持续启用、可信前提和生命周期闭包仍需重新核验。
- **K02**：产品权威固定七个规范名和 A/B 角色；仓库只有历史 `health-steward` Skill，没有另外六份运行 `SKILL.md`。七项安装、发现、全文/共享规则加载、动态最小上下文、版本绑定、实际使用、业务提交、披露和交付均未被当前快照证明。旧 `medical` 已退出产品入口/别名/回退，但物理隔离仍需重新核验。
- **K05**：没有已部署且可定位的当前健康状态平面或统一跨对象提交/恢复/单一当前权威证明；普通 Session/Memory/日志/备份边界保持未知，未读取其内容。历史 sidecar 和底层原语只是审计输入，不是当前路线。
- **K20/K21**：完整迁移闭包、真实使用/提交事实、删除防复活和未来验收可观察性均是后续验证义务。未实现不等于平台不可行，本票没有选择 HOW。

结论分类为：仓库静态候选和固定版本源码事实已证明；历史现场和随当前 Partner 变化的能力需要重新核验；`ops/` 候选、旧现场当前性、旧完整 CAN/HOW 与 `medical` 入口假设不再是当前权威；七 Skill 完整运行资产、统一受管权威和失败关闭尚未实现或尚未证明。当前仍处于 **CAN**，本票不进入 HOW、实现、部署或验收。
