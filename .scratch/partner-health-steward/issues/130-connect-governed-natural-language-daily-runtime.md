# 130 - 接通受控自然语言日常 Runtime

Type: task
Status: ready-for-agent
Parent: [健康管家有限实施链](../map.md)
Blocked by: [124 - 真实健康入口](124-connect-pinned-hermes-live-health-entry.md), [125 - 生产模型Adapter](125-implement-partner-model-and-governed-knowledge-adapter.md)
Unblocks: [128 - 主人产品验收](128-deploy-and-complete-owner-product-acceptance.md)

## Characterization input

2026-10-18独立源码核查：产品目录没有生产DailySkillRuntime executor；coordination.py约6322需外部callable，证据提交前的execute_evidence_stage已经需要StewardPlan/EvidenceDecision，后续需要PortraitDecision/StewardResolution。plugin.receive_weixin连续推进两阶段。现有合法模型链仅允许evidence-finalized来源，core.py约5361–5374及5745–5757；store.model_effect_for_source限制一个source一个模型效果。125只执行exact已授权request，不生成这些typed输入。

已有public路径可以完成：合法typed证据阶段→turn prepare/commit/finalize→exact model-work intent/grant/125→完整终态→NonDiagnosticReplyPipeline→typed portrait/reply→唯一commit/finalize。不能据此宣称任意自然语言记录/画像已完成，有限确定性解析也不能包装成完整NL。

## Required delta and retained boundaries

承接同一Core的controlled-effect、当前owner/route/profile同意、源绑定、typed候选与唯一提交。若模型做证据前抽取，先冻结最小候选阶段及其purpose、exact effect identity、重放/unknown/失败与后续问答的关系；不得直接在executor HTTP绕过Core授权，不新增第二业务状态/批准ledger。模型无数据库写权；既有七Skill runtime实际use proof与Core验证继续成立。任何未获批准的模型/owner资料路径保持关闭。

本票当前只记录已复现的实现差额，是128非诊断产品可用性的前置输入；不提前冻结详细设计/测试，待124/125当前接口闭合后独立验证与双轴预审。医学许可及诊断激活仍归127，不被此票替代。
