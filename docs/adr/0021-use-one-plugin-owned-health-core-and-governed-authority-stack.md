# 用一个 Plugin 私有 Health Core 统一入口、状态、模型、安全与运行

> 状态：已确认。本文是健康管家当前统一 HOW 权威；较早的局部 HOW 与 ADR 只保留为历史事实和约束输入。

## 背景

[完整首发健康管家产品合同](../../.scratch/partner-health-steward/issues/75-close-first-release-health-steward-product-contract.md)已经固定：产品仍是同一个 Partner Hermes 中的一项健康 Plugin，只服务唯一主人；初始化成功后才启动；以紧凑六域画像、三类证据、开放健康任务、每日复盘、主人控制、范围内辅助诊断与真实三态结果共同工作。[完整 CAN 报告](../../.scratch/partner-health-steward/evidence/28-complete-current-capability-and-constraint-report-20260820.md)又证明了可实施原语和必须避开的反例，但没有选择最终组合。

旧路线把入口、画像、任务、模型、安全、删除和状态分散到多个决定中，且存在四个不能继续继承的事实：Hermes 通用 Plugin/Hook 失效时会继续主体；内置微信在健康接管前可能去重和合批；现有 `ctx.llm` 不能证明实际首跳、容量和完整终态；旧 sidecar 把健康状态分散到多库、多文件、明文投影和不完整恢复面。当前路线必须让这些失败在同一个权威链中传播，不能再靠调用方自行拼装。

## 决定总览

选择“**一个健康 Plugin 产品入口 + 一个 Plugin 私有本机 `health-core` + 一份本地受管 SQLite 内容状态 + 一个域外强一致当前头 + 一个严格 Hermes 模型接口**”的路线。

```text
唯一主人微信 iLink
        │
        ▼
health_weixin Platform Adapter ── 明确非健康 ──► 普通 Partner Agent
        │ 健康 / 混合 / 无法排除健康
        ▼
Partner Health Plugin（准入、协调、模型和微信 Adapter）
        │ 受限本机 socket interface
        ▼
health-core（唯一状态写入者、规则裁决者、任务与 outbox 权威）
   ├── 受管 SQLite：画像、证据、任务、控制、诊断、交付与历史
   ├── 不可变产品 / 医学 / Skill release manifest
   └── DynamoDB 单区域强一致 current head：代际、摘要、writer fence、终止态
        ▲
        │ ModelWorkOrder / terminal result
StrictHealthLLM（同一 Hermes 当前首跳，无跨首跳 fallback）
        │
        ▼
主人已同意的首跳模型服务路线
```

`health-core` 不是第二个 Agent、第二个人格、独立 LLM Gateway 或独立健康产品。它没有主人入口、微信凭据、普通对话、模型供应商配置或自主行动定时器，只通过健康 Plugin 的受限本机 interface 接收命令并返回确定性结果。它与 Partner Gateway 由同一运行目标管理；Gateway 停止后它不能发消息、调用模型或推进任务。把它放在独立低权限进程中，是为了让 SQLite、画像密钥、事务和迁移状态不进入包含普通 Agent 的 Gateway 进程。当前以 root 且无 sandbox 运行的 Gateway 本身也是部署 No-Go；最终 Gateway 和 core 必须分别使用专用非 root 身份、最小目录/能力与不同凭据边界。

## 一、运行拓扑与小 interface

健康 Plugin 对主人仍是唯一产品模块；`health-core` 是其私有深模块。Plugin 与 core 之间只保留三类稳定 interface：

1. **健康操作**：提交逐次入站、主人控制、自然日唤醒或迁移命令，并携带可信来源、因果标识、当前代际和允许作用域。
2. **受控效果**：core 返回待执行的模型工作或微信投递意图；Plugin 回交模型完整终态或投递结果。模型调用和外部发送永远不能直接写业务状态。
3. **受管读取**：按主人权利返回当前画像、任务、导出和状态；迁移只取得经 manifest 枚举的语义快照。

生产使用权限受限的本机 socket Adapter；测试使用内存 Adapter。复杂性留在 core 内部，不把数据库表、规则引擎、模型 transport 或任务状态机暴露给调用者。四项职责、Skill、Command、调度唤醒和模型候选都只能通过这三个 interface，删除这个模块就会迫使全部权威规则散落到每个调用点，因此这个 seam 是真实且必要的。

