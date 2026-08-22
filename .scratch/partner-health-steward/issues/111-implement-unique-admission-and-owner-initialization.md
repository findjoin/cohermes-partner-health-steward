# 111 - 实现唯一准入与主人初始化

Type: task
Status: ready-for-agent
Parent: [健康管家首发 TO、CAN 与 HOW 决策闭合路线](../map.md)
Blocked by: [110 - 建立 Plugin/core 受信边界与合成验证骨架](110-establish-plugin-core-trust-boundary-and-synthetic-harness.md)

**What to build:** 让唯一获准私聊消息在原生去重、合批和 cursor 推进前进入 `health_weixin`，形成保真 envelope 并由 Plugin/core 管理 receipt、重投和业务提交；让主人通过 `health-init` 完成一次真实初始化，只有 prepare -> 条件提交 -> finalize 全部成功后才启用健康管家。

**Blocked by:** 110 - 建立 Plugin/core 受信边界与合成验证骨架

- [ ] allowlist 只承担技术准入，不被宣传为现实身份核验或知情同意；群聊、准入外、旧 `medical`、来源不明消息不进入健康处理。
- [ ] envelope 保留逐条来源、消息因果 ID、时间、Partner 身份和必要正文；Plugin/core 持久化 receipt 与重投关系，业务提交确认后才推进受管/native cursor。
- [ ] `health-init` 实际运行并产生系统可证明的使用事实和主人披露；安装、加载或模型自述不能冒充使用。
- [ ] 初始化说明、主人同意、首跳模型路线同意、时区/偏好、资料与联系人边界、初始画像、密钥和 current-head 状态共同完成 prepare/commit/finalize。
- [ ] 初始化中断、缺失、失败或未知保持未启用，不读取初始化前健康聊天，不倒填安全/画像/任务，不产生普通健康结果。
- [ ] 重投、崩溃和已提交但披露/交付未知的分支保持分层事实，不重复业务效果。

