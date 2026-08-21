# 健康状态由 sidecar 持有，并使用两个固定 Hermes Job

> 状态：已由 ADR 0014 取代，仅保留为决策历史。

健康画像、证据、资料卡和派生任务由 partner Hermes 所在服务器上的私有 health sidecar 持有；Hermes memory 只保留档案指针和稳定交互偏好。Hermes 只运行日检与派发器两个固定 Job，派生任务不直接创建原生 Cron，因为 Cron 运行于 fresh session 且不能递归管理 Cron。

为使隔离不仅停留在代码分工，partner Hermes 与 sidecar 分别运行在 `hermes-partner` 和 `health-sidecar` 受限账户下，通过不监听 TCP 的 Unix domain socket 通信。健康管家不修改 Hermes 核心源码；旧 v0.2 原型只作为 SQLite、审计和固定 Job 经验的参考，不直接部署。
