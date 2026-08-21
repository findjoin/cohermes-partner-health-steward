# 主人身份迁移与恢复能力核验（2026-08-18）

## 结论

这是负向 CAN：目标 Partner Hermes v0.20.0 当前没有一项已经接通、受支持且能闭合既定 TO 的端到端“主人身份迁移/恢复”能力。

目标栈确实有若干可复用构件：微信 iLink/Hermes 暴露技术用户标识和收发接口；Hermes 有管理员批准式 pairing、Plugin 扩展面和原子单文件写；运行环境有 Python、SQLite、`cryptography` 和 systemd；Hermes 也有通用备份/恢复。但是，**构件可用不等于身份迁移/恢复已实现**。现有能力没有同时提供真实主人的稳定身份证明、旧端发起与新端接受、主人预持的一次性恢复权利、跨状态原子消费、健康画像连续性、双端安全通知、非健康正文审计、无画像存在性泄露的失败响应，以及“全部身份与恢复权利丢失后不可被备份回滚解除”的永久失败关闭。

其中最硬的 CAN 缺口是不可回滚性：Hermes 通用恢复会用归档中的旧文件覆盖当前文件；如果未来把撤销、消费或永久锁定只保存在可恢复文件/数据库里，恢复旧快照就可能复活旧状态。固定源码与目标现场均未发现独立于该恢复域的单调代际、外部不可回滚锚点或已经实现的身份恢复状态机。因此当前证据不能证明既定 TO 可由现成能力闭合。

## 范围与证据纪律

- 目标源码固定为 Hermes `v0.20.0`、提交 `3c27eb6234bf91b8ceee9e9071591b31e9b148cb`；微信上游实现固定为 Tencent `openclaw-weixin` `v2.4.6`、提交 `cef0bfc390393f716903e16d50408118047f87e0`。
- 只检查了与身份、pairing、Plugin、持久化、备份和运行环境有关的固定源码、官方文档以及目标主机的只读元数据。
- 没有读取或写入健康正文，没有输出微信身份值或凭据，没有发送微信/模型请求，没有创建、替换、撤销或消费恢复凭据，也没有改动服务或配置。
- 下文严格区分“官方公开接口/保证”“固定源码行为”“目标现场事实”“推论”和“尚未证明”。源码能说明客户端现在怎样做，不能自动升级为腾讯服务端对身份稳定性或真人归属的保证。

## 逐项 CAN 核验

