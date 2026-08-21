# 当前 Partner Hermes 基线、Plugin 生命周期与可信执行边界（Ticket 78）

## Answer

截至 **2026-08-20 12:49（Asia/Shanghai）**，正式 Partner 仍运行 Hermes Agent `v0.20.0 (2026.8.3)`，安装树 HEAD 为 `3c27eb6234bf91b8ceee9e9071591b31e9b148cb`，但不是干净发行版。现场仍有四个 tracked 修改和一个 untracked 文件；Partner 由 root 用户级 systemd manager 以 `root`、完整有效 capability、无 systemd sandbox 的方式运行。官方当前最新发行已经是 `v0.20.4 (2026.8.18)`，这只证明版本漂移，不在本票选择升级路线。[L1][L2][O1]

Hermes v0.20.0 **真实提供**一个不改核心即可注册 Tool、Hook、Middleware、Platform、Skill 和辅助任务的进程内 Plugin 扩展面；普通 Plugin 受 `plugins.enabled` allow-list 约束，非 bundled Plugin 覆盖内置 Tool 还要单独授权。[F1][F2] 但当前 Partner 的普通 Plugin enabled 清单为空，profile `plugins/` 中没有 `plugin.yaml`/`plugin.yml`，健康 Plugin 没有部署。这个结论不等于“没有任何 Plugin 代码”：bundled backend 会自动加载，bundled platform 会注册延迟加载器；当前实际配置的 Telegram、Weixin 正属于需另行区分的聊天平台路径。[L3][L4][F3]

固定生命周期合同**不能证明健康管家所需的可信运行边界已经成立**：Plugin 加载或 `register()` 失败不会阻止 Hermes 继续启动；Hook 与 Middleware 回调异常被记录后继续原流程；一次 `register()` 中已经写入的部分注册项不会因后续异常自动回滚；启用、停用、更新或删除对长驻 Gateway 不提供可核验的热卸载/teardown；Plugin 也没有统一的状态导出、清理、迁移或完整性证明合同。[F3][F4][F5][F6] 因而“systemd active”“Gateway 能聊天”“普通 enabled 清单为空”都不能分别冒充“健康 Plugin 已加载”“安全闸门失败关闭”或“没有任何扩展代码”。

当前基座具备**部分可枚举与可迁移基础**：版本、Git 脏差异、profile 路径、Plugin manifest、Skill 文件、Cron 数量、依赖集合和日志路径都能单独枚举。本次现场数得 Partner profile 中 `80` 个 `SKILL.md`，而 `hermes skills list --source local --enabled-only` 只显示 `7` 个 local enabled 项；两者不是同一个全集。当前没有一份原生、单一、可验证的资产清单把源码提交与脏补丁、实际生效 Skill、Plugin 代码与自有状态、配置、Cron、权威文档、依赖和日志策略绑定为同一代际，所以尚不能证明“复制所有文档和 Skill 后即可完整迁移”。[L3][L4][L5]

本票因此得到的是：**Partner Hermes 的基础扩展能力成立；健康 Plugin 的完整生命周期、失败关闭、入口与日志隔离、可信前提持续观测和权威资产闭包均未成立或未证明。** 这是一项 CAN 能力边界，不选择 Plugin 结构、部署、存储、迁移或升级 HOW。

## 1. 范围、证据层级与禁止动作

- 当前现场快照：`2026-08-20T12:41:45+08:00` 至 `12:49`，主机 `findjoin`，正式 `partner` profile。
- 证据优先级：同一时点目标现场 `[L*]` > 目标 HEAD 固定官方源码 `[F*]` > 官方当前发行事实 `[O*]` > 当前仓库中尚未部署的候选实现 `[R*]`。
- 只执行版本、Git 元数据、systemd/proc 元数据、文件元数据、Hermes 脱敏状态/清单及 hash/count 命令；没有运行模型、读取聊天或健康正文、发送 Telegram/微信、读取凭据值、安装/启停/更新/删除 Plugin、建立 Cron、重启服务、制造故障或修改正式 Partner 配置。
- `hermes status --all` 自称输出适合分享的脱敏状态，但仍会显示截断凭据片段和聊天 home 标识；这些值已从本报告丢弃。报告只保留“是否配置”和平台名称。
- 本次没有读取日志正文。既有 Gateway、Cron ticker 以及 Hermes CLI 自身仍可能按正常运行写 heartbeat/日志，因此文件 mtime 变化不能被解读为本次改变了产品状态。
- 当前仓库 `ops/partner-health-steward/` 中存在 `health-autonomy`、`health-guard`、`health-steward` 三份候选 manifest 和大量未提交工作；它们是仓库源码事实，不是目标现场已部署事实。[R1]

