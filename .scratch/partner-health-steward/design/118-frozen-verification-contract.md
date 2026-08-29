# Ticket 118 冻结验证合同

> 状态：frozen。经审内容 checkpoint 为 `5f5cc383416401b82419db90fac2ba36b9f76bda`，tree `9dc75c783ae9e910ce4adc6fbaa4de25a651d481`；本合同 blob `b4f579d600965861d54ba60b5ba10b159f45ea22`，verifier-owned test blob `55a2c94373548f240934d6c201a4b5a5338748ee`，测试 SHA-256 `c31095d92fcd2f4c9e159babd261a6f50f6aa87fcedd7c767e61102fbef95189`；fresh-context Spec 与 Standards 均 PASS。characterization 产品基线为 `169cf6cdba421cc628de435cea8cb284e2d8ec94`，tree 为 `64334c675cf32eb950c5b19779d4a1965c863304`；旧全量基线为 `729/729 PASS`。本合同与 [`118-frozen-implementation-design.md`](118-frozen-implementation-design.md) 共同约束编码 Agent，二者任一变化都必须返回冻结阶段。

## 测试权威、公开 Seam 与依赖展开

独立 verification authority 独占 `tests/test_ticket118_integration.py`。编码 Agent 不得修改该文件、本合同或冻结设计；认为 Gate 错误、公开 Seam 客观不可实现、pinned Hermes 与 HOW 根本冲突或需要真实目标决定时，必须停止并返回冻结阶段。

验收只穿过一个新增深 Module 的三项公开 Interface：

- `HostReleaseContract.build(release_sources)`；
- `HostReleaseContract.verify(release_manifest, pinned_host_source)`；
- `HostReleaseContract.assess(transition_assessment)`。

返回对象必须提供严格、无秘密的 `to_wire() -> dict`。测试只观察 release digest、四类 manifest 事实、host verdict/proofs、三类 CorePort proof、readiness verdict/requirements 和外部 Adapter 调用记录；不读取产品私有 helper、缓存、表、registry 内部字段或摘要算法。`HostReleaseContract` 从 `partner_health_steward` 包公开导出；不为每种 artifact、检查或报告增加公共 validator。

`verify` 的第二参数是一个 verifier-supplied pinned-host source Mapping。测试只从显式环境变量 `TICKET118_PINNED_HERMES_SOURCE` 取得本地只读 source root，不保留开发机默认绝对路径；变量缺失时 V02 在依赖展开后必须 `FAIL`，最终不得 skip。Mapping 还包含固定 commit、allowlisted 相对文件及其已知 SHA-256，以及只用于本机验证的 synthetic credential、runtime socket endpoint 和 effect Adapter。root 只定位，不进入 manifest/report。fresh subprocess 先从 `ReleaseManifest.repository_verified` 定位并重算唯一 `hermes-host-health-weixin-adapter` artifact，再以完全相同字节重建临时 `HERMES_HOME` Plugin；required patch 与 native-disable assertion 必须是各自独立的公开、hash-bound release bytes，不能复制同一个 Python 文件冒充四项 artifact。required patch 使用可由本地 `git apply --no-index` 检查并应用的统一 diff，verifier 在导入 Hermes 前把它应用于一次性 staged checkout。`hermes_cli.plugins`、`gateway.platform_registry`、`gateway.run` 的实际 source path 必须全部属于该 staged root；前两项保持固定 base hash，实际加载的 `gateway.run` 必须是与 base hash 不同的 patched source，而非导入后临时 monkeypatch。V02/V05 在 fresh subprocess 中运行以隔离 Hermes 模块级 registry。正向 V02 必须由 `verify` 在返回前调用真实 `PluginManager.discover_and_load`，加载当前公共 `hermes_host.register(ctx)`，穿过真实 `PluginContext.register_platform` 和 `PlatformRegistry/GatewayRunner`，由真实 factory 实例化并 await Hermes 实际 lifecycle `connect(is_reconnect=False)/disconnect` 完成后才能记为 completed。测试只在这些真实调用点记录，不在 `verify` 返回后补跑 lifecycle，也不接受 report 自报字段、动态类路径伪装、marker 或手写正向 stub。错误 upstream hash 必须在 discovery/register 之前失败。fresh subprocess 使用显式最小环境，不继承调用进程的任意秘密环境变量。

