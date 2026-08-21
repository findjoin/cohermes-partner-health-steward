# partner Health Steward v0.2 部署门禁

## Ticket 13 capability and target guard

The installer refuses a target that is not exactly the `profiles/partner`
Hermes home. It creates an integration-only capability key at
`<partner>/private/health-steward-capability.key`; this key is not the sidecar
data key and is never placed in a prompt or ordinary Hermes configuration.
Each pre-run snapshot contains a ten-minute capability bound to the verified
Job id, scheduler fingerprint, and role. The corresponding plugin tool must
present that capability before it can reach the sidecar.

目标 profile：`/root/.hermes/profiles/partner`。

## 当前结论

**禁止生产部署。** v0.2 的功能与本地反例验收已经形成，但 partner Agent 与健康私有库仍处于同一 Unix 用户权限域。字符串级工具 hook 无法阻止动态路径、glob 或代码执行访问数据库；Hermes 其它 cron 写入口也尚未在 core 层统一关闭。必须先完成 [AUTONOMY_V02.md](AUTONOMY_V02.md) 第 6 节的 sidecar/独立用户边界。

本目录的完整自治栈仍只是部署候选源，不代表 partner 服务器现状。未经新的明确授权，不得修改真实 partner profile、创建真实健康 cron，也不得让男朋友代替数据主体授权。2026-08-05 用户另行明确要求把 **Skill 对话层**安装到自己的 default Hermes 试用；该例外只包含下文记录的两个 Skill 文件，不授权把 partner 专用插件、SOUL、数据库、dispatcher 或 cron 搬到 default。

## 候选生效路径

| 本地源 | 未来 partner 路径 |
|---|---|
| `plugin/health-guard/` | `/root/.hermes/profiles/partner/plugins/health-guard/` |
| `plugin/health-autonomy/` | `/root/.hermes/profiles/partner/plugins/health-autonomy/` |
| `skill/health-steward/` | `/root/.hermes/profiles/partner/skills/health-steward/` |
| `scripts/health_autonomy_dispatch.py` | `/root/.hermes/profiles/partner/scripts/health_autonomy_dispatch.py` |
| `scripts/verify_health_guard_preflight.py` | `/root/.hermes/profiles/partner/scripts/verify_health_guard_preflight.py` |
| `systemd/hermes-gateway-partner-health-guard.conf` | `/root/.config/systemd/user/hermes-gateway-partner.service.d/hermes-gateway-partner-health-guard.conf` |

## 两个固定 Hermes Job（Ticket 13）

Ticket 13 的接入资产位于 `plugin/health-steward/`、`scripts/health_steward_*` 和
`hermes_jobs.py`。它们只通过 `PartnerHealthAdapter` 访问 sidecar Unix socket；
不会读取 sidecar 数据库或密钥。部署到 partner profile 后，需在该服务环境中设置：

- `HEALTH_STEWARD_SOURCE_ROOT`：服务器上 `ops/partner-health-steward` 的绝对路径；
- `HEALTH_STEWARD_SOCKET`：sidecar Unix socket 路径；
- `HEALTH_STEWARD_SUBJECT`：唯一画像 subject；
- `HEALTH_STEWARD_TIMEZONE`：主人时区，默认 `Asia/Shanghai`。

启用 `health-steward` 插件后，由运维者显式运行
`python scripts/install_health_steward_jobs.py`。安装器只创建缺失的两个 Job：
`health-daily-profile-review`（主人时区 04:00）和
`health-due-task-dispatch`（每 5 分钟）；发现同名或同脚本配置漂移时失败关闭，
不会更新或删除无关 Cron。两个 Job 均为 Hermes agent Job（不是 `no_agent`），
每次由 Hermes 创建 fresh session；日检预运行脚本只注入一次性不透明 capability，
由 sidecar 在 capability 校验后读取当前快照并以独立 pinned 模型完成规划及持久化
的一次十分钟重试。派发 Job 只获得受控元数据并重新由 sidecar 复核；两个 Job 都不
获得 sidecar 文件、密钥或普通聊天历史。

本节是 staging/验收路径，不代表已在真实 Linux partner 服务上部署或通过生产验收。

> **Ticket 23 No-Go (2026-08-11):** Do not deploy these Job ports. The pinned,
> unmodified Hermes scheduler does not supply a trusted per-execution Job
> identity to the pre-run script or plugin. The local research-only injection
> is an uncommitted core change, and a same-UID symmetric-key proof cannot
> distinguish another Cron or plugin. This gate can reopen only with an
> upstream identity contract or an explicitly approved re-scope of the
> no-core-patch requirement.