## 2. 2026-08-20 同一时点现场指纹

| 核验项 | 当前事实 | 能证明 | 不能证明 | 来源 |
|---|---|---|---|---|
| 主机与版本 | `findjoin`；Linux `6.8.0-124-generic` x86_64；Hermes `v0.20.0 (2026.8.3)`；Python `3.11.15`；OpenAI SDK `2.24.0` | 当前核验对象和解释器版本 | 当前最新发行能力已存在 | [L1] |
| 安装树 | `/usr/local/lib/hermes-agent`；HEAD `3c27eb6234bf91b8ceee9e9071591b31e9b148cb`；describe `v2026.8.3-dirty` | 目标可固定到一个官方提交和现场差异 | 现场等于干净官方包 | [L1][O2] |
| 脏差异 | modified：`agent/display.py`、`agent/transports/codex.py`、`gateway/run.py`、`package-lock.json`；untracked：`gateway/skill_disclosure.py`；tracked diff 为 82 insertions / 68 deletions | 必须保留的现场定制范围 | 这些定制属于官方或健康 Plugin | [L1] |
| 脏改位置 | `display._get_cute_tool_message`；`ResponsesApiTransport`；`TurnRunner` 三处；`GatewayRunner` 四处 | 官方合同与现场定制不能混写；`plugins.py`、`plugins_cmd.py`、`middleware.py` 没有出现在 dirty 清单 | 仅凭函数名证明脏改全部行为安全 | [L1] |
| Partner unit | root 用户 manager 中 `loaded/enabled/active/running`；MainPID `143611`；自 `2026-08-07 07:30:33 +08:00` 运行；`Restart=always`、`RestartUSec=5s` | systemd 会管理并尝试重启该 Gateway 进程 | Plugin 已加载、健康功能可用或业务结果成功 | [L2] |
| systemd 作用域 | 系统 manager 中同名单元 `not-found/inactive`；root `Linger=yes`；正确单元位于 `/root/.config/systemd/user/hermes-gateway-partner.service` | 后续检查必须使用 root 用户作用域 | 系统级 unit 保护已存在 | [L2] |
| 启动入口 | `/usr/local/lib/hermes-agent/venv/bin/python -m hermes_cli.main --profile partner gateway run`；cwd `/root/.hermes/profiles/partner` | 正式 profile 与进程入口 | 其他入口不能访问同一状态 | [L2] |
| 进程权限 | UID/GID `0:0`；全部列出的 permitted/effective/bounding capabilities 为 `000001ffffffffff`；`NoNewPrivs=0`、`Seccomp=0` | 当前不是受限账户 | root 无法替换、读取或跨 profile 访问 | [L2] |
| unit sandbox | `ProtectSystem=no`、`ProtectHome=no`、`PrivateTmp=no`、`NoNewPrivileges=no`；无 `ReadOnlyPaths`、`ReadWritePaths`、`InaccessiblePaths`、drop-in | 当前 unit 没有这些 systemd 隔离门 | 应用内部不存在任何检查 | [L2] |
| 同机其他 Hermes | 默认 `hermes-gateway.service` 同样 active，PID `143552`、cwd `/root/.hermes`，也以 root 运行；Partner PID 没有子进程或 TCP/Unix 监听被 `ss` 归属于它 | `status --all` 报告的两个 PID 实际分属 default 与 partner，不可混写 | 两个 profile 有账户级或内核级隔离 | [L2] |
| profile 权限 | profile `0700 root:root`；`config.yaml`/`.env` 为 `0600`；`state.db` 为 `0644`，但受父目录 `0700` 约束；`skills/`、`cron/`、`logs/` 为 `0700`，`plugins/` 为 `0755` | 非 root 普通账户受目录权限阻止 | 同机 root/default Gateway 不能读取或改写 Partner | [L4] |
| 依赖指纹 | `pip freeze --all` 共 119 行，排序 SHA-256 `da0af4616356466ac4bded656e9b70ffc1f649fbb413a098d7ccb7c96ea3e35f`；关键包见附录 | 同一环境可做漂移比较 | 这些依赖在另一台机器已完整恢复或兼容 | [L5] |
| 微信适配器 | 工作树 `gateway/platforms/weixin.py` SHA-256 `e745f2bc7faaa6bbbdd8615fbfc79ca327ca6d0e7700620f37fc21fed14a178a`，与 8 月 16 日固定 HEAD 值一致，且不在 dirty 清单 | 当前 Weixin 文件仍可对准固定提交 | 微信端到端、白名单或唯一主人已通过 | [L1][L5] |

