# 111 - 实现唯一准入与主人初始化

Type: task
Status: resolved
Parent: [健康管家首发 TO、CAN 与 HOW 决策闭合路线](../map.md)
Blocked by: [110 - 建立 Plugin/core 受信边界与合成验证骨架](110-establish-plugin-core-trust-boundary-and-synthetic-harness.md)

**What to build:** 让唯一获准私聊消息在原生去重、合批和 cursor 推进前进入 `health_weixin`，形成保真 envelope 并由 Plugin/core 管理 receipt、重投和业务提交；让主人通过 `health-init` 完成一次真实初始化，只有 prepare -> 条件提交 -> finalize 全部成功后才启用健康管家。

**Blocked by:** 110 - 建立 Plugin/core 受信边界与合成验证骨架

- [x] allowlist 只承担技术准入，不被宣传为现实身份核验或知情同意；群聊、准入外、旧 `medical`、来源不明消息不进入健康处理。
- [x] envelope 保留逐条来源、消息因果 ID、时间、Partner 身份和必要正文；Plugin/core 持久化 receipt 与重投关系，业务提交确认后才推进受管/native cursor。
- [x] `health-init` 实际运行并产生系统可证明的使用事实和主人披露；安装、加载或模型自述不能冒充使用。
- [x] 初始化说明、主人同意、首跳模型路线同意、时区/偏好、资料与联系人边界、初始画像、密钥和 current-head 状态共同完成 prepare/commit/finalize。
- [x] 初始化中断、缺失、失败或未知保持未启用，不读取初始化前健康聊天，不倒填安全/画像/任务，不产生普通健康结果。
- [x] 重投、崩溃和已提交但披露/交付未知的分支保持分层事实，不重复业务效果。

## Answer

Ticket 111 已在当前 Partner Health Plugin 合成边界内完成：

- `health_weixin` 只接受一个配置的 Partner／主人发送者／私聊会话和 `health-init` 能力。正文在严格头部准入后才读取；群聊、准入外、旧 `medical`、来源不明和初始化前普通健康消息不进入健康状态。
- 每次来源保留独立 envelope、receipt、因果 ID、时间、Partner 身份和 native cursor。确定 message ID 的重复投递记录为 `possible-replay`；缺失 message ID 时保留 `replay-unknown`，不虚构首次或重复结论。
- 主人确认必须来自该唯一准入消息中的严格 consent evidence，并绑定初始化摘要、披露版本、固定披露主题和首跳路线确认。core 再验证该证据；调用方布尔值、模型自述、伪造 HMAC 或错误资产不能形成初始化。
- 实际 `health-init` 执行生成完整 HMAC 使用证明；证明、主人确认、空白六域画像、可选支持联系人边界、密钥 ID 和 prepared authority 一并加密持久化。重启后 exact prepare replay 复用原证明，不重新执行 Skill，也不丢失完整响应。
- 只有 `prepare -> current-head 条件提交 -> finalize` 全部成功才进入 `enabled`。commit/finalize 会重新核对当前准入配置、批准资产、证明验证器、installation、writer fence 和 current-head；配置漂移保持不可用且可在恢复后继续。远端 CAS 已成功但响应丢失时，只允许原命令按 transition ID 回查闭合，不重复 CAS。
- 初始化业务写、来源 cursor 状态和命令 receipt 处于同一事务；finalize 后才释放正文并签发一次 native cursor directive。cursor 结果为 `advanced` 或 `unknown` 后均为终态，相反结果被拒绝且不重复业务效果。
- 支持联系人未预置时仍可初始化，状态明确为 `not-configured`。Ticket 111 不创建联系人 outbox、逐次批准或交付事实，因此 owner/contact outbound 继续禁止。

本票不实现初始化后的普通／健康粗分流、七 Skill 日常协调和五类普通通知偏好；这些属于 Ticket 112，不在本票中提前实现。

## Comments

### TDD trace

审查缺口先以具名合成测试得到 red，再实现到 green：

- `test_caller_booleans_without_owner_message_consent_evidence_cannot_prepare`：最初缺少 consent evidence 类型／绑定，随后 Plugin 和 core 双层拒绝仅有布尔值的请求。
- `test_missing_native_message_identifier_preserves_replay_ambiguity`：最初实际为 `first-observation`，修复后为 `replay-unknown`。
- `test_initialization_without_preconfigured_support_contact_is_allowed`：最初抛出 `invalid support contact boundary`，修复后可完整 finalize 且保持 `not-configured`。
- `test_cursor_is_released_only_after_finalize_and_unknown_does_not_repeat_business`：最初相反终态抛出未处理异常，修复后返回可重放的 `native-cursor-result-terminal` 拒绝。
- `test_commit_and_finalize_revalidate_current_admission_and_health_init_asset`：最初配置漂移仍返回 `accepted`，修复后不推进 head，配置恢复后同一命令可继续。
- `test_prepare_replay_after_runtime_restart_reuses_the_durable_exact_proof` 与 `test_ambiguous_remote_commit_can_close_read_only_during_config_drift` 覆盖完整证明跨重启重放、正文释放后重放和 CAS 丢响应后的只读闭合。

### Verification

- `python -m unittest discover -v`：157/157 通过，其中 Ticket 110 边界回归 135 项、Ticket 111 合成测试 22 项。
- `python -m compileall -q partner_health_steward tests`：通过。
- `git diff --check`：通过。
- Standards 审查：0 个硬阻塞；记录的重复 peer guard、字符串状态和分散 dispatch 属后续重构判断项，不改变本票协议或验收结果。
- Spec 审查：主人确认绑定、缺失 message ID 歧义、可选联系人和持久等价重放均已修复；初始化后路由与日常通知偏好按 Ticket 112 边界保留。

