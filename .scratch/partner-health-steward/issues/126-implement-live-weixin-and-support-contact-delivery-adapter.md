# 126 - 实现真实 Weixin 与支持联系人投递 Adapter

Type: task
Status: ready-for-agent
Parent: [健康管家首发 TO、CAN 与 HOW 决策闭合路线](../map.md)
Blocked by: [124 - 接通 pinned Hermes 的真实健康入口](124-connect-pinned-hermes-live-health-entry.md)
Unblocks: [128 - 部署并完成主人产品验收](128-deploy-and-complete-owner-product-acceptance.md)

**What to build:** 用 pinned Hermes/iLink 能力实现现有 `OwnerDeliveryWireAdapter` 的生产 Adapter，分别承接主人回复／主动投递和唯一支持联系人最小警报。Adapter 只执行 Core 形成并授权的 exact intent，并把实际观察到的终态逐层回交。

## Bounded acceptance

- 稳定幂等 identity 绑定 effect、intent digest、generation、writer fence、route generation 和接收方角色；旧批准、旧 route 或旧 fence 在网络调用前拒绝。
- formed、committed、attempted、interface accepted、delivered、read/action、correction、unknown 保持不同事实；平台无法证明的层级不得补写。
- 响应丢失、发送后本地提交失败、重启和重复唤醒进入 unknown 并冻结自动重试；只有现有主人决定／纠正规则可形成新的独立 intent。
- 联系人 Adapter 只允许当前唯一联系人和当前批准，payload 只含可识别称呼、事件时间及固定求助语义；不得包含诊断、原消息、症状、位置、画像或证据。
- deny-network fake 完成完整 ingress/reply/send/replay/restart 后，真实微信只在 G10 和 G11 的精确批准下用合成／脱敏消息验证；partner Hermes 不得被触碰。

## Not in this ticket

不改任务／outbox 状态机，不增加备用联系人，不把接口无错当作送达或已读，不执行主人产品验收。

## Delivery discipline

编码前冻结 pinned iLink 可观察终态与 unknown 矩阵。若渠道不提供 delivered/read 证明，合同保留 unavailable/unknown，不用轮询或猜测扩展架构。通过后普通提交并推送。
