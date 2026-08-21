# 受管健康状态数据平面、保护隔离与单一权威能力核验

## Answer

截至 **2026-08-20 15:22（Asia/Shanghai）**，本轮在目标 Partner 只证明了构建受管状态所需的部分底层原语，没有发现或证明一套可定位且满足 C04 的已部署健康状态数据平面。当前解释器仍为 Python `3.11.15`，链接 SQLite `3.53.1`，`sqlite3.threadsafety=3`，并提供 `Connection.backup` 与 `serialize`；`cryptography 48.0.1` 可导入；systemd `249` 具备凭据、受管目录和服务隔离原语。它们分别只能证明事务数据库、密码学函数和操作系统服务边界可以被后续实现采用，不能证明六域画像、三类证据卡、任务、批准、控制、诊断修订、未知结果和交付事实已经形成同一套受管权威。[O1][O2][O3][L1]

当前正式 Partner 仍以 `root` 运行，`ProtectSystem/ProtectHome/PrivateTmp/NoNewPrivileges` 均为 `no`，没有 `StateDirectory/RuntimeDirectory/CacheDirectory/LogsDirectory` 或路径准入限制；本次只按指令名检查当前 unit 与 drop-in，共检查一个 unit 文件，`LoadCredential*`/`SetCredential*` 指令计数为零。profile 下 Plugin manifest 计数为零，六个工作树候选部署根路径也全部不存在。因而工作树 sidecar、受限账户、socket、专用状态、密钥、备份、投影和导出临时目录都不是当前现场能力。[L1][L2]

Hermes v0.20.0 的正式 Plugin 可以运行 Python 并注册 Tool、Hook、Command、Platform 等扩展，但没有受管 Plugin 私有状态、事务、迁移、per-plugin secret、备份或当前权威合同；Plugin 与 Hermes 同进程同权限，加载、Hook 或 Middleware 失败默认让基础 Hermes 继续。[F1][F2] 标准 Agent 路径会把完整 user/assistant/tool call/tool result 写入普通 Session 和 FTS，固定 Gateway 还可能在 Session 前记录消息片段，普通 Memory 生命周期能够取得回合正文；Hermes 全量备份可能复制 Plugin 数据、临时文件和密钥，quick snapshot 与恢复又没有任意 Plugin 状态合同。[F3][F4][F5] 所以普通 Session、Memory、FTS、日志、cache、Cron、通用备份和 profile export 不能自动成为健康状态的一部分，也没有一个原生清单证明健康正文不会进入它们。

当前仓库 sidecar 只能作为 **未部署的旧候选** 观察，不能继承为 HOW。它有局部正向构件：结构化候选在内存中校验，单次画像准入可在同一 subject 状态中同时加入一张个人证据、一个画像版本并切换 `current_version_id`；状态文件采用临时文件、`fsync` 和替换；专用删除路径有 tombstone；导出候选要求私有 tmpfs 并可按固定前缀清理。[W1][W2][W7] 但其对象仍是旧的四类画像结论、三种个人证据、独立通用资料卡、旧任务类型/状态、viewer 与非诊断边界，没有当前六域固定主题、三类证据库、四标签任务、受控执行范围批准、诊断修订链或当前完整初始化状态。[W2][W3][W4]

这个候选也不能证明跨对象单一权威：通用状态写入先替换状态文件、再追加独立 audit；资料卡元数据先提交、再写独立 raw blob；画像状态、资料库、delivery ledger、投影 JSON、key 文件、备份、导出附件和外部发送分属多个提交面。源码有若干回滚、`audit_pending`、orphan cleanup 和删除专用恢复，但没有覆盖所有这些对象的一项通用提交/恢复合同。[W1][W3][W5][W6] 例如“证据已写入但 audit 尚未写入”时崩溃，或者“批准已撤回而发送 ledger 已进入 in-flight”时崩溃，当前代码没有证明恢复后必然只暴露一个可确认的当前结果；不能把进程锁、单文件原子替换或一次正常测试提升为多对象原子性。

候选的受管副本也未闭包：它静态声明主状态、master/profile key、每次写入备份、source cache、audit、两个 delivery ledger、普通 Hermes 只读投影、健康模型/微信/Job 凭据、部署状态以及明文 tmpfs export，但没有一个运行时权威 manifest 同时列出这些对象、版本、属主、保留/删除状态和域外副本；普通 Hermes Session/FTS/Memory/journal、微信平台、模型服务、宿主机/云快照仍在该清单之外。[W1][W5][W6][W7] 当前现场普通 root Hermes 备份树有 `587` 个文件、Partner profile backup 文件数为 `0`、Partner cache 文件数为 `3`；未读任何内容，不能判断其中是否含健康聊天，也不能把按名称计数冒充完整枚举。[L2]