本机 Windows 不被要求证明 Linux 内核 `SO_PEERCRED` 或目标 Unix ACL 已执行。V03 使用只向产品暴露本机 byte-stream endpoint 的独立 runtime oracle：支持 `socket.AF_UNIX` 的平台必须使用真实 AF_UNIX；当前不提供 AF_UNIX 的 Windows 使用真实 TCP loopback framing 作为 transport substitute，并在 endpoint/测试中明确标为 `tcp-loopback`，不得冒充 AF_UNIX。`command`、`managed-read`、`controlled-effect claim/terminal` 三类都必须以 4-byte length + canonical JSON frame 真实过 socket，oracle 独立记录 frame 和被 core 接受的 terminal。错误 peer、截断、尾随、未知 kind 和不完整 terminal 都必须失败关闭；Linux `SO_PEERCRED` 与目标 socket ACL enforcement 仍留 119。测试不把后二者降为直接 Mapping，也不只断言 report 字符串。

当前产品没有 `HostReleaseContract`。因此使用依赖展开：V01 通过包的公开导出检查并调用 `build`；缺失时形成唯一 `FAIL`。V02—V07 仅在同一公共 Module 尚不存在时 `SKIP`。V01 转绿后，其余门全部自动展开；任何行为缺口必须真实 `FAIL`，不得继续 skip。编码前唯一接受形状为 `1 failure / 6 skips / 0 errors`；完成只接受 `7 passed / 0 skipped / 0 errors`。

## 冻结 fixture 与公共 wire

V01 在临时目录建立显式 allowlist 的 synthetic release tree。它不复制真实健康资料、目标配置、实例 migration manifest、联系人、密钥或 Token，也不读取任何历史 `ops/` artifact。Plugin/core、Ticket 117 migration synthetic fixture 使用当前仓库真实 artifact；`partner_health_steward.hermes_host` 出现后作为唯一 host/health_weixin Adapter artifact，其公开的 required patch bytes 与 native-disable assertion bytes 分别成为两个独立内容与 hash 的 release artifact，不把同一模块重复复制成四项。其余内容使用无秘密 synthetic fixture。allowlist 用语义 role 覆盖：Hermes patch/native-disable、当前 hermes_host+health_weixin Adapter、Plugin/core、七 Skill bundle、model/delivery Adapter、三类 CorePort、schema、capability-profile schema/builder/validator、MinimumHelpBundle、knowledge/safety/diagnostic bundle、migration protocol/schema/builder/semantic registry/synthetic fixture、Python/依赖和服务身份/ACL requirement。目录外文件和 `runtime/instance-manifest.json` 不是 release 输入。

`ReleaseManifest.to_wire()` 至少公开：

- `contract == "ticket118-release-manifest-v1"`；
- `release_digest`，以 `sha256:` 开头；
- `repository_verified`，每项含相对 path、role 和内容 hash；
- `target_binding_required`、`external_approval_required`、`forbidden_secret_classes`；
- pinned Hermes commit/allowlisted source hash、环境约束和三类 CorePort contract version。

上述 pinned commit、每个 source hash、extractor version、Python 环境约束、三类 CorePort version，以及 `target_binding_required`、`external_approval_required`、`forbidden_secret_classes` 三组分类声明都是 release 身份；wire 必须逐项精确公开，任何单项声明漂移都必须改变 release digest。

额外字段允许存在，但不能保存绝对根路径、时间戳、实例值、真实 profile/current-head、秘密或健康正文。`HostContractReport` 与 `ReadinessReport` 的总体 verdict 只允许 `pass | fail | cannot-confirm`。

## 七个 verifier-owned Gate

