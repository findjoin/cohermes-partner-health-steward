# 119 - 执行分层 canary 与主人联系人验收门槛

Type: task
Status: ready-for-agent
Parent: [健康管家首发 TO、CAN 与 HOW 决策闭合路线](../map.md)
Blocked by: [118 - 完成 Hermes/Weixin 宿主合同发布与回滚准备](118-complete-hermes-weixin-host-contract-release-and-rollback-preparation.md)

**What to build:** 建立并执行从静态 release 到获准真实主人/联系人验收的分层门槛。每层都必须记录可定位的通过、失败或无法确认事实；未通过项保持不可用或 staged，不得把安装、测试通过、接口接受或模型自述宣传为稳定运行。

**Blocked by:** 118 - 完成 Hermes/Weixin 宿主合同发布与回滚准备

- [ ] 按静态 manifest、合成 core、本机 socket/SQLite/认证加密、崩溃/未知故障、宿主合同、StrictHealthLLM、知识/医学审核、current-head、删除/迁移 canary 的顺序建立门槛。
- [ ] 医学内容权利、冻结中文版本、专业审核、诊断范围激活和外部服务资源均有独立证据；缺失时 BMI 保持 staged，健康路径如实显示不可用或无法确认。
- [ ] 真实模型、真实 Weixin、真实联系人、主人和联系人验收只在单独批准、合成/脱敏前置测试通过且不把凭据/资料写入仓库后执行。
- [ ] 分层结果严格区分业务形成、提交、发送尝试、接口接受、送达、已读/实际行动和未知；未知效果不自动重做。
- [ ] 任何验收失败、可信前提丢失、current-head 不一致、旧 fence 活跃或删除/迁移未闭合都阻止 active/稳定运行声明，并保留回滚路径。
- [ ] 产出可定位的验收报告和剩余硬门槛，未读取或上传真实健康资料、密钥、Token、服务器配置或运行数据库。

