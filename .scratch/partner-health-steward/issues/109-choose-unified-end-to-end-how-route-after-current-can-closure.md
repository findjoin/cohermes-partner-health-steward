# 【HOW】选择首发健康管家 Plugin 的统一端到端实现路线

Type: research
Status: resolved
Parent: [健康管家首发 TO、CAN 与 HOW 决策闭合路线](../map.md)
Blocked by: [【CAN】闭合七个健康 Skill 与支持联系人重建后的当前 CAN 能力与约束审计](108-close-current-can-after-seven-skill-contact-investigations.md)

## Question

基于最新完整 TO、Ticket 102 的 T01—T36／K01—K21 双向追溯、Evidence 30—35 和已经闭合的当前 CAN，选择一条**在 Partner Hermes 中实现这个健康管家 Plugin**的统一端到端路线，并形成唯一可交接的技术决策与验证边界。七个健康 Skill 是该 Plugin 内部的交互与职责合同，不是七个独立产品或插件。

本票必须一次性处理相互依赖的端到端选择：运行拓扑与可信边界；初始化、唯一准入、两级路由和七个健康 Skill 的协调；单一受管权威状态、对象关系、提交／恢复与副本边界；任务、自然日复盘、未知投递、主人控制和业务三态；首跳模型锁定、查询隔离、非诊断问答与完整终态；医学内容治理、诊断范围、权利、专业审核、安全和修订；支持联系人批准、最小警报、分层投递、纠正、删除与防复活；查看、导出、停止记录、暂停支持、迁移与回滚；权威文档、Skill 组织、版本和搬迁清单；以及静态、合成、故障、真实模型、真实微信、外部许可、医学审核和主人／联系人验收的分层验证与实施依赖。

答案必须说明每项职责的唯一权威写入者、稳定接口、事务与失败边界、未知状态的真实传播、旧状态／副本如何被隔离、路线为何满足最新 TO/CAN 的硬约束，以及哪些内容仍是实现、外部前提、医学审核、真实验收或迁移验证义务。不得把未验证候选冒充当前能力，不得恢复旧 Ticket 98 或 ADR 0021 的选择，不得在本票内直接修改产品目标或进入实现、部署和验收；若研究发现某个精确未知会改变“是否存在可实施路线”，必须暂停并新建单一 CAN 前提票。

## Answer

依据 [Evidence 36](../evidence/36-how-route-after-current-can-closure-20260822.md)、最新 TO、Ticket 102 的 T01—T36／K01—K21 追溯以及 Evidence 30—35，本票选择并闭合以下**健康管家 Plugin 的当前 HOW 路线**；旧 Ticket 98 与 ADR 0021 不恢复，只作为已重新核对的历史输入。详细架构权威记录在 [ADR 0022](../../../docs/adr/0022-select-current-health-steward-route-after-seven-skill-can-closure.md)。

### 统一路线

**一个 Partner Hermes 健康 Plugin → 在原生路径之前收敛的唯一 `health_weixin` 准入 → 一个 Plugin 私有、低权限、同机的 `health-core` → 一个本地加密受管状态域 + 一个不透明的单区域 DynamoDB current-head item → 严格的同一 Partner 首跳模型接口 → 离线受治理知识发布 → 确定性安全／诊断门禁 → 事务 outbox 与分层微信／联系人投递 → 业务事实三态、删除终止代际和 writer-fence 迁移。**

这仍是一个产品、一个画像主人和一个健康 Plugin；`health-core` 不是第二个 Agent、第二人格、第二画像或独立 LLM Gateway。它没有聊天入口、普通对话、微信凭据、模型供应商配置、独立定时器或直接外发能力，只通过受限 Unix socket 接收健康命令和候选，并作为唯一健康状态写入者、业务裁决者和最终结果提交者。Gateway、Plugin、core、密钥、current head 或健康 contract probe 任一无法证明时，健康路径失败关闭；普通 Hermes 继续运行不能被报告为健康可用。

### Plugin 与 Skill 的关系

- **Plugin 是要实现和部署的产品单元。** 它负责 `health_weixin` 适配器、确定性准入和粗分流、Plugin/core 接口、受管状态、任务与 outbox、模型和微信适配、安全门禁、删除／迁移以及业务三态。
- **Skill 是随 Plugin 绑定的交互／职责资源。** A 类为 `health-init`、`health-steward`、`health-settings`；B 类为 `health-portrait`、`health-evidence`、`health-owner-inquiry`、`health-literature`。Skill 提供说明、最小上下文和候选，不拥有数据库写权、最终业务提交权、发送权或独立回复权。
- **Plugin 约束 Skill，Skill 不能替代 Plugin。** Plugin 负责版本、加载、实际使用证明、最小上下文边界、候选回收和失败关闭；模型自称使用、Skill 被发现或文档被安装都不等于业务结果。最低安全结果甚至可以由 Plugin 的非 Skill 安全边界直接产生。

