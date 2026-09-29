# F4 implementation and acceptance matrix

Status: implementation and evidence packet on `codex/f4-outcomes-archive`, based
on merged F4 admission `5b351bd5856f138b4eca2809ad2a40c6e9bdb354`.
This record fixes implementation seams and maps executable coverage. Executed
exact-head PostgreSQL evidence must still be recorded in the delivery handoff;
source presence or a partial/local check is not completion evidence.

## Ownership and public boundary

- Sol is the only production writer for `sources`, `claims`, new `outcomes` and
  `archival` apps, settings/URL wiring, migrations, operator surfaces and shared
  interfaces. Astra retains architecture, acceptance and merge ownership.
- No second production lane is permitted. After the interfaces below are
  published, one optional disjoint lane may own only synthetic fixtures and
  tests under an explicit assignment.
- Inputs, stored examples and diagnostics remain public synthetic material.
  There is no private V0 import, live endpoint, deployment work or production
  authority transfer.
- The workflow-boundary registry and change-surface policy named by the review
  skill are not integrated yet in this repository. F4 uses
  `tests/helpers/workflow_boundary_contract.py` in concrete same-target and
  fail-closed feature tests; registry-backed selection is not claimed as
  evidence.

## Immutable owner DTOs

Cross-owner calls return frozen values, never mutable ORM rows.

| Owner query | Immutable result | Required content |
|---|---|---|
| `sources.verified_delivery_bytes` | `VerifiedDeliveryBytes` | organization, delivery/artifact identity, namespace/key, media type, exact verified bytes/digest/length |
| `records.archive_encounter_snapshot` | `EncounterArchiveSnapshot` | organization, patient/encounter identity and service date, accepted service/revision identities and values |
| `claims.historical_delivery_attribution` | `HistoricalDeliveryAttribution` | organization, encounter/claim/revision/approval/intent, delivery key, receiver tuple and receipt, accepted observation/fingerprint/original attempt, exact approved bytes digest/length, currency/charge, ordered line UUID/ordinal/charge mapping |
| `claims.archive_claim_snapshot` | `ClaimArchiveSnapshot` | exact claim/revision/line identities and immutable historical delivery attribution, without current-policy authorization claims |
| `outcomes.archive_outcome_snapshot` | `OutcomeArchiveSnapshot` | accepted lifecycle/event identities, immutable posting identities and exact derived totals plus current retained-conflict alert identities |

Historical attribution verifies the complete declared tuple and approved bytes.
For acceptance it runs inside a caller-owned atomic READ COMMITTED transaction,
locks and revalidates the membership/organization prelude, then locks
`Encounter`, `Claim`, `DeliveryIntent`, and the existing receiver receipt
identity anchor before scanning target and namespace conflicts in later
statements. The intent uses PostgreSQL `NO KEY UPDATE`: it retains owner
serialization while permitting the observation guard's deferred foreign-key
`KEY SHARE` check to commit before acceptance acquires the receipt anchor,
avoiding a lock cycle without weakening the later conflict scan. It never
creates an anchor for an unmatched target. Read-only
attribution uses the caller snapshot without opening another transaction.

## Durable relationship design

### Sources extension

- `Delivery`/`Artifact` remain the only retained inbound byte store. JSON intake
  is limited to the lifecycle/remittance namespaces, `application/json`, 1 MiB
  before and during materialization, while F1 CSV/DOCX retains its 5 MiB limit.
- The F1 parser returns `parser_unsupported` for admitted JSON and does not
  create patient-row observations.
- A narrow verified-byte query is the only outcomes read seam.

### Outcomes

| Record | Identity and immutable relationships |
|---|---|
| `InboundAttempt` | organization + source delivery + interpreter version; one terminal row for every actual computation, with start/end/success/reason |
| `InboundCandidate` | unique delivery/interpreter version; exact schema/kind/sender/event/intent/revision/delivery-key/receipt/currency, canonical semantic bytes/digest and normalized content |
| `InboundCandidateLine` | unique candidate/ordinal; immutable paid/adjustment values in original ordered subset |
| `InboundConflict` | immutable pair of candidate evidence identities for one organization/sender/kind/event or lifecycle stream/sequence conflict |
| `AcceptedEvent` | unique organization/sender/kind/event and semantic digest; exact accepted candidate, F3 attribution observation/fingerprint, intent/revision/receipt and actor/time |
| `AcceptedEventEvidence` | unique event/candidate link so equal semantic evidence from another delivery never posts twice |
| `FinancialAccount` | unique organization/exact delivered ClaimRevision/USD with immutable original charge/currency and a monotonic posting generation as its only permitted mutation, used only as a mutex |
| `ChargeBasis` | unique account/exact ClaimLine with ordinal and immutable original line charge |
| `PostingBatch` | one-to-one accepted remittance event/account and complete-or-absent acceptance |
| `PostingEntry` | unique event/line/kind; typed nonnegative payment or contractual credit bound to the same batch/account/revision/line/currency |
| `OutcomesCommandReceipt` | organization/request UUID namespace across accept/post commands; canonical input digest, actor/time and typed event/batch result |

