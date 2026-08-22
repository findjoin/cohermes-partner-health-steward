# 117 - 实现终止删除防复活与 writer-fence 迁移

Type: task
Status: ready-for-agent
Parent: [健康管家首发 TO、CAN 与 HOW 决策闭合路线](../map.md)
Blocked by: [110 - 建立 Plugin/core 受信边界与合成验证骨架](110-establish-plugin-core-trust-boundary-and-synthetic-harness.md), [114 - 实现主人设置数据权利与业务状态](114-implement-owner-settings-data-rights-and-business-status.md), [115 - 实现任务当地日复盘与分层主人投递](115-implement-tasks-local-day-review-and-layered-owner-delivery.md), [116 - 实现安全诊断门禁与支持联系人链](116-implement-safety-diagnostic-gates-and-support-contact-chain.md)

**What to build:** 让主人能够永久删除全部受管健康对象并让已删除状态不可复活，同时让完整健康状态可以在 writer fence 下迁移到新实例。删除、迁移、模型、任务和外发必须共享冻结和代际边界；任何终态未知都保持健康关闭，不重放未知效果。

**Blocked by:** 110 - 建立 Plugin/core 受信边界与合成验证骨架; 114 - 实现主人设置数据权利与业务状态; 115 - 实现任务当地日复盘与分层主人投递; 116 - 实现安全诊断门禁与支持联系人链

- [ ] 永久删除先冻结健康读写、任务推进、模型调用、outbox 和外发，再条件推进不可逆 terminal generation。
- [ ] terminal 确认后销毁健康密钥并清除画像、证据、任务、批准、控制、诊断、安全、联系人、警报、outbox、未知、索引、备份、导出和迁移暂存；站外已交付内容不宣称可召回。
- [ ] 删除响应未知时健康保持关闭，不声明全部旧副本已阻止，也不允许旧快照复活启用、批准或撤回状态。
- [ ] 迁移生成覆盖 Plugin/core/Skill/适配器/模型接口/知识/安全/诊断 bundle、语义状态、控制、任务、投递、未知、删除和迁移事实的 hash-checked manifest；秘密只重新配置。
- [ ] 目标实例在 manifest、密钥、bundle、路线和 current head 验证前离线；一次 CAS writer-fence 转移后源端、旧 VM 和旧 fence 无法写入、调用模型或发送。
- [ ] 合成故障测试覆盖 terminal delete、旧快照、CAS 冲突、转移超时、双写竞态、旧 fence、密钥销毁顺序和未知转移。

