# 【CAN】核验目标 Hermes 基线与受支持的健康扩展面

Type: research
Status: resolved
Parent: [健康管家首发 TO、CAN 与 HOW 决策闭合路线](../map.md)
Blocked by: None

## Question

目标正式运行实例实际使用的 Hermes 版本、提交、安装形态和配置入口是什么；官方文档、对应版本的上游源码与目标运行证据分别证明了哪些受支持的 Skill/插件扩展机制及其能力边界？对每项结论记录来源层级、版本或提交、核验日期和目标现场证据，不用旧实现、本地脏副本或社区描述推定当前能力。

## Answer

2026-08-16 的同一时点只读现场核验确认：正式 Partner 基座运行 Hermes `v0.20.0 (2026.8.3)`，目标工作树 HEAD 对应的官方 v0.20.0 发布提交为 `3c27eb6234bf91b8ceee9e9071591b31e9b148cb`，安装于 `/usr/local/lib/hermes-agent`，由 `hermes-gateway-partner.service` 以 `--profile partner` 和 `/root/.hermes/profiles/partner` 工作目录启动。现场 Git 工作树为 `v2026.8.3-dirty`，包含 Skill 使用披露等未提交定制；微信适配器文件则与该官方提交的 SHA-256 完全一致。当前官方最新稳定版为 v0.20.1，不能把其新增能力或 `main` 文档自动归因给目标。

目标提交固定的官方源码与文档证明：Skill 是经 `skill_view` 按需加载的知识/流程文档，本身不自动提供持久化、调度、身份授权或消息拦截；Plugin 是 Hermes 原生的可执行扩展面，可注册 Tool、Hook、Middleware、聊天接口 Adapter 以及配套 Skill。部分 Hook/Middleware 异常会继续原流程，不能未经设计和验证即视为 fail-closed 安全边界。目标 profile 当前没有任何已启用 Plugin，没有健康管家专用 Skill/实现，也没有 Cron Job；现有 `medical` Skill 不等于健康管家。

完整证据、版本链接、目标路径、源码行号及不能推出的结论见 [目标 Partner Hermes 扩展面基线](../evidence/02-target-hermes-extension-baseline-20260816.md)。本票只回答 CAN 基线，不选择 HOW，也不修改 TO。
