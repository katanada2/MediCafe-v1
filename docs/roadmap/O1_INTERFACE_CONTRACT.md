# O1 interface and admission proposal

Status: documentation-only, 2026-10-03; NOT runtime admission. Astra retains
architecture/milestone acceptance; coordinator owns publication/coordination;
Sol is sole proposal writer. Scope remains the [O1 card](O1_OPERATOR_REVIEW_CARD.md).
Publication base incorporates merged [PR #12](https://github.com/katanada2/MediCafe-v1/pull/12),
`adb87758cb0f250581c64c3afa92a043ab8a3b6a`: reviewed `4d6ddd1` passed all 45
tooling tests (3.150s, no skip, real Python 3.13 runner), 225 foundation tests
(257.552s), migrations/check/drift and GitGuardian in
[run 37152421036](https://github.com/katanada2/MediCafe-v1/actions/runs/37152421036).
That is prerequisite evidence, not execution of O1. Local synthetic runtime and
browser remain unresolved after the recorded Docker access/daemon failure.

## Accepted read-verification refinement

No interpretation command, new interpretation, reevaluation effect or persisted
evidence is allowed on O1 GET. Astra accepts owner-owned **pure verification
parsing** solely to compare verified retained bytes with immutable candidate
semantic bytes/digest, under existing 1 MiB outcomes limits and window budgets.
Reject digest-only semantic parity: byte integrity alone cannot reproduce the
detail check. Summary/detail/reevaluation may share a pure current-blocker query;
F4 mutation semantics and all acceptance/POST validation remain unchanged.

Do not call unbounded delivery_worklist/outcome_deliveries/archive_heads then
slice. Existing reevaluate_candidate verifies via parse_inbound and unbounded
read_bytes; do not reuse that I/O path. Add bounded owner ports instead.

## Frozen values and exact detail routes

Each owner proposes `operator_review_page(*, actor, organization_id: UUID,
cursor: str | None = None, limit: int = 25) -> ReviewPage`. Actor comes from trusted
authentication, not cursor input. Limits reject bool/noninteger/outside 1–50.
All following values are frozen dataclasses with tuple/frozen children, aware
UTC times, no ORM/lazy properties/dicts/callables. Optional means unknown, not success.

```text
Stamp(started_at: datetime, finished_at: datetime,
      isolation: statement | read_committed | repeatable_read | artifact)
Target(kind: observation | delivery_intent | inbound_candidate | archive_projection, id: UUID)
Evidence(kind: parse_result | delivery_attempt | receiver_observation | accepted_event |
               event_evidence | archive_attempt | archive_readback, id: UUID)
Fact(kind: receiver_acceptance_recorded | lifecycle_accepted | remittance_posted |
           archive_readback_confirmed, target: Target, evidence: tuple[Evidence],
     recorded_at: datetime, checked: Stamp)
Artifact(delivery_id: UUID, artifact_id: UUID, sha256: str, declared_length: int,
         observed_length: int?, state: verified | unavailable | budget_exhausted, checked: Stamp)
Head(head_id: UUID, encounter_id: UUID, projection_id: UUID, version: int)
Lag(head: Head?, state: current_projection | projection_lag | unavailable | refresh_needed,
    fingerprint: str?, checked: Stamp)
Row(target: Target, route_key: str, read_state: observed | unavailable | refresh_needed,
    owner_state: str?, owner_reasons: tuple[str], read_issues: tuple[str],
    history: tuple[Fact], related_ids: tuple[(str, UUID)], evidence: tuple[Evidence],
    classified: Stamp, artifact: Artifact?, enumerated_head: Head?, item_checked: Stamp?, lag: Lag?)
ReviewPage(organization_id: UUID, family: sources | claims | outcomes | archival,
           state: observed | unavailable, section_issue: str?, enumerated: Stamp?,
           requested_limit: int, evaluated_count: int?, rows: tuple[Row],
           has_more: bool?, next_cursor: str?)
```

Route keys are closed below, not arbitrary URLs. Composition supplies page.org
and row.target UUID to the named route parameter; there are no summary POST/actions.
related_ids keys are delivery/parse_result/encounter/claim/claim_revision/intent,
only after scoped owner proof. No inferred attribution, raw patient/source fields,
notes, aliases/receipt values, paths, payload bytes, amounts or credentials escape.

| Family | Target / route key / parameter | SQL keyset order |
| --- | --- | --- |
| sources | observation / observation_detail / observation_id | admitted_at ASC, row_ordinal ASC, observation UUID ASC |
| claims | delivery_intent / claim_delivery_detail / intent_id | authorized_at DESC, intent UUID ASC |
| outcomes | inbound_candidate / outcomes_candidate_detail / candidate_id | interpreted_at DESC, candidate UUID ASC |
| archival | archive_projection / archive_projection_detail / projection_id | encounter UUID ASC, head UUID ASC |

## Windows, cursors and authorization

Proposed sole production writer owns neutral `src/medicafe_v1/read_contracts.py`
(frozen reporting types, stdlib only/no domain imports), owner `queries.py` in
sources/records/claims/outcomes/archival, and `sources/artifacts.py`. Thin composition
is `src/medicafe_v1/operator_review.py`, root `urls.py`, and
`templates/operator_review.html`, not a fifth business owner. Owners import no
views/templates or another owner's ORM; UI never rebuilds blockers. Optional
`outcomes/views.py` read-classifier wiring preserves existing POST guards/commands.

SQL fetches <=limit+1 scalar headers, evaluates <=limit; extra header sets has_more.
Source uses SQL Exists; others filter bounded candidates, no whole-history prefetch/count.
Advance cursor after the last evaluated header, not last displayed exception.
If page budget expires, represent remaining headers as unavailable rows, never
skip them silently. Empty/last window is not whole-family-clear; refresh restarts
enumeration. No global snapshot, total, sort, urgency or completion badge.

Use locked Django timestamped signing, fixed salt `medicafe.o1.cursor.v1`, JSON
only/no compression. Proposed caps: 2,048 UTF-8 bytes and 15-minute age. Payload
has exactly version=1, family, organization UUID, authenticated actor identity,
filter=review-v1, family sort-version, limit and last key. Validate signature,
schema/types/age/scope/order/limit before business-target reads; generic invalid
cursor response, no silent reset/offset/fallback. Signing is not encryption,
snapshot, command authorization or permission for another tenant/actor.

Composition and every owner/related-owner port recheck active membership and
scope before lookup; recheck before rendering. Revocation denies the whole
request, not partial target data. No lock/global transaction pretends immediate
revocation after the last check. Unexpected errors are sanitized owner-unavailable;
authorization is never downgraded to an unavailable section. If enumeration
fails, count/has_more/stamp/cursor are None, never zero/clear/cached success.

## Owner inclusion, reasons and independent history

Include unavailable/refresh-needed rows in addition to these owner predicates.
Technical issues remain separate: owner_unavailable, target_unavailable,
review_budget_exhausted, artifact_budget_exhausted, head_changed,
owner_reason_unrecognized. No arbitrary exception/work text becomes a reason.

| Owner | Exact mapping / inclusion |
| --- | --- |
| sources | No accepted IdentityDecision: state identity_unresolved, derived UI reason identity_review_required (not persisted policy). Resolved observations excluded |
| claims | Preserve effect precedence receiver_conflict, receiver_accepted, uncertain, cancelled, receiver_rejected, blocked, leased, pending, definitely_unsent. Include pending/leased/blocked/uncertain/receiver_conflict or current blocker; reasons receiver_conflict/dispatch_outcome_unknown/work reason then envelope_unavailable, superseded_revision, selected_service_changed, policy_changed, unapproved, ordered/deduplicated |
| outcomes | accepted_fact_recorded vs unaccepted; include no accepted-event evidence or current blocker. Preserve BLOCKER_ORDER: artifact_unavailable, malformed_or_unsupported, conflicting_identity_or_content, unmatched_target, pending_delivery_evidence, pending_sequence_gap, overallocated_line, unaccepted. Bounded pure classifier shares actual F4 meanings, not guessed replacements |
| archival | Preserve evidence_conflict, historically_confirmed, not_queued, unknown_possible_write, pending_execution, failed_execution and exact item reason. Include nonconfirmed item, lag/alert/unknown coverage; only confirmed exact head plus observed current_projection without alerts is excluded |

Historical facts are queried independently of primary current-state precedence:
claims conflict cannot hide old acceptance; archive conflict cannot hide old exact
readback. Use earliest qualifying evidence by recorded_at/UUID with LIMIT 1, not
all attempts/observations. Validate exact org/target/revision or projection/version,
binding tuple, digest/length/bytes through bounded owner evidence rules; an accepted
producer flag alone is not proof. If proof cannot finish, expose unavailable
coverage/evidence IDs, not a confirmed Fact. Immutable accepted-event links/postings
remain historical, never liability/cash or current actionability. Do not use
historical_delivery_attribution's current-conflict rejection to erase that history.

## Bounded artifact and pure candidate verification

Sources proposes verify_delivery_artifact_for_review with actor/org/delivery and
budget. Resolve exact scoped delivery/artifact and server-generated storage key;
reject unsafe/out-of-store/nonregular/unverifiable handles. Existing owner admission
limits are 5 MiB intake, 1 MiB synthetic outcomes. Check declared length <= owner
limit, stream SHA-256 in <=64 KiB chunks with <=declared length+1 sentinel bytes.
No read_bytes, repair/promotion, interpretation or evidence row. Short/oversize,
digest mismatch or changed handle metadata is existing artifact_unavailable;
budget exhaustion is unavailable/artifact_budget_exhausted, not corruption/success.
Successful evidence is exact bytes' digest/length, not mtime. No private data escapes.

After successful streaming, outcomes may consume a bounded <=1 MiB owner-internal
buffer for pure parse_inbound and compare semantic bytes/digest with exact retained
candidate. Bound retained semantic data and <=100 lines before materialization.
Source-private `verified_delivery_bytes_for_review(*, actor, organization_id,
delivery_id, budget)` returns frozen `VerifiedReviewDelivery(verified: VerifiedDeliveryBytes,
checked: Stamp)` solely to outcomes. Capture its <=1 MiB buffer during the same
verified stream; parse those exact bytes, never reopen/re-read (TOCTOU). UI-facing
Artifact stays metadata-only; private buffered values never reach composition.
Preserve actual _verify_candidate_bytes failure mapping (including parse failure
mapped to artifact_unavailable), conflict checks, historical attribution,
predecessor/line allocation and accepted-evidence rules/order. Do not reclassify
every parser error as malformed_or_unsupported or create new financial policy.
No interpretation/reevaluation command, DB write, network or owner lock; bounded
pure classifier can serve detail too without changing command admission guards.

## Actual costs, lag snapshots and open budget decision

Proposed review caps requiring Astra acceptance: 1,000 materialized related rows
and 24 SQL statements/item, 250 statements and 64 MiB examined/page; SQL timeout
250 ms/statement, cooperative 2-second page deadline. Count history/related binary
reads, not just headers; aggregates can scan more database rows than they return.
Check actual database octet length before bounded binary fetch: claim/receiver
1 MiB, candidate semantics 1 MiB, archive projection/readback 2 MiB. File syscall
blocking is not forcibly cancelled by a cooperative deadline; no hard I/O bound
is claimed. Deadline/row/query/byte exhaustion is unavailable, never truncated truth.
These proposed caps are not measured SLOs or constant-cost guarantees.

Archive bounded review_current_lag takes enumerated Head and opens standalone
read-only REPEATABLE READ, rejecting outer atomic. Bounded owner snapshot variants
must preserve complete existing F4 fields/order/serialization; use LIMIT remaining
budget+1 and grouped posting sums, not unbounded snapshot queries then slicing.
Complete snapshot encoding/hash <=2 MiB must equal the existing F4 fingerprint.
If complete equivalence/cost cannot be assured, return unavailable/fingerprint None
and stop for architect review; never hash a prefix/omit history/guess current.
Exact query plan/cost feasibility is an admission gate, not permission for an
unrelated snapshot refactor. Retain independently stamped enumeration, exact
item proof and lag Head; compare org/encounter/head/projection/version. Changed or
missing head yields refresh_needed/head_changed, never cross-attach newer evidence.

## Named future evidence and admission stop

O1-01 SQL windows/UUID ties; O1-02 signed cursor tamper/expiry/cross-scope;
O1-03 empty/last window not clear; O1-04 conflict retains exact historical acceptance;
O1-05 same-target summary/detail semantic parity with bounded pure parse and wrong
candidate fail-closed; O1-06 sentinel/digest/path/byte-budget read/parse limits;
O1-07 forced enumeration/item/lag head races; O1-08 full-reference fingerprint
equivalence or unavailable on large history; O1-09 outage/revocation denial;
O1-10 repeat GET/restart counts and intercepted INSERT/UPDATE/DELETE/commands/network
all zero; O1-11 frozen/route/privacy graph; O1-12 synthetic browser navigation.
Use concrete workflow-boundary helper tests and register implemented O1 evidence
only after admission. These are planned scenarios, not executed tests. Exact-head
3.13/PostgreSQL owner/view/interleaving/full-regression/scanner checks and separate
browser evidence remain required. No source/selector/historical CI substitutes.

Freeze accepted budgets/cursors and bounded snapshot feasibility with this card,
then explicitly admit only owner queries/artifact ports/bounded snapshot variants,
composition/navigation and synthetic tests. No schema/dependency/worker/command
change. Tooling is accepted; usable runtime, interface acceptance and O1 admission
remain gates. Stop for policy/effect expansion, unsafe data or infeasible complete
bounds. Deliver local proposal only; no push, application code, installs or services.