因此本票得到的是一项**负向但不降低 TO 的 CAN**：目标环境有足够的一般构件，Hermes 正式扩展面也保留实现空间；但完整受管对象模型、候选/最终隔离、相关对象的一致提交、崩溃后“当前／无当前／无法确认”的确定恢复、普通历史隔离和全部副本闭包均未实现或未证明。这里不选择数据库、schema、加密算法、路径、事务、备份或 sidecar 路线。故障注入、备份恢复和真实健康数据实验仍须主人另行批准。

## 1. 范围、证据层级与禁止动作

- `[PRODUCT]`：当前 [`CONTEXT.md`](../../../CONTEXT.md) 定义的产品对象与结果；它说明必须证明什么，不指定物理表、文件或服务。
- `[OFFICIAL]`：Python、SQLite、`cryptography`、systemd 与 Hermes 官方文档或固定官方仓库。
- `[FIXED-SOURCE]`：目标 Hermes v0.20.0 / commit `3c27eb6234bf91b8ceee9e9071591b31e9b148cb` 的固定源码行为。
- `[LIVE]`：2026-08-20 12:41–12:49 的同日基线，以及 15:22–15:24 的补充脱敏只读元数据探针。
- `[WORKTREE-CANDIDATE]`：`D:\cohermes\ops\partner-health-steward` 当前 dirty/untracked 源码的静态行为，不是部署事实，不继承旧 HOW。
- `[HISTORICAL]`：旧 CAN 中只在相同版本/依赖指纹下可继承的来源定位和构件事实。
- `[UNPROVEN]`：没有当前证据或需要获准实验才能知道的结果。

本轮没有读取或输出 `.env`、secret、key、数据库、备份、cache、日志、聊天或健康正文，没有运行模型、发送微信/Telegram、创建/恢复/删除备份、安装依赖、启停服务、写远端文件或制造故障。现场只输出版本、布尔项、计数、UID/GID、权限和大小。第一次 SSH 探针因引号错误在远端 shell 解析阶段失败，没有执行读取；随后使用修正后的只读探针完成核验。

## 2. `[PRODUCT]` 同一套受管状态必须能定位什么

下表是能力判据，不是 schema。名称可以由 HOW 另定，但任何实现都必须让这些对象、当前性和引用无歧义。

| 逻辑对象 | 至少要能唯一定位和保留的关系 | 不能冒充 |
| --- | --- | --- |
| 唯一健康画像 | 同一画像、不可覆盖的画像修订、唯一当前修订或明确无当前/无法确认；当前状态与六个固定一级领域、固定二级主题；每条当前理解到证据、任务和前序修订的引用 | 第二份摘要、普通用户画像、完整聊天 |
| 三类证据卡 | 每张卡的唯一身份、个人健康证据/通用权威知识/任务过程证据类型、六域与二级主题索引、来源与时间、准入、支持/反对/限定关系、失效/撤回/纠正和后继；正文只由一张权威卡拥有 | 搜索命中即准入、任务 solved 即个人事实、目录复制正文 |
| 健康任务 | 任务身份、具体画像目标、当前实施阶段、验收、`active/solved/failed/cancelled` 主标签、延期/未知警示、证据和画像引用、前序/后继、纠正历史 | 内部调用即任务、发送即验收、无痕重开终态 |
| 批准与撤回 | 批准身份、承担者、健康目的、允许资料、外部效果、有效边界、当前有效性、撤回/替代关系及其任务/动作引用 | 历史批准即当前批准、Plugin 启用即空白授权 |
| 控制状态 | 初始化整体结果、停止新增记录、主动支持暂停、通知选择、首跳接收方同意及变化、任务控制；各状态互相分离并关联同一画像 | 一个含义模糊的全局开关、旧备份复活撤权 |
| 诊断判断与修订链 | 同一问题/事件/适用时期的链身份、每次判断或复核、最小个人证据与医学依据引用、变更类型和理由、唯一当前判断/明确无判断/权威无法确认 | 最新模型输出覆盖历史、多个冲突判断同时当前 |
| 外部动作、未知和交付事实 | 业务对象、执行动作和交付尝试的不同身份；是否提交、是否尝试、接口是否接受、主人到达是否证明；结果未知与任务/判断/批准的引用，且记录不含多余健康正文 | 接口成功即主人收到、未知即失败、盲目重试 |

三个例子说明这里的“单一当前权威”具体指什么：

