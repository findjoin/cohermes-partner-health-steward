# 健康档案、数据权利与保护能力核验（Ticket 45）

## 1. 核验范围与证据纪律

- 固定源码：目标现场 Hermes v0.20.0，commit `3c27eb6234bf91b8ceee9e9071591b31e9b148cb`。
- 现场核验：2026-08-16 02:48:17–02:53:49（Asia/Shanghai），主机 `findjoin` 上正式运行的 `partner` profile。
- 方法：固定提交的官方文档与源码审计，加一次 SSH 只读现场检查。没有安装或启用 Plugin，没有修改文件、创建任务、发送消息、停止或重启服务；没有读取或输出聊天正文、`USER.md`、Memory 正文、token、身份值或模型请求。
- 本报告只回答 CAN：哪些能力原生存在、哪些能由正式扩展面承接、哪些当前缺失。它不选择档案结构、数据库、加密算法、密钥、备份、删除实现或主人操作方式等 HOW。

## 2. 分层结论矩阵

| 产品要求 | Hermes v0.20.0 原生能力 | 正式扩展空间 | 当前 Partner 现场 | CAN 判断 |
|---|---|---|---|---|
| 独立、最小、可追溯健康档案 | 普通 Session 保存完整聊天；通用 Memory 会进入模型上下文，二者均无健康领域结构 | Plugin 可自行实现专用文件或数据库状态；Adapter 可提供可信逐条来源。这是扩展能力推断，不是 Hermes 受管存储 | 没有启用健康 Plugin 或可识别的健康权威档案 | **原生不满足；可扩展，尚未实现** |
| 事实、医生转述、外部知识与 AI 推断分离 | 无对应领域类型、来源和确认状态 | Plugin 可定义专用记录模型和提交规则 | 无可识别健康领域状态 | **需健康组件承担** |
| 主人查看、纠正、导出、删除 | 有通用 Session 导出、清空、删除，但粒度是聊天会话且无健康主人授权语义 | Plugin 工具或命令可提供健康专用操作 | 无可识别主人权利状态或操作面 | **原生操作不能冒充产品权利** |
| 停止新增记录与暂停主动支持 | 无两个互相独立的主人级健康状态 | Plugin 可持久化并在真实写入与发送路径执行 | 无可识别状态 | **需健康组件承担并失败关闭** |
| 数据接收方变化后暂停并重新同意 | 可配置 provider/model，调用后可审计实际路由；原生无主人同意账本 | Plugin 可持有同意状态并限制健康调用，但必须在发送前验证全部路由和 fallback | 无健康接收方同意状态 | **原生不满足；后续必须验证事前闸门** |
| 静态数据保护 | 一般 OS 文件权限、普通 SQLite/Markdown 和普通 ZIP 压缩；无健康专用加密与密钥生命周期 | Plugin 可自行管理加密、密钥、权限和受管备份 | 只有 root profile 目录边界，未发现健康专用密钥或加密产物 | **原生不满足；威胁边界与方式留给 HOW** |
| 身份迁移与恢复后延续同一档案 | 无健康档案控制权映射 | Plugin 状态可绑定同一档案标识并保留控制状态 | 无可识别映射 | **需健康组件承担** |

## 3. 普通 Session 与通用 Memory 不是健康档案

