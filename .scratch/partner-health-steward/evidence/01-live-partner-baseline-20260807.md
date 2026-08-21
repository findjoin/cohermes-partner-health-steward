# Partner Hermes 真实服务器基线（Ticket 01）

## 1. 核验范围与结论

- 核验时间：2026-08-07 12:29—12:38（Asia/Shanghai）。
- 核验对象：真实服务器上的 `partner` Hermes；同时只读确认 default Hermes、旧账户和受保护服务边界。
- 核验方式：现有 SSH 身份执行只读命令；日志只统计固定事件标记和时间，未输出凭据、用户标识、聊天正文或健康内容。
- 变更结果：服务器零写入、零迁移、零停止、零重启、零测试消息。

当前基线可以作为后续部署起点，但它不是“健康管家已经部署”的证明。当前没有健康 sidecar、健康插件、健康数据库或健康 Cron；partner 仍由 `root` 账户直接运行。

## 2. Hermes 运行基线

| 项目 | 2026-08-07 实测事实 |
|---|---|
| 主机 | `findjoin`，Linux 6.8.0-124-generic x86_64 |
| Hermes | `Hermes Agent v0.20.0 (2026.8.3)`；入口 `/usr/local/bin/hermes`；安装目录 `/usr/local/lib/hermes-agent` |
| Python / OpenAI SDK | Python 3.11.15；OpenAI SDK 2.24.0 |
| partner 服务 | `hermes-gateway-partner.service`：active、running、enabled；核验时 MainPID 143611；启动于 2026-08-07 07:30:33 +08:00 |
| partner 归属 | profile 根目录 `/root/.hermes/profiles/partner`；服务工作目录同上；服务通过 `hermes ... --profile partner gateway run` 启动 |
| partner 进程账户 | `root:root`，尚未按目标架构隔离 |
| default 服务 | `hermes-gateway.service`：active、running、enabled；核验时 MainPID 143552；工作目录 `/root/.hermes` |
| profile 清单 | Hermes CLI 只报告 default 和 partner；`/root/.hermes/profiles` 下只有 `partner` 目录，default 使用 `/root/.hermes` 根目录 |
| systemd 单元 | 两个 Hermes 用户单元均位于 `/root/.config/systemd/user/`；当前均无 drop-in |

账户事实：

- 旧账户 `hermes_partner` 存在，但只有其用户级 `systemd` 与 `(sd-pam)` 会话进程；没有 Hermes 进程，也没有旧的 partner 用户服务单元。
- 目标账户 `hermes-partner` 不存在。
- 目标账户 `health-sidecar` 不存在。

以上均为本次实测事实；历史交接文档只用于定位服务器，没有被当作现状证据。

## 3. 微信接口基线

### 3.1 配置和服务

- partner `.env` 存在，权限 `0600`；微信 token、账户标识和允许用户清单对应的变量均为非空，但本报告未读取或记录其值。
- 安全策略实测为：`WEIXIN_ALLOW_ALL_USERS=false`、`WEIXIN_DM_POLICY=allowlist`、`WEIXIN_GROUP_POLICY=disabled`。
- `config.yaml` 没有显式 `weixin` 节；当前微信配置由 `.env` 提供。`plugins.enabled=[]`，`streaming.enabled=true`。
- 同一份 partner `.env` 还存在 Telegram 配置；这只是当前配置事实，不代表本项目会修改或迁移 Telegram。
- partner 服务重启后，固定日志标记显示微信适配器于 2026-08-07 07:30:45 +08:00 进入 Connected 状态。

### 3.2 最近活动证据与证明边界

在 Hermes v0.20.0 本地源码中，微信处理链的固定标记含义为：

1. `[weixin] inbound`：适配器收到消息；
2. `response ready: platform=weixin`：模型本轮生成完成；
3. `[weixin] Sending response`：进入实际发送路径；
4. 发送失败会记录 `send failed`、`failed to deliver response` 或 `fallback send also failed`。

服务器日志中最近一条可闭合的微信活动链为：

- 2026-08-05 03:49:55 +08:00：微信 inbound；
- 2026-08-05 03:50:02 +08:00：response ready；
- 2026-08-05 03:50:02 +08:00：Sending response；
- 同一时段没有微信发送失败标记。

结合源码的失败记录机制，这支持“该轮首次发送返回成功”的判断；日志没有记录对端已展示或用户已阅读，因此不能把它扩大表述为“用户端收取已独立证明”。两份日志镜像了同一事件，统计时已去重理解为一轮活动。

此外，2026-08-07 07:30:32 与 07:30:48 +08:00 各出现一条微信发送失败标记，时间位于本轮服务启动阶段；本次只读审计不根据日志正文推断原因，也没有发送测试消息。因此当前服务“已连接”已证明，但本次启动后的成功请求—回复闭环尚未证明，必须留给 ticket 15 的显式验收。

## 4. 原生 Jobs 与旧健康原型

