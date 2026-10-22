# Ticket130 正向交接及旧 batch 重投的局部观察修订

原R2.5完整WIP七门 `/tmp/ticket130-business-full7-remote.log` 如实保留235.996秒、V01/02/03/06/07通过、V04一项error及V05一项failure，未冒称正式绿灯。后续真实取消的业务时钟错误已交产品修复；新WIP `/tmp/ticket130-business-wip-v5-remote.log` 的V06通过、V05仍因旧cursor观察失败，亦非正式门。

独立verification authority与root仅确认两处有限观察修订：

- V04原known正向child只等模型terminal与HTTP文字可见便disconnect，可能取消尚未回交Core的原通知。三次正常对照及 `/tmp/ticket130-known-failed-teardown-v3-remote.log` 的真实外部清理延迟对照显示：session实际close后延迟0.75秒，立即teardown留下模型failed/terminal=true、通知executing/attempted及Core正确UNKNOWN/拒读正文；相同延迟下等真实通知handoff再断开，则actual delivery-complete accepted/handoff=true、Core healthy、零evidence。修订只加强known正向分支，要求同source实际completion外层accepted、内外层handoff与accepted层后才disconnect；父侧Core零事实检查及真实unknown/peer-exit恢复均不变。
- V05实际task-cancel已accepted并advanced后，同message ID/body/protocol time/旧batchcursor重投task-once。原Core只允许ready/executing的cursor directive，已advanced不得重新签发；持久游标不得倒退到旧任务batch。原helper倒退断言是假红，但 `/tmp/ticket130-business-cancel-replay-observe-remote.log` 记录的真实重投causal-id-conflict是独立产品缺口，不能当成功。修订同时要求重投accepted/replayed、同原source/refs、无stage/model/send/新directive、最新持久cursor不变及父侧唯一同ID任务/取消状态。`/tmp/ticket130-business-cancel-wake-observe-remote.log` 仅证明原取消与到期零发送，不代替正式V05。产品修复只复用既有HMAC完整native fingerprint核验后的首receipt generation/received_at归一，不能修改cursor状态机或新建权威。

唯一当前checkpoint `fb97e5e656b4ebe29d7b1dfce25c24d6ce58ed46` / tree `b6e7fd0811be0fd017d848895ccda8086b50e0cf`。design `b5df3ef47fde1993a72cc293d5e56edee4fb44dc`不变；contract `5134e3a1f137bf24fe0acdcfc0aa50a43117214d`、verifier `19ba1c10dbf2de199c751c1f454569fced2091ed`替代Evidence62对应项。仅两owned文件37增/11删；其余16冻结blob逐字不变，七家族不变。root独立clean clone `/tmp/health-steward-130-r26-fb97e5e-clean` 已核对精确身份、18blob、内存编译及diff check。身份与有限diff另见 `/tmp/ticket130-r26-checkpoint.json`、`/tmp/ticket130-r26.diff`。

当前任务内fresh-context只读 `pre130_r26_spec` **Spec PASS，无P0—P2**，`pre130_r26_standards` **Standards PASS，无P0—P2**；均独立核对同checkpoint、真实对照与原权限链，没有联网、写文件、再委派或使用额外外部执行器。两轴明确重投产品错误仍须修，当前结论不代表formal、部署或主人验收。

root仅冻结上述同family观察修订并授权现设计内最小修复。最终干净提交仍须正式七门、受影响门、全量、root独立回归、编译、18冻结及runtime完整性、实施后双轴与root闭票；真实部署仍归128。
