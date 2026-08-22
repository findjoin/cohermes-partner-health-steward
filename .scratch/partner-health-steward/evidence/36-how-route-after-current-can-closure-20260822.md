# Ticket 109 HOW research: unified health-steward Plugin implementation route (2026-08-22)

## Answer

The current TO and the closed CAN support one implementable HOW space, but they do not prove that any component is installed, running, medically approved, or accepted. This evidence selects one route for the current HOW frontier:

> **One Partner Hermes health Plugin product, one Plugin-private low-privilege `health-core`, one local encrypted authoritative state domain, one opaque strongly consistent external current head for generation and writer fencing, one strict host model interface, one offline governed knowledge release path, and one business-fact status/observation path.**

This is a fresh route decision for Ticket 109. It does not restore Ticket 98 or ADR 0021 as current authority. The older ticket and ADR are historical candidates whose compatible constraints were rechecked against the current TO, Ticket 102 trace, Evidence 30-35, and the fixed Hermes/iLink boundaries. The route below is a decision candidate until Ticket 109 is resolved and the current HOW authority is recorded by the parent agent.

No real health material, chat, contact, credentials, tokens, server configuration, runtime database, logs, or backups were read or uploaded. No model, Weixin, alert, correction, deletion, recovery, migration, deployment, medical review, or acceptance action was executed.

## Evidence classification

- **Proven / boundedly reusable:** current product contracts and resolved TO/CAN answers; fixed Hermes v0.20.0 source at commit `3c27eb6234bf91b8ceee9e9071591b31e9b148cb`; fixed iLink message and send-result boundaries; general SQLite, authenticated-encryption, systemd, and conditional-write primitives described by Evidence 30-35.
- **Needs recheck:** the target Partner version and dirty state, actual Plugin/Adapter loading, all health and ordinary entry points, current configuration and owner/contact authorization, current model route, storage and replica surface, resource identity, permissions, real external effects, and all claims about present runtime behavior.
- **Invalid as current authority:** old `ops/` implementations, old `medical` entry assumptions, viewer/second-recipient models, old task and deletion semantics, ordinary Session/Memory/FTS/logs/cache/backup as health authority, and the old Ticket 98/ADR 0021 selection as an already-current decision.
- **Unimplemented / unproven:** the selected route itself, all seven Skill runtime assets and use facts, the core, current-head resource, strict model interface, governed medical bundle, contact effects, deletion and migration closure, business three-state, and every real or external acceptance result.

The CAN closure is therefore a feasibility boundary, not an implementation result. [Evidence 30](30-ticket-103-current-partner-seven-skill-assets-managed-authority-20260822.md)-[Evidence 34](34-ticket-107-support-contact-approval-alert-delivery-correction-deletion-20260822.md) establish that the current Partner lacks the complete seven-Skill, managed-state, routing, medical/safety, diagnostic-revision, and support-contact chains; [Evidence 35](35-current-can-closure-after-seven-skill-contact-investigations-20260822.md) establishes that those gaps no longer contain an uninvestigated fact that determines whether a route can exist.

## Selected topology and trust boundary

The product remains one health Plugin in one Partner Hermes for one owner. The health Plugin owns the user-facing adapter, deterministic admission, coordination, model-port calls, and Weixin delivery adapter. It does not become a second Agent, personality, health product, or independent LLM gateway.

The Plugin calls a same-host, low-privilege `health-core` through a permission-restricted Unix-domain socket. `health-core` has no chat entry point, ordinary conversation, Weixin credential, provider configuration, autonomous timer, or direct outbound channel. It is the only writer of health state, the only business-state arbiter, and the only component allowed to turn a candidate or command into an authoritative health result. Hermes scheduling only wakes it through the Plugin.

The Gateway and `health-core` are managed as one health runtime boundary: if the Gateway or the Plugin cannot prove the core contract, health processing stops. A separately running core cannot produce a health reply, model effect, or Weixin effect. This isolates health keys, transaction state, and migration state from the ordinary Agent process while preserving the product boundary of one Partner Hermes.

