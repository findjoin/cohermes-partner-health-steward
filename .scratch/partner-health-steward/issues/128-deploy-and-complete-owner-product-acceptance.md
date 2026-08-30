# 128 - 部署并完成主人产品验收

Type: task
Status: ready-for-agent
Parent: [健康管家首发 TO、CAN 与 HOW 决策闭合路线](../map.md)
Blocked by: [122 - 实现 DynamoDB current-head 生产 Provider](122-implement-dynamodb-current-head-provider.md), [124 - 接通 pinned Hermes 的真实健康入口](124-connect-pinned-hermes-live-health-entry.md), [125 - 实现 Partner 首跳模型与治理知识 Adapter](125-implement-partner-model-and-governed-knowledge-adapter.md), [126 - 实现真实 Weixin 与支持联系人投递 Adapter](126-implement-live-weixin-and-support-contact-delivery-adapter.md), [127 - 取得医学内容权利与专业审核](127-obtain-medical-content-rights-and-review.md)

**What to do:** 对一个新内容寻址 release 在用户的 default Hermes 上完成 Ticket 119 G10—G12 的真实 target binding、最小 canary、一次性 acceptance authorization、主人初始化和产品验收。明确禁止访问或部署女友的 partner Hermes。

## Fixed target and safety boundary

- 唯一目标：用户自己的 default `/root/.hermes` 与 `hermes-gateway.service`。partner `/root/.hermes-partner`、`hermes-gateway-partner.service` 及其他 profile/service 永久为 pre-write rejection。
- 每个真实 AWS、模型、微信、联系人、部署、删除、迁移和主人动作分别使用 Ticket 119 的 target/release/run/gate-bound opaque approval；批准不能跨 gate 借用。
- collector 不读取或返回凭据、完整配置、健康正文、联系人身份、运行数据库、模型 transcript 或可逆摘要；只保存无正文 opaque refs。

## Bounded acceptance

1. 对同一 release digest 重跑 G01—G09；任何非 passed 立即停止。
2. G10 验证 default 的 pinned artifact/dirty digest、required patch、Plugin discovery、唯一入口、CorePort service、peer/ACL、current-head、密钥/vault、capability profile、co-stop 和可回滚安装。
3. G11 仅用最小合成／脱敏内容验证真实 Partner 首跳模型和用户自己的 Weixin；interface accepted 不冒充 delivered/read，unknown 冻结同 run。
4. G12 先取得一次性 acceptance authorization，再由主人在微信中完成真实 `health-init`；Core 读回 initialization enabled、current head 和 writer fence 当前后，才显示“健康管家已初始化”。
5. 按冻结主人测试序列逐项验收：普通健康记录、画像／证据、健康问答、当地日复盘、任务、主人控制／权利、失败／unknown 状态、最低安全、危险升级、最小联系人警报／纠正和 active-path readback。
6. 主人明确确认“有用、清楚、可信”后，G12 才可 passed；拒绝、超时或无法确认保持 acceptance-authorized/staged，不自行激活。
7. 任一 post-check 失败按 release-bound backup 回滚 default，重新启动并确认普通 Hermes 可用；不得触碰 partner。

## Completion claim

只有 G01—G12 对同一 release/run 全部 passed、五项 G12 receipts 和 active-path readback 齐全，才可在 Ticket 119/128 记录“主人可用／产品验收通过”。这不等于已经证明长期稳定；上线后稳定性另以真实无正文运行证据观察，不在本票预设新的架构或功能。

## Delivery discipline

部署前冻结精确 release、target、run、回滚点和测试序列。实施完成后提交无正文证据、更新 Ticket/Map、普通 push；不得把批准、秘密或主人资料写入 Git。
