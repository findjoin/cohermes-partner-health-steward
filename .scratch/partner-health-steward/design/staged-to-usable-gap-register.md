# 健康管家从 staged 到主人可用的有限缺口清单

> 这是当前 Map 的实施缺口登记表，不是第二份 Spec 或新架构。权威产品目标仍是 `spec.md`，技术路线仍是 ADR 0022，真实验收顺序仍是 Ticket 119 的 G01—G12。

## 当前可确认基线

- 基线代码与 staged 部署证据：commit `777cc585bbda3e13385b73b9146c0d8f948838d1`。
- Tickets 110—117 已建立业务状态机、失败关闭、权限、删除／迁移和合成测试合同；Ticket 118 已建立 Hermes 宿主发布合同；Ticket 119 已建立分层验收合同；Ticket 120 已把内容寻址发布物 staged 安装到 default Hermes。
- 当前 default Hermes 的普通聊天可用，但健康 Plugin 尚未被真实加载，`health_weixin` 平台尚未注册；已安装的 `StagedCorePortServer` 对健康请求只返回 `health-core-staged`。
- 因此“初始化健康管家”收到的自然语言回复不能视为 `health-init` 已执行。当前没有健康初始化事实、健康 current head、健康 writer fence 或主人验收事实。

## 不再讨论的架构

以下决定已经冻结，不因实施困难而替换：

1. 一个 `health_weixin` Plugin、一个低权限 `health-core`，七个 Skill 只是该 Plugin 的职责资源。
2. Plugin 与 core 之间只保留 command、managed-read、controlled-effect 三类 CorePort 接口。
3. 加密 SQLite 是健康正文和业务事实的唯一权威；DynamoDB current-head 只存不透明代际、摘要、transition、writer fence、site 和 terminal 标记。
4. HealthCore 是唯一业务写入者；Hermes、Skill、模型、Cron 和外部适配器只能提交候选、唤醒或回交终态。
5. 未证明、未知或外部效果不确定时失败关闭；不能用普通聊天、进程存活、接口接受或测试通过冒充健康业务成功。

## 有限缺口与唯一归属

| 缺口 | 当前证据 | 唯一闭合 Ticket | 完成后能证明什么 |
| --- | --- | --- | --- |
| 本机数据密钥／删除、writer holder 与 effect completion capability 只有静态／内存实现 | `storage.StaticKeyProvider`；`core.InMemoryWriterFenceVault`；`core.InMemoryExecutionCapabilityVault`；Ticket 117 `destroyable_key_adapter` 只有 synthetic 实现 | 121 | 复制 SQLite 或重启进程不能复制写入／完成权限；密钥缺失时健康路径关闭；terminal 删除可真实销毁 exact 数据密钥 |
| `CurrentHeadPort` 只有 `InMemoryCurrentHead` | `current_head.py` | 122 | disposable 单区域 DynamoDB 上的强读、CAS、未知回查、lease、terminal 与旧 fence 行为成立 |
| 发布物只有拒绝请求的 staged server，没有生产 `HealthCore` 组合根、AF_UNIX 服务、受管 replica/migration-artifact Adapter 和 Python 3.11 dependency-closed runtime | `release_deployment.StagedCorePortServer`；Ticket 117 lifecycle 配置仍是 synthetic adapters；目标机当前只有 Python 3.10.12 且无 pip | 123 | 本机真实 socket、peer/ACL、加密 SQLite、受管删除/迁移恢复、固定运行时依赖和三类 CorePort 可运行 |
| Hermes Plugin 只有注册和 lifecycle 探针，没有把真实逐条微信消息、回复和 Cron 唤醒接入 `HealthPlugin` | `hermes_host.py` | 124 | pinned default Hermes 的唯一健康入口、七 Skill 调度、cursor 和无旁路合同真实成立 |
| `StrictModelAdapter` 只有 Interface，没有绑定当前 Partner 首跳的生产 Adapter | `model_contract.py` | 125 | 当前 capability profile 下真实模型请求、严格终态、actual-model 与无 fallback 可证明 |
| 主人／联系人投递只有 wire Interface，没有真实 Weixin Transport Adapter | `delivery.py` | 126 | 形成、尝试、接口接受、送达／已读／unknown 分层，且 unknown 不盲重发 |
| 医学知识、最低帮助、危险规则和 BMI bundle 尚无实际权利与相称审核 | Ticket 119 G07；发布声明仍为 staged/unavailable | 127 | 精确 bundle digest 最多进入 `activation-ready`；不自动变成 active |
| 没有同一 release/run 的 G10—G12 真实证据和主人验收 | Ticket 119；当前仅 staged 安装 | 128 | 仅 default Hermes 从 staged 进入主人可用，并完成初始化与功能验收 |

以上八项是本轮完整清单。实施中发现的问题只有满足以下任一条件才可新增门或新票：现有验收可复现失败、会导致数据／权限／外部效果越界、或使当前冻结架构无法工作。代码风格偏好、理论风险、替代架构更优和未复现猜测都不能扩大范围。

## 执行顺序与可并行点

```text
121 本机私有权威 ─┐
                   ├─> 123 CorePort 服务 -> 124 Hermes 入口 ─┐
122 Dynamo current-head ┘                                     ├─> 128 部署与主人验收
123 CorePort 服务 ─────────────> 125 真实模型与知识 Adapter ──┤
124 Hermes 入口 ───────────────> 126 微信／联系人 Adapter ────┤
125 精确发布 bundle ───────────> 127 权利与医学审核 ──────────┘
```

- 121 与 122 可在各自冻结设计完成后并行。
- 125 与 126 在 123／124 的接口稳定后可并行。
- 127 是 `ready-for-human`：Agent 可以整理证据、校验 hash 和执行机械门，但不能伪造许可或医学专业审核。
- 128 之前不再让主人输入真实健康资料。128 只部署到 default Hermes，不触碰 partner Hermes。

## 每票统一停止规则

1. 编码前只做当前代码 characterization，形成一份冻结实施设计和一份独立 verifier-owned 验证合同；预期红灯必须来自本票缺口。
2. 设计评审只允许修正会阻止本票验收的 P1；不以“还能更安全”为由更换 ADR 0022 或增加新业务能力。
3. 编码 Agent 只实现冻结设计，评审只检查是否正确落地；发现架构外问题时停止并返回证据，不在本票内重构路线。
4. 每票通过自己的冻结门和受影响回归即可交审；项目全量测试只在最终交审运行一次，避免每个小修改重复数百项测试。
5. 真实 AWS、模型、微信、联系人、部署、删除、迁移和主人动作分别需要 Ticket 119 已定义的精确批准；缺批准为 `not-authorized`，不是代码失败。

## “可以使用”的唯一判定

只有 Ticket 128 对同一 release digest 完成以下事实，才通知主人重新发送“初始化健康管家”：Plugin 已加载、health-core 真实健康、current-head 与 writer fence 当前、最低安全资产可用、真实模型／渠道门通过、`health-init` 形成并提交初始化事实，且读回状态为 enabled。此前任何自然语言“已初始化”都不是产品事实。
