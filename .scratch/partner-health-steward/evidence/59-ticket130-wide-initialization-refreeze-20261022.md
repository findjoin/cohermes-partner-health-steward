# Ticket130 宽分片正向样例初始化纠正

root在精确d364783的真实隔离3.11／Publisher／AF_UNIX阶段测试发现原V03宽正向未到模型即等待超时。网络作者仅用独立观察wrapper记录真实RPC元数据：Core healthy后首个governed-receive立即rejected／initialization-required、next_stage=null，无prepare/chunk/model。原父样例与child chunks均未初始化，其他V03 mutation已经调用既有public `_initialize`。日志 `/tmp/ticket130-observe-wide-remote-v2.log`，阶段原样失败 `/tmp/dmit-connection-audit/formal-d364783-130-model-debug-selected.log`；产品正确保持初始化门禁。

因果对照只在真实fixture调用该public初始化，再运行原child：intake request69747及answer70484 bytes各3请求片／3结果片，实际complete→daily-finalized→126 accepted／handoff→cursor advanced；`/tmp/ticket130-observe-wide-initialized-remote.log`。观察wrapper缺原PASS marker，外层断言失败，明确不是正式V03通过。没有修改密封产品／冻结测试或伪造业务返回。

独立verification authority仅给wide positive补一行既有`_initialize(fixture)`并记录合同事实，两文件3增1删。新checkpoint `87fb488291f13d935f89f6bed963546b1fe88670` / tree `e4cf0f73bf040dfb66e8ba60df4994e390b6b96c`；设计 `b5df3ef47fde1993a72cc293d5e56edee4fb44dc`不变，合同 `518abde834452777d02885ba56d54e049c223db6`，verifier `774201899a2e70103e5bf400a712555056a192cf`。AST／内存compile／diffcheck通过。旧83448d7基线加相同三blob的干净来源 `/tmp/health-steward-130-r22-prereq-baseline`仍为7明确缺模块failure、0error/skip（`/tmp/ticket130-precode-r22-baseline-red.log`）；它不是当前部分实现checkpoint的执行结果。

root独立干净来源 `/tmp/health-steward-130-r22-87fb488-clean`，两个当前任务fresh-context只读reviewer仅复核此实证矛盾：`pre130_r22_spec` **Spec PASS，原V03假红消除，无剩余P0—P2**；`pre130_r22_standards` **Standards PASS，无剩余P0—P2**。两者分别核对精确identity／三blob／clean／diff及原helper的公开披露、独立同意、commit/finalize和enabled readback；无直接置enabled、放开产品门禁或新架构。没有写文件、委派、额外外部执行器、网络或真实资料访问。

root据此窄refreeze，上述三blob取代Evidence58对应合同／测试，唯一设计／七家族及其余Evidence57权限不变。原正式门仍须在完整最终产品精确source执行；本页不宣称130完成、真实部署或主人验收。
