# 域外身份代际权威候选能力核验（Ticket 71）

## 1. 直接结论

截至 2026-08-18，公开一手合同能证明两类外部原语具有进入后继 HOW 比较的**事实基础**，但都不是当前项目已经可用或已经满足 Ticket 67 的能力：

1. **受管强一致键值或事务服务**：只要未来选定的具体配置确实使用强一致当前读，并把“预期旧代际、唯一转换标识、状态摘要和终止状态”放进同一次条件更新或可串行化事务，就能让并发或旧快照中的诚实 Plugin 以旧前提推进时条件失败。DynamoDB 的强一致表读取、条件写和可串行化事务，以及 Spanner 的强读、外部一致事务，分别证明现实中存在这组原语。
2. **强一致对象存储中的唯一可变当前头**：单一 live object 若具有强一致读取，并强制每次替换都携带当前 ETag 或 generation 前提，可以表达线性化的“只替换我刚读到的当前头”。但是 payload 的业务代际、状态摘要和转换标识仍须由项目协议核验；WORM/保留只能保护指定历史版本，不能单独定义唯一当前头。

以下能力类别**单独不充分**：

- 强一致读但没有条件写；条件写但允许绕过条件、任意写较小业务代际或把资源缺失当作首次初始化；
- 对象版本、WORM、保留策略、异机备份或不可覆盖历史版本，但没有唯一 live head 的强一致条件推进；
- 追加式或透明日志：它能证明某条记录进入过日志和历史未被静默改写，却不拒绝同一画像的冲突、过期或较小代际继续追加；
- TPM NV counter 或其他裸单调计数器：计数器本身不绑定身份授权状态摘要、唯一转换和不可恢复终态；当前 KVM 来宾又没有 TPM/vTPM，QEMU 的模拟 TPM 状态可随 VM save/restore 与 snapshot 迁移；
- 当前目标现场的 SQLite、AEAD、文件、Hermes/Plugin 备份、整机快照及已安装客户端构件。它们的负向边界已由 [Evidence 17](17-owner-identity-authority-anchor-capabilities-20260818.md) 固定。

所以本票不是“已找到并接通锚点”的正向验收。准确结论是：**候选原语层 CAN 已闭合，目标现场可用性仍未闭合**。当前没有外部账号、资源、区域、权限、credential 接线、费用/配额接受、项目提交协议或 old-snapshot canary；初始化、创建正式健康画像、保存健康资料、产品级验收和上线继续 No-Go。

本报告不选择供应商、账号、区域、资源、凭据、跨域提交协议或 HOW。外部文档读取日期为 2026-08-18。

## 2. 四层事实不得混写

| 候选 | 公开原语合同 | 目标服务器接入前提 | 真实账号、资源、权限与合同 | 项目协议与 old-snapshot canary | 是否有条件进入 HOW 比较 |
|---|---|---|---|---|---|
| DynamoDB 类强一致 KV/事务 | 已证明表的强一致读、条件写、可串行化事务与短时请求幂等 token | Evidence 17 只证明目标 venv 有 `boto3`/`botocore`；没有探测网络、credential chain 或 metadata | 未证明存在 AWS 账号、表、Region、IAM、计费、配额、删除保护或数据处理合同 | 未设计；未验证跨 SQLite 提交、旧 VM、超时回查或资源重建 | **是**，仅限下文前提成立后 |
| Spanner 类外部一致事务数据库 | 已证明默认强读、外部一致/可串行化读写事务和明确的 outcome unknown 客户端状态 | Evidence 17 未发现 `gcloud` 或常见 Google 配置，Google client/认证路线也未证明；通用 HTTPS client 不等于可认证调用 | 未证明项目、实例、数据库、location、IAM、计费或 SLA 选择 | 未设计；未验证事务重试副作用、转换去重或旧快照 | **是**，仅限下文前提成立后 |
| S3/GCS 类条件对象存储 | 已证明单 key/object 的强一致读取与基于 ETag/generation 的条件替换；可选 WORM/保留 | S3 只有 SDK 构件，GCS 只有通用 HTTPS 构件；两者网络与认证均未探测 | 未证明 bucket、location、versioning、retention、IAM、费用或账号生命周期 | 未定义唯一 live head、delete marker/版本规则、业务代际校验或 canary | **是，但只比较“条件当前头”组合**；WORM 单独不进入 |
| Rekor/CT 类透明日志 | 已证明追加、包含证明、树头/一致性审计；公开 Rekor 只有 99.5% availability SLO | 未从目标主机访问；向公共日志提交会产生公开、长期外部状态，本票禁止执行 | 没有项目专用日志、schema、隐私、地域、删除或治理合同 | 没有每画像 CAS、冲突拒绝和唯一当前头规则 | **否，不能单独承载权威**；最多以后作辅助审计 |
| TPM NV counter / 硬件计数器 | TCG 定义 8-byte counter，只能通过 `TPM2_NV_Increment` 修改；物理 passthrough 与模拟 TPM 的快照语义不同 | Evidence 17 已证明目标来宾无 `/dev/tpm*`、EFI monotonic state 与 `tpm2_getcap` | 未证明 DMIT 提供物理 TPM passthrough、不可回滚 vTPM、独立 HSM 或相应生命周期合同 | 未定义 counter 与摘要/终态的原子绑定；未做 TPM/VM 恢复 canary | **当前否**；先要新的平台专属 CAN，不能直接进 HOW |