Hermes generic Hook, Middleware, prompt text, Skill self-report, ordinary Tool, or model behavior is not a fail-closed security boundary. The fixed Hermes source documents Plugin registration and callback continuation behavior, so a health implementation must make loading, registration, core reachability, current-head consistency, and source identity explicit health prerequisites. A failed health prerequisite makes the health path unavailable; ordinary Hermes continuation cannot be reported as health availability. See [Evidence 19](19-current-partner-hermes-baseline-plugin-lifecycle-trust-20260820.md), [Evidence 30](30-ticket-103-current-partner-seven-skill-assets-managed-authority-20260822.md), and [Evidence 31](31-ticket-104-admission-routing-duty-composition-minimum-safety-20260822.md).

### Three stable interfaces

Only three deep interfaces cross the Plugin/core boundary:

1. **Health command:** one trusted inbound envelope, owner control, scheduler wake-up, migration action, or bounded internal candidate with provenance, causal ID, generation, and permitted scope.
2. **Controlled effect:** a model work order or delivery intent returned by core, followed by a complete model or delivery result returned to core. External effects never write business state directly.
3. **Managed read:** current portrait, evidence, task, control, export, and business-status reads, plus a manifest-scoped migration snapshot.

Database tables, model transport, task state transitions, medical rules, and contact routing are not exposed as independent caller APIs. This keeps final authority in one deep module instead of scattering it across each Skill, Tool, Command, Cron job, and adapter.

## Entry, initialization, and seven-Skill coordination

The route uses one custom `health_weixin` Platform Adapter as the only human health entry. The built-in Weixin path, Telegram, other human platforms, ordinary Agent commands, generic Tools, direct dispatch, and generic internal routes must not hold health credentials or a route that can reach the health core. If the health Plugin or adapter is absent, the health entry is absent; native or ordinary continuation cannot silently become a health fallback.

The adapter must receive each usable inbound envelope before the fixed native path can perform body deduplication, batching, or cursor advancement. It sends source metadata, missing-field facts, and a short-lived protected body handle to core. Core durably records each receipt and only advances the health cursor in the same confirmed transition as the corresponding admission/result state. Same-body observations are retained as separate sources. If re-delivery versus a deliberate repeat cannot be proved, core freezes health effects to at most one result and preserves the ambiguity; it does not silently discard the second observation or create a second effect. These requirements follow the fixed iLink/Hermes limits in [Evidence 21](21-unique-weixin-admission-routing-provenance-replay-results-20260820.md) and [Evidence 31](31-ticket-104-admission-routing-duty-composition-minimum-safety-20260822.md): cursor progress, native deduplication, batching, and `sendmessage` success are not business submission or owner-arrival proof.

Initialization is deterministic and owner-facing. `health-init` is a discoverable explanation and entry contract; it does not itself write health state and is not allowed to depend on a model deciding to load a Skill. Core prepares disclosure version, explicit owner consent, agreed first-hop model route, timezone, behavior and notification preferences, initial portrait, keys, local revision, and opaque current-head generation. Only a prepare -> conditional current-head commit -> finalize transition enables health. A cancellation, missing prerequisite, failed probe, or unknown commit leaves health disabled and clears pending health content according to the product contract.

After initialization:

- `health-steward` is the single coordinator for health turns.
- `health-settings` is the owner-facing control entry.
- `health-portrait`, `health-evidence`, `health-owner-inquiry`, and `health-literature` are internal, purpose-limited candidate producers.
- The four internal Skills have no database or delivery write authority and cannot complete tasks, send messages, change diagnosis, or reply directly.
- Core owns the task framework, final admission of evidence, portrait revisions, diagnosis revisions, control transitions, outbox, and delivery facts.

The seven Skills are therefore organized by role, not treated as seven independent business entry points. A model failing to call a Tool cannot bypass the adapter's pre-Agent health routing. A Skill being discovered, loaded, or named in a reply is not a usage fact; system-created minimal usage facts are recorded only when the runtime can prove the required Skill action occurred.

