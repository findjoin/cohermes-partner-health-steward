# 130 - 接通受控自然语言日常 Runtime

Type: task
Status: claimed
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
