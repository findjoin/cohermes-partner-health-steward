# 医学知识来源、检索接口与安全强制工具核验（Ticket 59）

## 1. 范围、基线与证据纪律

- 本报告只回答 CAN：Ticket 50 选择辅助诊断与安全 HOW 前，哪些具体医学来源、正式接口和目标现场工具真实存在，分别能做什么、不能做什么。它不选择最终来源组合、诊断规则、提示词、危险阈值或实现结构。
- 产品输入以当前 [`map.md`](../map.md)、[`CONTEXT.md`](../../../CONTEXT.md) 及已解决的 [Ticket 46](../issues/46-verify-diagnostic-reasoning-knowledge-and-safety-capabilities.md) 为准：同一个 Partner Hermes 可以给出 AI 辅助诊断，但必须展示支持与反对证据、缺失信息、紧急度和下一步；不得把 AI 判断冒充医生正式诊断，不得独立建议开始、停止或调整处方药；急症、自伤和危险用药必须优先安全处理。
- 固定 Hermes 源码为 v0.20.0 / tag `v2026.8.3` / commit [`3c27eb6234bf91b8ceee9e9071591b31e9b148cb`](https://github.com/NousResearch/hermes-agent/commit/3c27eb6234bf91b8ceee9e9071591b31e9b148cb)。2026-08-17 16:03:20（Asia/Shanghai）的目标只读复核确认主机 `findjoin` 仍运行该 commit、Hermes v0.20.0、Python 3.11.15。
- 现场只读取版本、包元数据、Plugin 清单和服务状态；没有读取 `.env`、凭据、聊天、Memory、数据库、日志或健康正文，没有安装依赖、修改配置、重启服务，也没有发送模型或微信请求。
- 外部来源只使用发布机构自己的网页、文档、固定源码或正式接口说明。公开可阅读不自动等于允许批量摄取、翻译、改写、训练模型或商业再发布；许可未知时保持未知。

## 2. 直接结论

1. **不存在一个已经核验、可直接接入的“万能医学知识 API”。** 权威诊断规则、疾病编码、患者教育、论文检索、药品标签和急症规则是不同产品。任何一个来源单独使用都会留下实质缺口。
2. **真正能作为诊断要求或临床管理依据的候选主要是具体 WHO 临床手册、具体 NICE 指南和中国国家卫生健康委发布的具体指南/规范。** WHO ICD-11 MMS 主要是分类与术语；MedlinePlus 是患者教育；PubMed 是文献索引；DailyMed/openFDA 是药品标签。后四类不能单独证明某个诊断成立。
3. **中文且可机器调用的最成熟候选是 WHO ICD-11 MMS API，但它只解决术语和编码，不解决完整诊断逻辑。** 中国国家卫生健康委有原生中文、适合中国语境的正式指南，但本轮没有发现统一结构化 API、全量版本清单或开放再利用许可。NICE 的结构和版本能力较强，但当前项目尚未获许可，国际与 AI 使用需要审批和许可，内容为英文。
4. **目标 Hermes 已有实现确定性校验所需的基础构件，但没有医疗安全成品。** 当前目标可用 `pydantic 2.13.4`、`jsonschema 4.26.0`、`httpx 0.28.1`、`requests 2.33.0` 和 `PyYAML 6.0.3`；正式 Plugin Adapter 可以在普通 Agent 之前拥有消息，`ctx.llm` 可以返回结构化候选结果。结构校验只能证明字段和枚举满足合同，不能证明诊断真实、来源适用或危险已排除。
5. **Skill、提示词、普通 Tool、通用 Hook/Middleware 和“模型自己记得安全”都不能充当不可绕过的医疗闸门。** 固定 Hermes Hook/Middleware 会在回调异常时继续原路径；普通 Agent 也可以不调用 Tool 直接回复。只有健康 Plugin 自有代码实际控制模型调用、结果接受和发送出口时，才保留“检查失败就不提交、不发送”的实现空间；该闭环当前尚未实现。
6. **当前 CAN 结论是“候选与实现空间存在，但生产来源合同未闭合”，因此不能直接放行 Ticket 50。** 本轮没有证实任何一套来源同时具备足够中文诊断内容、当前项目可用许可、可追溯版本和已验证目标可用性。目标 Hermes 保留实现强制控制流的空间，所以这不是“技术上绝对做不到”；但必须先通过 TO-CAN 决策明确是否保持辅助诊断目标，并把来源许可、中文内容清单和专业审核作为上线前硬依赖，不能把这些缺口悄悄留到实现后再处理。

### 2.1 逐来源事实矩阵

| 来源 | 只可承担的职责 | 版本与更新 | 中文覆盖 | 许可与当前可用性 | 远程接收边界 | 可追溯引用 |
|---|---|---|---|---|---|---|
| WHO ICD-11 MMS | 疾病术语、代码和分类关系；不是诊断规则 | 按 `release id` 发布，API 保留多版 | `2026-01` 有官方中文 | 可按 WHO 分类许可嵌入软件，但代码、标题和 URI 必须保留；翻译和 crosswalk 需另行书面协议 | 云 API 会接收查询；可本地部署。主人事实派生查询仍先按潜在健康数据外发处理 | `release + entity URI + MMS code + language` |
| WHO CDDR / mhGAP | 精神健康诊断要求和管理建议候选；面向卫生专业实践 | 2024 CDDR、2023 mhGAP 固定出版物，无结构化更新 feed | CDDR 当前列英文原版和意大利语版本，未见官方中文全文；mhGAP 本轮未闭合完整中文覆盖 | CDDR 为 BY-NC-ND，mhGAP 为 BY-NC-SA；本项目的改编、翻译、规则化和商业使用授权均未闭合 | 下载后可本地使用，不必逐次外发主人资料 | 出版年、ISBN、章节/页码 |
| 国家卫生健康委指南/规范 | 中国语境的中文诊断与管理依据候选 | 分病种发布 HTML/PDF，以版本年和发文信息追踪；无统一 feed | 原生中文 | 官网标示版权所有，本轮未找到批量摄取、改写或 AI 再利用的开放许可；当前只能确认公开可读，不能确认生产再利用获准 | 下载后可本地使用；无需把主人资料发给官网 | 标题、版本年、发文字号、发布日期、章节/页码、文件哈希 |
| NICE Guidance / Syndication API | 结构化诊断、治疗和管理指南候选 | 指南/推荐编号、发布日期、更新记录、ETag/Last-Modified | 英文，无官方中文 API 内容 | 国际和 AI 使用需申请、许可并可能付费；当前项目无 key 或许可 | 远程查询会形成访问记录；主人事实派生查询先按潜在健康数据外发处理 | 指南号、推荐号、发布日期、更新日期和本地快照 |
| MedlinePlus / PubMed | 患者解释；证据发现。均不是诊断规则 | MedlinePlus 有页面/XML 更新；PubMed 有记录更新、勘误和撤稿 | MedlinePlus 英/西语；PubMed 文献语言不一致，无完整中文规则层 | 受各自使用条款和论文版权约束；没有面向本项目的诊断内容许可合同 | 官方接口未承诺 PHI 处理、无日志或 BAA；主人事实派生 query 不能当作“已去隐私” | topic URL/更新时间；PMID/DOI/发表日期/勘误撤稿状态 |
| DailyMed / openFDA / RxNorm / 国家药监局查询 | 药品标签发现、核验和术语；不是诊断规则，也没有现成全覆盖相互作用闸门 | DailyMed 有 SPL 历史；openFDA 周更新；RxNav 相互作用服务已停；国家药监局分散发布 | 美国来源主要英文；国家药监局资料中文 | 各来源许可不同；openFDA 明确不能依赖其作医疗决策；当前没有已获准的中国市场综合药物规则服务 | 远程产品查询也可能暴露主人正在使用或关注的药物，应按潜在健康数据外发处理 | SETID/SPL version/date；openFDA version/effective time；国家药监局文件信息 |
| WHO SMART Guidelines | 已发布特定领域的机器可读工作流与规则结构 | 按具体 DAK/Implementation Guide 版本治理 | 逐包不同，本轮未发现覆盖本产品范围的完整中文包 | 许可必须逐包核验；没有通用成人健康规则包可直接采用 | 取决于选择本地包还是远程服务，当前未选择 | 具体包、版本、规则标识和来源文档 |

## 3. 医学来源与正式接口矩阵

### 3.1 WHO ICD-11 MMS：术语、编码与版本锚点

- WHO ICD API 是 HTTPS REST API；v2 请求使用 `API-Version: v2`，云端根地址为 `https://id.who.int/`，实体 URI 是稳定标识和 API endpoint。[ICD API v2](https://icd.who.int/docs/icd-api/APIDoc-Version2/)
- 当前官方支持表列出 `2026-01` release 的 ICD-11 MMS 中文，语言代码为 `zh`；历史 release 仍可按版本访问。[版本与语言](https://icd.who.int/docs/icd-api/SupportedClassifications/)
- 云 API 需要注册并取得访问 key；WHO 也提供 Docker、Windows service 和 Linux systemd 三种本地部署方式。[API 入口](https://icd.who.int/icdapi) [本地部署](https://icd.who.int/docs/icd-api/ICDAPI-LocalDeployment/)
- 本地 Docker 可以设置 `saveAnalytics=false`，物理含义是本地容器不收集或向 WHO 发送搜索分析数据；这不是关闭容器日志，也不是医学正确性开关。[Docker 参数](https://icd.who.int/docs/icd-api/ICDAPI-DockerContainer/)
- 许可为 CC BY-ND 3.0 IGO。纳入软件时必须保留分类代码、标题和 URI；翻译以及与其他分类/术语制作 mapping 或 crosswalk 不在现有许可内，需 WHO 另行书面协议。[ICD-11 许可](https://icd.who.int/docs/icd-api/license/) [WHO 分类许可协议 1.2.2–1.2.4](https://icd.who.int/en/docs/icd11-license.pdf)
- **CAN 边界：** 可为诊断候选、画像事实和引用提供 `release id + entity URI + MMS code + language` 的强版本锚点；不能仅凭一个 ICD 代码生成或确认诊断，也不提供治疗、急症、自伤或药物相互作用规则。
- 数值物理含义：`v2` 是 API 合同的主版本，不是 ICD 医学内容版本；`2026-01` 表示 2026 年 1 月发布的分类内容，不是有效期或复查周期。

### 3.2 WHO CDDR 与 mhGAP：精神健康临床内容

- WHO 2024 年 CDDR 是 ICD-11 精神、行为和神经发育障碍的临床描述与诊断要求，面向负责临床诊断的专业人员及需要理解这些障碍的其他卫生专业人员；它与统计分类 MMS 不同。[CDDR 发布页](https://www.who.int/publications/i/item/9789240077263)
- CDDR 是 852 页、ISBN `9789240077263` 的固定出版物，没有结构化查询 API 或自动更新馈送；本轮核验到英文原版和发布页列出的意大利语正式版本，未发现官方中文全文，不能把中文新闻稿当作中文诊断手册。[CDDR 发布页](https://www.who.int/publications/i/item/9789240077263) [WHO 中文发布说明](https://www.who.int/zh/news/item/08-03-2024-new-manual-released-to-support-diagnosis-of-mental--behavioural-and-neurodevelopmental-disorders-added-in-icd-11)
- CDDR 采用 CC BY-NC-ND 3.0 IGO：非商业条件下可以按许可复制传播，但不得改编；自行翻译或将内容改造成可发布规则包需要另外处理许可。[CDDR 正式 PDF](https://iris.who.int/bitstream/handle/10665/375767/9789240077263-eng.pdf)
- WHO 2023 mhGAP guideline 覆盖精神、神经和物质使用障碍的循证推荐，正式出版记录标明 CC BY-NC-SA 3.0 IGO；本项目若涉及商业使用、翻译或规则化，仍须按该许可与 WHO 要求另行核验。[mhGAP 2023](https://iris.who.int/handle/10665/374250)
- **CAN 边界：** 两者可作为心理/精神健康知识候选和引用依据，但定位在卫生专业实践，不能直接当成对普通用户自动确诊的机器规则；完整中文、结构化接口和当前项目再利用许可尚未闭合。
- 数值物理含义：`852` 是 CDDR 正文页数，只表示人工摄取和审查规模；`2024` 与 `2023` 是出版年份，不是知识自动失效年。

### 3.3 中国国家卫生健康委指南与规范：中文、中国语境、分散发布

- 国家卫生健康委发布的《精神障碍诊疗规范（2020年版）》是原生中文正式规范，覆盖精神障碍的评估、诊断、鉴别、治疗和管理，并要求结合病史、体检、辅助检查等综合判断。[发布通知](https://www.nhc.gov.cn/yzygj/c100068/202012/b4305ace9e14440792eb76d29602c88a.shtml) [规范 PDF](https://www.nhc.gov.cn/wjw/c100175/202012/d21da62f7a654ae28650bc473f6d05e3/files/1644833637272_77437.pdf)
- 国家卫生健康委还按病种发布《肥胖症诊疗指南（2024年版）》《原发性肝癌诊疗指南（2024年版）》等正式文件。[肥胖症指南](https://www.nhc.gov.cn/yzygj/c100068/202410/18966b78087d44429f934a2ef028b027.shtml) [肝癌指南](https://www.nhc.gov.cn/yzygj/c100068/202404/b12cab9adae7424493cd2d387f018367.shtml)
- 本轮在官方资料中没有发现覆盖全部诊疗指南的统一 API、不可变版本 endpoint、结构化规则格式或自动更新 feed。可追溯引用需要自行保存标题、版本年、发文字号、发布日期、章节/页码和下载文件哈希。
- 官方页面可阅读和下载，但本轮没有找到允许批量摄取、改写、翻译、训练模型或再发布的开放许可；这些用途必须在确定 HOW 后另行核验，不能从“主动公开”推导出任意再利用权。
- 2020 精神障碍规范沿用 ICD-10 诊断体系，不能静默替换成 ICD-11 CDDR，也不能把二者条目自动合并。
- **CAN 边界：** 这是当前最重要的中文、中国临床语境候选，但需要逐病种清单、版本监测、许可和专业审核；目前不是可直接调用的统一知识服务。
- 数值物理含义：`2020`、`2024` 是文件版本年；它们不是“每 2020/2024 天更新”或自动证明内容仍为最新。

### 3.4 NICE Guidance / Syndication API：结构化指南强，但当前未获许可

- NICE Syndication API 是 REST 服务，支持 HTML、Atom、JSON 和 XML；调用需 `API-Key` 与 `Accept`，并提供 ETag、Last-Modified 和 HEAD，可定位资源是否变化。[API 技术说明](https://www.nice.org.uk/corporate/ecd10/chapter/using-your-api-key-to-explore-nice-content)
- 指南有编号、推荐编号、发布日期与更新记录，可支持逐条引用和变更监测。API 覆盖广泛生理与心理主题，但不包含 CKS、BNF 或 BNF for Children。[NICE API 申请页](https://www.nice.org.uk/reusing-our-content/nice-syndication-api/nice-syndication-api-application-form)
- 国际使用需要审批、许可证和费用；AI 使用 NICE 内容必须走许可，当前项目没有获批 key 或许可；内容为英文，没有官方中文 API 内容。[国际与 AI 许可](https://www.nice.org.uk/reusing-our-content) [NICE 条款](https://www.nice.org.uk/terms-and-conditions)
- 官方指南建议 page feed 至少每 24 小时刷新、其他信息至少每 7 天刷新；`24 小时`和`7 天`是内容缓存刷新周期，不是患者复查、病情观察或急症响应时间。[API 概述](https://www.nice.org.uk/corporate/ecd10/chapter/introduction)
- **CAN 边界：** 版本、引用和接口能力足以成为候选，但许可、费用、中文和目标访问都未闭合，不能写成当前可用的生产来源。

### 3.5 MedlinePlus 与 PubMed：患者解释和证据发现，不是诊断规则

- MedlinePlus Connect 接收已经存在的诊断、药品、检查或操作代码并返回患者教育资料；它不负责生成诊断，只支持英语和西班牙语。[Connect 定位](https://medlineplus.gov/medlineplus-connect/) [Connect Web Service](https://medlineplus.gov/medlineplus-connect/web-service/)
- Connect 的 `100 次/分钟/IP` 是同一来源 IP 每个物理分钟最多请求次数；超过限制时，官方可暂停服务 `300 秒`（5 个物理分钟）或直到请求速率降到限制以下，以较晚者为准。这些是服务容量参数，不是医学时限。文本 Web Service 的 `85 次/分钟/IP` 同理。[MedlinePlus Web Services](https://medlineplus.gov/about/developers/webservices/)
- PubMed E-utilities 可检索生物医学论文、系统综述和元数据；无 key 默认 `3 次/秒`、有 key 默认 `10 次/秒`，均是接口吞吐上限，不是证据质量分数。[NCBI E-utilities](https://www.ncbi.nlm.nih.gov/books/NBK25497/)
- PubMed 不评定单篇论文质量，也不把“检索命中”变成临床推荐。摘要和全文的版权不同，不能假定全部可长期复制进知识库。[NLM 数据版权说明](https://www.nlm.nih.gov/databases/download.html)
- **CAN 边界：** MedlinePlus 适合给主人解释，PubMed 适合发现和追踪文献；两者都不能单独作为某个诊断或安全动作的最终依据，且没有一致中文覆盖。

### 3.6 药品来源：标签可追溯，但没有现成综合相互作用闸门

- DailyMed 提供企业提交 FDA 的 SPL 药品标签和 v2 REST API，可按 SETID 读取版本历史，并有每日、每周、每月和完整数据包。[DailyMed API v2](https://dailymed.nlm.nih.gov/dailymed/app-support-web-services.cfm) [SPL 版本历史](https://dailymed.nlm.nih.gov/dailymed/webservices-help/v2/spls_setid_history_api.cfm)
- DailyMed 明确提示“当前使用标签”可能未经 FDA 核验，也可能不同于最新 FDA 批准标签；因此可以记录 SETID、SPL version 和发布日期，但“是否为 FDA 已批准产品/版本”必须另与 Drugs@FDA 或对应 FDA 权威来源交叉核验，不能由 DailyMed 单独推出。[DailyMed 边界](https://dailymed.nlm.nih.gov/dailymed/about-dailymed.cfm)
- openFDA Drug Label API 便于搜索 SPL 字段，但官方结果自带“不得依赖 openFDA 作医疗决策、结果应视为未验证”的声明；它只能作发现或交叉索引，不得成为用药安全唯一来源。[openFDA 结果声明](https://open.fda.gov/apis/drug/label/understanding-the-api-results/)
- RxNorm 提供规范药物术语，但 RxNav 的药物相互作用功能已于 2024-01-02 停用；因此不能把 RxNorm API 写成现成相互作用检查器。[RxNorm API](https://lhncbc.nlm.nih.gov/RxNav/APIs/RxNormAPIs.html) [RxNav FAQ](https://lhncbc.nlm.nih.gov/RxNav/information/FAQs.html)
- 国家药监局提供国产药品、进口药品及疫苗说明书等政务查询入口，但本轮没有找到面向普通药品标签、禁忌和相互作用的公开统一 API 合同。[国家药监局政务查询](https://www.nmpa.gov.cn/zwfwqjd/index.html?type=pc)
- **CAN 边界：** 标签来源能核验某一产品的适应证、禁忌、警告和相互作用段落，却不能自动形成覆盖中国市场、全部药物和组合的可靠相互作用引擎；“不建议擅自调整处方药”仍需要本地输出动作规则强制，而不能靠标签检索成功与否决定。
- 数值物理含义：`2024-01-02` 是 RxNav 相互作用功能停用日期；DailyMed 的每日/每周/每月是数据包更新频率，不是患者用药复查周期。

### 3.7 WHO SMART Guidelines：证明机器可读临床逻辑存在，但覆盖有限

- WHO SMART Guidelines 的 Digital Adaptation Kit 可包含业务流程、核心数据、决策支持逻辑、指标及功能要求；L3 Implementation Guide 可把特定领域规则表达为 FHIR 等机器可读规范。[SMART Guidelines](https://smart.who.int/) [DAK 说明](https://www.who.int/publications/m/item/who-digital-accelerator-kits)
- 当前公开目录覆盖孕产、计划生育、HIV、结核、免疫、特定儿童健康等领域，没有一个覆盖普通成人常见生理/心理问题、全部急症、自伤和全部药物安全的通用包。
- WHO Emergency Care Toolkit 面向医院急诊和一线卫生工作者；它证明急症知识有权威来源，但不是为聊天健康管家提供的通用机器判定 API。[WHO Emergency Care Toolkit](https://www.who.int/teams/integrated-health-services/clinical-services-and-systems/emergency-and-critical-care/emergency-care-toolkit)
- **CAN 边界：** 可借鉴结构与版本治理，并在特定已发布领域复用机器逻辑；不能把“WHO 有 SMART Guidelines”推导成当前已有完整健康管家规则库。

## 4. 急症、自伤和危险用药的规则边界

### 4.1 自伤与自杀：不能用单一分数证明“低风险”

- NICE NG225 明确要求：不要使用风险量表预测将来自杀或重复自伤，不要用量表决定治疗/出院，也不要用低、中、高全局分层作预测或准入；评估应聚焦当事人的需要以及即时和长期安全。[NG225 recommendations 1.6](https://www.nice.org.uk/guidance/ng225/chapter/recommendations)
- 国家卫生健康委《精神障碍诊疗规范（2020年版）》和《心理援助热线技术指南（试行）》包含自杀风险评估、危机支持和转介要求，但它们是面向专业诊疗/热线服务的叙述性规范，不是可直接导入的统一机器规则 API。[精神障碍规范](https://www.nhc.gov.cn/yzygj/c100068/202012/b4305ace9e14440792eb76d29602c88a.shtml) [心理援助热线指南](https://www.nhc.gov.cn/jkj/c100063/202101/74ada48ed1cd4e7f93c39db57cff0b4b.shtml)
- **CAN 约束：** 关键词、量表分数或一次模型分类不能证明“没有风险”。Ticket 50 若选择任何安全路线，必须保留来源不可用、规则未覆盖和判断不明的状态；具体采用哪些规则和怎样处置仍属于 HOW 与后续临床审查。

### 4.2 生理急症：没有覆盖全部成人场景的现成统一 API

- WHO Emergency Care Toolkit 和国家卫生健康委急诊相关指南列出系统性评估、急救、转诊和典型急症，但定位在卫生工作者和医疗机构。[WHO Emergency Care Toolkit](https://www.who.int/teams/integrated-health-services/clinical-services-and-systems/emergency-and-critical-care/emergency-care-toolkit) [国家卫健委急诊科指南](https://www.nhc.gov.cn/zwgkzt/pyzgl1/200906/41146.shtml)
- WHO SMART 机器逻辑只覆盖当前目录中的特定领域；本轮没有找到一个官方、中文、可机器读取并覆盖普通成人全部急症的统一决策包。
- **CAN 约束：** 当前没有现成统一规则包，也不能把关键词无命中解释成安全。具体规则集、专业审核和不确定状态的处置方式必须由 Ticket 50 选择并经原型验证；本票不预选其组成。

### 4.3 危险用药和处方药：标签事实与行为禁止是两层

- 药品标签可以提供具体药物的适应证、禁忌、警告和相互作用段落；没有已核验的中国市场全覆盖、权威、公开、实时相互作用 API。
- “不得独立建议开始、停止或调整处方药”是已经确认的产品输出禁令，不依赖某个相互作用数据库是否命中。固定工具能够表达确定性输出检查，但检查位置、规则表达和失败行为仍由 Ticket 50 选择并验证；数据库只提供药品事实，不能替代该禁令。
- 模型提出的药名、剂量或改变方案即使结构合法，也不等于医学正确；若要允许任何具体用药建议，仍需明确来源、适用人群、当前药物清单、剂量/单位和专业确认边界。

## 5. 目标 Hermes 的确定性强制构件

### 5.1 固定源码与当前现场

| 构件 | 官方/固定能力 | 2026-08-17 现场 | 医学边界 |
|---|---|---|---|
| Plugin Platform Adapter | Plugin 可注册 Adapter；已选路线允许在普通 Agent、正文去重和合批前拥有微信消息 | 目标没有已启用的健康 Plugin | 可以决定是否进入普通 Agent、是否调用模型、是否发送；框架不自动提供医疗规则 |
| `ctx.llm` | Plugin 自行构造输入，可请求结构化结果；不自动写普通 Session | Hermes v0.20.0 可用，未发 canary 请求 | 结构化候选仍是模型输出，不是医学真值 |
| Pydantic | Hermes 固定依赖 `pydantic==2.13.4` | `2.13.4` 可导入 | 可严格验证类型、枚举、必填字段和自定义不变量；不能验证诊断真实性 |
| `jsonschema` | Hermes 的 `complete_structured` 在包存在时做本地 schema 校验 | `4.26.0` 可导入，但不是 Hermes core 的直接固定依赖 | 能验证 schema 形状；format 默认并非全部强制，不能验证医学语义 |
| HTTP/YAML | 固定依赖 `httpx`、`requests`、`PyYAML` | 分别为 `0.28.1`、`2.33.0`、`6.0.3` | 能抓取正式 JSON/XML/文本接口和解析配置；不自带来源可信度 |
| HTML 解析候选 | 非 Hermes 固定核心能力 | `lxml`、`beautifulsoup4` 当前未安装 | 不能在 HOW 中假定无需新增依赖即可稳定抓取任意 HTML |

固定依据：

- Hermes v0.20.0 精确依赖包含 `pydantic==2.13.4`、`httpx[socks]==0.28.1`、`requests==2.33.0`、`PyYAML==6.0.3`。[固定 `pyproject.toml`](https://github.com/NousResearch/hermes-agent/blob/3c27eb6234bf91b8ceee9e9071591b31e9b148cb/pyproject.toml#L36-L62)
- `ctx.llm.complete_structured` 请求使用 `strict=false`；本地 `jsonschema` 存在时才校验结构。即使校验通过，也只证明 JSON 符合 schema。[结构化调用与本地校验](https://github.com/NousResearch/hermes-agent/blob/3c27eb6234bf91b8ceee9e9071591b31e9b148cb/agent/plugin_llm.py#L683-L773) [校验边界](https://github.com/NousResearch/hermes-agent/blob/3c27eb6234bf91b8ceee9e9071591b31e9b148cb/agent/plugin_llm.py#L897-L917)
- `jsonschema.validate()` 验证 instance 是否符合 schema；`format` 默认只是注释，未显式提供 FormatChecker 或缺少相应依赖时并不保证强制检查。[jsonschema 4.26 validation](https://python-jsonschema.readthedocs.io/en/v4.26.0/validate/)
- 通用 Gateway Hook 异常时继续正常分发；Middleware 回调在进入下游前异常也会继续下游，均不是医疗 fail-closed。[Gateway Hook](https://github.com/NousResearch/hermes-agent/blob/3c27eb6234bf91b8ceee9e9071591b31e9b148cb/gateway/run.py#L13355-L13396) [Middleware](https://github.com/NousResearch/hermes-agent/blob/3c27eb6234bf91b8ceee9e9071591b31e9b148cb/hermes_cli/middleware.py#L234-L292)
- 普通 Agent 可以不调用 Tool 直接形成文字回复，所以 `pre_tool_call` 无法兜底直接生成的诊断或用药文字。[普通 Agent 直接回复分支](https://github.com/NousResearch/hermes-agent/blob/3c27eb6234bf91b8ceee9e9071591b31e9b148cb/agent/conversation_loop.py#L5885-L5902)

软件版本号只用于绑定已核验行为，不代表医学内容版本、准确率或安全等级。

### 5.2 三个强制点能保证什么

下表只说明目标工具的可表达能力，不选择 Ticket 50 的最终实现：

| 候选强制阶段 | 若 Ticket 50 选择并实现，本地代码可检查的内容 | 不能由该检查证明的内容 |
|---|---|---|
| 模型前 | 主人/私聊准入、逐条来源是否存在；知识包是否有受信版本；是否出现已编入规则的明确危险信号；调用输入是否仅含必要字段 | 没有命中关键词不等于没有急症或自伤风险；规则集本身是否完整、医学正确仍需审核 |
| 模型后 | JSON 类型、必填字段、枚举、来源 ID 是否存在于准入清单；是否出现被明令禁止的处方药动作；是否携带反证、缺失信息与不确定性字段 | schema 合法不等于诊断正确；引用存在不等于引用支持该结论 |
| 发送前 | 只接受已通过本地校验的结构；拒绝未审查自由文本、未知引用、被禁动作；任何异常时不提交画像结果、不发送诊断/用药建议 | 不能自行判断遗漏的医学事实，也不能证明微信最终显示给主人 |

由固定源码可以推断：健康 Plugin 自有 Adapter 若不调用普通 handler、不接受模型候选且不调用发送接口，普通 Agent 不会替它自动完成这次健康回复。因此“异常时不放行”在受支持扩展面内可实现。该判断是对扩展控制流的推断，不是 Hermes 官方提供的医疗安全保证；当前目标没有实现或 canary 证据。

## 6. 来源更新、引用与接收方边界

- 国家卫生健康委《医疗机构临床决策支持系统应用管理规范（试行）》要求临床知识来源具有权威性，知识库及时更新且更新周期一般不长于半年，保留审核流程与审计日志。[CDSS 应用管理规范](https://www.nhc.gov.cn/yzygj/c100068/202307/d5239ed63d324aaa8ea85922b5fb1310.shtml)
- `半年`在该规范中是医疗机构 CDSS 知识库的一般最长更新周期，物理含义约为两个季度；它不是本项目自动适用的法律结论，也不是主人复盘或临床随访频率，但可以作为后续知识治理候选基准。
- 上述接口分别提供可用于建立追溯合同的候选字段，例如发布机构、文档/指南编号、版本或发布日期、章节/推荐编号、语言、原始 URL/URI、内容哈希、PMID/DOI、勘误或撤稿状态；最终必填字段和失效规则由 Ticket 50 选择，不能由本票直接宣布合同已经建立。
- WHO ICD 云 API、NICE、PubMed、MedlinePlus、DailyMed/openFDA 都可以用代码、药品标识或主题查询，但“去掉姓名”不自动等于没有个人健康资料。只要 query 由主人画像、症状、疾病代码或用药事实派生，就先按潜在新增健康数据接收方处理，因为这些官方接口没有为本项目承诺 PHI 合同、无日志或 BAA。只有预先下载的通用语料，或与任何主人事实无关的通用查询，才可以明确不外发主人健康资料。
- 本地部署或受控快照可以降低逐次外发和可用性风险，但会新增下载、许可、版本同步、撤回处理和完整性验证责任。当前目标没有安装 WHO ICD 本地服务、NICE key、医学知识快照或来源更新任务。

## 7. 五层证据与尚未完成的实验

| 层级 | 当前结论 |
|---|---|
| 官方保证 | 上述 WHO、NICE、NLM、FDA、NHC 来源的公开用途、接口、版本、语言和许可边界；Hermes Plugin/`ctx.llm`/Adapter 的官方接口合同 |
| 固定源码行为 | Hermes 结构化调用 `strict=false`、可选本地 schema 校验；Hook/Middleware fail-open；普通 Agent 可不经 Tool 直接回复；Plugin Adapter 保留自有控制流 |
| 目标现场已验证 | 2026-08-17 16:03:20 +08 的 v0.20.0/commit；Pydantic、jsonschema、httpx、requests、PyYAML 可导入；lxml/BeautifulSoup 未安装；没有已启用的非 bundled 健康 Plugin；Partner service active/enabled |
| 尚未验证 | 任何候选接口从目标主机的真实连通性、延迟和错误语义；NICE 许可/key；WHO/NICE/NHC 的本项目最终许可；中文常见病覆盖完整度；知识更新监测；具体规则的医学正确性；Plugin 三段强制闭环 |
| 必须另行取得主人批准 | 注册或购买外部服务、接受许可证、安装依赖或本地知识服务、创建 canary Plugin、发送模型/微信请求、用真实健康资料测试、故障注入、目标配置/服务修改 |

没有执行真实请求不能写成“接口失败”；没有安装健康 Plugin 也不能写成“Plugin 方案失败”。当前只证明候选合同、固定控制流和目标依赖是否存在。

## 8. 对 Ticket 50 与后续生命周期的结论

### 8.1 已查清事实与未解锁原因

- 有可逐版本引用的术语/编码接口（WHO ICD-11 MMS，含中文）。
- 有具体、权威的临床内容候选（WHO CDDR/mhGAP、具体 NICE 指南、具体 NHC 指南），但其语言、许可和接口能力不同，必须按职责而非混成一库。
- 有患者解释、文献发现和药品标签候选，但它们不能越权充当诊断规则。
- 目标现场有结构校验、HTTP 获取、YAML 配置和 Plugin 自有控制流构件；模型前、模型后和发送前的检查在受支持扩展面内具有候选实现空间，不需要第二 Agent、独立 LLM Gateway 或独立 provider，但当前尚未实现或验证。
- 固定扩展面保留了“知识/规则不可用、版本不受信、校验异常或结果不确定时不提交候选结果”的实现路径，但当前现场没有医疗规则、校验器、统一发送出口或 canary，尚未证明端到端失败关闭。

因此 Ticket 59 可以以**负向 CAN 结论**解决：候选职责、接口与强制构件已经查清，但当前没有一套生产来源合同同时闭合中文诊断内容、许可、版本和目标可用性。Ticket 50 仍不得开始；它必须先等待新建的 TO-CAN 差距决策，明确是否保持辅助诊断目标并允许增加来源许可、中文内容清单和专业审核依赖。

### 8.2 仍不是生产能力，后续必须闭合

- 最终生产来源清单、许可/key、中文覆盖和更新责任人尚未确定；这不是普通实施细节，而是当前阻塞 HOW 的能力缺口。
- 没有一个现成来源覆盖全部成人生理/心理诊断、急症、自伤和中国市场药物相互作用；具体规则包必须经过专业审查，且“无规则命中”不得等同于安全。
- Pydantic/jsonschema 和引用 allowlist 只能验证合同，不验证医学真伪。诊断质量、引用支持关系、遗漏风险和危险场景必须用合成病例、对抗输入、来源失效、校验异常和发送中断做 Prototype/验收；任何真实主人健康或微信实验仍需单独批准。
- NICE/API key、商业或 AI 再利用许可、WHO/NHC 翻译/改编/再发布、医学专家审核和目标连通性属于后续实施依赖或 No-Go，不得在 HOW 中写成已具备。

当前差距不是 Hermes 扩展面绝对无法实现，而是**尚无已获准、足够中文且可作为生产诊断内容的来源组合**。因此先创建 TO-CAN 差距票，由主人决定是否保持既定辅助诊断目标，并授权把内容许可/采购、逐病种中文来源清单和专业审核纳入上线硬依赖；若不接受这些依赖，只能显式降低诊断目标或停止路线，不能静默使用无许可或未经审核的资料。
