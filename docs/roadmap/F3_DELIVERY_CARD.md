# F3: durable delivery and explicit uncertainty

Status: draft architecture contract. F3 runtime remains gated on Astra acceptance of F2 and review/merge of this detailed card. Planning may proceed alongside F2; do not change F2 code to implement this draft. Owner: Astra; intended delivery owner: Sol.

## Outcome and scope

An operator requests delivery of an exact current approved synthetic claim. A PostgreSQL-backed worker sends the preserved bytes to a separately running synthetic receiver. Operator views explain whether work is pending, blocked, definitely unsent, accepted by that receiver, rejected without acceptance, or uncertain. Process restart and duplicate pickup preserve that distinction. Reconciliation uses independent receiver evidence, not a producer success flag.

F3 adds claims-owned delivery intent, authorization, attempt and reconciliation plus a small PostgreSQL execution queue and loopback-only receiver adapter. It sends no real claim and adds no payer, cloud service, broker, scheduler platform, remittance, financial posting or archival work. Receiver acceptance means only that this synthetic receiver durably recorded these bytes; it does not establish adjudication, remittance or payment.

Preserve F1/F2 contracts. Do not rewrite accepted claim bytes from current service state. A new implementation must adapt this card to the accepted F2 owner-query names without changing their meaning; escalate a contradiction instead of silently widening scope.

## Owners and exercised interfaces

Claims owns DeliveryIntent, ClaimDeliveryControl, DeliveryAttempt, AttemptOutcome, ReceiverObservation and DeliveryWork. These are domain records and narrowly scoped execution bookkeeping, not a generic workflow engine or event-sourced aggregate. Access still owns membership; records supplies the encounter-locking query. Composition supplies authenticated forms and the worker management command. The adapter supplies transport observations; it cannot approve a claim or choose a different revision, destination or payload.

`request_delivery(actor, organization, request_id, claim_revision_id, expected_envelope_digest)` admits a current approved F2 revision and creates exactly one intent/work item atomically. It uses the claims-owned accepted-command receipts and canonical intent rules from F2, including command kind and exact target. Same accepted request replays original IDs and historical/current status separately; changed target/input conflicts. Different requests for that same already-created revision return the existing intent without creating another effect or replacing its authorizer. Rejected requests leave no receipt or partial work.

`cancel_before_dispatch(actor, organization, request_id, intent_id)` can cancel only when no attempt has a committed possible-dispatch marker. An operator cannot turn uncertainty or acceptance into cancellation. It returns the durable reason if cancellation loses a race with dispatch. Use an accepted receipt for a successful cancellation/no-op, with immutable evidence of who canceled it.

`reconcile_delivery(actor, organization, intent_id)` performs a bounded readback at the intent's pinned receiver. It records attributable observations and recomputes current status. It sends no claim bytes and cannot authorize retry by itself. A transport/readback failure does not overwrite earlier valid receipt evidence.

`retry_idempotent_delivery(actor, organization, request_id, intent_id)` is an explicit retry authorization for an uncertain attempt only on a receiver version whose fixture contract guarantees persistent idempotency. Recheck active membership, F2 current actionability and exact bytes/route; preserve intent ID, delivery key and bytes. Record an accepted receipt and enqueue at most one pending retry. Never switch an uncertain intent to a different receiver version or create a new key.

Claims exposes a delivery-detail/worklist query that returns exact revision/intent/attempt identities, historical outcomes, current state, blocking reasons, permitted actions and receiver evidence. All UI paths use this query. Authorization failures remain scoped not-found/denied responses rather than leaked target information.

## Durable records and invariants

All rows use existing UUID/organization/UTC conventions and PostgreSQL tenant constraints. Enforce same-organization and exact aggregate pairs, not independent foreign keys alone. Immutable records reject ordinary UPDATE and DELETE; mutable execution rows use guarded transitions. Application commands remain the authorized write surface.

| Record | Required identity and evidence |
| --- | --- |
| DeliveryIntent | Immutable organization, Claim/ClaimRevision, exact ClaimApproval, envelope digest, byte length, format version, pinned route and receiver capability version, stable delivery key, authorizing actor/time; unique organization/ClaimRevision |
| ClaimDeliveryControl | Unique organization/Claim; current intent slot, initialized/advanced under the Claim lock; protects the case across revisions |
| DeliveryWork | Unique intent, pending/leased/blocked/finished execution state, due time, lease owner/expiry and monotonic fencing generation; no independent business approval |
| DeliveryAttempt | Immutable intent, attempt UUID/ordinal, triggering authorization/receipt, actor-attribution, payload digest/length, destination/capability snapshot, start time and whether possible dispatch was committed; unique intent/ordinal |
| AttemptOutcome | At most one immutable terminal outcome per attempt: pre_dispatch_failed, receiver_accepted, receiver_rejected or unknown; reason, end time and referenced receiver observation when applicable |
| ReceiverObservation | Immutable origin, receiver ID/version, lookup key, receipt ID, exact intent/revision/digest/length binding, observed receiver state and time; retain conflicting/unmatched observations separately from accepted evidence |

