# 【HOW】选择健康画像数据平面、模型调用与保护路线

Type: grilling
Status: resolved
Parent: [健康管家首发 TO、CAN 与 HOW 决策闭合路线](../map.md)
Blocked by: [【HOW】选择健康管家在 Hermes 中的单一执行与权威路线](47-choose-hermes-health-execution-and-authority-route.md), [【HOW】选择微信接入、主人授权与逐次来源路线](48-choose-channel-identity-and-provenance-route.md), [【CAN】核验健康画像数据平面的可用工具与接口](56-verify-health-data-plane-tools-and-interfaces.md), [【CAN】核验健康模型调用与全部实际接收方事前锁定能力](57-verify-health-model-routing-and-recipient-preflight-capabilities.md), [【TO】决定健康模型接收方锁定缺口下的产品承诺边界](58-decide-health-model-recipient-lock-gap-boundary.md)

## Question

在直接 CAN Research 已核验的目标 Hermes v0.20.0、目标运行环境和可用工具/接口内，选择健康 Plugin 的具体数据平面路线：怎样使用已验证可用的 SQLite、`cryptography`、文件系统权限和 Hermes Plugin 接口承载同一健康画像、主人控制状态与逐次处理状态；怎样通过已验证的 `ctx.llm` 调用同一 Hermes 当前配置的模型服务路线，同时阻止健康内容进入普通 Session、Memory、全文索引、普通日志和通用备份；怎样检测首跳模型服务路线的配置变化，并用实际可用的事务、密钥、备份恢复与删除机制落实既定主人权利。只选择实现工具、接口、数据流和故障边界，不重新讨论七域画像、纠正权、模型服务内部路由、永久删除或其他 TO。

## Comments

### 2026-08-17 — Claimed and CAN baseline

本票已认领。既有 CAN 已排除把普通 Hermes `state.db`、Session、Memory、`USER.md`、普通日志或通用备份当成健康画像：这些路径会保留完整对话或进入普通模型上下文，也没有健康画像、来源、主人权利、删除和接收方同意语义。正式健康 Plugin 可以自行拥有受保护的事务状态，但目标 Hermes 不提供现成的健康 schema、事务、加密、密钥、备份或数据权利合同。

因此后续路线只在同一个 Hermes 的健康 Plugin 内建立一处专用受保护状态域；历史证据、当前理解、主人控制状态、逐次接收登记和临时处理状态是不同职责，不是多份健康画像。具体数据库产品、字段、加密算法和固定时间参数属于后续 Spec/依赖核验。本轮先确认运行时信任边界、纠正历史、实际数据接收方，以及临时内容和导出副本的生命周期；这些答案闭合后再选择存储、密钥、备份和永久删除的根路线。

### 2026-08-17 — Recharted: HOW paused for direct CAN

主人指出本票虽然名义上已经进入 HOW，我提出的问题却仍在询问纠正历史、接收方同意和删除副本等产品承诺；这混淆了 TO 与 HOW。该判断成立。上一段末句及本轮提出但尚未回答的 Q1–Q4 不构成决定，也不进入未来 `## Answer`。

既有“核验健康档案、数据权利与保护能力”只证明健康 Plugin 有自行实现状态的扩展空间，并排除普通 Session/Memory 作为画像权威；它没有核验到足以选择具体 HOW 的工具和接口粒度。当前 claim 已释放，本票改为只选择已验证可用的事务存储、加密/密钥、Plugin 数据路径、普通历史隔离、接收方预检和备份/删除机制，并等待新的直接 CAN Research 子票。

### 2026-08-17 — Recipient CAN remains open

Ticket 56 已闭合其数据平面研究问题，但得到的是一项负向 CAN：当前没有已验证的正式接口同时满足“健康内容不进入普通历史”与“发送前锁定全部实际模型接收方”。因此本票仍不认领、不进入 HOW，并继续阻塞于新的接收方路线 CAN Ticket 57。若 Ticket 57 仍找不到符合既定 Hermes 架构与 TO 的路线，应先创建 TO-CAN 差距决策，不能在本票中降低接收方同意边界。