All history and accepted receipts reject ordinary UPDATE/DELETE. Composite
organization/aggregate foreign keys and deferred relationship triggers enforce
candidate/event/attribution, lifecycle predecessor, batch completeness and
posting relationships. A posting insert locks/advances its account generation
and verifies cumulative per-line credits do not exceed immutable charge.
Populated downgrade refuses before removing durable F4 protections.

### Archival

| Record | Identity and immutable relationships |
|---|---|
| `ArchiveProjection` | organization/encounter/version, unique predecessor, schema, exact deterministic bytes/digest/length, source fingerprint, actor/time |
| `ArchiveHead` | one row per encounter pointing only to its same-aggregate newest projection; no rewind |
| `ArchiveCommandReceipt` | organization/request UUID namespace across capture/queue/retry with canonical input digest and typed projection/batch/authorization result |
| `ArchiveBatch` / `ArchiveBatchItem` | immutable ordered 1..100 projection grouping; item binds same projection/work/authorization and unique ordinal/membership |
| `ArchiveAuthorization` | immutable initial three-attempt or manual one-attempt grant for one projection/receiver, with retry predecessor when applicable |
| `ArchiveWork` | one mutable fenced work row per projection, pointing to at most one scheduled authorization without refreshing its budget |
| `ArchiveAttempt` | immutable projection/version/bytes/receiver/authorization/work/lease token and possible-write marker; unique work/generation |
| `ArchiveReadbackObservation` | immutable independently read exact bytes/identity/version/receipt with verified/conflicting classification and original attempt attribution |
| `ArchiveAttemptOutcome` | at most one immutable terminal result per attempt; confirmation requires a matching pre-existing verified observation |

Projection capture owns one short REPEATABLE READ transaction and retries a
serialization/head race at most twice from a fresh snapshot. Owner queries share
that connection/snapshot. Network I/O never occurs inside capture or a canonical
transaction. The worker uses committed possible-write markers, finite timeout,
leases/fences and per-authorization budgets. Send success alone remains unknown;
only exact per-item readback confirms. Batch completion is derived from every
requested item and never from a producer boolean.

## Workflow-boundary contracts

| Workflow | Target / intent | Attempt and terminal evidence | Consumer gate |
|---|---|---|---|
| Inbound interpretation | exact Delivery + interpreter version | terminal `InboundAttempt`; successful immutable candidate | acceptance requires current verified bytes plus fresh historical attribution |
| Lifecycle/remittance acceptance | candidate + canonical semantic digest + request UUID | accepted event, evidence link, receipt; remittance also complete batch/entries | views distinguish accepted fact from current artifact/conflict alerts |
| Projection capture | encounter + expected head + canonical fingerprint | immutable projection and capture receipt in one coherent snapshot | queue accepts exact projection IDs only; absent capture is not archived |
| Archive execution | projection + authorization + work fence/generation | immutable attempt and terminal outcome; possible write may remain unknown | item confirmed only by exact verified readback; batch complete only when all items confirm |
| Reconciliation/retry | exact projection/receiver and latest attempt | deduplicated observation; manual one-attempt grant bound to predecessor | stale attempt conflicts; older unknown history remains visible |

Missing, stale, partial, mismatched, conflicting, in-flight and wrong-target
evidence retain distinct reason codes. No latest timestamp, nonempty path, HTTP
success, process exit, expected digest echo or producer flag establishes success.

## Concrete file ownership

- Shared owner seams: `src/medicafe_v1/sources/{commands,queries,parsers,views,forms,urls}.py`,
  `src/medicafe_v1/claims/queries.py`, `src/medicafe_v1/records/queries.py`.
- Outcomes production: new `src/medicafe_v1/outcomes/`, templates, migrations
  and management commands.
- Archive production: new `src/medicafe_v1/archival/`, loopback target,
  templates, migrations and management commands.