## Single authoritative state and object relationships

`health-core` owns one local protected state domain. It contains the semantic objects needed by the current TO:

- receipt and source provenance, initialization and current generation;
- one portrait with a versioned schema, current top status, six fixed first-level domains, and fixed base subtopics;
- three evidence classes: personal health evidence, authoritative general knowledge, and task-process evidence, all indexed to the same six domains;
- tasks, stages, assignees, acceptance criteria, approvals, withdrawals, and independent owner controls;
- diagnosis chains, safety facts, knowledge/rule versions, unknown outcomes, delivery attempts, outbox intents, status facts, migration, and deletion state;
- content-free audit events inside the same authority domain.

The portrait, tasks, and diagnosis revisions reference evidence cards by stable identity and version. They do not copy a second authoritative summary. Empty topics are explicit unknown. Adding or changing a base subtopic requires an owner-approved schema release. The model receives only the minimum current projection whose omission would change the decision; a small projection is not allowed to silently omit required evidence.

Health content is protected with standard authenticated-encryption primitives and keys delivered through a dedicated credential boundary. Ordinary Hermes Session/FTS/Memory, logs, cache, generic backup, model transcript, or external snapshot is not a health authority and must not become an untracked health copy. The current evidence proves these ordinary surfaces are not sufficient for the product contract and that the old sidecar had multi-file and object-model conflicts; the route therefore does not reuse them as a second authority. See [Evidence 30](30-ticket-103-current-partner-seven-skill-assets-managed-authority-20260822.md), [Evidence 32](32-ticket-105-managed-domain-state-tasks-controls-deletion-observation-migration-20260822.md), and [Evidence 33](33-ticket-106-first-hop-medical-governance-diagnostic-integrity-safety-revision-20260822.md).

### Local state plus opaque current head

The local SQLite state is the content authority; the external current head is not a second portrait. A single strongly consistent external item stores only opaque installation identity, business generation, digest of the finalized local revision, transition ID, active writer fence, and irreversible terminal-deletion marker. It contains no health content, owner/contact identity, credentials, or inferable medical values.

For a state change:

1. Core writes an invisible prepared local revision.
2. Core conditionally advances the current-head generation/digest/fence.
3. Core finalizes the same transition locally.

This is intentionally not described as a cross-store transaction. On an unknown remote response, core reads back by transition ID and accepts only the remote-selected digest. Until local finalized state and current head agree, health reads, writes, model work, and external effects stop or return “cannot confirm.” Old snapshots cannot become current merely because they contain a locally readable database.

The chosen current-head service is a narrow strongly consistent conditional-write resource (the historical candidate was a single-region DynamoDB item). Its account, region, resource identity, IAM, credential injection, cost, quota, and synthetic old-snapshot canary remain implementation and acceptance prerequisites. A local tombstone, WORM document, ordinary backup, or VM-local marker is not a substitute for the selected cross-instance fence.

## Tasks, daily review, controls, delivery, and business status

Core's TaskEngine is the only task authority. It owns purpose, assignee, stage, acceptance, four primary labels (`active`, `solved`, `failed`, `cancelled`), predecessor/successor links, allowed data, approval, and external-effect scope. Waiting, deferred, missing capability, one-step failure, and external-result unknown are separate facts; `sent`, Cron completion, or API acceptance cannot become `solved`.

Hermes Cron, startup recovery, or a Plugin tick only wakes core. The business review key is owner generation plus the owner's current local day and timezone. Core submits one review per day, records an unchanged review without notification, and on recovery re-evaluates the current day rather than replaying stale backlog. Business facts and encrypted outbox intents commit together; sending happens outside the transaction.

Delivery is layered and immutable:

1. health result formed;
2. business result submitted;
3. send attempted;
4. channel interface accepted, rejected, or unknown;
5. owner/contact delivery or reading observed, if actually provable.