The DeliveryIntent's ClaimRevision, ClaimApproval and digest must match the same F2 immutable revision; route/capability snapshot must match its route. Attempt references its own intent and identical byte/destination identity. Outcome and linked observation must match that attempt's intent. Receiver receipt identity is unique per receiver namespace; repeated identical evidence is a replay, changed evidence under that identity is a recorded conflict that cannot establish success.

Use the immutable F2 database envelope as the byte source. Verify SHA-256 and byte length before every dispatch. Never reconstruct from mutable rows or route aliases. The loopback base URL/port is private local configuration; resolve it from the pinned fixture receiver ID/version, never a submitted URL. Configuration mismatch blocks dispatch rather than falling back to another destination. Include a stable configured receiver identity and require it in the response/readback; no production authentication claim.

## Case-level duplicate prevention

The ClaimDeliveryControl slot stays occupied while an intent is queued, leased, blocked, possibly dispatched, uncertain or receiver-accepted. New claim revisions do not release it. Requesting another revision's delivery in that case fails with prior_delivery_unresolved or prior_delivery_accepted. F3 does not authorize replacement/corrected submissions after a possible or confirmed effect.

Only durable proof of no possible acceptance can release the slot: cancellation before any possible-dispatch marker, or a verified receiver rejection explicitly guaranteeing no acceptance for every possibly dispatched attempt. A rejection of a later v1 retry says nothing about an earlier unknown/in-flight attempt; it cannot release the slot or demote uncertainty. Negative lookup is never that proof. All possibly dispatched attempts must have independently verified terminal no-acceptance evidence before rejection permits release, and no attempt may have accepted/conflicting evidence. A pre-dispatch failure stays on the same retryable intent and retains the slot. Slot advance, intent creation and work creation occur in one transaction under the Claim lock. Database guards reject switching to another case's intent, rewinding the slot, clearing a possibly accepted intent without permitted evidence, and concurrent competing occupants. Retain all released intent history.

F3 offers no manual mark-unsent, force-success or resend-anyway button. If a receiver lacks sufficient evidence or idempotency, the unresolved state is the correct result. Production replacement and resubmission policy remains a later explicit decision.

## Fake receiver and independent evidence

Implement one separately running loopback HTTP process with its own PostgreSQL schema/connection and durable receiver ledger, isolated from application transactions. The canonical application must not import its ledger writer or query its tables; send/readback goes through the adapter. Tests may inspect receiver state through an independent test connection to prove what was actually stored. Use the PostgreSQL 17 CI service, not SQLite as a substitute for canonical or receiver persistence. No new runtime framework is necessary for the synthetic receiver.

Provide two fixture capabilities corresponding to F2's synthetic-receiver/v1 and /v2:

- v1 durably deduplicates the stable delivery key and exact bytes. Same key/same digest returns the original receipt without another acceptance. Same key/different bytes is a conflict with no second acceptance. Its guarantee survives receiver restart; immutable key ledger and accepted bytes commit atomically.
- v2 has no idempotency guarantee. Repeated POSTs can create multiple receiver records. The application must demonstrate it sends at most once after any possible dispatch unless independent evidence already classifies the result; absence from a lookup is not authority to send again.

Both receiver versions validate synthetic envelope marker, declared digest/length, request identity and configured receiver identity. A receipt is generated from actual body bytes read and committed by the receiver, never copied from the sender's expected-success fields. Store exact received bytes, computed digest, length, stable delivery key, revision ID and receipt ID. Receiver readback returns these stored identities and bytes (bounded to the F2 1 MiB envelope) so the adapter can independently verify digest/length and compare exact bytes. A readback response claiming a digest without verifiable received bytes is insufficient for confirmed acceptance in this fixture.

Support deterministic test modes: reject before acceptance, delay before response, commit acceptance then drop response, return wrong-target/corrupt evidence, and receiver restart. Test-only controls are separate from claim payloads and unavailable in normal operator forms. Receiver storage survives process restart. A negative lookup means not_observed, never proof of no prior/in-flight effect. Wrong/mismatched/conflicting evidence cannot be presented as accepted.

## Worker, lease and dispatch boundary

Expose a bounded `run_delivery_worker --once` management entrypoint and a simple optional loop using the same owner command. No automatic background service or deployment is required. Use PostgreSQL `SELECT FOR UPDATE SKIP LOCKED` for due execution rows and database time for leases. A configurable synthetic lease must be longer than the finite adapter timeout; tests may shorten both. Cap one worker pass and use explicit maximum safe pre-dispatch retries (three attempts total, persisted), then show operator attention.

