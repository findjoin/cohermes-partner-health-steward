# 130 - 接通受控自然语言日常 Runtime

Type: task
Status: resolved
Parent: [健康管家有限实施链](../map.md)
Blocked by: [124 - 真实健康入口](124-connect-pinned-hermes-live-health-entry.md), [125 - 生产模型Adapter](125-implement-partner-model-and-governed-knowledge-adapter.md), [131 - 明确标识的非诊断模型操作预算](131-support-explicit-nondiagnostic-model-operational-budget.md)
Unblocks: [128 - 主人产品验收](128-deploy-and-complete-owner-product-acceptance.md)

## Characterization input

2026-10-18独立源码核查：产品目录没有生产DailySkillRuntime executor；coordination.py约6322需外部callable，证据提交前的execute_evidence_stage已经需要StewardPlan/EvidenceDecision，后续需要PortraitDecision/StewardResolution。plugin.receive_weixin连续推进两阶段。现有合法模型链仅允许evidence-finalized来源，core.py约5361–5374及5745–5757；store.model_effect_for_source限制一个source一个模型效果。125只执行exact已授权request，不生成这些typed输入。

已有public路径可以完成：合法typed证据阶段→turn prepare/commit/finalize→exact model-work intent/grant/125→完整终态→NonDiagnosticReplyPipeline→typed portrait/reply→唯一commit/finalize。不能据此宣称任意自然语言记录/画像已完成，有限确定性解析也不能包装成完整NL。

## Required delta and retained boundaries

承接同一Core的controlled-effect、当前owner/route/profile同意、源绑定、typed候选与唯一提交。若模型做证据前抽取，先冻结最小候选阶段及其purpose、exact effect identity、重放/unknown/失败与后续问答的关系；不得直接在executor HTTP绕过Core授权，不新增第二业务状态/批准ledger。模型无数据库写权；既有七Skill runtime实际use proof与Core验证继续成立。任何未获批准的模型/owner资料路径保持关闭。

本票当前只记录已复现的实现差额，是128非诊断产品可用性的前置输入；不提前冻结详细设计/测试，待124/125当前接口闭合后独立验证与双轴预审。医学许可及诊断激活仍归127，不被此票替代。

主人已选择当前 JOJO 的非诊断操作预算与公开上下文限制，见 [ADR 0024](../../../docs/adr/0024-allow-owner-selected-nondiagnostic-model-operational-budget.md) 与 Ticket 131；本票须待该模式经验证后承接，不自行把配置窗口、风险接受或生产 executor 当作共同容量证明，亦不借此放开诊断。

## Cross-process characterization input

独立只读核查补充：现有Core.execute_strict_health_model的lifecycle lock跨adapter.execute；daily_turn_runtime_preparation也跨yield执行executor。生产service逐连接串行，反向等Plugin callback会堵唯一socket。CorePort现有claim只交intent/grant metadata；terminal仅status/result_ref，缺完整StrictModelRequest/ModelTransportResult。开启model_authority时effect结果必须匹配Core进程自身观察的report，不能让Plugin自报成功绕过。

可复用严格request/result codec、effect session/grant、已持久model_attempt_started、既有终态journal与lease释放，以及DailySkillRuntime.complete已有model_answer_resolution/model_reply_atoms参数。后继冻结需明确短调用的canonical request准备/开始标记、Plugin进程执行、同session完整terminal由Core重验、继续唯一typed提交；不能让Core持模型凭据或在executor发HTTP。现authority_for_digest只恢复route/profile/schema，不含生产measurement strategy，组合根也需实际typed绑定。这里仍只是阻塞接口事实，不提前定新wire/状态。

## Live owner-operation characterization input

