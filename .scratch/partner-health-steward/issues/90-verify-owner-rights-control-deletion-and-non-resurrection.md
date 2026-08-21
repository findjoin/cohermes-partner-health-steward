# 【CAN】核验主人数据权利、分离控制、永久删除与防复活能力

Type: research
Status: wontfix
Parent: [健康管家首发 TO、CAN 与 HOW 决策闭合路线](../map.md)
Blocked by: [【CAN】核验健康能力入口、初始化门禁与真实结果返回能力](79-verify-health-capability-entry-initialization-gate-and-result-contract.md), [【CAN】核验受管健康状态数据平面、保护隔离与单一权威能力](81-verify-managed-health-state-plane-protection-and-single-authority.md), [【CAN】核验紧凑六域健康画像与三类证据卡的维护追溯能力](82-verify-six-domain-portrait-and-three-class-evidence-capabilities.md), [【CAN】核验健康任务与受管运行框架的生命周期、复盘投递、主人控制、三态观测及迁移能力](83-verify-open-health-task-lifecycle-dispatch-acceptance-and-scope-approval.md), [【CAN】核验当地自然日复盘、通知投递、未知结果与故障恢复能力](84-verify-local-day-review-notification-delivery-unknown-and-recovery.md), [【CAN】核验诊断修订链、依据失效传播与单一当前权威能力](89-verify-diagnostic-revision-chain-and-current-authority.md), [【CAN】核验有依据的非诊断健康问答与真实结果能力](93-verify-evidence-grounded-nondiagnostic-health-answer-capabilities.md)

## Question

基于完整受管数据清单和全部健康能力入口，当前候选能力能否让主人查看、纠正、导出同一画像当前快照，并沿索引访问相关证据、任务、阶段、批准、未知、交付和诊断修订历史；导出默认人可读并可提供机器可读形式，不含完整聊天，也不形成第二份继续变化的权威画像。画像更新能否如实返回已更新、未更新、拒绝、失败或无法确认，行为设置又只改变联系时间、表达和主动联系偏好而不关闭安全规则？

本票必须分别证明暂停主动支持、停止新增记录、任务取消、执行批准撤回和永久删除的真实效果，不引入含义模糊的“关闭但保留资料”全局状态。暂停主动支持只停止普通主动询问、关心和提醒，不自动取消任务或撤回另行批准的受控动作；停止新增记录期间仍可临时回答主人主动提出的健康问题和执行危险处置，但不长期写入停止期间的新健康内容、不建立相应新任务，恢复后也不倒填；取消任务停止其后续阶段和动作，但不抹掉已经发生或结果未知的外部效果；撤回执行批准使尚未开始的动作不得发出，并让已经发出或结果未知的动作停止后续推进和重试、保留真实未知，而不自动把任务冒充为已解决或已取消。永久删除要覆盖产品仍持有或控制的全部当前/历史受管正文、索引、临时资料、缓存、日志、临时导出、任务、批准、未知、交付和备份，停止读取、推断、复盘、任务和联系；不承诺删除主人已下载、微信、模型服务或其他站外主体持有的副本，也不把已发生站外动作说成已撤回。外部结果未知时不为等待站外结果而拖延本地删除。旧 Hermes/Plugin/备份/VM 状态不得复活已删除资料、已撤回批准或已终结任务；删除后只有主人主动发起的完全空白初始化，不关联旧状态。

永久删除能力不新增倒计时、固定保留期、删除回执、失联自动清理或管理员代删承诺；核验不得把这些未承诺功能反向写成成功条件。

本票只调查本地、备份与必要域外候选原语能否支撑这些结果，并沿用“不主动对抗恶意最高权限主体”的信任边界。文件删除、数据库行消失、加密存在、WORM、快照或 CAS 文档都不能单独证明防复活。删除、恢复、旧状态注入或密钥操作属于高风险实验，必须使用可丢弃数据并另行取得主人批准；本票不选择存储、密钥、墓碑、备份或域外服务 HOW。

## Comments

### 2026-08-20 — 由完整 TO 能力链重建创建

本票对应[【CAN】重建完整 TO 的能力链与追溯关系](76-rebuild-complete-to-capability-chain-and-traceability.md)中的 C14。

本票吸收[【CAN】核验抵抗旧状态恢复的身份权威锚点能力](68-verify-non-rollback-owner-identity-authority-anchor-capabilities.md)和[【CAN】核验域外身份代际权威候选的强一致与防回滚能力](71-verify-external-owner-generation-authority-candidates.md)中“旧状态可能复活”的通用事实，但明确取消身份迁移、恢复权和身份代际 No-Go，只服务永久删除、撤权和任务终态。

### 2026-08-20 — 被连贯受管运行框架调查吸收

本票对应的 C14 没有取消，也没有被视为已经证明；查看、纠正、导出、更新真实结果、五种分离控制、完整永久删除、站外副本边界、旧状态防复活和删除后空白初始化，现由[【CAN】核验健康任务与受管运行框架的生命周期、复盘投递、主人控制、三态观测及迁移能力](83-verify-open-health-task-lifecycle-dispatch-acceptance-and-scope-approval.md)统一调查。旧身份迁移、恢复权和身份代际 No-Go 仍不恢复。本票改为 `wontfix` 只表示不再作为独立 Frontier 或 CAN 闭合前提；原 Question 保留作追溯输入，不在本票追加 Answer。重接决定见[【CAN】按连贯技术问题压缩并重接剩余能力调查](94-consolidate-current-can-investigations-by-coherent-route.md)。
