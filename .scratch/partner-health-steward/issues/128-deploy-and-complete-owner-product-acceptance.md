# 128 - 部署并完成主人产品验收

Type: task
Status: ready-for-agent
Parent: [健康管家首发 TO、CAN 与 HOW 决策闭合路线](../map.md)
Blocked by: [122 - 实现 DynamoDB current-head 生产 Provider](122-implement-dynamodb-current-head-provider.md), [124 - 接通 pinned Hermes 的真实健康入口](124-connect-pinned-hermes-live-health-entry.md), [125 - 实现 Partner 首跳模型与治理知识 Adapter](125-implement-partner-model-and-governed-knowledge-adapter.md), [126 - 实现真实 Weixin 与支持联系人投递 Adapter](126-implement-live-weixin-and-support-contact-delivery-adapter.md)

**What to do:** 对一个新内容寻址 release 在用户的 default Hermes 上分两阶段完成真实部署与验收。阶段 A 在诊断范围保持 staged 时完成 target binding、最小 canary、主人初始化和非诊断能力验收，使主人可以先使用健康记录、画像、非诊断问答、提醒、任务、安全提示、控制和数据权利；阶段 B 仅在 Ticket 127 闭合后完成 BMI 诊断激活、完整 G12 和完整首发验收。明确禁止访问或部署女友的 partner Hermes。

## Required orchestration delta

当前 Ticket 119 `AcceptanceRunContract` 只有完整首发的固定 G01→G12 路径，并在 G07 医学审核未通过时阻断 G10—G12；因此不能靠文档跳过 G07 实现阶段 A。本票在任何真实部署前，先为同一个 Module、同一份不可变报告和同一 GateExecutor Seam 增加两个固定 `run_scope`：

- `non-diagnostic`：固定执行 G01—G06 → `128-ND07` → G08—G11 → `128-ND12`。`128-ND07` 必须证明 BMI 保持 staged、普通入口不能调用诊断、非诊断运行只加载项目自有或已明确授权的固定最低安全／治理文案；`128-ND12` 只形成初始化和非诊断主人验收证据，不写 active、G12 passed 或 product acceptance passed。
- `full`：保持 Ticket 119 已有 G01→G12 顺序、gate ID、批准、报告和完成语义不变。

`run_scope` 绑定 release/run/target 且不可在同一 run 改写；两个分支共用现有 ledger、重放、unknown、批准和无正文规则。不得建立第二验收账本、第二产品状态、任意 gate 列表或可配置 DAG。该增量必须先完成 characterization、冻结设计、独立 verifier-owned 门和双轴预审；旧 Ticket 119 七门及完整分支回归必须保持绿色，随后才允许执行阶段 A。

## Fixed target and safety boundary

- 唯一目标：用户自己的 default `/root/.hermes` 与 `hermes-gateway.service`。partner `/root/.hermes-partner`、`hermes-gateway-partner.service` 及其他 profile/service 永久为 pre-write rejection。
- 每个真实 AWS、模型、微信、联系人、部署、删除、迁移和主人动作分别使用 Ticket 119 的 target/release/run/gate-bound opaque approval；批准不能跨 gate 借用。
- collector 不读取或返回凭据、完整配置、健康正文、联系人身份、运行数据库、模型 transcript 或可逆摘要；只保存无正文 opaque refs。

## Bounded acceptance

### 阶段 A：非诊断主人可用

1. 用冻结后的 `non-diagnostic` 分支对同一 release digest 依次运行 G01—G06、`128-ND07`、G08—G11、`128-ND12`；任何非 passed 立即停止。不得由 caller 跳过 gate 或直接调用 G10—G11。
2. G10 验证 default 的 pinned artifact/dirty digest、required patch、Plugin discovery、唯一入口、CorePort service、peer/ACL、current-head、密钥/vault、capability profile、co-stop 和可回滚安装。
3. G11 仅用不含诊断内容的最小合成／脱敏输入验证真实 Partner 首跳模型和用户自己的 Weixin；interface accepted 不冒充 delivered/read，unknown 冻结同 run。
4. 取得精确阶段 A 授权后，由主人在微信中完成真实 `health-init`；Core 读回 initialization enabled、current head 和 writer fence 当前后，才显示“健康管家已初始化”。初始化结果必须同时显示 BMI 诊断未启用，不能写 G12 passed、诊断 active 或完整首发。
5. 按冻结主人测试序列验收非诊断能力：普通健康记录、画像／证据、一般健康问答、明确拒绝范围外诊断、当地日复盘、任务、主人控制／权利、失败／unknown 状态、最低安全、危险升级和已获准的最小联系人警报／纠正。使用的最低安全与非诊断文案必须是项目自有或具有明确使用权的固定版本，不得复制尚未获权的诊断内容。
6. 主人确认上述范围“有用、清楚、可信”后，只能记录 `non-diagnostic-owner-usable` 里程碑；它是无正文验收结论，不是新的产品状态、G12 passed 或完整首发声明。

### 阶段 B：诊断激活与完整首发

7. Ticket 127 对同一 release/bundle digest 闭合后，建立新的 `full` run，按 Ticket 119 原顺序重跑 G01—G12 并取得规定的一次性 acceptance authorization；完成真实 BMI 范围验收、五项 G12 receipts 和 active-path readback 后，才允许 G12 passed。
8. 主人对包含已激活 BMI 范围的完整序列明确确认“有用、清楚、可信”后，才可记录完整产品验收并解决本票；拒绝、超时、无法确认或 Ticket 127 失效时保持 staged，不自行激活。
9. 任一阶段的 post-check 失败均按 release-bound backup 回滚 default，重新启动并确认普通 Hermes 可用；不得触碰 partner。

## Completion claim

阶段 A 证据齐全时只能记录“非诊断健康管家已初始化并可供主人使用”，并列出诊断仍 staged；此时本票保持 `claimed`。只有 Ticket 127 当前有效、G01—G12 对同一 release/run 全部 passed、五项 G12 receipts 和 active-path readback 齐全，才可在 Ticket 119/128 记录“完整首发／产品验收通过”并解决本票。这不等于已经证明长期稳定；上线后稳定性另以真实无正文运行证据观察，不在本票预设新的架构或功能。

## Delivery discipline

部署前分别冻结阶段 A 与阶段 B 的精确 release、target、run、回滚点和测试序列；阶段授权不得互相借用。每个阶段完成后提交无正文证据、更新 Ticket/Map、普通 push；不得把批准、秘密或主人资料写入 Git。
