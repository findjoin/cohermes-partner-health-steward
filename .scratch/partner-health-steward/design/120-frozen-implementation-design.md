# Ticket 120 冻结实施设计

> 状态：frozen。候选基线为 commit `4b90a4fe22d2d4acf674d76c732a9de765f03079`，tree `c855edb43240882ac69008dcd08eac6db1a208b8`。本设计是 Ticket 119 的真实部署前置；它不改变 Tickets 110—119 的任何冻结产物、业务语义或 Map。

## 目标与当前差额

已有 `partner_health_steward` 业务源码和 Ticket 118 synthetic release verifier，但没有可由 Hermes 用户 Plugin loader 发现的真实目录，也没有实际 default-only 的备份、staging、安装、服务重启、检查与回滚入口。`hermes_host` 已经是 pinned Hermes `register(ctx)` client，却没有运行中的 CorePort server。当前仓库对 `CurrentHeadPort`、writer-fence vault 和 execution-capability vault 只有标为 synthetic 的内存实现；它们不能作为默认部署的健康权威。

120 只闭合“可部署但未启用”的缺口。输出必须让 default Hermes 发现一个完整发布物，所有健康入口继续 staged；不能把文件存在、service active、Plugin manifest 被发现或任何自报字段写成 activation、健康可用、产品验收或稳定运行。对 default 的一次实际安装属于 Ticket 119 的 `119-G10` target-local 外部动作：它只能使用本设计定义、由当前主任务明确授权的单次运维能力文件，不能把调用者字符串或 120 的本地测试冒充批准。

## 固定发布目录

新增深 Module `HermesReleasePublisher`，由薄入口 `tools/ticket120_release.py build --output <directory>` 调用。它只从当前仓库中列出的真实源码与静态无医学发布资产生成 release，不读取历史 `ops/`、实例、环境变量、目标配置或秘密。

发布目录是版本化、内容寻址的：先在调用者指定根下建立临时目录，严格写入并逐文件 SHA-256 验证，再以不可变 digest 名目录原子定名。`release-manifest.json` 的 `release_digest` 精确等于 canonical JSON `{contract, state, files, host_release_manifest}` 的 SHA-256，其中 `files` 是除 manifest 自身外按相对 path 排序的完整 regular-file `{path,sha256}` 列表，`host_release_manifest` 是对当前输出目录以 `HostReleaseContract.build()` 重新计算的完整 wire，而非仅其 digest 字符串。发布 wire 只公开其 `host_release_digest`，但安装前和 verifier 必须逐项重算该完整 host manifest 与 distribution identity。该闭包不含时间、绝对路径、目标配置、profile/current-head 值、凭据、联系人或健康正文。同一源码连续 build 必须得到相同 digest 和内容；已存在且逐项相同的 digest 目录只作为幂等结果返回。

发布物至少包含：

- `plugin/health-weixin/plugin.yaml` 和 `__init__.py`。manifest 必须是 pinned Hermes `PluginManager` 可扫描、在临时 isolated `HERMES_HOME` 的 `plugins.enabled` allowlist 下可真实 load/register 的 user `platform` Plugin；wrapper 必须携带可导入的当前 `hermes_host.py` 与 `host_contract.py` 副本，并且在无仓库 `PYTHONPATH` 的全新 Python interpreter 中以对象身份直接 re-export 当前 hash-identical `partner_health_steward.hermes_host.register`；其注册 `health_weixin`，初始 `check_fn()` 为 false。发布物不写 Hermes config，也不 arm/activate。
- 仅为 Plugin 接线所需的 `hermes_host.py`、`host_contract.py` 与显式 wrapper；现有完整 `plugin.py`、`core.py`、model/delivery interface 与迁移源码作为 hash-bound release assets，不能由 sentinel、fixture 文本或占位符代替。
- 七个确切名称的 `skills/<name>/SKILL.md`：`health-init`、`health-steward`、`health-settings`、`health-portrait`、`health-evidence`、`health-owner-inquiry`、`health-literature`。每个只忠实声明现有冻结职责和 `staged` 可用性，不含新健康/医学内容，也不把职责变成独立写入入口。
- 当前 release declaration 所要求的三类 CorePort interface、state/capability schema、minimum-help/knowledge/safety/diagnostic 声明、migration/environment/ACL 声明、required patch 与 disabled-native assertion。权利、医学审核或实例授权尚未存在的 bundle 必须显式 `staged` / `unavailable`，不能伪造 approved 或 activation-ready。
- `runtime/core_port_server.py`：真实 AF_UNIX/TCP-loopback v1 framing server 的可执行实现，提供只用于发布 self-check 的 `StagedCorePortServer.start() -> endpoint` 与 `close()`。它复用 118 的 4-byte big-endian canonical JSON、64 KiB、exact-field、无重复 key 规则：非 v1、未知 kind/field、截断、尾随、重复 key 或超长 frame 必须关闭该 connection 而不返回成功/health verdict。默认运行态不构造 `HealthCore`、不创建 `CurrentHeadPort`、不创建 vault、也不读取 health state；仅对严格合法的 command、managed-read、controlled-effect 三类请求逐一返回 `rejected / health-core-staged`。将来仅可由已有外部权威注入一个真实 HealthCore；120 不定义或实现该权威。当前授权不允许启动独立 service，故该 runtime 随发布物安装但不由 120 启动。