1. 主人新回答同时准入证据、改变画像理解并完成信息补全任务时，要么三者形成同一个可确认结果，要么系统明确显示结果无法确认并阻止任一半成品冒充当前；不能显示“任务 solved”却找不到支持它的证据。
2. 新诊断判断已经确认提交、只是微信交付未知时，新判断仍可成为当前，未知的只是交付；若连判断是否提交都无法确认，候选和旧判断都不得冒充当前。
3. 主人撤回批准与外部动作并发时，未外发动作必须停止；如果动作可能已经外发，撤回状态与外部结果未知必须同时可定位，不能删除未知事实，也不能自动重试。

## 3. `[OFFICIAL]` 与 `[FIXED-SOURCE]` 可用原语及其边界

### 3.1 SQLite、密码学与 systemd

- `[OFFICIAL]` Python `sqlite3` 支持显式事务、连接上下文和在线 `backup()`；SQLite 单库事务可原子提交同一数据库中的相关行。[O1] 这不自动覆盖 JSONL、key 文件、raw cache、另一个 SQLite、外部 API 或消息发送，也不证明业务恢复语义。
- `[OFFICIAL]` `cryptography` 提供 AEAD 等认证加密原语。[O2] 它不自行决定密钥存放、轮换、进程可见性、备份覆盖、删除或 schema 事务。
- `[OFFICIAL]` systemd 249 的 `LoadCredential=`/`LoadCredentialEncrypted=`、受管目录和 sandbox 指令能作为服务级候选原语。[O3] 它们只有实际接入具体 unit 并验证读写边界后才产生能力；指令存在也不抵抗已控制主机的 root。

### 3.2 Hermes Plugin、普通历史与通用备份

- `[FIXED-SOURCE]` `PluginContext` 没有受管 `data_dir`、事务 state、migration 或 per-plugin secret getter；`register_secret_source` 是进程级 secret 来源，不是 Plugin 间秘密隔离。[F1]
- `[FIXED-SOURCE]` Plugin 是与 Hermes 同进程同身份的受信 Python；加载/`register()`、Hook 和 Middleware 异常默认记录后继续，部分注册也不自动回滚。[F2]
- `[FIXED-SOURCE]` 标准 handler 创建/取得普通 Session，保存 user、assistant、tool call/result 与实际 API 内容，FTS 索引正文和工具字段；模型调用 Plugin Tool 因而会把健康参数/结果带入普通 transcript。[F3]
- `[FIXED-SOURCE]` 固定 Gateway 在进入 Session 前存在入站/回复片段日志，首次模型调用前持久化 user message，普通 Memory 在 turn 边界可取得正文。当前 `gateway/run.py` 是 dirty 文件，本票没有读当前日志/Memory，所以这是必须重证的固定基线，不是“现场已经发现健康正文”的声明。[F4][L3]
- `[FIXED-SOURCE]` 全量 Hermes backup 扫描 Hermes root；只有 `.db` 走 SQLite 在线快照，ZIP 压缩不是加密，Plugin DB、临时文件和 key 可能被一并复制。quick snapshot 不覆盖任意 Plugin 数据，通用 restore 对任意 Plugin 文件没有 schema、权限、完整性或删除合同。[F5]

结论：这些原语允许后续实现专用状态，但没有一个原生组合能直接证明 C04。

## 4. `[LIVE]` 当前 Partner 数据与权限面

| 核验项 | 15:22–15:24 当前事实 | 能证明 | 不能证明 |
| --- | --- | --- | --- |
| Python/SQLite | `3.11.15` / `3.53.1`；`threadsafety=3`；`backup`、`serialize` 均存在 | 无新增依赖即可使用标准 SQLite 构件 | 已有健康 schema、跨文件事务、恢复合同 |
| cryptography | `48.0.1` 可导入 | 认证加密原语候选存在 | 当前健康内容已正确加密、key 已隔离 |
| systemd | `249.11-0ubuntu3.21`；Partner active/running | 服务管理与凭据/sandbox原语在系统中存在 | 当前已接入健康边界 |
| 当前身份 | MainPID 进程 UID/GID 为 `0:0` | 正式 Hermes 仍以 root 运行 | default 与 Partner、Plugin 与宿主互相隔离 |
| 当前 unit | `PrivateTmp/ProtectHome/ProtectSystem/NoNewPrivileges=no`；受管目录和路径准入项为空 | 当前没有这些 systemd 门 | 应用层从未做任何校验 |
| credential 接线 | unit 与 drop-in 共检查 1 个文件，四类 credential 指令计数 `0` | 当前未用 systemd credential 传递健康密钥 | 服务器上绝无任何其他 secret 文件 |
| profile 权限 | profile `0700 root:root`；config/env `0600`；`state.db` `0644`、大小 `5,345,280` bytes；Session/Memory/log/Cron 目录 `0700`；Plugin 目录 `0755` | 一般 DAC 元数据及普通状态持续存在 | `state.db`/日志/Memory 中是否有健康聊天；root 不可读 |
| 当前健康部署 | profile manifest `0`；按名称扫描健康文件 `0`；六个候选部署根路径全部 absent | 当前未部署本仓库候选 health sidecar/Plugin 状态面 | 任意未命名第三方实现绝对不存在 |
| 一般副本面 | root Hermes backup 树文件 `587`；Partner backup 文件 `0`；Partner cache 文件 `3` | 一般 backup/cache 表面存在且可按路径计数 | 这些文件含什么、是否有服务器外快照、是否覆盖健康内容 |