An uncertain or possibly already-sent effect is not rewritten to failed and is not blindly retried. A task normally remains `active` with an attached unknown delivery fact until an owner-approved, bounded new attempt is allowed. A local client ID or `sendmessage` no-error result is not owner arrival.

Owner controls are independent commands: pause ordinary proactive support, stop new recording, cancel or adjust one task, withdraw an external-effect approval, and permanently delete. Pausing support does not cancel tasks. Stopping recording can still allow a temporary owner-initiated answer and minimum safety handling, but does not persist new personal evidence, portrait, diagnosis, safety event, or task and never backfills after recovery. Withdrawal blocks unsent effects and preserves in-flight unknowns. Delete applies to all controlled objects and replicas.

`StatusProjector` derives `active`, `abnormal`, or `cannot-confirm` from business facts: entry, initialization, keys/state, portrait/evidence, tasks/controls, review, delivery, model route, safety, question answering, diagnostic scope, and current head. It does not derive “active” from a live process, Gateway, Cron, or observer heartbeat. A separate content-free observer may append missing/recovered observations, but it cannot write health state, send health effects, or declare the product active. Core consumes observations and commits one transition notification per causal state change.

## Model, query, non-diagnostic answer, and medical route

The route does not use raw `ctx.llm` as the health contract because the fixed Hermes model surface can expose fallback, incomplete context, and incomplete terminal semantics that current health results cannot safely infer. The Plugin therefore requires a narrow `StrictHealthLLM` host interface that still uses the same Partner model configuration and owner-approved first-hop route. It is not a second provider configuration or gateway. See [Evidence 33](33-ticket-106-first-hop-medical-governance-diagnostic-integrity-safety-revision-20260822.md) and the fixed Hermes model references it cites.

Before each request, the interface records and compares provider, canonical base URL, API mode, requested model, configuration generation, and owner-consent fingerprint. Cross-first-hop fallback is disabled. The interface builds the final wire payload before capacity checking, explicitly sets output limits and strict structure, does not use tools, and returns response ID, requested and actual model, `completed`/`incomplete`/`failed`, incomplete reason, usage, and fallback facts. A capability profile binds a conservative common context lower bound, tokenizer or safe upper-bound method, fixed wrapper overhead, output reservation, and invalidation conditions. Static context configuration, rough token estimates, `stop`, non-zero text, or post-hoc usage cannot prove completeness.

The health path has only three allowed external directions: the owner-approved first-hop model, Weixin iLink, and the content-free current-head/observation resource. No owner-derived Web Search, MCP, ordinary Tool, arbitrary HTTP, or cache-miss URL fetch is allowed. A separate offline `KnowledgePublisher` may acquire and prepare general medical knowledge on a fixed owner-independent governance schedule, producing immutable releases with source, version, rights, Chinese-language status, review, and hash. It cannot read owner data or send messages. Missing or expired knowledge becomes a knowledge gap, not an owner-triggered network request.

Non-diagnostic answers are model candidates, never direct replies or portrait writes. The candidate must separate owner facts from general knowledge, cite current evidence/knowledge cards with source, time, and purpose, expose support/opposition/unknown/uncertainty and the permitted safety next step, and reference approved claim/template IDs. Core validates IDs and currentness, then deterministically renders text from approved claim atoms. Disease ranking, diagnosis labels, exclusion claims, or individualized medication adjustment have no non-diagnostic output atom and must transfer to the complete diagnostic path.

The initial diagnostic scope is a staged, not active, candidate: Chinese adults aged 18 or older, non-pregnant, with reliable recent height and weight measurements, limited to BMI-based overweight/obesity and degree classification. It is selected for a narrow input and deterministic local recomputation path, not because it is licensed, medically reviewed, implemented, or accepted. The scope stays staged until the actual content/translation/rule-use rights, frozen Chinese release, qualified medical review of the exact bundle hash, implementation compatibility, safety review, and real product acceptance all pass. No high-blood-pressure or other condition is a silent fallback. The candidate and its licensing/review boundary are grounded in [Evidence 25](25-named-diagnostic-scope-governance-and-full-chain-capabilities-20260820.md) and [Evidence 33](33-ticket-106-first-hop-medical-governance-diagnostic-integrity-safety-revision-20260822.md).