Claiming a DeliveryWork row is a short transaction that advances its fencing generation and records lease owner/expiry. Release that row lock before taking business locks. Final dispatch admission uses the F2 lock order: encounter, policy selection, Claim, delivery control/intent, then work row. Recheck lease/fence and effective authorizer active membership, F2 actionability, exact payload bytes/digest, route and case slot while those locks are held. Do not hold a work-row lock while acquiring encounter/Claim locks in the reverse order. Scheduling/recovery likewise must not nest locks in an inconsistent order.

A worker is an internal execution principal; its presence is not human authority. Recheck the effective dispatch authorizer's active membership before possible dispatch: the intent authorizer for initial/safe-preflight attempts, or the actor on the accepted explicit retry receipt for a v1 retry. Persist that actor and receipt identity on the attempt; a queue worker cannot substitute itself. Revoked membership, superseded claim, changed selected service/policy, invalid envelope or route mismatch blocks queued work and records the reason without an external call. Read-only reconciliation of an older attempt remains available to another active operator even if the original authorizer left. Reauthorization of a blocked intent is not added in F3; a current new revision may be requested only after the old slot is safely canceled/released.

Before the network call, atomically append a DeliveryAttempt with possible_dispatch=true and its exact checked authorization snapshot, then commit. This commit is the effect-authorization boundary. Changes to services/policy or membership before it block dispatch; changes afterward do not retroactively revoke an already authorized/in-flight call. They remain visible on the current claim. A mutable work lease or current-screen boolean cannot override this ordering. The adapter receives only the frozen intent/attempt envelope after commit.

Call the receiver outside all canonical database transactions with finite connect/read timeout and no automatic HTTP retry. Record returned evidence/outcome in a new transaction. A definitive accepted outcome requires independently verified exact receiver evidence; a definitive rejection requires the fixture's explicit rejected-without-acceptance response. Any response loss, timeout after the marker, ambiguous failure or mismatched evidence is unknown. Conservatively classify a crash between marker commit and the first network byte as unknown: the database cannot prove the call never began.

Preflight failures before a possible-dispatch marker may create a terminal pre_dispatch_failed attempt with possible_dispatch=false; it cannot carry acceptance evidence. Retry only declared transient preflight failures within the persisted limit, rechecking all authorization on every attempt. Domain staleness or bad bytes blocks rather than automatically retries. An expired lease with no possible-dispatch attempt is safely reclaimable. An expired lease with a possibly dispatched attempt and no verified outcome produces unknown and disables automatic sending.

A stale lease holder cannot authorize/append another dispatch, move current work state or clear a newer lease. An already committed possible-dispatch attempt may still reach the receiver after its lease expires (for example, the process paused just before its HTTP call). Lease expiry cannot revoke network activity atomically, so recovery retains uncertainty and the case slot; v1 retry reuses the same durable receiver key, and v2 never authorizes a second call. Do not claim the fence prevents that previously authorized physical call. Late independently valid receiver evidence may be appended through a separate reconciliation path even from a completed/unknown attempt; it can establish acceptance without reviving the old worker's fence. AttemptOutcome remains immutable: later evidence supplements its historical unknown result, and the query derives confirmed acceptance only from accepted receiver observations. Duplicate late observations are idempotent.

## Recovery and current status

Recovery examines durable attempts and receiver evidence, not PID files or producer flags. For v1, readback may establish acceptance; if still not observed/unknown, an active operator may authorize one exact idempotent retry through retry_idempotent_delivery. Concurrent retry commands produce at most one pending or leased retry authorization/work item, and the receiver key guarantees at most one durable acceptance. If a retry is already pending or leased, another request returns that scheduled retry identity with a receipt; it cannot replace its lease/fence or arm an additional retry. A new retry authorization is possible only after that scheduled retry reaches its durable terminal/unknown outcome. F2 current actionability is required before such a new POST; historical readback is allowed without current approval.

For v2, reconciliation may confirm acceptance through exact readback, but not_observed, missing receipt, timeout or contradictory evidence remains uncertain with no retry action. Restarting either process or editing the claim cannot erase this uncertainty or release its case slot. A rejection conflicting with a previously verified acceptance must not release the slot; preserve the acceptance and flag receiver_conflict for review.

Claims exposes ordered blockers and current delivery state. Scope/member denial is handled before lookup. Evidence conflicts take primary precedence; then confirmed receiver acceptance; then uncertainty/possibly dispatched without a verified terminal outcome; then verified no-acceptance rejection or safe cancellation; then blocked current authorization; then leased/pending work. Show all applicable reasons and distinguish execution status from effect status. A blocked current revision cannot demote a historical confirmed receipt, and an old lease expiry cannot turn a receipt into uncertainty.