`[LIVE]` 因为本轮未发现可定位的健康 Plugin 或受管健康状态面，无法在现场验证六域画像、三类证据、任务、批准、控制、诊断修订和未知交付的对象/引用；也不能执行候选/最终、崩溃、恢复或删除实验。普通 `state.db`、Memory、log、Cron、cache、root backup 是否偶然含主人健康聊天保持未知，本票按禁止边界没有打开它们。[L1][L2]

## 5. `[WORKTREE-CANDIDATE]` 未部署 sidecar 的静态能力与反例

当前仓库 HEAD 为 `5f358137309d7670e7ad615c8af9d1aa679a49e3`，`ops/partner-health-steward` 有大量 dirty/untracked 文件；以下结论按实际读取文件而不是 HEAD 归因。[W8]

### 5.1 有限正向构件

- [`profile.py`](../../../ops/partner-health-steward/sidecar/profile.py) 把完整入站消息只放入有界内存 staging/recent window；候选不接受 `source_text/message_text`，准入证据 excerpt 最多 300 字。一次已验证候选通过同一 profile subject mutation 加入 personal evidence、不可变 profile version，并切换 `current_version_id`。[W2]
- [`store.py`](../../../ops/partner-health-steward/sidecar/store.py) 在内存 SQLite 中提交后序列化，用同目录临时文件、`fsync`、`os.replace` 与父目录 `fsync` 更新一个加密状态文件；每个 subject 有 version，另有 global version。[W1]
- 状态正文与 source raw candidate 都有加密/认证检查，明文 SQLite header 被拒绝；profile key 可单独销毁。删除路径以 tombstone 处理“状态文件与 key 文件不能同事务”的专用崩溃窗口。[W1]
- [`export_attachments.py`](../../../ops/partner-health-steward/export_attachments.py) 的候选导出只允许 `0700` owner-owned tmpfs，附件为 `0600`、随机固定前缀，正常 finally 删除，重启/计时器可清理超过 22 小时的孤儿。[W7]

这些都是局部机制，不是当前合同或生产证明。特别是 `store.py` 自行实现 HMAC keystream/XOR 与 MAC，未调用已安装的 `cryptography`；静态看到认证检查不能代替密码学审查、key/nonce 生命周期验证或获准恢复实验。[W1]

### 5.2 对象模型仍是旧合同

| 当前 C04 要求 | 候选静态对象 | 结论 |
| --- | --- | --- |
| 六域画像与固定二级主题 | 四类结论：`state/habit_goal/interaction_preference/task_context`，一个 300 字 summary | 不同对象模型；不满足当前六域导航和主题索引 |
| 三类证据卡 | profile 内三种 personal evidence；source library 另存通用资料卡；任务过程主要在 task/audit | 没有统一的个人/通用/任务过程三类证据卡及六域索引 |
| 四标签任务、阶段与验收 | `candidate/scheduled/due_for_render` 等旧派发状态，旧类型禁止 diagnosis | 不等于 `active/solved/failed/cancelled`、实施阶段和按类型验收 |
| 受控执行范围批准 | viewer grants、recording consent、Job action token 和若干 policy constraints | 没有当前承担者/目的/资料/外部效果/有效边界批准与撤回对象 |
| 控制状态 | recording、proactive pause、viewer、旧 owner recovery 等 | 未包含完整初始化、通知选择和当前产品已取消的 viewer/迁移边界仍存在 |
| 诊断修订链 | health sidecar 主路径明确 non-diagnostic/forbids diagnosis | 没有判断链、当前判断、修订/降级/撤回/替代或依据失效传播 |

