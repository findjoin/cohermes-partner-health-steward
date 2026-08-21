# 【CAN】核验健康画像数据平面的可用工具与接口

Type: research
Status: resolved
Parent: [健康管家首发 TO、CAN 与 HOW 决策闭合路线](../map.md)
Blocked by: None

## Question

针对目标 Partner Hermes v0.20.0 固定提交与目标运行环境，核验“选择单一健康画像、主人权利与保护路线”实际可以选择的工具和接口：正式 Plugin 的数据目录、配置/secret 注入、启动失败关闭与生命周期接口；目标 Python 环境已经可用且无需安装的事务存储、加密和密钥依赖；Adapter、Plugin Tool/Command 与 `ctx.llm` 的输入输出分别会不会进入普通 Session、Memory、全文索引或日志，以及健康路径可用的无普通历史调用面；模型 provider、endpoint、fallback 和实际接收方能否在发送健康内容前确定并强制允许表；Hermes 通用备份对 Plugin 数据、数据库 WAL/临时文件、密钥和恢复权限的真实覆盖，以及可行的排除、专用备份、恢复与永久删除接口。

研究必须分开记录官方保证、目标固定源码行为、目标现场已验证、仍未知及需要批准才能执行的破坏性或真实健康数据实验；只读核验，不安装依赖、不修改目标、不读取聊天或健康正文、不发送模型/微信请求，也不选择最终 HOW。若某项候选依赖目标现场并未安装或某个安全边界无法由正式接口强制，必须如实排除或标为未验证，不能用一般 Python 可实现性代替目标可用性。

## Answer

目标 Partner Hermes v0.20.0 / commit `3c27eb6234bf91b8ceee9e9071591b31e9b148cb` 没有受管的 Plugin 私有数据目录、配置 accessor、per-plugin secret getter、事务状态、迁移、加密、备份或删除服务。Plugin 是同进程受信任 Python 代码，可以自行使用文件与库；单 Plugin `register()` 或 Hook 失败只记错并让 Hermes 主体继续，普通 Plugin 也没有通用 shutdown/on-unload。因此健康路径的失败关闭、刷盘和恢复不能依赖这些默认行为。

2026-08-17 现场只读核验确认，目标 venv 中可直接使用 Python `3.11.15`、SQLite `3.53.1`（`threadsafety=3` 表示 DB-API serialized 等级，不是三个线程）与 `cryptography 48.0.1`；`Connection.backup`/`serialize` 存在。SQLCipher、keyring、APSW、`aiosqlite`、PyNaCl 和 PyCryptodome 均未安装。systemd 249 支持 Credential 传递，但当前 Partner unit 未接 `LoadCredential*`/`SetCredential*`、受管目录或文件隔离，服务仍以 root 运行；所以在本票核验且无需新增依赖的候选中，已证实可用的是标准 SQLite、密码学原语和一般 OS/systemd 能力，没有现成的加密数据库或独立密钥库。

Adapter 一旦把消息交给标准 handler，普通 Session 会保存 user/assistant/tool call/tool result 并建立全文索引，后续还可能进入普通 Memory；模型调用 Plugin Tool 因此不是健康正文隔离接口。已识别 Plugin slash command、Command 内直接 `ctx.dispatch_tool` 和 out-of-band `ctx.llm` 在固定源码中不自动创建普通 Session/FTS/Memory，但这不保证 Plugin、Tool、日志、微信、provider 或 relay 不留存。

`ctx.llm` 只能限制请求的名义 provider/model/agent/profile，没有 endpoint 允许表、禁用 fallback、route preview 或发送前最终接收方回调；常规 fallback 仍可能把同一健康内容发给其他 provider，relay 下游也未知。故当前没有一条已验证的正式接口同时满足“无普通历史”与“发送前确定全部实际健康数据接收方”。调用后归因不能替代主人事前同意，Ticket 49 不得假定该闸门已存在。

Hermes 全量备份会扫描 Hermes root；只有 `.db` 走 SQLite 在线快照，ZIP 的压缩等级 `6` 不是加密。Plugin DB、临时文件和密钥若未命中硬编码排除项可能被一并复制。quick snapshot 不包含任意 Plugin 数据；通用恢复是覆盖式，只对少数核心文件自动设 `0600`，并无 Plugin schema/权限/完整性或按主人永久删除合同。因此通用 backup 不能直接充当健康备份、恢复或删除机制。

Ticket 56 的 CAN 问题已闭合，但负向结论尚不足以解锁 Ticket 49：必须先由 [核验健康模型调用与实际接收方事前锁定能力](57-verify-health-model-routing-and-recipient-preflight-capabilities.md) 查清同一 Hermes 内是否还有满足该闸门的受支持路线；若仍不存在，则必须转成 TO-CAN 差距决策，不能静默降低愿景。完整官方源码、现场事实、未知项和需审批实验见 [健康画像数据平面工具与接口核验](../evidence/10-health-data-plane-tools-and-interfaces-20260817.md)。

## Comments

### 2026-08-17 — 继承权威说明

本票的工具、接口、现场依赖与通用备份边界作为 CAN 原样继承；`## Answer` 不回写。其中“Ticket 49 尚不得进入 HOW”只记录当时的阻塞状态，后续已由 [【CAN】核验健康模型调用与全部实际接收方事前锁定能力](57-verify-health-model-routing-and-recipient-preflight-capabilities.md)、[【TO】决定健康模型接收方锁定缺口下的产品承诺边界](58-decide-health-model-recipient-lock-gap-boundary.md) 和 [【HOW】选择健康画像数据平面、模型调用与保护路线](49-choose-health-record-rights-and-protection-route.md) 闭合，不再是当前阻塞。