目标官方当前最新稳定发行由 GitHub `releases/latest` 指向 `v0.20.4 (2026.8.18)`；目标仍在 `v0.20.0`。这只记录漂移，不能把 v0.20.4 的任何接口归因给当前现场，也不在本票提出升级方案。[O1]

## 3. 当前 Plugin、Skill、Cron 与聊天入口

### 3.1 Plugin 的准确表述

- `hermes --profile partner plugins list --enabled --json` 返回空数组；`--no-bundled --json` 也为空；profile `plugins/` 下没有 manifest。[L3][L4]
- 因此当前**没有 ordinary/user/project 健康 Plugin 被启用或安装到 Partner profile**。
- 不能写成“运行时没有 Plugin”：固定 loader 会自动加载 bundled backend，并把 bundled platform 注册成 deferred loader；配置的聊天平台首次使用时才导入其模块。[F3]
- 当前仓库的三个健康候选 Plugin manifest 只在 `D:\cohermes\ops\partner-health-steward\plugin\`，不在现场 `/root/.hermes/profiles/partner/plugins/`。[R1][L4]

### 3.2 Skill 已从旧快照显著变化

- profile 文件系统当前有 `80` 个 `SKILL.md`，聚合内容指纹为 `2f6fba74773230d61ba890d297c44f2548d313a3aa3333c34fea55548e03c494`；其中包括多级分类、`medical` 及其 references/scripts，而不是 8 月 16 日可概括的“仅 medical”。[L4]
- `hermes skills list --source local --enabled-only` 只列出 `7` 个 local enabled 项。它是 Hub/本地安装管理视图，不是 profile 文件树的完整 manifest 清单；本次不能把 80 个文件都称为“当前模型一定可发现/采用”，也不能把 7 个称为全部可迁移 Skill。[L3][L4]
- `/root/.hermes/skills/health-steward` 在默认 root home 中存在，但不位于 Partner profile 的 `skills/` 路径；没有证据证明正式 Partner 进程会加载它。[L4]
- Plugin 随附 Skill 的固定合同是显式命名空间 `plugin:name`，不进入平铺 Skill 索引，需要显式 `skill_view`；所以“Plugin 带 Skill”也不等于每轮自动运行。[F7]

### 3.3 Cron 与聊天入口

- `cron status` 显示 Gateway/ticker 在运行，但 `cron list` 为 `No scheduled jobs`，当前 job 数为 `0`；profile 中只有 `executions.db`、锁、heartbeat/last-success 和空的 output 基础目录。[L3][L4]
- 当前 profile 配置了 **Telegram** 与 **Weixin** 两个 messaging platform；其他由脱敏 status 列出的平台均未配置。[L3]
- 本次没有读取两个平台的 home 标识、allow-list 值或消息；也没有发送 canary。因此只能证明“两个入口配置存在”，不能证明微信是唯一健康入口、Telegram 已被排除、每条消息来源可信、白名单正确、主人是唯一使用者或入站—模型—回复闭环当前成功。
- Hermes 的 CLI/chat、Cron、`send`、Gateway 内部 dispatch 等代码入口仍存在。是否允许它们触达健康能力取决于未来 Plugin 的收敛合同；当前普通 Plugin 不存在，不能把平台配置本身当成入口收敛。

## 4. 固定 v0.20.0 Plugin 生命周期合同

### 4.1 发现、选择与注册

固定 manager 扫描四类来源：bundled、profile `plugins/`、显式允许的项目 `.hermes/plugins/`、Python entry points。显式 disabled 优先；exclusive/model-provider 走各自路径；bundled backend 自动加载；bundled platform 延迟注册；其余普通 Plugin 只有在 `plugins.enabled` 中才加载。[F3]

一次普通 Plugin 加载发生在 Hermes Python 进程内：导入目录模块/entry point，创建 `PluginContext`，调用 `register(ctx)`，把 Tool、Hook、Middleware、Command、Platform、Skill、辅助任务等对象写入进程内 registry。[F4] 这证明可扩展，但没有形成独立健康服务边界。

### 4.2 安装、启用、更新、停用与删除

| 操作 | 固定行为 | 能证明 | 明确不能证明 |
|---|---|---|---|
| install | 用 Git `--depth 1` clone 到临时目录，读取 manifest、校验 manifest version，移入 profile plugin 目录；交互默认不启用；命令明确提示重启 Gateway 才生效。[F5] | 有受支持的文件安装入口和默认 opt-in | 源码签名、供应链真实性、固定 commit、测试通过、运行中原子切换 |
| enable | 把规范 key 写入 `plugins.enabled`，移出 disabled；非 bundled 的 Tool override 默认拒绝并需另授权；提示“next session”生效。[F5] | 普通第三方代码有显式 allow-list 与高权限 override 二次门 | 正在运行的长驻 Gateway 已热加载、register 成功或安全检查成功 |
| update | 对插件目录执行 Git pull 并清理 bytecode。[F5] | 有更新入口 | 版本 pin、签名、回滚、迁移、不中断切换；当前报告未执行 |
| disable | 从 enabled 删除并加入 disabled，提示“next session”生效。[F5] | 下次发现时 loader 会跳过 | 当前进程内已经注册的回调已卸载、后台任务已停止、状态已封存 |
| remove | `shutil.rmtree(target)` 删除安装目录。[F5] | 文件目录可移除 | enabled/disabled 配置清理、运行中 unregister、Plugin 自有 DB/日志/Skill/外部资源清理、可恢复卸载 |

固定 public manager/context 中没有统一 `unregister`、`teardown`、`shutdown`、Plugin state export/import 或 migration callback；`force=True` 只是清空 manager registry 后重新发现，并不调用旧 Plugin 清理器。[F3][F4] 因此生命周期的准确结论是“安装/配置/下次加载可管理”，不是“完整可事务化安装和卸载”。

### 4.3 Hermes 同生共停的保证边界

- 对**只在 `register(ctx)` 中注册进程内对象且不自行派生进程/线程/外部任务**的 Plugin，Gateway 进程退出会终止这些进程内对象；systemd 重启 Gateway 后会重新发现和注册。这是可用的基础能力。[F3][F4][L2]
- Hermes Plugin 合同允许任意 Python import/register 代码，也没有统一 teardown/supervision 接口。源码不能阻止 Plugin 自己创建脱离 Gateway 的 subprocess、外部任务或状态副作用；所以“任何 Plugin 都必然与 Hermes 同生共停”不成立。
- 当前没有健康 Plugin，无法对真实健康实现证明同生共停；`Restart=always` 只证明 Gateway 进程会被尝试拉起，不证明 Plugin 重载成功或健康状态一致。[L2][L3]

## 5. 默认失败语义不是健康 fail-closed

1. `_load_plugin()` 捕获 import/`register()` 异常，写 `loaded.error` 和 warning，随后把结果留在 Plugin 清单；它不终止 Hermes。[F4]
2. `register(ctx)` 对共享 registry 是逐项直接写入。若 Plugin 先注册 Hook、后续再抛异常，catch 分支没有回滚已写 registry；因此可能出现“清单报 load error，但部分 callback 仍在进程内”的非事务状态。[F4]
3. `invoke_hook()` 与 `invoke_middleware()` 分别对每个 callback 捕获异常、记 warning、继续后续 callback/基础流程。[F6]
4. `pre_gateway_dispatch` 虽可在正常返回时给出 `skip/rewrite/allow`，但异常仍经过上述隔离语义；不能把它单独当成主人准入或危险健康消息的天然 fail-closed 闸门。[F6][F8]
5. Middleware 可以改写或包裹模型/Tool 执行，但固定执行链在 callback 异常时以继续链为默认，仍不是天然 fail-closed。[F6][F9]

所以后续健康 Plugin 若要实现“初始化前完全不启动”“可信前提丢失即停止健康处理”，必须由可验证的具体能力把**加载失败、部分注册、Hook/Middleware 异常、状态不可读、渠道身份不可确认**映射到明确停止结果。当前基座不自动给出该保证，本票也不选择实现办法。

## 6. 入口、日志与可信前提隔离

### 6.1 已有的逻辑分隔

- `--profile partner`、独立 cwd、独立 `config.yaml/.env/state.db/skills/plugins/cron/logs` 路径，使默认与 Partner 的普通文件路径可区分。[L2][L4]
- Partner unit 名称独立，可用 unit filter 查询 systemd 状态；profile 日志目录为 `0700`，日志文件位于该目录。[L2][L6]
- 当前 `gateway/platforms/weixin.py` 未脏改，固定渠道研究可对准目标提交。[L1][L5]

### 6.2 仍未形成可信隔离

- default 与 Partner 均以 root 运行并共享安装树；目录 `0700` 对另一个 root 进程没有隔离意义。Partner unit 没有 systemd 文件、权限、namespace 或 syscall sandbox。[L2][L4]
- Partner 的 stdout/stderr 都进普通 journal，`SyslogIdentifier` 与 `LogNamespace` 为空；虽然可以按 unit 查询，但没有独立 journald namespace。profile 日志目录内文件为 `0644 root:root`，依靠父目录 `0700`；没有 Plugin 专用日志权限边界。[L6]
- 本次未读日志正文，因此不能证明日志不含消息、身份、健康内容、模型输入或 Plugin 参数。当前只证明日志路径和权限元数据。
- 两个聊天平台同时配置；allow-list/白名单值因禁止读取身份与 secret 而未核验。当前 `status` 也没有一个不含身份值、可证明“唯一微信入口 + 单一使用者 + 当前白名单有效”的统一可信状态。
- `systemd active`、最近 ticker heartbeat、日志持续写入和平台 `configured` 都只代表局部技术状态；它们不证明初始化完成、主人可信、健康资料可用或安全闸门有效。

## 7. 权威资产枚举与迁移基础

### 7.1 当前可以逐项枚举

| 资产面 | 当前枚举手段 | 本次结果 |
|---|---|---|
| Hermes code | Git HEAD/describe/status/name-status/hash | 固定 commit + 五个 dirty 路径 [L1] |
| Python/Node dependency | 排序后的 `pip freeze` hash、关键包版本、`package-lock.json` hash | 119 行依赖 + 两个指纹 [L5] |
| profile configuration | realpath/stat 与 Hermes 脱敏 status | 路径、权限、配置入口和平台是否配置；未读取值 [L3][L4] |
| Plugin | `plugins list` + manifest find | ordinary enabled 0；profile manifest 0 [L3][L4] |
| Skill | 文件 manifest count/hash + Hub/local CLI view | 文件树 80；CLI local enabled 7；两者语义不同 [L3][L4] |
| Cron | `cron status/list` + cron 路径元数据 | jobs 0；ticker/execution 基础文件存在 [L3][L4] |
| logs | 路径、权限、大小、mtime；不读正文 | profile 独立目录，但无 root/journal 隔离 [L6] |
| 项目权威链 | 当前仓库 Map/Tickets/Evidence/ADR/ops 源码 | 文件存在且大量为 dirty/untracked；不在正式 Partner profile [R1] |

### 7.2 当前不能宣称“完整可迁移”

- 没有单一 manifest 声明迁移闭包，也没有把 80 个 Skill 文件与实际生效的 7-item 管理视图解释为同一权威集合。
- 没有已部署健康 Plugin，因此也没有可现场验证的 Plugin 自有数据、schema version、migration callback、外部依赖或卸载残留清单。
- 现场 dirty 源码不是只凭 commit 可复原；必须连同补丁或不可变制品另行固定，但本票不选择打包 HOW。
- `config.yaml/.env`、平台授权、state DB、Cron DB、Skill curator/hub 元数据、项目文档和候选健康源码分布在不同路径；“复制文档和 Skill”不会自动包含运行配置、依赖、脏补丁或 Plugin 状态。
- 当前仓库本身有大量未提交和 untracked 权威材料；`git clone` 单独不能复原它们。[R1]

因此当前可证明的是“构成迁移清单的原始资产可分别发现”，不能证明“权威资产闭包、同代际快照、导入验证和迁移后可用性”。这些事实应交给后继可迁移性 CAN，而不是在此决定工具或包格式。

## 8. 能力结论矩阵

| C01 子问题 | 当前结论 | 能证明 | 不能证明／阻塞事实 |
|---|---|---|---|
| 版本与差异可固定 | **有，带条件** | commit、dirty 文件、依赖和关键文件 hash 可取 | dirty patch 尚无单一不可变制品 |
| 普通 Plugin 显式准入 | **有** | allow-list、disabled 优先、Tool override 二次授权 | bundled backend/platform 不受同一普通 enabled 结论概括 |
| Plugin 注册扩展 | **有** | Tool/Hook/Middleware/Platform/Skill/aux task 等进程内接口 | 健康业务语义与安全性 |
| 安装与卸载管理 | **部分** | Git 安装、启停、更新、目录删除入口 | 事务安装、运行时 unload、teardown、state migration、供应链证明 |
| 加载失败关闭 | **无** | 错误被记录、基础 Hermes 继续 | 健康处理自动停止；部分注册自动回滚 |
| Hermes 同生共停 | **仅限进程内、守约 Plugin** | 进程内注册对象随 Gateway 进程退出 | 任意后台副作用受监督；当前健康实现通过 |
| 聊天入口收敛 | **未证明** | Telegram/Weixin 两个已配置入口可枚举 | 唯一微信入口、白名单、主人和旁路失败关闭 |
| 日志隔离 | **只有路径分隔** | profile 目录和 unit 可区分 | root/default 隔离、Plugin 专用 namespace、正文最小化 |
| 可信前提观测 | **局部** | service/PID/profile/platform configured/Cron count 可观测 | 初始化、唯一主人、白名单、健康核心与安全闸门的统一真实三态 |
| 权威资产枚举迁移 | **原始材料可枚举，闭包未证明** | code/profile/Plugin/Skill/Cron/dependency/log path 可逐项列出 | 单一权威集合、同代际、完整导出、恢复后验证 |

## 9. 本票明确未做的推断

- 没有把 8 月 16–18 日快照冒充 8 月 20 日事实；旧报告仅用于定位命令和需要重核的路径。
- 没有把 `active/running` 写成健康管家已运行。
- 没有把普通 Plugin enabled 为 0 写成 bundled platform/backend 没有加载。
- 没有把 profile 中存在 `medical` 或默认 home 中存在 `health-steward` Skill 写成 Partner 当前采用了健康管家。
- 没有把 Telegram/Weixin `configured` 写成入站、唯一主人、白名单或回复闭环通过。
- 没有把恶意 root 排除在产品威胁范围之外这一假设，冒充当前 root 部署已有技术隔离。
- 没有选择 Plugin 组织、受限账户、日志后端、资产 manifest、升级、部署或迁移 HOW。

## 10. 一手来源与现场命令记录

### 当前目标现场

- **[L1] 版本与 Git：** `date --iso-8601=seconds`、`hermes --version`、目标 venv `python --version`、`git rev-parse HEAD`、`git describe --tags --always --dirty`、`git status --porcelain=v1 --untracked-files=all`、`git diff --name-status/--stat`，以及仅提取 `diff --unified=0` 的 hunk header；采样于 `2026-08-20T12:41:45+08:00`–`12:42:34+08:00`。
- **[L2] 服务与权限：** `loginctl show-user root`；root 用户和系统两个 scope 的 `systemctl show/list-units`；`ps`、`/proc/<pid>/status`、`readlink /proc/<pid>/{exe,cwd}`、`ss`；未读取 `/proc/<pid>/environ`。
- **[L3] Hermes 清单：** `hermes --profile partner status --all`、`plugins list --json/--enabled/--no-bundled`、`skills list --source local --enabled-only`、`cron status/list`。报告丢弃 status 中的截断 credential 和聊天标识。
- **[L4] profile 元数据：** 对 profile/config/env/state/skills/plugins/cron/logs 使用 `stat`、受限深度 `find`、manifest count/hash；未读取 config、env、DB、Skill 或日志正文。
- **[L5] 依赖与固定文件：** 排序 `pip freeze --all` 的 count/hash；`pip show` 的 Name/Version；`sha256sum` 仅用于固定源码、lockfile 和 Skill manifest 聚合。
- **[L6] 日志元数据：** `systemctl --user show ... StandardOutput/StandardError/SyslogIdentifier/LogNamespace` 与日志目录 `stat/find -printf`；未执行 `journalctl` 或读取任何日志内容。
- SSH 使用现有专用 key 和已保存 host key，`StrictHostKeyChecking=yes`；报告未读取、复制或输出私钥和远端 secret。

### 固定官方源码与文档

- **[O1]** [NousResearch/hermes-agent 最新发行 API](https://api.github.com/repos/NousResearch/hermes-agent/releases/latest)；[v2026.8.18 / v0.20.4 release](https://github.com/NousResearch/hermes-agent/releases/tag/v2026.8.18)。
- **[O2]** [目标 v0.20.0 固定提交 `3c27eb...`](https://github.com/NousResearch/hermes-agent/commit/3c27eb6234bf91b8ceee9e9071591b31e9b148cb)；[v2026.8.3 release](https://github.com/NousResearch/hermes-agent/releases/tag/v2026.8.3)。
- **[F1]** [Plugin 定义、manifest 与 register(ctx)](https://github.com/NousResearch/hermes-agent/blob/3c27eb6234bf91b8ceee9e9071591b31e9b148cb/website/docs/user-guide/features/plugins.md#L8-L108)。
- **[F2]** [Tool 注册与 override 权限](https://github.com/NousResearch/hermes-agent/blob/3c27eb6234bf91b8ceee9e9071591b31e9b148cb/hermes_cli/plugins.py#L377-L428)。
- **[F3]** [PluginManager 发现、缓存、来源、普通 opt-in、bundled backend 与 platform 分流](https://github.com/NousResearch/hermes-agent/blob/3c27eb6234bf91b8ceee9e9071591b31e9b148cb/hermes_cli/plugins.py#L1181-L1364)。
- **[F4]** [Plugin import/register、注册计数与 load-error 继续语义](https://github.com/NousResearch/hermes-agent/blob/3c27eb6234bf91b8ceee9e9071591b31e9b148cb/hermes_cli/plugins.py#L1611-L1689)。
- **[F5]** [安装、启用、更新、停用、删除实现](https://github.com/NousResearch/hermes-agent/blob/3c27eb6234bf91b8ceee9e9071591b31e9b148cb/hermes_cli/plugins_cmd.py#L450-L699)；[allow-list 与启停实现](https://github.com/NousResearch/hermes-agent/blob/3c27eb6234bf91b8ceee9e9071591b31e9b148cb/hermes_cli/plugins_cmd.py#L753-L979)；[管理命令官方说明](https://github.com/NousResearch/hermes-agent/blob/3c27eb6234bf91b8ceee9e9071591b31e9b148cb/website/docs/user-guide/features/plugins.md#L263-L323)。
- **[F6]** [Hook 与 Middleware 回调异常被隔离并继续](https://github.com/NousResearch/hermes-agent/blob/3c27eb6234bf91b8ceee9e9071591b31e9b148cb/hermes_cli/plugins.py#L1744-L1806)。
- **[F7]** [Plugin Skill 只读、命名空间化、显式加载合同](https://github.com/NousResearch/hermes-agent/blob/3c27eb6234bf91b8ceee9e9071591b31e9b148cb/hermes_cli/plugins.py#L1108-L1147)；[普通 Skill 渐进加载](https://github.com/NousResearch/hermes-agent/blob/3c27eb6234bf91b8ceee9e9071591b31e9b148cb/website/docs/user-guide/features/skills.md#L7-L13)。
- **[F8]** [`pre_gateway_dispatch` 固定调用点](https://github.com/NousResearch/hermes-agent/blob/3c27eb6234bf91b8ceee9e9071591b31e9b148cb/gateway/run.py#L13355-L13396)。
- **[F9]** [Middleware 执行链与 callback 异常继续](https://github.com/NousResearch/hermes-agent/blob/3c27eb6234bf91b8ceee9e9071591b31e9b148cb/hermes_cli/middleware.py#L187-L292)。

### 当前仓库

- **[R1]** `D:\cohermes\ops\partner-health-steward\`、`D:\cohermes\docs\adr\`、`D:\cohermes\.scratch\partner-health-steward\` 的文件清单与 `git status --porcelain`；仓库 HEAD `5f358137309d7670e7ad615c8af9d1aa679a49e3`。这些路径只证明候选源码和权威规划材料存在，不证明已经部署到目标现场。
