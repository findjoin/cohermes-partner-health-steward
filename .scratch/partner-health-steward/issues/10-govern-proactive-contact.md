# 10 — 实现主动触达治理

**What to build:** 让自主触达在去重、未回复退避、夜间理由、主人暂停和滚动容量限制下运行，并在状态变化后取消或重新评估旧任务。

**Blocked by:** 06 — 实现主人自查、查看授权与只读访问；09 — 实现到期快照渲染与消息派发

**Status:** resolved

- [x] 同一目的存在未完成任务时不能创建或发送重复任务。
- [x] 主人未回复时，同一主题至少 72 小时后才可再次主动触达；日检可选择更久或不再追问并记录理由。
- [x] 没有固定静默时段，但每条夜间主动消息必须保留可复查的时间选择理由。
- [x] 主人能够暂停指定时长或无限期的主动触达；暂停取消等待任务但不阻断被动回应和实时画像维护。
- [x] 无限期暂停只能由主人明确恢复，不能由日检或偏好推断自动解除。
- [x] 任意滚动 24 小时最多发送 100 条自动消息，该值只作为故障熔断而非目标配额。
- [x] 达到容量后任务以 `capacity_exhausted` 跳过，不排队补发；下一日日检仅在仍有意义时重新判断。
- [x] 结论失效、证据覆盖、授权撤回、档案删除和时间窗过期均在发送前取消或跳过任务。

## Answer

- Implemented purpose deduplication, topic-level unanswered backoff with a 72-hour minimum, owner-reply tracking without retaining message bodies, and reviewable timing rationale for local-night delivery (22:00–06:00).
- Added owner-authorized pause/resume actions through the Partner Adapter and sidecar socket. Pausing cancels waiting proactive tasks; finite pauses expire by time, while indefinite pauses require an explicit owner resume. Reactive message staging and profile maintenance remain available during a pause.
- Added the rolling 24-hour automatic-message circuit breaker at 100 messages, `capacity_exhausted` skip handling without catch-up, and final pre-send checks for superseded conclusions, invalid evidence, pause, capacity, topic backoff, and expired windows.
- Canonicalized the unanswered-topic identity from verified conclusion/evidence references, so a model-renamed `topic_key` cannot bypass the 72-hour backoff; direct owner statements also release the unanswered state. Receipt validation, state mutation, and one-time consumption now share one lock, and stored reply/task times reject naive timestamps.
- Bound a finite pause duration into the signed owner receipt, so the gateway cannot alter the requested end time or turn it into an indefinite pause after authorization.
- Verification on Windows: Ticket 10 targeted tests are 14 passed with one AF_UNIX socket test skipped because the development host has no Unix-domain sockets; the full suite ran 271 tests, with 15 environment skips and all non-skipped tests passing. The suite must still be rerun on non-production Linux before deployment.
