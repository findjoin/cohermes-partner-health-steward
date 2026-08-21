# Partner Hermes 自主健康管家

Type: spec
Status: historical
Authority: historical-input-only; the active planning authority is [`map.md`](map.md)

## Problem Statement

画像主人目前只有一个通过微信与她交流的 partner Hermes，但没有一个可靠的长期健康支持系统。单纯安装 Health Skill 只能影响某次对话，不能持续维护有依据的健康画像，不能根据画像自动创建和撤销关心任务，也不能保证定时任务在 fresh session、上下文压缩、资料更新、授权撤回或证据失效后仍使用当前状态。

用户需要的是一个自主健康管家：它能从画像主人的直接陈述、测量和本人转述的医生意见中维护紧凑健康画像；能从受控权威资料库获得参考；每天复核画像并生成即时或未来派生任务；任务到期后结合当前上下文重新调用 LLM 决定发送或跳过；能学习交互偏好；能与 Hermes memory 单向联动；同时具备可追溯、可暂停、可撤权、可删除、可导出和可验收的边界。

现有 v0.2 健康自治代码只是历史原型。它使用与 Hermes 相同的权限域、确定性派发器和已被本设计放弃的固定门禁，且没有在真实 partner 服务器完成部署与验收，因此不能直接作为生产实现。

当前仓库虽已具备 sidecar、画像、证据、资料、任务、授权、删除、审计和固定 Job 的主体能力，但最近一次同机上线准备仍为 `no-go`：真实微信入站尚未形成可验证收据，普通对话尚未接入主人控制工具，健康专用 LLM、资料下载、幂等微信发送和独立运维告警也尚未完成生产装配。规格必须覆盖这段真实运行链路，不能把库级测试或插件已加载误称为已部署。

## Solution

在 partner Hermes 所在服务器上部署独立 `health-sidecar`。sidecar 由受限服务账户持有加密 SQLite 健康档案、资料卡和原始资料缓存，通过不监听 TCP 的 Unix domain socket 向受限的 partner Hermes 提供最小能力。Hermes 核心保持不变。

partner Hermes 负责实时对话和调用 sidecar；sidecar 负责结构化校验、画像版本、证据簿、资料库、任务表、授权和审计。Hermes 只保留两个固定原生 Job：每日 04:00 的日检，以及每 5 分钟运行一次的到期任务派发器。派生任务保存在 sidecar，不各自创建原生 Cron。

实时对话只提出候选写入；日检维护画像、资料卡并创建派生任务，但不直接发送消息；派发器读取到期任务和当前健康快照，在 fresh session 中再次调用 LLM，输出 `send` 或 `skip`，并在发送前复核授权、任务、结论和资料的新鲜度。

系统通过画像主人身份、完整查看授权、主动触达暂停、无内容审计、加密存储、备份删除传播、运行熔断和完整上线验收控制风险。普通 Hermes memory 只接收档案指针和授权长期交互偏好的单向投影，不成为第二份健康数据库。

partner-only 微信适配层在认证后、消息合批前形成精确临时入站信封；独立的窄权限签发服务把真实 sender、message ID、UTC 时间和当前动作签入收据，sidecar 只持验证公钥。健康判断、健康相关轮次回答、日检和派发使用单独固定的健康模型配置；查看和导出由 sidecar 直接发往微信，不经过普通聊天 LLM 或普通会话历史。

独立 Monitor 不依赖 Gateway 或 LLM 做故障判断。它读取真实无内容审计、Job 心跳和受控时间，向操作者微信、系统日志、外部 dead-man 心跳和指定邮箱报告运行、故障与恢复。Gateway 故障时健康对话、LLM 和主动任务停止；Monitor 的职责仅是继续检测并发出故障信号，而不是维持健康管家业务。

## User Stories

