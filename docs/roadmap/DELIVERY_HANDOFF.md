# Delivery handoff

## Objective and authority

Deliver the public synthetic foundation under the [charter](../architecture/CHARTER.md). Astra owns architecture, consequential decisions, milestone acceptance and merge. Sol owns bounded delivery, with at most two implementation lanes and one writer per shared seam. Public source and synthetic evidence do not establish production qualification or transfer V0 authority.

## Current state and entry gates

- Charter PR #1 is merged at `c24bbe5fe0bab3079b6c569e91143ccc23afced8`.
- F1 PR #2 is merged at `cceec754ff00e754de41757cad49696b7173d0b7`; Astra accepted the synthetic intake/identity milestone on 2026-09-22.
- The [detailed F2 card](F2_SERVICE_CLAIM_CARD.md) defines the next service/claim milestone. Astra's focused review is complete. Merge of PR #3 admits F2 runtime; main containing this handoff is the confirmed entry gate. Before merge, its review branch is not authorization. No F2 runtime has been implemented by this planning change.
- F3 and F4 remain gated. No real data, external effect, migration or live integration is authorized.

## F1 acceptance evidence

Accepted implementation head: `56604ab6526c1ab917224cb9b6f0709b1161a06e`, branch `codex/f1-attributable-intake`, delivered through task `01a09b4c-b9cb-7f83-bc7b-2dbd2c3b717d`.

[PostgreSQL run 35687948907](https://github.com/katanada2/MediCafe-v1/actions/runs/35687948907) passed fresh PostgreSQL 17 migrations, Django system checks, migration-drift detection and all 33 F1 tests in 25.747 seconds. GitGuardian passed on the same head. Astra inspected the corrections and exact-head results, resolved all three automated review threads, and merged through normal branch protection.

Corrections cover upload size validation before application materialization with bounded chunk accumulation; short CSV rows becoming stable failed ParseAttempts; and request replay bound to the exact observation. Earlier reviews also established immutable history, current artifact verification, concurrency accounting and form-error preservation. Existing required check `postgres-foundation` remains enforced.

This is executed synthetic integration evidence. It is not a browser walkthrough, deployed test, payer interoperability or production qualification. The upload correction does not limit proxy ingress or Django's pre-view temporary spooling; production ingress controls remain a later deployment concern. No local PostgreSQL test success is inferred from CI.

## F2 delivery assignment

Read the [F2 card](F2_SERVICE_CLAIM_CARD.md), charter and ADR 0001 initially. Start from main containing the merged F2 planning commit in a dedicated worktree/branch. Its presence on main confirms the entry gate; no additional planning approval is required. Outcome, ownership, interfaces, privacy classification, dependencies, acceptance evidence and stop conditions are all specified by the card.

One owner implements exercised records/claims and shared wiring. A disjoint fixtures/test lane may begin after the owner fixes schema and query seams. Use Terra or Luna for settled bounded work as useful; do not add recursive management layers. Keep changes synthetic and do not copy private V0 material.

Return a draft PR and evidence packet to Astra. Do not merge or begin F3. Mechanical choices inside the card are delegated; changes to identity, authority, policy meaning, owner boundaries or external-effect rules require architectural review.

## Evidence packet and escalation

Report branch, exact head, PR, changed responsibility, setup commands, resolved versions, executed tests/results, failed or unrun checks, contract coverage and open gaps. Distinguish source review from execution and local evidence from deployed qualification. Keep private operational links and source data out of this file.

For an escalation, identify the conflicting card paragraph, attempted approach, observed failure and one bounded alternative. Escalate a contract contradiction or two failed attempts at one approach rather than redesigning the charter.

## Decision and review record

F1 preserved explicit delivery identity, atomic create-and-resolve retries, immutable terminal ParseAttempts and success-only ParseResults. Computation stays outside the Delivery lock; every completed computation records a terminal attempt, only the first success creates canonical observations, and true replay creates no attempt. Historical decisions remain distinct from current artifact availability.

Astra's F2 design and Luna's focused review settled service correction provenance, exact claim membership, immutable envelopes and historical-versus-current approval. Policy activation generations prevent revival of old approval. The follow-up closes policy-switch/no-op retry receipts, database head rewind prevention, explicit cross-row relationship constraints and canonical intent encoding. No concrete contradiction remained in the follow-up review. Automated review then clarified post-merge admission wording and a fixed precedence for combined actionability blockers. These are reviewed contracts, not executed F2 evidence.

Deferred alternatives remain explicit in the card: clinical inference, real coding/coverage policy, automatic line inclusion or approval transfer, broad identity correction, a generic policy engine and dispatch infrastructure.

## Associated PR history

- [F2 contract PR #3](https://github.com/katanada2/MediCafe-v1/pull/3): F2 admission decision: merging this record accepts the card and opens implementation. On main containing this record, F2 is admitted.
- [F1 implementation PR #2](https://github.com/katanada2/MediCafe-v1/pull/2): verified merged 2026-09-22, accepted evidence above.
- [Charter PR #1](https://github.com/katanada2/MediCafe-v1/pull/1): verified merged; established the initial F1 entry gate.
