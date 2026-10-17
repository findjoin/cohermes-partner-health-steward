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

## Frozen implementation authority (2026-10-18)

[Evidence47](../evidence/47-ticket126-precode-review-20261018.md)记录初审三个验证缺口和R2有界修正。最新唯一冻结checkpoint `3b53ed23389159a88f31459e6e9437edebebac9c` / tree `10c6fc19da6bb78d45c0a3c707915a1ad58b1ea1` 两轴PASS。三件套blob依次为设计 `4a6ec81c94edab252936815cf0fc98925def3d0f`、独立合同 `5b0b5336f27343192708869cb4591f67b7802ccd`、verifier `1559c548bf9b42af85f221bae67d2db9e7f65c5b`；覆盖旧候选，授权在此边界内实施。5个prerequisite红灯不代表内部路径已执行；未授权改动冻结门或真实渠道。root为验证权威，闭票仍需完整执行门与有界实施后双轴审查。

## Bounded verifier refreeze R3 (2026-10-18)

[Evidence50](../evidence/50-ticket126-unknown-cursor-refreeze-20261018.md)记录持久unknown/handoff后exact source cursor被总门错误阻断的独立复现与有界验证补齐。最新checkpoint `c54deceed45807f4c3397f4b07ceac23242bb660` / tree `fbbe72c2450f05ee52d9b03302b3de44373e32bb` 双轴PASS；设计blob不变，合同 `f80433a1c639b0747717274bbfd8f35b3dfe8eb0`、verifier `87577caefcc087c6c0e64034a5b365168e3605ff` 取代旧对应项。允许仅按既有设计修复该unknown ACK边界，保留一般写入／模型和重试冻结；仍未完成产品门。旧DynamoDB网络替身只识别占位release摘要另交独立验证修正，不改旧冻结文件或生产Provider。

## Latest bounded verifier refreeze R4 (2026-10-18)

[Evidence51](../evidence/51-ticket126-release-fixture-refreeze-20261018.md)：最新checkpoint `1158d51d100bbf45339414059e6c358a29d549a4` / tree `bd8cb08c42812ba60802bac15fdb1c6220f43d60` 两轴PASS，仅修正external DynamoDB fake对真实operation摘要的支持；五门及R3 unknown ACK方法AST不变，旧122/123与产品门禁不变。**当前唯一三件套**：设计 `4a6ec81c94edab252936815cf0fc98925def3d0f`，合同 `6bbc200afaa676fd42c8b76f68a3b7c422fdd89b`，verifier `df3427c9add51fe82456adf99f33ba7b9adfa272`；取代所有旧对应项。允许使用精确干净最新产品快照执行五门／794全量与编译／闭包，再进行有界实施后审查；当前尚未通过，不声称完成。


## Latest bounded verifier refreeze R5 (2026-10-18)

[Evidence52](../evidence/52-ticket126-refusal-and-confirm-time-refreeze-20261018.md)记录两个局部verifier样例矛盾及root独立public复现、精确837 provisional5/5和新鲜双轴PASS。当前唯一冻结checkpoint `837ac4dba1ca6024ca81e3bdbab5f2193344f878` / tree `c178e4e7fb64b7cca2d5ba2591f5aa817864ea7d`；设计 `4a6ec81c94edab252936815cf0fc98925def3d0f`，合同 `f824e8c2d2b00586c592edc1533ca5a03342813d`，verifier `a4d9b67366f3b0e52528f3c9f43562a6e50c80c7`。取代Evidence51旧合同/测试，不改产品或五方法/R3未知ACK。root允许在全新正式快照运行同精确source的五门/794/23/编译及闭包；尚未完成正式执行或实施后审查，不能闭票。磁盘失败无测试、临时验证副本清理和provisional证据的边界保留在Evidence52。


## Latest bounded verifier refreeze R6 (2026-10-18)

[Evidence53](../evidence/53-ticket126-formal-execution-20261018.md)记录精确837正式5/4/4/794及root23全绿；[Evidence54](../evidence/54-ticket126-safety-independence-refreeze-20261018.md)记录后继独立审查发现并由root实际复现的安全两路独立P2，故不能闭票。最新唯一冻结checkpoint `86115a5026a0549014326e4c4396c08e7e068846` / tree `f63ae993385df75821ee87f960b8a2078cbb7e06` fresh两轴PASS；design `4a6ec81c94edab252936815cf0fc98925def3d0f`，contract `5c05dd6ca14afbd0365d1d9f17a3cc6b2092b0a2`，verifier `a97dc7893bdd802142ed943d02b975f305ee821e`。仅原V05补同来源owner unknown不抑制当前contact及不同来源仍拒绝的等价类，保留旧五门。允许产品作者在既有Core claim接缝最小修此P2，仍须新精确执行全门/完整性及仅原finding双轴复核。旧837绿灯不冒充R6通过，未授权真实外部动作。
