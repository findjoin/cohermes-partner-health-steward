# 13 — 接入真实 Hermes 的两个固定 Jobs

**What to build:** 让真实 Hermes mirror 加载 partner 适配层，并通过两个 fresh-session 原生 Job 调用 sidecar，而无需修改 Hermes core 或允许派生任务创建 Cron。

**Blocked by:** 08 — 实现每日画像复核与派生任务规划；09 — 实现到期快照渲染与消息派发；10 — 实现主动触达治理；11 — 实现周度画像差异报告；12 — 实现审计保留与运行失联告警

**Status:** resolved

- [x] partner 适配层在未修改的 Hermes mirror 中成功加载；固定 Job 的 pre-run 经 Unix socket 取得 sidecar 快照，工具调用再经短时 capability 复核。
- [x] 安装器只创建每日 04:00 日检和每五分钟派发器两个健康原生 Job，周报和未来任务不创建额外 Cron。
- [x] 两个 Job 使用 Hermes agent 路径（`no_agent=false`、不附着会话），固定 prompt 搭配受控 sidecar 快照；capability 绑定 role、Job ID、指纹并在 10 分钟后失效。
- [x] 固定 Job 使用角色专属 toolset 和 `no_mcp`，安装器拒绝 default/非 `profiles/partner` 目标。
- [x] Hermes core 工作树没有健康管家私有修改，旧 v0.2 scheduler patch 和固定门禁不参与新行为。
- [x] default Hermes、其他 profile 和无关工具的本地回归未被修改；全量 partner 测试通过。

## Comments

2026-08-09 Linux acceptance preflight: connected read-only to findjoin (69.63.215.227). Hermes partner service was active, but the partner process still ran as root; the health-steward plugin, both fixed Job scripts, and /run/health-sidecar/health.sock were absent, and hermes cron list reported no scheduled Jobs. No server files, services, configuration, or Cron records were changed. Ticket 13 is resolved for its local implementation and code-review scope; Linux deployment acceptance remains explicitly deferred until Ticket 14 has supplied the isolated runtime.

## Answer

已实现本地接入：新增 `hermes_jobs.py`、partner-only 插件、两个 pre-run 快照脚本、显式安装器和共享 capability 验证。未修改 `.research/hermes-agent` 的 Hermes core。插件只接受带 HMAC capability 的日检计划或派发调用；capability 由 scheduler 注入的 Job ID/指纹签发，并由当前持久 Job 再次复核。

验证证据：Ticket 13 定向测试 `9 passed, 1 skipped`（10 项运行）；全量 `304 passed, 17 skipped`；`git diff --cached --check` 通过。唯一跳过是当前 Windows 环境没有 `croniter`，因此没有声称真实 Cron store/fresh-agent/Linux Unix-socket smoke 已通过。上线前须在非生产 Linux partner profile 执行真实 Hermes thin smoke：两条 Job 各跑一次 pre-run→fresh agent→plugin→sidecar socket，并验证错误 role、篡改/过期 capability 均无 socket 写入。
