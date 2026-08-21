# 【CAN】核验主人身份迁移与恢复所需的身份、凭据和持久化能力

Type: research
Status: resolved
Parent: [健康管家首发 TO、CAN 与 HOW 决策闭合路线](../map.md)
Blocked by: [【TO】确定主人授权聊天身份变化后的健康画像连续性与恢复边界](38-define-owner-identity-continuity-boundary.md), [【CAN】核验目标 Hermes 基线与受支持的健康扩展面](42-verify-target-hermes-baseline-and-supported-extension-surface.md), [【CAN】核验聊天接口、主人身份与逐条消息来源能力](43-verify-channel-owner-identity-and-message-provenance-capabilities.md), [【CAN】核验健康画像、数据权利与保护能力](45-verify-health-record-data-rights-and-protection-capabilities.md), [【CAN】核验微信 iLink 与目标 Hermes 的真实接口能力](52-verify-weixin-ilink-and-target-hermes-interface-capabilities.md), [【CAN】核验健康画像数据平面的可用工具与接口](56-verify-health-data-plane-tools-and-interfaces.md)

## Question

在已经确认的单一主人、单一活动微信私聊身份、同一健康画像连续性和不可恢复锁定 TO 下，目标 Partner Hermes v0.20.0、腾讯微信 iLink 固定实现及目标运行环境，真实提供、限制或缺失哪些可用于身份迁移与身份恢复的身份、凭据和持久化能力？只核验 CAN，不选择凭据形态、数据库结构、交互流程或最终 HOW。

研究至少覆盖：微信侧及 Hermes 侧可稳定识别和绑定的身份字段及其保证边界；旧身份发起、新身份接受的双端确认所需接口；启用前建立且仅由主人控制的一次性恢复权利能否生成、保存、查看准备状态、替换、撤销、原子消费和失效；凭据随机性、有效期、验证、重放防护及进程重启后的持久性；迁移或恢复时原健康画像、来源时间、暂停状态、接收方同意和未发送主动支持如何保持连续；旧、新身份安全通知与不含健康正文的审计记录；失败请求不泄露画像存在性、全部身份与恢复权利丢失后永久失败关闭，以及相关状态如何受备份、恢复和永久删除约束。

结论必须分别记录官方保证、目标固定提交源码行为、目标现场只读事实、尚未证明项及需要主人另行批准的最小实验。不得读取或写入真实健康正文，不得发送微信消息，不得创建、替换或消费真实恢复凭据；如必须通过真实身份或破坏性实验才能确认，只列明目的、外部影响和停止条件并等待批准。产出带固定引用的 Markdown 证据并在本票追加 `## Answer`；若没有可闭合既定 TO 的受支持能力，先报告负向 CAN，由后继 TO 决定是否改变目标或边界，不得直接生成 HOW。

## Answer

证据见 [主人身份迁移与恢复能力核验（2026-08-18）](../evidence/13-owner-identity-migration-recovery-capabilities-20260818.md)。

结论是负向 CAN：目标 Partner Hermes v0.20.0 当前没有已经接通、受支持且能端到端闭合既定 TO 的主人身份迁移/恢复能力。

真实可用的是技术 sender/user id、通用收发、管理员批准式 pairing、Plugin 扩展面、SQLite 事务/备份 API、密码学与 systemd credential 等构件；但 iLink 没有公开保证这些技术 ID 代表唯一真人主人或跨账号生命周期稳定，固定源码也没有旧端发起+新端接受、主人预持一次性恢复权、原子消费、健康画像及暂停/同意/待发状态连续性、双端通知、无健康正文审计或不存在性隐藏。Hermes built-in pairing 的主体和方向是“未知聊天者取码、bot 管理员批准”，且 pending 删除与 approved 写入分属两个文件，不等于既定恢复权。

**构件可用不等于身份迁移/恢复已实现。** 当前通用 restore 还会用旧归档覆盖当前状态；没有独立于备份域的不可回滚代际/锁定锚点，因而不能证明已消费或已撤销权利不会被旧备份复活，也不能证明全部身份与恢复权利丢失后的永久失败关闭。目标现场的 Partner Gateway 实际由 root 用户级 systemd manager 管理并处于 enabled/active/running，但仍没有已安装的 Partner Plugin manifest 或可核验的健康身份恢复状态。尚未证明项和仅可在主人另行批准后进行的最小非健康 canary 已列入证据；本票不选择凭据、存储或交互 HOW。
