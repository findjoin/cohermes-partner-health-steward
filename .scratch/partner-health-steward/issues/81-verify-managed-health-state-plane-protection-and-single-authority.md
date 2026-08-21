# 【CAN】核验受管健康状态数据平面、保护隔离与单一权威能力

Type: research
Status: resolved
Parent: [健康管家首发 TO、CAN 与 HOW 决策闭合路线](../map.md)
Blocked by: [【CAN】核验当前 Partner Hermes 基线、Plugin 生命周期与可信执行边界](78-verify-current-partner-hermes-baseline-plugin-lifecycle-and-trust-boundary.md)

## Question

当前目标 Hermes 的 Plugin 私有状态接口、SQLite/文件类持久化、系统凭据与密码学能力、Session/Memory/全文索引/日志/临时文件/备份路径，分别能够或不能怎样承载同一套受管健康状态：六域画像、三类证据卡、健康任务、批准与撤回、控制状态、诊断修订、结果未知、交付事实和历史关系？

本票必须核验对象唯一标识与引用、候选和最终结果隔离、相关状态原子提交、崩溃或部分写入后的异常/无法确认、恢复后的单一当前权威，以及全部受管正文、副本、缓存、临时资料、密钥和备份是否可完整枚举。健康正文不得进入普通 Session、通用 Memory、普通日志或本机明文静态副本；库已安装、数据库可写、文件权限存在或某条调用不自动建 Session 都不能证明完整合同成立。

本票只报告候选数据与保护原语、限制和未知，区分官方合同、固定源码、当前目标依赖与获准故障实验；不选择数据库、schema、加密算法、路径、备份或事务 HOW。故障注入、备份恢复或任何可能改变正式状态的实验必须另行取得主人批准。

## Comments

### 2026-08-20 — 由完整 TO 能力链重建创建

本票对应[【CAN】重建完整 TO 的能力链与追溯关系](76-rebuild-complete-to-capability-chain-and-traceability.md)中的 C04。

本票重建[【CAN】核验健康画像、数据权利与保护能力](45-verify-health-record-data-rights-and-protection-capabilities.md)，并条件继承[【CAN】核验健康画像数据平面的可用工具与接口](56-verify-health-data-plane-tools-and-interfaces.md)在相同版本和依赖指纹下的事实，不继承旧 HOW 对 SQLite 或加密路线的选择。

### 2026-08-20 — 当前后继调查按运行框架合并

本票 Answer 中指向独立主人权利调查的历史后继，现由[【CAN】按连贯技术问题压缩并重接剩余能力调查](94-consolidate-current-can-investigations-by-coherent-route.md)重接到[【CAN】核验健康任务与受管运行框架的生命周期、复盘投递、主人控制、三态观测及迁移能力](83-verify-open-health-task-lifecycle-dispatch-acceptance-and-scope-approval.md)。本票的 C04 负向事实与证据边界不变。

## Answer

完整调查、事实分层与一手引用见[《受管健康状态数据平面、保护隔离与单一权威能力核验》](../evidence/22-managed-health-state-plane-protection-and-single-authority-20260820.md)。本轮只读取官方合同、固定源码、当前仓库候选与目标 Partner 的脱敏元数据；没有读取健康或聊天正文、凭据、数据库、备份或日志内容，也没有写入远端、发送消息、调用模型、重启、恢复备份或注入故障。

2026-08-20 15:22–15:24 的当前现场证明：Python `3.11.15`、SQLite `3.53.1`、`cryptography 48.0.1` 和 systemd `249` 提供了事务数据库、密码学函数、凭据传递与服务隔离的候选原语。但正式 Partner 仍以 `root` 运行，当前 unit 没有接入 systemd 凭据、受管目录或主要 sandbox 闸门；profile 中没有健康 Plugin manifest，仓库候选 sidecar 及其状态、密钥、备份、投影和导出目录也未部署。这些依赖和权限只证明可用构件，不证明受管健康状态已成立。

固定 Hermes 合同没有 Plugin 私有受管状态、事务、迁移、per-plugin secret、备份或当前权威服务。标准 Agent 路径会把消息、Tool 调用与结果、实际 API 内容写入普通 Session/FTS，Memory、普通日志、cache、Cron 和通用 backup/export 又有独立生命周期。某条直接调用不自动建 Session，不能推出模型、relay、日志、Memory 或备份链路不会形成副本。因此这些普通表面既不是健康权威，也不能自动证明健康正文隔离。

当前工作树 sidecar 仅是未部署的旧候选。它有局部正向构件：个人证据候选可与画像版本及当前指针在一个 subject 修改中提交，主状态文件使用临时文件、`fsync` 和替换，部分删除、未知交付与导出路径也有专用恢复或清理设计。但它仍是旧画像、证据、任务、viewer 和非诊断对象模型；主状态、audit、source cache、两套 delivery ledger、明文 `memory.json` 投影、key、backup 和 export 又不属于一项全局事务。该明文投影还会向所有非 Cron 会话注入画像派生的互动偏好，未按微信、发送者或主人过滤，因而是“健康派生正文不进普通会话或本机明文静态副本”的直接反例。

结论：C04 在当前 Partner 中**未实现且未证明**。当前没有完整受管对象清单与唯一引用、统一的候选/最终隔离、相关状态共同提交、崩溃后的失败或无法确认结果、恢复后单一当前权威，也没有覆盖正文、内存、索引、日志、缓存、临时文件、密钥、备份与域外副本的运行时权威 manifest。本票不证明主人权利、删除防复活、三态观测或整体迁移已成立，它们继续由各自后继能力票核验。

这是一项负向 CAN，不降低任何 TO，不选择 SQLite、sidecar、schema、密码学、路径、事务或备份 HOW。旧数据平面事实只在相同版本与依赖指纹下条件继承；旧身份防回滚和域外代际目标已失效，其一般旧状态复活风险只交由[【CAN】核验主人数据权利、分离控制、永久删除与防复活能力](90-verify-owner-rights-control-deletion-and-non-resurrection.md)继续核验。在形成实际当前候选后，才值得另行取得主人批准，用非真实健康资料做故障、恢复、密钥与副本闭包实验。
