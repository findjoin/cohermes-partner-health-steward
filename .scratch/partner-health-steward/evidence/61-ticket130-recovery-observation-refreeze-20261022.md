# Ticket130 原恢复家族的真实观察修订

精确产品 `a71f2714b23d6bc16286998f7456cc725bad6212` / tree `f169e186f6efd49ad904907d8c14b1a36c0d6141` 在新的DMIT隔离副本 `/opt/hsv-7i66_gv9/formal-a71f271-130-r23` 原样执行R2.3七门，结果为7 tests、6 failures、0 errors/skips、174.711秒；V02/V03通过，其余失败不是完整产品绿灯，后续组件和全量未执行。封存runtime7467文件，closure `sha256:adad2e6da5b5851faeee5566dce31cd9650968c6a2121257cc656e6bce7d6cd3`；完整原日志 `/tmp/dmit-connection-audit/formal-a71f271-130-r23-failures.log`。实际产品初始化、控制、可见回执、长正文和销钥收尾的错误仍交产品修复，不能归并为fixture假红。

独立verification authority仅确认原V04三处观察矛盾：

- `/tmp/ticket130-unknown-read-characterization.py/.log` 实际Core admit→prepare→start→abort unknown→重开：原Core正文读取按既有安全门拒绝，三写门关闭、无该source durable turn，原Store合成状态digest未变且evidence为零。要求此时Core正文读取成功会迫使产品放开旧门。修订仍要求其拒绝，并仅以同fixture既有Store公共事实读取比较健康时的baseline。
- `/tmp/ticket130-observe-recovery-remote.log` 首个固定限制已实际显示并沿原outbox接受交接；重开新HTTP观察器正确复用原refs且没有第二次发送，不能要求重发后再看到正文。修订保留每个严格handoff、同refs、零模型/新send/POST；未显示过限制的candidate-loss/peer-exit仍要求首次真实显示。
- 第一次补充复现的handoffFalse没有被后一次成功掩盖。`/tmp/ticket130-notice-crash-exception-remote.log` 在合成provider接受后实际终止child，原attempt时间 `2026-10-22T08:48:10.652967+00:00` 晚于fixture固定Core恢复时钟 `08:48:06.900178+00:00`；首次原公开恢复抛出 `DeliveryContractViolation: delivery observation predates attempt`，导致effect unknown而outbox仍attempted。只在原重开前推进已声明fixture clock到真实当前UTC；生产时间比较、真实退出/重建和handoff要求不变。

唯一当前checkpoint `2d9da87194554bb31119d618ce8baaf2af3e5bc3` / tree `e14e7aae0a96185a6182794657be2f7b527f8300`。design `b5df3ef47fde1993a72cc293d5e56edee4fb44dc`不变；contract `1da035fa0994bb718184bd646292a24a57fa0aa7`、verifier `d4c943f5876720614cc5bd8088b22e0b661f0117`替代Evidence60对应项。仅原V04，七家族及其余六测试方法/helper AST保持；总18冻结文件中其余16逐字不变。root独立clean clone `/tmp/health-steward-130-r24-2d9da87-clean`，内存编译/diff/identity检查通过。

当前任务内fresh-context只读 `pre130_r24_spec` **Spec PASS，无P0—P2**：独立重跑unknown characterization，并用原断言拒绝15种错误观察。`pre130_r24_standards` **Standards PASS，无P0—P2**：核对严格handoff、chrono、真实退出及16不变blob，并实际拒绝6类错误refs/效果/显示观察。两者没有修改、联网、再委派或调用被拒绝的额外外部执行器。此为局部编码前refreeze，不是formal、产品完成或部署通过。

root仅冻结上述同family修订；原唯一设计、产品权限及其余权威不变。完整最终提交仍须原七门、受影响门、全量、编译、18冻结及runtime完整性、实施后双轴和root闭票，真实部署仍归128。