当前 `HealthPlugin.health_operation`（plugin.py约939–977）虽可构造TrustedHealthCommand，真实 `receive_weixin` 在初始化后只进入safety/coarse/daily路径；`LiveHealthCoreOperations`与`LiveHealthWeixinAdapter`未映射主人任务、控制及数据权利操作。因此仅提供NL证据executor仍不能完成128阶段A所列的提醒/任务/暂停/停止记录/权利的真实入口。后继只在同一Module/同三类kind内承接受真实admitted owner source绑定的有限显式命令或typed候选；现有Core命令权威、批准和回执不变，不能把模型抽取的文本当成主人已批准的不可逆动作，也不能从普通handler直接调用健康写入。这里仅记录现行公开链的实现差额，不提前冻结详细命令API或测试。

## 唯一增量设计候选

2026-10-18由deployment_audit承接只读characterization与[受控NL唯一设计候选](../design/130-governed-live-nondiagnostic-runtime-design.md)。候选明确同源intake/answer、同budget/stage关系、短Core调用与Plugin125网络、真实主人有限入口；独立verification authority为implementation_audit。当前尚未冻结、未实现，候选接口与最小权利等价类需同一checkpoint预审后固定；不改变131或126冻结权威。

候选在同一引用内收口：原64KiB CorePort不变，以同effect session短内存、8MiB总量/32768-byte片传完整request/result；真实owner rights包含受管JSON附件的单次固定Weixin媒体链，8MiB本地文件上限（同export effect session有限分片）与不可远程证明的CDN删除限制明确披露。真实due/localday review wake、停止记录正文短寿命和内部纯executor仍为必需验收输入。该补充不构成实现、冻结或闭票。

初始化独立确认、控制/权利及失败未知提示的实际主人结果也由同候选收口：原native source/业务transition→Core固定结果→原owner-outbox→126受控发送，不以enabled projection/ACK或RPC返回代替实际交接；131限制说明实际随成功结果显示。

## Frozen implementation authority (2026-10-22)

[Evidence57](../evidence/57-ticket130-precode-freeze-20261022.md)记录原V03/V06预审P2与已实证Gate07 fixture矛盾的独立R2修订，以及同一checkpoint的新鲜Spec／Standards PASS。当前唯一冻结checkpoint `813d7a77d3013bea2fe18708961efe2ae23de291` / tree `177bd5932689b989860d697adc6b64e374c722ab`；设计 `b5df3ef47fde1993a72cc293d5e56edee4fb44dc`、合同 `c08f24c07fe7ba4dce0dd299db300834088b1f9a`、verifier `ba7aa63a04ce541f4463243eaba170e3850e527a`。root授权在此边界实施，产品作者不得改冻结门。7个prerequisite失败不代表内部路径已执行；真实外部动作／部署仍由128承接。前置126已按Evidence55/56闭合，794全量／root23是精确d86的历史结果，不冒充本票绿灯。完成仍须本票七门、受影响／全量／编译及18冻结完整性、实施后双轴与root闭票。

## Narrow verifier refreeze R2.1 (2026-10-22)

[Evidence58](../evidence/58-ticket130-unknown-time-refreeze-20261022.md)记录原时间enum样例的实际public roundtrip与fresh双轴PASS。唯一当前checkpoint `83448d732bdf9a9ec1e693f8ff5a6c043ca68a91` / tree `5a9b6c8e7ab4997320b7e44aa8d189353d73ae30`；设计 `b5df3ef47fde1993a72cc293d5e56edee4fb44dc`不变，合同 `7b07cea1e21d61d06c3dae65f7146210c945d189`、verifier `05557434802fb897b18eeb281989529d1817890e`取代R2对应项。仅原V02 unknown occurrence按旧known/uncertain合同期待uncertain，不扩产品enum或七门。其余Evidence57实施权限不变，最终执行和闭票仍待完成。

## Narrow verifier refreeze R2.2 (2026-10-22)

