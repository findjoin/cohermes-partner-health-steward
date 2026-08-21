# 【CAN】核验首跳模型路线、主人派生查询隔离与非诊断健康问答结果链

Type: research
Status: resolved
Parent: [健康管家首发 TO、CAN 与 HOW 决策闭合路线](../map.md)
Blocked by: [【CAN】按连贯技术问题压缩并重接剩余能力调查](94-consolidate-current-can-investigations-by-coherent-route.md), [【CAN】核验当前 Partner Hermes 基线、Plugin 生命周期与可信执行边界](78-verify-current-partner-hermes-baseline-plugin-lifecycle-and-trust-boundary.md), [【CAN】核验健康能力入口、初始化门禁与真实结果返回能力](79-verify-health-capability-entry-initialization-gate-and-result-contract.md), [【CAN】核验唯一微信准入、排他分流、逐次来源与重投结果能力](80-verify-unique-weixin-admission-routing-provenance-and-replay-results.md), [【CAN】核验受管健康状态数据平面、保护隔离与单一权威能力](81-verify-managed-health-state-plane-protection-and-single-authority.md), [【CAN】核验紧凑六域健康画像与三类证据卡的维护追溯能力](82-verify-six-domain-portrait-and-three-class-evidence-capabilities.md)

## Question

在当前 Partner Hermes 从健康资料选择、模型调用到主人结果返回的同一执行链中，能否准确定位并披露实际首跳模型服务路线，只沿主人已同意的首跳及其正常内部路由或故障切换处理；在首跳变化、fallback 改用其他 provider、endpoint、gateway 或实际路线无法证明时，能否暂停需要该路线的健康处理，同时保留无需新接收方的本地查看、纠正、导出和删除权？

同一执行链能否在任何查询离开本机前，依据查询主题、参数、组合、触发时机和优先级的真实来源，区分主人派生医学查询与独立通用医学更新，并阻止主人派生查询进入当前同意路线之外的搜索、医学 API、普通 Tool、缓存回源或普通 Agent 路径；去姓名、编码、延迟、批处理或缓存命中不得改变查询来源性质。

当主人询问现有测量代表什么、已记录生活因素可能怎样影响当前状态或如何理解画像开放判断等非诊断问题时，当前入口、画像与证据引用、模型调用和结果接口能否只选择本次必要且当前适用的已准入资料，形成可追溯的非诊断结果：明确区分个人事实与一般知识，标明实际使用资料的类型、来源、时间和用途，并表达不确定性、关键未知及安全下一步？只要输出效果形成疾病方向排序、诊断标签、排除结论或个体化用药改变，就必须停止非诊断路径并交给完整诊断合同；若独立安全前提返回危险、危险未明或安全能力不可用，本路径只能服从相应安全结果，不能拼出残缺诊断或回退普通聊天。

主人在问答中产生的新陈述只能成为候选个人证据，画像更新必须另经证据准入并返回独立真实结果。最终问答全文、提示、完整模型输入输出、草稿、临时资料集合和未通过候选不得长期保存；必须区分结果形成、业务提交、发送尝试、接口接受和主人实际到达。

本轮候选边界固定为当前固定 Hermes 与 Partner 的实际模型、fallback、Tool、搜索、缓存出站图和当前工作树候选，并用不含真实健康资料的合成场景核对测量解释、生活因素关联、新主人陈述、输出跨入诊断边界及安全前提不可用。完成条件是在一份带引用的证据报告中分别给出 C08 与 C17 的已证明能力、限制、反例、未知及仍需批准的实验；当前能力不存在或只能得到负向结论也可以解决。

本票只核验当前路线、出站隔离、最小资料选择、非诊断结果组装、诊断效果边界、职责交接、留存和真实返回能力。医学内容是否具备使用权、中文版本及专业审核，安全规则和诊断范围本身是否医学有效，继续由医学与辅助诊断调查负责。本票不选择 provider、模型、搜索、提示、检索或渲染 HOW，不发送真实健康正文；一次看似合理的模型回答不构成能力证明。

## Comments

### 2026-08-20 — 由完整 TO 能力链重建创建

本票最初对应[【CAN】重建完整 TO 的能力链与追溯关系](76-rebuild-complete-to-capability-chain-and-traceability.md)中的 C08。

