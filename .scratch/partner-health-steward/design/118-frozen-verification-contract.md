# Ticket 118 冻结验证合同

> 状态：candidate，等待当前 verifier-owned 门运行、测试文件 hash 和 fresh-context 双轴预审后冻结。characterization 产品基线为 `169cf6cdba421cc628de435cea8cb284e2d8ec94`，tree 为 `64334c675cf32eb950c5b19779d4a1965c863304`；旧全量基线为 `729/729 PASS`。本合同与 [`118-frozen-implementation-design.md`](118-frozen-implementation-design.md) 共同约束编码 Agent，二者任一变化都必须返回冻结阶段。

## 测试权威、公开 Seam 与依赖展开

独立 verification authority 独占 `tests/test_ticket118_integration.py`。编码 Agent 不得修改该文件、本合同或冻结设计；认为 Gate 错误、公开 Seam 客观不可实现、pinned Hermes 与 HOW 根本冲突或需要真实目标决定时，必须停止并返回冻结阶段。

验收只穿过一个新增深 Module 的三项公开 Interface：

- `HostReleaseContract.build(release_sources)`；
- `HostReleaseContract.verify(release_manifest, pinned_host_source)`；
- `HostReleaseContract.assess(transition_assessment)`。

返回对象必须提供严格、无秘密的 `to_wire() -> dict`。测试只观察 release digest、四类 manifest 事实、host verdict/proofs、三类 CorePort proof、readiness verdict/requirements 和外部 Adapter 调用记录；不读取产品私有 helper、缓存、表、registry 内部字段或摘要算法。`HostReleaseContract` 从 `partner_health_steward` 包公开导出；不为每种 artifact、检查或报告增加公共 validator。

`verify` 的第二参数是一个 verifier-supplied pinned-host source Mapping。测试只从显式环境变量 `TICKET118_PINNED_HERMES_SOURCE` 取得本地只读 source root，不保留开发机默认绝对路径；变量缺失时 V02 在依赖展开后必须 `FAIL`，最终不得 skip。Mapping 还包含固定 commit、allowlisted 相对文件及其已知 SHA-256，以及只用于本机验证的 synthetic credential、CorePort 和 effect Adapter。root 只定位，不进入 manifest/report。正向 V02 将当前 release 中的真实 health Plugin/host patch/health_weixin Adapter 接入该 checkout；测试在产品 report 之外直接拦截并检查真实 `hermes_cli.plugins.PluginContext.register_platform`、真实 `PluginManager` 类型与真实 `gateway.platform_registry.PlatformRegistry` 的公开调用和可达项，再由 registry factory 实例化 release Adapter 并运行 `start/stop`。不能用 report 自报字段、marker 文件或测试手写生命周期 stub 代替。负向分支只改变 Adapter 的自然返回/异常或提交 forged controlled-effect probe，不提供魔法 `fault_injection` 标志、测试专用产品分支或正向宿主替身。

本机 Windows 不被要求证明 Linux 内核 `SO_PEERCRED` 或目标 Unix ACL 已执行。V03 仍必须通过真实本机 byte-stream socket 把 protocol-v1 frame 送入现有 `HealthPlugin.handle_frame` Seam；支持 AF_UNIX 时使用 AF_UNIX，不支持时只以本机 `socketpair` 替代传输原语，Linux credential enforcement 仍留 119。V03 以 synthetic credential Adapter 杀死错误 peer，并实际杀死截断、尾随、未知 kind 和不完整 terminal；不能只断言 report 字符串。该延期不得让 118 把 synthetic 结果写成真实 Partner proof。

当前产品没有 `HostReleaseContract`。因此使用依赖展开：V01 通过包的公开导出检查并调用 `build`；缺失时形成唯一 `FAIL`。V02—V07 仅在同一公共 Module 尚不存在时 `SKIP`。V01 转绿后，其余门全部自动展开；任何行为缺口必须真实 `FAIL`，不得继续 skip。编码前唯一接受形状为 `1 failure / 6 skips / 0 errors`；完成只接受 `7 passed / 0 skipped / 0 errors`。

## 冻结 fixture 与公共 wire

V01 在临时目录建立显式 allowlist 的 synthetic release tree。它不复制真实健康资料、目标配置、实例 migration manifest、联系人、密钥或 Token。Plugin、host patch、health_weixin Adapter 和 Ticket 117 migration synthetic fixture 使用当前仓库真实 artifact 的本地副本；其余内容使用无秘密 synthetic fixture。allowlist 用语义 role 覆盖：Hermes patch/native-disable、Plugin/core、七 Skill bundle、health_weixin/model/delivery Adapter、三类 CorePort、schema、capability-profile schema/builder/validator、MinimumHelpBundle、knowledge/safety/diagnostic bundle、migration protocol/schema/builder/semantic registry/synthetic fixture、Python/依赖和服务身份/ACL requirement。目录外文件和 `runtime/instance-manifest.json` 不是 release 输入。

`ReleaseManifest.to_wire()` 至少公开：

- `contract == "ticket118-release-manifest-v1"`；
- `release_digest`，以 `sha256:` 开头；
- `repository_verified`，每项含相对 path、role 和内容 hash；
- `target_binding_required`、`external_approval_required`、`forbidden_secret_classes`；
- pinned Hermes commit/allowlisted source hash、环境约束和三类 CorePort contract version。