## 健康相关轮次回答（Ticket 19）

partner 微信插件在普通文本合批前分流健康相关轮次。健康回答使用独立固定的
provider、HTTPS endpoint、model ID、privacy mode 和 partner auth profile，且不读取
普通会话历史、不开放工具、也不允许 provider fallback。除前述变量外，partner 服务
还必须显式配置：

- `HEALTH_STEWARD_RECEIPT_SIGNER_SOCKET`：仅 Gateway 主进程可访问的入站收据签发 socket；
- `HEALTH_STEWARD_HEALTH_MODEL_CONFIG`：权限受限的健康模型 JSON 快照路径；
- `HEALTH_STEWARD_EXPECTED_OWNER_SENDER_ID`：预配置画像主人微信 sender ID；
- `HEALTH_STEWARD_EXPECTED_VIEWER_SENDER_ID`：唯一预配置只读查看者微信 sender ID，必须与主人不同；
- `HEALTH_STEWARD_HEALTH_SOURCE_CATALOG`：关键词到精确 HTTPS 白名单 URL 的 JSON 路径；
- `HEALTH_STEWARD_HERMES_SOURCE_ROOT`：已验收 Hermes 安装物或源码根，用于微信 transport 来源校验；
- `HEALTH_STEWARD_ACCEPTED_HERMES_VERSION`：已通过微信幂等投递验收的 Hermes 版本；
- `HEALTH_STEWARD_DELIVERY_LEDGER_PATH`：partner 账户可写、只含投递元数据的 SQLite 路径；
- `HEALTH_STEWARD_HEALTH_MODEL_ATTESTATION_PATH`：partner 账户可原子写入的无正文模型接收方证明路径；
- `HEALTH_STEWARD_EXPORT_TMPDIR`：只属于 `hermes-partner` 的绝对 tmpfs 目录；导出 JSON 以 `0600` 写入，发送尝试后立即删除，启动、每次导出及已启用的 systemd 每小时清理器都会在 24 小时上限前清理孤儿文件。

Ticket 20 的 sidecar 服务还必须分别设置
`HEALTH_SIDECAR_EXPECTED_OWNER_SENDER_ID` 和
`HEALTH_SIDECAR_EXPECTED_VIEWER_SENDER_ID`，并与 partner 插件中的两个 sender ID
完全一致。查看者限制会在插件控制面和 sidecar 授权面各校验一次；服务器管理员身份不替代
其中任何一个微信身份。

partner 插件还会把该账号的有效微信私聊入口固定为上述主人和唯一预配置查看者。即使迁移的
Hermes `config.yaml` 原先只允许主人，或包含管理员等额外 sender，插件构建时也会用这两个
已校验 sender ID 覆盖 `dm_policy/allow_from`；环境变量不能绕过这条有效配置边界。

健康模型文件只能包含 `provider`、`endpoint`、`model_id`、`privacy_mode` 和
`auth_profile` 五个字段；endpoint 必须是无凭据、无 query/fragment 的 HTTPS URL。
资料目录只能使用以下固定 schema，URL 仍须通过 sidecar 的来源白名单：

```json
{
  "catalog_schema_version": 1,
  "keyword_urls": {
    "已审核关键词": "https://已审核权威来源/精确路径"
  }
}
```

Hermes 的插件 LLM 权限默认拒绝覆盖。部署配置必须把下列两个占位值替换为健康模型
快照中的精确值，不能使用 `*`：

```yaml
plugins:
  entries:
    health-steward:
      llm:
        allow_provider_override: true
        allowed_providers: [<health-provider>]
        allow_model_override: true
        allowed_models: [<health-model-id>]
        allow_profile_override: true
```

加载插件时会写入不含 prompt、回答或画像正文的模型证明，只记录 provider、规范化
endpoint、model ID、privacy mode、auth profile 和配置 SHA-256。该记录用于如实标注
实际第三方中转与后续变更复验，不能把中转描述成官方直连；每次调用还必须确认响应
返回的实际 model ID 与这份固定 model ID 完全一致，否则该结果失败关闭且不得采用。

当前仓库已闭合可注入 source-fetch port 的 20 秒硬预算，以及真实 Linux sidecar 的
HTTPS 下载器 host/redirect/大小限制。它们仍只是本地发布物和验收路径；缓存未命中
不得据此宣称已经在生产部署完成按需下载。

## 主人导出与永久删除（Ticket 21）

只有预配置主人可以导出完整 JSON，且导出始终由 sidecar 直接生成并经微信 JSON 附件投递；它不进入普通 LLM、聊天历史或文本合批。查看者、管理员和其他 sender 都不能导出。