“有条件进入 HOW”只表示公开合同没有排除这类路线，不表示项目已采用、能连通、能付费或通过验证。

## 3. 受管强一致 KV/事务服务

### 3.1 DynamoDB 代表合同

- DynamoDB 的 `GetItem`、`Query`、`Scan` 在表或 local secondary index 上设置 `ConsistentRead=true` 后，返回所有先前成功写入所反映的最新数据；默认读取、global secondary index 和 stream 不能冒充该语义。[AWS：读取一致性](https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/HowItWorks.ReadConsistency.html)
- `PutItem`、`UpdateItem`、`DeleteItem` 可以携带 condition expression；只有表达式为真才修改 item。官方示例明确展示两个并发者以同一旧值更新时，先成功者改变值，后到者条件失败。[AWS：条件表达式](https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/WorkingWithItems.html)
- `TransactWriteItems` 是全成或全败；事务与事务、标准单项写、单项 `GetItem` 之间具有 serializable isolation。事务只在调用 Region 内提供 ACID，不能把普通跨 Region global-table 复制静默当成同一事务。[AWS：事务隔离与跨 Region 边界](https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/transaction-apis.html)
- `ClientRequestToken` 让相同 `TransactWriteItems` 请求在 10 分钟窗口内幂等；窗口后同一 token 会被当作新请求。它不能代替业务记录中长期保存的唯一转换标识。[AWS：TransactWriteItems API](https://docs.aws.amazon.com/amazondynamodb/latest/APIReference/API_TransactWriteItems.html)
- AWS 还明确用“请求发出后网络错误、结果未知”说明条件写为何可安全重试：只有当前属性仍等于预期旧值时才会再次执行。这证明网络未知不是普通失败；项目仍须强一致回读转换 ID/摘要，区分首次提交成功与条件失败。[AWS：conditional write idempotence](https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/WorkingWithItems.html#WorkingWithItems.ConditionalUpdate)
- DynamoDB 的错误处理文档进一步说明写入收到 HTTP 500 时可能已经成功也可能没有成功；单项写要先读回状态再决定是否重试，事务写则依赖同一幂等请求语义。timeout/500 不能直接映射成“失败”。[AWS：error handling](https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/Programming.Errors.html)

这组原语可以表达 `expected generation=N and expected state digest=D -> generation=N+1, transition=T, new digest=D2`。但是 `ConditionExpression` 和新 payload 由调用者提供，服务并没有独立理解“恢复权利已经消费”或“永久锁定”。AWS 对 DynamoDB IAM condition keys 的完整表只列出 partition key、attributes、return values、是否属于 transaction 等约束，没有一个 key 能强制请求必须携带指定 `ConditionExpression` 或证明 `new generation > old generation`；这是基于官方枚举表的推论，不是 IAM 已提供业务单调验证。[AWS：DynamoDB service authorization](https://docs.aws.amazon.com/service-authorization/latest/reference/list_dynamodb.html) 如果旧 VM 携带的 credential 仍有效，并且它能绕过条件、先刷新当前值后提交任意业务状态，或者存在另一个无条件写入口，DynamoDB 本身不会替项目判断该转换是否合法。因此进入 HOW 前仍须证明：所有应用写路径都不能绕过既定条件与状态机；外部账号管理员的权限属于独立、更高信任边界。

跨 Region 也不能笼统表述：MREC global tables 异步复制并以 last-writer-wins 解决同 item 冲突，不能作为全球唯一单调头；MRSC 才允许任一 replica 强读最新值，但支持的 Region 组合和功能不同，且 DynamoDB transaction 不跨 Region。未来 HOW 必须固定一致性模式，不得把“global table”名字当保证。[AWS：global tables consistency modes](https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/V2globaltables_HowItWorks.html)

Point-in-time recovery 也不是 current-head：它把过去 1 至 35 天内的状态恢复为**新表**，不是原位恢复当前表。未来若允许自动改指向恢复表，会重新引入旧状态；resource identity 与 endpoint/table 绑定必须失败关闭验证。[AWS：PITR restore](https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/pointintimerecovery_restores.html)

表 deletion protection 只防误删：表所有者或授权管理员可以改变该设置；AWS 账号被删除时，账号内表仍会在 90 天内删除。[AWS：表删除与 deletion protection](https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/WorkingWithTables.Basics.html) 费用按读取、写入、存储及可选功能计取；事务对每个 item 使用 prepare 与 commit 两次底层操作。默认 throughput 与表数量配额按 Region 计算，实际账号配额和可接受费用均未核验。[AWS：DynamoDB pricing](https://aws.amazon.com/dynamodb/pricing/) [AWS：DynamoDB quotas](https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/ServiceQuotas.html)

**进入 HOW 的未证明前提：** 具体一致性模式与 Region 固定；当前头只从支持强一致读的表路径读取；每次转换使用服务端条件推进并持久绑定 transition ID/摘要/终态；无条件写和非强一致旁路被权限与代码边界排除；resource identity、账号删除、费用/配额、credential 轮换与故障关闭得到接受；真实目标网络和授权另行核验。

### 3.2 Spanner 代表合同

- Spanner 默认强读会观察操作开始前全部已提交事务；默认 serializable isolation 提供 external consistency，读写事务的读和写在同一提交时间点原子生效。[Google Cloud：TrueTime 与 external consistency](https://docs.cloud.google.com/spanner/docs/true-time-external-consistency) [Google Cloud：事务](https://docs.cloud.google.com/spanner/docs/transactions)
- 因此项目可以在事务内读当前 row，验证 `generation`、状态摘要和 transition ID，再进行单一受保护更新；并发事务不能都把同一预期当前状态成功消费。但这仍是未来项目协议，不是 Spanner 已内置的健康身份状态机。
- client driver 可能重新运行 transaction body，事务体内的域外副作用可能执行多次；这些副作用不能直接放在可重试事务体内。[Google Cloud：事务重试边界](https://docs.cloud.google.com/spanner/docs/transactions#read-write_transactions)
- Go 官方 client 明确定义 `TransactionOutcomeUnknownError`：Commit 已发送但 client 在收到响应前 timeout/cancel 时，事务结果未知。未来协议必须凭持久 transition ID 强读回查，不能把超时猜成未提交。[Google Cloud：Spanner Go client](https://docs.cloud.google.com/go/docs/reference/cloud.google.com/go/spanner/latest#cloud.google.com_go_spanner_TransactionOutcomeUnknownError)

Spanner 的 regional、dual-region、multi-region 配置具有不同的复制地域、availability、延迟与费用；多 Region 不等于无故障，无法取得强读/提交结果时仍必须显示“无法确认”并失败关闭。[Google Cloud：instance configurations](https://docs.cloud.google.com/spanner/docs/instance-configurations) deletion protection 可由具有更新权限者关闭，且删除整个 project 不受该 database deletion protection 阻止。[Google Cloud：deletion protection](https://docs.cloud.google.com/spanner/docs/prevent-database-deletion) 费用包含 compute capacity、数据库/备份存储、复制和网络；具体 edition、capacity、quota 和 location 尚未选择或报价。[Google Cloud：Spanner pricing](https://cloud.google.com/spanner/pricing)

**进入 HOW 的未证明前提：** 具体 instance configuration、location、edition、容量和费用被接受；目标主机有获准 client 与不暴露 secret 的 credential 注入；事务 schema 能在同一提交内核验并推进 generation、摘要、transition ID 与终态；重试体没有外部副作用；outcome unknown 能强读回查；IAM 不给应用绕过状态机的通用写入口；project/instance/database 删除和重建均导致失败关闭而不是重新 bootstrap。

## 4. 条件对象存储与 WORM 的准确边界

### 4.1 条件 live head 有事实基础

- S3 对 PUT、DELETE、GET/LIST 提供强 read-after-write consistency，单 key 更新是原子的；`If-Match` 用当前 ETag 作为写前提，不匹配时失败。bucket policy 还能要求上传请求必须带 `If-Match` 或 `If-None-Match`。[AWS：S3 consistency](https://docs.aws.amazon.com/AmazonS3/latest/userguide/Welcome.html#ConsistencyModel) [AWS：conditional writes](https://docs.aws.amazon.com/AmazonS3/latest/userguide/conditional-writes.html) [AWS：enforce conditional writes](https://docs.aws.amazon.com/AmazonS3/latest/userguide/conditional-writes-enforce.html) 但该 policy 不是账号管理员不可变边界：AWS 明确允许 bucket owner/root 调用 `DeleteBucketPolicy`，即使当前 bucket policy 显式 deny root。[AWS：DeleteBucketPolicy](https://docs.aws.amazon.com/AmazonS3/latest/API/API_DeleteBucketPolicy.html)
- GCS 同样对 object read-after-write、read-after-delete 和 listing 提供 strong global consistency；`ifGenerationMatch` 只在 live object generation 等于预期值时执行，`0` 表示只有不存在 live object 才创建。带 generation 前提的 mutation 被官方列为 conditionally idempotent。[Google Cloud：consistency](https://docs.cloud.google.com/storage/docs/consistency) [Google Cloud：preconditions](https://docs.cloud.google.com/storage/docs/request-preconditions) [Google Cloud：retry/idempotency](https://docs.cloud.google.com/storage/docs/retry-strategy)

所以“一个固定 object key 代表当前头，成功替换必须匹配刚读到的 ETag/generation”具有线性化 CAS 的公开原语基础。它能让两个都基于同一旧头的诚实 client 至多一个成功，也能让响应丢失后的重复请求不覆盖后继版本。

但 object service 的 generation/ETag 是**对象版本标识**，不是项目业务 generation。它不会检查 payload 中 `N+1 > N`，也不会理解恢复权利、终止状态或 transition ID。项目协议仍须校验完整 payload，并确保 delete marker、无条件 PUT、copy、multipart completion、版本恢复或另一 API 不能改变“唯一当前头”的含义。

### 4.2 WORM/保留不能单独定义当前头

S3 Object Lock compliance mode 能在保留期内阻止包括 account root 在内的主体覆盖或删除**指定 object version**，但不阻止同 key 创建新 version，也不阻止 simple DELETE 创建成为 current version 的 delete marker；delete marker 自身不受 WORM，删除 current delete marker 还会让旧 version 再次成为可见当前。删除 AWS account 仍是保留期前删除 compliance object 的例外。[AWS：Object Lock](https://docs.aws.amazon.com/AmazonS3/latest/userguide/object-lock.html) [AWS：Object Lock considerations](https://docs.aws.amazon.com/AmazonS3/latest/userguide/object-lock-managing.html) [AWS：delete markers](https://docs.aws.amazon.com/AmazonS3/latest/userguide/ManagingDelMarkers.html) 因而“历史版本不可删”不等于“当前授权头唯一且只能单调前进”。

GCS Bucket Lock 能让 retention policy 不可降低或移除，并在对象满足保留期前阻止替换/删除；它还会给 project deletion 加 lien，但有相应高权限的 project 主体可以移除 lien，账号还必须持续 active and in good standing。[Google Cloud：Bucket Lock](https://docs.cloud.google.com/storage/docs/bucket-lock) 这同样是保留合同，不是身份状态机；把同一 live head 锁住还会在保留期内阻止正常推进。

WORM 还与永久删除边界发生直接取舍：健康正文、身份明文、恢复凭据或可重建画像的内容绝不能写入长期锁定对象；健康画像永久删除后仍需保留的只能是不能重建健康内容、用于拒绝旧状态复活的最小终止/代际事实。保留期、账号关闭、对象/项目删除和费用必须在 HOW 中显式选择，不能由“WORM”三个字代替。

对象存储费用由请求、存储、数据取回/传输和可选保留/复制构成；长期版本与不可缩短的 retention 会积累成本。实际 location、quota、费用和合同均未核验。[AWS：S3 pricing](https://aws.amazon.com/s3/pricing/) [Google Cloud：Cloud Storage pricing](https://cloud.google.com/storage/pricing)

**进入 HOW 的未证明前提：** 只比较“强一致唯一 live head + 强制条件替换 + payload 业务单调校验”组合；明确 version/delete marker/复制/恢复规则；没有无条件写旁路；响应未知时按同一 object generation 和 transition ID 回查；WORM 历史若采用则与可变 current head 分离；数据 location、保留、账号生命周期、费用和永久删除后的最小 tombstone 已接受。

## 5. 追加式或透明日志为何单独不充分

Rekor 官方把日志定义为 append-only、不可变且可密码学验证；verifier 能验证 inclusion proof，auditor/monitor 能检查日志是否保持追加。公共实例公开 99.5% availability SLO。[Sigstore：Rekor overview](https://docs.sigstore.dev/logging/overview/) 但官方 monitor 同时强调，透明日志是 tamper-evident 而不是 tamper-proof，持续 monitoring 是其安全模型的一部分。[Sigstore：Rekor monitor](https://github.com/sigstore/rekor-monitor)

这些能力只能回答“记录 X 是否被追加、某树头是否包含它、两个树头是否保持追加关系”。它们没有项目级 compare-and-swap，也不会在 `generation=N+1` 已存在后拒绝另一台旧 VM 再追加一个声称 `generation=N` 或冲突 `N+1` 的记录。按最高 log index 取“当前”只会让较晚到达的过期请求取得更大 index；按 payload generation 取最大值又无法排除同代冲突。可靠解决这些冲突需要另一个验证/共识状态机，而该状态机才是真正的当前权威。

公共 Rekor 还是软件供应链公开透明服务，提交会产生长期公开外部状态，availability SLO 也低于健康处理可自行忽略的依赖；本票没有核验任意健康身份 schema、数据地域、删除、费用或私有 deployment。它不能单独进入身份权威 HOW；以后若选中某个强一致当前头，可把透明日志作为辅助审计候选，但必须另行核验隐私、monitor/witness 和可用性，且不得写入身份明文、恢复凭据或健康正文。

## 6. 硬件单调计数器与当前托管边界

TCG TPM 2.0 结构规范定义 `TPM_NT_COUNTER` 为 8-octet counter，并规定只能通过 `TPM2_NV_Increment()` 修改；这证明物理 TPM 可以提供“数值只按增量命令变化”的原语。[TCG：TPM 2.0 Library Part 2, Version 1.84](https://trustedcomputinggroup.org/wp-content/uploads/Trusted-Platform-Module-2.0-Library-Part-2-Version-184_pub.pdf)

但裸 counter 不携带身份授权状态摘要、transition ID 或永久锁定语义。旧 VM 如果仍被允许访问当前 counter，可以先读取/增加它，再把过期业务状态配给新数值；计数器本身无法判断业务转换是否合法。counter 的 NV index 定义、授权、清除/更换、耐久与设备生命周期也取决于平台和具体 policy，不得由公开 TPM 命令推断为当前托管保证。

QEMU 的边界更明确：硬件 TPM passthrough 的状态不能跨主机迁移，所以启用 passthrough 时 VM migration 被禁用；TPM emulator 则明确支持 VM save/restore、network migration 和 snapshotting。[QEMU：TPM device](https://www.qemu.org/docs/master/specs/tpm) 因此普通 vTPM 不能自动作为“不会随来宾快照回滚”的事实。

Evidence 17 已证明当前 DMIT/KVM 来宾不存在 `/dev/tpm*`、EFI variables 或 `tpm2_getcap`，也没有平台合同证明一个域外物理计数器。**当前托管边界没有真实可得的硬件候选。** 只有 DMIT 或另一获准平台先提供可定位的物理 passthrough、不可回滚 vTPM/HSM 及其授权、迁移、snapshot、reset、替换和故障合同，才值得建立新的平台专属 CAN；在此之前不能把 TPM 直接列入 HOW 选择。

## 7. 旧 VM、管理员和账号删除的威胁边界

| 情形 | 上述候选能做什么 | 仍不能单独证明什么 |
|---|---|---|
| 诚实 Plugin 从旧快照启动，并携带旧的 expected generation/digest | 强一致 CAS 可使其旧条件失败，转入“无法确认” | 若它先刷新 current 后仍按陈旧本地恢复权利发起新转换，服务不知道业务请求是否合法；协议必须绑定摘要、transition ID 和终态 |
| 旧 VM 仍持有有效应用 credential | 服务把它视为并发 client；旧 CAS 仍可失败 | credential 本身不是 freshness proof；不能阻止有通用写权限的 client 绕过条件或提交任意 payload |
| 应用管理员误操作 | deletion protection、bucket policy、WORM 可降低部分误删/无条件写风险 | 能修改 policy、代码、credential 或 resource 的更高权限主体仍可能扩大权限、停服或删除 |
| 恶意 guest root | 外部 current state 在来宾之外，不会被 VM snapshot 一起恢复 | root 可替换 Plugin、读取可用 credential、跳过检查或伪造 UI；现有 TO 未承诺抵抗恶意 root |
| 外部账号/项目管理员 | 某些 compliance retention 在保留期内限制版本删除 | 管理员可改 IAM、停计费、删表/数据库/project/account，或制造不可用；服务不可用只能触发失败关闭，不构成当前状态证明 |
| resource 被删除后以同名重建 | 若协议固定并验证 resource identity，可拒绝新资源 | 只看 endpoint/table/bucket 名称会把空资源误认成首次初始化，导致旧状态复活 |

因此本票延续 Evidence 17 的威胁边界：候选只为遵循已审查协议的诚实 Plugin 检测旧状态和并发提供原语，不抵抗恶意 root 或外部账号管理员改写整个信任边界。如果主人希望增加这类对抗承诺，必须先建立新的 TO，而不是在 HOW 中偷偷扩大保证。

账号、resource、network、DNS、TLS、credential、强读、条件写、quota 或费用任何一项无法确认时，都只能把健康管家置为“无法确认”并停止健康处理、迁移和恢复；不得把远端不存在当成 `generation=0` 自动重建。明确无关健康的普通聊天仍按 Ticket 67 继续。

## 8. 外部最小数据与永久删除边界

候选服务不需要健康正文、聊天正文、身份明文、恢复凭据明文、模型输入输出或画像内容。为了让旧快照在永久删除后仍不能重新启用，域外权威至少要能表达并长期确认：当前业务代际、不能重建身份/健康内容的授权状态摘要、唯一转换标识/摘要，以及不可恢复终止事实。具体字段、标识可链接性、hash/key 方案和 retention 属于 HOW，不由本票预选。

删除候选资源或账号不等于完成健康画像永久删除：如果权威消失，诚实 Plugin 必须失败关闭；如果随后把空资源当作首次启动，旧快照反而可能复活。反过来，若使用 WORM 保存含个人内容的对象，又可能违反永久删除。后继 HOW 必须把“健康内容全部删除”和“最小防复活事实继续成立”作为两个同时满足的不变量。

## 9. 需主人另批的最小 Prototype / 现场核验

| 候选 | 最小目的与外部影响 | 仅允许的数据形态 | 必测事实 | 停止条件 |
|---|---|---|---|---|
| 受管 KV/事务 | 主人先选候选、Region、费用上限和测试账号边界；创建一个隔离、可删除、可能计费的测试 table/database | 随机 anchor ID、整数 generation、随机 transition ID、随机摘要、terminal flag；无身份/健康/聊天正文 | 强读；两个并发相同前提仅一个成功；较小代际和同代不同摘要拒绝；相同/不同 transition 重试；commit 后丢响应再回查；throttle/credential/network/service 故障失败关闭；删除/重建 resource 不得 bootstrap | 需要输出 credential；指向正式账号生产资源/Partner profile；费用、地域或删除边界未先批准；SDK 自动重试无法观测 |
| 条件对象 current head | 在隔离 bucket 验证一个固定 key 的 ETag/generation CAS；versioning/WORM 若测试会产生保留与费用影响 | 同上，object 仅为几十至几百 bytes 的合成状态 | 并发 `If-Match`/generation-match；响应丢失；delete marker、无条件 PUT、copy、multipart、版本恢复；bucket policy 是否真能封死旁路；retention 到期前后与账号删除边界 | 需要不可逆锁定 retention 而主人未确认时长/费用；会写真实身份或健康内容；无法保证 bucket 完全隔离 |
| 透明日志（仅作辅助） | 只有后继 HOW 明确需要审计补充时，才在私有或获准测试日志追加合成冲突记录；公共 Rekor 写入必须单独明确批准 | 不可关联真实主人的随机摘要 | 同一旧前提的两条冲突记录是否都能追加；inclusion/consistency proof 与 monitor；服务不可用 | 任何记录将公开或不可删且主人未接受；日志被拿来替代 current-head CAS |
| TPM/硬件计数器 | 先只读取得托管平台正式设备与 snapshot/migration/reset 合同；合同足够后才在可丢弃 VM/device 做计数器实验 | 合成计数与随机摘要 | 物理/模拟类型；snapshot/restore 是否回滚 NV；counter 与摘要/终态绑定；设备 reset/替换/失联时失败关闭 | 目标平台仍无设备合同；实验影响正式 VM/宿主 TPM；需要恢复正式快照或读取非本任务 NV/credential |
| 跨 SQLite 与域外权威 old-snapshot canary | 候选 HOW 和隔离资源就绪后，在可丢弃 profile/VM 推进合成代际，再分别强杀本地前/后提交、丢远端响应并恢复旧 Hermes/Plugin/整机状态 | 仅上述合成状态 | 明确成功、条件失败、结果未知三态；任何旧状态都不能成为当前；永久 terminal 后旧快照仍失败关闭 | 无法证明 VM/profile/resource 完全隔离；会触及真实 Partner 服务、主人微信、模型、正式 credential 或健康资料 |

Prototype 通过只能证明被测配置和协议没有在覆盖场景中被证伪，不能把一次成功扩大为所有 Region、账号管理员或未来版本的永久保证。最终仍需固定配置、可审查不变量、故障矩阵、真实部署只读配置证据和获准的 old-snapshot 验收。

## 10. 直接回答 Ticket 71

- **单独不充分：** 本地或异机备份、WORM/保留、对象版本历史、追加/透明日志、裸 TPM counter、强读无 CAS、CAS 无业务单调校验、短时 SDK idempotency token，以及任何允许把 resource 缺失当作首次初始化的方案。
- **有条件进入 HOW 的候选：** 受管强一致 KV/事务服务；强一致对象存储的唯一 live head + 强制 ETag/generation 条件替换。两类都必须在尚未证明的真实账号、Region/location、IAM、credential、费用/配额、资源生命周期、最小数据、永久终止保留、outcome-unknown 回查和项目状态机前提下比较。
- **当前不能进入 HOW 的候选：** 透明日志只能作辅助审计；当前托管边界没有真实可得的域外硬件计数器，普通 vTPM 还会随 QEMU snapshot/migration 保存状态。
- **威胁边界：** 这些原语能够帮助诚实 Plugin 拒绝旧快照和并发旧条件，不能单独抵抗恶意 guest root、仍持有通用写 credential 的任意代码或外部账号管理员。扩大该威胁模型需要新的 TO。
- **下一步：** 候选类别 CAN 足以让同一 Map 建立身份迁移/恢复的 HOW Ticket，比较“受管事务/CAS”与“条件对象 current head”并设计唯一协议；选定候选和费用/地域边界后，仍须主人另批候选专属账号内只读核验、合成数据 Prototype 与可丢弃环境 old-snapshot canary。上述验证完成前 Ticket 67 的初始化、健康资料写入、产品级验收与上线 No-Go 不变。