Every diagnostic attempt has three fail-closed gates:

1. **Before model:** verify initialization, controls, current head, first-hop consent, active bundle, complete minimum evidence, capacity, safety, and scope.
2. **After model:** accept only an authoritative `completed` result with approved structure, current evidence IDs, support/opposition/unknown, urgency, and scope values; independently recompute deterministic BMI facts.
3. **Before commit/release:** re-read generation, controls, evidence, bundle hash, first-hop consent, and deletion state, then commit the diagnostic revision and outbox together.

The result order is safety capability unavailable, danger escalation, danger unknown, out of scope, and in scope. Safety unavailable produces only the fixed non-diagnostic minimum-help result. Credible danger stops ordinary diagnosis and produces the fixed owner prompt plus a minimum contact alert candidate. Danger unknown does not become safe through keyword absence or a model guess. Out-of-scope does not produce a partial disease ranking. Only an in-scope result forms a diagnostic judgment. The medical source, safety, and template bundles are versioned; source withdrawal, expiry, owner correction, or professional-review invalidation first removes the dependent judgment from current and then creates a revision, downgrade, withdrawal, replacement, or one necessary correction notice.

## Support contact, deletion, and migration

The route uses one current support contact as a one-way, minimum-data recipient, never as a second owner or health-data viewer. Initialization discloses the contact, method, purpose, and minimum alert behavior; the owner explicitly approves it. Contact or route change invalidates the prior approval. No valid contact does not block owner safety output; it only makes the additional contact capability unavailable.

Only a current, reviewed, applicable danger can create an alert candidate. The minimum alert contains only the owner-recognizable address, event time, and fixed request to contact the owner and help seek urgent assistance. It contains no diagnosis, original message, symptoms, location, portrait, or evidence. Contact delivery has the same layered result levels as owner delivery. If the effect may have left the system, automatic retry is frozen; a necessary correction goes only once to the same current contact after rechecking approval and route. Unknown correction remains unknown and is not treated as withdrawal of an external copy.

Permanent deletion first freezes health effects, task progression, model work, and outbox, then conditionally advances the current head to an irreversible terminal generation. After terminal state is confirmed, core destroys the health data keys and clears all controlled local objects, indexes, tasks, approvals, controls, diagnoses, unknowns, outbox, backups, exports, migration staging, and other enumerated health copies. If terminal confirmation is unknown, health remains closed and the product does not claim that every old VM or external copy has been prevented. Later owner-initiated initialization creates a new blank installation; deleted state is never linked back.

Migration uses the same writer fence. The source freezes health effects and produces a semantic, hash-checked manifest covering the product/ADR/Skill release bundle, locked Hermes artifact and required patch, Plugin/core/adapter versions, disabled native entry assertions, service identities and ACLs, model-interface version, knowledge/safety/diagnostic bundles, local semantic state, current-head and observation resource identities, and all receipt, portrait, evidence, task, approval, control, diagnosis, unknown, delivery, review, deletion, and migration facts. Secrets are referenced and re-provisioned at the target; they are not placed in the manifest.

The target remains offline until the manifest, references, keys, owner consent, route, and bundles validate. One conditional writer-fence transfer gives the target authority. The source and every old VM then fail all health writes, model work, and sends because their fence is stale. A transfer result that is unknown leaves both ends unable to write or send; unknown in-flight effects are never replayed. Copying only documents, Skills, a profile directory, or a primary database blob is not a semantic migration.

## Authority and implementation matrix

