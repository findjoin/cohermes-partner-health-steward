# Ticket126 持久unknown游标验证返冻结

原冻结设计第106行与五门范围不变。局部公开Core复现见 `/tmp/t126-root-unknown-ack-reproduction.log`；旧门正式5run/3failure/0error/skip见 `/tmp/dmit-connection-audit/formal-cd5bcb3-126-131-components-only.log`。V02/V04真实client framing及V03 external fake release另行精确处置；本次只补持久unknown/handoff后的exact cursor ACK与零重发。

Reviewed checkpoint `c54deceed45807f4c3397f4b07ceac23242bb660` / tree `fbbe72c2450f05ee52d9b03302b3de44373e32bb`；独立clean checkout `/tmp/health-steward-126-r3-precode`。新内部路径未实际通过最高接口，不是产品验收；compile/diff绿不代替执行。

## Spec

PASS — bounded Spec verifier-refreeze review only. No P0–P2 contradiction, false-red, fake authority, or missing causal coverage found in `cd5bcb3..c54dece`.

- [Restart tracer](/tmp/health-steward-126-r3-precode/tests/test_ticket126_live_delivery.py:664) requires the original source’s directive, exact cursor advancement, and no resend after durable unknown recovery.
- [HTTP-timeout tracer](/tmp/health-steward-126-r3-precode/tests/test_ticket126_live_delivery.py:934) requires real Core `unknown`, `unknown_frozen`, and handoff, followed by exact persisted/poll cursor and no second send on replay. These assertions meaningfully catch blocked ACK, misclassified terminal, and duplicate-send mutations. Mutation execution is not claimed.
- These expectations match unchanged design line 106. HTTP injection supplies only a transport failure.

Checkpoint:
- Commit: `c54deceed45807f4c3397f4b07ceac23242bb660`
- Tree: `fbbe72c2450f05ee52d9b03302b3de44373e32bb`

Clean worktree; in-memory compile and diff check PASS. No modifications or services run. This is **pre-affected-code refreeze only**, not product acceptance, dual-axis approval, or a claim that V04/full794 passes.

## Standards

PASS — bounded pre-affected-code verifier-refreeze review. No P0–P2 contradiction, false-red, fake authority, or missing causal coverage found in `cd5bcb3..c54dece`.

- New V04 checks durable unknown→exact cursor advancement and no resend through the production registry/Bridge path, with only HTTP timeout injection.
- Restart coverage adds original-source cursor directive/result checks while retaining old-session rejection.
- This follows existing design line 106; design blob and five-gate count remain unchanged.
- Contract append accurately distinguishes prior product failures, standalone reproduction, and the unexecuted new highest-interface path.

Reviewed checkpoint:
- Commit: `c54deceed45807f4c3397f4b07ceac23242bb660`
- Tree: `fbbe72c2450f05ee52d9b03302b3de44373e32bb`
- Contract blob: `f80433a1c639b0747717274bbfd8f35b3dfe8eb0`
- Verifier blob: `87577caefcc087c6c0e64034a5b365168e3605ff`

Clean worktree; in-memory compile and diff check PASS. No modifications or services started. This is one bounded review verdict, not root freeze, product acceptance, or an implementation-completion claim.

## Root authority

同checkpoint双PASS；唯一设计blob仍 `4a6ec81c94edab252936815cf0fc98925def3d0f`，独立合同更新为 `f80433a1c639b0747717274bbfd8f35b3dfe8eb0`，verifier更新为 `87577caefcc087c6c0e64034a5b365168e3605ff`。本条取代Evidence47对应合同／测试blob，允许在既有设计范围修复该unknown exact cursor边界；不得打开一般健康写入、模型或重试权限。已复现的旧external DynamoDB fake占位operation限制另需独立verification修订，不修改旧122/123冻结文件或生产DynamoDB来迎合占位值。最终126仍需最新三件套与全部794执行门、终审，尚未完成。