1. As a 画像主人, I want Hermes to recognize health-related facts in my messages, so that my health profile is maintained without a special command prefix.
2. As a 画像主人, I want ordinary conversation to remain ordinary, so that unrelated chat is not copied into my health record.
3. As a 画像主人, I want my direct health statements to become traceable personal evidence, so that the profile does not rely on model impressions.
4. As a 画像主人, I want measurements to retain value, unit, observation time, and source message, so that they remain meaningful historical facts.
5. As a 画像主人, I want relayed medical advice to be labelled as my relay of a clinician's advice, so that it is not presented as a verified diagnosis.
6. As a 画像主人, I want each profile conclusion to cite evidence, so that I can understand why it exists.
7. As a 画像主人, I want the model-visible health profile to remain within 300 characters, so that it stays compact in every Hermes context.
8. As a 画像主人, I want the 300-character profile rebuilt by priority instead of cut mid-sentence, so that it stays coherent.
9. As a 画像主人, I want resolved, expired, and lower-priority conclusions removed or deferred before higher-priority conclusions, so that the summary preserves useful current state.
10. As a 画像主人, I want facts, tendencies, and unverified hypotheses distinguished, so that uncertainty is visible.
11. As a 画像主人, I want only facts and tendencies to create ordinary automatic tasks, so that hypotheses do not silently become assumed health facts.
12. As a 画像主人, I want an unverified hypothesis to create at most one completion question, so that uncertainty does not trigger repeated intervention.
13. As a 画像主人, I want newer direct statements to update older time-sensitive statements, so that the profile follows my current state.
14. As a 画像主人, I want measurements from different times to coexist, so that later measurements do not erase history.
15. As a 画像主人, I want persistent high-impact contradictions downgraded to an unverified hypothesis, so that Hermes asks rather than guesses.
16. As a 画像主人, I want acute-state conclusions to expire after 24 hours without a new direct confirmation, so that yesterday's discomfort is not treated as current indefinitely.
17. As a 画像主人, I want habit and goal conclusions to expire after 30 days without new evidence, so that stale routines do not keep generating tasks.
18. As a 画像主人, I want explicit communication feedback to take effect immediately, so that Hermes can adapt to how I prefer to interact.
19. As a 画像主人, I want an implicit interaction preference to require three independent same-direction behaviors within 60 days, so that a single event does not overfit the assistant.
20. As a 画像主人, I want interaction preferences to stop guiding proactive contact after 60 days without new evidence, so that old preferences do not become permanent.
21. As a 画像主人, I want silence, reply speed, and one-off emotion excluded as preference evidence, so that Hermes does not misread me.
22. As a 画像主人, I want the daily review to examine my current profile, evidence, task feedback, and relevant source cards, so that it can autonomously decide whether action is useful.
23. As a 画像主人, I want the daily review to be allowed to produce `no_action`, so that autonomy does not imply mandatory messaging.
24. As a 画像主人, I want the daily review to create completion questions, status follow-ups, care messages, and authorized low-risk reminders, so that tasks reflect the current profile.
25. As a 画像主人, I want a future task to store its purpose rather than stale final copy, so that the message is generated from current context at delivery time.
26. As a 画像主人, I want the dispatcher to evaluate due tasks every five minutes, so that future contact has a defined maximum scheduling granularity.
27. As a 画像主人, I want due tasks rendered in a fresh LLM session using a controlled health snapshot, so that old chat sessions are not treated as current truth.
28. As a 画像主人, I want the current health snapshot to include the task purpose, time window, evidence references, current profile, relevant conclusions, authorized preferences, and my latest three messages, so that delivery decisions have enough current context.
29. As a 画像主人, I want the latest three messages used ephemerally unless a relevant excerpt becomes evidence, so that the sidecar does not retain complete chat history.
30. As a 画像主人, I want due tasks skipped when their evidence, conclusion, authorization, or time window is no longer valid, so that stale care is not sent.
31. As a 画像主人, I want LLM and channel failures retried exactly once after 15 minutes, so that transient failures can recover without duplicate-message loops.
32. As a 画像主人, I want a failed retry to end as failed without automatic duplicate sending, so that uncertain delivery does not cause message floods.
33. As a 画像主人, I want unfinished tasks with the same purpose deduplicated, so that the system does not create repeated equivalent contact.
34. As a 画像主人, I want the same unanswered topic to wait at least 72 hours before another proactive contact, so that no response is not treated as an invitation to chase me.
35. As a 画像主人, I want proactive messages allowed at model-selected times, including night when justified, so that the assistant can adapt timing instead of following a fixed quiet period.
36. As a 画像主人, I want every night contact to record why that time was selected, so that timing remains reviewable.
37. As a 画像主人, I want a rolling 24-hour hard ceiling of 100 automatic messages, so that a task loop cannot produce unlimited contact.
38. As a 画像主人, I want the 100-message ceiling treated as a circuit breaker rather than a target, so that the system never tries to use the quota.
39. As a 画像主人, I want tasks blocked by the capacity ceiling to be re-evaluated instead of blindly queued for later, so that old messages are not released in a flood.
40. As a 画像主人, I want to pause all proactive health contact for a duration or indefinitely, so that I control interruptions without deleting my record.
41. As a 画像主人, I want Hermes to keep responding to my messages and maintaining evidence while proactive contact is paused, so that pausing does not disable support.
42. As a 画像主人, I want explicit resumption to be required after an indefinite pause, so that the system does not restart contact on its own.
43. As a 画像主人, I want to view my complete profile, evidence ledger, and unfinished tasks, so that I can inspect my own data.
44. As a 画像主人, I want to export my complete health record, so that my access does not depend on the operator's authorization.
45. As a 画像主人, I want to delete my health record, so that profile versions, personal evidence, and unfinished tasks are removed.
46. As a 画像主人, I want deletion to immediately destroy the record-specific encryption key and make backup copies unreadable, so that backup rotation does not preserve usable health content.
47. As a 画像主人, I want old backup copies physically removed within 30 days, so that deletion has a bounded completion period.
48. As a 画像主人, I want only content-free deletion audit metadata retained, so that deletion is provable without retaining my health text.
49. As a 画像主人, I want to grant a specified viewer complete read access and later revoke it, so that sharing is explicit and reversible.
50. As a 画像主人, I want revocation to immediately stop future reads and weekly reports, so that server administration or relationship status does not substitute for consent.
51. As an authorized viewer, I want read-only access to profile, evidence, task records, reports, and access audit, so that I can review the health steward without altering its facts.
52. As an operator without content authorization, I want to see paths, service health, job status, and content-free audit, so that I can maintain the system without reading health content.
53. As an authorized viewer, I want a Sunday 10:00 profile-difference report, so that I can review material weekly changes without a third native Cron.
54. As an authorized viewer, I want the weekly report to summarize changes and link to traceable detail rather than copying the full record, so that reports do not become duplicate health archives.
55. As an operator, I want an external content-free alert after two daily-review failures or 15 minutes without dispatcher heartbeat, so that runtime failure is visible promptly.
56. As a 画像主人, I want medical answers based first on unexpired source cards, so that the assistant uses reviewed material when available.
57. As a 画像主人, I want on-demand retrieval restricted to approved authorities, so that arbitrary web pages do not become medical evidence.
58. As a 画像主人, I want unavailable whitelist evidence reported as unavailable, so that Hermes does not pretend a claim was verified.
59. As a 画像主人, I want external medical documents treated only as data, so that instructions embedded in pages or PDFs cannot call tools, modify my profile, or create tasks.
60. As a 画像主人, I want source updates to influence questions and task premises but never automatically become my personal facts, so that general medical guidance is not confused with my condition.
61. As an operator, I want source cards tagged by fixed categories with normalized values, so that the library remains searchable without uncontrolled taxonomy growth.
62. As an operator, I want raw source cache, metadata index, document size, excerpt size, scan rate, and retention bounded, so that storage usage remains predictable.
63. As an operator, I want referenced source evidence preserved while referenced, so that storage cleanup never breaks traceability.
64. As an operator, I want health data stored on the partner Hermes server rather than on the Windows development machine, so that autonomous jobs remain available continuously.
65. As an operator, I want partner Hermes and health-sidecar to use separate restricted service accounts, so that ordinary Hermes execution cannot directly open the health database.
66. As an operator, I want Hermes and sidecar to communicate through a private Unix socket with no TCP listener, so that the health interface is not exposed to the network.
67. As an operator, I want partner Hermes to remain upgradeable without a private core fork, so that Hermes updates and rollback remain tractable.
68. As an operator, I want only the partner Hermes deployment changed, so that default Hermes and unrelated services are unaffected.
69. As an operator, I want a single one-way memory projection containing only the archive pointer and authorized durable interaction preferences, so that Hermes memory remains useful without duplicating health data.
70. As an operator, I want every action-producing LLM response schema-validated and failed closed, so that malformed model output cannot partially write, schedule, or send.
71. As an operator, I want task, authorization, view, deletion, and send operations retained as content-free audit for 90 days, so that behavior is reviewable without storing duplicate health text.
72. As an operator, I want deployment blocked until the full acceptance suite passes, so that an installed Skill or running prototype is not mistaken for a delivered health steward.
73. As a 画像主人, I want every authenticated Weixin message independently classified in a fresh health-model call, so that health facts can be recognized without inheriting an old chat session.
74. As a 画像主人, I want failed health classification to leave ordinary conversation available, so that a health subsystem fault does not silence Hermes.
75. As a 画像主人, I want a classification failure marked as `记录处理中`, a successful retry marked as `已补录`, and a second failure marked as `本次未记录`, so that record state is honest.
76. As a 画像主人, I want the trusted inbound envelope retained for at most ten minutes and retried at most once, so that recovery does not create a shadow chat archive.
77. As a 画像主人, I want health processing disabled until I explicitly opt in, so that server ownership or relationship status cannot substitute for my consent.
78. As a 画像主人, I want only my first trusted message after opt-in to bind the preconfigured owner identity, so that another sender cannot claim my record.
79. As a 画像主人, I want to stop health recording without deleting the existing record, so that I can suspend classification and new writes while keeping view, export, resume, and deletion rights.
80. As a 画像主人, I want stop-recording to cancel pending classification retries and derived tasks and pause proactive contact, so that processing really stops.
81. As a 画像主人, I want resuming health recording to require an explicit current-turn action, so that processing cannot restart implicitly.
82. As a 画像主人, I want view and export requests tied to my authenticated current turn, so that a model cannot replay an old request.
83. As a 画像主人, I want grant, revoke, pause, resume, and stop-recording actions tied to the exact target, duration, and current message, so that Hermes cannot alter their meaning.
84. As a 画像主人, I want permanent deletion to require a second confirmation within ten minutes, so that a single misunderstood utterance cannot destroy my record.
85. As a 画像主人, I want deletion to cover profile, evidence, versions, tasks, reports, grants, and memory projection, so that no active health copy remains in the steward.
86. As a 画像主人, I want deletion to leave Weixin and ordinary Hermes chat history untouched, so that the deletion boundary is explicit rather than falsely broad.
87. As a 画像主人, I want to know that already delivered or exported copies cannot be recalled, so that deletion is not represented as retroactive erasure.
88. As a 画像主人, I want my JSON export delivered as a Weixin attachment from a strict-permission temporary file, so that export does not pass through ordinary chat generation.
89. As a 画像主人, I want export plaintext created only on private tmpfs and removed after sending, with cleanup no later than 24 hours, so that temporary files do not become a durable copy.
90. As an authorized viewer, I want full views delivered directly from sidecar without ordinary chat LLM processing or session persistence, so that authorized access does not create an uncontrolled duplicate.
91. As an authorized viewer, I want export forbidden, so that the owner's grant remains read-only rather than becoming redistribution authority.
92. As a 画像主人, I want full health content sent to a model only after I explicitly request analysis in the current turn, so that viewing alone does not disclose it to a provider.
93. As a 画像主人, I want the health model provider and model configured independently from the partner chat model, so that later chat-model changes do not silently change health-data processing.
94. As a 画像主人, I want the initially selected current partner provider explicitly recorded as an accepted third-party processor, so that model provenance is not overstated.
95. As a 画像主人, I want only health-related turns to receive my current compact profile and relevant references, so that ordinary conversation does not expose health context.
96. As a 画像主人, I want the health turn to use the post-write current profile, so that an accepted update is not followed by stale advice.
97. As a 画像主人, I want the latest three ordinary messages kept only in memory for at most 72 hours and cleared on restart, so that short-term context is bounded.
98. As a 画像主人, I want Hermes to say `正在核验资料` when a health answer lacks a fresh source card, so that a delayed answer is explained.
99. As a 画像主人, I want whitelist retrieval given at most 20 additional seconds, so that source checking cannot indefinitely block the conversation.
100. As a 画像主人, I want unavailable or timed-out verification stated explicitly, so that neither model memory nor an unverified source is presented as authority.
101. As a 画像主人, I want a health-action tail marker only when the sidecar actually changed profile/evidence or completed a control action, so that tool use is visible without false positives.
102. As a 画像主人, I want no health tail marker on ordinary chat or rejected/no-op candidates, so that the marker remains meaningful.
103. As a 画像主人, I want one high-entropy recovery code shown only to me, so that I can recover from a lost Weixin sender identity without giving the administrator content authority.
104. As a 画像主人, I want the recovery code stored only as a verifier, rotated after use, and never available to the viewer or administrator, so that recovery cannot become a standing bypass.
105. As a 画像主人, I want identity recovery to fail closed if both my old identity and recovery code are unavailable, so that convenience does not override ownership.
106. As an operator, I want the receipt signer isolated from sidecar data keys and inaccessible to health tool subprocesses, so that a compromised tool cannot forge owner actions or decrypt health data.
107. As an operator, I want Weixin delivery to use a stable delivery key and content-free ledger, so that retries cannot duplicate an uncertain send.
108. As an operator, I want the partner Weixin adapter pinned to an accepted Hermes version and revalidated on every Hermes upgrade, so that an upstream change cannot silently break identity or idempotency.
109. As an operator, I want the first runtime failure alert immediately, repeated failure reminders no more often than every six hours, and one recovery alert, so that failures are visible without alert flooding.
110. As an operator, I want operational alerts excluded from the owner's 100-message health-contact ceiling, so that a circuit breaker does not hide a system failure.
111. As an operator, I want a content-free external HTTPS dead-man heartbeat, so that an independent service can detect whole-host or network loss.
112. As an operator, I want whole-host or network-loss alerts sent to a separately configured email address, so that an outage is visible when local Weixin and syslog cannot send.
113. As an operator, I want Monitor behavior to remain deterministic without LLM access, so that Gateway failure can still be detected even though health conversations and tasks stop.

