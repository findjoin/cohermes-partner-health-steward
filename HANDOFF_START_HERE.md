# Start here: Hermes Partner Health Steward

Snapshot generated: 2026-08-22 07:40:48 +08:00

This private repository is a **decision and evidence handoff** for the next Agent. It is not proof that the health steward is implemented, deployed, medically approved, or accepted in real Weixin use.

## Reading order

1. Read [AGENTS.md](AGENTS.md) for the workflow contract.
2. Read [CONTEXT.md](CONTEXT.md) for the current product contract and domain terms.
3. Read the current [Wayfinder map](.scratch/partner-health-steward/map.md).
4. Claim exactly one unblocked frontier ticket according to the local issue tracker.
5. Read only the evidence and historical decisions linked from that ticket before acting.

## Current CAN handoff

- [【CAN】重建七个健康 Skill 交互合同后的完整能力链与追溯关系](.scratch/partner-health-steward/issues/102-rebuild-complete-capability-chain-after-seven-health-skill-interaction-contract.md)

Completion criterion for takeover: the next Agent can identify the single current frontier, its blockers, the relevant current TO decisions, and the exact evidence it must recheck without relying on chat history.

## Authority and status boundary

- **map.md**, **CONTEXT.md**, resolved Tickets, and their linked evidence are the authoritative decision chain.
- Files under **ops/partner-health-steward** and **ops/weixin-skill-disclosure** are historical implementation and audit inputs. They are **not** the selected current HOW unless a current decision explicitly reselects them.
- Local tests, source presence, and old deployment notes do not prove Linux deployment, live Weixin behavior, medical approval, or product acceptance.
- No credentials, runtime health records, databases, local research mirrors, environments, caches, or logs are included.

## Source snapshot provenance

- Original workspace Git branch: **main**
- Original workspace Git HEAD: **5f358137309d7670e7ad615c8af9d1aa679a49e3**
- The snapshot includes the current allowlisted working files, including their uncommitted content.
- Original workspace status is recorded in [SOURCE_WORKTREE_STATUS.txt](SOURCE_WORKTREE_STATUS.txt).
- Fixed upstream source references are recorded in [SOURCE_BASELINES.md](SOURCE_BASELINES.md).
