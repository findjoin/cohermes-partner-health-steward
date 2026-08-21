# 23 — 用生产适配器运行两个固定健康 Job

**What to build:** 让现有两个固定 Hermes Job 在真实 partner runtime 中使用独立健康模型、白名单资料下载和幂等微信发送：日检只产生受控候选任务，派发器从当前快照重新判断并至多发送一次。

**Blocked by:** 17 — 建立严格幂等的微信健康投递；19 — 用当前画像和权威资料回答健康问题

**Status:** wontfix

**Historical:** 旧实施路线，已退出当前前沿；其中的阻塞证据可由新决策票重新核验，但不得直接恢复实施。

- [ ] 日检和派发均通过 Hermes 支持的独立模型调用面创建 fresh 调用，不复用普通聊天 session，并使用单独固定的健康模型配置。
- [ ] 生产 sidecar/runtime 装配真实健康模型、受控资料下载、幂等微信发送、时钟、密钥和 memory 投影端口，不以 Noop 或测试替身启动为成功。
- [ ] 日检在主人时区 04:00 从当前画像、证据、反馈和资料卡生成 `no_action` 或候选任务，不直接发送消息。
- [ ] 派发器每五分钟读取到期任务，在发送前重新获取当前快照并复核授权、记录状态、暂停、证据、资料、时间窗和容量。
- [ ] 到期任务只能 `send` 或 `skip`，使用稳定 delivery ID 投递；fresh 模型、资料或渠道失败遵守既定一次重试和不盲目重发规则。
- [ ] Hermes 中始终只有日检和派发两个固定健康 Job；派生任务不创建、修改或递归管理原生 Cron。
- [ ] Job capability 与持久 Job 身份、角色和单次执行绑定，普通聊天、其他 Cron 和篡改 Job 不能调用健康 Job 工具。
- [ ] 主验收从真实 Job tick 经过 production plugin、fresh 健康模型、Unix socket、sidecar 和微信投递闭合，并验证固定 Hermes 版本与无 core patch。

## Comments

### 2026-08-11 — implementation stop: trusted native-Job identity unavailable

The pinned, unmodified Hermes scheduler has no supported per-execution Job ID
or immutable execution-snapshot fingerprint available to a pre-run script or
plugin tool. The local research mirror supplies both values only through an
uncommitted scheduler-core change. Without that change, the health pre-run
script fails closed before the agent/plugin is created.

The attempted same-UID HMAC delegation is not a substitute: the partner
runtime can read its symmetric key, so another Cron/plugin can mint a fresh
proof. The installed plugin and pre-run scripts are also partner-owned today,
so their paths alone cannot prove an immutable Job identity. Therefore the
requirement that ordinary chat, another Cron, and a tampered Job cannot invoke
the privileged health Job action cannot be met with the current Hermes public
API and the ticket's no-core-patch condition.

Local production-port and timing work remains uncommitted and must not be
deployed or treated as ticket acceptance. A human decision is needed before
resuming: either pin an upstream Hermes release with an unforgeable
per-execution Job identity contract, or explicitly re-scope the no-core-patch
requirement and approve a maintained scheduler/OS-isolation design.