Forms cover request delivery, safe cancellation, read-only reconciliation and explicit v1 retry, preserving UUID/expected values on errors and enforcing CSRF. Detail shows revision/digest, fake receiver, attempt history, received evidence and explanation. Every page is marked synthetic; use receiver accepted, not submitted to payer, approved for payment or complete.

## Acceptance evidence

Run all F1/F2 tests plus these PostgreSQL-backed cases. Use actual separate receiver/worker processes, bounded synchronization hooks and independent receiver readback. Do not simulate receiver acceptance solely by mocking the producer adapter or expected booleans.

1. Exact approved bytes delivered to each fixture receiver; independent stored bytes equal the immutable envelope. Receipt remains attributable after application and receiver restart.
2. Same request replay and changed target/input conflicts; different requests cannot duplicate the same revision's intent. Competing revisions cannot bypass the ClaimDeliveryControl slot.
3. Pre-dispatch failure/retry, domain staleness, revoked membership, corrupt envelope and wrong route: no receiver acceptance and no false success. Persisted safe retry limit terminates in operator attention.
4. Claim/service/policy mutation racing dispatch follows the specified authorization boundary. Test one change committed before the boundary (no send) and one after (frozen authorized bytes retain their attempt identity).
5. Concurrent workers and duplicate pickup produce one possible-dispatch attempt under a valid fence. Stale workers cannot create new dispatch authorization or complete newer work; a delayed physical call for an already committed attempt remains possible and is covered by uncertainty/idempotency. Lease recovery with no marker is retryable; recovery with a marker is unknown without blind resend.
6. Kill a worker after marker/before call and after receiver commit/before producer outcome. Both initially become uncertain. Restart never silently sends again. Independent receiver evidence distinguishes actual accepted bytes from absence.
7. v1 receiver commit/response-loss followed by explicit authorized retry produces one receiver acceptance and stable receipt/key. Concurrent retry requests stay bounded. v2 equivalent failure makes no second POST; missing readback remains unresolved.
8. Delayed valid receipt after lease expiry/unknown is accepted as supplementary evidence without mutating the historical AttemptOutcome or granting stale worker authority. Duplicate evidence is replay; wrong target/bytes/receipt and reused conflicting receipt IDs stay in review.
9. New claim revision or route cannot evade old uncertain/accepted intent. Safe pre-dispatch cancellation or definitive no-acceptance rejection allows a new revision's intent only through the guarded slot transition. Conflicting rejection cannot erase an accepted effect, and rejection of a later retry cannot release an earlier unknown or in-flight attempt.
10. SQL writes cannot substitute organization, revision/approval/digest, intent/attempt or receipt bindings, rewind fences or rewrite immutable history. Inactive/wrong-organization callers cannot request, read, cancel, reconcile or retry. Test web CSRF and bounded form errors.
11. Run a fresh-process durability case for pending work, unknown attempt and supplementary receipt. Assert sensitive synthetic sentinel absent from application logs/errors and only visible in authorized payload/detail surfaces.
12. Stop receiver during delivery/readback and restart it with the same ledger. No false completion, lost durable key or default route fallback; ordinary accepted records/claim review remains available while receiver is down.

Record setup commands, exact head, actual process/transport evidence, suite results, unrun checks and remaining limitations. Add deterministic receiver setup/teardown to the existing PostgreSQL CI without relying on external services. No local test success may be inferred from CI or vice versa.

## Decisions, gaps and delivery handoff

Proposed choices: exact immutable envelope reuse, explicit possible-dispatch boundary, one case-level effect slot, persisted lease fences, at most three safe preflight tries, explicit v1 idempotent retry, no v2 retry after possible dispatch, append-only late receiver observations and separate receiver PostgreSQL state.

Rejected: reconstructing payloads from current records, changing keys/destinations on uncertainty, treating negative lookup as no effect, work queues as permission, network calls inside canonical transactions, and marking a newer revision safe merely because the older attempt is historical.

Open production gaps include certified transport, real receiver identity/authentication, vendor idempotency/readback guarantees, corrections/resubmission, retry policy, alerting and deployed worker recovery. This fixture fills none of those qualification gaps. F4 still requires a reviewed lifecycle/remittance/posting/archive card after F3 acceptance.

Delivery entry requires accepted F2 evidence and this card's review/merge with an explicit admission record. Sol then owns the exercised claims/worker/adapter seam; a disjoint receiver/test lane may begin only after adapter and evidence interfaces settle. Public synthetic inputs only. At most two implementation lanes. Return a draft PR and exact-head evidence to Astra, without merge or F4 implementation. Escalate a contract contradiction or two failed attempts at one approach.
