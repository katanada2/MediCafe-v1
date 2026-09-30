# Delivery handoff

## Objective and authority

Deliver the public synthetic foundation under the [charter](../architecture/CHARTER.md). Astra owns architecture, consequential decisions, milestone acceptance and merge. Sol owns bounded delivery, with at most two implementation lanes and one writer per shared seam. Public source and synthetic evidence do not establish production qualification or transfer V0 authority.

## Current state and entry gates

- [PR #10](https://github.com/katanada2/MediCafe-v1/pull/10) merged on
  2026-09-29 at 19:13:48 UTC as `7432930536dfc26b48f3d57077256cc7e244c377`.
  Astra accepted F4; the public-synthetic F1–F4 foundation is complete.
  Final reviewed documentation head `dbaeb6c91aa4893c0dbda3d801e5be5d288c4cbb`
  passed [run 36617022085](https://github.com/katanada2/MediCafe-v1/actions/runs/36617022085):
  225 tests, including 76 F4 tests, in 262.205 seconds, with fresh PostgreSQL 17
  migrations, system checks, migration-drift checks and GitGuardian green.
  The earlier runtime-head evidence below remains distinct from this final run.
  This merged checkpoint supersedes historical premerge, pause, no-export and
  no-PR instructions below; those sections remain dated historical evidence.
- Charter PR #1 is merged at `c24bbe5fe0bab3079b6c569e91143ccc23afced8`.
- F1 PR #2 is merged at `cceec754ff00e754de41757cad49696b7173d0b7`; Astra accepted the synthetic intake/identity milestone on 2026-09-22.
- Astra accepted F2 on 2026-09-22 and merged [PR #6](https://github.com/katanada2/MediCafe-v1/pull/6) at `87526383052ebb68395fe1fe14f26f901bd5c952`. Its bounded service/claim authority is synthetic only.
- F3 is accepted and merged through PR #8 at `0033e5c892a40535fb06200432cb62e68cfba69b`; final evidence is recorded below. F4 implementation is admitted only from main containing the merged [F4 admission record](F4_IMPLEMENTATION_ADMISSION.md). An unmerged branch is not authorization. No real data, live integration, migration from V0, deployment or production authority transfer is authorized.

## F4 accepted foundation and remaining qualification

The merged implementation covers the complete public-synthetic F4
card and maps
all twelve acceptance groups in the [F4 matrix](F4_IMPLEMENTATION_MATRIX.md):
strict inbound parsing and attribution; replay/conflict namespaces; historical
delivery evidence and receipt-anchor ordering; lifecycle correction sequences;
conserved multi-line and concurrent posting; bounded financial semantics;
relationship, authorization, CSRF and form-retention guards; restart durability
and redaction; coherent projection snapshots and head races; independent archive
readback; bounded retries/fences; and partial/outage recovery. Source review is
complete. [PostgreSQL run 36615748027](https://github.com/katanada2/MediCafe-v1/actions/runs/36615748027)
passed fresh PostgreSQL 17 migrations, Django system checks, migration-drift
verification and all 225 F1–F4 tests, including 76 F4 tests, in 254.325 seconds
at exact runtime head
`7e7bfebf34ec7109dc51fdeab0556339d616e3d3`.

The locked verification stack is Python 3.13.15, Django 5.2.17, psycopg 3.2.13,
PostgreSQL 17 and uv 0.12.13. Earlier diagnostic runs remain useful evidence:
run `36614797914` executed 224 tests in 255.335 seconds and passed both production
repairs, with only the now-fixed hidden bound retry form; run `36615037902`
executed 225 tests in 253.590 seconds and additionally passed the controlled
claims-reconciliation/capture interleaving, again with only that known form
failure. Neither failed run is acceptance evidence.

Still unrun are a manual browser walkthrough, local PostgreSQL execution and all
private/deployed qualification. Public-synthetic acceptance does not establish
real transport or payer schemas; correction, reversal or coordination-of-benefit
semantics; opening balances; pricing or coverage policy; patient responsibility
or communications; cash/deposit reconciliation; Medisoft mapping; scheduling or
retention policy; identity-correction breadth; qualified recovery; deployment;
or private migration qualification. These remain explicit future product and
qualification gaps. No later milestone work, live integration, private data,
production readiness, compliance claim or V0 authority transfer is included.

## Post-foundation planning handoff — 2026-09-30

The user authorized a bounded Sol planning continuation from the merge SHA above.
The [continuation packet](POST_FOUNDATION_CONTINUATION.md) ranks remaining work
and recommends [O1 operator exception review](O1_OPERATOR_REVIEW_CARD.md).
O1 is a draft for Astra review, not runtime admission. Sol is sole writer for
this documentation packet; existing foundation branches and owner seams remain
preserved. No runtime, schema, dependency, integration, deployment, push or PR
creation is authorized by this continuation. Astra retains architecture,
consequential decisions and acceptance.

The local browser assessment found no already available verified runtime/database
environment; exact bounded observations and the reproducible walkthrough plan
are in the packet. No browser or local PostgreSQL success is claimed. The prior
225-test suite was not repeated for documentation-only changes. Registry-backed
workflow verification is not integrated yet; this packet does not claim it.

## F1 acceptance evidence

Accepted implementation head: `56604ab6526c1ab917224cb9b6f0709b1161a06e`, branch `codex/f1-attributable-intake`, delivered through task `01a09b4c-b9cb-7f83-bc7b-2dbd2c3b717d`.

[PostgreSQL run 35687948907](https://github.com/katanada2/MediCafe-v1/actions/runs/35687948907) passed fresh PostgreSQL 17 migrations, Django system checks, migration-drift detection and all 33 F1 tests in 25.747 seconds. GitGuardian passed on the same head. Astra inspected the corrections and exact-head results, resolved all three automated review threads, and merged through normal branch protection.

Corrections cover upload size validation before application materialization with bounded chunk accumulation; short CSV rows becoming stable failed ParseAttempts; and request replay bound to the exact observation. Earlier reviews also established immutable history, current artifact verification, concurrency accounting and form-error preservation. Existing required check `postgres-foundation` remains enforced.

This is executed synthetic integration evidence. It is not a browser walkthrough, deployed test, payer interoperability or production qualification. The upload correction does not limit proxy ingress or Django's pre-view temporary spooling; production ingress controls remain a later deployment concern. No local PostgreSQL test success is inferred from CI.

## F2 delivery assignment

Read the [F2 card](F2_SERVICE_CLAIM_CARD.md), charter and ADR 0001 initially. Start from main containing the merged F2 planning commit in a dedicated worktree/branch. Its presence on main confirms the entry gate; no additional planning approval is required. Outcome, ownership, interfaces, privacy classification, dependencies, acceptance evidence and stop conditions are all specified by the card.

One owner implements exercised records/claims and shared wiring. A disjoint fixtures/test lane may begin after the owner fixes schema and query seams. Use Terra or Luna for settled bounded work as useful; do not add recursive management layers. Keep changes synthetic and do not copy private V0 material.

Return a draft PR and evidence packet to Astra. Do not merge or begin F3. Mechanical choices inside the card are delegated; changes to identity, authority, policy meaning, owner boundaries or external-effect rules require architectural review.

## F2 implementation evidence

Implementation branch `codex/f2-service-claims`, [PR #6](https://github.com/katanada2/MediCafe-v1/pull/6), was delivered through task `01a09b4c-b9cb-7f83-bc7b-2dbd2c3b717d`. Verified implementation head `de1d16681c08781c4de705c5ecc93227f41822f3` is rebased on merged F3/F4 planning baseline `8973724df9e36ae3f27538b9e51316152e518dfd`.

[PostgreSQL run 35697177174](https://github.com/katanada2/MediCafe-v1/actions/runs/35697177174) passed fresh PostgreSQL 17 migrations, Django system checks, migration-drift detection and all 68 F1+F2 tests in 54.249 seconds. GitGuardian passed on the same head.

The evidence covers the ten F2 card groups: append-only service acceptance/correction/exclusion/reinstatement with evidence provenance; canonical retries and a shared request namespace; deterministic ordered claim snapshots and bounded arithmetic; immutable envelopes and restart durability; generation-bound policy compare-and-set; historical approval with fixed-order current actionability; PostgreSQL relationship, history, head and receipt constraints; tenant, inactive-membership and CSRF denial; serialized competing corrections/preparations/approvals/policy changes including a forced lock-order schedule; and authenticated CSV/DOCX operator flows, redaction, invalid-selection atomicity, maximum-size cases and setup paths.

The final edge matrix explicitly exercises policy no-op replay after later activations, same-version policy return without approval revival, equal-valued selected-service correction invalidation, corrected reuse of a rejected request UUID, wrong or unresolved same-organization evidence, and named wrong-aggregate/patient/encounter database constraints. It also proves that claim lines can be inserted only while a revision is under construction, current/approved/historical revisions are sealed, cross-member request races converge without raw integrity errors, correction forms preserve the current evidence decision, and an approval POST cannot substitute another claim's revision while exact same-claim historical replay remains available. Failed intermediate run 35695248247 had 62 of 63 tests pass and exposed a fixture that collided with a uniqueness constraint before reaching the intended service/revision composite constraint; the fixture was corrected before the later green runs.

Of four final automated-review findings, three required bounded corrections: construction-only line insertion, current-evidence form initialization and claim/revision presentation binding. The proposed cross-member receipt race was refuted by the existing shared-organization lock and is now covered by a two-member, two-encounter concurrency test that yields one mutation and receipt plus one domain conflict, without a raw integrity error.

This is public-synthetic repository and PostgreSQL integration evidence. It is not a manual browser walkthrough, deployed qualification, real payer interoperability, production readiness, compliance evidence or authority transfer from V0. No external dispatch exists, and F3/F4 runtime remains out of scope.

## F3 admission and delivery assignment

Astra accepts the reviewed [F3 delivery contract](F3_DELIVERY_CARD.md) against the merged F2 implementation. Its exact-envelope, approval, service-dependency and policy-generation interfaces remain the authority at the future dispatch boundary. Merge of this record admits implementation of the complete public-synthetic F3 scope. It does not establish F3 completion or acceptance; no F4 runtime is admitted.

F2 acceptance used implementation head `de1d16681c08781c4de705c5ecc93227f41822f3`, final documentation head `19dff27f5a01f5bf06cc375bdf46ef8b9d1c7b7d`, the 68-test implementation run above, and green [final-head run 35697574634](https://github.com/katanada2/MediCafe-v1/actions/runs/35697574634). All four automated-review threads were resolved after focused source and PostgreSQL verification. The final merge used normal repository protections.

Sol owns exercised claims, worker, adapter, migrations and operator wiring. Start a dedicated worktree and `codex/` branch from main containing this admission. A disjoint receiver/fixtures/test lane may begin only after Sol records stable adapter and evidence interfaces; at most two implementation lanes and one writer per shared seam. Astra owns consequential decisions, acceptance and merge. Inputs are the charter, stack decision, accepted F1/F2 and detailed F3 card. Privacy classification is public synthetic only.

Deliver the full F3 contract: durable intent and guarded claim effect slot, explicit dispatch authorization, fenced work and immutable attempts/outcomes, a separate loopback receiver with its own PostgreSQL evidence, v1 idempotent retry, v2 uncertainty without resend, independent reconciliation and operator explanations. Preserve F1/F2 behavior and the public boundary. Do not substitute mocked producer state for actual separate-process receiver observations.

Map every numbered F3 acceptance scenario and its subcases to executable evidence before declaring the packet complete. Include direct SQL relationship/fence tests with isolated named failures, deterministic competing-worker/crash schedules, actual receiver readback, fresh-process durability and the full regression suite. Keep the matrix in the existing handoff or milestone setup document; distinguish executed, source-reviewed and unrun evidence. A green partial suite does not establish milestone completion.

Return a draft PR, exact-head PostgreSQL/process evidence, setup, remaining production gaps and reviewed public artifacts. Stop before merge or F4 implementation, or escalate a contract contradiction or two failed attempts at one approach. Mechanical choices inside the contract are delegated. No live endpoints, credentials, private V0 material or deployment configuration are authorized.

## F3 implementation evidence

Astra accepted the public-synthetic F3 runtime implementation and evidence at
`8b42173315b0b042a4aa718d10dd6c0175ac088a`. [PostgreSQL run 35715327434](https://github.com/katanada2/MediCafe-v1/actions/runs/35715327434)
passed fresh PostgreSQL 17 migrations, Django system checks, migration-drift
detection, the F2-to-F3 upgrade regression, and all 143 F1/F2/F3 tests in
142.246 seconds.

The executed matrix covers exact v1/v2 bytes and independent receiver storage;
request replay/coalescing and case-slot exclusion; all pre-dispatch blockers;
domain and membership races; fencing, stale completion, and delayed physical
calls; actual process termination on both sides of the external-effect boundary;
v1 explicit retry and v2 no-resend; late/conflicting evidence; monotone slot
release; command/query authorization, CSRF, and relationship-class SQL guards;
fresh-process durability and output redaction; and receiver outage without false
completion. See the [F3 matrix](F3_IMPLEMENTATION_MATRIX.md) and reproducible
[F3 walkthrough](F3_SETUP.md).

At this 2026-09-22 evidence checkpoint, PR #8 was ready for review and not yet
merged. This acceptance is synthetic integration evidence, not deployed
qualification, live payer interoperability, compliance evidence, production
readiness, or authority transfer from private V0. F4 runtime remains closed
until a separate explicit reviewed admission record.

## Evidence packet and escalation

Report branch, exact head, PR, changed responsibility, setup commands, resolved versions, executed tests/results, failed or unrun checks, contract coverage and open gaps. Distinguish source review from execution and local evidence from deployed qualification. Keep private operational links and source data out of this file.

For an escalation, identify the conflicting card paragraph, attempted approach, observed failure and one bounded alternative. Escalate a contract contradiction or two failed attempts at one approach rather than redesigning the charter.

## Decision and review record

F1 preserved explicit delivery identity, atomic create-and-resolve retries, immutable terminal ParseAttempts and success-only ParseResults. Computation stays outside the Delivery lock; every completed computation records a terminal attempt, only the first success creates canonical observations, and true replay creates no attempt. Historical decisions remain distinct from current artifact availability.

Astra's F2 design and Luna's focused review settled service correction provenance, exact claim membership, immutable envelopes and historical-versus-current approval. Policy activation generations prevent revival of old approval. The follow-up closes policy-switch/no-op retry receipts, database head rewind prevention, explicit cross-row relationship constraints and canonical intent encoding. No concrete contradiction remained in the follow-up review. Automated review then clarified post-merge admission wording and a fixed precedence for combined actionability blockers. These are reviewed contracts, not executed F2 evidence.

Deferred alternatives remain explicit in the card: clinical inference, real coding/coverage policy, automatic line inclusion or approval transfer, broad identity correction, a generic policy engine and dispatch infrastructure.

## Associated PR history

- [F4 implementation PR #10](https://github.com/katanada2/MediCafe-v1/pull/10):
  at the 2026-09-29 premerge checkpoint, open accepted-for-merge candidate at
  `7e7bfebf34ec7109dc51fdeab0556339d616e3d3`; green exact-head
  [run 36615748027](https://github.com/katanada2/MediCafe-v1/actions/runs/36615748027)
  passed 225 tests in 254.325 seconds. Synthetic F4 milestone acceptance remains
  conditional on governed merge.
- [F4 admission PR #9](https://github.com/katanada2/MediCafe-v1/pull/9):
  verified merged at `5b351bd5856f138b4eca2809ad2a40c6e9bdb354`; admitted the bounded
  public-synthetic F4 implementation without establishing completion.
- [F3 implementation PR #8](https://github.com/katanada2/MediCafe-v1/pull/8): accepted and verified merged at `0033e5c892a40535fb06200432cb62e68cfba69b`; final implementation head `f5dfafe6ecc42f51a8b2b27c7fdea526432673d4` passed green run `35719081505` (149 tests in 147.898 seconds). Earlier diagnostic and green history is retained in the F3 matrix.
- [F3 admission PR #7](https://github.com/katanada2/MediCafe-v1/pull/7): verified merged 2026-09-22 at `07bad8f39a631ced75b1f5df829c3a6cbb84d09e`; admits the public-synthetic F3 implementation assignment above without admitting F4.
- [F2 implementation PR #6](https://github.com/katanada2/MediCafe-v1/pull/6): accepted and verified merged 2026-09-22 at `87526383052ebb68395fe1fe14f26f901bd5c952`; implementation and final-head evidence above.
- [F4 planning PR #5](https://github.com/katanada2/MediCafe-v1/pull/5): verified merged at `8973724df9e36ae3f27538b9e51316152e518dfd`; planning only, runtime gate closed.
- [F3 planning PR #4](https://github.com/katanada2/MediCafe-v1/pull/4): verified merged at `a5a74e2f3d4e870aaa87afd6dc20bc0233ec69c2`; planning only, runtime gate closed.
- [F2 contract PR #3](https://github.com/katanada2/MediCafe-v1/pull/3): F2 admission decision: merging this record accepts the card and opens implementation. On main containing this record, F2 is admitted.
- [F1 implementation PR #2](https://github.com/katanada2/MediCafe-v1/pull/2): verified merged 2026-09-22, accepted evidence above.
- [Charter PR #1](https://github.com/katanada2/MediCafe-v1/pull/1): verified merged; established the initial F1 entry gate.

## Final F3 acceptance and F4 handoff

As of 2026-09-22, [F3 PR #8](https://github.com/katanada2/MediCafe-v1/pull/8) is accepted and verified merged at `0033e5c892a40535fb06200432cb62e68cfba69b`. Final implementation head `f5dfafe6ecc42f51a8b2b27c7fdea526432673d4` passed [run 35719081505](https://github.com/katanada2/MediCafe-v1/actions/runs/35719081505): all 149 tests in 147.898 seconds, PostgreSQL migrations, Django checks and drift verification; GitGuardian passed. All three inline review findings were resolved after focused code/regression review. This supersedes the earlier dated premerge checkpoint, whose evidence remains historical.

The [F4 admission record](F4_IMPLEMENTATION_ADMISSION.md) defines the next entry gate, claims-owned historical attribution and serialization contract, and Sol's ownership/checkpoints. Runtime starts only from main containing that merged record. Astra retains final acceptance and merge ownership. V0 production authority remains unchanged.

## F4 local implementation pause checkpoint

F4 implementation was admitted by merged [PR #9](https://github.com/katanada2/MediCafe-v1/pull/9)
at `5b351bd5856f138b4eca2809ad2a40c6e9bdb354`. Sol implemented the
public-synthetic outcomes and delayed-archive slice on local branch
`codex/f4-outcomes-archive`. Durable checkpoints are `684f2fa` (relationship
design), `4801176` (outcomes foundation), `0a5ae6d` (archive workflow and
relationship guards), and `3171ec0` (operator/process/evidence surfaces before
this handoff clarification).

The local tree provides strict lifecycle/remittance interpretation; historical
delivery attribution; immutable accepted events and conserved posting entries;
coherent REPEATABLE READ archive capture and lag comparison; fenced bounded
archive attempts; independently verified readback with wrong-item conflict
retention; authenticated target-bound operator forms; a separate loopback
PostgreSQL archive target; setup documentation; and F1–F4 CI wiring.

Executed local evidence is limited to AST parsing of 103 Python files, Django
`manage.py check`, offline migration-state drift detection (`No changes
detected`), and `git diff --check`, all green. The PostgreSQL-backed F4 tests and
separate-process tests were not run locally because no configured local
PostgreSQL service was available. No CI result or browser walkthrough is
claimed.

Publishing is also incomplete. The attempted push of
`codex/f4-outcomes-archive` was rejected before execution by the sandbox approval
reviewer because this turn lacked explicit user authorization to export the
repository to its GitHub remote. No draft PR exists and no push occurred. Resume
by obtaining explicit authorization, pushing the branch, opening a draft PR,
and running the exact-head PostgreSQL 17 workflow.

The [F4 matrix](F4_IMPLEMENTATION_MATRIX.md) lists present test-source mappings
and the required scenarios still missing as isolated deterministic tests:
concurrent receipt-anchor orderings, RC/RR direct-SQL overposting, capture versus
posting snapshot races, lease/worker fence races, complete archive relationship
classes, concurrent archive heads, and batch order/replay conflicts. F4 is not
accepted at this pause point. No later milestone, deployment, private-data work,
live integration, production readiness, compliance evidence, backup
qualification, or V0 authority transfer is implied.

On the 2026-09-25 F4 resume, the two final bounded static-review findings were
closed locally: every transition into `leased` must now originate at `pending`
with a freshly incremented fence, and non-string archive send statuses now
produce bounded `archive_response_invalid` unknown results. Focused direct-SQL
and malformed-response regressions accompany the changes. PostgreSQL execution
evidence remains pending with the broader acceptance scenarios below.

Resume from this exact local workspace and ownership boundary:

```powershell
Set-Location C:\Users\danie\.codex\worktrees\a1c6\MediCafe-v1\f4
git -c safe.directory=C:/Users/danie/.codex/worktrees/a1c6/MediCafe-v1/f4 status --short
git -c safe.directory=C:/Users/danie/.codex/worktrees/a1c6/MediCafe-v1/f4 log -5 --oneline
```

Sol remains the sole production writer for F4; Astra owns architecture,
acceptance, publication authorization and merge. On resume, fix only the two
open review findings and the explicitly listed missing acceptance scenarios,
then run the static checks and the full PostgreSQL suite. Only after explicit
user authorization to export this repository should the branch be pushed and a
draft PR/CI run created. Preserve the existing F1–F3 history and do not begin a
later milestone.

## F4 local acceptance-coverage checkpoint

On 2026-09-29, local F4 work resumed with explicit authorization while the
separate GitHub export authorization remained pending. The preserved worktree
had no active terminal session or repository lock and still pointed at
`93acac9`. Sol retained sole production/shared-test ownership; no second writer
or later-milestone work was started.

The local evidence packet now maps every clause in the twelve card groups to a
named test in [the F4 matrix](F4_IMPLEMENTATION_MATRIX.md). Added source covers
strict input bounds and failure atomicity; source/event/request replay and
conflict; historical attribution mismatches and current-head changes;
predecessor arrival and stream conflict; multi-event/multi-line conservation;
exact financial display/non-inference; full command/query authorization and
mutation CSRF; fresh-process durability and sentinel exclusion; both
receipt-anchor orderings; READ COMMITTED and stale REPEATABLE READ direct SQL;
coherent capture/posting and initial/successor head races; named relationship
guards; partial archive batches; receiver/version/byte conflicts; batch and
manual-retry replay; competing workers; expired fences; delayed older target
head protection; and canonical review/posting during an archive outage.

Database-free execution on the commit containing this record consists of
Python compilation across `src` and `tests`, green `manage.py check`, offline
migration drift reporting `No changes detected`, and green `git diff --check`.
The focused malformed archive-response `SimpleTestCase` passed through the
configured Django runner (one test in 0.056 seconds, no database). A preliminary
direct `unittest` command failed before collection because `src` was not on
`PYTHONPATH`; it did not execute a test. The local PostgreSQL history probe
timed out once, so no repeated local PostgreSQL attempts were made.

The workflow-boundary registry, change-surface policy and selector scripts
named by the review skill are not integrated yet in this repository. Concrete
outcome/archive tests use `tests/helpers/workflow_boundary_contract.py`, and the
matrix does not present registry-backed selection as evidence.

All 70 F4 PostgreSQL/process tests and the complete F1–F4 regression suite
remain unrun, as does fresh exact-head PostgreSQL 17 CI. Therefore this is a
reviewable local source/evidence checkpoint, not F4 acceptance, production
readiness, compliance evidence, live integration, private-data qualification,
deployment authority or V0 authority transfer. Do not push or create a PR until
the user separately authorizes repository export.
