# Source baselines

The evidence set primarily evaluates the Partner production baseline:

- Hermes Agent v0.20.0 / release **v2026.8.3**
- Fixed official commit: [3c27eb6234bf91b8ceee9e9071591b31e9b148cb](https://github.com/NousResearch/hermes-agent/commit/3c27eb6234bf91b8ceee9e9071591b31e9b148cb)
- Upstream repository: [NousResearch/hermes-agent](https://github.com/NousResearch/hermes-agent)

Exact source links are embedded beside claims in **.scratch/partner-health-steward/evidence**. Local **.research** mirrors are deliberately omitted because they are large, mutable working copies and are not an authority by themselves. Fetch the cited commit from upstream when source inspection is required.

The Partner server was historically reported as a dirty tree at that commit. Its relevant disclosure candidate and before/after snapshots are included under **ops/weixin-skill-disclosure**; treat them as audit inputs, not verified current production state. Recheck any live or current-version claim before using it in CAN.