| Responsibility | Unique authority in this route |
|---|---|
| C01 runtime/trust boundary | Partner Health Plugin + `health-core` contract probe |
| C02 initialization and entry closure | `health_weixin` adapter + core initialization state machine |
| C03 source, replay, admission | `health_weixin` + core receipt/cursor and ambiguity ledger |
| C04 protected state/current | core single-writer SQLite + opaque current head |
| C05 portrait/evidence | core schema releases and card/relation writer |
| C06 tasks | core TaskEngine |
| C07 local-day review/outbox/delivery | core ReviewEngine and delivery ledger |
| C08 first-hop model | `StrictHealthLLM` |
| C09 governed knowledge | offline `KnowledgePublisher` and immutable release registry |
| C10 diagnostic scope | core ScopeRegistry |
| C11 minimum-complete input and terminality | `StrictHealthLLM` plus core pre/post/commit gates |
| C12 safety and scope routing | core deterministic safety gate and approved rule bundle |
| C13 diagnostic revision | core diagnostic revision writer |
| C14 owner controls/delete | core control and terminal-generation protocol |
| C15 business status/observation | core `StatusProjector`; observer only appends content-free observations |
| C16 migration | core semantic manifest and current-head writer-fence transfer |
| C17 non-diagnostic answer | core candidate validator and deterministic claim/template renderer |
| K16-K18 contact chain | core contact approval/alert/correction/delete writer and Weixin delivery adapter |
| K19-K21 contact observability/portability/acceptance | core business facts, manifest, and layered verification |

Skills, ordinary Agent code, model outputs, delivery adapters, observers, and external services are not alternative writers for these rows.

## Representative owner journey

| Situation | Selected route and truthful result |
|---|---|
| Health not initialized and owner sends health-like text | The health adapter does not create health records, safety events, tasks, or retroactive facts. Only deterministic initialization can enter pending initialization. |
| Initialization completes | All disclosure, consent, route, timezone, controls, initial state, keys, and current-head transitions finalize together. Any failure/unknown leaves health disabled. |
| Owner says a new health fact | Adapter preserves the envelope; core admits a candidate evidence card, then separately commits portrait/task effects. Ordinary Session does not become a second record. |
| Same message is observed again | Both receipts remain; ambiguous replay produces at most one health effect and freezes further effect until resolved. |
| Daily review or restart | Scheduler wakes core; local-day ledger recomputes current state once. Recovery does not replay stale backlog. |
| BMI evidence is incomplete | No diagnostic judgment is formed; owner sees a truthful insufficient-information result. |
| BMI result passes all gates | Core commits one structured revision with exact evidence, knowledge, safety, template, and model capability references; rendered text is sent only from the committed outbox. |
| Danger, danger unknown, out of scope, or safety unavailable | The deterministic safety branch wins before ordinary diagnosis; it produces only the contractually allowed owner/contact result and minimum state. |
| Model route or capacity cannot be proven | Health work requiring that route stops. No fallback, partial result, silent truncation, or provider switch occurs. Local rights reads remain available if they do not need the unavailable route. |
| Weixin or contact result is unknown | Business submission and external delivery are separate. Unknown is preserved and automatic resend is frozen. |
| Owner pauses support, stops recording, withdraws approval, or deletes | Only the named control changes. Delete freezes effects, advances terminal generation, clears controlled copies, and requires a future blank initialization. |
| Old VM returns or migration is interrupted | Stale generation/fence prevents health write, model, and send. Unknown transfer leaves both sides stopped. |

## Validation boundary and dependencies

This HOW research chooses validation cuts; it does not execute them:

