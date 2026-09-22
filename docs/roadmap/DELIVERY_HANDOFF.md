# Delivery handoff

## Objective and authority

Deliver the public synthetic foundation under the [charter](../architecture/CHARTER.md). Astra owns architecture, consequential decisions, milestone acceptance and merge. Sol owns bounded delivery, with at most two implementation lanes and one writer per shared seam. Public source and synthetic evidence do not establish production qualification or transfer V0 authority.

## Current state and entry gates

- Charter PR #1 is merged at `c24bbe5fe0bab3079b6c569e91143ccc23afced8`.
- F1 PR #2 is merged at `cceec754ff00e754de41757cad49696b7173d0b7`; Astra accepted the synthetic intake/identity milestone on 2026-09-22.
- Astra accepted F2 on 2026-09-22 and merged [PR #6](https://github.com/katanada2/MediCafe-v1/pull/6) at `87526383052ebb68395fe1fe14f26f901bd5c952`. Its bounded service/claim authority is synthetic only.
- F3 runtime is admitted by merge of the admission record below. Main containing this record is the entry gate; an unmerged branch is not authorization. F4 runtime remains closed. No real data, live integration, migration from V0, deployment or production authority transfer is authorized.

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

## Evidence packet and escalation

Report branch, exact head, PR, changed responsibility, setup commands, resolved versions, executed tests/results, failed or unrun checks, contract coverage and open gaps. Distinguish source review from execution and local evidence from deployed qualification. Keep private operational links and source data out of this file.

For an escalation, identify the conflicting card paragraph, attempted approach, observed failure and one bounded alternative. Escalate a contract contradiction or two failed attempts at one approach rather than redesigning the charter.

## Decision and review record

F1 preserved explicit delivery identity, atomic create-and-resolve retries, immutable terminal ParseAttempts and success-only ParseResults. Computation stays outside the Delivery lock; every completed computation records a terminal attempt, only the first success creates canonical observations, and true replay creates no attempt. Historical decisions remain distinct from current artifact availability.

Astra's F2 design and Luna's focused review settled service correction provenance, exact claim membership, immutable envelopes and historical-versus-current approval. Policy activation generations prevent revival of old approval. The follow-up closes policy-switch/no-op retry receipts, database head rewind prevention, explicit cross-row relationship constraints and canonical intent encoding. No concrete contradiction remained in the follow-up review. Automated review then clarified post-merge admission wording and a fixed precedence for combined actionability blockers. These are reviewed contracts, not executed F2 evidence.

Deferred alternatives remain explicit in the card: clinical inference, real coding/coverage policy, automatic line inclusion or approval transfer, broad identity correction, a generic policy engine and dispatch infrastructure.

## Associated PR history

- [F2 implementation PR #6](https://github.com/katanada2/MediCafe-v1/pull/6): accepted and verified merged 2026-09-22 at `87526383052ebb68395fe1fe14f26f901bd5c952`; implementation and final-head evidence above.
- [F4 planning PR #5](https://github.com/katanada2/MediCafe-v1/pull/5): verified merged at `8973724df9e36ae3f27538b9e51316152e518dfd`; planning only, runtime gate closed.
- [F3 planning PR #4](https://github.com/katanada2/MediCafe-v1/pull/4): verified merged at `a5a74e2f3d4e870aaa87afd6dc20bc0233ec69c2`; planning only, runtime gate closed.
- [F2 contract PR #3](https://github.com/katanada2/MediCafe-v1/pull/3): F2 admission decision: merging this record accepts the card and opens implementation. On main containing this record, F2 is admitted.
- [F1 implementation PR #2](https://github.com/katanada2/MediCafe-v1/pull/2): verified merged 2026-09-22, accepted evidence above.
- [Charter PR #1](https://github.com/katanada2/MediCafe-v1/pull/1): verified merged; established the initial F1 entry gate.