Hermes 的 `state.db` 是普通会话权威：它保存完整消息历史、工具调用、reasoning、系统提示和精确 API 内容，并提供全文检索。通用导出、清空和删除也以 Session 为粒度，而不是以“主人健康档案”及其权利为粒度。[Session 存储范围](https://github.com/NousResearch/hermes-agent/blob/3c27eb6234bf91b8ceee9e9071591b31e9b148cb/website/docs/developer-guide/session-storage.md#L2-L27) [消息字段](https://github.com/NousResearch/hermes-agent/blob/3c27eb6234bf91b8ceee9e9071591b31e9b148cb/website/docs/developer-guide/session-storage.md#L75-L107) [通用导出与删除](https://github.com/NousResearch/hermes-agent/blob/3c27eb6234bf91b8ceee9e9071591b31e9b148cb/website/docs/developer-guide/session-storage.md#L340-L368)

这与当前产品目标存在两个直接差别：健康档案只能保存有健康意义的最小资料，而普通 Session 保存完整对话；健康档案还必须区分个人事实、医生转述、外部知识和 AI 推断并保留来源、时间与确认状态，Session 没有这些领域语义。因此，Session 的导出或删除 API 不能直接视为主人健康数据权利已经成立。

内置 `MEMORY.md` 与 `USER.md` 是容量受限的通用模型记忆，在会话开始时进入 system prompt 并在当前会话中冻结；它们支持通用字符串增删改，后台记忆流程还可能使用另一个模型。[Memory 容量与注入生命周期](https://github.com/NousResearch/hermes-agent/blob/3c27eb6234bf91b8ceee9e9071591b31e9b148cb/website/docs/user-guide/features/memory.md#L8-L45) [Memory 写入与后台处理](https://github.com/NousResearch/hermes-agent/blob/3c27eb6234bf91b8ceee9e9071591b31e9b148cb/website/docs/user-guide/features/memory.md#L194-L270) 它既不是独立结构化健康档案，也不是接收方隔离边界；把健康内容写入其中会使内容进入普通模型上下文。

Skill 也是按需加载到模型上下文的知识与流程载体，不提供持久档案、授权、删除或静态保护边界。[Skill 渐进加载](https://github.com/NousResearch/hermes-agent/blob/3c27eb6234bf91b8ceee9e9071591b31e9b148cb/website/docs/user-guide/features/skills.md#L111-L121)

## 4. 正式 Plugin/Adapter 扩展面保留实现空间

Hermes 的正式 Plugin API 可以注册工具、Hook、命令、平台 Adapter、上下文引擎和模型调用。[Plugin 能力清单](https://github.com/NousResearch/hermes-agent/blob/3c27eb6234bf91b8ceee9e9071591b31e9b148cb/website/docs/user-guide/features/plugins.md#L87-L106) Plugin 是拥有 Agent 进程权限的 Python 代码，官方也展示了随 Plugin 分发和读取数据文件的方式。[Plugin 数据文件](https://github.com/NousResearch/hermes-agent/blob/3c27eb6234bf91b8ceee9e9071591b31e9b148cb/website/docs/developer-guide/plugins/index.md#L343-L356) [Plugin 权限](https://github.com/NousResearch/hermes-agent/blob/3c27eb6234bf91b8ceee9e9071591b31e9b148cb/SECURITY.md#L134-L147)

由正式执行扩展和进程权限可以推断，健康 Plugin 能自行实现独立权威档案、事实与推断类型、主人控制状态、接收方同意状态和身份连续性映射；Ticket 43 已确认正式 Adapter 扩展面还可以在微信正文合并前保留逐条来源。这不是 Hermes 提供的受管存储保证：目标版本没有通用 `ctx.state`、健康档案 schema、事务、迁移、加密、备份或主人数据权利服务，因此上述内容不能写成原生已支持；数据模型、并发、版本、恢复和操作入口都属于后续 HOW。

Hook 与 middleware 抛异常时，Hermes 只记录警告并继续核心流程；Plugin 加载失败也不会阻止 Hermes 主体运行。[Plugin 与 Hook 失败行为](https://github.com/NousResearch/hermes-agent/blob/3c27eb6234bf91b8ceee9e9071591b31e9b148cb/hermes_cli/plugins.py#L1611-L1689) [Hook/Middleware 异常行为](https://github.com/NousResearch/hermes-agent/blob/3c27eb6234bf91b8ceee9e9071591b31e9b148cb/hermes_cli/plugins.py#L1744-L1806) 因此，停止记录、暂停主动支持、身份授权、删除阻断和接收方同意不能只依赖观察型 Hook；后续 HOW 必须把这些约束放在真实读取、写入和发送路径，并验证失败时不会继续处理健康内容。

## 5. 主人权利与删除覆盖边界

正式扩展面足以提供健康专用的查看、纠正、导出、删除、停止新增记录和暂停主动支持操作，但 Hermes 没有现成的主人身份授权、原子纠正、导出结果、删除覆盖或两种暂停状态。服务器管理员手工删除文件只能是运维动作，不能替代主人通过 Hermes 行使产品权利。

“主人要求删除后，Hermes 删除健康档案”不需要增加倒计时、固定期限、删除回执或管理员代删功能；但实现与验收必须覆盖所有仍会让健康管家重新读取、推断或恢复该档案的受管副本。如果只删除 Plugin 权威文件，而普通 `state.db`/全文检索、通用 Memory、工具结果、导出物或受管备份仍能重新提供已删健康内容，就没有满足既定删除结果。这是删除的 HOW 与验收范围，不是新增产品功能。

## 6. 数据接收方变化的能力边界

Plugin 的 `ctx.llm` 默认跟随活动 provider/model；显式 provider、model 或 auth profile 覆盖可以使用允许表并在未授权时失败关闭。[Plugin LLM 默认路由](https://github.com/NousResearch/hermes-agent/blob/3c27eb6234bf91b8ceee9e9071591b31e9b148cb/website/docs/developer-guide/plugin-llm-access.md#L22-L30) [覆盖与允许表](https://github.com/NousResearch/hermes-agent/blob/3c27eb6234bf91b8ceee9e9071591b31e9b148cb/website/docs/developer-guide/plugin-llm-access.md#L280-L344)

但 Hermes 没有“健康数据接收方同意账本”。正常调用还可能因服务错误或限流进入 fallback，provider/model 归因是在调用后获得；聚合供应商也可能继续选择下游模型。[Fallback 与事后审计](https://github.com/NousResearch/hermes-agent/blob/3c27eb6234bf91b8ceee9e9071591b31e9b148cb/website/docs/developer-guide/plugin-llm-access.md#L354-L378) [聚合层路由配置](https://github.com/NousResearch/hermes-agent/blob/3c27eb6234bf91b8ceee9e9071591b31e9b148cb/website/docs/user-guide/configuration.md#L1091-L1108)

因此，健康组件可以保存“主人同意了哪些接收方”的状态，但事后审计不能代替发送前同意。后续 HOW 必须逐条证明所有携带健康资料的模型调用、工具调用和接口发送都能在发送前确定允许的接收方；无法确定时必须停止新的健康处理。已经发送给外部接收方的数据能否由对方删除，不受 Hermes 本地删除直接控制，当前尚未验证。

## 7. 静态保护、密钥与备份边界

目标源码中的 `state.db` 是普通 SQLite，Memory 是普通 Markdown；全量备份使用 `ZIP_DEFLATED`，压缩等级 `6` 只表示耗时与压缩率的折中，不是加密强度。[备份创建与压缩](https://github.com/NousResearch/hermes-agent/blob/3c27eb6234bf91b8ceee9e9071591b31e9b148cb/hermes_cli/backup.py#L545-L583)

全量备份扫描 `HERMES_HOME`，因此通常会复制放在其中的 Plugin 数据；快速快照只枚举部分核心文件，任意 Plugin 数据又不会自动进入其恢复合同。恢复后只有若干已识别文件自动设为 `0600`，任意 Plugin 健康文件不自动获得同等权限。[备份扫描与排除](https://github.com/NousResearch/hermes-agent/blob/3c27eb6234bf91b8ceee9e9071591b31e9b148cb/hermes_cli/backup.py#L44-L76) [恢复权限规则](https://github.com/NousResearch/hermes-agent/blob/3c27eb6234bf91b8ceee9e9071591b31e9b148cb/hermes_cli/backup.py#L115-L121) [快速快照范围](https://github.com/NousResearch/hermes-agent/blob/3c27eb6234bf91b8ceee9e9071591b31e9b148cb/hermes_cli/backup.py#L880-L947)

所以目标版本没有可直接复用的健康专用静态加密、独立密钥生命周期或跨备份永久删除合同。后续 HOW 必须同时确定健康档案的静态保护、密钥与模型上下文隔离、受管备份及删除覆盖；把密钥与密文一同放入同一个全量备份不能证明静态保护成立。

Hermes 是单租户个人 Agent，Plugin 与 Hook 拥有完整进程权限；真正的文件、网络和推理隔离依赖 OS 或进程外边界。[Hermes 安全边界](https://github.com/NousResearch/hermes-agent/blob/3c27eb6234bf91b8ceee9e9071591b31e9b148cb/SECURITY.md#L50-L73) [Plugin 权限](https://github.com/NousResearch/hermes-agent/blob/3c27eb6234bf91b8ceee9e9071591b31e9b148cb/SECURITY.md#L134-L147) 当前 TO 确认的是管理员不会因技术权限自动获得产品权利，不是“服务器 root 在技术上永远无法读取”。不能把普通文件权限夸大成后一个尚未确认的承诺。

## 8. 目标现场事实

- `hermes-gateway-partner.service` 为 `active/running/enabled`，MainPID `143611`，自 2026-08-07 07:30:33 +08:00 起运行；版本和 HEAD 与本报告固定源码一致，进程用户为 `root`。
- profile 的 `plugins/` 目录为空，配置中 `plugins.enabled: []`；当前没有启用 Plugin。`skills/medical` 存在，但它只是 Skill 资产，不是健康 Plugin、健康档案或产品状态。
- 当前非敏感配置选择 `jojo` provider、`https://max2.jojocode.com/v1` 端点和 `codex_responses` 模式；没有健康接收方同意状态。本次没有读取 `.env` 或发送模型请求，因此不能穷尽运行时覆盖、证明 relay 后续实际接收方，或把当前配置冒充主人已经知情同意的健康数据接收方。
- 通用 `state.db` 为 3,031,040 bytes、`0644 root:root`；其祖先 `/root`、`/root/.hermes` 和 profile 为 `0700`。`sessions/`、`memories/`、`logs/` 和 Cron 通用状态存在，但本次没有读取其正文或数据库内容，不能把它们当健康档案、同意状态或数据权利实现。
- 只按名称、权限、属主、大小和修改时间检查了 profile（剪枝 Session、Memory、日志正文）、systemd、`/opt`、`/var/lib`、`/var/backups` 与 `/run`。未发现启用的健康 Plugin、独立命名健康档案或产品状态、健康专用 service/socket、同意/接收方/暂停/纠正/导出/删除状态、健康专用密钥或备份。
- 所在挂载为普通可写 ext4。现场目录权限只能证明 root profile 的一般访问边界，不能证明应用层健康数据加密、独立密钥、主人授权或服务器外备份状态。
- 对精确的 `partner health steward`/`health sidecar` 日志标记只做无正文存在性测试，未发现匹配。这只能说明没有这些命名标记，不能排除任意其他命名的实现。

因此，当前现场存在 Hermes 的通用会话、Memory、日志、配置与 Cron 状态，但没有证据表明独立健康档案、主人数据权利、接收方同意门或静态保护已经实现。通用数据库中是否偶然包含健康内容、服务器外备份和真实主人权利端到端结果均不可验证。

## 9. TO-CAN 判断与后续边界

正式 Plugin/Adapter 扩展面仍允许在 Hermes 架构内建立专用权威档案和控制路径。本票不创建 TO-CAN 差距决策，也不降低已经确认的产品目标。

后续 HOW 必须明确并验证：独立档案的数据模型与事务、事实和推断提交规则、最小化读取与工具返回、身份授权与恢复连续性、查看纠正导出删除的真实结果、停止新增记录与暂停主动支持的独立状态、普通历史/Memory/日志/导出/备份的派生副本控制、发送前接收方同意门、静态保护和密钥/备份边界。任何观察型 fail-open Hook 都不能单独承担上述强制边界。

只有后续证明正式扩展面无法在默认会话持久化或模型发送前截断健康路径、无法阻止普通历史或 Memory 重新摄取已删除内容、无法拥有可真正删除的专用状态，或主人确认了“root 技术上也必须绝对不可读”“已发送给外部接收方的数据也必须由 Hermes 撤回”等更强目标且目标环境不能实现时，才需要创建 TO-CAN 差距决策。