来源见 [W2][W3][W4]。这说明旧候选不能因“测试多、字段多、sidecar 已写好”而继承为当前 HOW。

### 5.3 候选/最终与多对象提交仍不闭合

候选只在个人证据准入这一条路径上有清晰分隔：模型候选经过结构、来源、时间、摘要长度和当前 recording 检查后，才与 evidence/version/current pointer 一起进入同一个 profile status。以下范围没有同等证明：

1. `write_subject_status()` 先把状态文件持久化，再把 `status_write` 和业务 audit 追加到独立 JSONL；audit 异常时会尝试恢复旧 blob，但“状态已替换后、audit 开始前”的进程崩溃没有通用 journal。[W1]
2. `SourceLibrary.ingest()` 先提交 card metadata，再写独立 raw blob；异常路径会回滚并登记 orphan，但进程在两步之间消失后的启动一致性没有统一证明。[W3]
3. profile、source-library special subject、delivery ledger、projection、key、backup、export 和外部消息不是一个提交面。单个 `RLock` 或单个 SQLite transaction 不能覆盖另一进程、另一文件或微信接口。[W1][W3][W5][W6]
4. delivery candidate 有 `sent/uncertain/rejected` 和 `*_audit_pending` 恢复状态，是一项局部正向设计；它仍没有证明 task label/phase、批准当前有效性、业务结果和交付 ledger 在一次崩溃后共同收敛。[W5]
5. deletion tombstone 只处理 profile-key 删除的特定不可逆过程，不能外推为全部画像更新、任务、批准、诊断修订或发送都有同等恢复合同。[W1]
6. 候选 `restore_backup()` 校验并替换的只有主 `state.sqlite.enc` blob；它不会把 audit、source raw cache、两套 delivery DB、projection、profile key、导出临时副本与主状态恢复为同一代际。[W6]
7. 候选中个人证据和画像版本拥有 UUID，但画像 conclusion 只有去重键而没有稳定对象 ID；通用资料卡中的 `conclusion_refs/task_refs` 又只是字符串集合，没有外键或生产路径中的引用完整性证明。因此局部对象有 ID 不能外推为所有画像、证据、任务和诊断关系都可唯一引用。[W2][W3]

因此“单文件原子替换”“数据库支持事务”“测试中能重启”都不足以证明多对象原子提交与恢复后的单一当前权威。

### 5.4 候选副本与普通 Hermes 隔离反例

候选静态声明或创建的内容/副本面至少包括：

| 面 | 候选静态事实 | 当前判断 |
| --- | --- | --- |
| 主状态与 key | `state.sqlite.enc`、master key、profile key 目录 | 可按硬编码路径发现；非当前部署；key 为普通文件，不是 systemd credential/keyring |
| 状态备份 | 每次 status write 前复制 encrypted state 到 `backups/`；另有 pre-restore copy | 备份可枚举但与 key/外部快照的同代际和恢复当前性未证明 |
| source cache | card metadata 在状态中，raw blob 在独立目录，临时文件和 orphan list 另算 | 局部清理存在；跨崩溃闭包未证明 |
| audit | 设计为 content-free JSONL，另有 lock/tmp | allowed-key 校验是正向构件；与状态跨文件原子性未闭合 |
| delivery | Partner 与 sidecar 各有独立 SQLite ledger | 不是画像/任务同一事务；可能形成 `audit_pending/uncertain` |
| 普通投影 | `0640` 明文 `memory.json` 保存 archive pointer、最多两条画像派生 interaction preferences 和 proactive state | Plugin `pre_llm_call` 对非 Cron Session 注入它，未按 Weixin/owner过滤；普通 Telegram/CLI 回合可能读取健康派生内容，并可能随实际模型请求进入普通 Session 的 `api_content`，违反普通聊天不读健康画像的当前合同 [F3][W6] |
| profile export | 完整 profile/tasks/reports/audit 生成明文 JSON tmpfs 附件 | 是受控临时副本候选；崩溃孤儿需计时器，微信接收端副本不受本机清理 |
| 配置和凭据 | env 文件指向 health-model key、Weixin token、receipt public key、Job secret 等；Job secret 复制给两个服务账户 | 可以列路径，不是 per-plugin secret；当前未部署且未验证轮换/备份/完整迁移 |
| 普通 Hermes 面 | 候选 Adapter/Hook 与标准 Agent 共存；普通 Session/FTS/Memory/log/journal、Cron、Hermes backup 仍有独立生命周期 | 没有一份运行时证明把所有健康正文排除；projection 已给出一个明确反例 |

