# Ticket 120 冻结验证合同

> 状态：frozen。与 `120-frozen-implementation-design.md` 同属 baseline commit `4b90a4fe22d2d4acf674d76c732a9de765f03079`、tree `c855edb43240882ac69008dcd08eac6db1a208b8`。本合同的 verifier-owned 实现固定为 `tests/test_ticket120_integration.py`，后续实施不得修改这三件套。

## 公共对象与测试边界

包必须公开 `HermesReleasePublisher` 与无参数生产构造的 `DefaultOnlyGateExecutor`。测试只使用：

```python
published = HermesReleasePublisher(repository_root).build(output_root)
observation = DefaultOnlyGateExecutor().execute(request)
```

`published.to_wire()` 和 `observation.to_wire()` 是唯一产品输出观察面；发布目录位置由 caller 的 `output_root / published.to_wire()["release_digest"]` 推导，不读取发布对象属性。测试以 patch 替换私有 default-local operations factory 到临时目录 fake，以观察真实 permit read/consume、backup/stage/install/restore 调用及与 fake service 共享的顺序日志；这不改变 production constructor、request target identity 或生产 root/service。fake service 只接受精确 `hermes-gateway.service`，收到任何其他名称即测试失败；它只返回 restart/active 故障，不连接 systemd/network。测试必须断言 `inspect.signature(DefaultOnlyGateExecutor)` 无参数。测试不得读取产品私有字段、仓库真实配置、任何历史 `ops/`、环境秘密、服务器、聊天、健康资料、联系人或运行数据库。

测试 request 必须使用严格 target identity，并精确带 `run_id`、`gate_id=119-G10` 与 DeploymentPermit canonical digest 的 opaque `approval_ref`：

```json
{
  "profile": "default",
  "hermes_home": "/root/.hermes",
 "service": "hermes-gateway.service"
}
```

临时目录仅替代目标文件系统位置；不得用它改变 request 中的 target identity。任何输出只能包含 digest、固定状态、opaque ref 与固定 reason，禁止绝对路径和秘密。

fake permit 用 canonical `ticket120-deployment-permit-v1` fixture 表示 root-owned `0600` regular, non-symlink target-local file；它精确绑定 release/run/G10/default target/expiry，既不含身份也不含 health/config/credential 内容。测试覆盖缺失、owner/mode/regular 条件不符、release/run/gate/target 错绑、过期、删除撤回、首次消费与同 execution key replay；失败只允许 permit read，任何 backup/stage/install/restart 都必须为零。production implementation 必须以真实 uid/mode/stat/atomic create-or-consume 达到同一规则，自动门不伪造 root 或 Linux target 成功。

## 分平台执行与同一证据绑定

V01—V06 在当前 Windows 工作树运行；V07 是同一 `tests/test_ticket120_integration.py` 的 strict Linux-only method。Windows 不设置 `TICKET120_LINUX_V07=1` 时 V07 必须明确 platform skip，绝不能 mock、删除或伪造 symlink/non-regular-file 通过；macOS/BSD 或任一非 `sys.platform == "linux"` 的运行也必须失败关闭而不能进入聚合。Linux V07 只能在 SSH 目标的随机 `/tmp/ticket120-v07-*` fresh directory 内执行：它真实创建并 `lstat` 确认 symlink 与 FIFO，再让 release verifier 证明二者均在 permit consume、backup、安装根写入、service controller 调用之前被拒绝。上传材料只限冻结 verifier、当前候选 Git root tree 的 raw object、实现后所需的当前无敏感 `partner_health_steward` 源码和公开 release build 输入；不得读取/复制 Hermes config、凭据、聊天、健康资料、联系人或运行数据库，不创建 permit，不触碰 `/root/.hermes`、partner profile 或任何 service。

每次跨平台验收先生成同一 opaque `run_id`，并记录当前 Git tree、verifier Git blob、release digest。Linux V07 要求 `TICKET120_RUN_ID`、`TICKET120_GIT_TREE`、`TICKET120_VERIFIER_BLOB`、同一 isolated directory 内的 `TICKET120_GIT_TREE_OBJECT`，以及 implementation 后由 Windows release build 产生的 `TICKET120_RELEASE_DIGEST`；它以 canonical Git `tree <length>\\0<body>` SHA-1 重算上传 raw tree object，重算 verifier blob，且重建 release digest 必须相等。最终只有 Windows V01—V06 与 Linux V07 都 PASS，且四个值完全一致，才可报告 `7/7 PASS`；任一值缺失或不等只能是 `cannot-confirm`，不能以单机全绿或 Windows symlink mock 聚合。编码前 Linux run 仍先真实完成 symlink/FIFO mechanical probe，随后因两个公共 Module 缺失形成同一 prerequisite skip；它只是冻结机械可执行性证据，不是 7/7 聚合。

## 七门

