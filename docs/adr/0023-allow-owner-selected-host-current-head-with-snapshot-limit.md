# 允许主人选择宿主 current-head 并明确整机快照限制

状态：技术实现候选；产品恢复边界已由主人于 2026-10-18 明确接受。对应 [Ticket 129](../../.scratch/partner-health-steward/issues/129-implement-host-sqlite-current-head-provider.md)。本 ADR 不证明 Provider、部署或产品验收已经完成。

## 决定输入

主人没有 AWS 账号，并在本会话明确选择“仅用 DMIT，接受旧快照恢复限制”。[决定证据](../../.scratch/partner-health-steward/evidence/38-owner-host-current-head-choice-20261018.md)记录精确范围。ADR 0022 的其他受信边界继续有效；其外部 DynamoDB 资源前提与整机旧快照新鲜性保证，在这次明确选择的 host-sqlite 部署模式中由本后继边界取代。旧 DynamoDB 实现与历史证据不删除、不修改、不冒充新模式的证明。

## 候选实现

在既有 CurrentHeadPort 增加真实 `HostSQLiteCurrentHead`：受限的独立宿主 SQLite 只承载不透明 head/fence 与 transition/lifecycle/lease receipts。HealthCore 仍是健康正文/画像/证据/任务/批准与 outbox 的唯一业务写入者，加密业务库不变。采用原九方法 typed 合同、事务 CAS、exact recovery、capability hash 验证、terminal generation 与 writer transfer；无 InMemory/synthetic 生产 fallback。

正常打开不创建缺失 head，只有明确 bootstrap 新 installation 可排他创建。生产选择显式声明 `host-sqlite`；没有 AWS 凭据不触发隐式 Provider 切换。内容寻址 release、运行身份、路径权限、未知冻结及受管删除仍需验证。

## 已接受与未降低的保证

保留正常服务/进程重启、当前 SQLite 崩溃恢复、跨进程 CAS、当前 head 下的旧 holder fencing、效果 unknown 冻结、当前受管文件与备份 purge、单写迁移、同意和加密。

不能保证同时恢复旧健康库、head 与密钥的整机快照不会恢复删除/撤销/迁移前状态；纯同机软件无法证明快照之后发生过什么。此模式不宣称域外新鲜性或自动旧 VM 检测。整机旧快照恢复后须离线，由主人决定丢弃旧健康安装并重新空白初始化；这是已接受操作限制，不能改写成技术防复活保证。

正常永久删除不得因此变成软删除或省略受管备份/导出/联系人清理。新的空白安装不覆盖或解除旧 terminal namespace。最高权限控制主体仍在既有不承诺边界内。

## 证明边界

独立门需证明真正宿主磁盘/进程并发与恢复，不以 unit fake/内存状态冒充生产持久化。目标部署与验收在同一 128 run 中记录 Provider、当前 head、ACL、恢复与限制；DynamoDB 的账号/IAM/外部 old-snapshot 证据不适用于本模式，也不能伪造为 passed。医学权利、真实模型/微信和主人验收各门仍独立。
