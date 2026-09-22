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
  skill are absent from this repository. F4 will extend and use
  `tests/helpers/workflow_boundary_contract.py` in concrete same-target and
  fail-closed feature tests; absent registry infrastructure is not claimed as
  integrated evidence.

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
statements. It never creates an anchor for an unmatched target. Read-only
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

| Group | Primary executable evidence |
|---|---|
| 1–2 | `tests/f4/test_outcomes.py`: strict interpretation, duplicate keys, replay, canonical money spellings and no double posting |
| 3–4 | `tests/f4/test_outcomes.py`: complete historical conflict scan, retained accepted fact, ordered reevaluation, lifecycle gap and direct sequence-zero denial |
| 5–6 | `tests/f4/test_outcomes.py`: conserved entries, atomic overallocation denial, precision normalization and typed components |
| 7 | `tests/f4/test_outcomes.py` and `tests/f4/test_web.py`: relationship-class SQL guards, page-target retention, tenant authorization inherited from owner queries and CSRF denial |
| 8 | `tests/f4/test_process_archive.py` plus F1–F3 regressions: fresh process persistence/restart and bounded non-payload command output |
| 9 | `tests/f4/test_archive.py`: coherent capture/replay, nested-transaction denial and current fingerprint lag |
| 10 | `tests/f4/test_archive.py` and `tests/f4/test_process_archive.py`: exact independent readback, send-success denial, wrong-item conflict and separate target restart |
| 11 | `tests/f4/test_archive.py`: bounded automatic retry, pending-grant coalescing, reported-attempt preservation, immutable-unknown late confirmation and fence guard |
| 12 | `tests/f4/test_process_archive.py`: unavailable archive leaves canonical remittance available, followed by exact recovery |
