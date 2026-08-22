# 116 - 实现安全诊断门禁与支持联系人链

Type: task
Status: ready-for-agent
Parent: [健康管家首发 TO、CAN 与 HOW 决策闭合路线](../map.md)
Blocked by: [113 - 实现 StrictHealthLLM 治理知识与非诊断回答](113-implement-strict-health-llm-governed-knowledge-and-nondiagnostic-answer.md), [114 - 实现主人设置数据权利与业务状态](114-implement-owner-settings-data-rights-and-business-status.md), [115 - 实现任务当地日复盘与分层主人投递](115-implement-tasks-local-day-review-and-layered-owner-delivery.md)

**What to build:** 让健康管家在非诊断回答之外拥有独立、确定性的最低安全和 staged 诊断路径，并在可信危险且主人批准有效时向唯一支持联系人生成最小警报。安全不可用、危险未明和范围外必须失败关闭；联系人外发不能替代给主人固定的求助提示。

**Blocked by:** 113 - 实现 StrictHealthLLM 治理知识与非诊断回答; 114 - 实现主人设置数据权利与业务状态; 115 - 实现任务当地日复盘与分层主人投递

- [ ] 安全不可用、可信危险、危险未明、范围外和范围内按固定优先级产生 truthful 结果；最低安全结果不依赖 Skill、steward 或医学范围可用。
- [ ] 首发 BMI 诊断范围保持 staged，只有内容权利、冻结中文 bundle、医学专业审核、实现兼容、安全审查和真实主人验收全部通过后才可激活。
- [ ] 诊断执行模型前、模型后、提交前三段门禁，独立重算确定性 BMI；同一问题/事件/时期最多一个 current 判断，依据失效或主人纠正先退出 current 再形成修订。
- [ ] 初始化披露一个当前支持联系人、方法、目的和最小警报，联系人/方法变化使旧批准失效且不配置备用联系人。
- [ ] 最小警报只含主人可识别称呼、事件时间和固定求助语义；不含诊断、原消息、症状、位置、画像、证据或模型草稿。
- [ ] 停止新增记录期间仍可临时判断危险和产生最小警报，但不得新增健康事件或健康正文，只保留无正文防重复和投递未知事实。
- [ ] 合成测试覆盖危险未明、能力不可用、范围失效、批准撤回、纠正、未知联系人投递和不盲重试。

