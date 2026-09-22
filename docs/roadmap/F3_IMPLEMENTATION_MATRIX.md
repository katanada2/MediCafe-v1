# F3 implementation and acceptance matrix

Status: Astra accepted the runtime implementation and evidence at `8b42173`.
At that evidence checkpoint, PR #8 was ready for normal review and not yet
merged. Executed evidence below is tied to an exact commit and CI run; source
inspection is not test execution.

## Settled seams

- Claims owns immutable `DeliveryIntent`, `DeliveryAttempt`, `AttemptOutcome`,
  and `ReceiverObservation` records, the guarded `ClaimDeliveryControl` slot,
  and the single mutable, fenced `DeliveryWork` row.
- A claims receipt records the effective actor and time. Its typed F3 result
  references are reciprocally bound to the intent/work in the same transaction;
  coalescing receipts never replace the initial authorizer.
- Final dispatch admission first locks and validates membership as an
  authentication prelude compatible with existing service commands, then locks
  encounter, policy, claim, slot/intent, and work. It validates the live
  database-time lease and fencing generation before committing a
  possible-dispatch attempt. The HTTP call occurs after commit.
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

| # | Contract scenario and subcases | Executable evidence | State |
|---|---|---|---|
| 1 | v1/v2 exact bytes, independent ledger, receiver and worker restart | `test_process_delivery.ProcessDeliveryTests.test_exact_bytes_each_receiver_survive_receiver_and_worker_restart` plus `assert_delivery_boundary` | Executed at `8b42173` |
| 2 | Replay/conflict/coalescing and guarded case slot | `test_commands.DeliveryCommandTests.test_request_receipts_replay_conflict_and_coalesce`; `test_slot.ClaimDeliveryControlTests`; `test_concurrency.DeliveryRequestRaceTests.test_competing_revision_requests_create_only_current_slot_intent` | Executed at `8b42173` |
| 3 | Pre-dispatch cap and no-send blockers | `test_worker.WorkerPreflightTests.test_transient_preflight_limit_records_three_definitely_unsent_attempts`, `test_revoked_effective_authorizer_blocks_before_marker`, `test_invalid_receiver_route_blocks_before_marker`, `test_corrupt_envelope_read_fails_closed_before_send`; `test_authorization_boundary.DispatchBoundaryRaceTests.test_each_mutation_class_committed_before_marker_prevents_send` | Executed at `8b42173` |
| 4 | Domain/membership races before boundary and frozen state after boundary | `test_authorization_boundary.DispatchBoundaryRaceTests.test_each_mutation_class_committed_before_marker_prevents_send`, `test_policy_change_after_marker_keeps_frozen_authorized_bytes`, `test_membership_lock_prelude_avoids_service_dispatch_deadlock` | Executed at `8b42173` |
| 5 | Duplicate pickup, fencing, recovery with/without marker, delayed call | `test_concurrency.WorkerFenceRaceTests`; `test_integrity.DispatchFenceSQLTests`; `test_worker.WorkerPreflightTests.test_expired_lease_without_marker_is_released_to_new_generation` | Executed at `8b42173` |
| 6 | Actual process termination at both required crash windows | `test_crash_windows.CrashWindowProcessTests.test_kill_after_marker_before_call_recovers_unknown_without_send`, `test_kill_after_receiver_commit_before_outcome_recovers_then_reconciles` | Executed at `8b42173` |
| 7 | v1 idempotent retry, concurrent retry, v2 no resend | `test_crash_windows.CrashWindowProcessTests` response-loss tests; `test_reconciliation.ReconciliationEvidenceTests` retry tests; `test_concurrency.WorkerFenceRaceTests.test_concurrent_retry_commands_schedule_once` | Executed at `8b42173` |
| 8 | Late/duplicate/conflicting evidence and original attribution | `test_reconciliation.ReconciliationEvidenceTests`; `test_integrity.DispatchFenceSQLTests` evidence tests | Executed at `8b42173` |
| 9 | Slot exclusion and safe monotone release | `test_slot.ClaimDeliveryControlTests` four named tests | Executed at `8b42173` |
| 10 | SQL integrity, authorization, CSRF and bounded errors | `test_integrity.DispatchFenceSQLTests`; `test_relationships.F3RelationshipSQLTests`; `test_web.DeliveryWebTests`; `test_authorization.DeliveryAuthorizationTests` | Executed at `8b42173` |
| 11 | Fresh processes preserve pending/unknown/supplementary evidence; payload sentinel stays out of process output | `test_process_delivery.ProcessDeliveryTests.test_exact_bytes_each_receiver_survive_receiver_and_worker_restart`; `test_crash_windows.CrashWindowProcessTests.test_v1_commit_response_loss_then_explicit_retry_has_one_durable_acceptance` with fresh `query_state` processes; `test_process_delivery.ProcessDeliveryTests.test_synthetic_payload_sentinel_is_absent_from_process_output` | Executed at `8b42173` |
| 12 | Receiver outage/readback failure without false completion or UI loss | `test_process_delivery.ReceiverOutageTests.test_receiver_outage_has_no_false_completion_resend_or_route_fallback` | Executed at `8b42173` |

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

- `3931883`, CI `35709767966`: migrations/check/drift passed; 100 tests ran
  with three failures (one shared fixed receipt fixture and two claim/source URL
  collisions). No migration or runtime error remained after diagnosis.
- `4251878`, CI `35711086917`: migrations/check/drift passed; 118 tests ran,
  117 passed and one lease-expiry fixture errored because migration `0008`
  correctly rejected directly backdating a live lease. Secret scan passed.
- `8bc9b84eea0882f02b0a1a93f79147b770f66f61`, CI `35711730214`:
  migrations, Django check, migration drift, F2-to-F3 upgrade regression, and
  all 120 F1/F2/F3 tests passed in 108.865 seconds.
- `4c567d698caabb20d7eb37369f614566786c95e5`, CI `35713012171`:
  migrations/check/drift and all 130 tests passed in 130.189 seconds, including
  both actual worker-kill windows and the membership/Encounter lock-order case.
- `c333e603bc324fae22f3f938df18feb09a26c1a2`, CI `35713520220`:
  migrations/check/drift passed; 132 of 133 tests passed in 133.275 seconds.
  The sole error was a test-only sentinel service code rejected by the existing
  synthetic policy; the next packet uses the already serialized synthetic
  patient UUID instead. Competing-revision and corrupt-read cases passed.
- `8b42173315b0b042a4aa718d10dd6c0175ac088a`, CI `35715327434`:
  fresh PostgreSQL 17 migrations, Django check, migration drift, F2-to-F3
  upgrade, and all 143 F1/F2/F3 tests passed in 142.246 seconds. This exact run
  includes all twelve mapped scenarios, all ten relationship-class negatives,
  both real worker-kill windows, and the corrected payload sentinel case.

At the `8b42173` evidence checkpoint, PR #8 remained unmerged and the final
documentation head still required its own normal checks. This matrix does not
claim deployed qualification, live interoperability, production readiness, or
F4 authorization. Follow the PR link in the handoff for current repository state.
