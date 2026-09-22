# F4 implementation admission

## Authority and predecessor

Astra accepts F3 at runtime head `f5dfafe6ecc42f51a8b2b27c7fdea526432673d4`, merged through [PR #8](https://github.com/katanada2/MediCafe-v1/pull/8) as `0033e5c892a40535fb06200432cb62e68cfba69b` on 2026-09-22. [Run 35719081505](https://github.com/katanada2/MediCafe-v1/actions/runs/35719081505) passed PostgreSQL 17 migrations, Django checks, migration drift and all 149 F1/F2/F3 tests in 147.898 seconds. GitGuardian passed; the three automated review findings were resolved after code review and regression coverage.

Merge of this admission record admits implementation of the [F4 card](F4_OUTCOMES_ARCHIVE_CARD.md), with the interface clarifications below. An unmerged copy does not authorize runtime work. This is public synthetic foundation work, not production acceptance, compliance evidence, deployment, private data migration or V0 authority transfer. The card's twelve acceptance groups and all existing regression suites remain required.

## Claims-owned historical attribution

Outcomes must use a narrow claims-owned query rather than current claim actionability or raw models. Add `historical_delivery_attribution(actor, organization_id, intent_id, delivery_key, claim_revision_id, expected_receiver_id, expected_receiver_version, receiver_receipt_id, line_ordinals, for_acceptance=False)`.

The fixed sender mapping is `synthetic-sender-v1` to receiver `synthetic-receiver` version `v1`, and `synthetic-sender-v2` to the same receiver version `v2`. Unknown senders are unsupported. Sender IDs are fixture identities, never endpoints or evidence of real-world sender authentication.

Return an immutable DTO with scoped organization/encounter/claim/revision/approval/intent identities, delivery key, receiver identity/version/receipt, verified acceptance observation ID and fingerprint, original reported attempt ID, approved envelope digest/length, currency/original charge, and immutable ordinal-to-ClaimLine-ID/charge mapping. Lifecycle may request no ordinals; remittance requires a nonempty distinct subset from the exact revision. Do not expose mutable ORM rows across the boundary.

Verify the complete declared tuple and independently received exact bytes against the approved envelope. The receiver receipt must be a binding-valid accepted observation. A late accepted observation may supplement an immutable UNKNOWN attempt outcome; UNKNOWN alone must not hide that acceptance. Later service changes, current policy changes and claim supersession do not invalidate historical attribution. Current actionability is a separate concern.

Require active membership before scoped lookup. Return stable safe blockers: `unmatched_target` for a missing/wrong scoped identity or line, `pending_delivery_evidence` for an exact local target without verified acceptance, and `conflicting_identity_or_content` for retained contradictions. Do not reveal foreign-organization identities, receipt contents or existence. This query performs no HTTP call, readback, dispatch, posting or implicit acceptance.

## Acceptance transaction and conflict policy

For acceptance, require an existing caller-owned atomic READ COMMITTED transaction. Reject an incompatible caller transaction before mutation; archive capture remains REPEATABLE READ. Acquire locks in this order: active membership/organization prelude, records Encounter, claims Claim, DeliveryIntent, matching receiver-receipt identity anchor, then outcomes event/account rows. The claims-owned query takes the claims/evidence locks in that order through owner seams; do not independently lock the same objects in reverse order. Revalidate membership after acquiring its lock. Resolve and verify scoped identities before locking a global receipt anchor.

The intent lock serializes against F3 reconciliation, while the receipt identity anchor serializes against conflicting reuse across intents. Acquire the anchor lock first, then inspect target-intent conflicts and conflicts for the same receiver ID/version/receipt namespace in subsequent statements. Do not combine a potentially waiting lock and conflict scan into one statement with a pre-wait snapshot. Any retained contradiction blocks new F4 acceptance, including cross-intent receipt reuse; return only the generic safe blocker for cross-organization conflicts. Do not create or modify an anchor merely to make an unmatched inbound document attributable.

A conflicting receipt observation committed after a successful F4 acceptance does not retroactively delete or repost that accepted fact. Preserve the accepted observation/fingerprint in the acceptance record and expose a current conflict alert. Concurrent acceptance and conflict insertion must have a defined serialization order at the shared anchor. Tests must force both orderings rather than rely on timing sleeps, including acceptance waiting behind a conflicting receipt insertion and rejection of an incompatible transaction isolation level.

Read-only attribution and archive capture use the caller's connection and snapshot without starting an independent transaction. Capture retains the card's coherent REPEATABLE READ semantics. Acceptance uses fresh evidence under the prescribed locks; do not carry a stale interpretation-time authorization into posting.

## Delivery ownership and checkpoints

Sol owns outcomes, archival, the narrow claims/sources query extensions, schema, shared wiring and integration tests in one isolated branch based on main containing this record. Astra owns architecture decisions, contract changes and final acceptance. At most one additional disjoint fixture/test lane may run after Sol publishes settled interfaces; every assignment states outcome, inputs, exact file ownership, dependencies, evidence, public-synthetic classification and stop condition. Do not add a second production writer or recursively delegate orchestration.

1. Settle immutable DTOs and model/relationship matrix against this record. Report architectural contradictions before implementing around them.
2. Implement retained inbound interpretation, historical attribution, lifecycle acceptance and conserved remittance posting; verify ledger and ordinary direct-SQL guards.
3. Implement coherent explicit projection capture, bounded archive authorizations, independent fake target and exact per-item readback; preserve canonical operation during target outage.
4. Deliver operator surfaces, full twelve-group acceptance matrix, process/restart/concurrency evidence, setup walkthrough and production-gap handoff in a draft PR. Run all F1-F4 tests and migration/check/drift verification on PostgreSQL.

These are checkpoints in one F4 contract, not permission to omit later groups. Reuse proven F3 mechanisms where their semantics match; archive's bounded automatic retry grant differs from claim delivery's explicit retry authority. Every possibly dispatched attempt must retain a terminal outcome or an explicit unresolved recovery state, and duplicate evidence must not lose per-attempt history. Accepted evidence can confirm repeated exact idempotent effects; attempt-specific rejection cannot settle a different attempt. Populated downgrade must never destroy durable history silently.

Stop for an unresolved authority/interface contradiction, two failures of the same approach, or the completed draft PR/evidence packet. Sol does not merge or begin production work. Astra reviews implementation and exact-head checks before normal governed merge. No local PostgreSQL execution is claimed when only discovery/checks ran; use CI evidence if local PostgreSQL is unavailable without repeated connection attempts.

## Alternatives and remaining boundaries

Rejected: attributing outcomes to the current Claim head, using current policy as a historical acceptance gate, treating UNKNOWN as proof of no receiver acceptance, bypassing claims through raw cross-owner writes, accepting a receipt solely because its string exists, and silently rewriting accepted facts after later conflict.

The card's production gaps remain open: real schemas and transport, corrections/reversals/COB, opening balances, pricing/coverage, patient responsibility, cash/deposit reconciliation, actual Medisoft mapping, scheduling, retention, identity correction and qualified operational recovery. Completing F4 produces a synthetic end-to-end foundation and an explicit gap handoff, not a production replacement.