Hermes 通用 Hook、Middleware、`pre_gateway_dispatch` 和提示词不承担失败关闭。健康 Plugin 加载失败、core 不可用、当前代际无法证明或 contract probe 失败时，健康入口不可用；普通 Hermes 是否继续运行不能被解释为健康管家可用。

## 二、唯一微信入口、初始化与能力入口

首发注册唯一自定义 `health_weixin` Platform Adapter，并显式禁用内置 `weixin`、Telegram 和其他人类健康入口。iLink 凭据和唯一 allowlist 只交给 `health_weixin`，不放到内置微信能够自动读取的普通配置中。这样 Plugin 未加载时 `health_weixin` 根本不存在，禁用且无凭据的内置微信也不能接管；启动与持续探针仍验证 Plugin、Adapter、core、密钥和当前代际，但探针不再是防回退的唯一手段。

`health_weixin` 在内置正文去重、合批、普通 Session 和模型之前接住每个原始 envelope。它把每次投递的可用来源、字段缺失和独立接收时间交给 core；core 在同一受管提交中登记整批 receipt 与 cursor。长期 receipt 只保留渠道/发送者技术标识、消息标识、协议时间与接收时间、字段存在性、带密钥摘要和处理状态，不保存正文、媒体或完整 envelope；正文和媒体只进入加密短生命周期处理区，完成准入、拒绝或结果提交后清除，获准长期存在的内容只进入最小证据卡。提交未完成就不推进 cursor，也不产生画像、任务、诊断或回复。重复或重投歧义保留两次来源，但在消歧前只允许一个健康业务效果；危险检查不等待消歧。

初始化采用一个 `health-init` Skill 加确定性初始化命令。Skill 只保存可检查的说明，Adapter 直接呈现和推进流程，不依赖模型加载 Skill。明确同意前不持久保存健康正文；同意后允许把渐进初始化内容放进加密 pending draft，但 pending draft 不是画像、证据或可用健康状态。只有披露版本、明确同意、首跳同意、时区、行为和通知偏好、初始画像、密钥、当前头及本地状态全部完成 prepare—CAS—finalize 后，唯一启用状态才成立；中断、取消或结果未知均不得启动健康处理，pending 健康内容按初始化合同清除。

初始化前除确定性初始化入口外，所有消息按基础 Hermes 自己的合同处理；健康 Plugin 不识别、记录或倒填其中的健康内容。初始化后，Adapter 先做受管分流：明确非健康才进入普通 Agent；健康、混合或无法排除健康影响的整条消息只进入健康协调器。分流无法完成时不回退普通 Agent。

能力入口固定如下：

| 主人或系统目的 | 可见入口 | 最终权威路径 |
|---|---|---|
| 初始化 | `health-init` Skill、Adapter 自己处理的显式初始化命令或明确初始化短语 | Adapter → core 初始化状态机 |
| 健康询问、个人陈述、画像更新候选 | 自然语言；`health-steward` Skill只解释用法 | Adapter → HealthCoordinator；新陈述先成为候选证据 |
| 查看/导出画像、查看/延期/调整/取消任务 | 自然语言与 Adapter 自己处理的显式健康命令 | core 的受管读取或任务命令 |
| 设置行为、暂停支持、停止记录、撤回批准 | 自然语言与 Adapter 自己处理的显式健康命令 | core 的独立控制命令；互不替代 |
| 永久删除 | 明确删除命令或无歧义自然语言请求 | core 的终止代际协议；不由普通 Agent 执行 |
| 查看运行状态 | 自然语言或状态 Command | core 的业务状态投影，不读进程心跳冒充活跃 |
| 每日复盘、到期任务、文献更新 | Hermes 调度只发 wake-up；知识发布另走离线治理 | core 自然日账本；KnowledgePublisher 无主人数据 |

包内保留一个主人可发现的 `health-steward` Skill、一个 `health-init` Skill，以及画像维护、证据维护、主人询问、文献查找四份只读职责 Skill。后四者只生成受约束候选，不拥有数据库写权限；任务框架是 core 代码，不是第五个内容权威。首发不向普通 Agent 注册可直接读写健康状态的 Tool、Plugin Command 或通用 API；显式 `/health-*` 形式由 `health_weixin` Adapter 自己解析，内部自动流程使用受限的健康操作 interface。模型没有选择 Tool 时也无法绕过，因为健康消息在普通 Agent 之前已经被 Adapter 收敛。

