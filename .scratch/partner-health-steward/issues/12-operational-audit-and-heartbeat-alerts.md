# 12 — 实现审计保留与运行失联告警

**What to build:** 让操作者在不读取健康正文的情况下追踪系统动作、失败和运行失联，并使审计数据按固定期限清理。

**Blocked by:** 08 — 实现每日画像复核与派生任务规划；09 — 实现到期快照渲染与消息派发；10 — 实现主动触达治理

**Status:** resolved

## Answer

- Added content-free audit records for access, profile candidates, daily review, task dispatch, and heartbeat outcomes. Audit writes now fail closed on unknown fields, nested values, free-form text, invalid identifiers, and invalid timestamps.
- Added a metadata-only external monitor with a one-shot `python -m sidecar.operations` entrypoint, JSONL audit reader, JSONL durable alert spool, and configurable syslog operator sink. The monitor runs audit retention cleanup on every poll, detects two daily-review failures and 15-minute dispatcher heartbeat loss, deduplicates alerts, and persists firing/recovery transitions.
- Added cross-process locking for audit append/purge and monitor state read-modify-write. The monitor never opens the encrypted health database or receives profile/evidence/model content.
- Verification: targeted operational monitor tests 12 passed; full suite 294 tests, 16 skipped on Windows because AF_UNIX is unavailable; compileall and `git diff --check` passed. Linux restricted-account/socket and real Hermes acceptance remain Ticket 14/15 deployment gates.

- [x] 授权查看、撤回、删除、候选写入、任务状态和发送结果记录时间、执行角色、动作、对象 ID、结果和理由/证据 ID。
- [x] 审计不保存健康正文、完整画像、完整消息、资料原文或模型思维文本。
- [x] 一般无内容审计和任务操作日志保留 90 天，过期清理不破坏当前对象的证据引用。
- [x] 日检连续两次失败时，系统外运行监控向指定操作者发送不含健康内容的故障告警。
- [x] 派发器连续 15 分钟没有成功心跳时发送同类告警，并在恢复后提供可审计的恢复状态。
- [x] 告警路径不依赖已经失联的健康计划 Job，也不能获得健康数据库内容权限。
- [x] 运维查询能够区分服务健康、Job 健康、内容授权和生产验收状态。