[Evidence59](../evidence/59-ticket130-wide-initialization-refreeze-20261022.md)记录真实隔离观察到wide positive漏初始化而正确被拒绝的局部假红，以及仅补既有public初始化的fresh双轴PASS。当前唯一checkpoint `87fb488291f13d935f89f6bed963546b1fe88670` / tree `e4cf0f73bf040dfb66e8ba60df4994e390b6b96c`；design `b5df3ef47fde1993a72cc293d5e56edee4fb44dc`不变，contract `518abde834452777d02885ba56d54e049c223db6`、verifier `774201899a2e70103e5bf400a712555056a192cf`取代R2.1对应项。七家族和产品初始化门禁不变。旧基线7个prereq失败及补初始化后的debug因果对照均不冒充当前正式门绿灯；完整最终source执行／闭票仍待完成。

## Narrow verifier refreeze R2.3 (2026-10-22)

[Evidence60](../evidence/60-ticket130-native-replay-refreeze-20261022.md)记录root与独立权威双复现的原native跨batchcursor alias兼容缺口，以及仅原V01有限补门的fresh双轴PASS。当前唯一checkpoint `7977d6c5563d8398b27f2377bfb9b71d05fa5bb3` / tree `99fa4c8914120e646c83d7e2f790cee912ecf79b`；design `b5df3ef47fde1993a72cc293d5e56edee4fb44dc`不变，contract `f8b82e354138961ae5d4cf227deaffa5653e0f33`、verifier `096792e578f98f0ef546c9c7d2e00376cf9a124e`取代R2.2对应项。只授权沿旧准入canonical source／原outbox恢复重投语义，不重建正文或形成新model/record/send；原七家族不变，完整执行与闭票仍待完成。

## Narrow verifier refreeze R2.4 (2026-10-22)

[Evidence61](../evidence/61-ticket130-recovery-observation-refreeze-20261022.md)保留精确a71/R2.3正式七门6fail的真实结果，并记录原V04三处已独立实证的观察矛盾与fresh双轴PASS。当前唯一checkpoint `2d9da87194554bb31119d618ce8baaf2af3e5bc3` / tree `e14e7aae0a96185a6182794657be2f7b527f8300`；design `b5df3ef47fde1993a72cc293d5e56edee4fb44dc`不变，contract `1da035fa0994bb718184bd646292a24a57fa0aa7`、verifier `d4c943f5876720614cc5bd8088b22e0b661f0117`取代R2.3对应项。仅恢复家族的原Core正文拒绝／原Store零事实、已接受提示同refs零重发、fixture真实时间顺序观察修订；严格handoff及生产chrono未放宽，七家族不变。产品错误继续修复，完整最终执行与闭票仍待完成。

## Narrow verifier refreeze R2.5 (2026-10-22)

[Evidence62](../evidence/62-ticket130-original-review-authority-refreeze-20261022.md)记录独立public复现的原V05权威观察矛盾及fresh双轴PASS。当前唯一checkpoint `20f48dcd4149ceaa788f39114c3a879a347709f0` / tree `d291984067d2d49b71aaf8ad071e1c6a279d0485`；design `b5df3ef47fde1993a72cc293d5e56edee4fb44dc`不变，contract `462b33c7b7e5c76d13b71469a1f8b2b1c610287a`、verifier `38449b5b8bbaf44cf74d6de3acab9f7ce0894b72`取代R2.4对应项。仅V05读取原唯一DailyReviewLedger的current当地日真实完成与完整重放不变，防止为假红伪写Settings第二权威；其余家族、产品权限及设计不变。WIP补充结果不冒充正式门，完整最终执行与闭票仍待完成。

## Narrow verifier refreeze R2.6 (2026-10-22)