## 三、单一权威状态、加密与当前头

`health-core` 是唯一物理写入者。一个受管 SQLite 状态域统一承载：逐次 receipt/cursor、初始化、六域画像、三类证据卡、任务与阶段、批准/撤回、主人控制、自然日复盘、模型候选处理状态、诊断修订、未知外部效果、加密 outbox、交付分层、运行状态事实、迁移与删除状态。持久审计同样在这个状态域中保存不含正文的事件，不再写独立 JSONL、第二套 delivery DB 或明文 projection。

健康正文和可重建个人健康内容使用标准认证加密后才进入 SQLite、WAL、临时区、导出或专用备份；不自制密码算法。每位主人使用独立数据密钥，密钥由 OS/systemd credential seam 注入 `health-core`，不进入 `.env`、普通 Session/FTS/Memory、日志、模型提示或备份。SQLite 清晰列只保存无法单独重建健康内容的状态、标识和索引。模型工作内容只在内存和受保护短生命周期临时区存在；最终候选被接受或拒绝后清除，完整 prompt、模型输入输出和完整回复不长期保存。

画像顶部当前状态、六个固定一级领域与全部固定基础二级主题由版本化 `PortraitSchemaRelease` 表示；空主题明确未知。二级主题扩展先写主人批准事件，再激活新 schema release。证据库先按个人健康证据、通用权威知识、任务过程证据三类分开，再按相同六域索引到最小证据卡。每项证据只有一张权威卡；画像当前关系、任务和诊断修订只引用卡及其版本，不复制正文。发生时间、记录时间、来源、用途、不确定性、支持/反对/限制、纠正、撤回、失效和后继属于证据卡或关系，不堆到每条画像摘要中。AI 每次只取得省略后会实质改变当前目的的卡。

为防旧 VM、旧备份或迁移源重新成为当前，选择**单区域 DynamoDB 强一致 item + 条件事务/CAS**作为域外 current head。它只保存随机安装标识、业务 generation、SQLite 当前 revision 的不透明摘要、transition id、writer fence/active site、永久终止标志，以及不含健康正文的 contract-probe heartbeat sequence/lease；不保存主人身份、健康正文、画像、凭据或可反推出内容的值。资源身份固定，资源缺失或同名重建绝不能当作首次初始化。`health-core` 是 current-head 与 heartbeat 的唯一写入者：Plugin 只通过本机 interface 回交 contract-probe 结果，core 验证完整探针和当前 fence 后才条件更新 heartbeat；该更新不改变业务 generation，也不能单独证明产品“活跃”。

每次改变权威状态都使用短协议：SQLite 写入不可见 prepared revision → DynamoDB 以预期旧 generation/digest 条件推进 current head → SQLite 把同一 transition finalize 为可见当前。网络结果未知时按 transition id 强读回查，不猜测成功或失败；本地 finalize 只接受远端已经选中的 digest。该协议不冒充跨 SQLite 和 DynamoDB 的单事务，而是把中间状态显式隔离。任何健康读取、写入、诊断或外部效果开始前都必须强读并证明本地 finalized revision 与当前 head/fence 一致；没有 current head、条件失败或回查失败时，相关健康能力停止并显示“无法确认”，旧源或旧 VM 也不能借“只读”继续披露旧画像。永久删除仍可先冻结并清理当前本地内容，但在远端终止态无法确认时不得声称全部防复活结果已经完成。

选择 DynamoDB 而不选择本地 tombstone、WORM 或条件对象 current-head，是因为当前证据已经证明它有强读、条件更新、事务和结果未知回查所需原语，并且目标栈已有 SDK 构件。实际 AWS 账号、单一区域、表、资源身份、最小 IAM、费用、配额、credential 注入和合成 old-snapshot canary 都是后继实施与验收硬门槛；未完成或未通过时整条健康路线不得激活，也不得宣称完整首发。此选择不扩大到抵抗恶意 guest root 或 AWS 账号管理员。