| 既定 TO 所需能力 | 官方公开接口/保证 | 固定源码行为 | 目标现场只读事实 | CAN 判定 |
|---|---|---|---|---|
| 稳定识别并绑定主人 | iLink 消息模型公开 `from_user_id`，扫码确认响应可带 `ilink_user_id`；这些字段在公开 TypeScript 类型里均是可选字段。公开材料没有承诺其跨重新登录、换账号、账号回收或主体变更时稳定，也没有把它定义为真人身份证明。 | Hermes 把 `from_user_id` 原样作为技术 sender id；扫码登录把可选 `ilink_user_id` 保存为账号元数据。它没有把该值与“唯一主人”或健康画像建立受认证绑定。 | 固定提交仍在位，所核验的身份/Plugin/pairing/备份文件没有工作树差异；Partner Plugin 目录中 `plugin.yaml` 数量为 0。 | **部分构件存在，主人身份保证缺失。** 技术 ID 可路由，不能据此证明真人归属或长期身份连续性。 |
| 旧身份发起、新身份接受 | 官方接口允许接收来自某个 `from_user_id` 的消息，也允许向 `to_user_id` 发送消息；发送响应只有 API 返回码/错误文案，没有“目标真人已接收/同意”的交付保证。 | Hermes 能产生 inbound `MessageEvent`，也能向技术 chat id 发送；没有 migration proposal、双端 nonce、旧端授权、新端接受、竞争请求仲裁或切换提交点。 | 未执行双身份微信试验；目标上没有已安装的健康 Plugin 来提供该状态机。 | **接口原语有，双端迁移协议未实现且未被服务端保证。** |
| 启用前由主人预持的一次性恢复权利 | Python `secrets` 官方保证操作系统级密码学安全随机源，并提供 token 与常量时间比较；`cryptography` 官方提供 AEAD 与密码 KDF。官方文档只保证这些原语的语义，不保证本产品已正确组合它们。 | Hermes built-in pairing 生成 8 位、32 字符字母表的随机码（码空间 `32^8 = 2^40`），保存带盐 SHA-256 摘要，设一小时有效期并有限流、批准、撤销和磁盘持久化。但流程是“未知聊天者拿到码，再让 bot 管理员从 CLI/dashboard 批准”，不是主人启用前预持并独占控制的恢复权利。 | Python `3.11.15`、`cryptography 48.0.1` 已安装；未发现 Partner Plugin manifest，Partner profile 三层内未发现匹配 `*/pairing/*` 的普通文件。没有读取任何凭据值。 | **密码学与 pairing 构件可用；既定恢复权利不存在。** built-in pairing 的权利主体、发放时机和批准方向均不等于 TO。 |
| 查看准备状态、替换、撤销、原子消费、重放防护、重启持久化 | SQLite 官方保证单事务提交的原子性；Python `sqlite3` 提供事务上下文与在线 backup API。 | Pairing 的 pending 与 approved 是两个 JSON 文件；每个文件用临时文件、`fsync`、重命名单独原子写，但批准过程先删除并保存 pending，再另存 approved，两个状态之间没有一个共同事务，崩溃窗口可留下“两边都无”的状态。它也没有“恢复权已消费”的健康身份语义。 | 目标 Python 链接 SQLite `3.53.1`，`threadsafety=3`，`Connection.backup` 可用；但目标没有相应 Plugin/数据库/恢复记录。 | **底层事务能力存在；一次性恢复生命周期及其原子性未实现。** 进程锁也不能替代跨进程/崩溃事务证明。 |
| 迁移/恢复后维持同一画像及关联状态 | 没有发现微信或 Hermes 官方接口对健康画像、来源时间、停止记录、暂停主动支持、模型接收方同意或未发送主动联系队列作任何定义。 | 所检查的 Weixin adapter、Plugin API 和 pairing 代码只传递通用消息/账号/批准状态；没有上述健康状态字段，也没有把这些状态与身份切换放在同一提交中的逻辑。 | Partner profile 没有已安装 Plugin manifest；本次未打开任何健康数据或消息正文。 | **缺失。** SQLite 可以承载将来的原子关联，但固定产品没有现成健康连续性事务。 |
| 旧、新身份通知与无健康正文审计 | iLink/Hermes 提供通用发送能力；没有迁移通知或不可否认审计的上游契约。 | 通用发送返回 API 层结果和本地 client id；固定源码没有 migration/recovery audit event、旧/新端通知联动、审计保留/删除边界。 | 没有发送测试消息；没有发现提供该功能的 Partner Plugin。 | **通用发送可用，安全通知和审计未实现；“已送达主人”也未证明。** |
| 失败不泄露画像存在性 | 上游没有健康画像查询或恢复接口，因此没有这项产品级保证。 | Built-in pairing 的响应围绕 pairing 码和管理员批准，不查询健康画像；这不能证明未来健康恢复入口对“存在/不存在”返回一致。 | 没有可供黑盒核验的恢复入口。 | **未证明。** 目前不是“实现后通过”，而是尚无被测功能。 |
| 全部身份与恢复权利丢失后的永久失败关闭 | SQLite 官方说明 backup 产生一致快照；WAL 是数据库持久状态的一部分。`secure_delete` 只处理数据库页中的删除内容且有边界，并不删除外部备份。systemd credentials 可以把秘密交给服务，但不提供业务上的不可回滚代际。 | Hermes full backup 会遍历并归档未排除的 profile/root 文件，数据库用 SQLite 安全复制；导入/恢复把归档成员覆盖到当前路径。quick snapshot 只含固定白名单，不含任意未来 Plugin 状态，也不含完整 Weixin 状态。源码没有恢复后拒绝旧授权世代的锚点。 | 2026-08-18 03:09 +08:00，root 用户级 `hermes-gateway-partner.service` 为 enabled/active/running；目标仍没有 Partner Plugin manifest，也没有可核验的永久锁状态。 | **关键负向 CAN。** 仅靠当前通用备份域内的状态不能证明永久锁；旧快照可回滚撤销/消费/锁定，quick snapshot 又可能漏掉状态。 |