### 2026-08-17 — TO-CAN gap opened

Ticket 57 已用负向答案确认不存在符合当前边界的受支持路线。本票继续保持未认领，并新增阻塞于 TO-CAN Ticket 58；只有主人明确决定保持哪些产品承诺以及是否扩大技术边界后，才能继续 HOW。

### 2026-08-17 — TO-CAN gap resolved; HOW resumed

主人通过 Ticket 58 明确：健康 Plugin 沿用同一 Hermes 当前配置的模型服务路线及其正常路由与故障切换，不要求在发送前锁定或枚举 JOJO 内部最终模型；只有 Hermes 改为另一条首跳模型服务路线时才重新告知并取得同意。Ticket 57 的负向 CAN 事实继续保留，但不再阻塞本票。固定源码已证明 `ctx.llm` 不会自动写入普通 Session/Memory，因此它可以作为同一 Hermes 的候选模型调用入口；端到端日志、入站与备份隔离仍须由本票完成 HOW 选择和后续验证。本票恢复为未认领的 HOW frontier，只从 Ticket 56 已证实的 SQLite、`cryptography`、OS 权限、Plugin 接口、`ctx.llm` 与备份事实中选择路线。

### 2026-08-17 — Claimed for HOW selection

本票现已认领。后续只从已完成 CAN Research 证明可用的目标 Hermes v0.20.0 接口、SQLite、`cryptography`、文件系统与 systemd 能力中选择具体数据平面路线；不重新询问健康画像、主人权利、永久删除或模型接收方等已闭合 TO。

### 2026-08-17 — Grilling Round 1: data-plane root route

直接 CAN 已把可行根路线收窄为同一健康 Plugin 自有的一处专用状态域：使用目标现场已验证的标准 SQLite 承载逐次接收登记、同步游标、同一健康画像、主人控制、任务和处理结果；使用已安装的 `cryptography` 在写入前对健康正文与模型输入输出做认证加密；数据库、密钥和健康备份均与 Hermes 普通 `state.db`、Session、Memory、全文索引、普通日志和通用备份隔离。密钥由 systemd/OS 的专用凭据路径注入，不进入数据库、`.env`、模型上下文或备份。

数据流采用两段短事务：第一段把每次微信接收登记与新同步游标共同持久化后才接管该批消息；随后在事务外通过 `ctx.llm` 使用同一 Hermes 当前配置的模型服务路线完成推理；第二段共同提交画像变更、补问任务、最终处理状态与待发结果。模型调用不得占用数据库事务，也不得经过会把参数或结果写入普通历史的普通 Agent Tool 路径。首跳变化只检测 Ticket 58 已确认的持久 Hermes 路由配置边界；现有接口不能预览服务内部的实际 fallback，且主人已经确认无需锁定该内部路线。

备份使用 SQLite 一致快照后再认证加密的 Plugin 专用备份，不使用 Hermes 未加密的通用 ZIP。永久删除按既定 TO 覆盖全部受管健康内容、临时内容、待发内容、服务器临时导出和 Plugin 专用备份，并使 Plugin 不再取得该画像的密钥；只允许保留不能重建健康内容的最小同步位置、接管状态和防旧数据复活标记。站外备份落点、备份频率、宿主/云快照清单、恢复演练和删除验证仍是后续实施与验收 No-Go，不在本票中冒充已具备。

已排除普通 `state.db`/Memory/Tool transcript、普通 JSON/Markdown 多文件状态、目标现场未安装的 SQLCipher/keyring、`.env` 密钥、Hermes 通用备份、私有模型 client，以及新增 Agent、sidecar、provider 或 LLM Gateway。待主人确认是否接受上述整体根路线；字段、算法参数、路径细节、备份频率和验收脚本随后进入 Spec、实施依赖与验收方法，不逐项作为产品取舍重新询问。

