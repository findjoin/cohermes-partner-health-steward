# 目标 Partner Hermes 扩展面基线（Ticket 42）

## 1. 核验范围与证据纪律

- 核验时间：2026-08-16 01:38–01:51（Asia/Shanghai）。
- 目标：主机 `findjoin` 上正式运行的 `partner` Hermes 基座。
- 方法：SSH 只读检查运行状态、版本、Git 元数据、路径元数据和 Hermes 列表命令；没有发送聊天消息，没有读取凭据值、聊天正文或健康内容，也没有修改配置、安装插件、创建任务、停止或重启服务。
- 证据优先级：同一时点目标现场 > 目标提交固定的官方源码与文档 > 当前官方稳定发行信息。仓库中的旧实现、旧 ADR/Spec/Tickets、本地旧镜像和社区说明均未用于推定目标能力。

## 2. 目标现场基线

| 项目 | 2026-08-16 现场事实 | 物理含义 |
|---|---|---|
| 主机与实例 | `findjoin`；`hermes-gateway-partner.service` 为 `active/running/enabled` | 当前被核验的正式 Partner Hermes 进程正在运行，不代表健康管家已经存在 |
| Hermes 版本 | `Hermes Agent v0.20.0 (2026.8.3)` | 目标不是当前最新稳定版，不能直接套用 `main` 或更新版本的能力 |
| 安装形态 | CLI 入口 `/usr/local/bin/hermes`；源码与虚拟环境位于 `/usr/local/lib/hermes-agent`；服务直接运行该目录虚拟环境中的 `python -m hermes_cli.main --profile partner gateway run` | 这是 Git 工作树加本地虚拟环境，不是仅凭包版本即可复原的干净安装 |
| 官方基线提交 | `3c27eb6234bf91b8ceee9e9071591b31e9b148cb`，tag 描述为 `v2026.8.3-dirty` | HEAD 对应官方 v0.20.0 发布提交，但现场工作树包含未提交定制 |
| 现场源码差异 | 修改 `agent/display.py`、`agent/transports/codex.py`、`gateway/run.py`、`package-lock.json`；新增 `gateway/skill_disclosure.py` | 这些差异不是官方 v0.20.0 能力。已检查的 gateway 差异包括微信回复中的 Skill 使用披露和重启通知本地化；不能把它当作健康插件、持久化或安全机制 |
| 微信适配器 | 现场 `gateway/platforms/weixin.py` 与 HEAD 版本的 SHA-256 均为 `e745f2bc7faaa6bbbdd8615fbfc79ca327ca6d0e7700620f37fc21fed14a178a` | 微信适配器本身未被现场脏改；后续消息契约研究可以对准官方 v0.20.0 文件，但仍须结合真实运行事件验证 |
| 服务入口 | 工作目录 `/root/.hermes/profiles/partner`；进程用户 `root:root`；MainPID `143611`，启动于 2026-08-07 07:30:33 +08:00 | `--profile partner` 与该目录共同确定当前 profile；root 运行只是现场事实，不是目标安全设计 |
| 配置入口 | `/root/.hermes/profiles/partner/config.yaml`、`.env` 均为 `0600 root:root`；另有 `skills/`、`plugins/`、`cron/` | 配置、凭据、知识文档、可执行插件和调度状态是不同入口；本次未读取 `.env` 值 |
| Plugin 现场状态 | `hermes plugins list --plain` 没有任何 `enabled` 项；`--no-bundled` 无输出；profile 的 `plugins/` 下未发现 `plugin.yaml` | 当前没有已启用的健康 Plugin，也不能把仓库自带但未启用的条目说成目标已加载能力 |
| Skill 现场状态 | profile 中存在 `/root/.hermes/profiles/partner/skills/medical/SKILL.md` | 这是现有医疗知识/流程资产，不是健康管家已经实现的证据 |
| 调度现场状态 | `hermes cron list` 返回 `No scheduled jobs.` | 当前没有每日健康复盘任务；调度语义仍由 Ticket 44 核验 |

