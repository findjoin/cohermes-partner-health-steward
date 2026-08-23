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

- `health_weixin` 只接受一个配置的 Partner／主人发送者／私聊会话和 `health-init` 能力。Plugin 与 core 必须在严格协议中携带并精确匹配同一份技术准入策略；core、current head 或 writer 无法证明时，在读取正文前即失败关闭。群聊、准入外、旧 `medical`、来源不明和初始化前普通健康消息不进入健康状态。
- 每次获准来源保留独立 envelope、receipt、因果 ID、协议发送时间、接收时间、Partner 身份和 native cursor。确定 message ID 的重复投递只标为 `possible-replay`；缺失 message ID 时保留 `replay-unknown`，不虚构首次或重复结论。来源到达顺序也纳入认证完整性清单。
- `health-init` 先形成并持久化 pre-consent challenge，challenge 绑定完整版本化主人可见披露、HMAC 使用证明和签发时准入策略；披露发生时间必须严格早于消息协议发送时间与接收时间。主人确认必须来自后续唯一准入消息中的严格 consent evidence，并绑定初始化摘要、披露、首跳路线确认和显式布尔确认。调用方布尔值、模型自述、伪造 HMAC、错误资产或跨入口旧披露都不能形成当前初始化。
- 并发候选不会按“最后写入”静默覆盖。经历史 challenge 和其签发策略验证的不同配置候选会冻结，只有更晚主人消息显式列出冲突来源才可解决。单条微信正文物理上限为 16,384 字节，因此最多允许声明 6 个既有来源因果 ID，并保留第 7 个 active 槽给解决消息；一次配置轮换可额外冻结 1 个同配置失效槽，所以总 unresolved 正文硬上限为 8。不同主人配置不得借替换槽覆盖，第二次轮换在恢复并完成当前解决消息前返回不可用。
- 实际 `health-init` 执行生成完整 HMAC 使用证明；证明、主人确认、空白六域画像、可选支持联系人边界、密钥 ID 和 prepared authority 一并认证加密持久化。支持联系人披露明确区分“预置不是授权”和“整体启用后边界才获批准”；未预置时仍可初始化并显示 `not-configured`。
- 只有 `prepare -> current-head 条件提交 -> finalize` 全部成功才进入 `enabled`。prepare、commit、finalize、模型效果意图签发和执行授权领取都会重新核对当前准入策略、批准资产、证明验证器、installation、writer fence 与 current head；配置漂移返回不持久化的不可用结果，恢复后原请求可继续。远端 CAS 已成功但响应丢失时，只允许原命令按 transition ID 回查闭合，不重复 CAS。
- 初始化业务写、全部解决／被替换来源的 cursor 状态和命令 receipt 在同一权威链中收口；finalize 后才原子清除冻结正文并释放所有 native cursor。directive 丢响应时重发完全相同的指令；派生命令 ID 使用固定长度摘要，不会因 256 字节来源 ID 超出协议边界。cursor 结果为 `advanced` 或 `unknown` 后均为终态，相反结果被拒绝且不重复业务效果。
- Ticket 110 的认证完整性清单只在 Ticket 111 表为空时迁移；非空新表、密文、行身份或来源到达顺序不一致都会失败关闭。Ticket 111 不创建联系人 outbox、逐次批准或交付事实，因此 owner/contact outbound 继续禁止。

本票不实现初始化后的普通／健康粗分流、七 Skill 日常协调和五类普通通知偏好；这些属于 Ticket 112，不在本票中提前实现。

## Comments

### TDD trace

审查缺口先以具名合成测试得到 red，再实现到 green：

- `test_disclosure_challenge_is_prior_durable_and_owner_visible`、`test_disclosure_must_precede_protocol_send_time_and_requires_it`：闭合先披露、完整固定文案、持久 challenge 和严格时间顺序。
- `test_plugin_and_core_admission_policy_divergence_fails_before_body_read`、`test_disclosure_policy_rotation_cannot_replay_or_prepare_old_authority`：闭合 Plugin/core 分叉、跨入口重放和幽灵冲突候选。
- `test_conflict_queue_reserves_one_transportable_resolution_source`、`test_stale_reserved_resolution_slot_is_replaced_after_configuration_rotation`：证明 16,384 字节正文、6 个冲突 ID、1 个解决槽及总 8 条 unresolved 的物理边界。
- `test_source_arrival_order_is_covered_by_the_integrity_manifest`、`test_ticket110_integrity_manifest_migrates_only_with_empty_ticket111_tables`：闭合顺序认证与安全迁移。
- `test_disclosure_configuration_mismatch_does_not_poison_later_replay`、`test_prepare_configuration_mismatch_does_not_poison_later_replay`、`test_resolution_slot_configuration_mismatch_does_not_poison_source_replay`：证明暂态配置失配不写入永久重放结果。
- `test_core_configuration_drift_blocks_effect_intent_issue`、`test_core_configuration_drift_blocks_existing_effect_claim`、`test_divergent_plugin_cannot_claim_core_effect_execution`：把当前初始化配置复核落实到效果签发与实际执行授权。
- 其余具名测试覆盖布尔伪同意、伪造证明、缺失 message ID、最长因果 ID、全来源 cursor 原子释放、返回丢失等价重放和 CAS 未知闭合。

### Verification

- `python -m unittest -q tests.test_ticket111_admission_initialization`：46/46 通过。
- `python -m unittest discover -v`：181/181 通过，其中 Ticket 110 边界回归 135 项、Ticket 111 合成测试 46 项。
- `python -m compileall -q partner_health_steward tests`：通过。
- `git diff --check`：通过。
- Edge、Standards 与 Spec 三路最终审查：P0/P1 均为 0；剩余仅为 challenge/cache 清理和诊断优先级等非阻塞后续重构判断项。