## 固定源码证据

### 微信 iLink：技术标识可见，但身份保证有限

1. Tencent 固定实现把消息的 `from_user_id`、`message_id`、`seq`、时间、session 和 context token 都声明为可选字段；这证明客户端能接收这些字段，不证明每条必有或跨账号生命周期稳定：[types.ts L153-L205](https://github.com/Tencent/openclaw-weixin/blob/cef0bfc390393f716903e16d50408118047f87e0/src/api/types.ts#L153-L205)。
2. 扫码确认响应中的 `ilink_user_id` 也是可选字段；确认分支要求 bot id/token，却不会把 user id 提升为必填：[login-qr.ts L36-L45](https://github.com/Tencent/openclaw-weixin/blob/cef0bfc390393f716903e16d50408118047f87e0/src/auth/login-qr.ts#L36-L45)、[login-qr.ts L385-L407](https://github.com/Tencent/openclaw-weixin/blob/cef0bfc390393f716903e16d50408118047f87e0/src/auth/login-qr.ts#L385-L407)。
3. 客户端会把可选 user id 与账号凭据一同保存在本地，并用它清理同一 user id 的旧本地账号项；这是客户端实现行为，不是腾讯关于真人归属或永续稳定的服务契约：[accounts.ts L74-L110](https://github.com/Tencent/openclaw-weixin/blob/cef0bfc390393f716903e16d50408118047f87e0/src/auth/accounts.ts#L74-L110)、[accounts.ts L161-L220](https://github.com/Tencent/openclaw-weixin/blob/cef0bfc390393f716903e16d50408118047f87e0/src/auth/accounts.ts#L161-L220)。
4. 官方 README 描述扫码确认、本地保存 credentials、多账号登录、`getUpdates` cursor 和向 `to_user_id` 发送；未给出用户 ID 稳定、账号再分配、真人所有权、双端迁移或送达回执保证：[README L41-L60](https://github.com/Tencent/openclaw-weixin/blob/cef0bfc390393f716903e16d50408118047f87e0/README.md#L41-L60)、[README L125-L177](https://github.com/Tencent/openclaw-weixin/blob/cef0bfc390393f716903e16d50408118047f87e0/README.md#L125-L177)、[README L254-L267](https://github.com/Tencent/openclaw-weixin/blob/cef0bfc390393f716903e16d50408118047f87e0/README.md#L254-L267)。

Hermes 固定 adapter 延续这一边界：它保存 token/base URL/可选 user id（[weixin.py L234-L273](https://github.com/NousResearch/hermes-agent/blob/3c27eb6234bf91b8ceee9e9071591b31e9b148cb/gateway/platforms/weixin.py#L234-L273)），按账号和 user id 持久化 context token（[L276-L319](https://github.com/NousResearch/hermes-agent/blob/3c27eb6234bf91b8ceee9e9071591b31e9b148cb/gateway/platforms/weixin.py#L276-L319)），并把 `from_user_id` 用作 sender 技术 ID（[L1341-L1406](https://github.com/NousResearch/hermes-agent/blob/3c27eb6234bf91b8ceee9e9071591b31e9b148cb/gateway/platforms/weixin.py#L1341-L1406)）。扫码确认仍把 `ilink_user_id` 当作可选元数据保存（[L967-L1089](https://github.com/NousResearch/hermes-agent/blob/3c27eb6234bf91b8ceee9e9071591b31e9b148cb/gateway/platforms/weixin.py#L967-L1089)）。没有源码把这些值认证为健康画像主人。

发送路径需要技术目标 ID，并可附带 context token；API 成功只能证明请求返回路径，没有主人接受/交付收据：[Tencent send.ts L19-L92](https://github.com/Tencent/openclaw-weixin/blob/cef0bfc390393f716903e16d50408118047f87e0/src/messaging/send.ts#L19-L92)、[Tencent api.ts L471-L489](https://github.com/Tencent/openclaw-weixin/blob/cef0bfc390393f716903e16d50408118047f87e0/src/api/api.ts#L471-L489)、[Hermes weixin.py L413-L465](https://github.com/NousResearch/hermes-agent/blob/3c27eb6234bf91b8ceee9e9071591b31e9b148cb/gateway/platforms/weixin.py#L413-L465)。

### Hermes pairing：有凭据原语，但不是既定恢复权利

1. 固定源码明确其语义是“未知用户收到一次性码，由 bot owner 在 CLI 批准”，并列出有效期、限流、锁定与常量时间比较等安全构件：[pairing.py L1-L18](https://github.com/NousResearch/hermes-agent/blob/3c27eb6234bf91b8ceee9e9071591b31e9b148cb/gateway/pairing.py#L1-L18)、[L46-L59](https://github.com/NousResearch/hermes-agent/blob/3c27eb6234bf91b8ceee9e9071591b31e9b148cb/gateway/pairing.py#L46-L59)。Gateway 给未知聊天者的提示同样要求 bot owner 运行批准命令：[run.py L14330-L14389](https://github.com/NousResearch/hermes-agent/blob/3c27eb6234bf91b8ceee9e9071591b31e9b148cb/gateway/run.py#L14330-L14389)。
2. pairing code 由密码学随机选择生成，保存随机盐加 SHA-256 摘要；支持过期、失败计数和批准检查：[pairing.py L580-L721](https://github.com/NousResearch/hermes-agent/blob/3c27eb6234bf91b8ceee9e9071591b31e9b148cb/gateway/pairing.py#L580-L721)、[L814-L895](https://github.com/NousResearch/hermes-agent/blob/3c27eb6234bf91b8ceee9e9071591b31e9b148cb/gateway/pairing.py#L814-L895)。这说明有组件，不说明它满足主人预持恢复权的威胁模型。
3. PairingStore 把 pending、approved 和 rate limit 分别存在 JSON 文件并使用进程内 `RLock`（[L405-L500](https://github.com/NousResearch/hermes-agent/blob/3c27eb6234bf91b8ceee9e9071591b31e9b148cb/gateway/pairing.py#L405-L500)）。单文件写有临时文件、`fsync` 和原子重命名（[L379-L402](https://github.com/NousResearch/hermes-agent/blob/3c27eb6234bf91b8ceee9e9071591b31e9b148cb/gateway/pairing.py#L379-L402)），但批准顺序先删除 pending 并落盘，再写 approved（[L585-L607](https://github.com/NousResearch/hermes-agent/blob/3c27eb6234bf91b8ceee9e9071591b31e9b148cb/gateway/pairing.py#L585-L607)）。所以固定实现没有跨两文件的原子消费。
4. 固定 Plugin API 可以注册 platform/hook，加载失败会被隔离记录；同名 platform 注册最后写入者覆盖。这是扩展面，不是身份恢复实现：[plugins.py L865-L908](https://github.com/NousResearch/hermes-agent/blob/3c27eb6234bf91b8ceee9e9071591b31e9b148cb/hermes_cli/plugins.py#L865-L908)、[L1629-L1688](https://github.com/NousResearch/hermes-agent/blob/3c27eb6234bf91b8ceee9e9071591b31e9b148cb/hermes_cli/plugins.py#L1629-L1688)、[platform_registry.py L209-L225](https://github.com/NousResearch/hermes-agent/blob/3c27eb6234bf91b8ceee9e9071591b31e9b148cb/gateway/platform_registry.py#L209-L225)。

### 持久化、备份与永久锁

- Python 官方 `secrets` 文档保证密码学强随机与操作系统随机源，并提供 token/`compare_digest`；它也建议密码采用带盐强单向哈希：[secrets — Generate secure random numbers](https://docs.python.org/3.11/library/secrets.html)。`cryptography 48.0.0` 官方文档提供 [AEAD](https://cryptography.io/en/48.0.0/hazmat/primitives/aead/) 和 [password KDF（含 Scrypt/Argon2id）](https://cryptography.io/en/48.0.0/hazmat/primitives/key-derivation-functions/)。这些是构件保证，凭据形态和参数属于后继 HOW。
- SQLite 官方说明事务把一组变更作为一个单位提交，单次最多一名 writer；原子提交意味着一个事务中的修改全有或全无：[Transactions](https://www.sqlite.org/lang_transaction.html)、[Atomic Commit](https://www.sqlite.org/atomiccommit.html)。Python `sqlite3` 提供 [事务上下文](https://docs.python.org/3.11/library/sqlite3.html#how-to-use-the-connection-context-manager) 和 [Connection.backup](https://docs.python.org/3.11/library/sqlite3.html#sqlite3.Connection.backup)。这能承载将来的状态机，但当前产品没有相应 schema/事务。
- SQLite 官方特别说明 WAL 是数据库持久状态的一部分，不能与数据库文件分离；完成的 backup 是一致快照：[WAL persistence](https://www.sqlite.org/wal.html)、[SQLite Online Backup API](https://www.sqlite.org/backup.html)。`secure_delete` 也只约束数据库删除页，不能替代备份销毁：[PRAGMA secure_delete](https://www.sqlite.org/pragma.html#pragma_secure_delete)。
- systemd 官方说明服务可通过只读 credential 目录取得 credential；这是秘密交付构件，不是一次性业务权利或不可回滚机制：[systemd Credentials](https://systemd.io/CREDENTIALS/)。目标 root 用户级 Partner gateway unit 正在运行，但本次只读核验没有发现或验证由该 unit 接通的身份恢复 credential；服务 active 本身不能证明恢复权已实现。
- Hermes full backup 遍历未排除文件并对数据库做 SQLite 安全复制：[backup.py L44-L76](https://github.com/NousResearch/hermes-agent/blob/3c27eb6234bf91b8ceee9e9071591b31e9b148cb/hermes_cli/backup.py#L44-L76)、[L489-L568](https://github.com/NousResearch/hermes-agent/blob/3c27eb6234bf91b8ceee9e9071591b31e9b148cb/hermes_cli/backup.py#L489-L568)。import/restore 会把归档成员覆盖到当前路径（[L732-L800](https://github.com/NousResearch/hermes-agent/blob/3c27eb6234bf91b8ceee9e9071591b31e9b148cb/hermes_cli/backup.py#L732-L800)）；quick snapshot 只收固定白名单（[L891-L920](https://github.com/NousResearch/hermes-agent/blob/3c27eb6234bf91b8ceee9e9071591b31e9b148cb/hermes_cli/backup.py#L891-L920)）。因此可直接推出：若撤销/消费/永久锁只存在于这些可恢复文件中，旧 full backup 能回滚它；而 quick snapshot 又可能遗漏未来 Plugin 状态。源码没有补充不可回滚代际检查。

## 目标现场只读快照

初次核验时间：`2026-08-18T03:01:37+08:00`；systemd 作用域纠正复核：`2026-08-18T03:09:19+08:00`；主机：`findjoin`。

- `/usr/local/lib/hermes-agent` 的 HEAD 为 `3c27eb6234bf91b8ceee9e9071591b31e9b148cb`。对 `gateway/platforms/weixin.py`、`gateway/pairing.py`、`hermes_cli/plugins.py`、`gateway/platform_registry.py`、`hermes_cli/backup.py`、`utils.py` 的限定 `git status --short` 无输出。
- **systemd 作用域纠正：** 初次命令使用裸 `systemctl`，查询的是系统级 manager；该作用域中确实只有 enabled/active 的 `hermes-dashboard.service`，并没有 Partner unit，但不能据此判断 root 用户级服务不存在。复核 `loginctl show-user root` 得到 `Linger=yes`、user manager `State=active`；`systemctl --user` 得到 root 用户级 `hermes-gateway-partner.service` 为 loaded/enabled/active/running，`Type=simple`、`Restart=always`、`RestartUSec=5s`、`MainPID=143611`、`WorkingDirectory=/root/.hermes/profiles/partner`。同一用户级 manager 还运行默认 `hermes-gateway.service`。因此正确事实是：Partner Gateway 当前由 **root 用户级 systemd manager** 管理并运行，系统级 manager 只管理 dashboard。
- `/root/.hermes/profiles/partner/plugins` 下 `plugin.yaml` 数量为 `0`；Partner profile 最深三层内匹配 `*/pairing/*` 的普通文件数量为 `0`。这只证明所查路径当前没有相应构件，不证明其他未查路径绝无文件。
- 目标环境为 Python `3.11.15`、SQLite `3.53.1`、`sqlite3.threadsafety=3`，`sqlite3.Connection.backup` 可调用，安装 `cryptography 48.0.1`。没有为此创建数据库或秘密。

## 尚未证明与最小批准实验

以下事实不能由公开合同、固定源码和只读现场闭合。每项都需要主人另行批准；本票没有执行。

1. **两个真实微信身份的字段稳定性及双端确认可达性。** 最小实验：使用两个由主人控制的测试身份，仅发送不含健康信息的随机标记，记录去标识化的 sender/receiver 字段存在性、旧端发起、新端接受和两端通知结果，并跨 gateway 重启复测。外部影响是产生少量真实微信消息；任一消息发往非测试身份、字段错配或出现健康内容立即停止。重新扫码/换绑会改变凭据，必须单独获得更高风险批准。
2. **候选恢复状态机的并发、崩溃与重放性质。** 只有后继 HOW 形成候选实现后，才能在隔离 canary profile 中用纯合成身份和合成 credential 验证 prepare/replace/revoke/consume、并发双消费、各提交点强杀与重启。外部影响限定为 canary 文件和进程重启；任何真实 profile 路径或真实凭据被触及立即停止。
3. **备份回滚与永久锁。** 在隔离 canary 中先消费/撤销合成权利并进入锁定，再恢复消费前快照，验证旧状态是否被拒绝。该实验会故意破坏 canary 当前状态并执行 restore，只能在可丢弃副本上进行；命令解析到 Partner 正式 profile 就立即停止。
4. **不存在性隐藏和审计/通知完整性。** 只有存在实际恢复入口后，才能用“存在画像”和“不存在画像”的合成主体比较响应、时序、日志和通知；不得放入真实健康正文。任何响应暴露真实标识或写入正式审计域立即停止。

这些实验能证伪具体实现，却不能凭一次测试证明“未来任何旧备份都无法解除永久锁”。该性质仍需要可审查的不变量、恢复程序及其验证证据；本研究不选择其 HOW。

## 直接回答 Ticket 61

- **真实提供：** 技术 sender/user id、通用入站/出站消息接口、pairing 的随机码/摘要/有效期/限流/批准/撤销构件、Plugin 扩展面、SQLite 事务和备份 API、密码学原语、systemd credential 构件、Hermes 通用备份/恢复。
- **真实限制：** iLink 身份字段可选且无真人归属/跨生命周期稳定保证；发送成功不是主人接受；built-in pairing 是管理员批准未知用户而非主人预持恢复；其跨 pending/approved 变更不是单事务；通用备份恢复不理解撤销、消费或永久锁语义。
- **真实缺失：** 旧端+新端双确认迁移、同一健康画像及相关状态连续提交、主人控制的一次性恢复权生命周期、双端通知、无健康正文审计、不泄露存在性的失败接口、备份回滚后仍不可解除的永久失败关闭，以及目标现场已安装/运行的健康身份恢复 Plugin。
- **因此：** 当前只能认定“可以找到构件供后继设计评估”，不能认定“身份迁移/恢复已实现”或“既定 TO 已被目标栈支持”。