| Gate | 验收 | 公开结果与等价类 | 必须杀死的独立现实错误 |
|---|---|---|---|
| 118-V01 | 118-A1 | 同一 allowlist 连续 build 的完整 wire 和 digest 相同；对每个受管 artifact 的一个等价漂移循环都改变 digest；修改 allowlist 外实例文件后完整 manifest 不变；`repository_verified` 逐项精确等于相对 path、role、`sha256:` 内容 hash；pinned/source/extractor/Python/CorePort 与三组事实分类声明逐项公开且任一漂移改变 digest | 漏 artifact/声明 hash 仍同摘要，或实例状态、机器路径、构建时间混入 release |
| 118-V02 | 118-A2 | 独立强读 pinned HEAD/四文件 hash；从 manifest 的 host artifact 原字节重建 Plugin 并核加载 hash；真实 staged pinned source 内 discovery 加载当前 hermes_host，精确一次注册 `health_weixin`，经真实 registry/Gateway factory await `connect/disconnect` 完成后才可返回 proof，非 awaitable lifecycle 直接失败；Mapping 仍声明原 hash 但实际 staged source 漂移，以及错误 Mapping hash，均在 discovery 前失败 | 自报字段、动态类、未 await lifecycle、只核声明不核实际 source 或手写 stub 冒充 pinned host |
| 118-V03 | 118-A3 | 独立 runtime oracle 实收三类 socket frame，controlled-effect 还必须形成 claim 与 terminal 两帧并接受完整 terminal；错误 peer、截断、尾随、未知 kind、不完整 terminal 等价类均无 activation proof；只有 Linux credential enforcement 留 119 | 仅 command 走 socket、其余 Mapping 直通，或错误 frame/effect 未知冒充成功 |
| 118-V04 | 118-A4 | runtime oracle 发出并保存同 session 的当前 core intent/grant；合法效果必须把 Adapter 返回的 status/result_ref/terminal 连同 session/lease/intent/generation/fence 精确回交并仅接受一次；无 claim、错误 grant、forged/stale 在 Adapter 前拒绝，缺 status/result_ref/terminal 调用 Adapter 后仍不被 core 接受 | Adapter 自造业务结果、错配 grant、提升 terminal 或未完整回交就被报告成功 |
| 118-V05 | 118-A5 | worker 从 manifest 独立定位、读回并重算 native-disabled assertion path/hash，再把实际 bytes 与声明 hash 交给 host verification；预置真实 native/old candidates 后，故障前经 pinned Gateway 探测四入口，register 精确一次且仅 current 可达；core 失败并注销 current 后再次探测，四者均不可达且 old factory 始终零调用；manifest 不变但 assertion 实际文件被篡改时 discovery 前失败 | 只信 assertion 声明、空 registry 真空证明，或 Plugin 失败后 current/旧健康路径重新可达 |
| 118-V06 | 118-A6 | install 缺 binding 或 synthetic verified 均 `cannot-confirm`；两次 `build` 的相同 manifest 是纯 offline upgrade `pass` 的独立 oracle；修改真实 schema artifact 后新 manifest 形成 drift 并 `fail`；rollback generation/fence 只有 synthetic evidence 时整体 `cannot-confirm` 且绝不恢复实例状态 | 用 `compatible/current` 字符串回显通过，或 synthetic rollback 冒充目标安全 |
| 118-V07 | 118-A7 | manifest 四类事实互斥；全 synthetic `verified + compatible` observation 仍不能产生 Partner `pass` 或 activation；manifest/HostContractReport/ReadinessReport 三类完整 wire 递归扫描所有 `Mapping`（含 dict 子类）与 list/tuple/set/frozenset，禁止开发机 root、Linux/Windows/UNC 绝对路径及注入环境秘密；artifact 注入 secret marker、健康正文或绝对路径时 build 拒绝 | 合成 fixture 冒充当前 Partner，或自定义 Mapping／嵌套容器让秘密、PII、配置值进入 release/digest/report |

每门只杀死表中一个现实错误。等价输入只在同一决策点共享一个 `subTest`；不对 artifact、字段、平台、故障和阶段做笛卡尔积，也不以七个测试数量本身作为充分性证明。

