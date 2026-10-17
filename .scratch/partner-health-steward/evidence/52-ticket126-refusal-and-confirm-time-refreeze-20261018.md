# Ticket126 R5：拒绝观察与确认时间样例有界重冻结

Reviewed checkpoint `837ac4dba1ca6024ca81e3bdbab5f2193344f878` / tree `c178e4e7fb64b7cca2d5ba2591f5aa817864ea7d`，实际干净detached checkout `/tmp/health-steward-126-r5-837ac4d-clean`。只修正126独立verifier的两个局部样例，41个产品Python文件与6752逐字相同，全部五个test方法AST、R3 unknown ACK、唯一设计及旧122/123不变。root独立identity证据 `/tmp/ticket126-r5-root-837ac4d-identities.json`。

## 实际故障和独立复现

R4正式6752五门5run/1fail/0error/skip：真实严格客户端在两个故意非法binding收到Service EOF时抛固定异常，verifier误按另一transport的None观察。R5只在这两个负例捕获实际固定类型/原因，并保留或增加无accepted/handoff/新发送、查询仍可读且uninitialized断言；正常调用不吞异常。随后cde88eb provisional五门仍1fail，已修负例通过，后继独立confirm合成protocol时间却早于真实披露2小时40分，Core正确拒绝。

修正仅将V02独立confirm时间设为披露后的2026-08-24T00:00:01Z，真实received_at仍由Adapter取当前时间。root独立运行 `/tmp/ticket126-r5-confirmation-order.py`，日志 `/tmp/ticket126-r5-root-confirmation-order.log`：旧protocol在received_at也晚于披露时仍被health-init-disclosure-order-invalid拒绝；新protocol及received_at分别晚1秒/2秒时可真实prepare/commit/finalize enabled。没有修改生产顺序门或替主人同意。

第一837隔离快照复制基础runtime时Errno28，没有seal或执行测试，不记作产品失败。root只清理本任务创建、已过时且无进程使用的32个runtime/hermes-pinned/tmp孩子，保留各snapshot logs/manifests/source/verifier及本地原Git/builder；正式profile/DB/密钥/服务未修改，释放4,003,962,880bytes。日志 `/tmp/dmit-connection-audit/prune-superseded-verification-copies.log`。default实际为root user unit；只读确认其loaded/active/running，system级not-found不代表停服。

完全新tag `formal-126-r5p2-837ac4d`在冻结前仅作characterization：5run/0failure/error/skip，30.829秒；源87、原批准13+候选2 identities、运行环境7464文件不变，closure `sha256:92911a523ed4f6d58df0b2ce4ed477a14e600c89b4b469c144db89834347595a`。日志 `/tmp/dmit-connection-audit/formal-126-r5p2-837ac4d-components-only.log`，明确PROVISIONAL-R5-NOT-FROZEN、没有full794；不将此历史改写为正式验收。

## Spec

**PASS — Spec 轴，限 R5 冻结前有界修正。** 无 P0–P2 finding。

- EOF 捕获仅覆盖两个故意非法 binding，限定异常类型及精确原因；继续断言无 accepted、无 handoff、无额外发送，真实查询仍为 uninitialized。
- 独立确认时间修正恢复披露先于来源的语义；独立 native ID、实际接收时间及生产严格顺序检查保持不变。
- 独立核对五个 Gate 方法 AST、41 个产品 Python 文件均未变化；三个 blob 匹配，工作树干净，编译及限定差异检查通过。历史失败和 provisional 证据边界保留。

Commit：`837ac4dba1ca6024ca81e3bdbab5f2193344f878`
Tree：`c178e4e7fb64b7cca2d5ba2591f5aa817864ea7d`

本轮未运行服务或五门测试。本结论不代表正式五门、full794、闭票或真实外部验收；仍需 root 重冻结及新精确干净快照。

## Standards

**PASS — R5 有界 Standards 审查；无 P0–P2 阻塞 finding。**

- EOF 捕获仅限两个故意非法 binding，限定异常类型及精确原因 `core-frame-truncated`；正常路径不吞异常。保留无 handoff，并增加无 accepted、无新增发送、真实查询可读且仍未初始化的断言。
- 确认时间修正为披露后的 `2026-08-24T00:00:01Z`，独立 native ID 保留。Core 对协议时间和接收时间的严格先后检查未变；提供的 root 日志证明旧时间拒绝、新时间启用。
- 独立核验：41 个产品 Python 文件与基线一致，五门方法 AST 一致，旧122/123测试未改，三个 blob 全部匹配；内存编译与 diff check 通过，工作树干净。未引入伪造授权、业务结果或产品旁路。

Commit：`837ac4dba1ca6024ca81e3bdbab5f2193344f878`
Tree：`c178e4e7fb64b7cca2d5ba2591f5aa817864ea7d`

本结论仅供正式重冻结前审查；未运行服务或正式五门/full794。既有失败记录保留，不构成闭票或真实外部验收。

## Root authority

同一837 checkpoint新鲜双轴PASS，root现允许对该精确干净source/同41产品字节使用全新正式snapshot运行原样五门、131四门、124四门、完整794、标准compileall/15冻结blob/运行闭包及root独立23门。唯一设计blob `4a6ec81c94edab252936815cf0fc98925def3d0f`；最新独立合同 `f824e8c2d2b00586c592edc1533ca5a03342813d`；verifier `a4d9b67366f3b0e52528f3c9f43562a6e50c80c7`，取代Evidence51旧对应两项。只修正verifier观察，不放宽生产权限，不授权更改冻结文件。新正式执行、实施后双轴、真实模型/微信/部署/主人验收仍未完成；真实目标归128，130另有唯一候选且不得纳入本票全绿声明。