## Implementation Decisions

- The production design consists of one partner Hermes instance and one `health-sidecar` on the same Linux server. The Windows workspace is a development and documentation location only.
- The partner Hermes process runs as restricted account `hermes-partner`; the sidecar runs as restricted account `health-sidecar`. Before migration, deployment work must read-only verify the actual partner service account, profile paths, unit configuration, channel state, and current runtime.
- The sidecar owns encrypted SQLite state, encrypted source cache, per-record data-encryption keys, source metadata, task state, and content-free audit. Hermes does not receive direct file or key access.
- The sidecar exposes a local Unix domain socket owned by the sidecar and accessible only to the partner Hermes account. It does not bind a TCP port or expose a public API.
- Hermes core source is not modified. Integration uses partner-only configuration, a version-pinned partner Weixin adapter/plugin, two native fixed Jobs, and the sidecar socket contract. The accepted Hermes commit/version is a deployment invariant; every Hermes or health-model change requires the affected integration and Linux acceptance suites to pass again. If native extension points cannot satisfy the contract, work remains in acceptance and does not introduce a private core patch.
- The partner Weixin adapter observes the authenticated real-format event after channel admission and before text batching. It forms a temporary envelope containing the exact sender ID, message ID, UTC event time, channel/profile identity, message kind, and necessary plaintext. A batched message cannot borrow only the first event's ID or time as evidence for later text.
- A narrow receipt-signer service is the only holder of the Weixin action-signing private key. Only the partner Gateway main process can request a signature; plugin tool subprocesses cannot read the private key. The receipt binds action, sender, target, message ID, UTC time, and action-specific parameters such as pause deadline. The sidecar holds only the public verification key; this key is separate from all health-data encryption keys.
- The initially approved health model may use the current partner provider, including a third-party provider explicitly accepted by the user, but provider, endpoint, model ID, and relevant privacy mode are snapshotted in a separate health-model configuration. They never silently inherit later partner-chat configuration changes and are not described as official or direct unless independently verified.
- Each health classification, health-related reactive answer, daily review, due-task render, and explicitly requested full-record analysis uses a fresh health-model invocation with only the allowed structured input. A fresh call does not inherit ordinary Hermes chat history.
- Existing v0.2 autonomy, guard, dispatcher, and integration code is prior art only. It is not patched in place or deployed as production. Its SQLite, audit, authorization, deletion, and fixed-Job experience may inform the new implementation where it matches this spec.
- The sidecar is the only authoritative store for the health profile, profile versions, conclusions, evidence ledger, source cards, authorization, derived tasks, task decisions, and deletion state.
- Ordinary Hermes memory stores only a one-way projection: a health-record pointer and authorized durable interaction preferences. It cannot write back into sidecar state, and deletion removes the projection.
- Deployment preconfigures the expected owner Weixin sender identifier, but this alone neither binds the record nor grants consent. Health classification and record creation remain disabled until the owner explicitly opts in; only her first trusted message after opt-in can complete binding. The operator, server administrator, and relationship owner are not automatically the profile owner or viewer.
- Every authenticated bound-owner Weixin message is independently classified by a fresh health-model call with a structured result. The classification has a 15-second pre-response budget. A health fact, measurement, owner-relayed clinician advice, explicit preference, or owner control request may create a candidate; ordinary chat creates no candidate and its trusted plaintext is discarded after the bounded recent-message window.
- Classification failure does not block the ordinary Hermes reply. The first failure shows `记录处理中`; the exact trusted inbound envelope may remain encrypted/in memory for at most ten minutes and is retried once. Retry success reports `已补录`; a second failure reports `本次未记录` and destroys the retry material. These reactive status messages do not count against proactive-contact capacity.
- Candidate writes are structured model outputs. The sidecar validates identity, action role, schema, evidence links, lengths, state transitions, authorization, deduplication, and current version before atomically committing a new immutable profile version.
- Action-producing output fails closed. Missing fields, parsing failure, invalid evidence, unauthorized role, illegal state transition, or profile-summary overflow means no write, no schedule, or no proactive send. Reactive conversation may continue, but the assistant cannot claim that a failed action was saved.
- A health-action tail marker appears only after the sidecar confirms an actual profile/evidence change or a completed owner control action. Ordinary chat, rejected candidates, model-only reasoning, failed tool calls, and no-op writes have no health marker.
- `profile_summary_zh` counts Chinese characters, Latin letters, digits, spaces, and punctuation and must contain no Markdown. It is hard-limited to 300 characters at write and context-injection boundaries.
- A profile exposes at most eight active conclusions to the compact summary: up to two active states, three habits/goals, two interaction preferences, and one task context. Overflow handling first removes resolved or expired conclusions, merges synonymous values in the same field, and defers the lowest-priority conclusion that has no live task dependency. Mid-string truncation is forbidden; remaining overflow rejects the write as `summary_overflow`.
- Conclusions have status `fact`, `tendency`, or `unverified_hypothesis`. Facts and tendencies may create automatic tasks. An unverified hypothesis may create only one profile-completion question.
- Personal evidence includes direct owner statements; measurements with type, value, unit, and observation time; and clinician advice relayed by the owner and labelled as owner-relayed. A source card or model inference is not personal evidence.
- Evidence excerpts preserve only the necessary original span, maximum 300 characters, plus channel message ID and UTC timestamp. Outside admitted evidence, at most the latest three ordinary owner messages are held in process memory for at most 72 hours and are cleared on restart; they are never persisted as sidecar profile data.
- General time-sensitive statement conflicts prefer the newer direct owner statement. Measurements coexist as time-indexed observations. Persistent high-impact conflicts become an unverified hypothesis and generate at most one clarification question.
- When evidence does not specify a shorter validity period, an acute-state conclusion expires 24 hours after the last direct confirmation, a habit or goal expires 30 days after the last evidence, and an interaction preference stops guiding proactive contact after 60 days without new preference evidence. Measurements remain historical observations rather than current state.
- Explicit interaction feedback takes effect immediately. An implicit preference requires at least three independent same-direction owner behaviors within 60 days. Silence, reply speed, and one-off emotion are excluded.
- Daily review runs at 04:00 in the profile owner's timezone, default `Asia/Shanghai`. It reviews current profile, evidence, task feedback, and relevant source cards and produces `no_action` or candidate derived tasks.
- Derived tasks may represent a profile-completion question, status follow-up, care message, authorized low-risk reminder, immediate conversation, or future contact. Diagnosis, medication change, and external third-party notification are not task types.
- Future tasks persist purpose, evidence references, time window, validity, deduplication key, and policy constraints, not final message copy.
- Task lifecycle is `candidate`, `scheduled`, `due_for_render`, `sent`, `skipped`, `failed`, or `cancelled`, with `capacity_exhausted` recorded as a skip/failure reason. Invalidated conclusions, superseding evidence, authorization revocation, pause, deletion, and expired time windows cancel or skip before send.
- There are exactly two native health Jobs: daily review and due-task dispatcher. No derived task creates or modifies a native Cron Job.
- The due-task dispatcher runs every five minutes. Five minutes is the scheduling and delivery polling granularity, not a promise of exact-to-the-second delivery.
- A due Job starts a fresh agent session. The effective context remains normal Hermes native context plus the fixed Job prompt plus a controlled health snapshot. Native Hermes context can affect language style and tool behavior but is not authoritative health state.
- The health snapshot contains task purpose, time window, evidence IDs, current 300-character profile, relevant conclusions, authorized interaction preferences, and the latest three messages from the same owner sender identifier. The snapshot is the sole authority for whether the current health premise still holds.
- Due rendering can output only `send` or `skip`. It cannot modify the profile, source cards, task plan, or native Cron. A skip returns the matter to the next daily review rather than planning inside the dispatcher.
- Before rendering, the dispatcher revalidates current authorization, pause state, claim validity, source freshness, task deduplication, contact capacity, and time window. A stale or downgraded premise skips the task.
- A model or channel failure is retried exactly once after 15 minutes. A second failure marks the task failed without blind duplicate sending; the next daily review may re-evaluate the purpose.
- Daily review failure is retried once after 10 minutes. A second failure produces no new tasks for that day, records the failure, and appears in the next operational report.
- A monitor outside the health planning flow alerts the specified operator without health content after two daily-review failures or 15 minutes without a successful dispatcher heartbeat.
- The independent Monitor reads real content-free audit and Job heartbeat state without invoking an LLM. The first active fault alerts immediately, an unresolved fault is reminded at most every six hours, and recovery emits exactly one recovery alert. Its channels are the specified operator Weixin identity, system log, a content-free external HTTPS dead-man heartbeat, and a separately specified outage-alert email. Gateway or whole-host failure stops health LLM work; the Monitor only detects and reports the loss, and the external dead-man service covers cases where the local host cannot transmit.
- Operational fault and recovery messages are not health contact and do not consume the owner's rolling 100-message capacity.
- Contact capacity is a rolling-24-hour hard limit of 100 automatic messages. It is a circuit breaker, never a target or quota. Each proactive contact requires a purpose, evidence reference, and deduplication key.
- The same purpose cannot repeat while an unfinished task exists. An unanswered topic cannot be proactively repeated for at least 72 hours; daily review may select a longer delay or no repeat and must record its rationale.
- There is no fixed quiet period. The model chooses timing within the task window, but every night contact records a reviewable timing rationale.
- When capacity is exhausted, no message is sent and old messages are not queued for automatic catch-up. The next daily review may create a new task only if evidence and timing still make it useful.
- The profile owner can pause all proactive contact for a fixed duration or indefinitely. Pause cancels waiting proactive tasks but does not block reactive replies or evidence maintenance. Explicit owner action is required to resume an indefinite pause.
- Health recording consent is separate from proactive-contact pause. `recording_stopped` disables new health classification and writes, cancels pending classification retries and derived tasks, and pauses proactive contact while retaining the encrypted record for owner view, export, explicit resume, or deletion. Resume requires a verified current-turn owner action.
- Full viewer access requires a one-time explicit owner grant naming the single preconfigured viewer sender ID and covering profile, evidence ledger, task records, and profile-difference reports. No arbitrary additional viewers are supported in the first release. Revocation immediately blocks future content reads and report delivery. Previously delivered copies cannot be recalled.
- View/export, grant/revoke, pause/resume, stop/resume recording, recovery, and deletion are accepted only with a fresh action-bound receipt from the current authenticated owner turn. Grant/revoke binds the target; finite pause binds the normalized deadline. Permanent deletion requires a second action-bound owner confirmation within ten minutes.
- The profile owner always retains full self-view and export rights. The viewer is read-only and cannot export. Server administrator status alone reveals only paths, service state, and content-free audit, not health content.
- Complete owner/viewer views are projected directly from sidecar to Weixin and are not inserted into the ordinary chat LLM prompt or ordinary Hermes session history. Full content enters the approved health model only when the authorized requester explicitly asks in the current turn for model analysis, and only the required scope is supplied.
- Owner export is a JSON Weixin attachment. Plaintext is created only in a strict-permission private tmpfs location, removed after confirmed send, and swept no later than 24 hours. It does not pass through ordinary chat generation.
- Owner identity recovery uses either a verified transfer from the old identity or a one-time high-entropy recovery code shown only to the owner. The sidecar stores only a verifier/hash and rotates it after use. Administrators and viewers cannot rebind; loss of both the old identity and recovery code fails closed.
- Every successful profile write creates an immutable profile version. The current profile is the latest effective version. Weekly difference reports compare adjacent versions.
- Daily review creates a weekly profile-difference report as a derived task due Sunday 10:00 in the owner's timezone. It is not a third native Job. The report includes profile changes, evidence additions/revocations, task sent/skipped/failed events, authorization/deletion operations, and daily-review failures, with references rather than copied full content.
- Approved source origins are the National Health Commission of China, China CDC, WHO, US CDC, NICE, and vetted medical-specialty clinical guidelines. Automated discovery, retrieval, refresh, and tagging remain inside this whitelist.
- Source cards have six fixed tag categories: topic, symptom/behavior, target population, evidence type, region/language, and freshness. Values are normalized against existing synonyms; only an unmergeable value creates a new normalized value. Categories do not grow dynamically.
- Current-reference review intervals are seven days for public-health alerts, 180 days for clinical guidelines, and 365 days for general health education. A shorter source-declared validity period overrides these defaults.
- On-demand health questions use a current source card first. If none fits, Hermes first sends `正在核验资料` and gives the production source fetcher at most 20 additional seconds to retrieve a whitelist source and create a card. If the source is unavailable or times out, the response explicitly states that verification was unavailable and does not expand to arbitrary web sources or treat model memory as authority.
- Source documents and extracts are untrusted data. Embedded text cannot issue instructions, call tools, write sidecar data, or create tasks. Source updates cannot become personal facts; they may invalidate a task premise or create one completion question for a personal evidence gap.
- The raw-document cache is limited to 200MB; index and metadata are limited to 100MB; an individual raw document is limited to 5MB; a retained evidence excerpt from a source is limited to 8KB.
- Each daily review downloads at most 20 raw documents, one at a time, with at least one minute between downloads from the same domain. Excess candidates remain queued for later review.
- At raw-cache capacity, cleanup removes the least-recently-used raw content that is not referenced by a current conclusion or unfinished task. URL, version hash, and key excerpt remain. Referenced content is not deleted to admit a new download; the new raw download is rejected if necessary.
- Evidence supporting a current profile conclusion is retained for the conclusion's lifetime plus 180 days after expiry. Task creation, delivery, revocation, and content-free audit logs are retained for 90 days. A source-card reference remains while any retained object cites it. Owner deletion overrides ordinary retention.
- Health data and backups are encrypted at rest. Keys do not enter prompts or ordinary Hermes configuration. Encryption protects storage and backups but does not claim to defeat an active server root administrator.
- Each owner health record uses a distinct encryption key. Confirmed deletion immediately destroys the key and removes active profile, profile versions, personal evidence, tasks, reports, grants, delivery state, and memory projection. Encrypted backup remnants become unreadable immediately and are physically purged within 30 days. Content-free deletion audit remains; Weixin/ordinary Hermes chat history and copies already delivered or exported are outside this deletion boundary.
- All stored timestamps are UTC. Owner-facing schedules and time windows use the explicit owner timezone, default `Asia/Shanghai`; the system does not infer timezone from conversational location.
- Health-related reactive turns are diverted before ordinary text batching. Only the independently pinned health-answer invocation receives the current compact profile, relevant evidence IDs, and relevant source-card summaries as ephemeral input through a one-time turn-bound receipt; the turn and projection do not enter the ordinary chat model or ordinary session history. Once classification has confirmed the turn is health-related, later admission, context, source, or answer failure and timeout fail closed on the health route and cannot fall back to ordinary chat. If the current turn admitted a write, the health answer uses the newly committed current profile rather than the pre-write snapshot. Ordinary turns receive no health projection.
- Weixin sends use a stable sidecar-derived delivery key and content-free delivery ledger. An adapter without an idempotent `send_once` contract fails closed for retryable health delivery. The adapter is tied to the accepted Hermes version and must be revalidated before an upgrade is activated.
- The application has no RMB-denominated daily LLM cost cutoff. Message, task, retry, source-fetch, and storage bounds still apply.

