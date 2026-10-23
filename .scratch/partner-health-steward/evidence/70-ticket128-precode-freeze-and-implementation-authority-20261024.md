# Ticket128：编码前冻结与一致性实施授权

2026-10-24。root只在下述同一checkpoint收敛后冻结本票增量并授权一致性实施；本页不表示生产安装、G10/G11、主人同意、非诊断可用里程碑或完整产品验收通过。128保持claimed，127/完整full医学范围仍未满足。

## 同一checkpoint与两轴

当前冻结checkpoint `cb1435477aa4fc6c0e6062884984e60b00394dfb`，tree `215aa2a9fb1b67106be6e170199ac85f3ac29ee8`，已普通push至原 `codex/complete-health-steward`，root工作树与clean clone均干净。产品仍为130已闭合的精确f21e8ad，未因本轮设计/测试改变。唯一设计为下表第一项；其候选标题/未授权文字记录原写入阶段，当前冻结权威是本页和本票，无第二Spec/Map/验收账本。

- fresh-context Spec R2 `/root/pre128_r2_spec`：**PASS**，`128-SPEC-01`关闭，无其他阻塞；报告 `/tmp/health-steward-reviews/128-pre-cb14354-spec-fresh.txt`。
- fresh-context Standards R2 `/root/implementation128/standards_r2_readonly`（fork_turns=none、只读、未参与作者）：**PASS**，无阻塞；原始最终报告由父任务转交root并保存在 `/tmp/health-steward-reviews/128-pre-cb14354-standards-fresh.txt`。root自身新线程额度到限后由既有team父节点派发这个独立新上下文，没有外部模型执行器/新app chat/审查豁免。

此前R1 `56d9e90`的fresh Standards PASS、fresh Spec仅P2 `128-SPEC-01` FAIL均保留，不重写历史。问题是V07误要求成功导出后外部managed root非空；root分类为测试oracle错误。独立verification只修改test八行和合同同段，保留加密SQLite实际blob/完整JSON附件强正向，改为外部root真实empty且原Adapter可枚举；原导出不为测试新增磁盘副本。R2产品/设计/两fixture/原119/旧冻结均未变，未重开架构或扩门。详本票R1记录及 `/tmp/ticket128-verification-candidate-r2-final-files.json`。

## 不可由实施者修改的五份冻结字节

| 文件 | Git blob | SHA256 |
| --- | --- | --- |
| `.scratch/partner-health-steward/design/128-default-nondiagnostic-deployment-design.md` | `75840ed2a5d1e6b089453c984dc0d0528d69d7de` | `c0d942c89aec085e8837ebd2d942c78eb28d2128542486e4d630f2689a2976e2` |
| `.scratch/partner-health-steward/design/128-frozen-verification-contract.md` | `6a7e86880042a61979cbf7542c4bd7f5633c2d30` | `246cdf09ec5583d7758ad6407c55fb6820c5fc13f205528388085caf67a061eb` |
| `tests/test_ticket128_default_deployment.py` | `9d8affe72375a83807923e54468381f228e0bcd8` | `33aa1f196b1662d9e632c83cb16bde53fde9f2785984975f6477c2e11d1d17cf` |
| `tests/fixtures/ticket128_default_deployment_inputs.json` | `df01af3d43b23632a120776ed9b454a8b16b2ce1` | `fbd0e2c22a6c12073fc97c59bf91c1392cb17106a20b66ee888a1aa51a227c3f` |
| `tests/fixtures/ticket128_namespace_runner.py` | `84744a661006291d6810355ae74583c749f49b71` | `0235a2935af9174f220b7aa98e637a5a182adab8ec542635d5e38ec9e4983365` |

