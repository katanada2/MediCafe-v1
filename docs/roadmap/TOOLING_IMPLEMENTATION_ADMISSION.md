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

Astra retains architecture and milestone acceptance; the coordinator records
that accepted scope and owns publication/coordination. Sol is sole writer of
all listed seams. No parallel writer, private V0 import,
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

## Local implementation evidence — 2026-10-03

The admission was committed before tooling edits. Publication base is now merged
[PR #11](https://github.com/katanada2/MediCafe-v1/pull/11), squash
`b15aaa3c31d11c61467bb3e063e7e206b1746068`. The coordinator reports final
reviewed head `7408889` passed 225 foundation tests in 206.797 seconds on
[run 37151341169](https://github.com/katanada2/MediCafe-v1/actions/runs/37151341169),
with migrations/check/drift and GitGuardian green. That is baseline evidence,
not execution of this tooling candidate.

Executed locally with bundled Python 3.12.14:

- `python -m unittest discover -s tests/tooling -p 'test_*.py' -v`:
  45 tests discovered, 44 passed, one explicitly skipped (real Python 3.13
  runner-to-selector matrix); 2.449 seconds test runtime, 2.825 seconds measured
  inner shell runtime. Provisional stdlib evidence only.
- Direct selector execution for all ten changed paths selected the governing
  lane and boundary review, with docs-only/tooling states and no unknown paths.
  The Markdown procedure's final docs-only label was rechecked after correction.
  Initial ten-path direct selection took 1.570 seconds measured inside the shell.
- The default host invocation
  `python tools/run_modern_python.py tools/select_verification.py AGENTS.md --json`
  refused its wrong-version interpreter with exit 2, without fallback. The
  real Python 3.13 runner/selector matrix is included in the single CI tooling
  step and remains unrun locally. No repeated wrong-runtime invocation was used
  as a substitute for successful verification.
- Whitespace checks passed and all ten local Markdown file links resolved.
  Static catalog references validate concrete helper calls, including F2's
  transitive parse helper; this is linkage, not feature execution. Existing full
  foundation CI invocation is retained exactly once, with one new tooling step.

Exact-head Python 3.13 tooling execution, the required foundation CI and scanner
results remain pending publication by the coordinator. No local application
suite or browser walkthrough was run. O1 is planned, not implemented/admitted.

### Environment disposition

Read-only availability probes measured 2.907 and 0.466 seconds internally. No
checked PostgreSQL 17 service/listener/runtime or locked project virtualenv was
verified. Bundled Python 3.12 lacks Django/psycopg; executable presence is not a
project environment. The existing Docker CLI was available, service stopped,
daemon usability unverified. A bounded `docker version --format "{{json .Server}}"`
probe exited 1 in 0.196 seconds internally: private config access denied and
default daemon pipe missing. No private config contents were read. This actual
access/config/host failure stopped environment preparation; no ACL workaround,
engine launch, image pull, install, container/service creation or repeat probe.
No repository performance conclusion is drawn from tool wall time. Environment
path resolution remains with the coordinator/user, independently of tooling.

## Canonical coherence review

- Canonical source: this repository's developer policy, JSON machine catalog,
  owner index and canonical procedure; charter/cards retain product authority.
- Propagation map: AGENTS/skill routes reach policy and procedure; catalog drives
  pure selection; concrete helper/test links reach existing owner features;
  one CI tooling step validates linkage/unit behavior before the existing suite.
- Boundary impact: developer selection and wording only, no business/effect
  state; malformed/unknown/escaping inputs fail closed and planned O1 stays planned.
- Agent behavior delta: select every changed path, follow guidance/boundary
  review, require Python 3.13 for the runner and record executed versus unrun checks.
- Duplication/conflict check: no copied private policy or Markdown registry;
  static developer routing does not replace runtime evidence or owner commands.
  Astra's authority is preserved in AGENTS, policy, owner index and this admission.
- Retirement check: missing V1 procedure/index now supplied natively; no existing
  competing V1 copy needed removal. No private guidance/automations synchronized.
- CI efficiency check: one lightweight stdlib step; no duplicate full PostgreSQL
  run, dependency, new service or background verification job.
- Acceptance check: local 44-pass/one-skip provisional evidence, static linkage
  and docs checks are recorded; exact-head 3.13/feature CI, browser environment,
  milestone acceptance and O1 admission remain distinct gates.