## 四、任务、复盘、投递、控制与三态

TaskEngine 逻辑拥有任务目的、承担者、允许资料/接收方/外部效果、阶段、验收、四标签和前后继；HealthCoordinator 统一提交。画像维护只能提出画像关系，证据维护只能提出证据准入/拒绝/撤回/失效，主人询问只能提出最小非诱导问题，文献查找只能提出通用资料候选。四者不能自行建档、改验收、标 `solved` 或产生外部效果。

任务只有 `active / solved / failed / cancelled` 四个主标签；等待、延期、能力缺口、单步失败和外部结果未知是附加事实。接口 accepted、Cron completed、提醒已尝试或资料已找到都不能成为 `solved` 或健康改善证据。终态不原地重开；新证据或新目标建立带关系的后继任务。

Hermes Cron、Plugin tick 和启动恢复只唤醒 core。真正的每日复盘以“主人当前 generation + 当前时区下当地自然日”为业务账本键：同日只提交一次最终复盘；无变化也记录“已复盘、无需通知”。停机恢复只按当前当地日和当前画像重判，不补历史积压。计算和模型调用在事务外完成，最终以 revision 和 control 前提一次提交画像/任务变化、复盘结论和加密 outbox。

业务状态与 outbox intent 在同一 SQLite revision 中提交，微信发送在事务外进行。权威事实严格分为：结果形成、业务提交、发送尝试、接口接受/拒绝/未知、主人实际到达是否已证明。可能已发出的效果进入 `unknown` 并冻结自动重试，原任务通常保持 `active + unknown`；主人承担重复风险后才能建立新的重试 attempt，原 unknown 不被擦除。

五类普通通知分别是新任务、普通阶段变化、关心/提醒、任务终态和复盘摘要；各自偏好只控制主动发送，不改变任务事实。危险升级、曾影响主人的必要纠错、全局离开/恢复活跃以及一次新增授权/未知重试/关键能力缺口行动请求不可被普通偏好吞掉，但都以因果事件防重。

主人控制互不替代：暂停主动支持只停普通主动询问、关心和提醒；停止新增记录后仍可临时回答主人主动问题和执行危险处置，但不长期写入新的个人证据、画像、诊断、安全事件或新任务，依赖新资料的旧任务保持等待，恢复记录后也不倒填停止期间内容；取消任务只停止该任务未来阶段；撤回批准阻止未发动作并冻结在途/未知后继；永久删除作用于全部受管对象和副本。正常控制状态单独显示，不被错误聚合成系统故障。

StatusProjector 只从入口、初始化、密钥/状态、画像证据、任务控制、复盘、投递、模型路线、安全、问答、诊断范围和 current head 的业务事实派生“活跃、异常、无法确认”。`活跃` 要求所有核心能力已确认正常且至少一个诊断范围有效；最后一个范围确认失效为异常，是否仍有有效范围无法证明为无法确认。进程、Gateway、Cron 或 observer 活着只能提供 liveness 证据，不能独立宣称活跃。

异故障域 observer 只读取 current-head 的无正文 heartbeat，并且只向独立、无正文的 observation partition 条件追加单调编号的 observation record；它是这些 record 的唯一写入者，但没有 SQLite、任务、画像、outbox 或主人通知权限。每条 record 只保存 observation sequence、观察时间、所见 generation/fence 与 `missing / recovered`，不能决定产品状态；不同事件不得互相覆盖。Plugin/core 恢复后，core 从 SQLite 已消费序号之后强读这些 record，经 HealthCoordinator 验证 current head 后，由仍是唯一 SQLite 写入者的 core 按序提交观察事实、已消费序号、StatusProjector 转态和防重通知 outbox；observer 自己永远不能宣称“活跃”或发送健康结果。Gateway 不可达期间的离开活跃事实由 observer 保留，恢复后离开与恢复事件分别按因果键最多尝试一次，不冒充故障当时已经送达。

DynamoDB 最小权限明确分开：Plugin 不持有 DynamoDB 凭据；core 凭据只允许对固定 current-head item 做强读/条件写，并对固定 observation partition 做强读；observer 凭据只允许强读固定 current-head item，并向固定 observation partition 条件追加。两者都不能枚举或访问其他安装、其他表或健康内容。