| Gate | 验收 | 必须证明 | 必须杀死的独立错误 |
|---|---|---|---|
| 120-V01 | 120-A1/A7 | verifier 以本地 canonical algorithm 重算 `{contract,state,files,full host_release_manifest}` digest，并以固定 role/path closure 与公开 `HostReleaseContract.build()` 重算嵌入 manifest；在 temporary isolated `HERMES_HOME` 使用固定 pinned `PluginManager` 对发布目录 discovery/load/register，确认对象身份、初始 `check_fn` false；七 Skill/bundle state staged/unavailable；启动发布内 runtime，对三类 canonical v1 frame 得到 `rejected/health-core-staged`，对 malformed/unknown/non-canonical/type-invalid/duplicate/truncated/oversized frame 关闭连接 | 固定 digest、假/缺 host closure、假 wrapper、仓库 import 泄漏、Plugin YAML 但 loader 无法发现、存在 server 却接受/宽松解析 health 操作、文件存在即 health active |
| 120-V02 | 120-A2 | `inspect.signature` 证明 production executor 无参数；partner/default root/service 的所有错配组合、顶层/target 未知字段均 `rejected` 且 factories 零调用；缺失/错绑/过期/撤回/重复消费 permit 仅 read permit，任何 backup/stage/install/restart/service 调用为零 | 先备份/写入后才发现 Partner，或由 caller 注入 physical partner root/错误 service，或由普通字符串伪造 G10 授权 |
| 120-V03 | 120-A3 | 合法 default + exact permit 安装由 fake operations 与 service 的共享日志真实记录 consume→backup→stage→install→精确 default restart/check；stage 保存 digest-bound byte copy；正常与 stage-after-copy tamper/extra-file 两个等价类均独立重算完整 closure，后者零 install/restart；Plugin 安装完成仍 `staged` | 无 permit/备份直接覆盖、伪造 steps、未 stage/复验、stage 被换字节仍安装、安装即 activation、重启多个或 Partner service |
| 120-V04 | 120-A4 | partial install 或 initial restart 故障后 restore 完整 managed target，再 restart 仅 default service 并检查新进程 active；顺序确认后才 failed/rollback completed | partial/restart 失败留半安装、只恢复 Plugin 不恢复 metadata、旧进程仍可能加载候选、回滚不复查、用失败冒充 staged |
| 120-V05 | 120-A4 | post-install check 故障时自动 restore，再 restart/check default；restore、rollback restart、rollback active-check 分别无法确认都 `cannot-confirm`，三者均确认才 failed/completed | 只有 restart 故障才回滚，或无法确认却报告确认回滚 |
| 120-V06 | 120-A5 | 两个新 executor 实例共享 target state 的同 release/run/G10 execution 返回 idempotent staged，permit consume/backup/stage/install/restart 计数均不增加；其他 key 不得重用 consumed permit | 实例内缓存假幂等、重试重复 service 重启/备份，或 consumed permit 被跨 run 重放 |
| 120-V07 | 120-A6 | Linux `/tmp/ticket120-v07-*` isolated verifier 真实创建/lstat 确认 symlink 与 FIFO，并与 distribution/host manifest、files entry、受管文件、未声明 regular file 或 release path/strict fields篡改一并证明：在 permit consume/任何 write/service 调用前 `rejected`；每个 `files` item 严格只含 path/hash；每个 observation wire 字段集、类型、枚举精确且递归拒绝 POSIX/Windows/UNC 绝对路径、permit 内容、操作者/health/contact、配置或凭据值 | Windows mock 或无权限跳过 symlink、只相信 manifest self-report、安装被替换/额外/非 regular 的代码或 Skill，或在 observation/file list 偷带 target/config/secret/permit 值 |

基线的唯一红灯是两个公共 Module 缺失；V02—V07 只因该同一前置 skip。预期为 `1 failure / 6 skips / 0 errors`。实施完成后不改测试，预期 `7/7 PASS`。本合同不伪造 production CurrentHead/vault、医疗审核、真实 Hermes config/ACL、Plugin enablement、socket daemon、模型、Weixin、主人或联系人证据；它只用 root-owned one-shot permit 校验 119-G10 的当前 release/run/gate/target 运维授权，仍不产生 active、健康处理或产品验收。

## 固定命令与冻结完整性

实施前、后都运行（Windows V07 是明确 platform skip）：

```text
python -m unittest -v tests.test_ticket120_integration
TICKET118_PINNED_HERMES_SOURCE=D:\CodexData\tmp\ticket118-hermes-3c27eb python -m unittest -v tests.test_ticket118_integration
python -m unittest -v tests.test_ticket119_integration
python -m unittest discover -v
python tools/ticket120_release.py build --output <temporary-directory>
python -m compileall -q partner_health_steward tests tools
git diff --check
```

Linux V07 的机械 pre-code 命令只能在先后各一次只读 `systemctl --user is-active hermes-gateway.service` 与 `systemctl --user is-active hermes-gateway-partner.service` 之间运行。通过限制 identities 的 SSH 创建随机 `/tmp/ticket120-v07-*`，仅上传当前 `tests/test_ticket120_integration.py`、由 `git cat-file tree <candidate-tree>` 得到的 raw root tree object 与无敏感 binding values；使用 `TICKET120_LINUX_V07=1`、同一 run/tree/blob/tree-object values 执行 `Ticket120VerificationTests.test_v120_07_rejects_tamper_before_operations_and_keeps_wire_safe`。基线必须显示 symlink/FIFO probe 已执行、随后公共 Module prerequisite skip；结束后删除该精确 `/tmp/ticket120-v07-*`，再以 `--user` 读服务状态并确认未变。实施后同一命令额外传入 Windows release build 的 digest，并上传最小源码；它必须成为 PASS，才可与 Windows V01—V06 聚合。

冻结 checkpoint 以后，必须核对 `118/119` 两份 frozen implementation design、两份 frozen verification contract 与两份 verifier-owned integration test 相对其冻结 blob 均为零变化，并额外核对 120 三件套自身零变化。静态扫描只针对新发布目录与新增/修改文件，禁止读取根目录 Token 或任何配置值。