永久删除必须先发送明确的删除请求，再在 10 分钟内由主人发送独立的“确认删除”动作。请求本身不会删除任何内容；超时、重放、不同请求 ID 或单条消息都会失败关闭。确认成功后会销毁画像密钥、移除当前记录与 projection、撤销投递账本，并只保留 90 天无正文删除审计；加密备份的物理清理仍在 30 天边界执行。

systemd staging 会声明 `/run/partner-health-steward-export` 的 `0700` RuntimeDirectory、一日 tmpfiles 兜底规则，以及启用后按小时运行的私有导出清理 timer（`Persistent=true`）。该规则及本仓库测试只是发布物声明和本地验证，不代表真实 Linux partner 服务已经部署、发送或通过生产验收。已发送的微信附件、普通 Hermes 聊天历史和对方保存的外部副本不能被系统召回。

| `SOUL.health-steward.md` | 以有界 marker 合并到 `/root/.hermes/profiles/partner/SOUL.md` |

运行时私有库目标为 `/root/.hermes/profiles/partner/private/health-autonomy-v02.sqlite3`。在 sidecar 方案完成后，该目录和数据库必须归 sidecar 用户所有，partner Agent 不应拥有文件级读写权。

## 转 Go 前置条件

1. 健康 store/dispatcher 由独立 Unix 用户 sidecar 运行，只暴露带本人路由、平台 message ID、动作 schema 和幂等键的窄 IPC。
2. 将本地镜像 `.research/hermes-agent/cron/scheduler.py` 中的可信 `HERMES_CRON_JOB_ID` 与 `HERMES_CRON_JOB_FINGERPRINT` 注入改动移植到锁定的真实 Hermes 版本；两者必须先清除继承值，再由父 scheduler 根据本次实际执行并最终投递的同一 job 快照覆盖，不能来自 job 配置或普通会话环境。
3. partner Agent 的 terminal、文件、Python、插件、CLI/API/Dashboard 等路径均不能直接读写健康库或创建/修改健康 cron；用绕过样例实际验证，不以字符串扫描代替。
4. 固定 dispatcher 每次执行前核对可信当前 job ID、实际运行/投递快照指纹、数据库受管 ID、唯一脚本引用、持久化完整 cron 指纹、无限 repeat、`no_agent=true`、脚本、prompt、`deliver=origin`、`chat_type=dm` 与本人 route HMAC；快照与持久化记录必须一致，不匹配时先数据库隔离和清理过期数据，再禁止输出。
5. 锁定真实服务器 Hermes commit/版本，重新核验 `pre_gateway_dispatch`、busy/idle、插件命令时序、cron schema 与 origin 投递语义。
6. `plugins.enabled` 同时包含 `health-guard` 和 `health-autonomy`，两者均不在 disabled；`streaming.enabled=false`、`multiplex_profiles=false`、时区为 `Asia/Shanghai`。
7. 发布物由 root 或发布用户所有且不可被运行 Agent 修改；dispatcher 为 `0500`；私有目录/库权限和 owner 由 preflight fail-closed 核验。
8. 全量本地测试通过，生产 staging 再完成未授权零写入、群聊隔离、重放、删除、重启恢复、并发激活、cron 篡改、到期清理与消息路由验收。
9. dispatcher 的指纹拒绝、数据库锁定/损坏、权限拒绝和模块加载失败都必须表现为“空 stdout、退出码 0、Telegram 0 输出”；错误只能以不含健康内容和私有路径的元数据进入管理员日志。当前本地已验证损坏数据库经真实 `run_job(no_agent)` 返回 `[SILENT]`，其余 Linux 故障注入留给 staging。
10. 最后由女朋友本人在真实 partner Telegram 私聊阅读隐私说明并发送完整授权语句；此前 cron 必须为空。

## 未来发布顺序

1. 只读核验 partner Gateway/provider/plugin/skill/cron 和 systemd 当前状态，备份 `SOUL.md`、`config.yaml`、插件、skill、scripts、cron jobs 与 unit drop-in。
2. 在隔离 staging 校验发布物 hash、owner、mode 和真实插件注册；任何漂移停止发布。
3. 只在 partner profile 合并启用插件与关闭 streaming，所有 Hermes CLI 都显式设置 `HERMES_HOME=/root/.hermes/profiles/partner`。
4. 执行同解释器 preflight；只重启 `hermes-gateway-partner.service`。不得触碰 default、x-ui 或 xray。
5. 先做零数据和错误授权验收，再由本人授权；逐项验证状态、暂停、恢复、关闭、删除和旧消息重放。