## 五、严格模型、查询隔离与非诊断问答

现有 `ctx.llm` 不进入最终健康链。选择为锁定 Hermes 版本增加一个很窄的 `StrictHealthLLM` host interface：它仍使用当前 Partner Hermes 的同一模型配置、凭据和主人已同意首跳，不建立独立 LLM Gateway、第二 provider 配置或健康 Agent。它从实际运行配置解析 provider、canonical base URL、API mode 和配置 generation；每次发送前与初始化时保存的同意指纹比较。跨 provider/base URL/gateway fallback 全部关闭；同一首跳服务内部不可枚举的正常路由与容灾仍按 TO 处理。

该 interface 必须在一处同时补齐四项能力：

1. 从最终 wire payload 计量，不附带普通 Session、完整会话、隐藏 Agent prompt 或 Tool；
2. 显式发送真实输出上限与严格结构格式，诊断和问答使用非流式调用；
3. 原样返回 response id、请求/实际 model、`completed / incomplete / failed`、不完整原因、usage 和宿主 fallback 事实；只有权威 `completed` 才可进入校验；
4. 激活一份绑定“首跳指纹 + 请求模型 + host interface 版本”的容量能力清单，包含可证明的共同上下文下限、固定包装开销、经验证的 tokenizer 或保守上界算法、输出预留和失效条件。

调用前先形成最终 wire payload，再证明必要输入上界与输出预留都在能力清单内。静态 `240000`、粗估 token、卡片数量、事后 usage、`stop` 或“留很大余量”都不是证明。放不下全部必要证据、冲突、安全事实、医学规则和输出预留时不删卡、不静默摘要、不自动分块，直接拒绝形成诊断；安全分支只有在自己的资料和规则独立完整时才继续。

健康运行时只有三个允许的外部方向：主人已同意的首跳模型路线、微信 iLink，以及不含健康正文的 DynamoDB current-head/observation resources。模型调用为 no-tools；Web Search、MCP、普通 Tool 和任意 HTTP 不可从主人健康操作触发。医学与一般健康资料由独立 `KnowledgePublisher` 按与任何主人无关的固定治理计划离线获取，产出带来源、版本、许可、中文、审核和 hash 的 staged release；publisher 没有画像、消息、任务、密钥或 outbox 读取权。缓存缺失或过期时只形成知识缺口，绝不按主人问题临时回源。

非诊断问答使用当前问题、必要个人证据、明确标记的本轮候选陈述、已准入通用知识卡和独立安全事实。模型只返回不可发送的结构候选：个人事实与一般知识分区、资料来源/时间/用途、支持/反对、未知、不确定性、安全下一步及允许的 claim/template id。core 只接受本轮提供且仍 current 的引用；最终文字从已审核的中文 claim atoms 和模板确定性渲染。疾病方向排序、诊断标签、排除结论或个体化调药没有非诊断输出原子，因此不能靠模型措辞绕过，而是移交完整诊断路径；范围不成立时不拼出残缺诊断。新主人陈述另走候选证据准入，问答本身不得冒充画像已经更新。

## 六、医学内容、首发范围、五分支与修订链

首发诊断范围目标选择：**中国 18 岁及以上成人、非妊娠、近期身高体重测量可靠，仅基于 BMI 的超重、肥胖及肥胖程度 AI 辅助分类**。选择它是因为已有国家卫健委 2024 原生中文一手候选，输入和确定性重算面最窄，适合先完成一条纵向全链；不把 NICE 或高血压规则混入，也不把高血压作为静默 fallback。

运行时只读一组不可变兼容 release：Plugin 工程不变量、所有范围共享且经审核的安全核心、BMI 范围证据投影/知识/接受规则，以及经审核的中文 claim atoms/渲染模板。ScopeRegistry 只有在内容使用与规则化权利、精确中文版本、更新/撤回条件、合格医学人员对实际 bundle hash 的内容/规则/危险边界审核、Plugin 和 StrictHealthLLM 兼容及范围产品验收均成立时才把 staged release 原子切换为 active。现在尚未取得生产使用权或医学签字，因此本 ADR 只选目标和流程，不宣称范围已经激活。

每次诊断固定经过三段失败关闭：

