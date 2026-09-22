# F3 implementation and acceptance matrix

Status: implementation plan. Every row is **planned**, not executed, until the
exact-head evidence section is updated. Source inspection is not test execution.

## Settled seams

- Claims owns immutable `DeliveryIntent`, `DeliveryAttempt`, `AttemptOutcome`,
  and `ReceiverObservation` records, the guarded `ClaimDeliveryControl` slot,
  and the single mutable, fenced `DeliveryWork` row.
- A claims receipt records the effective actor and time. Its typed F3 result
  references are reciprocally bound to the intent/work in the same transaction;
  coalescing receipts never replace the initial authorizer.
- Final dispatch admission locks encounter, policy, claim, slot/intent, then
  work; it validates the live database-time lease and fencing generation before
  committing a possible-dispatch attempt. The HTTP call occurs after commit.
- The adapter accepts only a frozen intent/attempt envelope and returns transport
  facts. Accepted/rejected outcomes require a separate readback containing the
  receiver's stored bytes; a producer response flag is never terminal evidence.
- The receiver is a separate loopback HTTP process with a separate PostgreSQL
  connection and schema. Canonical application code neither writes nor queries
  its ledger.
- An `unknown` outcome is immutable. Late verified observations supplement it;
  they never rewrite the historical outcome or revive an expired worker fence.
- The case slot can advance only after cancellation with no possible-dispatch
  attempt, or verified no-acceptance evidence for every possible attempt. A
  negative lookup and a later retry rejection do not release an earlier unknown.
- Queue claim releases its row lock before business admission. Recovery and
  completion lock attempt then work consistently; worker mutations require a
  live database-time lease, and the configured lease must exceed adapter timeout.
- Final admission rechecks current effect evidence so late acceptance,
  rejection, conflict, or cancellation cannot leave stale queued work sendable.

The workflow-boundary registry and change-surface policy named by the review
skill are not present in this admitted repository. The concrete F3 boundary
helper and tests below therefore serve as the feature integration; this absence
does not turn planned evidence into completion evidence.

## Executable evidence map

| # | Contract scenario and subcases | Planned executable evidence | State |
|---|---|---|---|
| 1 | v1 and v2 receive the exact approved bytes; independent ledger bytes equal the immutable F2 envelope; application and receiver restart preserve receipt attribution | `tests.f3.test_process_delivery.ProcessDeliveryTests.test_exact_bytes_each_receiver_survive_both_restarts`; independent psycopg ledger read plus `assert_delivery_boundary` | Planned |
| 2 | Exact request replay; changed input/target conflict; different request coalescing; competing revision slot exclusion | `tests.f3.test_commands.DeliveryCommandTests.test_request_receipts_replay_conflict_and_coalesce`; `tests.f3.test_concurrency.DeliveryRaceTests.test_competing_revisions_have_one_case_slot` | Planned |
| 3 | Transient pre-dispatch failure and three-attempt cap; stale domain, revoked actor, corrupt envelope, and wrong route never reach receiver | `tests.f3.test_worker.WorkerPreflightTests` methods for `safe_retry_limit`, `domain_stale`, `membership_revoked`, `corrupt_envelope`, and `route_mismatch`; ledger count assertions | Planned |
| 4 | Service correction, claim revision, policy mutation, and membership revocation each race dispatch. Every class is exercised before the boundary (no send); representative after-boundary cases prove frozen authorized bytes retain their attempt identity. | Named methods in `tests.f3.test_concurrency.DispatchBoundaryRaceTests` with deterministic barriers | Planned |
| 5 | Concurrent workers/duplicate pickup create one possible-dispatch attempt; stale fence cannot append/finish; delayed authorized call remains possible; recovery differs with/without marker | `tests.f3.test_concurrency.WorkerFenceRaceTests`; isolated SQL stale-owner, stale-generation, expired-lease cases in `tests.f3.test_integrity.DispatchFenceSQLTests` | Planned |
| 6 | Kill after marker/before call and after receiver commit/before outcome; both first become uncertain; restart never blindly resends; readback distinguishes accepted from absent | `tests.f3.test_crash_windows.CrashWindowProcessTests` using bounded subprocess barriers and process termination | Planned |
| 7 | v1 response loss plus explicit retry yields one durable acceptance/key/receipt; concurrent retry requests stay bounded; v2 performs no second POST and missing evidence stays uncertain | `tests.f3.test_retry.IdempotentRetryTests`; receiver invocation counts read through independent psycopg | Planned |
| 8 | Late valid receipt supplements unknown after lease expiry; duplicate observation replay; wrong tuple/bytes/receipt and conflicting reuse remain review; original attempt attribution retained; another attempt's rejection cannot bind | `tests.f3.test_reconciliation.ReconciliationEvidenceTests`; named outcome/observation SQL binding failures in `tests.f3.test_integrity.ObservationBindingSQLTests` | Planned |
| 9 | New revision/route cannot evade uncertain or accepted slot; safe cancellation and all-attempt definitive rejection permit guarded advance; conflicting/later rejection cannot erase or release earlier possible effect | `tests.f3.test_slot.ClaimDeliveryControlTests` including every release proof branch and direct guarded-advance SQL cases | Planned |
| 10 | SQL cannot substitute tenant/revision/approval/digest/intent/attempt/receipt, rewind fences, use stale lease, or rewrite history; wrong/inactive callers fail all commands/queries; web CSRF and bounded errors | `tests.f3.test_integrity` names one assertion per relationship/fence/history guard; `tests.f3.test_authorization`; `tests.f3.test_web` | Planned |
| 11 | Fresh processes preserve pending work, unknown attempt, and supplementary receipt; synthetic sentinel absent from logs/errors and present only on authorized detail/payload | `tests.f3.test_durability.FreshProcessDurabilityTests`; `tests.f3.test_web.SensitiveSurfaceTests` | Planned |
| 12 | Receiver outage during delivery/readback and same-ledger restart produce no false completion, lost key, or route fallback; ordinary claim review remains available | `tests.f3.test_process_delivery.ReceiverOutageTests` plus authenticated F2 claim view assertion | Planned |

## Required regression and verification

- Fresh PostgreSQL 17 migrations, `manage.py check`, and migration-drift check.
- Full `tests.f1`, `tests.f2`, and `tests.f3` suite at the exact PR head.
- Separate receiver and worker process commands with bounded synchronization;
  tests must record real transport and independent receiver-ledger evidence.
- Boundary selection for every changed path and at least one concrete use of
  `tests/helpers/workflow_boundary_contract.py` extended for F3.
- Public-artifact review: synthetic fixtures only, no credentials, live URLs,
  private V0 material, or operational records.

## Exact-head evidence

Not executed yet. Populate with commit, commands, counts, process evidence,
failures, and unrun checks before requesting acceptance.
