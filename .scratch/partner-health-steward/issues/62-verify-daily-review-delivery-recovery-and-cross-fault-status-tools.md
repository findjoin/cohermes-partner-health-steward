# 【CAN】核验每日复盘、主动投递恢复与跨故障域状态观测工具

Type: research
Status: resolved
Parent: [健康管家首发 TO、CAN 与 HOW 决策闭合路线](../map.md)
Blocked by: [【TO】确定稳定运行及主人可见运行状态的产品承诺](41-define-stable-operation-observation-promise.md), [【CAN】核验目标 Hermes 基线与受支持的健康扩展面](42-verify-target-hermes-baseline-and-supported-extension-surface.md), [【CAN】核验每日复盘、发送恢复与运行状态能力](44-verify-scheduling-delivery-recovery-and-runtime-status-capabilities.md), [【HOW】选择健康管家在 Hermes 中的单一执行与权威路线](47-choose-hermes-health-execution-and-authority-route.md), [【HOW】选择微信接入、主人授权与逐次来源路线](48-choose-channel-identity-and-provenance-route.md), [【HOW】选择健康画像数据平面、模型调用与保护路线](49-choose-health-record-rights-and-protection-route.md), [【CAN】核验微信 iLink 与目标 Hermes 的真实接口能力](52-verify-weixin-ilink-and-target-hermes-interface-capabilities.md)

## Question

在每日复盘、必要主动联系、失败恢复和主人可见三态运行状态 TO，以及已经选定的同一 Partner Hermes 健康 Plugin、微信 Adapter 和专用健康数据平面路线下，目标 Hermes 固定提交与目标运行环境真实具备哪些可用于自然日业务幂等、投递不确定态恢复、健康核心自检和跨故障域状态观测的工具、接口与限制？只核验候选能力，不选择调度、监控、通知或恢复 HOW。

研究至少覆盖：主人时区和自然日边界可从何处取得并保持；Cron、Plugin 与专用数据库能记录哪些调度、执行、业务提交、发送尝试和未知态事实；进程崩溃、重启、整机或网络离线后的当前状态重评估及防重复基础；微信接口结果与真实到达之间可获得的确认层级；健康画像读写、问答、每日复盘及安全闸门分别可提供哪些不含健康正文的自检信号；systemd、主机、网络及现有外部服务中哪些已安装或受支持机制能够在 Partner Hermes 或整机故障域之外观察状态并通知主人；这些机制的时钟、持久性、认证、隐私、失联检测和自身故障边界。

必须区分“任务存在、开始执行、业务状态提交、接口接受、主人真实到达、健康核心当前可验证、跨故障域观察仍可用”七层事实，并分别记录官方保证、固定源码、目标现场、未知项与需批准实验。不得安装服务、改配置、创建任务、发送消息或制造故障；需要真实投递、停机或外部通知实验时，只提出最小实验及停止条件。产出带引用的 Markdown 证据并追加 `## Answer`；若候选工具无法支持既定状态承诺，先形成负向 CAN 并交由后继 TO 决定，不得直接降低 TO 或提前选择 HOW。

## Answer

固定 Hermes v0.20.0 与目标环境具备继续实现既定承诺所需的候选工具：Hermes/Python `zoneinfo` 可按经授权保存的主人 IANA 时区计算当地自然日；Cron 可记录任务与执行尝试；Plugin 专用 SQLite 可用事务、唯一约束和持久状态分别记录自然日业务提交、发送尝试与未知态；Plugin 也可提供不含健康正文的画像读写、问答、每日复盘和固定安全闸门自检信号。因此本票是正向 CAN，不降低 TO，也不在此选择调度、监控、通知或恢复 HOW。

证据必须停在七层边界：任务存在不等于开始执行，开始执行不等于健康业务提交，业务提交不等于接口接受，接口接受不等于主人真实到达；四项健康核心当前可验证和跨故障域观察仍可用又各需独立证据。腾讯 iLink 响应和 Hermes 本地 `client_id` 没有主人展示、收取或已读回执；外部副作用也无法与 SQLite 事务原子提交，超时或崩溃窗口必须保留“无法确认”并禁止盲目重发。

2026-08-18 现场只读核验只证明 root 用户 systemd manager 中的 Partner unit 与 Gateway/Ticker，以及同机系统作用域的 dashboard、主机 watchdog、QEMU Guest Agent 等基座存在；系统 manager 中不存在 `hermes-gateway-partner.service`。root 用户作用域 Partner unit 为 `loaded/active/running/enabled`，root `Linger=yes`，两项事实与系统作用域“unit not found”并不矛盾。健康 Plugin、健康 Cron、健康专用数据库、自然日业务提交、健康 outbox、四项核心自检、主人三态状态面、跨主机观察者和主人状态转换通知均未部署或未证明。任一作用域的 `systemd active`、同机默认 Hermes/dashboard、Gateway 心跳或 QGA 进程存在都不能冒充跨主机观察；Partner 当前也没有 TCP 健康监听。

完整固定源码、官方文档、现场事实、七层矩阵、负向边界与需批准的最小实验见 [每日复盘、投递恢复与跨故障域状态工具核验](../evidence/14-daily-review-delivery-recovery-cross-fault-status-tools-20260818.md)。
