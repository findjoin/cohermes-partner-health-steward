# Ticket 120 default-only staged deployment evidence (2026-08-30)

## Answer

The Ticket 120 `119-G10` default-only action installed the verified release as **staged**, not active. The operation used one short-lived, root-owned `0600` DeploymentPermit bound to the release, run, G10 and exact default target; it completed without rollback. This is deployment evidence only. It is not health activation, model/Weixin/contact use, owner acceptance, product acceptance, or stability evidence.

## Bounded, content-free facts

- Implementation commit: `f42cb8f883cde59d668f7e459ee73b765259e647`; tree: `260620a80d4834d8e0b6b01205a7bf4b40374d54`.
- Release digest: `sha256:c34479767a6e8f9f419182faba0cc68abd4ada05996673ac92a6138601775e8b`.
- Run: `ticket120-g10-20260830-001`; gate: `119-G10`.
- Opaque permit reference: `sha256:f01bf650de04461959bfed3537a3c0cd2284a9f6a075718da8a24045cfdb9d71`; it was consumed once.
- Opaque backup reference: `backup:f55afadf7f8b485881a7a2a2d5bc0763`.
- The default service interpreter resolved from the default user service was Python `3.11.15`, satisfying the frozen `>=3.11,<3.12` constraint. No system Python, shared virtual environment, or global Hermes source was modified.
- The gate observation was `staged`, `plugin_state=discovered-staged`, `service=default-active`, `rollback=not-needed`, with the fixed sequence `permit-read -> permit-consumed -> backup -> stage -> install -> restart -> is-active`.
- A same-request replay was idempotently `staged` without a second deployment effect; it revalidated the staged release closure and installed-plugin byte closure.
- The actual Hermes PluginManager discovered `health-weixin` as platform `health_weixin`; its health check was `false`. No CorePort was started and no health capability was enabled.
- Default user service was active after the operation. The partner user service was active before and after; its content-free systemd fingerprint was unchanged: `sha256:49441c1ce09b3f181ed85643fb58f0663b7d3f0410250707ba0e87addcd4aaf0`.

## Boundary confirmation

No Partner profile or Partner service was modified. No configuration values, chat, health data, contacts, credentials, tokens, runtime database, permit body, backup contents, or absolute target paths are recorded here. The temporary deployment work directory was removed after verification.
