# 124 - 接通 pinned Hermes 的真实健康入口

Type: task
Status: ready-for-agent
Parent: [健康管家首发 TO、CAN 与 HOW 决策闭合路线](../map.md)
Blocked by: [123 - 实现生产 health-core 与 CorePort 服务](123-implement-production-health-core-and-coreport-service.md)
Unblocks: [126 - 实现真实 Weixin 与支持联系人投递 Adapter](126-implement-live-weixin-and-support-contact-delivery-adapter.md), [128 - 部署并完成主人产品验收](128-deploy-and-complete-owner-product-acceptance.md)

**What to build:** 在固定 Hermes commit 上完成 `health_weixin` Platform Adapter 的真实消息生命周期：逐条来源在正文物化前通过唯一准入，调用已有 `HealthPlugin.receive_weixin`，发送 core 已提交的唯一回复，回交 native cursor 终态，并把 Cron／启动恢复只作为 core 唤醒。

## Bounded acceptance

- 应用 Ticket 118 hash-bound required patch，原生 `weixin`/旧 medical/health 路径在健康入口前不可选择；Plugin 是唯一 `health_weixin` 注册者。
- Adapter 实现 pinned Hermes 实际要求的 connect、receive/poll、reply/send、cursor 与 disconnect 行为；来源、消息 ID、重投和 causal identity 不被合批或普通 Memory 改写。
- 初始化前仅明确 `health-init` 能进入；普通聊天继续走普通 Hermes，不能由 LLM 自然语言假装健康命令已成功。
- 七个发布 Skill 由 `health-steward` 按既有职责调用并形成真实 use proof；Skill 文本、加载成功或模型自述不等于使用。
- Cron、重连和服务重启只唤醒当前 Core；同一当地日、同一来源和 unknown 效果不得产生第二业务结果。
- pinned artifact 的 Plugin discovery、无旁路、co-stop、升级重新验证和 deny-network 渠道 canary 通过 Ticket 119 G05/G09；此票不调用真实微信。

## Not in this ticket

不实现模型或真实投递 Transport，不更换 Hermes，不把七 Skill 变成七个 Plugin，不读取普通历史来倒填健康资料。

## Delivery discipline

编码前以 pinned Hermes 实际接口做 characterization 并冻结最小 Adapter 设计；若 pinned 接口缺少必需语义，以精确接口证据停止，不在健康项目中重写 Hermes。通过后普通提交并推送，不激活 default。