## Testing Decisions

- Tests assert externally observable behavior rather than SQLite tables, private helper functions, prompt wording, or implementation-specific class structure.
- The primary runtime acceptance seam starts with a real-format authenticated partner Weixin event or a real fixed-Job tick. It passes through the production partner adapter/plugin, pre-batch trusted envelope, receipt signer, fresh health-model port, Unix socket, sidecar, source-fetch port, and idempotent Weixin delivery port. Tests observe only Weixin-visible replies/attachments/tail markers, authorized sidecar views, task disposition, delivery outcome, and content-free audit.
- The primary runtime seam substitutes only controlled external boundaries: health-model result, whitelist HTTP response, Weixin network acknowledgement, time, and cryptographic key material. It does not bypass the production adapter, signer, plugin handlers, protocol, authorization, sidecar state machine, delivery ledger, or view/export renderer.
- A second independent operations seam starts with the real audit file format, real Job heartbeat records, controlled time progression, and external heartbeat state. It passes through the production Monitor and observes operator Weixin alerts, system-log events, external dead-man heartbeat, outage email, reminder cadence, and recovery. It proves that no LLM is required for detection and that Gateway failure is reported rather than misrepresented as continued service.
- Deterministic tests use a fake clock and controlled LLM, source-fetch, Weixin-network, email/dead-man, and key-management adapters. This makes 15-second classification, 20-second source fetch, 10-minute retry/confirmation, 5-minute polling, 10-minute daily retry, 15-minute send retry, 6-hour fault reminder, 72-hour context/backoff, rolling 24-hour capacity, 24-hour export cleanup, and 30-day backup deletion reproducible.
- The real Hermes integration suite verifies that the production partner adapter/plugin loads against the pinned Hermes version, the main Gateway alone can reach the signer, tool subprocesses cannot read its private key, both fixed Jobs invoke fresh health-model sessions, only the two allowed health Jobs exist, derived tasks do not create Cron, and Hermes core remains unmodified.
- Existing autonomy tests provide prior art for authorization, task lifecycle, deduplication, deletion, audit, and fail-closed state changes. Existing Hermes integration tests provide prior art for loading a partner plugin/adapter and exercising Cron integration. Existing fixed health-guard tests are not behavior requirements because the custom gate was explicitly excluded.
- Profile tests cover character counting, no-Markdown output, category caps, synonym merging, priority deferral, overflow rejection, immutable versions, evidence citations, status classification, conflict handling, and category-specific expiry.
- Evidence tests cover direct owner statements, structured measurements, owner-relayed clinician advice, non-owner rejection, excerpt minimization, source message linkage, latest-three-message ephemerality, and ordinary-chat exclusion.
- Inbound tests cover post-auth/pre-batch event identity, multi-message batches, explicit consent before binding, first-trusted-message binding, fresh per-message classification, 15-second non-blocking timeout, ten-minute one-retry envelope retention, and the three user-visible processing states.
- Recording-control tests cover stop-without-delete, cancellation of retries/tasks, proactive pause, retained view/export, explicit resume, no classification while stopped, and separation from ordinary proactive-contact pause.
- Interaction preference tests cover immediate explicit feedback, three independent same-direction behaviors within 60 days, exclusion of silence/reply speed/one-off emotion, and 60-day expiry.
- Daily-review tests cover `no_action`, allowed task types, evidence-linked rationale, immediate and future tasks, no direct message send, source refresh prioritization, source-scan throughput, and one retry after 10 minutes.
- Dispatcher tests cover current-snapshot rendering, `send` and `skip`, evidence/source/authorization revalidation, no profile or source writes, no Cron creation, one retry after 15 minutes, uncertain-delivery duplicate prevention, and five-minute polling.
- Weixin-delivery tests cover stable delivery keys, repeated acknowledgements, success followed by local-state failure, network uncertainty, no non-idempotent fallback, content-free ledger state, and fail-closed behavior under an unaccepted Hermes adapter version.
- Contact-governance tests cover deduplication, one unfinished task per purpose, 72-hour unanswered-topic backoff, night timing rationale, pause/resume, rolling-24-hour count, `capacity_exhausted`, and no catch-up flood.
- Authorization tests cover owner self-view/export, viewer grant, viewer read-only access, revocation, operator metadata-only access, weekly report suppression after revocation, and access audit.
- Owner-control tests cover action/target/duration/message/time binding, ten-minute second deletion confirmation, replay rejection, one configured viewer, viewer export denial, old-identity transfer, one-time recovery-code rotation, administrator/viewer rebind denial, and fail-closed unrecoverable identity loss.
- Privacy-path tests prove that full view/export bypasses the ordinary chat LLM and session history, ordinary turns receive no health context, only the pinned health-answer invocation receives the bounded current projection, post-write reasoning uses the new profile, and model analysis of a full view requires an explicit current-turn request.
- Health-model configuration tests prove the accepted provider/endpoint/model/profile snapshot is separate from partner chat configuration, every response reports the exact accepted model ID, health answers have no ordinary history, tools, or provider fallback, ordinary chat-model changes do not alter it, and health-provider changes require explicit configuration plus revalidation.
- Tail-marker tests prove the marker appears only after confirmed sidecar mutation/control completion and is absent for ordinary chat, rejected candidates, failures, and no-op writes.
- Source-library tests cover the exact whitelist, source-card precedence, unavailable verification, six fixed tag categories, synonym normalization, freshness intervals, prompt-instruction isolation, personal-fact separation, cache limits, LRU cleanup, reference preservation, and download refusal when necessary.
- Reactive source tests cover `正在核验资料`, the 20-second additional budget, successful card admission, timeout/unavailable wording, and prohibition on arbitrary-web or model-memory substitution.
- Deletion tests cover active-record deletion, task cancellation, profile-version removal, memory-projection removal, immediate per-record key destruction, content-free deletion audit, and physical backup purge by day 30.
- Export tests cover JSON attachment shape, owner-only access, strict tmpfs permissions, deletion after confirmed send, 24-hour orphan cleanup, and absence from ordinary LLM/session history.
- Process-boundary tests verify separate service accounts, socket ownership and permissions, absence of TCP listeners, denial of direct database access to partner Hermes, and unchanged default Hermes/unrelated services.
- Operational tests cover dispatcher heartbeat loss, daily-review failures, immediate first alert, six-hour reminder ceiling, one recovery alert, operator Weixin and syslog delivery, external heartbeat loss, outage email, no health content in any alert, encrypted backups, restore behavior before deletion, and undecryptability after key destruction.
- Acceptance requires every behavior named in `上线验收门槛` to pass in the primary seam. Because the owner has only the active DMIT Linux host, the thin Hermes integration smoke uses a two-phase same-host production canary: phase A completes backup, offline regressions, immutable install, and static isolation checks without stopping the legacy partner; phase B starts only after explicit interruption-and-rollback authorization, stops only the legacy partner, starts sidecar then restricted partner, and immediately rolls back on any critical failure. Local regressions alone do not authorize phase B, and the result must never be described as non-production acceptance.