- Shared wiring: `src/medicafe_v1/settings.py`, `src/medicafe_v1/urls.py`.
- Verification: new `tests/f4/`, extension of
  `tests/helpers/workflow_boundary_contract.py`, and F1-F3 regression suites.
- Evidence/docs: this matrix, `F4_SETUP.md`, `DELIVERY_HANDOFF.md`, and roadmap
  index. No other worktree owns these files during F4 delivery.

## Planned executable acceptance coverage

| # | Required executable group |
|---|---|
| 1 | JSON admission/interpretation bounds, duplicate keys, schema/semantic failures, missing/corrupt bytes and no partial facts |
| 2 | source replay/conflict, semantic duplicate/conflict, request races/reuse and exactly-once posting |
| 3 | historical attribution after current changes; sender/receipt/line/tenant mismatch; pending evidence then explicit reevaluation |
| 4 | lifecycle sequence gap, predecessor arrival, occupied-sequence conflict and contiguous current state |
| 5 | partial/multi-event remittance, atomic over-allocation rejection and competing owner/direct-SQL conservation |
| 6 | zeros/bounds/precision/unsupported reversals and non-inference of liability/cash |
| 7 | relationship-class direct SQL, immutable history, membership, CSRF and form-target retention |
| 8 | restart durability, reparse isolation and synthetic sentinel redaction |
| 9 | coherent projection, replay/successor, forced concurrent snapshot/head races and current lag |
| 10 | independent exact archive readback, false send-success denial, receipt conflict, stale version and restart |
| 11 | batch replay/order conflict, coalescing, retry budget/fence races and older delayed write |
| 12 | archive outage while canonical claims/remittance continue, followed by per-item reconciliation and accurate lag |

At least one test in groups 1, 3, 9 and 10 uses the shared workflow-boundary
helper to assert persisted producer/consumer relationships. Concurrency tests
use barriers/locks, not timing sleeps, for both receipt-anchor orderings and
capture/posting races. PostgreSQL CI is the execution authority when the local
database is unavailable.

## Delivery checkpoints

1. This immutable DTO/model/relationship/coverage design.
2. Sources intake, claims attribution, outcomes interpretation/acceptance and
   conserved ledger with migrations and relationship tests.
3. Coherent projection capture, command receipts, fake archive, work/attempt
   state machine and exact readback.
4. Operator surfaces, full twelve-group matrix, setup/handoff, draft PR and
   exact-head PostgreSQL evidence.

Stop for an authority/interface contradiction, two failures of one approach,
or the completed draft PR/evidence packet. Sol does not merge.

## Acceptance group implementation map

Every row below is source-present but PostgreSQL-unrun unless the evidence
section says otherwise. A method name maps one concrete clause; it does not
turn neighboring clauses into implied coverage.