本票取代[【CAN】核验健康模型调用与全部实际接收方事前锁定能力](57-verify-health-model-routing-and-recipient-preflight-capabilities.md)已经被后继 TO 取消的“枚举全部最终下游”问题，同时保留其关于 fallback、普通历史和 relay 不透明性的受限事实输入。

### 2026-08-20 — 合并非诊断健康问答结果链

[【CAN】按连贯技术问题压缩并重接剩余能力调查](94-consolidate-current-can-investigations-by-coherent-route.md)把 C08 与 C17 合并到本票，因为二者共同依赖同一条资料选择、模型出站、结果形成、持久化与交付证据链。医学内容与诊断规则是否合格仍由独立医学诊断全链调查负责。

## Answer

完整调查、事实分层、合成场景与一手引用见[《首跳模型路线、主人派生查询隔离与非诊断健康问答结果链核验》](../evidence/24-first-hop-model-route-owner-derived-query-isolation-nondiagnostic-answer-results-20260820.md)。本轮对正式 Partner 只做脱敏只读检查，没有读取或输出凭据、身份、聊天、Session、日志或健康正文，没有写远端、调用模型、发送消息、重启或制造故障；本地测试也只使用 fake model、fake source、fake channel 与非真实健康场景。

当前正式 Partner 的磁盘配置声明名义首跳为 provider `jojo`、base URL `https://max2.jojocode.com/v1`，API mode 为 `codex_responses`，请求模型名为 `gpt-5.6-sol`；配置未出现顶层 `fallback_model` 或 `fallback_providers`。这只能证明当前磁盘配置声明的名义首跳，不能证明一次实际请求、JOJO 内部最终节点或宿主 fallback 的实际选择。正式 Partner 没有健康 Plugin、受管初始化、主人同意路线快照或健康状态，所以“实时路线与同意路线比较、跨首跳前暂停、无需新接收方的本地数据权利继续”均未实现或未证明。固定 `ctx.llm` 虽是不自动创建普通 Session 的候选原语，但公开接口不能在发送前完整预览 endpoint 或禁用所有跨首跳 fallback；普通 Agent、Tool、Web Search、缓存回源及内部 dispatch 也没有共享的主人派生查询来源闸门。

未部署工作树还给出了 C08 的确定性允许分支反例：当分类结果要求来源核验、没有新鲜资料卡且主人本次消息命中静态关键词 URL 时，候选会按该消息选出的 URL 发起 HTTPS 回源。URL 白名单、去姓名、无 query 参数或先查缓存只能限制目标和请求形态，不能改变主题与触发时机来自主人这一事实；候选也没有“即使没有这位主人仍会按同一计划取得相同资料”的通用更新证明。因此主人派生查询隔离当前**未实现、未证明**。

C17 同样是负向结论。正式 Partner 没有受管且符合现行合同的健康问答入口或结果对象；普通 Agent 的一般问答面不能冒充该能力。工作树只有若干局部候选原语，包括 health answer handler 单轮不读写普通历史、禁止模型 Tool、限制画像摘要和来源卡数量、引用 ID 白名单以及不保存回复正文的交付 ledger；全入口普通 Session 隔离仍未证明。但回答 schema 只有自由正文和来源卡 ID，不能强制区分个人事实与一般知识，不能完整呈现资料类型、来源、时间、用途、不确定性、关键未知和安全下一步，也没有疾病排序、诊断标签、排除结论、个体化用药改变的产品级输出闸门或危险、危险未明、安全能力不可用的独立前提。若分类模型返回新陈述的旧对象 candidate，后续准入与画像更新仍使用旧合同，更新结果只是问答尾标；结果形成、权威业务提交、发送尝试、接口接受和主人实际到达也没有完整分层。本地 ledger 的 `sent` 只是由 transport 接受映射的状态，不是 provider 回执或主人真实看到的证明。

四个相关本地测试模块共 69 项，其中 66 项通过、3 项跳过、0 项失败；它们只证明上述旧候选局部函数，不覆盖现行六域/三类证据、主人派生查询隔离、诊断效果与安全交接、真实模型/搜索/微信、业务提交或主人到达。本票因此给出一项**负向但已闭合的 CAN 事实**：当前固定 Hermes 有可组合的底层原语，当前正式能力与工作树候选均不能支撑 C08 或 C17。该结论不降低任何 TO，也不选择 provider、模型、搜索、提示、检索、缓存、渲染或最终 Plugin/HOW；医学内容权利、中文版本、专业审核、安全规则与诊断范围继续由后继诊断全链调查负责。