旧124/125/126/129/130/131共18份design/contract/test冻结继续原字节；连同本票5份共23。root在clean checkpoint上用现有formal builder核实际Git blob/SHA，完整表 `/tmp/dmit-connection-audit/formal-cb14354-128-precode-generated-frozen-blobs.json`（SHA256 `4eaa1032bbea91013a3bef9b484b267802f6374cdb5b0c4df999c55b8baf497a`）。本票实施者不修改这些文件、原119测试或治理文档；真实未覆盖错误/假oracle仍交独立verification确认并返回同冻结阶段，不自改门变绿。

## 真实执行输入与明确未证明项

[Evidence69](69-ticket128-characterization-and-deployment-inputs-20261024.md)记录公开接口characterization、actual DMIT249隔离原语和非冻结helper试跑、失败修正及原闭包未变。root对R2最终四文件独立重算SHA/blob并原样运行本机真实Python3.12.3：新7项均因两个公开入口缺失而prerequisite失败，0error/skip、内部case0；旧119七项pass，collection808但没有全量执行之声明。记录 `/tmp/ticket128-root-precode-r2-check.json`（SHA256 `bf135051bf057b847fd532fb40d0edac736865a1b9441c896b14ee77bbb0e1c4`）及其原始logs。它们不是实际Python3.11正式门，也不证明最终内部case通过。

同checkpoint正式脚本只在本机生成并通过shell/AST语法，**未执行**：metadata `/tmp/dmit-connection-audit/formal-cb14354-128-precode-generated-metadata.json`，archive SHA256 `3ba276de0b7a136f8ef02b44ca43df9a08c72ad7cf096a709a6a8862a2cb6ba5`，源码108文件（93 Python/15资源）、23冻结，generated_only=true/test_execution_performed=false。实施后须对新的clean/pushed最终产品commit重新生成并在实际3.11闭包执行，不能借此generated checkpoint或历史f21绿灯代替。最终full数量按实际discovery核对；原固定119、受影响118/120—126/129—131、root边界、compile/diff/源码和冻结integrity及fresh双post都须真实通过。

## root实施授权与停止边界

用户已授权补完自己的default项目及DMIT部署，并选择无AWS的host-only旧整机快照限制、JOJO非诊断固定65536 UTF8 bytes/2048tokens/无自动重试切换/不提供共同上下文保证。该工程授权继续有效，不另问已选路线；没有把工程授权写成真人初始化、已读行动、联系人或医学批准。

自本页提交/普通push完成后，root明确授权 `/root/implementation128` 仅按这套冻结边界完成生产差额：同119的ND/full固定scope和H/D双绑定；同Publisher真实ND资源与严格披露/absence；固定typed factory/首次bootstrap/真实空副本；三角色OS与原Gateway relay/proxy/worker；真实ordinary出站和同poller有限G11/ND12技术receipt；固定default的prepare/run、完整程序backup/安全rollback。内部helper/文件组织仍可逆，不建立第二健康或审批权威。

实施owner最多并行两名明确不重叠文件worker。`core.py`任何必要局部变更由其唯一指定owner持 `/tmp/cohermes-core-edit.lock`，其他人不得同时修改；stage/commit持 `/tmp/cohermes-git-mutation.lock`、空index并精确只stage自己文件。root负责远端正式验证/实际目标操作与最终固定非医学文案真实编辑确认；测试/合成/provider边界不能代生产或真人事实。不得外部codex执行器重试、在线安装依赖、伪造Python/importlib/版本/回执或放宽旧门超时来绿。

目标永久仅 `/root/.hermes`、root用户 `hermes-gateway.service`，禁止partner/profile旁路。实施中默认不改真实服务、不POST真实模型/微信；正式执行门及fresh双post全绿后，root才按同128 run真实逐层G01—G09→G10→G11→ND12，保留原逐gate精确许可、未知冻结/单次/原poller ACK、安全rollback。真实主人必须自己完成native init/独立confirm/G11行动与ND体验反馈；没有的事实保持缺失。ND里程碑也不激活BMI/fullG12、不解决128或声称长期稳定。
