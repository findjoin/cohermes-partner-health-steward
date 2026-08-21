# 抵抗旧状态恢复的身份权威锚点能力核验（Ticket 68）

## 1. 结论

这是**负向 CAN**：截至 2026-08-18，目标 Partner Hermes、当前 DMIT/KVM 来宾、已选择的健康 Plugin 专用 SQLite/加密备份数据平面以及目标现场已安装依赖中，没有一项已经配置、接通并得到端到端证明的权威能力，可以保证旧状态恢复后仍拒绝已经失效的身份、已经使用/替换/撤销的恢复权利和不可恢复锁定之前的状态。

本地 SQLite 事务、AEAD、`fsync`、Hermes full backup、quick snapshot、Plugin 专用加密备份、单独文件、watchdog、QEMU Guest Agent 和 DMIT 快照/异机备份都能解决各自的一致性、完整性、恢复或可用性问题，但**不能证明恢复后的本地状态仍是最新代际**。只要“当前身份授权代际”与它的判断逻辑、密钥或本地计数器一起位于可恢复的来宾域内，恢复同一旧状态就会同时恢复旧数据和旧检查依据。

能够承载既定 TO 的最小能力类别必须位于被保护的来宾恢复域之外，并至少提供：对当前代际的强一致读取、以预期旧代际为条件的线性化更新（CAS）、只能前进不能接受较小代际的业务约束、唯一转换标识及状态摘要、明确成功/条件失败/结果未知三种结果，以及网络分区或权威不可用时失败关闭。当前现场没有这样的已配置资源或凭据接线；因此健康管家可以安装 Plugin，但初始化、创建正式健康画像、保存健康资料、产品级验收和正式上线继续保持 No-Go。

本报告不选择锚点、服务、供应商、凭据、协议或 HOW。文中外部服务只用于核对公开能力语义，不代表项目已经选择、购买、配置或能够调用它们。

## 2. 范围、继承前提与证据纪律

