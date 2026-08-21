# 01 — 核验真实 partner 服务器基线

**What to build:** 形成一份只读、可复查的真实 partner 服务器基线，使后续部署不再依赖历史文档中的版本、账户、路径、微信状态或 Job 假设。

**Blocked by:** None — can start immediately

**Status:** resolved

- [x] 记录真实 partner Hermes 的版本、进程账户、服务单元、profile 归属和运行状态，并区分事实与历史材料。
- [x] 记录当前微信接口的配置存在性、服务状态和最近成功活动证据，但不输出凭据或健康内容。
- [x] 枚举当前 partner 原生 Jobs，确认是否已有健康相关 Job、重复 Job 或旧原型残留。
- [x] 确认 default Hermes、其他 Hermes profile 和无关服务的边界，形成明确的禁止修改清单。
- [x] 记录当前可回滚的配置、服务和数据目标，只读检查不执行停止、迁移、写入或重启。
- [x] 输出可定位的基线证据，供 ticket 14 和 ticket 15 使用。

## Answer

只读基线已记录于 [`../evidence/01-live-partner-baseline-20260807.md`](../evidence/01-live-partner-baseline-20260807.md)。结论要点：partner 当前以 root 运行；健康 sidecar、隔离账户和原生健康 Jobs 均不存在；微信已配置且适配器已连接，最近可闭合的成功发送链为 2026-08-05，本次服务启动后的成功请求—回复闭环留待 ticket 15 验收；default Hermes、Telegram、x-ui/xray 及 443/2096/18000 已列为禁止修改边界。本票据未对服务器执行写入、停止、迁移、重启或测试消息。