## 回滚原则

1. 先把数据库 mode 置为隔离并确认 dispatcher 零输出，再按精确 job ID 删除 dispatcher。
2. 只停止 partner Gateway/sidecar，恢复备份的 partner 配置与 SOUL，禁用两个健康插件。
3. 移走发布物到可恢复备份区，不直接破坏；只启动 partner 服务并复验 provider/Gateway。
4. 不重启或修改 default、x-ui、xray。

## 安全声明

本系统不是医疗器械。规则无法覆盖语音转写错误、图片、方言、隐晦表达、非中文输入或全部提示注入；急症、自伤与药物安全只能增强分流，不能替代急救、医生或药师。

## 2026-08-05 default Skill 对话层试用实况

用户明确要求安装到自己的 Hermes。按项目环境矩阵，“自己的 Hermes”落实为 default profile `/root/.hermes`；女朋友的 partner profile 未修改。

- 已安装：`/root/.hermes/skills/health-steward/SKILL.md` 与 `references/medical-safety-sources.md`。
- 未安装：`health-guard`、`health-autonomy`、SOUL 片段、私有数据库、dispatcher 和任何健康 cron。
- 安装前技能清单保存于 `/root/.hermes/backups/health-steward-default-20260805T0338/skills-before.txt`。
- `SKILL.md` 的自动路由描述版 SHA-256 为 `bd3a73e3a9d334877ad3d02a66616debd6ab324a2e8b0c67965baee4de9d2179`；reference SHA-256 为 `a25f84bd9eb14f642a0d11c7ba6c5a71ecc4612ec1da97bf85a64ba501d09151`。首装版本保存在同一备份目录的 `SKILL.before-auto-route.md`。
- 文件属主为 `root:root`，目录 mode `0755`，`SKILL.md` mode `0644`。
- 只重启 `hermes-gateway.service`；2026-08-05 03:41:26 CST 后 default 为 `active/enabled`、`NRestarts=0`，partner 服务继续 `active`，未重启。该重启只证明服务恢复，不会追溯重建既有 channel session 已冻结的 system prompt。
- 显式 `--skills health-steward` 合成验收通过：回复明确只提供非诊断建议，并明确本次没有建立画像、定时任务、主动提醒或保存数据。
- 不带 `/health-steward`、也不使用 `--skills` 的合成消息“我最近总忘记喝水”已验证自主路由：session `20260805_034900_d5304d` 的真实 trace 为 `tool_call_count=1`，唯一工具调用是 `skill_view({"name":"health-steward"})`，随后回复仍明确零保存、零画像、零任务。
- default 微信既有 session `20260804_180056_06defb50` 创建于安装之前，其保存的 system prompt 不含 `health-steward`。第一次“我肚子不舒服”没有调用 Skill；用户追问后才在 assistant message `1449` 调用 `skill_view`，tool message `1450` 加载成功，message `1451` 承认首次漏调用。该反例证明新 CLI 正例不能代表既有微信会话。
- default 微信新 session `20260805_040944_8f40f27b` 的无前缀健康表达最终调用成功：第一次错误请求 `health-steward:health-steward` 返回 not found，第二次纠正为 `health-steward` 并由 tool message `1456` 加载成功。Gateway 只向微信发送最终 190 字回复，没有发送工具进度。
- post-check 显示 default 没有健康私有库或健康插件；现有 cron 列表中的两项非健康任务没有被本次安装修改，也没有新增 `health-steward` 任务。

该状态只允许试用 Skill 的检索、加载和交互规则。产品目标仍是普通健康表达无需 `/health-steward` 前缀，前缀只用于强制加载和排障；现有证据已经覆盖新 CLI 正例和新微信 session 经错误名称重试后的成功命中，同时保留安装前既有微信 session 的真实漏路由反例。以后安装或更新 Skill 后，不得仅凭 Gateway 重启宣称既有 channel session 已刷新，必须分别验收新 session 与既有 session。任何看似“记住偏好”的表现都只来自当前会话上下文，不能称为结构化长期学习。完整自治仍保持生产 No-Go。

微信可见性边界：default 当前全局配置虽为 `display.tool_progress: all`，但 Weixin 不实现消息编辑，Gateway 会清空其工具进度队列。因此“微信没有显示技能名”不等于 Skill 未调用，且单改 `tool_progress` 或 `/verbose` 无法解决。推荐的后续实现是由 Gateway 根据成功的 `skill_view` trace，在最终回复追加只含 allowlist Skill 名称的最小披露；不要把所有工具参数逐条发送到微信。该显示增强尚未实现。