候选部署脚本确实列出许多固定路径和预期权限，但固定路径集合不是运行时资产闭包：代码新增临时文件、Plugin/Tool 自行输出、Hermes journal、模型/微信留存、宿主机 snapshot 和管理员复制都不由这份脚本自动枚举。[W6]

## 6. 能力矩阵与仍需批准的证明

| C04 子能力 | 当前结论 | 已有原语/候选 | 缺少的证明 |
| --- | --- | --- | --- |
| 完整对象与引用 | **未实现/未证明** | UUID、subject/version/current pointer、若干 refs | 当前六域、三类证据、任务/批准/控制/诊断/未知的共同身份与引用完整性 |
| 候选与最终隔离 | **局部候选有** | personal evidence candidate 校验后一次准入 | 所有健康结果、任务、诊断、控制与外部动作的统一 final gate |
| 相关对象一致提交 | **单 subject 局部有；跨对象无证明** | SQLite transaction、atomic file replace、locks | DB/audit/raw/projection/keys/backups/delivery/external action 的一致结果 |
| 崩溃/部分写入处理 | **少数专用路径有** | deletion tombstone、audit rollback、orphan list、delivery audit-pending | 全操作故障矩阵及“失败/未知/已提交”可判定恢复 |
| 恢复后单一当前权威 | **未证明** | profile `current_version_id` | 全对象 current-head、损坏/旧备份/部分恢复时的停止与重建证明 |
| 普通历史隔离 | **当前无；候选有反例** | no-history command/adapter 原语、独立 sidecar候选 | Session/FTS/Memory/log/journal/Cron/cache/export 全路径排除；projection 当前冲突 |
| 静态保护 | **原语有，产品能力未部署** | `cryptography`、文件权限、systemd、候选自有加密 | 选定实现、key边界、root威胁声明、备份/导出/临时副本验证 |
| 全部副本可枚举 | **未证明** | 固定路径、profile/Plugin/cron/log count、candidate path list | 单一受管 manifest、域外副本声明、每代完整性与删除/迁移闭包 |

以下实验在实现以后仍需主人单独批准；本票没有执行：

1. 用不含真实健康资料的隔离 canary，在每个相关提交点前/中/后强制终止进程，恢复后验证只出现“旧当前、新当前、明确无当前或无法确认”之一，且半成品不被读取或派发。
2. 同时改变证据、画像、任务、批准/撤回、诊断修订与 delivery 状态，验证并发、重启、磁盘满、权限拒绝和 audit/raw/projection/ledger 单点失败。
3. 对 Session、FTS、Memory、普通日志/journal、tmp/cache、Cron output、Hermes backup、健康 backup、profile export 和域外 snapshot 建立 canary 清单，再验证正常、异常、恢复、导出和永久删除覆盖。
4. 对选定静态保护和 key 路线做独立密码学审查、权限/进程边界验证、备份恢复及 key 缺失/损坏实验；不得用“文件是密文”或“mode 0600”替代。

## 7. 一手来源与可定位证据

### `[OFFICIAL]` 通用构件