- 继承的产品边界来自 [Ticket 67](../issues/67-decide-owner-recovery-anti-rollback-launch-promise.md)：失效身份、已使用/替换/撤销的恢复权利和不可恢复锁定不得因恢复旧状态而复活；该性质未被证明前不得完成健康管家初始化、保存健康资料、产品级验收或上线，运行中无法确认时全部健康与身份处理失败关闭。
- 继承的现有能力来自 [Ticket 61 / Evidence 13](13-owner-identity-migration-recovery-capabilities-20260818.md)：目标栈有技术身份、Plugin、SQLite、密码学与通用备份构件，但没有主人恢复状态机或独立于通用恢复域的不可回滚锚点。
- 继承的数据平面路线来自 [Ticket 49](../issues/49-choose-health-record-rights-and-protection-route.md)：同一健康 Plugin 使用专用 SQLite、应用层认证加密、OS/systemd 凭据和 Plugin 专用加密备份；这些是已选择 HOW，不是已经部署的现场能力。
- 固定 Hermes 源码为 v0.20.0 / commit [`3c27eb6234bf91b8ceee9e9071591b31e9b148cb`](https://github.com/NousResearch/hermes-agent/commit/3c27eb6234bf91b8ceee9e9071591b31e9b148cb)。本次现场复核确认 `/usr/local/lib/hermes-agent` 仍在该 HEAD，`hermes_cli/backup.py` 对该文件的限定 Git 状态无差异，SHA-256 为 `b572bdf36d2724cbe703519e2b7c3ecee6c8e587b1082c092692fa38e0eba47a`。
- 目标现场只读快照时间为 `2026-08-18T06:45:23+08:00`，主机仍为 `findjoin`。本次只读取版本、虚拟化、块设备、设备存在性、服务状态、命令/包存在性、常见配置目录存在性和 unit 指令数量。
- 没有读取 secret、凭据值、身份值、健康或聊天正文，没有查询云实例 metadata credential，没有创建云资源、表、bucket、对象或记录，没有修改配置、写锚点、恢复任何备份、制造故障、重启服务、发送模型或微信请求。

## 3. 各恢复路径实际回滚什么

| 恢复路径 | 固定或已选择的行为 | 身份权威后果 |
|---|---|---|
| Hermes full backup/import | full backup 扫描 Hermes root 中未排除的文件，`.db` 使用 SQLite 在线快照；ZIP 不加密。import 把归档成员覆盖到当前路径，但不删除归档外的当前文件。[扫描与 SQLite 分支](https://github.com/NousResearch/hermes-agent/blob/3c27eb6234bf91b8ceee9e9071591b31e9b148cb/hermes_cli/backup.py#L49-L78) [归档与恢复](https://github.com/NousResearch/hermes-agent/blob/3c27eb6234bf91b8ceee9e9071591b31e9b148cb/hermes_cli/backup.py#L504-L620) [覆盖式 import](https://github.com/NousResearch/hermes-agent/blob/3c27eb6234bf91b8ceee9e9071591b31e9b148cb/hermes_cli/backup.py#L738-L870) | 包内身份/授权/恢复状态可被旧归档回滚；包外 Plugin DB 可能保持较新，形成 Hermes 与 Plugin 代际不一致。两种结果都不是“旧状态必被拒绝”。 |
| Hermes quick snapshot/restore | quick snapshot 是固定白名单，包含部分 Hermes 核心状态，但不包含任意未来 Plugin 数据。[固定白名单](https://github.com/NousResearch/hermes-agent/blob/3c27eb6234bf91b8ceee9e9071591b31e9b148cb/hermes_cli/backup.py#L971-L1003) [quick restore](https://github.com/NousResearch/hermes-agent/blob/3c27eb6234bf91b8ceee9e9071591b31e9b148cb/hermes_cli/backup.py#L1249-L1324) | 它可能回滚 Hermes/渠道/会话一侧而不回滚专用 Plugin 状态，制造跨域不一致；“没有回滚 Plugin DB”不等于具备反回滚权威。 |
| Plugin 专用 SQLite 与加密备份 | Ticket 49 选择用 SQLite 一致快照并在写出前认证加密，密钥与数据库/备份分离。 | SQLite 事务保证一次提交的原子性，AEAD 能检测密文篡改；但旧的合法密文、旧 DB、旧密钥状态可以作为一个完整旧集合恢复。真实性与一致性不证明新鲜度或最新代际。 |
| 人工文件恢复 | 操作者可以只恢复某一 DB、配置、credential、密钥、身份文件或备份。 | 局部恢复会产生代际组合；如果没有域外当前代际，Plugin 只能在本地旧证据之间猜测，不能证明哪一份最新。 |
| 整盘/虚拟机快照 | 当前来宾只有一个 20 GiB `vda`，根文件系统为 `/dev/vda1` 上的 ext4；QEMU 正式支持保存/恢复来宾设备状态，`snapshot-load` 建议纳入所有自快照后可变化的可写块设备。[QEMU save/restore](https://www.qemu.org/docs/master/devel/migration/main.html) [QMP snapshot-load](https://www.qemu.org/docs/master/interop/qemu-qmp-ref.html#command-snapshot-load) | 整体回到旧时间点会同时回滚数据库、文件、密钥、缓存状态、代码与本地计数器。来宾内没有不随该恢复回滚的本地事实。 |
| DMIT snapshot / automated backup | DMIT 官方描述 instant snapshot 为 point-in-time snapshot，可在数秒内 rollback；automated backup 是 scheduled、off-host backup。[DMIT Cloud Instance](https://www.dmit.io/pages/cloud-instance) | “异机”只表示副本故障域，不表示业务状态不可回滚。官方页面没有提供客户可读写的单调代际、CAS、不可覆盖身份记录或恢复后拒绝旧状态的合同；snapshot/backup 本身正是旧状态来源。当前账号是否启用这些 add-on 也未由来宾内证明。 |

所以必须明确区分：Hermes restore 只会覆盖归档内成员，域外 Plugin DB 可能不随之回滚；整机/虚拟机 snapshot 则会覆盖整个来宾本地状态。前者产生不一致，后者产生整体陈旧；二者都不能代替独立权威锚点。

## 4. 目标主机、虚拟化层与本地硬件事实

### 4.1 现场已验证

- Ubuntu `22.04.5 LTS`，kernel `6.8.0-124-generic`，`systemd-detect-virt` 返回 `kvm`。
- DMI 为 `QEMU`、Q35 标准机型；现有项目运维记录把该唯一主机标为 DMIT。来宾 DMI 本身是通用 QEMU 标识，不能从来宾内证明具体 DMIT 套餐、控制台权限或 backup/snapshot add-on 已启用。
- 唯一持久块设备为 `vda`，根分区 `vda1`、ext4；未发现第二块独立持久盘。
- `/dev/tpm*` 不存在，EFI variables 目录不存在；当前没有可供来宾直接使用的 TPM NV counter 或 UEFI 单调状态。
- `cloud-id` 为 `nocloud`，seed 来自 `/dev/sr1`；NoCloud 提供启动配置输入，不提供业务单调代际。
- `qemu-guest-agent.service` 与 `watchdog.service` 均为 active。QEMU 官方说明 Guest Agent 允许 hypervisor 读取/写入来宾文件、设置时间、冻结文件系统等；这证明它属于宿主管理/快照协作面，不是独立于宿主的身份权威。[QEMU Guest Agent](https://www.qemu.org/docs/master/interop/qemu-ga.html)
- 即使以后增加模拟 TPM，也不能未经平台合同就把它当作反回滚锚点；QEMU 官方明确支持 TPM emulator 状态随 VM save/restore、网络迁移和 snapshot 迁移。[QEMU TPM Device](https://www.qemu.org/docs/master/specs/tpm)

### 4.2 本地机制的保证边界

| 机制 | 能保证 | 不能保证 |
|---|---|---|
| SQLite 单事务、WAL、online backup | 单一 DB 提交原子性与一致快照 | 恢复的是最新快照；跨 DB/文件/域外服务单事务；旧合法快照失效 |
| AEAD、hash、签名 | 内容未被未知密钥方篡改、内容摘要相同 | 内容是最新代际；旧的正确签名记录已经失效 |
| `fsync`、原子 rename | 单文件落盘与替换边界 | 另一文件、外部服务或旧备份与它处于同一代际 |
| systemd credential | 把 credential 交给 unit | 业务状态单调；credential 不被整机快照回滚；root 不能替换进程 |
| watchdog / service restart | 进程故障后尝试恢复 | 当前授权代际仍新鲜；恢复时未加载旧状态 |
| qemu-ga / filesystem freeze | 帮助宿主取得更一致的来宾快照 | 该快照不会回滚；来宾能拒绝宿主恢复旧快照 |

## 5. 目标现场可用外部依赖

### 5.1 已安装但未形成可用权威

- Hermes venv 中有 `boto3 1.42.89`、`botocore 1.42.97`、`httpx 0.28.1` 和 `requests 2.33.0`。它们证明目标 Python 能构造一般 HTTPS 或 AWS API 客户端，不证明存在 AWS 账号、目标资源、权限、网络可达、配额、计费或数据处理合同。
- 未发现 `aws`、`az`、`gcloud`、`doctl`、`hcloud`、`linode-cli`、`vultr-cli`、`openstack`、`rclone`、`restic`、`borg`、`vault`、`consul`、`etcdctl`、`mc`、`s5cmd`、`systemd-creds` 或 `tpm2_getcap` 命令。
- 常见 AWS/Azure/GCP/rclone/hcloud/linode/doctl/kube/vault/consul 配置目录存在性检查无结果；没有读取任何配置或 credential。
- 没有发现本机 Vault、Consul、etcd、PostgreSQL、MySQL/MariaDB、Redis、MinIO、CockroachDB 或 MongoDB systemd unit。
- `hermes-gateway-partner.service` 的 unit 文本中，`LoadCredential=`、`LoadCredentialEncrypted=`、`SetCredential=`、`SetCredentialEncrypted=`、`StateDirectory=` 及所查文件隔离指令数量均为 0。当前没有为身份权威服务接线的 unit credential。

因此准确现场结论是：**客户端构件存在，外部权威资源未证明存在或可调用。** 本次没有通过读取环境、credential provider chain 或云 metadata 来“试探”账号，因为那会触及禁止读取的凭据边界；也没有发出任何外部写入。

### 5.2 一手合同能证明的外部能力类别（不是项目选择）

- DynamoDB 官方说明，带 `ConsistentRead=true` 的表读取返回所有先前成功写入后的最新值；`UpdateItem` 的 condition expression 只有条件为真才执行。这类接口能表达“读当前代际 + 仅当当前代际等于预期值时推进”的原语。[强一致读取](https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/HowItWorks.ReadConsistency.html) [条件更新](https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/Expressions.ConditionExpressions.html)
- S3 官方支持 `If-Match`/`If-None-Match` 条件写；Object Lock compliance mode 能在保留期内阻止包括账号 root 在内的用户覆盖或删除**指定对象版本**。但 Object Lock 不阻止创建新版本或 delete marker，因此单独锁住旧版本并不等于“当前代际指针不可伪造”；它还会带来保留期、账号删除和永久删除边界。[条件写](https://docs.aws.amazon.com/AmazonS3/latest/userguide/conditional-writes.html) [Object Lock](https://docs.aws.amazon.com/AmazonS3/latest/userguide/object-lock.html)

这些合同只证明现实中存在相应原语，不证明目标已经获得任何该类服务。即使 API 原语满足，仍必须单独证明真实账号/资源、region、权限策略、credential 启动、删除与保留、费用、可用性和故障行为；本票没有进行这些选择或验证。

## 6. 能承载既定 TO 的最小语义事实

下列是由既定 TO 和回滚模型直接推出的能力约束，不是具体 HOW：

1. **域外当前代际**：权威记录必须不随 Hermes full/quick、Plugin backup、人工文件恢复或整机/VM snapshot 一同恢复。
2. **强一致读取**：每次启用、身份处理、健康处理和提交前必须能确认读取的是所有已成功转换之后的当前代际；默认 eventually consistent 读取不足以排除刚发生的撤销/消费。
3. **线性化条件推进**：只有持有预期当前代际与唯一转换标识的请求可以把 `generation=N` 推进为 `N+1`；并发第二次消费必须条件失败，不能 last-write-wins。
4. **不可倒退**：接口或受强制策略保护的写入路径不得接受较小 generation 覆盖当前值。只保留追加日志但不能可靠确定唯一当前头，也不足以单独放行健康处理。
5. **绑定最小摘要**：域外事实至少需要把 generation 与不含健康正文的身份授权状态摘要、转换 ID/哈希和终止状态绑定；只存一个裸整数无法发现本地状态被替换成同代不同内容。
6. **三态结果**：远端明确成功、条件失败和结果未知必须分开。超时可能发生在远端已经提交之后，不能猜成失败并盲目重做。
7. **分区失败关闭**：网络、DNS、TLS、credential、远端服务、强一致读取或条件写无法确认时，当前授权状态为“无法确认”，健康处理、身份迁移和恢复全部停止；明确无关健康的普通聊天可继续。
8. **跨域非原子性**：SQLite 与域外服务没有一个现成共同事务。任何未来路线都必须证明远端先提交、本地先提交以及响应丢失各窗口如何恢复；本票只确认这是必须验证的依赖，不选择协议。
9. **最小外部数据**：域外锚点不需要健康正文、聊天正文、身份明文或恢复凭据明文。永久删除健康画像后，为防旧状态复活仍必须保留或以等价方式证明最小的终止/代际事实；若把该事实也删除，旧快照将重新失去反回滚参照。具体标识、保留期和可链接性属于后继设计与验收。

## 7. 管理员、root、故障域与保证边界

- 产品合同是管理员、操作者和服务器所有者没有建立、查看或代用主人恢复权利的**产品权限**；现有 TO 没有声称恶意 root 在技术上绝对不能替换 Plugin 或读取其进程。两者不能混写。
- 在遵循部署代码的普通故障/恢复模型中，域外强一致代际可以让恢复后的诚实 Plugin 发现本地状态陈旧并失败关闭。
- root 可以替换来宾代码、绕过检查、读取来宾 credential 或伪造主人可见 UI。单靠同一来宾中的纯软件锚点不能抵抗这种恶意管理员；外部记录即使自身未被改写，也不能强迫被替换的 Plugin 查询它。若未来要承诺抵抗恶意 root，需要另行确认更强 TO，并核验远程授权、硬件根信任/远程证明或独立执行边界；当前现场没有这些能力。
- 外部权威会引入新的可用性与账户故障域：网络分区、供应商/region 故障、账号暂停、凭据撤销、配额和费用问题都会让健康管家进入“无法确认”。多 region 或多服务并不自动提供唯一线性化当前状态，必须由具体合同证明。
- DMIT 操作者或宿主能够执行 VM snapshot/restore；QEMU Guest Agent 还允许宿主与来宾文件系统协作。当前来宾没有能力从内部证明宿主从未恢复旧快照。

## 8. 尚未证明与需主人另行批准的最小实验

| 未知项 | 为什么静态证据不足 | 另行批准后的最小实验与停止条件 |
|---|---|---|
| DMIT 当前账号是否启用 snapshot/backup、实际覆盖哪些磁盘/VM state | 来宾无法读取控制台 entitlement；官网只给产品描述 | 只读查看控制台产品状态与官方订单/合同，不创建快照、不恢复；若页面将显示支付信息、API token 或其他实例信息，先停止并缩小采集范围 |
| 某个获准域外服务是否真实可用 | SDK 存在不等于账号、资源、credential 或权限存在 | 主人先选择并批准候选服务及费用/外部数据边界；再只读验证资源配置、强一致/CAS/保留/删除合同和最小权限，不写生产状态；出现 credential 值即停止输出 |
| 跨本地/域外提交及响应丢失恢复 | 文档原语不能证明项目协议组合正确 | 候选 HOW 形成后，在隔离 canary 用合成身份、无健康正文验证并发、远端/本地各提交点强杀、超时后查询和重启恢复；任何路径指向正式 Partner profile、真实账号生产表或健康资料即停止 |
| old snapshot 是否被拒绝 | 不能在正式主机上用推论代替破坏性恢复 | 只有可丢弃 VM/profile 与获准域外测试资源就绪后，先推进合成代际，再恢复旧整机/Plugin/Hermes 快照并验证失败关闭；无法证明完全隔离或将影响正式服务时不得开始 |
| 永久删除后的最小锚点是否仍不含健康内容且不可用于画像重建 | 取决于未来字段、标识与保留策略 | 对合成记录做数据流与可链接性审计，再验证健康正文/身份明文不存在；任何真实画像、身份或 credential 将进入记录时停止 |

这些实验可以证伪具体实现，不能通过一次成功证明未来所有恢复都安全；最终仍需要可审查的不变量、故障矩阵和产品级恢复验收。

## 9. 直接回答 Ticket 68

- **真实提供：** Hermes 固定 full/quick 备份与恢复接口；目标现场标准 SQLite、`cryptography`、systemd、一般文件系统、watchdog、QEMU Guest Agent；Python 的 HTTPS 与 AWS SDK 客户端构件；DMIT 的 KVM、point-in-time snapshot/rollback 与可选异机备份产品描述。
- **真实限制：** full restore 只覆盖包内成员，quick 不含任意 Plugin 状态，二者均可制造跨域代际不一致；Plugin 加密备份和整机快照可以恢复一个内部一致但已经过期的集合；来宾没有 TPM/UEFI 单调事实；DMIT/QEMU 恢复合同不提供应用级反回滚。
- **真实缺失：** 已配置且可调用的域外强一致当前代际、线性化 CAS/不可倒退约束、最小状态摘要、凭据接线、跨域结果未知恢复、真实账号/资源/权限/费用/可用性证据，以及 old-snapshot canary。
- **因此：** 目标现场当前不能承载 Ticket 67 的上线承诺。初始化、保存健康资料、产品级验收与正式上线继续 No-Go；不得从客户端库存在、DMIT 异机备份或公开云服务原语推断该能力已经成立，也不得直接进入身份迁移与恢复 HOW。

