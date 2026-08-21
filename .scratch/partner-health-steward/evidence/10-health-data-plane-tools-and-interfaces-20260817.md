# 健康画像数据平面工具与接口核验（Ticket 56）

## 1. 范围、基线与证据纪律

- 本报告只回答 CAN：目标 Partner Hermes 现成有什么、缺什么、哪些边界能由正式接口强制。它不选择数据库、加密方案、密钥路线、模型路线或备份路线等 HOW。
- 固定源码为 Hermes Agent v0.20.0 / tag `v2026.8.3`，commit [`3c27eb6234bf91b8ceee9e9071591b31e9b148cb`](https://github.com/NousResearch/hermes-agent/commit/3c27eb6234bf91b8ceee9e9071591b31e9b148cb)。2026-08-17 只读现场复核确认主机 `findjoin` 的 `/usr/local/lib/hermes-agent` 仍处于该 HEAD，目标解释器为 `/usr/local/lib/hermes-agent/venv/bin/python`。
- 继承输入为 [目标 Hermes 扩展基线](02-target-hermes-extension-baseline-20260816.md)、[健康档案与数据权利能力](05-health-record-data-rights-and-protection-capabilities-20260816.md)和 [微信 iLink/Hermes 接口能力](08-weixin-ilink-target-hermes-interface-capabilities-20260816.md)；本报告针对 Ticket 49 所需的具体工具和接口重新核验，不把旧结论自动当成当前答案。
- 现场只读取版本、模块可导入性、非敏感 systemd 属性、文件数量及固定源码；没有读取 `.env`、secret、数据库、备份、聊天或健康正文，没有安装依赖、创建数据、修改配置、重启服务，也没有发送模型或微信请求。

## 2. 直接结论

1. **存储与加密有可用构件，但没有健康数据平面成品。** 在本票核验且无需新增依赖的候选中，目标环境已证实可用的事务数据库是 Python 标准库 `sqlite3`，`cryptography` 可提供密码学原语。没有 SQLCipher、通用 Python keyring 或 Hermes 管理的 Plugin 私有数据目录、迁移、加密、密钥、备份和删除服务。
2. **普通 Agent Tool 路径会污染普通历史。** Adapter 把消息交给标准 handler 后，user/assistant/tool call/tool result 会进入普通 Session 和全文索引，并可能进入普通 Memory 生命周期。模型调用 Plugin Tool 因而不能承担健康正文隔离。
3. **存在不自动写普通 Session 的调用面，但都不是端到端“不留痕”保证。** 在标准 handler 前由 Adapter 自行处理、已识别的 Plugin slash command、Command 内直接 `ctx.dispatch_tool` 以及 `ctx.llm`，固定源码都不会自动创建普通 Session/FTS/Memory；Plugin 自身、具体 Tool、日志、微信、模型 provider 和 relay 仍可能保存内容。
4. **`ctx.llm` 不能在发送前闭合“实际健康数据接收方”允许表。** 它没有 endpoint、禁用 fallback、route preview、最终接收方回调或 relay 下游身份接口；常规 fallback 仍会生效。名义 provider/model 的允许表与调用后归因，不能证明发出健康内容前的最终接收方。
5. **Hermes 通用备份不是健康专用备份。** 全量 ZIP 可能把 Plugin DB、临时文件和密钥一并带走且 ZIP 不加密；quick snapshot 不包含任意 Plugin 数据；恢复是覆盖式且没有 Plugin 权限、schema、完整性或按主人永久删除合同。

因此 Ticket 56 的事实问题已经闭合，但 Ticket 49 尚不能进入 HOW：普通 Tool、`ctx.llm` 名义允许表和 Hermes 通用备份都不能写成已经满足隔离、接收方同意或永久删除。尤其是“无普通历史的模型调用”与“发送前确定全部实际接收方”目前没有一条已验证的正式接口同时满足；必须先由新的直接 CAN Research 核验同一 Hermes 内是否还有符合约束的模型调用与接收方路线。若仍不存在，就必须按 Map 规则转成 TO-CAN 差距决策，不能静默降低接收方重新同意的产品目标。

## 3. Plugin 数据、配置、secret 与生命周期

### 3.1 官方保证与固定源码行为

- 官方展示 Plugin 使用 `Path(__file__).parent / "data" / ...` 携带静态数据；这是相对 Plugin 代码目录读取文件的示例，不是 Hermes 分配和管理的可写数据目录。[Plugin 数据文件示例](https://github.com/NousResearch/hermes-agent/blob/3c27eb6234bf91b8ceee9e9071591b31e9b148cb/website/docs/developer-guide/plugins/index.md#L343-L356)
- 固定 `PluginContext` 有 manifest、profile、`ctx.llm` 和 Tool/Command/Hook/Adapter 等注册入口，但没有 `data_dir`、Plugin 配置 accessor、事务 state store 或 per-plugin secret getter。[`PluginContext` 接口](https://github.com/NousResearch/hermes-agent/blob/3c27eb6234bf91b8ceee9e9071591b31e9b148cb/hermes_cli/plugins.py#L311-L423)
- `register_secret_source` 注册的是全进程 SecretSource：框架把解析结果放入进程环境，供之后的凭据读取或子进程使用；它不是“此 Plugin 获取自己的密钥”的 API，也没有 Plugin 间 secret 隔离。[SecretSource 注册实现](https://github.com/NousResearch/hermes-agent/blob/3c27eb6234bf91b8ceee9e9071591b31e9b148cb/hermes_cli/plugins.py#L748-L789) [官方 SecretSource 生命周期](https://github.com/NousResearch/hermes-agent/blob/3c27eb6234bf91b8ceee9e9071591b31e9b148cb/website/docs/developer-guide/secret-source-plugin.md#L119-L143)
- 安装流程可收集 manifest 的 `requires_env` 并写入 `$HERMES_HOME/.env`，`secret: true` 只让交互输入隐藏。[安装时环境变量处理](https://github.com/NousResearch/hermes-agent/blob/3c27eb6234bf91b8ceee9e9071591b31e9b148cb/hermes_cli/plugins_cmd.py#L274-L354) 固定源码虽解析 `requires_env`，但通用 `discover_and_load()` 没有对每个 Plugin 执行统一的运行时缺失检查；因此文档中的“缺环境变量便自动禁用”不能作为该提交的通用 fail-closed 保证。[manifest 解析](https://github.com/NousResearch/hermes-agent/blob/3c27eb6234bf91b8ceee9e9071591b31e9b148cb/hermes_cli/plugins.py#L1509-L1520) [Plugin 发现与加载](https://github.com/NousResearch/hermes-agent/blob/3c27eb6234bf91b8ceee9e9071591b31e9b148cb/hermes_cli/plugins.py#L1268-L1358)
- 单个 Plugin 的 `register()` 抛异常时，manager 保存错误并记录 warning，随后继续运行 Hermes；Hook 抛异常也被记录后继续。[Plugin 加载失败行为](https://github.com/NousResearch/hermes-agent/blob/3c27eb6234bf91b8ceee9e9071591b31e9b148cb/hermes_cli/plugins.py#L1611-L1689) [Hook 异常行为](https://github.com/NousResearch/hermes-agent/blob/3c27eb6234bf91b8ceee9e9071591b31e9b148cb/hermes_cli/plugins.py#L1744-L1777) 这只证明宿主继续运行，不等于健康路径仍会被安全拦住。
- 固定 Plugin 文件没有通用 `shutdown`/`on_unload`。Platform Adapter 有 `connect`/`disconnect` 生命周期，但它不提供 Plugin 数据迁移、刷盘或关闭失败合同。[Adapter 生命周期](https://github.com/NousResearch/hermes-agent/blob/3c27eb6234bf91b8ceee9e9071591b31e9b148cb/gateway/platforms/base.py#L3470-L3495)
- Plugin 与 Hermes 同进程、同系统身份运行，是受信任 Python 代码；没有进程内数据或 secret 沙箱。[Hermes Plugin 信任边界](https://github.com/NousResearch/hermes-agent/blob/3c27eb6234bf91b8ceee9e9071591b31e9b148cb/SECURITY.md#L134-L147)

### 3.2 目标现场

- 目标 venv 为 Python `3.11.15`；这是解释器版本，不是支持期限。
- SQLite 引擎为 `3.53.1`；`sqlite3.threadsafety == 3` 表示 Python DB-API 的 **serialized** 线程安全等级，不表示“允许 3 个线程”。`sqlite3.Connection.backup` 和 `serialize` 均存在。[Python `sqlite3` 事务控制](https://docs.python.org/3.11/library/sqlite3.html#transaction-control) [Python在线备份接口](https://docs.python.org/3.11/library/sqlite3.html#sqlite3.Connection.backup)
- `cryptography 48.0.1` 可导入；它提供认证加密等密码学原语，但不自行提供密钥保存、数据库事务或备份合同。[`cryptography` AEAD 文档](https://cryptography.io/en/48.0.0/hazmat/primitives/aead/)
- 不可导入、即现场未安装：`keyring`、`sqlcipher3`、`pysqlcipher3`、APSW、`aiosqlite`、PyNaCl、PyCryptodome。不能在 HOW 中把这些包写成“不安装即可用”。
- systemd 为 `249.11-0ubuntu3.21`。该版本支持 `LoadCredential=`，每个 unit 累计 `1 MB` 是所有凭据内容的总字节上限，不是密钥长度或加密强度；目标 Partner unit 当前没有配置 `LoadCredential*`/`SetCredential*`，现场也未发现 `systemd-creds`、`keyctl` 或 `secret-tool` 命令。[Ubuntu systemd 249 凭据文档](https://manpages.ubuntu.com/manpages/jammy/man5/systemd.exec.5.html)
- 目标 unit 仍以 root 运行，未设置 `StateDirectory`、`RuntimeDirectory`、`ConfigurationDirectory`；`ProtectSystem=no`、`ProtectHome=no`、`PrivateTmp=no`，也未设置 `ReadWritePaths`、`ReadOnlyPaths` 或 `InaccessiblePaths`。这些是当前 unit 的隔离配置事实，不表示系统本身没有 Unix 文件权限；它们也不能证明健康数据对 root 保密。

结论是：目标已验证的无新增依赖构件为标准 SQLite、`cryptography` 与一般 OS/systemd 文件/环境能力；没有已接线的独立密钥库，也没有 Hermes 管理的数据目录、密钥或故障关闭生命周期。

## 4. 哪些入口会进入普通历史

| 路径 | 普通 Session / FTS | 普通 Memory | 日志与外部留存边界 |
|---|---|---|---|
| Adapter 收到消息但尚未调用标准 handler | 框架不自动写入 | 不自动触发 | Adapter 自己的代码与日志行为仍需约束 |
| Adapter 调用标准 `_handle_message` | 创建/取得 Session，并保存 user、assistant、tool call/result；FTS 索引正文与工具字段 | 进入普通会话生命周期，可能供 Memory review 使用 | 普通 gateway/provider/异常日志仍存在 |
| 模型调用 Plugin Tool | 参数和结果随 Agent transcript 进入 Session/FTS | 可能进入普通 Memory 生命周期 | Tool 自身还可写文件、日志或外部系统 |
| 已识别的 Plugin slash command | 在 Session 创建前直接处理，不自动写 Session/FTS | 不自动触发普通 Memory | 命令元数据和异常可能写日志；微信端仍保留收发内容 |
| Plugin CLI command | 不进入 gateway Session | 不触发 gateway Memory | 终端与 shell 历史是 Hermes 外部边界 |
| Command 内直接 `ctx.dispatch_tool` | registry 不自动把调用写入 Session | 不自动触发 | 具体 Tool 的副作用、状态和日志未知 |
| `ctx.llm` | out-of-band；不创建普通 Session/FTS | 不触发普通会话 Memory | Hermes 记录调用元数据；provider/relay 会收到请求且其留存未知 |

固定依据：

- 普通 Session 的 `state.db` 保存完整消息，FTS 索引 `content`、`tool_name`、`tool_calls`，还可保存实际发给 API 的 `api_content`。[Session 存储范围与字段](https://github.com/NousResearch/hermes-agent/blob/3c27eb6234bf91b8ceee9e9071591b31e9b148cb/website/docs/developer-guide/session-storage.md#L2-L27) [消息与 API 内容](https://github.com/NousResearch/hermes-agent/blob/3c27eb6234bf91b8ceee9e9071591b31e9b148cb/website/docs/developer-guide/session-storage.md#L75-L123)
- Gateway 把 Adapter 接到标准 handler；该路径取得或创建 Session，并最终保存所有新增的非 system 消息，包括 Tool 调用与结果。[Adapter 接线](https://github.com/NousResearch/hermes-agent/blob/3c27eb6234bf91b8ceee9e9071591b31e9b148cb/gateway/run.py#L10255-L10268) [Session 创建点](https://github.com/NousResearch/hermes-agent/blob/3c27eb6234bf91b8ceee9e9071591b31e9b148cb/gateway/run.py#L15168-L15168) [transcript 保存](https://github.com/NousResearch/hermes-agent/blob/3c27eb6234bf91b8ceee9e9071591b31e9b148cb/gateway/run.py#L16798-L16850)
- 已识别的 Plugin slash command 在 Session 创建前执行并直接返回。[Plugin slash command 分支](https://github.com/NousResearch/hermes-agent/blob/3c27eb6234bf91b8ceee9e9071591b31e9b148cb/gateway/run.py#L14374-L14389) `ctx.dispatch_tool` 直接进入 Tool registry，registry 本身不写 Session。[直接 Tool dispatch](https://github.com/NousResearch/hermes-agent/blob/3c27eb6234bf91b8ceee9e9071591b31e9b148cb/hermes_cli/plugins.py#L552-L578) [registry dispatch](https://github.com/NousResearch/hermes-agent/blob/3c27eb6234bf91b8ceee9e9071591b31e9b148cb/tools/registry.py#L706-L735)
- 官方把 `ctx.llm` 定义为 Plugin-owned 的 out-of-band 调用，并说明 provider/model/purpose/token 元数据审计及常规 fallback。[`ctx.llm` 执行与审计边界](https://github.com/NousResearch/hermes-agent/blob/3c27eb6234bf91b8ceee9e9071591b31e9b148cb/website/docs/developer-guide/plugin-llm-access.md#L354-L407)

“不自动进入普通 Session”只描述 Hermes 固定核心的默认写入，不是端到端零留存承诺。上述 no-history 路径尚未用目标现场合成 canary 验证，且任何 Plugin 自己写日志、将正文放入 `purpose`/异常文本、调用外部 Tool 或发送模型请求，都会产生额外暴露面。

## 5. 模型接收方事前预检

### 5.1 已证实能力

- `ctx.llm.complete()` 可以指定 `provider`、`model`、`temperature`、`max_tokens`、`timeout`、`agent_name`、`profile` 和 `purpose`；信任规则可以限制请求的 provider/model/agent/profile。[`ctx.llm` 参数](https://github.com/NousResearch/hermes-agent/blob/3c27eb6234bf91b8ceee9e9071591b31e9b148cb/website/docs/developer-guide/plugin-llm-access.md#L176-L213) [信任规则](https://github.com/NousResearch/hermes-agent/blob/3c27eb6234bf91b8ceee9e9071591b31e9b148cb/website/docs/developer-guide/plugin-llm-access.md#L280-L344)
- Plugin 可以在发送前读取名义配置来核对当前 provider/endpoint；截至 2026-08-16 的现场非敏感基线是名义 provider `jojo`、endpoint `https://max2.jojocode.com/v1`、API mode `codex_responses`。本次没有读取凭据或发送请求，不能把它冒充实际下游接收方。

### 5.2 已证实缺口

- 正式 `ctx.llm` 没有 `base_url`/endpoint 参数、禁用 fallback 参数、endpoint/实际接收方允许表、dry-run/route preview、发送前最终接收方回调，也没有 relay 下游身份或数据保留证明。官方明确说明调用使用通常的 fallback；调用结果中的 provider/model/usage/audit 是调用后的归因。[Fallback 与事后结果](https://github.com/NousResearch/hermes-agent/blob/3c27eb6234bf91b8ceee9e9071591b31e9b148cb/website/docs/developer-guide/plugin-llm-access.md#L258-L279) [通常 fallback](https://github.com/NousResearch/hermes-agent/blob/3c27eb6234bf91b8ceee9e9071591b31e9b148cb/website/docs/developer-guide/plugin-llm-access.md#L354-L378)
- 固定 auxiliary client 对支付/额度、连接、限流、模型不兼容或无效响应等错误可绕过显式 provider 的限制，依次尝试配置 fallback 或主 Agent 模型；同一 messages 会发给被选中的 fallback。[固定 fallback 判断与顺序](https://github.com/NousResearch/hermes-agent/blob/3c27eb6234bf91b8ceee9e9071591b31e9b148cb/agent/auxiliary_client.py#L9014-L9125)
- 普通 Agent 的 request middleware/`pre_api_request` 位于 conversation loop，但 `ctx.llm` 直接走 auxiliary client；固定 auxiliary client 不调用这些 middleware/Hook。因此普通 Agent 的发送前 Hook 不能冒充 `ctx.llm` 的强制闸门。[普通 Agent request Hook](https://github.com/NousResearch/hermes-agent/blob/3c27eb6234bf91b8ceee9e9071591b31e9b148cb/agent/conversation_loop.py#L2084-L2161) [`ctx.llm` 直达 auxiliary client](https://github.com/NousResearch/hermes-agent/blob/3c27eb6234bf91b8ceee9e9071591b31e9b148cb/agent/plugin_llm.py#L919-L1008)
- 当前 relay `max2.jojocode.com` 的真实下游接收方、日志和保留政策没有一手证据；运行时 provider 覆盖、credential pool 与实际 fallback 组合也没有发送前正式预览接口。

所以当前可在发送前确认的是**名义路由配置**，不是所有实际健康数据接收方。事后审计不能替代主人发送前知情同意。

## 6. 通用备份、恢复与删除

### 6.1 固定源码行为

- 全量备份遍历 `get_default_hermes_root()`；排除项和 symlink 处理是硬编码，没有 Plugin 注册 include/exclude 的接口。`backups/`、venv 与 cache 等目录整体排除；SQLite sidecar 只按 `.db-wal`、`.db-shm`、`.db-journal` 后缀排除。[排除规则](https://github.com/NousResearch/hermes-agent/blob/3c27eb6234bf91b8ceee9e9071591b31e9b148cb/hermes_cli/backup.py#L49-L78) [扫描与安全复制](https://github.com/NousResearch/hermes-agent/blob/3c27eb6234bf91b8ceee9e9071591b31e9b148cb/hermes_cli/backup.py#L211-L274)
- 只有文件后缀恰为 `.db` 才走 `sqlite3.Connection.backup()` 一致快照；`.sqlite`、`.sqlite3`、`.enc` 等作为普通文件复制。WAL 可能包含已提交但尚未并入主文件的数据，不能把忽略 WAL 当作普通复制安全。[全量备份后缀分支](https://github.com/NousResearch/hermes-agent/blob/3c27eb6234bf91b8ceee9e9071591b31e9b148cb/hermes_cli/backup.py#L504-L620) [SQLite WAL 文件含义](https://www.sqlite.org/wal.html#the_wal_file) [SQLite 在线备份一致性](https://www.sqlite.org/backup.html)
- ZIP 使用 `ZIP_DEFLATED, compresslevel=6`；`6` 是压缩速度与压缩率等级，不是加密强度，该 ZIP 没有加密。[ZIP 创建](https://github.com/NousResearch/hermes-agent/blob/3c27eb6234bf91b8ceee9e9071591b31e9b148cb/hermes_cli/backup.py#L596-L596)
- import 是覆盖式恢复，不删除目标中 archive 未包含的旧文件；自动设为 `0600` 的特殊文件只有 `.env`、`auth.json`、`state.db`。`0600` 表示 Unix DAC 下只有文件 owner 可读写、group/other 无权限，不等于 root 无法读取；任意 Plugin DB/key 不在该权限名单。[恢复与权限](https://github.com/NousResearch/hermes-agent/blob/3c27eb6234bf91b8ceee9e9071591b31e9b148cb/hermes_cli/backup.py#L738-L870)
- quick snapshot 是固定白名单，不包含任意 Plugin 数据；默认 `keep=20` 中 `20` 是最多保留的 quick snapshot 个数，不是天数。pre-update 全量归档默认 `keep=5` 中 `5` 同样是最多保留份数。[Quick 范围与保留](https://github.com/NousResearch/hermes-agent/blob/3c27eb6234bf91b8ceee9e9071591b31e9b148cb/hermes_cli/backup.py#L971-L1003) [Pre-update 保留](https://github.com/NousResearch/hermes-agent/blob/3c27eb6234bf91b8ceee9e9071591b31e9b148cb/hermes_cli/backup.py#L1571-L1605)

直接后果：

- 健康 DB、key、临时文件只要位于 Hermes root 且不命中硬编码排除项，就可能进入同一份未加密全量 ZIP；密钥与密文同包不能证明静态保护。
- DB 若不以 `.db` 结尾，不会获得 SQLite 在线快照；其 sidecar 也可能不匹配仅针对 `.db-*` 的排除规则，形成不一致组合。
- 放入名为 `backups` 的目录会因硬编码目录名被跳过，但这只是当前源码行为，不是健康 Plugin 的正式备份/排除合同。
- 通用 import 没有 Plugin schema 迁移、恢复后权限验证、健康级完整性认证或删除旧副本合同；没有按主人/健康画像删除 ZIP 内条目的接口。

### 6.2 当前现场

- 默认与 Partner 两份配置均为 `pre_update_backup: false`。
- `/root/.hermes/backups` 当前递归有 `587` 个文件；`587` 是文件数量，不等于 587 个备份代次。root quick snapshot、Partner `backups/`、Partner quick snapshot 当前文件数均为 `0`。
- 未发现名称含 `backup` 的用户级 systemd timer。本次没有读取任何归档，所以无法判断既有 587 个文件是否包含历史健康内容；当前健康 Plugin 尚未启用。
- 服务器外备份、宿主机或云平台快照仍未知。源码和这次主机检查都不能排除它们。

结论是：通用 backup 可作为“存在的一般文件复制机制”的候选事实，但不能直接作为健康 Plugin 的备份、恢复或永久删除机制。

## 7. 证据分级与未完成实验

| 分级 | 已得到的结论 |
|---|---|
| 官方保证 | Python SQLite 事务/在线备份、`cryptography` 密码学原语、systemd 249 Credential 能力；Hermes Plugin、Session、`ctx.llm` 和通用备份文档所述接口 |
| 固定源码行为 | Plugin 无受管 data/config/per-plugin secret；加载/Hook 失败继续；普通 handler 持久化 Session；slash/direct dispatch/`ctx.llm` 不自动建普通 Session；`ctx.llm` fallback 与无事前 route preview；backup 的固定排除、`.db` 快照、无加密 ZIP、quick/restore 范围 |
| 现场已验证 | commit/Python/SQLite/cryptography 版本和模块可用性；缺少 SQLCipher/keyring 等依赖；systemd unit 当前未接 Credential/目录/文件隔离；非敏感备份配置和文件数量 |
| 仍未知 | 服务器外备份；relay 下游接收方与保留；最终密钥来源和恢复流程；未来 Plugin 自身日志；恢复后的 owner/mode/完整性；真实 fallback 组合 |
| 需主人另行批准 | 安装合成 canary Plugin；创建测试 DB/key；改 unit 或重启；发送 `ctx.llm`/微信测试；故障注入 fallback；创建/恢复/删除备份、密钥或画像；任何真实健康资料实验 |

未执行实验不应被写成失败：slash command 和 `ctx.llm` 的普通历史隔离是固定源码结论，尚不是目标现场运行证据；provider/relay 的真实外部留存也不能仅靠本地 canary 证明。

## 8. 对 Ticket 49 的 CAN 输入边界

后续接收方路线 CAN 以及在其闭合后的 Ticket 49，只能使用以下具体事实：

- 可选构件限于现场实际存在的标准 SQLite、`cryptography`、一般 OS/systemd 文件与环境能力，以及 Plugin 自己明确实现的逻辑；SQLCipher、keyring、受管 Plugin state/secret/backup 不能假定存在。
- 健康正文不能经普通 Agent Tool/transcript；无普通 Session 的入口只可从已核验的 Adapter 前置处理、Plugin command/direct dispatch 和 `ctx.llm` 能力中判断，并必须另外控制 Plugin/Tool/日志/外部接收方。
- `ctx.llm` 不能被描述为“已能发送前锁定所有实际接收方”；通用 backup 也不能被描述为“已覆盖健康恢复与永久删除”。
- 若 HOW 选择使用 systemd Credential、专用备份、恢复校验或永久删除覆盖，它们是需要实现和验证的依赖，不是当前已接线能力。

本票没有选择这些构件如何组合，也没有改变 TO。