| Group | Clause-level executable evidence |
|---|---|
| 1 | Both schemas and strict duplicate-key handling: `OutcomesAcceptanceTests.test_interpret_replay_has_one_candidate_and_one_actual_attempt`, `test_duplicate_json_key_records_terminal_failure_without_candidate`; upload bound, extra/schema/currency/negative/precision/zero/omitted-line failures: `F4AcceptanceMatrixTests.test_json_bounds_and_semantic_failures_are_attributable_and_atomic`; missing/corrupt retained bytes: `test_missing_or_corrupt_inbound_bytes_fail_before_candidate`. |
| 2 | Source-key replay/conflict, changed content under an event ID, and wrong-candidate request reuse: `F4AcceptanceMatrixTests.test_source_replay_conflict_event_conflict_and_request_namespace`; semantically equal new delivery/no double post: `OutcomesAcceptanceTests.test_money_spellings_share_semantics_and_never_double_post`; identical and distinct concurrent accepted requests: `ReceiptAnchorConcurrencyTests.test_identical_concurrent_request_replays_one_receipt`, `test_distinct_concurrent_requests_share_fact_but_retain_each_receipt`. |
| 3 | Historical acceptance after service/claim head change plus sender, receipt, line and organization mismatch: `F4AcceptanceMatrixTests.test_historical_attribution_survives_current_change_and_mismatches_fail_closed`; that test also introduces the exact previously missing receipt through claims-owned reconciliation, proves explicit reevaluation changes only the blocker to `unaccepted`, and requires a separate explicit acceptance; exact retained attribution and boundary helper: `OutcomesAcceptanceTests.test_lifecycle_acceptance_binds_exact_historical_delivery`; both forced receipt-anchor orderings and incompatible isolation: `ReceiptAnchorConcurrencyTests.test_acceptance_first_commits_fact_then_later_conflict_remains_alert`, `test_conflict_first_forces_waiting_acceptance_to_fail_closed`, `test_acceptance_rejects_repeatable_read_transaction`. |
| 4 | Gap, predecessor arrival, occupied sequence conflict, retained accepted correction and contiguous current state: `F4AcceptanceMatrixTests.test_lifecycle_predecessor_arrival_conflict_and_current_sequence`; ordered blockers: `OutcomesAcceptanceTests.test_reevaluation_reports_conflict_and_sequence_gap_in_order`; same-organization wrong-stream predecessor SQL denial: `OutcomesRelationshipMatrixTests.test_evidence_link_and_lifecycle_predecessor_must_match`. |
| 5 | Exact once posting and duplicate replay: `OutcomesAcceptanceTests.test_remittance_posts_conserved_entries_once`, `test_money_spellings_share_semantics_and_never_double_post`; a valid first line followed by an invalid later line is rejected atomically by `F4AcceptanceMatrixTests.test_partial_multievent_and_multiline_overallocation_is_all_or_nothing`; distinct concurrent owner commands compete for one residual balance in `DirectPostingConcurrencyTests.test_distinct_owner_commands_compete_for_one_residual_balance`; direct READ COMMITTED and stale REPEATABLE READ competition retains exact SQLSTATE coverage in `test_direct_sql_conservation_serializes_rc_and_rejects_stale_rr`. |
| 6 | Zero component omission, maximum parser amount, precision normalization and explicit overallocation reevaluation: `F4AcceptanceMatrixTests.test_zero_component_precision_maximum_and_explicit_reevaluation`, `test_partial_multievent_and_multiline_overallocation_is_all_or_nothing`, `OutcomesAcceptanceTests.test_money_spellings_share_semantics_and_never_double_post`; explicit reversal kind, refund field, negative and other unsupported inputs: `test_json_bounds_and_semantic_failures_are_attributable_and_atomic`; exact rendered zero-residual wording without patient-liability or cash-settlement inference: `F4WebTests.test_zero_residual_page_uses_bounded_financial_wording`. |
| 7 | Named SQL relationship classes and immutable history: every method in `OutcomesRelationshipMatrixTests` and `ArchiveRelationshipMatrixTests`, plus `OutcomesSqlRelationshipTests`; wrong-org and inactive membership across every new owner command/query, using exact accepted request IDs for replay: both `F4AuthorizationTests` methods; all eight mutation routes require CSRF: `F4WebTests.test_every_f4_mutation_route_requires_csrf`; accept/post/capture/queue/retry error rendering retains submitted request UUIDs and target/fence fields: `test_receipt_bearing_forms_preserve_request_and_target_fields_on_error`. |
| 8 | Fresh-process accepted fact/ledger read, semantic reparse isolation and process-log sentinel exclusion: `OutcomeProcessDurabilityTests.test_fresh_process_reads_accepted_ledger_and_never_logs_sentinel`; error and unauthorized-view sentinel exclusion: `F4WebTests.test_synthetic_sentinel_is_absent_from_error_and_unauthorized_views`; target and worker restart: `ArchiveProcessTests.test_exact_projection_survives_target_and_worker_restart`. |
| 9 | Same fingerprint replay, successor and lag: `ArchiveFoundationTests.test_capture_replays_same_fingerprint_without_new_version`, `test_current_lag_uses_coherent_owner_snapshot`; `CapturePostingConcurrencyTests.test_capture_is_one_before_snapshot_and_posting_waits_then_creates_lag` proves the competing posting backend is lock-blocked, the first projection is wholly before the posting, and the successor projection contains the complete event, entries, account totals and current status; `test_capture_snapshot_excludes_reconciliation_committed_between_owner_reads` pauses after the records-owner read, requires an exact accepted claims reconciliation to commit before capture resumes, proves the repeatable-read projection wholly excludes it, then proves the successor contains the exact intent/revision/delivery/observation/receipt/fingerprint tuple and is current; concurrent initial and successor head races without partial receipts: `test_concurrent_initial_capture_has_one_projection_and_no_partial_receipt`, `test_concurrent_successor_capture_advances_head_once`; nested isolation denial: `ArchiveFoundationTests.test_capture_rejects_nested_transaction_before_isolation_change`. |
| 10 | Exact independent bytes/readback and boundary helper: `ArchiveFoundationTests.test_worker_confirms_only_independent_exact_item_readback`; send success without readback: `test_send_success_without_readback_remains_unknown_and_retries_bounded`; wrong item plus actual persisted receiver ID, receiver version, projection version and changed bytes: `test_wrong_projection_readback_cannot_confirm_item_with_existing_unknown`, `ArchiveReplayAndEvidenceTests.test_partial_batch_and_each_wrong_identity_variant_remain_attributable`; the consumer still requires the configured receiver tuple and never normalizes mismatched evidence before the SQL admission trigger; missing/unverified direct confirmation: `ArchiveRelationshipMatrixTests.test_authorization_attempt_outcome_and_receipt_relationships_fail_closed`, `test_wrong_item_readback_is_retained_conflict_and_cannot_confirm`. |
| 11 | Batch request replay/order conflict and unchanged budget: `ArchiveReplayAndEvidenceTests.test_batch_request_replay_order_conflict_and_later_batch_do_not_reset_budget`; manual retry replay/changed/stale conflict: `test_manual_retry_exact_replay_and_changed_or_stale_attempt_conflict`; competing workers: `ArchiveWorkerRaceTests.test_concurrent_workers_cannot_duplicate_grant_or_target_version`; expired pre-marker and possible-write fences/delayed old completion: `ArchiveFoundationTests.test_expired_pre_marker_lease_recovers_then_uses_fresh_generation`, `ArchiveWorkerRaceTests.test_expired_possible_write_is_closed_and_delayed_older_worker_is_fenced`; a real target retains one exact same-key row and original attempt attribution across response loss, target restart, exhausted automatic attempts and the manual retry in `ArchiveProcessTests.test_committed_write_with_dropped_response_retries_same_key_after_restart`; `ArchiveFoundationTests.test_manual_one_attempt_grant_cannot_restart_automatic_budget` proves no fifth send is created after the inconclusive manual attempt. |
| 12 | Archive outage while ordinary service review, successor claim preparation and historical remittance posting continue, then exact recovery and lag: `ArchiveProcessTests.test_archive_outage_does_not_block_canonical_remittance_and_later_recovers`; one item acknowledgment cannot complete a two-item batch: `test_one_item_acknowledgment_never_completes_partial_batch`; in-memory partial attribution: `ArchiveReplayAndEvidenceTests.test_partial_batch_and_each_wrong_identity_variant_remain_attributable`. |

