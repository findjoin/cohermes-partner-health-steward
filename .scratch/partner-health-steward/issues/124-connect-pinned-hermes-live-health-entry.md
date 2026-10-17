# 124 - 接通 pinned Hermes 的真实健康入口

Type: task
Status: claimed
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

## 2026-10-18 pre-code checkpoint candidate

唯一设计 `../design/124-live-entry-design.md`；独立验证合同 `../design/124-frozen-verification-contract.md` 与 verifier-owned `../../../tests/test_ticket124_live_entry.py`。基线19417da保留111/112已验证业务与123生产装配；124公开Module缺失使新门4个预期failure、0error/skip。正式运行要求可核验pinned Git来源、root和Python3.11 runtime，尚未以本机替代环境冒充通过。产品实现等待同一commit/tree新鲜双轴预审；真实模型、微信、部署另按既有后继门执行。

## Frozen implementation authority (2026-10-18)

- reviewed pre-code commit: `fe9c058fcf634ebe624f98c1c72adde90a86032a`; tree: `858f0cd397853138c226f35a968d1deef014dd28`.
- Fresh-context Spec: PASS；Fresh-context Standards: PASS；证据 `../evidence/40-ticket124-129-precode-review-20261018.md`。
- `.scratch/partner-health-steward/design/124-live-entry-design.md` blob: `ed27c319dbb57e974ca7df193c74df708689e399`.
- `.scratch/partner-health-steward/design/124-frozen-verification-contract.md` blob: `dfa4d0a283f4703ff5ee47262c345febe8f5e36d`.
- `tests/test_ticket124_live_entry.py` blob: `34ea7c8d8797e8b77df9a9ab5109a6ba309c0a7f`.
- 允许严格按上述冻结设计实施；产品实施者不得修改冻结三件套或自行闭票。真实部署/外部效果仍按后继既有门，未被本次预审冒充通过。

## Updated frozen implementation authority (published registry, 2026-10-18)

本节替代本票此前三件套blob；前次无关Core装配仍有效，129权威不变。

- reviewed commit `13d18a18754ed2a39a50e30d3f56358ed30409cf`; tree `9da5b6330b852f7e8ad884cfeaaaed47c5480695`；fresh Spec/Standards均PASS，见Evidence41。
- `.scratch/partner-health-steward/design/124-live-entry-design.md` blob `e26f4212f74b6c1fdd737e77af39137a429bfc44`。
- `.scratch/partner-health-steward/design/124-frozen-verification-contract.md` blob `fc563931fe822ca3cc1b4cd15a9f4dc6e81b9e1a`。
- `tests/test_ticket124_live_entry.py` blob `6d8578bc79597eb7a5114186938c574efc7073cb`。
- 允许最小实现既有process activation的真实registry选择、Publisher自身代码闭包与初始化前明确ordinary路由；不修改冻结门，不接真实服务，不自行闭票。

## Updated frozen implementation authority (advanced replay, 2026-10-18)

本节替代124此前三件套blob；产品和112既有隐私释放语义不变。

- reviewed commit `78bfe92b3be3286f338969315ef8e44def54daf6`; tree `9af993bef6defdb9493c5ac8991b7f7dc0eea733`；fresh Spec/Standards均PASS，见 [Evidence43](../evidence/43-ticket124-redacted-replay-verifier-correction-20261018.md)。
- `.scratch/partner-health-steward/design/124-live-entry-design.md` blob `b70c45df606c2379b361ba31377abadecd3d6357`。
- `.scratch/partner-health-steward/design/124-frozen-verification-contract.md` blob `6dc8430cb2c79436984be539e8ed84a27e696aad`。
- `tests/test_ticket124_live_entry.py` blob `8253c76fd0d8e1edbe943c4250d31b17c0bdcb3c`。
- V04等待 Core receipt advanced 后验证 accepted/redacted、无正文、原终态/record/transition/generation保持、无新bridge及unknown attempt仍一次；不得重建已释放回复。其余冻结验收保持，必须重跑执行门后才能实施后审查。