## 防假绿与停止

- V01 红灯必须来自当前包缺少公开 Module 或 build 的实际可观察结果；禁止无条件 `fail`、导入一个不存在的模块路径作为 test error、复制产品摘要算法或调用私有 helper。
- V02 正向必须对本地 checkout 执行 `git rev-parse HEAD`、逐文件 hash；测试从 manifest 重建当前 Plugin 并核对加载字节 hash，独立观察 staged pinned source 的真实 discovery、registration、Gateway/registry factory 和 await 完成的 `connect/disconnect`；fixture/stub 只允许制造负向 failure。
- V03 按 `hasattr(socket, "AF_UNIX")` 选择 transport：支持时必须 AF_UNIX，不支持时只允许显式 `tcp-loopback` substitute；两者都让三类 Interface 运行真实 byte-stream framing，119 只补目标 `SO_PEERCRED`/socket ACL enforcement。
- V06 唯一 `pass` 只证明两个 build 产物的纯离线 upgrade 兼容性，不得携带 Partner/Linux target requirement 或凭字符串声明；rollback 没有非 synthetic target authority 时必须 `cannot-confirm`。
- 测试不得访问网络、真实 Partner、真实微信、真实模型、服务器配置、环境凭据或仓库根 `telegram_bot_token.txt`。fixture 只读取显式创建文件和 pinned Hermes allowlist。
- fresh subprocess 只接收显式最小环境；manifest、host report、readiness report 的全部 wire 都必须通过路径／秘密扫描，observer 的本机定位记录不得进入产品 wire。
- `cannot-confirm` 是失败关闭的产品结果，不是测试 skip。最终任何 skip 都阻止完成。
- 若实现必须暴露任意 method RPC、第二 release/current-head/activation ledger、读取实例状态来生成 release，或把真实 Linux/Partner 证据提前写入 118，设计客观未满足，应停止而不是弱化 Gate。

pre-code checkpoint 必须记录：

- `python -m unittest -v tests.test_ticket118_integration`：预期 `1 failure / 6 skips / 0 errors`；
- `python -m unittest -v tests.test_ticket117_integration`：既有 `9/9 PASS`；
- `python -m compileall -q partner_health_steward tests`：通过；
- `git diff --check`：通过；
- `tests/test_ticket118_integration.py` 的 SHA-256。

实现完成后还需同一冻结文件 `7/7 PASS`、Tickets 113—117 受影响回归、`python -m unittest discover -v -s tests -p "test_ticket118_*.py"`、本票单一 release/preflight 工具入口、全量 discovery、compileall、diff check 和静态 secret/path scan 全绿。冻结设计、合同和 verifier-owned test blob 相对 test-gate checkpoint 必须零变化。

## 编码前运行证据

- characterization 产品基线：`169cf6cdba421cc628de435cea8cb284e2d8ec94`；tree `64334c675cf32eb950c5b19779d4a1965c863304`；旧全量 `729/729 PASS`。
- `python -m unittest -v tests.test_ticket118_integration`：`1 failure / 6 skips / 0 errors`；唯一失败为包尚未公开 `HostReleaseContract`，其余六门仅因同一前置缺失 skip。
- `python -m unittest -v tests.test_ticket117_integration`：`9/9 PASS`。
- `python -m compileall -q partner_health_steward tests`：通过。
- `git diff --check`：通过，仅报告工作树既有 LF/CRLF 转换提示，无 whitespace error。
- pinned Hermes 本地 checkout 已只读核对为 commit `3c27eb6234bf91b8ceee9e9071591b31e9b148cb`，四个 allowlisted 源文件 SHA-256 与 V02 常量一致；测试不保存该 checkout 的开发机绝对路径，执行时必须显式设置 `TICKET118_PINNED_HERMES_SOURCE`。
- 当前 verifier-owned 测试 SHA-256：`c31095d92fcd2f4c9e159babd261a6f50f6aa87fcedd7c767e61102fbef95189`；冻结 checkpoint、tree 与最终 blob 由顶层冻结 Agent 提交后补入。