1. **Static and release validation:** fixed Hermes commit, Plugin/adapter/core artifacts, Skills, product bundle, schema, model interface, knowledge/safety/diagnostic bundles, disabled-native-entry assertions, and semantic manifest.
2. **Core synthetic validation:** in-memory adapter and synthetic owner data for initialization, six domains, three evidence classes, tasks, controls, safety branches, diagnosis, revisions, deletion, status, and migration commands.
3. **Local integration and fault validation:** real core process, Unix socket, SQLite/authenticated encryption, missing keys, crash between prepare/current-head/finalize, outbox uncertainty, ordinary-session leakage checks, and stale-fence rejection.
4. **Hermes contract validation:** Plugin/adapter load against the pinned Hermes artifact, no native fallback, partial-registration and callback failure handling, Gateway/core co-stop, and upgrade invalidation.
5. **Model contract validation:** synthetic payloads for first-hop identity, no fallback, final-wire capacity, strict structure, complete/incomplete/failed terminality, actual-model reporting, and unknown commit handling. No diagnostic scope becomes active before this passes.
6. **Knowledge and medical gates:** obtain actual use/rule/translation rights, freeze the Chinese bundle, have a qualified medical reviewer approve the exact content/rule/safety/template hash, and verify withdrawal/expiry behavior.
7. **External current-head validation:** synthetic CAS conflicts, timeout/readback, missing/recreated resource, credentials, terminal deletion, old VM, and source-to-target writer-fence canaries.
8. **Controlled real-interface validation:** synthetic non-health Weixin ingress/reply/send and replay/restart canaries first; only after explicit approval, real model, real Weixin, owner, and contact acceptance for the staged scope.

No step above has been performed. Deployment, implementation, external licensing, medical review, real model/Weixin use, and owner/contact acceptance remain downstream hard gates. Failure at any gate disables the affected health capability and must be reported as unavailable or cannot-confirm, never as active.

## Route decision

No current CAN fact requires a new CAN prerequisite ticket, and no new product promise or risk acceptance was introduced by this route. The chosen HOW is therefore:

**Partner Health Plugin -> pre-native `health_weixin` admission -> single `health-core` authority -> encrypted local state plus opaque strongly consistent current head -> strict same-Partner first-hop model port / offline governed knowledge -> deterministic safety and diagnostic gates -> transactional outbox -> layered Weixin/contact delivery -> business-fact status and fenced migration/delete.**

The route is selected for its single authority and truthful failure propagation. It deliberately accepts lower availability when the core, current head, model completeness, medical bundle, or delivery state cannot be proven. That tradeoff is consistent with the current TO/CAN boundaries and does not prove the route has been implemented or accepted.

### Sources

- Current product and stage authority: [`map.md`](../map.md), [`CONTEXT.md`](../../../CONTEXT.md), Ticket 100, Ticket 101, Ticket 102, and Ticket 108.
- Current CAN results: [Evidence 30](30-ticket-103-current-partner-seven-skill-assets-managed-authority-20260822.md), [Evidence 31](31-ticket-104-admission-routing-duty-composition-minimum-safety-20260822.md), [Evidence 32](32-ticket-105-managed-domain-state-tasks-controls-deletion-observation-migration-20260822.md), [Evidence 33](33-ticket-106-first-hop-medical-governance-diagnostic-integrity-safety-revision-20260822.md), [Evidence 34](34-ticket-107-support-contact-approval-alert-delivery-correction-deletion-20260822.md), and [Evidence 35](35-current-can-closure-after-seven-skill-contact-investigations-20260822.md).
- Fixed Hermes and iLink source boundaries are cited in Evidence 19, Evidence 21, Evidence 30, Evidence 31, Evidence 32, and Evidence 33. The fixed baseline is Hermes v0.20.0 at commit [`3c27eb6234bf91b8ceee9e9071591b31e9b148cb`](https://github.com/NousResearch/hermes-agent/commit/3c27eb6234bf91b8ceee9e9071591b31e9b148cb). The fixed iLink contracts are cited in Evidence 21, including the official Tencent `getUpdates`, message-type, and send-result references.
- The bounded current-head/generation candidate is documented in [Evidence 18](18-external-owner-generation-authority-candidates-20260818.md); this is a route dependency to re-prove with a synthetic canary, not a current deployment fact.
- Historical candidate inputs that were rechecked but not restored: Ticket 98 and ADR 0021. Their compatible constraints are re-expressed here; their current-authority status remains invalid until the new HOW Ticket is resolved.
