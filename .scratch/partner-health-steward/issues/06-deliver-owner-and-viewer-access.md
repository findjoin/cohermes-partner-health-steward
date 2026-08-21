# 06 — 实现主人自查、查看授权与只读访问

**What to build:** 让画像主人始终能够查看和导出自己的健康档案，并能明确授予或撤回指定查看者的完整只读权限，同时保持管理员默认无内容访问。

**Blocked by:** 03 — 从主人消息维护证据与紧凑画像

**Status:** resolved

## Answer

Ticket 06 is implemented through the partner adapter and protected sidecar
socket. The owner can read and export the complete profile, evidence, tasks,
reports, and scoped audit; an owner-signed, action-bound receipt can grant or
revoke a named viewer. Viewer reads are read-only and never expose the
authorization source or export path. Every access action is audited without
health content. Access receipts are verified by the sidecar's configured gateway
verifier, expire after 600 seconds (10 minutes) or reject timestamps more than
60 seconds in the future, and are consumed once in a separate encrypted
ledger, so replay protection does not enlarge the profile.

Verification: the targeted access suite passes 8 tests with 1 Windows AF_UNIX
skip; the full partner-health-steward suite passes 226 tests with 11
environment skips; compileall and staged diff checks pass. Linux restricted
accounts/socket-owner deployment and real Hermes gateway wiring remain
environment-level follow-up work and are not claimed by this Windows run.

- [x] 画像主人能够查看完整画像、证据簿和未完成任务，并导出自己的健康档案。
- [x] 主人能够明确授予指定查看者读取画像、证据、任务、报告和访问审计的权限。
- [x] 查看者入口严格只读，不能修改事实、证据、偏好、任务或授权来源。
- [x] 主人撤回授权后，后续内容读取和报告发送立即被阻断；历史已发送内容不声称可召回。
- [x] 未获授权的服务器管理员只能看到服务状态、路径和不含健康正文的审计信息。
- [x] 授权、访问、拒绝和撤回均生成包含角色、动作、对象 ID、结果和时间的无内容审计。
- [x] 非主人发送者不能借查看入口获得主人权限或形成个人证据。
