# 【CAN】核验健康画像、数据权利与保护能力

Type: research
Status: resolved
Parent: [健康管家首发 TO、CAN 与 HOW 决策闭合路线](../map.md)
Blocked by: [【CAN】核验目标 Hermes 基线与受支持的健康扩展面](42-verify-target-hermes-baseline-and-supported-extension-surface.md)

## Question

在已核验的目标 Hermes 扩展面内，长期可追溯且最小化的独立健康档案、事实与 AI 推断分离、来源和时间保留、主人查看纠正导出删除、停止新增记录、暂停主动支持、数据接收方变化及静态数据保护分别有哪些受支持能力与限制？不得把普通聊天历史、通用记忆、模型上下文或旧 sidecar 默认当作健康档案权威，并给出官方、对应源码与目标运行证据。

## Answer

目标 Hermes v0.20.0 没有内置健康档案或主人数据权利。普通 `state.db` 保存完整会话并支持全文检索，通用 Memory 会进入模型上下文；二者都不能成为独立、最小、结构化的健康档案，也没有个人事实、医生转述、外部知识、AI 推断、来源、时间和主人确认等领域语义。Session 的通用导出或删除以聊天会话为粒度，不能冒充主人查看、纠正、导出或删除健康档案的产品能力。

根据正式 Plugin/Adapter 执行扩展和进程权限，可以推断健康组件能够自行实现专用权威状态、逐条来源、领域记录类型、身份连续性、接收方同意以及主人控制操作；这不是 Hermes 内置或受管状态服务。因此当前没有证据要求缩小 TO，也不创建 TO-CAN 差距决策。但目标版本不提供健康 schema、事务、迁移、加密、密钥、备份或数据权利合同；这些能力当前现场也全部尚未实现，必须由后续 HOW 明确并验收。

主人权利必须落在健康组件的真实读写和发送路径。停止新增记录与暂停主动支持是两个独立状态；管理员手工删除文件只是运维动作，不能代替主人向 Hermes 发起删除。永久删除不需要新增倒计时、回执或管理员代删功能，但必须覆盖所有仍会让健康管家重新读取、推断或恢复已删内容的受管副本，包括普通历史、通用 Memory、工具结果、导出物或备份，不能只删一份 Plugin 文件。

Hermes 可以配置 Plugin 模型路由和允许表，但没有健康数据接收方同意账本；fallback 与聚合路由可能改变实际接收方，而 provider/model 归因发生在调用之后。后续 HOW 必须在发送健康内容前验证接收方并在无法确定时停止处理，不能用事后审计代替同意。目标原生存储和备份是普通 SQLite、Markdown 与 ZIP 压缩，只有一般 OS 权限，没有健康专用静态加密或密钥生命周期；当前 TO 只确认管理员没有产品权利，不等于 root 在技术上绝对不可读。

2026-08-16 的只读现场核验确认 Partner 仍运行目标固定版本，但 `plugins.enabled` 为空；只有通用 Session、Memory、日志、配置和 Cron 状态，未发现可识别的健康档案、主人权利状态、接收方同意门、健康专用密钥或备份。完整官方源码、现场事实、未证明项和差距触发条件见 [健康档案、数据权利与保护能力核验](../evidence/05-health-record-data-rights-and-protection-capabilities-20260816.md)。

## Comments

### 2026-08-17 — 继承权威说明

本票的目标版本、原生缺失项和现场快照作为基础 CAN 原样继承；`## Answer` 不回写。关于模型接收方是否必须全部事前锁定、该缺口是否阻塞 HOW 的过程判断，现由 [【CAN】核验健康模型调用与全部实际接收方事前锁定能力](57-verify-health-model-routing-and-recipient-preflight-capabilities.md)、[【TO】决定健康模型接收方锁定缺口下的产品承诺边界](58-decide-health-model-recipient-lock-gap-boundary.md) 和 [【HOW】选择健康画像数据平面、模型调用与保护路线](49-choose-health-record-rights-and-protection-route.md) 接续并取代；不得再把本票中的旧过程判断作为当前产品合同。
