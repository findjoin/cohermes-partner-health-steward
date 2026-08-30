# 127 - 取得医学内容权利与专业审核

Type: task
Status: ready-for-human
Parent: [健康管家首发 TO、CAN 与 HOW 决策闭合路线](../map.md)
Blocked by: [125 - 实现 Partner 首跳模型与治理知识 Adapter](125-implement-partner-model-and-governed-knowledge-adapter.md)
Unblocks: [128 - 部署并完成主人产品验收](128-deploy-and-complete-owner-product-acceptance.md)

**What to establish:** 对当前 release digest 使用的 MinimumHelpBundle、治理知识、危险规则和窄 BMI 中文诊断 bundle，取得可验证的内容使用权、版本／有效期、相称医学专业审核与安全审核，并把无正文 attestation 绑定到精确文件 hash。

## Bounded acceptance

- 每个来源记录发布者、标题、版本／日期、用途、许可或使用权依据、中文状态、撤回／过期条件和精确内容 hash；不得把“公开可访问”自动解释为可用于产品。
- 具备相称资质的医学审核者对精确中文 bundle、适用成人范围、最低输入、危险优先级、限制、就医提示和 BMI 确定性重算签发 attestation；修改任一字节即失效。
- 安全审核确认 MinimumHelp 在模型、知识或诊断不可用时仍可独立工作，且不会建议自行调整处方药或冒充正式确诊。
- 机械验证只把同一 digest 推进到 `activation-ready`；不得写 active、主人已接受或生产稳定。
- 许可缺失、审核者不匹配、hash／版本漂移、撤回或过期均保持 staged，并阻断 Ticket 128。

## Human authority boundary

Agent 可以整理候选来源、生成 hash、核对证据和执行验证，但不能代表权利人授予许可，也不能冒充医学专业审核者。需要主人选择合法来源并安排合格审核；真实姓名或证件不写仓库，仓库只保存最小 opaque attestation ref 和机械可验证元数据。

## Not in this ticket

不改变诊断范围、不增加第二病种、不实现代码、不调用真实模型／微信、不部署或激活。