## Out of Scope

- A custom deterministic danger-signal or medication gate outside normal Hermes behavior.
- Medical diagnosis, prescribing, medication changes, emergency exclusion, or replacing professional care.
- Sharing health content with anyone other than the owner, the single explicitly authorized viewer, and the separately accepted health-model provider for the minimum approved operation.
- Automatically following the partner chat model/provider when it changes, or claiming the accepted third-party provider is an official/direct OpenAI service without separate evidence.
- Supporting arbitrary additional viewers, administrator-initiated owner rebind, recovery without the old identity or recovery code, or viewer export.
- Creating one native Cron Job per derived task or allowing a Cron execution to recursively manage Cron.
- Modifying Hermes core, maintaining a private Hermes fork, or deploying the old v0.2 core patch.
- Deploying the old fixed health guard or deterministic no-LLM dispatcher as production behavior.
- Storing full chat history, full webpage archives without limits, or complete health content in ordinary Hermes memory.
- Sending a full view/export through the ordinary chat LLM, writing it to ordinary Hermes session history, or automatically asking a model to analyze it.
- A public or remote sidecar API, hosting the sidecar on the Windows development machine, or sharing one health sidecar across unrelated Hermes profiles.
- Automatically inferring owner timezone, identity, consent, or health facts from server ownership, relationship status, silence, or arbitrary web content.
- Continuing health conversation, LLM classification, daily review, or proactive dispatch while the Gateway or whole host is unavailable; independent monitoring detects and reports such failure but does not replace the Gateway.
- An application-level RMB daily cost limit.
- Production deployment, server migration, or live channel changes as part of this specification-writing stage.