本次没有发送真实微信消息，因此没有新增“微信请求—回复闭环”证据；这属于后续验收，不属于 Ticket 42 的扩展面基线。

## 3. 官方版本边界

- 目标 HEAD 与官方 [`v2026.8.3 / v0.20.0` 发布](https://github.com/NousResearch/hermes-agent/releases/tag/v2026.8.3)的提交 [`3c27eb6234bf91b8ceee9e9071591b31e9b148cb`](https://github.com/NousResearch/hermes-agent/commit/3c27eb6234bf91b8ceee9e9071591b31e9b148cb)一致。
- 2026-08-16 核验时，官方最新稳定版是 [`v2026.8.13 / v0.20.1`](https://github.com/NousResearch/hermes-agent/releases/tag/v2026.8.13)，提交为 [`f80f453ae0679347e38abc917c7f94f717bf96c5`](https://github.com/NousResearch/hermes-agent/commit/f80f453ae0679347e38abc917c7f94f717bf96c5)。因此目标落后一个稳定发行版；这只是版本事实，不在本票中决定是否升级。
- 以下能力结论均取自目标提交固定的源码或文档。当前官网或 `main` 中新增的接口，除非也存在于 `3c27eb...`，不得归因给目标实例。

## 4. v0.20.0 已支持的扩展机制

### 4.1 Skill：按需加载的知识与流程文档

目标版本把 Skill 定义为按需加载的知识文档，主来源为 profile 的 `skills/`，并可配置外部目录；完整内容通过 `skill_view` 渐进加载，而不是常驻执行。[目标版本 Skills 定义](https://github.com/NousResearch/hermes-agent/blob/3c27eb6234bf91b8ceee9e9071591b31e9b148cb/website/docs/user-guide/features/skills.md#L7-L13) [渐进加载语义](https://github.com/NousResearch/hermes-agent/blob/3c27eb6234bf91b8ceee9e9071591b31e9b148cb/website/docs/user-guide/features/skills.md#L130-L140)

因此：

- Skill 可以表达健康管家的知识、对话步骤和调用其他工具的流程。
- Skill 目录可以带 supporting scripts，但脚本仍须由 agent 经已有工具显式运行；安装或加载 `SKILL.md` 不会自动注册常驻进程、消息 Hook、持久化存储、身份授权或定时任务。
- Plugin 注册的 Skill 仍是通过 `skill_view` 显式读取的只读 Skill，不会因此自动变成 Hook 或 Tool。[目标版本 `register_skill`](https://github.com/NousResearch/hermes-agent/blob/3c27eb6234bf91b8ceee9e9071591b31e9b148cb/hermes_cli/plugins.py#L1217-L1260)

结论：**Skill 可以承载健康知识与使用流程，但 Skill alone 不是健康管家的可强制运行时。**

### 4.2 Plugin：受支持的可执行扩展面

目标版本官方文档明确：Plugin 用于在不修改 Hermes 核心的前提下增加工具、Hook 和集成，基本形态是 `plugin.yaml` 加 Python `register(ctx)`。[目标版本 Plugin 定义与结构](https://github.com/NousResearch/hermes-agent/blob/3c27eb6234bf91b8ceee9e9071591b31e9b148cb/website/docs/user-guide/features/plugins.md#L8-L31)

已确认的 `PluginContext` 扩展面包括：

- `register_tool`：注册模型可调用的工具；覆盖内置工具还需单独的 operator 配置授权。[目标版本工具注册与覆盖闸门](https://github.com/NousResearch/hermes-agent/blob/3c27eb6234bf91b8ceee9e9071591b31e9b148cb/hermes_cli/plugins.py#L410-L465)
- `register_hook`：监听生命周期事件；`pre_gateway_dispatch` 可在普通授权流程前对消息作 `skip/rewrite/allow`。[目标版本 Hook 表](https://github.com/NousResearch/hermes-agent/blob/3c27eb6234bf91b8ceee9e9071591b31e9b148cb/website/docs/user-guide/features/plugins.md#L188-L204)
- `register_middleware`：改写 LLM/Tool 请求，或包裹真实 LLM/Tool 执行。[目标版本中间件契约](https://github.com/NousResearch/hermes-agent/blob/3c27eb6234bf91b8ceee9e9071591b31e9b148cb/hermes_cli/middleware.py#L187-L225)
- `register_platform`：注册遵循 `BasePlatformAdapter` 的聊天接口适配器。[目标版本平台注册](https://github.com/NousResearch/hermes-agent/blob/3c27eb6234bf91b8ceee9e9071591b31e9b148cb/hermes_cli/plugins.py#L950-L1002)
- `register_skill`：随 Plugin 提供命名空间化 Skill，但该 Skill 仍按上一节的文档加载语义工作。

Plugin 可来自 Hermes bundled 目录、profile 的 `plugins/`、显式允许的项目目录或 Python entry point；普通和第三方 Plugin 默认需要加入 `plugins.enabled`，`plugins.disabled` 优先。[目标版本发现与启用规则](https://github.com/NousResearch/hermes-agent/blob/3c27eb6234bf91b8ceee9e9071591b31e9b148cb/website/docs/user-guide/features/plugins.md#L118-L182)

结论：**v0.20.0 确实提供了不修改 Hermes 核心的可执行 Plugin 路线；健康管家可以组合 Plugin 与 Skill，但具体职责分配属于后续 HOW。**

## 5. 已证实的能力边界

1. `pre_gateway_dispatch` 的确在普通授权前运行并可停止或改写消息；但该 Hook 调用抛异常时，Hermes 记录警告后继续正常分发。因此不能未经额外设计和验证，就把这个 Hook 当作天然 fail-closed 的健康授权或危险闸门。[目标版本 gateway 调用点](https://github.com/NousResearch/hermes-agent/blob/3c27eb6234bf91b8ceee9e9071591b31e9b148cb/gateway/run.py#L13355-L13396)
2. 执行中间件可以包裹真实 LLM/Tool 调用；但回调在调用下游前抛异常时，默认继续执行后续链。因此它也不是天然 fail-closed 保证。[目标版本异常语义](https://github.com/NousResearch/hermes-agent/blob/3c27eb6234bf91b8ceee9e9071591b31e9b148cb/hermes_cli/middleware.py#L234-L292)
3. 目标版本提供扩展入口，不等于已经提供健康档案的数据模型、主人级授权、每日复盘语义、主动发送幂等、诊断知识质量或主人可见运行状态。它们分别由 Tickets 43–46 继续核验。
4. 当前目标没有启用健康 Plugin、没有健康管家专用 Skill/实现、没有任何 Cron Job。现有 `medical` Skill 和现场 skill-disclosure 定制都不能替代健康管家产品能力。
5. 目标工作树不是干净发行版。后续任何 CAN/HOW 结论必须注明是“官方 v0.20.0 能力”“现场本地定制”还是“尚未验证”，不能笼统写成“Hermes 支持”。

## 6. Ticket 42 结论

Ticket 42 的问题已闭合：目标正式运行基座是带现场定制的 Hermes v0.20.0 Git 工作树；其受支持路线中，Skill 是按需加载的知识/流程载体，Plugin 是能够注册 Tool、Hook、Middleware、Platform 与配套 Skill 的 Hermes 原生可执行扩展面。目标当前尚无健康 Plugin 或调度任务，且上述扩展点的存在不证明 TO 已可满足。

本结论没有选择健康管家的 HOW，也没有修改任何 TO。下一层 CAN Research 应以该目标提交和现场差异为基线，分别核验渠道与逐条来源、每日任务与恢复/状态、档案与数据权利、诊断与安全能力；发现硬缺口时创建 TO-CAN 差距决策，不得静默缩小愿景。
