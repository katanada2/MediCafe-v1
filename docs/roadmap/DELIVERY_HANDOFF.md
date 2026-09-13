# Delivery handoff

## Objective and authority

Deliver the synthetic foundation under the [charter](../architecture/CHARTER.md) and [F1 card](FOUNDATION_CARDS.md). The owner authorized Astra-led architecture and right-sized delivery orchestration. Architecture decisions and F1 scope are accepted when this planning milestone merges; they are not an application-completion or production-approval claim.

## Current state

- Public repository bootstrap is committed on main.
- This milestone adds charter, capability/authority map, stack decision and foundation cards.
- Runtime, migrations, integration fixtures and test evidence do not yet exist.
- V0 evidence remains historical discovery; no fresh code-completeness or production qualification claim.
- F1 is the only admitted runtime card. F2-F4 require further entry-gate decisions.

## Delivery assignment

Sol is the delivery owner. Read only this handoff, charter, ADR 0001 and F1 initially; load other documents as a named question requires. Work on a dedicated F1 branch/worktree from merged main. Use Terra for a substantial bounded implementation and Luna for settled fixtures/verification when useful. At most two code lanes; one writer per seam. Do not recursively add management layers.

Open a draft F1 PR and collect evidence. Do not merge it or begin F2; return the evidence packet to Astra. Do not copy private V0 code or data. Keep public diagnostics synthetic and minimal.

## Evidence packet

Report branch, head SHA, PR, changed responsibility, setup commands, actual resolved versions, exact tests/results, failed/unrun checks, contract coverage, open gaps, and any required architect decision. Distinguish source review from executed tests and local behavior from deployed qualification.

For an escalation, identify the conflicting card paragraph, attempted approach, observed failure and one bounded alternative. Mechanical implementation details are delegated; identity semantics, authority, module boundaries, public/private policy and external-effect rules are not silently changed.

## Coordination record

Astra reviewed two bounded read-only agent analyses. The synthesis corrected a proposed conflation of public code with private runtime data, kept patient/financial ownership in V1, and resolved F1 replay, organization constraints, artifact failure and operator-resolution behavior. Deferred extra queue infrastructure, automatic patient merging, and production policy inference.

A future update should record the delivery task/branch and evidence status. Keep private evidence links and operational details out of this public file.

F1 delivery is assigned to task `01a09b4c-b9cb-7f83-bc7b-2dbd2c3b717d` on branch `codex/f1-attributable-intake`. During implementation, Astra clarified concurrent parse accounting: computation remains outside the Delivery lock; every completed computation records its own terminal attempt, while only the first success creates the canonical result and observations. A call that sees the result before computing is replay and records no attempt.

Draft [F1 PR #2](https://github.com/katanada2/MediCafe-v1/pull/2) carries the implementation and remains unmerged for Astra review. GitHub Actions [run 34766254507](https://github.com/katanada2/MediCafe-v1/actions/runs/34766254507) passed on implementation head `08bc63d`: fresh PostgreSQL 17 migrations, Django system checks, migration-drift detection, and all 23 synthetic F1 tests. This is executed synthetic foundation evidence, not deployed or production qualification.

Final contract review resolved delivery version ambiguity, atomic create-and-resolve retry identity, and success-only ParseResult persistence. The associated [charter PR #1](https://github.com/katanada2/MediCafe-v1/pull/1) was last verified open during review; its merge is the F1 entry gate.
Automated PR review additionally required version-scoped failure history. F1 therefore records immutable terminal ParseAttempts while keeping ParseResults success-only; no durable running/lease subsystem is added.
