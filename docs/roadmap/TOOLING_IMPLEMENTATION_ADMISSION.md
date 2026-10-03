# O1 verification prerequisite admission

Status: accepted bounded tooling scope, 2026-10-03. This record precedes tooling
edits. Base: published planning head
`5a2b2993f5816b90ecb153e8b5657220ebaf41e4`; branch
`codex/o1-verification-prerequisite`. The coordinator owns PR publication/merge.
O1 application runtime remains separately gated by its reviewed interface and
explicit admission record.

## Outcome, authority and ownership

Implement the smallest public-native developer verification integration required
by workflow-boundary review: canonical policy, static catalog, pure selector,
strict interpreter runner, coherence procedure and focused stdlib tests. The
catalog routes verification; it stores no runtime evidence and is never business
state, action permission or completion authority. Preserve planned O1 status.

The coordinator accepted this scope and owns architecture and acceptance. Sol
is sole writer of all listed seams. No parallel writer, private V0 import,
application/schema/dependency change or O1 feature implementation is admitted.
The continuation checkout is preserved for the coordinator's publication work.

## Exact file set

- `AGENTS.md`: concise route to canonical workflow/guidance policy.
- `docs/CHANGE_SURFACE_CONTROL.md`: canonical developer verification policy.
- `tools/workflow_boundary_registry.json`: static versioned contract catalog.
- `tools/select_verification.py`: stdlib validation and deterministic path selection.
- `tools/run_modern_python.py`: verified Python 3.13 execution, no installation/fallback.
- `tools/CODEX_SCAFFOLDING_COHERENCE_REVIEW.md`: concise public-native canonical procedure.
- `docs/agent-guidance/README.md`: policy-owner and routing index, not copied policy.
- `tests/tooling/test_workflow_verification.py`: focused stdlib positive/negative tests.
- `.github/workflows/foundation.yml`: exactly one lightweight tooling-validation step;
  retain the existing once-only full PostgreSQL foundation suite.
- This admission record: scope, executed/unrun evidence and environment disposition.

## Contract and verification requirements

Selector has no service, network, mutation or hidden test execution. Malformed
catalogs, unknown code and unsafe paths fail closed; docs-only results remain
explicit and do not imply feature execution. Catalog links existing concrete
feature helper calls/tests, including F2 cross-owner coverage, and represents
O1 as planned rather than implemented. Static references are not executed proof.

Runner verifies Python 3.13 and propagates child failure, with no alternate-version
fallback, installation or recursive relaunch. Stdlib tests cover malformed/missing
catalog data, traversal/unknown paths, deterministic multi-contract selection,
guidance/docs lanes, actual helper/test links, planned status and runner failure.
Run selection for every changed path and follow governing-guidance/boundary
review. Bundled Python 3.12 may execute these stdlib tests directly as provisional
tooling evidence only; final CI uses locked Python 3.13. Existing concrete
foundation tests use the feature-boundary helper; no new O1 feature tests here.

## Synthetic environment scope and stop conditions

Safe disposable synthetic runtime preparation is authorized: bounded availability
probe and normal launch of the existing Docker engine if available, then owned
temporary containers only. Do not read private Docker configuration, bypass ACLs,
install global runtimes/services, change global Docker settings or use private
mounts/data. Actual host/config/access errors stop environment preparation and
are reported, not worked around through repeated probes or alternate credentials.

Use the foundation's locked Python 3.13/uv and PostgreSQL 17 recipe, synthetic
database/credentials/artifact storage and loopback fixture processes. Do not
claim available daemon/images/browser/database from executable presence. Preserve
unrelated sessions/resources; no destructive cleanup or deployment changes.

All committed material is public synthetic developer guidance/source/test data.
No operational configuration, PHI, credentials or private evidence enters Git.
Stop for owner/policy changes, unsafe environment, transport stalls or scope
expansion. Report exact command and inner timing; no duplicate jobs/retry loops.
Return local commits, focused test/selection evidence and environment disposition
to the coordinator. Do not push, publish or implement O1 application code.