`HostReleaseContract` 继续独占 release 输入的语义闭包。120 的 distribution manifest 只是对已生成字节的内容寻址包装，不是第二 release database、批准账本或业务真相。verifier 维护独立、固定的 role/path closure；它不能从候选 manifest 自身导出预期 closure。安装前与 staging 后都必须拒绝 manifest 任何未知/缺失字段、重复 path、非 regular file、symlink、未声明 regular file、嵌入 host manifest 的任何篡改，以及任一被声明文件的 hash 不符。

### V01 verifier-authority correction：唯一 hash-bound marker 常量

`MISSING-CURRENT` 与 `REPLACED-BY-CURRENT` 继续对发布目录每个 regular text file 零容忍。`TICKET118_` 也继续零容忍，唯一的精确例外是 `plugin/health-weixin/partner_health_steward/host_contract.py`：verifier 必须同时证明它与仓库 `partner_health_steward/host_contract.py` SHA-256 完全一致，并收集所有含该字面量的发布相对路径，精确断言集合只等于该路径。该唯一出现是产品自身的 forbidden-marker policy 常量，不是 synthetic fixture 内容；hash-identical source copy 因而既防止例外被扩展，也防止用替换源码规避现有 policy。任何第二个 regular text file 含 `TICKET118_` 都必须使 V01 失败；不得按后缀、目录或 role 作宽泛排除。

Windows 工作树不能创建 symlink 时不降低此闭包。V07 的真实 symlink/FIFO 攻击只在 `sys.platform == "linux"` 的 default target 主机、随机 `/tmp/ticket120-v07-*` isolated directory 的冻结 verifier 中运行；该程序不读取 Hermes 文件、不创建 permit、不写安装根或 service。Linux verifier 必须对同目录上传的 raw Git root tree object 重算 canonical tree hash，再与 verifier blob、run_id 和 release digest 绑定；Windows V01—V06 与 Linux V07 只有这四项及 tree 完全相同才可聚合。任一绑定不一致是 `cannot-confirm`，不是本地替代的通过。

## 唯一部署公共 Seam

新增 `DefaultOnlyGateExecutor`，生产构造器签名必须为无参数，且不接受 profile、root、service、operations factory、filesystem 或 service-controller 参数；公共行为仅为：

```python
DefaultOnlyGateExecutor(...).execute(request) -> GateObservation
```

`request` 是严格 `ticket120-default-stage-install-v1` Mapping，必须精确指定：`profile=default`、`hermes_home=/root/.hermes`、`service=hermes-gateway.service`、本地 release directory、opaque `run_id`、`gate_id=119-G10` 与本次 permit 的 opaque `approval_ref`。任一 Partner profile/root/service、任一其他 profile/service、路径逃逸、顶层或 target 内未知字段、无效或被篡改 release 都在创建备份、文件 staging、安装或 service 调用前返回 `rejected`，零写入。