1. **模型前**：重核初始化、主人控制、current head、首跳同意、active bundle、最小且完整资料、容量、安全和范围；危险/危险未明/安全不可用/范围外在此收敛，不能先让模型猜。
2. **模型后**：只接收权威 completed 的严格候选；校验证据/知识 id、角色、支持/反对/未知、紧急程度、处方药禁令和范围允许值，并由本地规则独立重算 BMI 与分类。任何自由正文、未知引用、终态不完整或不一致都隔离候选。
3. **提交与放行前**：在最终 revision 中重读初始化 generation、控制、证据、bundle hash、首跳同意和删除代际；全部前提仍成立才追加诊断修订和 outbox。发送未知只改变交付状态，不重跑诊断。

五类结果固定优先：安全能力不可用、危险升级、危险未明、范围外、范围内。安全能力不可用只给预审非个性化最低求助提示；危险升级停止普通诊断并给审核过的人工医疗/急救提示；危险未明只问最小非诱导问题，不能安全等待时建议及时人工紧急评估；范围外不输出残缺疾病排序、排除或个体调药；范围内才形成最终结构化诊断。关键词未命中永远不证明安全。

五类结果的长期留存也固定分开：只有通过全部门槛的范围内结果保存结构化判断、最小证据/知识引用、版本、适用时间、紧急程度和下一步；范围外不建诊断记录；危险升级只留最小危险事件与交付状态；危险未明只留最小开放缺口和已采取处置；安全能力不可用只留不含健康正文的状态。未通过候选、完整 prompt、模型输入输出、整份外部记录和完整回复均不长期保存。

同一“健康问题 + 事件 + 适用时期”使用稳定修订链，至多一个 current 或显式 none/authority-unknown。最终 revision 引用确切个人证据版本、医学/安全/模板 bundle、首跳能力清单、适用期、支持/反对/未知、紧急程度和变更原因。模型重跑、提示或 provider 变化不能改判；医生结论作为独立有来源证据触发复核，不自动覆盖 AI。来源、规则或审核依据失效时，依赖它的 current 先退出并显示撤回/降级；主人纠正被当前判断使用的个人事实时，受影响判断同样先退出再复核。主人能看到修订、降级、撤回或替代及原因；曾影响主人的实质纠错产生一次防重通知。

## 七、删除、防复活与完整迁移

永久删除先冻结新入站健康效果、任务推进、模型和 outbox，再把 DynamoDB current head 条件推进到不可恢复的 terminal generation。响应未知就强读 transition id，绝不重试猜测。terminal 已确认后，core 销毁画像数据密钥并清除 SQLite 中全部个人内容、索引、任务、批准、控制、诊断、临时/outbox、专用备份、服务器导出和迁移暂存；Plugin 和 observer 只能看见不含个人内容的终止代际。若远端终止态尚无法确认，本地清理仍继续、产品保持完全关闭，但不得声称旧 VM 防复活已经完成。删除请求的正常操作结果不是新增倒计时、固定期限或独立删除回执；删除后不再发送健康通知。主人以后主动初始化时建立全新 installation/generation 和空白个人状态，旧资料永不关联。

计划迁移必须枚举同一 release/semantic manifest：锁定的 Hermes artifact 与必要 patch、`StrictHealthLLM` interface/version、Plugin/core 代码、`health_weixin` 配置及唯一 allowlist 引用、内置微信/Telegram 禁用断言、Gateway/core/observer/KnowledgePublisher 的 service unit、运行用户、sandbox/ACL、依赖锁、运行配置、发布计划与不可变发布库；当前 ADR 与产品合同 bundle、`health-init`/`health-steward`/四职责 Skills、画像 schema、知识/安全/范围 bundle；SQLite 语义快照、密钥和 credential 引用、current-head 与 observation resource identity，以及所有 receipt/cursor、画像/证据、任务、批准、控制、诊断、unknown/outbox、复盘和删除状态。秘密不进入 manifest 或迁移包，只迁移引用并在目标重新配置、验证。仅复制文档与 Skill、profile 目录、Plugin/core 或主 DB 文件都不叫完整迁移。