- **[O1]** [Python 3.11 `sqlite3` transaction control](https://docs.python.org/3.11/library/sqlite3.html#transaction-control)、[`Connection.backup`](https://docs.python.org/3.11/library/sqlite3.html#sqlite3.Connection.backup)、[SQLite transactions](https://www.sqlite.org/lang_transaction.html) 与 [atomic commit](https://www.sqlite.org/atomiccommit.html)。
- **[O2]** [`cryptography` 48.0.0 AEAD primitives](https://cryptography.io/en/48.0.0/hazmat/primitives/aead/)；只用于说明原语，不为本仓库自定义组合背书。
- **[O3]** [Ubuntu Jammy systemd.exec(5)](https://manpages.ubuntu.com/manpages/jammy/man5/systemd.exec.5.html)：Credential、受管目录与 sandbox 指令的官方语义。

### `[FIXED-SOURCE]` Hermes v0.20.0 / `3c27eb...`

- **[F1]** [`PluginContext` 接口](https://github.com/NousResearch/hermes-agent/blob/3c27eb6234bf91b8ceee9e9071591b31e9b148cb/hermes_cli/plugins.py#L311-L423)、[`SecretSource` 注册](https://github.com/NousResearch/hermes-agent/blob/3c27eb6234bf91b8ceee9e9071591b31e9b148cb/hermes_cli/plugins.py#L748-L789)。
- **[F2]** [Plugin import/register 失败继续](https://github.com/NousResearch/hermes-agent/blob/3c27eb6234bf91b8ceee9e9071591b31e9b148cb/hermes_cli/plugins.py#L1611-L1689)、[Hook/Middleware 异常继续](https://github.com/NousResearch/hermes-agent/blob/3c27eb6234bf91b8ceee9e9071591b31e9b148cb/hermes_cli/plugins.py#L1744-L1806)、[Plugin 信任边界](https://github.com/NousResearch/hermes-agent/blob/3c27eb6234bf91b8ceee9e9071591b31e9b148cb/SECURITY.md#L134-L147)。
- **[F3]** [Session 存储范围](https://github.com/NousResearch/hermes-agent/blob/3c27eb6234bf91b8ceee9e9071591b31e9b148cb/website/docs/developer-guide/session-storage.md#L2-L27)、[消息/API/FTS 字段](https://github.com/NousResearch/hermes-agent/blob/3c27eb6234bf91b8ceee9e9071591b31e9b148cb/website/docs/developer-guide/session-storage.md#L75-L123)、[Gateway transcript 保存](https://github.com/NousResearch/hermes-agent/blob/3c27eb6234bf91b8ceee9e9071591b31e9b148cb/gateway/run.py#L16798-L16850)。
- **[F4]** [固定 Gateway 的 Session 前片段日志](https://github.com/NousResearch/hermes-agent/blob/3c27eb6234bf91b8ceee9e9071591b31e9b148cb/gateway/run.py#L15141-L15168)、[首次模型调用前持久化和 Memory 回合面](https://github.com/NousResearch/hermes-agent/blob/3c27eb6234bf91b8ceee9e9071591b31e9b148cb/agent/turn_context.py#L985-L1171)。
- **[F5]** [Hermes backup 排除与 sidecar 规则](https://github.com/NousResearch/hermes-agent/blob/3c27eb6234bf91b8ceee9e9071591b31e9b148cb/hermes_cli/backup.py#L49-L78)、[`.db` 快照与 ZIP 创建](https://github.com/NousResearch/hermes-agent/blob/3c27eb6234bf91b8ceee9e9071591b31e9b148cb/hermes_cli/backup.py#L504-L620)、[restore 权限](https://github.com/NousResearch/hermes-agent/blob/3c27eb6234bf91b8ceee9e9071591b31e9b148cb/hermes_cli/backup.py#L738-L870)、[quick snapshot 范围](https://github.com/NousResearch/hermes-agent/blob/3c27eb6234bf91b8ceee9e9071591b31e9b148cb/hermes_cli/backup.py#L971-L1003)。

### `[LIVE]` 当前目标

- **[L1]** 15:22:34 探针：目标 venv 仅输出 Python/SQLite/cryptography 版本、`threadsafety` 与 `backup/serialize` 布尔；`systemctl --user show` 仅输出非敏感 service/sandbox 属性；`stat` 仅输出 profile/config/env/state/Session/Memory/log/Cron/Plugin 目录权限和 `state.db` 大小。没有读取文件内容或进程环境。
- **[L2]** 15:24 探针：只按指令名统计当前 unit/drop-in 的 Credential 指令；只输出进程 UID/GID、profile Plugin manifest/健康命名文件计数、六个候选根路径存在布尔，以及 root/Partner backup 与 cache 文件数量。没有输出路径内容、文件名、身份值或凭据。
- **[L3]** [同日《当前 Partner Hermes 基线、Plugin 生命周期与可信执行边界》](19-current-partner-hermes-baseline-plugin-lifecycle-trust-20260820.md)：12:41–12:49 的版本/dirty 指纹、Plugin/manifest/Cron、日志权限及禁止动作；[《唯一微信准入、排他分流、逐次来源与重投结果能力》](21-unique-weixin-admission-routing-provenance-replay-results-20260820.md)只用于固定 Session/log/Memory 源码定位，不把 C03 结论写入本票。

### `[WORKTREE-CANDIDATE]` 当前仓库（未部署）

- **[W1]** [`sidecar/store.py`](../../../ops/partner-health-steward/sidecar/store.py)：`:924-980` 路径/key/锁与启动恢复；`:1164-1416` 删除 tombstone 与旧备份迁移；`:1452-1634` subject 状态、version、audit rollback；`:3750-4015` 删除/备份/audit；`:4235-4535` backup、内存 SQLite、atomic replace、自有加密。SHA-256 `8fbbb9715d2afff1c29ca5db5652a2782b55a32679a9cd0cf1f260f122a3a5ee`。
- **[W2]** [`sidecar/profile.py`](../../../ops/partner-health-steward/sidecar/profile.py)：`:28-62` 三种 personal evidence 与四类结论；`:123-275` 候选校验；`:550-568` 旧 profile 对象；`:726-829` evidence/version/current pointer 同一 mutation；`:872-1006` 已同意候选准入。SHA-256 `f134af8060dc82e53678fef090f4c8d426b08ec95cee7a1593b6cd8f3ee77344`。
- **[W3]** [`sidecar/sources.py`](../../../ops/partner-health-steward/sidecar/sources.py)：`:1-5` 不写画像/任务；`:148-190` 独立 source state/cache；`:212-330` metadata/raw 两步与 rollback/orphan；`:637-656` card 身份/refs；`:767-850` cache/orphan/temp。SHA-256 `492b9611fd6efe54835f2cb97e9dd0d44c44e490bc16e8aa03896d8bf7973a96`。
- **[W4]** [`sidecar/tasks.py`](../../../ops/partner-health-steward/sidecar/tasks.py)：`:33-74` 旧 task types/status/fields；`:809-940` task candidate 验证；文件仍禁止 diagnosis。SHA-256 `a90a618e6b21c4228f8fdba85669553cc07aa38593ac748e37a65a2081fdd83d`。
- **[W5]** [`sidecar/weixin_delivery.py`](../../../ops/partner-health-steward/sidecar/weixin_delivery.py)：独立 delivery SQLite、`sent/uncertain/rejected` 与 `*_audit_pending`、恢复和禁止无 key 发送；只证明候选局部交付状态机。
- **[W6]** [`plugin/health-steward/__init__.py`](../../../ops/partner-health-steward/plugin/health-steward/__init__.py)：`:24,77-171` 候选 projection/ledger/env；`:317-370` 非 Cron `pre_llm_call` 注入没有 Weixin/owner 过滤；`:373-442` 注册。SHA-256 `1748ec7c76cb59a78539375f6ca51d3a21fe66e36e84e945ad7590eb34334a60`。[`sidecar/ports.py`](../../../ops/partner-health-steward/sidecar/ports.py)：`:159-206` 投影最多保留两条画像派生偏好。[`deployment.py`](../../../ops/partner-health-steward/deployment.py)：`:36-65` 候选资产路径；`:695-769` restore 只替换主状态 blob；`:1075-1108` 权限目录；`:1200-1206` projection 为 `0640`；`:1305-1448` 候选 units/sandbox/export timer。SHA-256 `de0bb6aba56922f579350565bf95cb1feb5431c4a38e4c311238d233f2d265dc`。
- **[W7]** [`export_attachments.py`](../../../ops/partner-health-steward/export_attachments.py)：`:24-28,77-90` 固定前缀、22 小时边界与 tmpfs 检查；`:97-267` `0600` plaintext export 创建/删除/孤儿清理。SHA-256 `ff1f84e34a370f7281fdc89b9477e2abc82740d3db570f26289b176ed5e232f1`。
- **[W8]** `git status --porcelain -- ops/partner-health-steward` 与上述文件 SHA-256；当前仓库包含大量 modified、added 和 untracked 候选，不能只凭 HEAD 复原本次源码。

### `[HISTORICAL]` 条件继承

- [健康画像数据平面工具与接口核验](10-health-data-plane-tools-and-interfaces-20260817.md)只条件继承其固定 commit、官方接口定位和当时 Python/SQLite/cryptography/systemd/backup 原语；本票用 8 月 20 日 live probe 重新确认当前版本和接线，没有继承旧 SQLite/加密/sidecar HOW。
- [健康档案、数据权利与保护能力核验](05-health-record-data-rights-and-protection-capabilities-20260816.md)只继承普通 Session/Memory 不等于健康档案、Plugin 同进程和通用 backup 不等于健康 backup 的固定事实；当前完整对象范围以 `[PRODUCT] CONTEXT.md` 为准。

## 8. 明确未证明与本票停止边界

- `[UNPROVEN]` 当前普通 `state.db`、Session/FTS、Memory、日志、cache 或 root backup 是否含主人健康聊天；禁止读取正文，因此不能宣称存在或不存在。
- `[UNPROVEN]` 模型服务、微信、宿主机/云平台 snapshot、管理员手工副本的实际留存和可删除性。
- `[UNPROVEN]` 任一未来实现对磁盘满、掉电、kill、权限拒绝、时钟错误、并发撤权、旧备份恢复和部分迁移的结果。
- `[UNPROVEN]` 工作树自有密码学组合的安全性、所有 key 的同代际备份/恢复、所有路径的完整枚举及删除后不复活。
- 本票没有选择或推荐 SQLite、sidecar、自有加密、systemd Credential、路径、表结构、事务协调、备份或导出 HOW；也没有创建实现或验收资产。
