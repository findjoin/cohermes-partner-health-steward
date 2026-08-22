# 113 - 实现 StrictHealthLLM 治理知识与非诊断回答

Type: task
Status: ready-for-agent
Parent: [健康管家首发 TO、CAN 与 HOW 决策闭合路线](../map.md)
Blocked by: [112 - 实现七 Skill 协调与日常证据画像处理](112-implement-seven-skill-coordination-and-daily-evidence-portrait-turn.md)

**What to build:** 让已初始化的健康 turn 通过严格锁定的同一 Partner 首跳模型和离线治理知识，形成有证据边界的非诊断回答。模型只能返回受管候选，core 校验当前证据/知识卡、来源、版本、支持/反对/未知和批准模板后确定性渲染；任何 fallback、截断或不完整终态都不能形成业务结果。

**Blocked by:** 112 - 实现七 Skill 协调与日常证据画像处理

- [ ] `StrictHealthLLM` 在最终 wire payload 上锁定 provider、canonical base URL、API mode、model、配置代际、主人同意指纹、容量 profile 和结构；路线变化先暂停并重新取得主人同意。
- [ ] 禁止跨首跳 fallback、路线外 Web Search/MCP/普通 Tool/任意 HTTP 和主人派生医学查询；`completed`、`incomplete`、`failed` 及原因必须可观察。
- [ ] `KnowledgePublisher` 只读取无主人数据并生成不可变 staged release，绑定来源、版本、许可、中文状态、适用范围、专业审核状态和 hash；过期/缺失返回知识缺口。
- [ ] 非诊断候选区分主人事实、通用知识、支持、反对、未知、限制和下一步；只允许引用当前有效证据/知识卡和批准 claim/template。
- [ ] 疾病排序、诊断标签、排除结论和个体化处方调整没有非诊断输出原子；模型失败、结构错误、容量不足或终态未知不写入、不发送。
- [ ] 合成测试覆盖 provider drift、fallback、工具旁路、截断、未知终态、旧卡引用和确定性渲染，不调用真实模型或上传真实健康资料。