`GateObservation.to_wire()` 字段严格等于 `contract`、`release_digest`、`verdict`、`backup_ref`、`plugin_state`、`service`、`rollback`、`steps`、`reason`、`idempotent`。它只输出 release digest、`staged | rejected | not-authorized | failed | cannot-confirm` verdict、无值 backup ref、plugin staged 状态、默认 service 结果、rollback 状态、固定步骤名和稳定 reason code；每个字段的类型与枚举由 verifier 固定，不允许嵌套 Mapping 或任意诊断文本。不得添加绝对路径、permit path/content、操作者身份、文件内容、配置、Token、凭据、联系人、健康资料或 service 配置。值对象不可变。

实现内部只可有一个私有、不可由生产调用者配置的 default-local operations factory：它固定解析 `/root/.hermes`，并固定创建仅能 `systemctl restart/is-active hermes-gateway.service` 的 controller。verifier 用 patch 替换该私有 factory 到临时目录 fake，以观察真实 permit/backup/stage/install/restore 调用；fake controller 对任何非该精确 service 名立即失败，测试的 physical backing 不改变 request identity，也不成为公共构造参数或可配置 target。它不是新的公共部署框架。生产薄入口不调用、列举或检查 partner service。

## G10 一次性 DeploymentPermit

当前主任务的明确授权仅可转换为一个 root-owned 的 target-local `DeploymentPermit`，而不是产品审批、健康授权或可复用 deployment framework。其 canonical UTF-8 JSON 精确字段为 `contract=ticket120-deployment-permit-v1`、`release_digest`、opaque `run_id`、`gate_id=119-G10`、严格 default target 三元组和 RFC3339 UTC `expires_at`；其 SHA-256 canonical digest 是 Ticket 119 G10 的 opaque `approval_ref`。permit 是 `/root/.hermes` 下固定 private permit directory 的 regular file：owner uid `0`、mode `0600`、非 symlink、无 ACL/owner 异常；只保存上述运维绑定，不含 owner/health/contact/model/config/credential 资料。创建 permit 只允许在产品代码和双轴实施审查通过后、按当前主任务授权在 default target-local root 上进行。

执行器先验证 request/release，再从固定 permit directory 读取该 opaque ref 对应 permit，验证 canonical digest、owner/mode/regular-file、未过期、release/run/gate/target 精确绑定。缺失、错误绑定、过期、撤回（文件删除）、重复消费给出 `not-authorized`，不创建 backup、不 stage/install/restart；permit read 不属于部署写入。验证成功时，在同一 default-local private directory 原子消费 permit 并记录仅 `(permit digest, execution key, release digest)` 的不可逆消费事实。相同 `(release_digest, run_id, 119-G10)` 的已完成 execution 必须从已安装 metadata/recovery record 幂等回读，零第二部署；其他 execution key 不能重用 consumed permit。此短期 permit/消费记录只服务该次运维恢复或重放，删除 permit 可在消费前撤回，不成为健康业务状态、产品批准、用户授权或通用持久账本。项目不承诺对 root/SSH 运维身份的恶意行为防护。

## 固定执行顺序

