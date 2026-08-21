# 【CAN】重建七个健康 Skill 交互合同后的完整能力链与追溯关系

Type: task
Status: ready-for-agent
Parent: [健康管家首发 TO、CAN 与 HOW 决策闭合路线](../map.md)
Blocked by: [【TO】确定七个健康 Skill 的主人交互入口、文档结构与能力边界](100-define-seven-health-skill-interaction-entry-document-and-capability-boundaries.md)

## Question

[【TO】确定健康 Skill 的必经使用、主人可见披露与回复结果](99-define-required-health-skill-use-visible-disclosure-and-reply-contract.md)、[【TO】确定七个健康 Skill 的主人交互入口、文档结构与能力边界](100-define-seven-health-skill-interaction-entry-document-and-capability-boundaries.md)与[【TO】确定危险升级时主人提示、预设支持联系人通知、记录与失败结果](101-define-danger-escalation-owner-prompt-and-support-contact-alert-contract.md)已实质改变现行完整 TO 的 Skill 必经使用与披露、七项交互合同、两级路由、最低安全例外、支持联系人接收方和失败结果，因此旧 C01—C17、CAN 闭合与统一 HOW 不能继续整体冒充当前权威。本票须针对**完整最新 TO**重建或重审技术能力链和双向追溯，不只为新增功能补一个发送接口。

至少完成：

1. 遍历当前全部 TO 的目标、主人结果、边界、不变量、失败结果和首发成功条件，尤其逐项纳入上述 Skill 必经使用、七项交互和危险支持联系人三项后继 TO；把每个 TO 节点映射到可调查的能力节点、链内依赖和所需证明事实，并从能力节点反向链接到 TO。
2. 逐项重审旧 C01—C17、全部现行 CAN Evidence 与[【HOW】选择健康管家的统一技术路线、权威职责与分层验证架构](98-choose-unified-health-steward-technical-route-and-authority-architecture.md)，分别标明“可继承、需要重查、已经失效”，不得按票号或旧 resolved 状态默认继承。
3. 显式覆盖七个健康 Skill 的发现、明确与自然入口、确定性加载、版本绑定、目的最小上下文取得与注入、零／一／多职责组合、真实使用披露、普通健康结果失败关闭，以及最低安全结果例外；同时覆盖初始化对预置联系人／联系方法／自动警报的实际披露与批准、资料范围和首跳边界变化后的重新说明／同意，以及时区切换从下一有效当地自然日继续且不补做旧复盘的能力。
4. 显式覆盖唯一消息准入后的粗分流、`health-steward` 完整路由、非 Skill 安全最终裁决和 steward 不可用时的最低安全兜底；验证它们不会回退旧 `medical`、不会让职责 Skill 越权，也不会把普通 Hermes 或模型自述冒充受管健康结果。
5. 显式覆盖单一支持联系人、初始化披露与主人批准、最小警报／必要纠正、发送与到达分层、失败／未知／有限重试冻结、独立控制、停止记录、永久删除和旧状态防复活所需能力。
6. 显式覆盖六域主题视图、三类证据卡与四类关系、待澄清候选、近期五张明细、受保护例外、滚动历史摘要、画像与证据的候选回传／权威提交，以及任务三类候选来源、统一建档门槛、任务框架权威和自动事件上下文。
7. 为已经能够准确表述且共享连贯技术表面和证据链的能力节点，创建并接线最少的后继 CAN 调查 Tickets；尚不能准确形成调查问题的 fog 留在 Map 的 `Not yet specified`。本票不执行调查实验、不选择组件组合或 HOW，也不预建 CAN 闭合或 HOW 修订票。

完成条件：完整最新 TO 的每一项均有双向 CAN 追溯；旧能力事实与 HOW 逐项完成继承／重查／失效分类；后继调查票、直接依赖和当前 Frontier 均准确；尚未能出票的 fog 清楚；本票形成唯一 `## Answer`，且不选择技术路线。
