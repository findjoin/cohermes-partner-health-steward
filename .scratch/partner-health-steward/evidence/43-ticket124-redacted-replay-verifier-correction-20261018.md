# Ticket124 advanced receipt 重放验证修正

Reviewed commit `78bfe92b3be3286f338969315ef8e44def54daf6`; tree `9af993bef6defdb9493c5ac8991b7f7dc0eea733`。仅修正 V04 的既有隐私释放预期与等待终态，产品代码和 Ticket112 未修改。

## 原因与边界

既有112在 Core receipt 进入 advanced 后释放 daily.result；精确 native 重投返回 accepted / daily-turn-result-redacted，保留终态、record/transition 与 generation。新门不得要求重建已释放正文或再次调用 bridge。等待真实 Core advanced 后再重放，避免只看到 transport ACK 的竞态。

## Spec review

PASS — spec reviewer。限定于本次 V04 验证预期修正，未发现剩余 P0–P2 矛盾。

三文件修订与既有 storage/Core/Plugin 行为一致：等待 Core receipt advanced 后，重放返回 accepted/redacted；完整 terminal、record/transition 与 generation 保持不变，result 为 None，无新增 bridge 调用，unknown attempt 仍为一次。未要求重建已释放正文，未改变产品或 112。

仅做只读审查，未重跑门禁或重开既往结论。

Commit: `78bfe92b3be3286f338969315ef8e44def54daf6`  
Tree: `9af993bef6defdb9493c5ac8991b7f7dc0eea733`

## Standards review

PASS — standards review found no remaining P0–P2 contradiction within this correction.

The revised V04 matches existing advanced-receipt redaction, waits for Core completion and the replay response, and preserves terminal identity, generation, absent result, unchanged bridge calls, and one retained unknown attempt. No product or architecture changes.

Commit: `78bfe92b3be3286f338969315ef8e44def54daf6`
Tree: `9af993bef6defdb9493c5ac8991b7f7dc0eea733`

Read-only review; gates were not rerun.

## 冻结三件套

- `.scratch/partner-health-steward/design/124-live-entry-design.md`: `b70c45df606c2379b361ba31377abadecd3d6357`.

- `.scratch/partner-health-steward/design/124-frozen-verification-contract.md`: `6dc8430cb2c79436984be539e8ed84a27e696aad`.

- `tests/test_ticket124_live_entry.py`: `8253c76fd0d8e1edbe943c4250d31b17c0bdcb3c`.


本证据只授权按修正门重新执行124及全量回归，不声明实施完成或真实渠道已启用。