1. 解析 request 和 release manifest，验证目标三元组、目录边界、独立完整 closure、每个 manifest hash、Plugin 文件与七 Skill；任何失败零写入。
2. 若同 digest、同 `run_id`、同 `119-G10` execution 已完整 staged 且 Plugin hash 相同，返回 idempotent `staged`，零第二 permit consume/backup/安装/restart；其他 execution 必须尚未消费的精确 permit。
3. 在任何 live 文件改变前，验证并原子消费精确 `DeploymentPermit`；任何 permit failure 为 `not-authorized`，零 backup/stage/install/restart。
4. 在任何 live 文件改变前，创建无内容回传的 default-only backup，记录 opaque backup ref。
5. 在目标根内由 operations 创建 digest-bound staging 副本，复验 distribution manifest 的独立完整 closure、嵌入 118 manifest、Plugin registration 文件与 staged CorePort server；verifier 从 operations 的真实调用记录而非 `GateObservation.steps` 自报证明 permit/backup 先于 stage、stage 先于 install。staging 不含实例配置或任何 health state。
6. 原子安装 `plugins/health-weixin` 和 digest/execution-key release metadata；不写 `config.yaml`、profile、current-head、socket、database、service unit 或任何 partner 路径。写入后 Plugin 仍 staged，CorePort runtime 未启动。
7. 仅重启 `hermes-gateway.service`，只检查该 default service active 和安装 Plugin manifest/hash 可发现；该检查不把 service active 解释为健康处理可用。
8. 任一步（包括 partial install、restart 或 post-check）失败，自动恢复完整 backup，**再仅重启 default service 一次**，然后检查该新进程 active；这才证明候选 Plugin 不继续驻留在 rollback 后的进程中。恢复、rollback restart 或其检查任一不能确认时，返回 `cannot-confirm`；三者均确认才返回 `failed` / `rollback=completed`。不触碰 Partner 或任何其他 service。

安装不应用 required patch 到未知 Hermes source root，不修改 Gateway config，亦不启动 CorePort runtime：这些动作需要 119-G10 的精确 target binding/ACL/source evidence 与后续单独授权。本票只将 hash-bound patch 作为发布资产交给后续 gate，不能静默猜测 upstream root。

## 必须杀死的现实错误

| 验收 | 冻结控制 |
|---|---|
| 120-A1 | 构建的是完整、以完整 118 manifest + 全文件 canonical body 独立重算的内容寻址闭包，且经固定 pinned `PluginManager` 真实 discovery/register 后可在干净 interpreter 以对象身份导入真实 `hermes_host.register` 的发布目录；七 Skill 都存在，未把 verifier synthetic fixture 当运行资产。 |
| 120-A2 | production executor 构造器签名无参数、无可配置 target root/service/factory，且 profile/root/service 的任意非 default 组合或未知字段均零写入、零 service 操作；permit 错绑/过期/撤回/重复消费同样零部署写入。 |
| 120-A3 | operations 的真实调用记录证明 permit/备份严格发生在 staging/安装之前，stage 复验独立完整 closure 后才安装；安装后 health 明确 staged，成功只重启并检查 default service。 |
| 120-A4 | partial install、restart、post-check、恢复、恢复后 default restart 或其 active 检查不确定时自动回滚并 `cannot-confirm`；只有恢复后新 default 进程确认 active 才能报告 rollback completed。 |
| 120-A5 | 两个 executor 实例共享同一 target 时，同 digest/same execution key 的重复执行没有第二次 permit consume、backup、安装、restart 或副作用。 |
| 120-A6 | distribution/host manifest、file hash、未声明文件/symlink、release 路径或 Plugin/Skill 缺失时，在 permit consume/备份前拒绝；不能安装被替换字节。 |
| 120-A7 | 发布目录内启动的 staged runtime 对严格 v1 command、managed-read、controlled-effect 都拒绝无外部真实权威的操作，对 malformed/unknown/non-canonical/duplicate/truncated/oversized frame 关闭连接；不以 InMemoryCurrentHead/vault 或 synthetic result 冒充运行 Core。 |

## 复杂度上限、验证与停止

允许的增量只有：一个 release publisher、一个 default-only executor、不可变 observation、一个 staged CorePort server、静态发布资产与两个薄 CLI。禁止通用部署器、可配置 target/profile/service、第二数据库、第二 current-head、activation ledger、健康功能、医学内容、真实网络、真实模型、Weixin、联系人和产品验收。

编码前 verifier 固定为 `tests/test_ticket120_integration.py`。基线预期 `1 failure / 6 skips`，唯一红灯是两项公共 Module 尚不存在；实现后同一七门必须 `7/7 PASS`。随后运行 Ticket 118/119、受影响回归、全量测试、release build、compileall、diff check、静态 secret/path scan，并核对 Ticket 118/119 冻结三件套零变化。若需要任何冻结文件修改、新的生产 CurrentHead/vault、真实 Partner/Linux/凭据/配置值决定、未知 Hermes source root patch，立即停止并把可定位冲突交回用户。