- `HERMES_HOME=/root/.hermes/profiles/partner hermes cron list` 返回 `No scheduled jobs.`。
- 因此当前 partner 原生 Job 总数为 0：没有健康相关 Job、重复 Job或旧健康 Cron。
- Cron ticker 仍在运行：`ticker_last_success`/`ticker_heartbeat` 于本次审计期间持续更新；这证明调度器存活，不代表存在任何定时任务。
- 当前存在 `skills/medical`（16 个文件，约 64 KB），应视为已有通用医疗 Skill 资产，后续不得误删或当作健康 sidecar。
- 以下旧健康原型目标均不存在：
  - `skills/health-steward`
  - `plugins/health-guard`
  - `plugins/health-autonomy`
  - `private/health-autonomy-v02.sqlite3`
  - `scripts/health_autonomy_dispatch.py`
  - `scripts/verify_health_guard_preflight.py`
  - partner service 的 health-guard drop-in

## 5. 禁止修改边界

后续实现只允许改变 partner 健康项目明确列出的目标。以下对象不属于本项目：

| 对象 | 当前实测状态 | 边界 |
|---|---|---|
| default Hermes | `hermes-gateway.service` active/enabled，根目录 `/root/.hermes` | 不改配置、不改服务、不复用其会话或数据 |
| 其他 Hermes profile | 当前不存在第三个 profile | 不创建或修改无关 profile |
| x-ui | `x-ui.service` active/enabled；监听 2096、18000 | 禁止停止、重启、改配置或占用端口 |
| xray | 独立 `xray.service` 不活动，但 `xray-linux-amd6` 进程监听 443 | 以实际进程和端口为准，禁止停止、重启、改配置或占用 443 |
| Telegram | partner 中存在当前配置 | 本项目不迁移、不删除、不改凭据 |
| 用户聊天和健康内容 | 现有 sessions/logs/memories | 不复制到报告，不用于无授权调试 |

## 6. 回滚目标清单

本次只记录回滚目标，没有创建备份。进入部署前，应由实施票据对被修改目标制作带时间戳的备份或导出，并验证恢复步骤。

| 目标 | 基线元数据 / 用途 |
|---|---|
| `/root/.config/systemd/user/hermes-gateway-partner.service` | 文件，root:root，0644，955 B；partner 服务定义 |
| `/root/.hermes/profiles/partner/config.yaml` | 文件，root:root，0600，7,786 B；mtime 2026-08-07 07:29:19 +08:00 |
| `/root/.hermes/profiles/partner/.env` | 文件，root:root，0600，23,989 B；含凭据，备份与恢复必须保持 0600，禁止写入报告 |
| `/root/.hermes/profiles/partner/cron` | 目录，root:root，0700；5 个文件，20,516 B；当前 Job 为 0 |
| `/root/.hermes/profiles/partner/skills/medical` | 目录，root:root，0755；16 个文件，64,432 B；已有 Skill 资产 |
| `/root/.hermes/profiles/partner/sessions` | 目录，root:root，0700；13 个文件，1,647,257 B；会话数据 |
| `/root/.hermes/profiles/partner/memories` | 目录，root:root，0700；4 个文件，1,931 B；Hermes 记忆数据 |
| `/root/.hermes/profiles/partner/logs` | 目录，root:root，0700；15 个文件，22,977,550 B；运行证据，不作为配置回滚包 |
| `/root/.hermes/profiles/partner/cache` | 目录，root:root，0700；2 个文件，264,621 B；可再生数据，应与权威数据分开处理 |

未来 sidecar、专用账户、systemd 单元和两个固定 Jobs 当前均不存在；它们应作为新增对象单独登记，回滚方式是按实施记录有序停用并移除新增对象，而不是覆盖现有 partner profile。

## 7. 对 Ticket 14 / 15 的约束

Ticket 14（部署）必须以本基线为前置证据：

- 从零创建 `hermes-partner` 与 `health-sidecar` 隔离边界；不能假定账户已存在。
- 从零创建两个固定 Hermes Jobs；不能迁移或复用不存在的旧健康 Job。
- 保留 `skills/medical`、Telegram 配置、default Hermes 与 x-ui/xray。
- 对每个实际修改的现有目标先生成可定位备份，并保持原 owner/mode。
- 不得把 root 直写 sidecar 私有数据的现状延续为最终权限模型。

Ticket 15（验收）必须重新核验：

- partner 服务、default 服务以及 443/2096/18000 边界均未受损；
- 微信在部署后的真实请求—回复闭环，而不只检查 Connected；
- 两个固定 Jobs 的唯一性、健康状态和重复派发防护；
- sidecar 数据所有权、Hermes 只经受控接口访问、回滚恢复可执行；
- 不输出凭据、用户标识、聊天正文或健康内容。

## 8. 复查方法

复查应继续使用只读方式：Hermes `--version`、`profile list`、`gateway list`、partner `cron list`、systemd show/is-active/is-enabled、进程 owner、目标路径 `stat`、受保护端口 `ss -ltnp`，以及固定日志事件的计数与时间。任何需要发送测试消息、创建备份、改权限、改配置、重启或迁移的动作均不属于本基线票据。
