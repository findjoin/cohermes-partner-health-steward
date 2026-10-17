# 126 - 实现真实 Weixin 与支持联系人投递 Adapter

Type: task
Status: claimed
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

## 2026-10-18 characterization input

124的committed-turn与initialization-disclosure bridge形状仅是请求发送授权。现有OwnerDeliveryWireAdapter只收Core已授权的payload_ref/digest/route/attempt/idempotency；Core的outbox binding现只承接复盘/task、lifecycle notice和owner decision，缺已finalized DailyTurnResult唯一回复及既有初始化disclosure challenge的binding。初始化披露发生在enabled前，现_current_owner_settings与claim_effect_execution均要求enabled，因此需要在本票明确冻结只绑定现存challenge的最小发送例外；不能伪造daily/task、先置enabled或承接任意caller文本。

现有public主人投递链可复用：prepare→issue→claim→execute重新核验→complete将观察终态写回原effect/outbox。CorePort旧claim/terminal没有完整prepare/authorize/complete映射，需同三类kind中的固定purpose桥接。联系人仍用现有唯一联系人/批准与最小contact_alert，平台只证明interface accepted不能扩写delivered/read。

Pinned低层_get_updates/_send_message各一次调用_api_post，可用于生产Transport；native高层仍有先持久化cursor、正文dedup/batch、retry/tokenless fallback，不得复用。初始化workflow及发送幂等identity还需绑定真实native事件而非可能变化的batch cursor；不把124离线bridge输入当发送权。下游详细冻结等待124现行接口与实际发布门闭合。

## 2026-10-18 pre-code candidate

124/125/129已按Evidence44/45闭合，当前产品基线`58453bf`；开始本票唯一增量设计，不进入产品编码。唯一设计`../design/126-live-delivery-design.md`；独立verification authority为root，合同`../design/126-frozen-verification-contract.md`及verifier-owned `../../../tests/test_ticket126_live_delivery.py`由其持有。

当前直接链还证明：`live_weixin`只处理`meta.turn_result`，漏掉现有116 safety branch的主人最低提示/联系人接续；第一init分支返回`(None,False)`，需要原challenge/source receipt的可推进终态；daily advanced后会按旧112释放正文，实际授权交接必须先成立，不能在重投时重建。候选统一覆盖这些既有主人/联系人投递缺口，不另建发送账本。

准备验证通过最高生产socket/真实pinned低层网络替身和真实115/116业务fixture，明确accepted/unknown而不伪造delivered/read。本阶段不读取真实账户秘密、不实际发微信、不改产品或冻结旧测试；同一checkpoint新鲜Spec/Standards及精确三件套冻结后才实施。

## Independent verification candidate (2026-10-18)

root独立持有`../design/126-frozen-verification-contract.md`与`../../../tests/test_ticket126_live_delivery.py`五个有限门，唯一设计为`../design/126-live-delivery-design.md`。真pinned低层/HTTP-only替身、同socket与Publisher registry、preconsent stable native事件、Core exact daily/safety回复、unknown回交丢失重启及唯一contact批准/纠正均在公开生产接口验证；当前产品缺失为5明确prerequisite failure、0error/skip，新内链尚未执行。compile/diffcheck通过，继承785/14及独立contact旧链char见合同。等待同一checkpoint fresh Spec/Standards；不授权产品编码，不接真实渠道，不改旧冻结门。