[Evidence63](../evidence/63-ticket130-handoff-and-replay-observation-refreeze-20261022.md)记录原known正向提前teardown及旧batch游标倒退的实证矛盾、真实重投产品错误和fresh双轴PASS。当前唯一checkpoint `fb97e5e656b4ebe29d7b1dfce25c24d6ce58ed46` / tree `b6e7fd0811be0fd017d848895ccda8086b50e0cf`；design `b5df3ef47fde1993a72cc293d5e56edee4fb44dc`不变，contract `5134e3a1f137bf24fe0acdcfc0aa50a43117214d`、verifier `19ba1c10dbf2de199c751c1f454569fced2091ed`取代R2.5对应项。V04正向必须等同source真实accepted/handoff后结束，原unknown严格门不变；V05不要求旧cursor倒退，同时加强实际重投接受、原refs与单任务/取消/零新副作用断言。既有HMAC归一的入口兼容缺口继续产品修复，不能把causal-id-conflict当成功。七家族、其余16冻结blob、设计及产品权限不变；正式完整执行、闭票及128真实部署仍待完成。

## Same-freeze full-suite resource failure (2026-10-22)

[Evidence64](../evidence/64-ticket130-full-suite-resource-lifetime-failure-20261022.md)记录精确364943e正式组件20/20绿色但同快照全量801项出现7个真实FD耗尽error。独立sealed对照及产品作者public纯合成复现均证明原Service正常关闭与启动失败每轮遗留10个私有资源FD，另有临时provider遗留；不是仅fixture错误。root退回原authority/service自有资源生命周期内窄修，禁止提高limit、改冻结或拆全量绕过，R2.6十八冻结身份不变。当前票仍claimed，未开始实施后双轴或宣称全量／部署完成。

## Narrow verifier refreeze R2.7 (2026-10-24)

[Evidence66](../evidence/66-ticket130-green-execution-and-preinit-ordinary-regression-20261024.md)保留精确eff03ae的20／801／root30全绿事实，并记录独立公开对照实证的初始化前普通分流回归。[Evidence67](../evidence/67-ticket130-preinit-ordinary-compatibility-refreeze-20261024.md)记录仅原V01增加“已装配模型桥时 ordinary 转交一次、health 仍拒绝”的有限兼容观察、真实预期红与fresh双轴PASS。当前唯一冻结checkpoint `2a347c91f7645fd656db9569f10ad63f1bf2e5bd` / tree `ffe13de7219d153450af7c254ecc75125c2831c0`；design `b5df3ef47fde1993a72cc293d5e56edee4fb44dc`不变，contract `fcaa70d0182f31500fd695079f95859b99f1f7c0`、verifier `6e1522e4e7e944dca379b0f8f2e0f12391d9ec09`取代R2.6对应项。七家族、其余16冻结bytes和健康初始化权限不变。root仅授权原Adapter分流兼容修复；完整精确新版本执行、实施后双轴、闭票与128部署仍待完成，不把旧801绿色覆盖新缺口。

## Answer

已按唯一R2.7冻结在精确产品 `f21e8ad43bc92954da0a0ed5322cf421e48d0828` / tree `bf1f91164b318c65d8f4d5d010911fac8e555834` 完成受控intake/answer、真实七Skill typed候选与唯一提交、Plugin侧125单次模型执行、同Core有限主人操作/任务/复盘及受管JSON附件链。原三类CorePort、64KiB帧、8MiB短寿命分片、当前grant/peer、unknown冻结和原126投递保留；初始化前普通分流兼容已恢复，健康仍需独立原生同意。

[Evidence68](../evidence/68-ticket130-final-execution-review-and-closure-20261024.md)记录精确20组件、801全量、root30、91编译、91来源/18冻结/7467runtime闭包不变、干净普通push和fresh Spec/Standards双PASS；无未处置P0–P2 blocker。当前设计/合同/verifier blobs为 `b5df3ef47fde1993a72cc293d5e56edee4fb44dc` / `fcaa70d0182f31500fd695079f95859b99f1f7c0` / `6e1522e4e7e944dca379b0f8f2e0f12391d9ec09`。root只作元数据闭票，不把历史失败改写为当前绿色。

解除128实现前提；真实default部署、权限隔离、初始化和主人可用验收继续由128完成，医学范围仍需127。本票没有实际外发、生产部署或产品验收声明。