额外字段允许存在，但不能保存绝对根路径、时间戳、实例值、真实 profile/current-head、秘密或健康正文。`HostContractReport` 与 `ReadinessReport` 的总体 verdict 只允许 `pass | fail | cannot-confirm`。

## 七个 verifier-owned Gate

| Gate | 验收 | 公开结果与等价类 | 必须杀死的独立现实错误 |
|---|---|---|---|
| 118-V01 | 118-A1 | 同一 allowlist 连续 build 的完整 wire 和 digest 相同；对每个受管 artifact 的一个等价漂移循环都改变 digest；修改 allowlist 外实例文件后完整 manifest 不变；`repository_verified` 对每项精确等于相对 path、role、`sha256:` 内容 hash，且包含 Ticket 117 migration synthetic fixture | 漏 hash 仍同摘要，或实例状态、机器路径、构建时间混入 release |
| 118-V02 | 118-A2 | 先独立强读 pinned checkout HEAD 和四个 upstream 文件已知 SHA-256；再独立观察真实 PluginContext/PluginManager/PlatformRegistry 只注册一个 `health_weixin`，由 registry factory 加载当前 release Adapter 并实际运行 start/stop；错误 upstream hash 在注册前返回 `fail`、无 activation proof | 自报字段或手写 stub 冒充 pinned host，或来源漂移仍签发宿主通过 |
| 118-V03 | 118-A3 | 正向用真实本机 socket 传输实际 protocol-v1 frame 并由现有 HealthPlugin 解码/响应；错误 peer、截断、尾随、未知 kind、不完整 terminal 五个同决策点等价类均 `fail/cannot-confirm` 且无 activation proof；只有 Linux credential enforcement 留 119 | socket 外壳旁仍有 generic/direct write，错误 peer/frame 或 effect 后未知冒充成功 |
| 118-V04 | 118-A4 | 同一 Gate 先由现有 core 签发真实 intent/grant，合法完整 terminal 恰调用一次 Adapter 并通过；forged intent 与 stale fence 在调用前拒绝，missing terminal 调用后失败关闭；调用记录是独立 oracle | Adapter 自造业务结果、提升 terminal 或从普通宿主状态旁路写入 |
| 118-V05 | 118-A5 | core 回调失败时，独立观察真实 registry 已清空且只有 `health_weixin` 曾尝试注册；旧 `medical`、历史 split、native `weixin` fallback、普通健康入口均不可达且无 activation proof | 文档写 disabled 但 registry 仍可达，或 Plugin 失败回退旧健康路径 |
| 118-V06 | 118-A6 | install 缺 binding 为 `cannot-confirm`，即使 synthetic observation 自称 verified 仍不能通过；显式 `offline-release-compatibility` scope 且无 target binding 的 upgrade 与 rollback 各有可达 `pass`，但无 activation proof；schema drift upgrade 与 stale generation/fence rollback 各有代表性 `fail`，rollback pass/fail 都不恢复实例状态 | 未知被跳过，离线兼容永远不可达，或 rollback 被实现成复制旧文件/恢复旧 authority |
| 118-V07 | 118-A7 | manifest 四类事实互斥；全 synthetic `verified + compatible` observation 仍不能产生 Partner `pass` 或 activation；在 allowlisted artifact 中注入 secret marker、健康正文或绝对路径时 `build` 拒绝且不产生 manifest | 合成 fixture 冒充当前 Partner，或秘密/PII/配置值进入 release/digest/report |

每门只杀死表中一个现实错误。等价输入只在同一决策点共享一个 `subTest`；不对 artifact、字段、平台、故障和阶段做笛卡尔积，也不以七个测试数量本身作为充分性证明。

## 防假绿与停止

- V01 红灯必须来自当前包缺少公开 Module 或 build 的实际可观察结果；禁止无条件 `fail`、导入一个不存在的模块路径作为 test error、复制产品摘要算法或调用私有 helper。
- V02 正向必须对本地 checkout 执行 `git rev-parse HEAD`、逐文件 hash，并由测试独立观察真实 pinned lifecycle/registration Interface 的调用、registry、factory 和 Adapter lifecycle；fixture/stub 只允许制造负向 failure。
- V03 不因 Windows 缺 Linux peer credential 形成不可执行假门，但 Windows 仍运行真实 byte-stream socket framing；119 只补目标 `SO_PEERCRED`/ACL enforcement。
- V06 的 pass 只证明 release 的纯离线兼容性，不得携带 Partner 或 Linux target requirement；只要 transition 需要 target binding，synthetic evidence 一律不能产生 pass。
- 测试不得访问网络、真实 Partner、真实微信、真实模型、服务器配置、环境凭据或仓库根 `telegram_bot_token.txt`。fixture 只读取显式创建文件和 pinned Hermes allowlist。
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
- 当前 verifier-owned 测试 SHA-256：`973bc4b87d428314b5660f462fb99231497c01860108b3c00f382c7161d4e8ac`；冻结 checkpoint、tree 与最终 blob 由顶层冻结 Agent 提交后补入。
