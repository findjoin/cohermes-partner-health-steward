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

