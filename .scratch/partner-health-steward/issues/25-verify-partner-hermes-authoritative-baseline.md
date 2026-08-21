# 核验目标 Partner Hermes 的版本与权威证据基线

Type: research
Status: wontfix
Authority: historical-planning-draft-only
Superseded by: [健康管家真实上线与稳定运行路线](../map.md), recharted 2026-08-15
Parent: [健康管家首发 TO、CAN 与 HOW 决策闭合路线](../map.md)
Blocked by: None

## Question

健康管家实际目标所对应的 Partner Hermes 主机、profile、服务、Hermes 上游版本或提交、微信适配器版本与本地 mirror 分别是什么；后续 CAN 调查应采用怎样的证据优先级，才能明确区分上游权威事实、目标现场事实、本地适配事实和历史描述，并且不暴露任何凭据？

## Comments

### 2026-08-14 — Charting 后的首轮只读调查，尚未解决

- 已复核本地官方仓库镜像 `.research/hermes-agent`：origin 为 `https://github.com/NousResearch/hermes-agent.git`，HEAD 为 `7b5ba2054721dde998ed47fd4a0f031955278e99`，提交时间为 2026-07-12；它只能证明本地快照，尚未证明目标 Partner 或 2026-08-14 上游当前版本。
- 该 mirror 的 `cron/scheduler.py` 有本地未提交修改；其中新增的 Job identity 或 fingerprint 不能作为 Hermes 上游原生能力。
- 历史输入对 Partner 路径存在冲突：旧资料使用 `/root/.hermes/profiles/partner`，新部署候选使用 `/var/lib/hermes-partner/.hermes/profiles/partner`。当前真实主机、运行账户、profile realpath、service unit、`ExecStart`、安装包或 commit、微信适配器 hash 均未取得同一时间点的现场证据。
- mirror 快照包含 Tencent iLink 微信 long polling 与私聊实现及文档，但没有目标 Partner 的 adapter hash、包版本或 live 私聊探针，不能据此宣称现场能力成立。
- 后续 CAN 采用以下优先级：目标主机同一时间点的只读运行证据；NousResearch 官方 commit/tag/release 与官方文档；本地 clean upstream mirror 对照；目标现场 journal、live 微信私聊与 Cron fresh-session 证据；本仓库代码和测试；最后才是 ADR、spec、tickets 与旧报告。
- 仍缺三类证据：目标现场运行基线、NousResearch 官方当前版本核对、目标现场微信与 Cron 行为。缺任一项都不能关闭本票，也不能开始选择 HOW TO。