所以本票研究的是“这个 Plugin 如何由这些 Skill 合同和受管核心组合成一条可实现路线”，不是把七个 Skill 当成七个插件分别实现。

### 权威边界与七 Skill

`health_weixin` 在 Hermes 原生去重、合批、cursor 推进和普通 Agent 之前接收可用 envelope；core 保留来源与重投歧义，只有业务提交确认后才推进受管 cursor。初始化由确定性 `health-init` 流程完成披露、主人同意、首跳路线同意、时区偏好、初始画像、密钥、本地 revision 和 current head 的 prepare → 条件提交 → finalize；任一中断或未知都不启用健康管家且不倒填初始化前内容。

七 Skill 按角色组织而非七个独立写入口：`health-steward` 是唯一协调者，`health-settings` 是主人控制面，`health-portrait`、`health-evidence`、`health-owner-inquiry`、`health-literature` 只返回目的限定的候选。Skill 文档、模型自述、安装或加载都不等于真实使用；系统只有在运行时能证明必需动作后才记录最小使用事实。所有候选、自然语言、Tool、Command、Cron 和模型结果都只能经过 core 的深 interface，不能绕过权威提交、唯一主人回复或安全分支。

### 状态、模型、医学与安全

本地 SQLite 受管状态域统一承载 receipt／来源、六域画像、三类证据卡、任务、批准、控制、诊断修订、未知、outbox、交付和运行状态；普通 Session、Memory、FTS、日志、cache、通用备份和模型正文不是第二权威。DynamoDB item 只存不透明 installation/generation、revision digest、transition id、writer fence、active site 和不可逆 terminal deletion 标记，不保存健康正文、凭据或可推断医学值。每次变化使用本地 prepared revision → DynamoDB 条件推进 → 本地 finalize；结果未知时按 transition id 回查，双方不猜测、不继续写入或外发。

模型通过窄的 `StrictHealthLLM` host interface 使用同一 Partner 的已同意首跳；禁止跨首跳 fallback、路线外 Web Search／MCP／普通 Tool／任意 HTTP 和主人派生医学查询。接口必须在最终 wire payload 上证明容量、严格结构和 `completed`／`incomplete`／`failed` 终态，否则不形成业务结果。知识由无主人数据的离线 `KnowledgePublisher` 产生不可变、带来源／版本／许可／中文状态／审核／hash 的 staged release；首发诊断只选择窄 BMI 范围并保持 staged，直到实际权利、中文 bundle、医学专业审核、实现兼容和真实主人验收全部完成。

诊断固定经过模型前、模型后、提交前三段失败关闭；安全能力不可用、可信危险、危险未明、范围外、范围内按固定优先级分支。只有范围内结果才形成结构化诊断修订；依据失效、主人纠正或审核撤回先让旧判断退出 current，再形成降级、撤回、替代或一次必要纠错。危险联系人是单一、单向、最小数据接收者，主人批准独立于普通通知和暂停控制；接口接受、送达、已读和实际行动严格分层，可能已离站的警报或纠正冻结自动重试。

### 任务、控制、删除与迁移

core 的 TaskEngine 独占任务目标、阶段、验收、四标签、批准和后继关系；Hermes Cron 只唤醒，业务自然日账本决定复盘，`sent`、进程存活或 API accepted 不能变成 `solved` 或“主人已看到”。暂停主动支持、停止新增记录、任务取消、撤回外部批准和永久删除是独立命令。状态三态由业务事实聚合，不由进程 heartbeat 冒充。

永久删除先冻结健康效果、任务推进、模型和 outbox，再把 DynamoDB current head 条件推进至不可逆 terminal generation；确认后销毁密钥并清除全部受管对象、索引、备份、导出、迁移暂存和联系人／警报事实。迁移沿用同一 writer fence：源端冻结并生成完整语义 manifest，目标离线校验后一次 CAS 接管，旧 VM 和旧 fence 立即失去写入、模型和发送资格；传输未知时两端都停止，不重放未知外部效果。

### 验证与阶段边界

后继必须分层验证：静态 release／manifest；合成 core；本机 socket、SQLite／认证加密、崩溃和未知故障；锁定 Hermes 的 Plugin／Adapter 合同与无旁路；模型首跳、容量、结构终态和无 fallback；医学权利、中文版本、专业审核与范围激活；DynamoDB 条件冲突、超时回查、terminal delete、旧 VM 和 writer-fence 迁移；最后才是经批准的合成微信、真实模型、真实微信以及主人／联系人验收。本票没有实现、部署、读取真实健康资料、调用真实模型、发送真实警报、接受许可、医学签字、执行删除／迁移或产品验收。

本票没有暴露新的 TO、风险接受取舍或决定路线存在性的 CAN 未知，因此 HOW 正式闭合；后续实现、部署、医学审核、外部许可、真实模型／微信和验收仍是下游硬门槛。若实施研究发现某精确事实会改变路线是否存在，必须暂停并新建单一 CAN 前提票。
