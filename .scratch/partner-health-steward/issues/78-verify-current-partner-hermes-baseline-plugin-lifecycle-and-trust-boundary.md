# 【CAN】核验当前 Partner Hermes 基线、Plugin 生命周期与可信执行边界

Type: research
Status: resolved
Parent: [健康管家首发 TO、CAN 与 HOW 决策闭合路线](../map.md)
Blocked by: [【CAN】重建完整 TO 的能力链与追溯关系](76-rebuild-complete-to-capability-chain-and-traceability.md)

## Question

针对[【TO】闭合首发健康管家的完整产品合同与成功条件](75-close-first-release-health-steward-product-contract.md)中的真实 Plugin、单人专用 Hermes、初始化前不启动、可信边界丢失时停止处理以及权威资料不依赖 LLM 记忆，当前目标 Partner Hermes 的真实版本、提交与定制差异、profile、服务进程、Plugin/Skill/Cron/聊天入口、运行权限和依赖指纹是什么；固定官方合同、目标源码和目标现场分别证明哪些 Plugin 生命周期、注册与卸载、失败关闭、Hermes 同生共停、入口收敛、日志隔离和可信前提观测能力，哪些仍未证明？

本票必须区分官方保证、当前固定源码、目标现场只读事实和获准实验，不得把 2026-08-16 的旧现场快照、代码存在、服务存活或恶意最高权限主体不在对抗范围冒充当前健康管家已经可信运行。它同时只核验权威文档、Skill 和受管个人状态能够被枚举与迁移所需的基础扩展能力，不选择 Plugin 设计、存储、迁移或部署 HOW，不读取或输出 secret，也不改变正式 Partner 状态。

## Comments

### 2026-08-20 — 由完整 TO 能力链重建创建

本票对应[【CAN】重建完整 TO 的能力链与追溯关系](76-rebuild-complete-to-capability-chain-and-traceability.md)中的 C01。

本票重核[【CAN】核验目标 Hermes 基线与受支持的健康扩展面](42-verify-target-hermes-baseline-and-supported-extension-surface.md)的易漂移现场部分，并条件继承其固定版本源码事实；其 Answer 必须给后继入口、消息、状态、模型路线和可迁移性调查提供同一时点、可定位的目标指纹。

## Answer

完整证据见[《当前 Partner Hermes 基线、Plugin 生命周期与可信执行边界》](../evidence/19-current-partner-hermes-baseline-plugin-lifecycle-trust-20260820.md)。本票按“2026-08-20 目标现场 → 目标提交固定源码与文档 → 当前官方发行事实”分层核验；没有读取凭据、聊天或健康正文，没有发送消息、运行模型、安装或启停组件，也没有改变正式 Partner 状态。

截至 2026-08-20 12:49（Asia/Shanghai），正式 Partner 仍是 Hermes Agent `v0.20.0 (2026.8.3)`、Python `3.11.15`、OpenAI SDK `2.24.0`，安装树 HEAD 为 `3c27eb6234bf91b8ceee9e9071591b31e9b148cb`，且仍有四个 tracked 修改与一个 untracked 文件；当前官方最新发行已是 `v0.20.4 (2026.8.18)`。这只固定版本漂移与现场差异，不在本票选择升级路线，也不得把新版本或 `main` 的能力归给目标现场。

目标固定版本确有进程内 Plugin 扩展面，可注册 Tool、Hook、Middleware、Platform、Skill 与辅助任务；普通 Plugin 由 allow-list 控制，非 bundled Plugin 覆盖内置 Tool 还需单独授权。但当前 Partner 的普通 enabled Plugin 为零，profile `plugins/` 中没有 manifest，也没有健康 Plugin；bundled backend/platform 有独立自动或延迟加载路径，因此不能把这个结果写成“运行时完全没有 Plugin 代码”。Partner profile 当前有 `80` 个 `SKILL.md`，Hermes 的 local-enabled 管理视图只列 `7` 项，两者不是同一个全集；业务 Cron job 为零。Telegram 与 Weixin 都已配置，现状也不能证明唯一健康入口已经成立。

固定生命周期合同不是健康管家的失败关闭边界：Plugin import 或 `register()` 失败只记错误并继续 Hermes，且此前已经写入共享 registry 的部分注册项不会自动回滚；Hook、Middleware 和 `pre_gateway_dispatch` 回调异常均会继续基础流程。启用、停用、更新和删除主要改变文件或下次发现配置，没有统一的运行时 unload、teardown、状态迁移或清理合同。

Partner Gateway 当前由 root 用户级 systemd unit 以 `root` 和完整 capability 运行，未启用所核验的 systemd 文件、权限、namespace 或 syscall sandbox；default 与 Partner 还共享 root 信任域和安装树。纯进程内、守约的 Plugin 会随 Gateway 硬停止，但 systemd `active`、`Restart=always` 只能证明进程监督，不能证明 Plugin 注册成功、优雅卸载、外部副作用停止、健康核心可用或可信前提仍成立。日志目前只有 profile 路径与 unit 查询分隔，没有独立 journald namespace、Plugin 专用权限域或健康正文最小化证据。

源码提交与脏路径、profile 元数据、Plugin manifest、Skill 文件、Cron 数量、依赖集合和日志路径均可分别枚举，这证明了后续建立权威资产清单的基础能力；但现场没有已部署的受管健康状态、统一资产 manifest、同代际快照、Plugin 状态导入导出、引用完整性或迁移后单一权威验证。因此本票不能把“复制文档与 Skill”表述为完整健康管家已经可迁移。

结论是：**当前 Partner Hermes 可以作为后继 CAN 调查的可扩展基座，但健康 Plugin 的加载与失败关闭、初始化硬门禁、唯一入口、状态和日志隔离、可信前提观测以及权威资产迁移闭包均尚未成立或未证明。** 后继入口、微信、状态数据平面、模型路线和可迁移性票据必须继承本票的同一现场指纹与这些负向边界；不得把服务存活、代码存在或恶意最高权限主体不在主动对抗范围冒充能力已经成立。
