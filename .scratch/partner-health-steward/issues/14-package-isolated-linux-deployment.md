# 14 — 建立 Linux 账户隔离与部署包

**What to build:** 在唯一的 DMIT Linux 上以两阶段受控生产切换形成可安装、可回滚的 partner-only 部署，使 Hermes 与 sidecar 由不同受限账户运行并通过私有 socket 使用加密数据和备份；不得把该过程称为非生产验收。

**Blocked by:** 01 — 核验真实 partner 服务器基线；05 — 建立受控医学资料库与按需核验；07 — 实现删除、密钥销毁和 memory 投影清理；13 — 接入真实 Hermes 的两个固定 Jobs；18 — 完善自动判别与停止记录生命周期；19 — 用当前画像和权威资料回答健康问题；20 — 通过微信完成主人控制、查看者授权和私密查看；21 — 提供主人导出与二次确认删除；22 — 提供主人控制的身份恢复；23 — 用生产适配器运行两个固定健康 Job；24 — 部署独立运维监控与外部失联告警

**Status:** wontfix

**Historical:** 旧实施路线，已退出当前前沿；仅作为 [`健康管家重规划：TO、Hermes 权威能力与可验收路线`](../map.md) 的待审计输入保留。

- [ ] 部署包只涉及 partner Hermes 与 health-sidecar，不修改 default Hermes、其他 profile、网络代理或无关服务。
- [ ] partner Hermes 以 `hermes-partner` 受限账户运行，sidecar 以 `health-sidecar` 受限账户运行。
- [ ] Unix socket 的所有权和权限只允许 partner Hermes 连接；系统没有新增 health-sidecar TCP 监听器。
- [ ] partner Hermes 无法直接打开 sidecar 数据库、资料缓存或密钥，sidecar 不能读取不需要的 Hermes 私有文件。
- [ ] 健康状态、资料缓存和备份加密存储，并具备恢复、密钥销毁和 30 天备份删除验证流程。
- [ ] 安装前检查、安装、启动、停止、升级和回滚均可重复执行并产生不含秘密的结果证据。
- [ ] 先在不停旧 partner 的阶段完成备份、静态隔离与离线门槛，再在已授权维护窗口通过进程账户、文件权限、socket、两个 Jobs、无 core patch 和无第三 Cron 的同机生产薄集成验收；失败立即恢复旧 partner。

## Comments

- 2026-08-09：本地部署包、systemd 单元、固定 Job 安装、memory 投影、加密恢复/清理、升级/回滚恢复和 Linux 验收向导已经实现并通过双轴代码审查。
- Windows 定向测试 96 项通过、13 项因 AF_UNIX/croniter/Linux 账户与 systemd 环境跳过；上述 checklist 保持未勾选。原定非生产 Linux 路线后由 ADR 0004 的同机两阶段 canary 取代，真实 `scripts/linux_health_smoke_wizard.sh` 仍须在生产接线补齐且即时 smoke 通过后运行。
- 本地实现阶段没有上传或修改真实服务器，也没有改动 default Hermes、其他 profile、网络代理、x-ui/xray 或无关服务。
- 2026-08-09：用户确认只有一台 DMIT 服务器，并接受 partner 可能短暂中断及关键失败立即回滚；验收路线改为 ADR 0004 的同机两阶段受控切换。该授权不允许修改 default Hermes、其他 profile、x-ui/xray、防火墙或无关服务。
- 2026-08-09 阶段 A `no-go`：在上传或迁移前复核生产接线，发现发布插件只注册日检与派发两个 Job 工具，没有微信实时健康消息入档、主人查看/授权/暂停/删除入口或 Ed25519 收据签发端；生产 `sidecar.server.main` 也未装配 LLM、微信发送和资料下载 ports，部署包未启动运行监控。切换后无法通过 Ticket 15 的实时入档、派发、授权和告警门槛，因此未上传、未安装、未停止任何服务。
- 同轮 DMIT 只读基线：`findjoin` 上旧 `hermes-gateway-partner.service` 为 `active/enabled`，PID 143611 仍以 `root:root` 运行；新 sidecar socket 与部署状态均不存在。本轮远端零写入，default Hermes、其他 profile、x-ui/xray、防火墙和无关服务未触碰。
