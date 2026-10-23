# Ticket128：正常成功等价类与已证OS前提重冻

本票仍claimed。本记录不是正式执行/部署/主人验收通过；default仍未切换，真实模型POST、微信发送与主人初始化未发生。

## 实际R6与必要OS前提

精确候选5b652acb621ec02e7901c77a56b878f74f58c11e，实际3.11原V07 inner511.174秒、parent515.007秒，1failure/0error/0skip，owned cleanup确认，无timeout。G01—G09及ND07通过，原local七组637/12/118/74/11/6/5项全零failure/error/skip。首次到G10，Core实际UID950/caps0/NNP/AF_INET kernel拒绝/初始凭据env absence通过；ordinary main与ExecStartPost为226/NAMESPACE，未到ND12/自然提醒。原日志 `/tmp/dmit-connection-audit/ticket128-r6-gates-final-readonly.log`、`ticket128-r6-role-reason-readonly.log` 保留。

独立OS诊断在全新owned chroot中保持同ordinary-shaped unit全部策略与字节：缺 `/run/systemd/inaccessible/dir` 时226，stderr精确ENOENT；仅自有建立六类mode000 mask节点后main/post均成功。无需user0 mask，不绑定宿主、不放宽unit。全部cleanup确认、rootfs删除。证据 `/tmp/t128-mask-r2-evidence.json` SHA256 ba04f2c9888c4d07595f33406a02ef871c7081cb0f03a8de8eb0a02ac0935c01，含12份named原始records与各hash。它只证明普通OS前提，不是完整G10判词。

R6事后compileall98、冻结23、来源122及runtime9557均不变；closure sha256:eba89253e6fee5a50e68675cadcdfec51cc0dea44812b6d69168e78c037ca217。无活动进程/挂载引用守卫通过后只删除退役公共runtime/pinned副本，保留来源/日志/manifest/私有事实，实际default前后仍PID521/active/running。

## 既有验收差额及独立修订

唯一design §11:188要求失败/unknown按实际发生者核验，并允许known-failed后恢复作为正向代表。当前 `_SEQUENCE_PROGRAM` 无条件将known_failure纳入all(flags.values())，因此合法provider一直成功反而不能ready。verification authority已分类为既有局部实现差额+冻结覆盖漏检，不是新产品范围；这是源码因果反例，未冒称实际ND12 timeout或新V07 red。

独立verification仅修同V07/合同/helper：同一Core天然推进，A真正failed0/unknown0成功序列，B保留原known-failed后新source恢复全链，C当前真实ND12挑战后持久unknown，合法反馈仍不ACK/pass，最后保留未知不重试/换run。每run独立native/source，A首次原生同意，B/C不重新同意；固定同一3小时合成预算wire防止中途改变authority，其他family默认输入与生产不变。原45项V07断言、原七父方法和其他family保持；全量仍808。helper仅补上述标准mask，outer有限7200/7320/7350/7410；原local540、G11/ND12各300、ordinary12/join30、due90/quiet65不变，不省略前置/假ready/SQL/grant或新产品状态。

Checkpoint 42ccbb1a5abe478686710e094e00b15d024f8620 / tree4389dd2a13390073633e09c35ccf176883c71664，parent5b652ac。产品/design/raw/旧18冻结保持；只三文件改变，其余20份冻结逐字一致。

| 文件 | Git blob | SHA256 |
| --- | --- | --- |
| .scratch/partner-health-steward/design/128-frozen-verification-contract.md | 0569bdf77a5b918fad8d267393d47afe84ff4aae | b2533fba7d81ff6f710c674bf7febdb04d78e1c02f6576a4cd17bd3c0b7fb123 |
| tests/fixtures/ticket128_namespace_runner.py | 441636d16751a3679116991b637cd2ca86243b67 | 6bf5978c1d522de177bbe049dd380b27cc60b2fa924743224d09a146120bd706 |
| tests/test_ticket128_default_deployment.py | 8d92cbcaf85b8af2c21ba73ed45ea46f73de9ed1 | 08af1d5d5fbe147511e76fde30b92bdfb9f94e2904d825754074f7f19c82a69f |

## 双pre与root继续实施授权

- Fresh Spec PASS、无阻塞：`/tmp/health-steward-reviews/128-pre-42ccbb1-spec-fresh.txt`，SHA256 81db21415084e7bfde47916d74a4906c8a45bc96bf5c204e92f59db9ca798e4c。
- Fresh Standards PASS、无阻塞：`/tmp/health-steward-reviews/128-pre-42ccbb1-standards-fresh.txt`，SHA256 c04b40a509ca840fc215d17d3ed1232ac5faa57ca21aeb245675b89257766531。

同checkpoint/tree、fresh只读、互未读另一轴报告，新完整门尚未执行。root已普通push5b652ac..42ccbb1至原findjoin仓库同分支；reviewer本人未做网络核验，root不将该限制冒称未push。

Root接受窄重冻，并授权既有DefaultAcceptanceGateExecutor/_SEQUENCE_PROGRAM内最小修复：不再要求模型必须失败，实际已知失败/无失败如实，unresolved unknown继续阻断。不得由产品作者修改冻结门/旧Core/架构/生产预算，不伪造初始化、序列或反馈。

下一步从最终clean/pushed实现正常构造实际3.11闭包，先原V02验证已修OS下完整启动，再原123/118、119七门、root30、原full discover808同父进程一次（含全部七family及三世界），compileall/diff/完整性。全部实际零failure/error/skip才fresh双post，然后才准备真实default同scope逐层run和主人原生步骤。没有普通push或静态review可替代这些事实，阶段A不晋升full/诊断active/闭128。