## Further Notes

- Domain vocabulary is defined by the root health-steward glossary. The sidecar/fixed-Job, owner-grant, and current-snapshot ADRs are authoritative constraints for implementation.
- The current repository contains historical v0.2 prototype code and tests. They are evidence and prior art, not the authority for current behavior. Conflicts must be resolved in favor of this spec and the ADRs.
- Before implementation touches deployment assets, perform a read-only live audit of the partner server. Historical paths, service-account assumptions, Hermes version, channel state, and Cron state are not proof of current production state.
- Ticket decomposition and deployment must preserve one authoritative chain from this spec. Existing Tickets 01–13 and the reviewed Ticket 14 deployment package are implementation evidence, but the recorded Phase A `no-go` means the new production-integration gaps require explicit tickets and cannot be closed by documentation alone.
- Deployment parameters still to be supplied and snapshotted are the exact owner Weixin sender ID, the exact single viewer/operator Weixin sender ID, the actual accepted health provider/endpoint/model configuration, the external dead-man endpoint, the outage-alert email, and the Phase B maintenance window with fresh interruption/rollback authorization. They are deployment inputs, not unresolved architecture choices.
- The `ready-for-agent` status means the feature is fully specified for ticket decomposition. It does not mean implemented, deployed, or accepted.

## Comments

- Spec synthesized from the user-confirmed `$grill-with-docs` design tree. The primary system seam and the thin Hermes integration seam were explicitly confirmed before publication.
- 2026-08-09: updated from the user-confirmed Q1–Q22 production-integration decisions after the same-host Phase A `no-go`. The confirmed highest seams are the real-format partner Weixin runtime path and the LLM-independent operations-monitor path. Gateway failure is monitored and alerted; it is not treated as continued health-steward operation.
