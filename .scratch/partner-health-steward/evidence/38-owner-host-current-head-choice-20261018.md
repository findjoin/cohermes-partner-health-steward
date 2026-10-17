# 主人选择仅 DMIT 与整机旧快照限制（2026-10-18）

## 决定证据

本会话主人先明确表示没有 AWS 账号，随后明确选择：“仅用 DMIT，接受旧快照恢复限制”。顶层代理已在[原决定记录](../design/deployment-storage-choice-20261018.md#主人决定2026-10-18)记录该输入。此处只把这一个已发生的主人决定接回现有 Map/CONTEXT/ADR/Ticket 链，不再次请求同一决定，也不把决定当作代码或上线证明。

## 决定的精确含义

允许为现有 CurrentHeadPort 实现同机、受限且真实持久化的 head Provider；非诊断部署不再以 AWS 账号作为前提。可以继续保存不透明 head/fence/receipt，不能建立第二画像或业务账本。

明确接受：若整台 DMIT 同时恢复旧健康库、旧 head 与旧秘密，系统不能技术上证明快照后的删除、撤销或迁移，旧状态可能重现。旧快照恢复后须先离线处理健康安装，由主人决定丢弃旧安装并空白重建。不能宣称自动识别旧 VM、域外防回滚或技术上绝不复活。

未接受降低：正常永久删除与当前受管 purge、同意、加密、唯一业务写入、跨进程 CAS、当前 head 下旧 holder fencing、未知效果不盲重试、default/partner 隔离及真实外部门。

## 静态事实与未执行项

- 当前 Port 有九个 typed read/CAS/receipt/proof/lease/lifecycle 方法；当前本地实现仅 InMemory，已有 DynamoDB 生产实现需要外部资源。
- HostPrivateWriterFenceVault 已能提供公开 fence 及非序列化 capability proof；不透明宿主 head 可只保存 capability 的公开校验摘要。
- 本记录未创建 AWS/DMIT 资源、未部署 Provider、未读取秘密/健康资料、未运行真实删除/迁移或模型/微信。
- 唯一后继实现为 [Ticket 129](../issues/129-implement-host-sqlite-current-head-provider.md)，技术候选为 [ADR 0023](../../../docs/adr/0023-allow-owner-selected-host-current-head-with-snapshot-limit.md)。