迁移时源端先取得迁移意图并冻结，整理在途/unknown，生成 revision N 的一致快照；目标只离线校验版本、引用、密钥、入口、首跳同意和 bundle，不产生业务效果。DynamoDB CAS 一次把 active site/writer fence 推进到目标 generation N+1；目标只有读到自己的 current fence 才启动，源端和任何旧 VM 的旧 fence 立即使写入、模型和发送失败。CAS 结果未知时两端均保持“无法确认”，未发送 outbox 按当前状态重判，in-flight/unknown 永不重放，复盘只补当前当地日。此路线只承诺源端仍可用时的计划迁移，不重新引入聊天账号恢复或源丢失后的管家恢复承诺。

## 八、C01—C17 实现归属

| 能力节点 | 当前路线唯一归属 |
|---|---|
| C01 | Partner Health Plugin + 私有 `health-core` + 同一运行目标和 contract probe |
| C02 | Adapter 先行收敛、初始化状态机、统一健康操作 interface |
| C03 | `health_weixin`、唯一 allowlist、receipt/cursor 与 replay/unknown 账本 |
| C04 | core 单写 SQLite、标准 AEAD、credential seam、current-head 提交协议 |
| C05 | `PortraitSchemaRelease`、三类×六域证据卡、唯一引用与四职责写权限 |
| C06 | TaskEngine、四标签、阶段/验收/批准与后继关系 |
| C07 | 自然日 ReviewEngine、事务 outbox、五类通知与投递分层 |
| C08 | `StrictHealthLLM`、首跳同意指纹、无跨首跳 fallback、固定 egress |
| C09 | `KnowledgePublisher`、不可变 bundle、许可/中文/审核/退出治理 |
| C10 | ScopeRegistry 与 BMI 首发范围的 staged/active 准入 |
| C11 | 最小完整投影、容量能力清单、严格结构和权威终态 |
| C12 | 模型前三分支收敛、共享安全核心、处方药禁令和五类结果 |
| C13 | 稳定诊断链、不可变 revision、单一 current 与纠错通知 |
| C14 | 独立主人控制、terminal delete generation、全副本 manifest |
| C15 | StatusProjector + 无正文异故障域 observer + 转态 outbox |
| C16 | release/semantic manifest、源冻结、DynamoDB writer fence 与目标接管 |
| C17 | 结构化非诊断候选、claim/template 确定性渲染和独立画像更新结果 |

## 九、旧票逐项继承、修订与放弃

| 历史票 | 当前处理 |
|---|---|
| [选择健康管家在 Hermes 中的单一执行与权威路线](../../.scratch/partner-health-steward/issues/47-choose-hermes-health-execution-and-authority-route.md) | **继承**单一 Partner、单 Plugin 产品、单画像、无第二 Agent/LLM Gateway；**修订**“全部纯进程内、无 sidecar”为无人格的 Plugin 私有低权限 core，以隔离密钥和唯一写入。 |
| [选择微信接入、主人授权与逐次来源路线](../../.scratch/partner-health-steward/issues/48-choose-channel-identity-and-provenance-route.md) | **继承**在去重/合批前接管、receipt/cursor、重投歧义和未知；**修订**同名覆盖为唯一 `health_weixin` + 内置微信 disabled；**放弃**后来已被 TO 取代的候选身份/恢复准备。 |
| [选择健康画像数据平面、模型调用与保护路线](../../.scratch/partner-health-steward/issues/49-choose-health-record-rights-and-protection-route.md) | **继承**专用 SQLite、认证加密、密钥分离、短事务/outbox 和普通历史隔离；**修订**为 core 单写、同库审计/投递及域外 current head；**放弃**原样 `ctx.llm` 和仅靠本地删除防复活。 |
| [选择辅助诊断、医学知识与安全强制路线](../../.scratch/partner-health-steward/issues/50-choose-diagnostic-knowledge-and-safety-route.md) | 未形成旧 Answer；主人已选的私有协调器、本地固定审核包、模型非权威候选、三段失败关闭、分层版本规则、最小投影和确定性渲染全部**继承**，并由本文补上 `StrictHealthLLM`、BMI、五分支与修订链。 |
| [选择每日复盘、主动发送、恢复与运行状态路线](../../.scratch/partner-health-steward/issues/51-choose-daily-review-delivery-recovery-and-status-route.md) | 无旧 Answer；其问题全部**吸收**到 core 的自然日账本、outbox、unknown、StatusProjector 和 observer，不建立独立运行权威。 |
| [核验微信 iLink 与目标 Hermes 的真实接口能力](../../.scratch/partner-health-steward/issues/52-verify-weixin-ilink-and-target-hermes-interface-capabilities.md) | 不是 HOW；**继承**可选字段、无 exactly-once/到达回执和真实 canary 未做的事实，转为 Adapter 验证义务。 |
| [确认首发健康管家的基础产品能力与不可妥协边界](../../.scratch/partner-health-steward/issues/53-confirm-foundational-product-capabilities-and-boundaries.md) | 不是 HOW；保留经后继 TO 修订后的产品要求，旧七域和恢复准备不进入当前路线。 |
| [核验生理与心理健康画像的科学结构](../../.scratch/partner-health-steward/issues/54-research-scientific-health-portrait-structure.md) | 不是 HOW；保留科学覆盖、来源/时间/不确定性事实，导航按后继六域与固定二级主题实现。 |
| [选择健康能力入口与 Skill/Tool 契约](../../.scratch/partner-health-steward/issues/55-choose-health-capability-entrypoints-and-skill-tool-contract.md) | 无旧 Answer；**吸收**为 Adapter 先行、一个初始化 Skill、一个主人 Skill、四职责 Skill、确定性 Commands 和统一 core interface；**放弃**模型选不选 Tool 可以决定门禁的路线。 |