## Current execution evidence and remaining gate

Database-free checks on 2026-09-29: all `src` and `tests` Python compiled;
`manage.py check` passed; offline `makemigrations --check --dry-run` reported
`No changes detected` while warning that local PostgreSQL history was
unavailable; `git diff --check` passed; and
`ArchiveAdapterTests.test_non_string_send_status_is_bounded_unknown` passed in
0.056 seconds without a database. A direct `unittest` invocation first failed
before collection because `src` was not on `PYTHONPATH`; the configured Django
runner then executed the test successfully.

The user authorized the full public-synthetic GitHub workflow and PR #10 tracks
this packet. Its first 218-test PostgreSQL 17 run failed because an F3
migration regression cleanup restored only the claims leaf and left the F4
outcomes/archive schema unapplied; no distinct product failure appeared in that
log. Commit `00abc66` restores and verifies the original full leaf set. Its
219-test rerun completed with one failure and two errors: a receipt-anchor lock
cycle, a relationship-test reverse-accessor typo, and wrong-receiver evidence
laundering caused by persisting the configured tuple instead of the reported
tuple. This local packet applies the bounded `NO KEY UPDATE` intent lock repair,
fixes the accessor, preserves the actual bounded evidence tuple, and adds the
76-test F4 coverage described above. Run `36615037902` executed 225 tests in
253.590 seconds and passed the final controlled-evidence interleaving plus all
production repairs; its only failure was the retry form being conditionally
hidden on an error before any attempt existed. Exact candidate
`7e7bfebf34ec7109dc51fdeab0556339d616e3d3` retains the bound form and passed
[run 36615748027](https://github.com/katanada2/MediCafe-v1/actions/runs/36615748027):
all 225 F1–F4 tests, including all 76 F4 PostgreSQL/process tests, plus fresh
migrations, Django checks and migration-drift verification in 254.325 seconds.
Astra accepts this reviewed public-synthetic implementation for governed merge.
No local PostgreSQL retry is planned. Synthetic F4 milestone acceptance remains
conditional on merge of PR #10; an accepted candidate and open PR do not claim
that merge already occurred.
