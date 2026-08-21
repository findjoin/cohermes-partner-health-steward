# 【CAN】核验有依据的非诊断健康问答与真实结果能力

Type: research
Status: wontfix
Parent: [健康管家首发 TO、CAN 与 HOW 决策闭合路线](../map.md)
Blocked by: [【CAN】核验健康能力入口、初始化门禁与真实结果返回能力](79-verify-health-capability-entry-initialization-gate-and-result-contract.md), [【CAN】核验唯一微信准入、排他分流、逐次来源与重投结果能力](80-verify-unique-weixin-admission-routing-provenance-and-replay-results.md), [【CAN】核验紧凑六域健康画像与三类证据卡的维护追溯能力](82-verify-six-domain-portrait-and-three-class-evidence-capabilities.md), [【CAN】核验首跳模型路线、主人派生查询隔离与非诊断健康问答结果链](85-verify-first-hop-model-route-and-owner-derived-query-isolation.md), [【CAN】核验明确诊断范围候选形成、准入与诊断全链能力](86-verify-medical-content-governance-and-diagnostic-scope-candidates.md), [【CAN】核验诊断范围隔离、安全强制与不可用结果能力](88-verify-diagnostic-safety-enforcement-and-unavailable-results.md)

## Question

当主人主动提出不需要形成疾病方向排序、排除结论或个体用药改变的健康问题，例如询问一项现有测量代表什么、某种已记录生活因素可能怎样影响当前状态、或如何理解画像中的开放判断时，目标 Hermes 的健康入口、画像/证据索引、已准入通用知识和模型调用候选能力，能否形成有当前依据、可追溯、明确区分个人事实与一般知识、如实表达不确定性、关键未知和安全下一步的非诊断回答？

本票必须证明非诊断措辞不能用来绕过诊断范围：只要输出形成疾病方向排序、诊断标签、排除结论或个体化用药改变，就转入完整诊断合同；真正的一般健康回答仍须先经过独立安全分流，不得因诊断不可用而拼出残缺诊断，也不得回退普通聊天。主人可以查看本次实际使用的资料类型、来源、时间和用途；资料不足、冲突、过期、首跳路线未同意或安全链不可用时，主人得到明确的不可用或最低安全结果，而不是无依据回答。

回答中出现的新主人陈述只能作为候选个人证据，画像是否更新必须另经证据准入并返回真实结果；最终健康问答全文、提示、模型输入输出、草稿、临时资料集合和未通过候选不长期保存，只保留经准入的具体证据/画像关系以及必要的最小处理和交付事实。接口接受不等于主人实际收到。

本票对应[【CAN】重建完整 TO 的能力链与追溯关系](76-rebuild-complete-to-capability-chain-and-traceability.md)中的 C17。它只调查非诊断健康问答所需能力、限制和证据边界，不选择模型、提示词、检索、渲染或入口 HOW，不输出个体医疗建议；模型一次看似合理的回答不能证明该能力成立。

## Comments

### 2026-08-20 — 反对式完整性审计后补入

完整 TO 同时要求有依据的主人健康问答和受范围约束的辅助诊断。两者按输出效果区分；本票补上前者，避免把所有健康回答错误等同于诊断或主人询问职责。

### 2026-08-20 — 被连贯模型与非诊断问答调查吸收

本票不是因产品目标被取消而关闭。其 C17 全部范围——主人向健康管家提出非诊断问题、最小证据选择、个人事实与一般知识分离、不确定性和安全下一步、按输出效果转入诊断合同、新主人陈述只作候选证据、问答最小留存及真实交付——已由[【CAN】按连贯技术问题压缩并重接剩余能力调查](94-consolidate-current-can-investigations-by-coherent-route.md)吸收到[【CAN】核验首跳模型路线、主人派生查询隔离与非诊断健康问答结果链](85-verify-first-hop-model-route-and-owner-derived-query-isolation.md)。本票尚未形成 `## Answer`，不构成负向 CAN，也不计入研究轮次；它不再进入 Frontier 或 CAN 闭合前提，原 Question 只作为调查粒度重组的历史记录。