## 十、验证切面、实施硬依赖与 No-Go

后继 Spec 必须沿同一 interface 分层验证，不另建竞争架构：

1. **纯业务合同**：用内存 Adapter 验证初始化、六域/证据、任务、控制、诊断五分支、修订、删除和三态；测试只观察 interface 结果，不穿透内部表。
2. **本机集成**：真实 core 进程、socket、SQLite/AEAD、密钥缺失、崩溃 prepare/CAS/finalize、outbox 和普通 Session/日志泄漏检查。
3. **Hermes 合同**：锁定 commit，验证 `health_weixin` 动态注册、内置微信/Telegram 不可回退、Plugin 部分注册失败、Gateway/core 同停和升级失效。
4. **模型合同**：合成资料验证实际首跳、禁止 fallback、最终 wire 计量、结构格式、completed/incomplete/failed、截断、返回 model 和未知提交；未通过前诊断范围不能 active。
5. **医学与内容**：先取得 BMI 内容实际使用与规则化权利，再冻结中文 bundle，由合格医学人员审核实际 hash、规则、安全边界与模板；来源失效必须退出范围。
6. **外部 current head**：获准 AWS 资源后用纯合成无个人数据验证并发 CAS、响应丢失、credential/网络故障、资源删除重建、旧 VM、terminal delete 和迁移 writer fence。
7. **真实接口**：先用合成非健康数据完成 iLink 入站/回复/主动发送、重复、重启和 unknown canary；最后才由主人明确批准真实微信、真实模型和首发范围端到端验收。

以下条件任何一个未满足，均禁止宣称健康管家“活跃”、诊断范围已激活或完整首发：目标 Hermes/Plugin/core 未锁定并通过合同；普通入口仍可旁路；AEAD/credential/SQLite 恢复闭包未过；DynamoDB 资源和 old-snapshot canary 未过；StrictHealthLLM 无容量与终态证明；BMI 权利或医学审核未完成；安全五分支、删除、迁移、真实微信和主人实际结果未验收。

## 结果与代价

这条路线换取的是一个可定位的权威 seam：入口不会因模型未调用 Tool 而漏过，业务状态与发送不互相冒充，旧 VM 不能仅凭本地副本恢复成当前，模型候选不能直接成为健康结果。代价是增加一个本机私有进程、一个小型 Hermes host interface、一个单区域 DynamoDB 外部依赖，以及更严格但不如自由模型文本灵活的 claim/template 输出。DynamoDB 或严格模型能力不可用时，健康处理会降低可用性而不是猜测继续；这是有意选择的失败关闭。

本文不展开数据库字段、socket 消息、函数签名、加密参数、医学阈值、部署命令、完整测试矩阵或实施任务清单。它们进入下一条显式 Matt 流程形成的唯一实施与验收 Spec/计划。