## Answer

主人确认采用一条由同一健康 Plugin 独占的数据平面路线：在 Hermes 普通数据目录之外维护一处专用 SQLite 状态域，统一承载逐次接收登记与同步游标、同一健康画像的来源历史和当前理解、主人控制状态、补问及主动支持任务、模型处理状态和待发结果。上述只是同一画像及其处理职责的内部划分，不形成第二份画像或第二个运行权威。

所有健康正文、画像证据与推断、任务正文、模型输入输出、临时内容和待发正文均须在写入前由目标现场已安装的 `cryptography` 做应用层认证加密；数据库、密钥和专用备份彼此分离。密钥通过 systemd/OS 的专用凭据路径交给健康 Plugin，不进入数据库、Hermes `.env`、普通 Session/Memory、模型上下文、日志或备份；密钥缺失、无效或无法确认时，健康处理失败关闭。具体认证加密算法、密钥派生、文件路径与权限值留给 Spec 和依赖验证，但不得退回仅依赖文件权限的明文存储。

每批微信入站先以一个短事务共同提交每次接收登记、可用来源、受保护临时内容和新的同步游标；任何一项失败则整批不接管并保留旧游标。模型推理在事务外经 `ctx.llm` 使用同一 Partner Hermes 当前配置的模型服务路线，不经过会把参数或结果写入普通历史的普通 Agent Tool 路径。推理完成后再以一个短事务共同提交来源与画像变化、任务变化、最终处理状态和加密待发结果；不得在外部模型调用期间占用数据库事务，也不得出现画像已变更但任务或结果仍声称未提交的半完成状态。

健康 Plugin 只核对 Ticket 58 已确认的持久首跳模型服务配置边界；该边界改变或无法读取时暂停新的健康处理并重新告知、取得同意。现有 Hermes 接口不能预览 Hermes 宿主的实际 fallback 或模型服务内部下游，主人已经确认当前 Hermes 路由及其正常故障切换无需逐次锁定，因此不得把实际路由预览伪装成已实现能力。

普通 Hermes `state.db`、Session、Memory、`USER.md`、全文索引、普通 Tool transcript、受健康 Plugin/Hermes 控制的本地普通日志和通用备份均不得承载健康正文或画像内容；provider/relay 的外部留存继续遵循 Tickets 57、58 已确认的边界，不在本票中冒充可控。健康日志只保留不含正文的接收/处理标识、状态与错误类别。处理进入可证明终态后清除完整临时聊天和模型草稿，只保留进入同一画像所必需的最小证据、来源、时间与结论；服务器临时导出在交付后清除。

备份由健康 Plugin 使用 SQLite 一致快照生成并在写出前认证加密，不使用 Hermes 未加密且没有 Plugin 删除合同的通用 ZIP。主人永久删除画像时，先停止新的健康读写、复盘和主动发送，再清除全部受管画像内容、临时内容、任务、待发内容、服务器导出和 Plugin 专用备份，并使健康 Plugin 不再取得该画像的密钥；仅可保留不能重建健康内容的最小同步位置、接管状态和防旧数据复活事实。不得在相应清除和验证完成前宣称删除成功。

本票只锁定上述工具、接口、数据流和故障边界。数据库 schema、认证加密参数、凭据与恢复接线、专用备份落点和频率、宿主或云快照清单、恢复演练、删除验证及具体测试脚本仍属于后续 Spec、实施依赖与验收方法；它们当前尚未部署或验证，不能由本答案冒充为已具备。依据见 [Ticket 56](56-verify-health-data-plane-tools-and-interfaces.md)、[Evidence 10](../evidence/10-health-data-plane-tools-and-interfaces-20260817.md) 与 [Ticket 58](58-decide-health-model-recipient-lock-gap-boundary.md)。
