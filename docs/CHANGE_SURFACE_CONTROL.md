# Change-surface control

This is the canonical public-native developer verification policy. Architecture
and business authority remain in the charter/cards; this policy cannot authorize
runtime work. Astra retains architecture and milestone acceptance; the coordinator
records accepted scope and owns publication/coordination. One assigned writer
owns each shared tooling seam. See the [owner index](agent-guidance/README.md).

## Selection and evidence

For every changed path, from the repository root run:

```text
python tools/run_modern_python.py tools/select_verification.py <path> --json
```

The runner requires Python 3.13 (project runtime), optionally supplied with
`--python <executable>` before the script. It installs nothing and has no runtime
fallback. Use a locked environment. Direct execution with another modern Python
may provide provisional stdlib tooling evidence only, not runner/app qualification.

The sole machine routing authority is
`tools/workflow_boundary_registry.json`, a static developer verification catalog.
It contains contract identities and concrete test/helper references, never run
results, operational data, action grants or completion badges. Do not maintain
a competing Markdown registry. Selector output is a plan, not executed evidence.

Follow the selector's boundary-scan and governing-guidance decisions. Explicit
docs-only output does not waive semantic boundary review. Unknown code, unsafe
paths, malformed catalogs and broken references fail closed with exit 2; resolve
the catalog/review gap before claiming required verification. Planned contracts
remain planned even if their documents and tooling checks pass.

## Boundary review

Identify exact target, intent, attempt, terminal outcome, artifacts, packaging,
consumer wording and reconciliation of preserved context with mutable evidence.
Distinguish missing, stale, partial, wrong-target, in-flight and conflicting
evidence. Neither expected values, producer flags, file age nor nonempty paths
prove completion or permit an action. Keep historical facts separate from current
alerts and independently observed snapshots; no global completion inference.

Every implemented changed feature boundary needs a same-target producer-to-consumer
or explicit fail-closed negative feature test using the concrete boundary helper.
Static AST/reference validation checks linkage only; it is not execution, semantic
coverage or evidence that a feature is correct. Execute selected feature suites
on PostgreSQL with exact commit/runtime evidence. Preserve broader regression
requirements in the card/CI; do not substitute a focused suite for them.

Record selected contracts, feature tests, exact run/commit and executed/unrun
checks in the handoff. No contract/helper integration means `not integrated yet`,
not completion. O1 remains planned and separately runtime-admitted. Tooling tests
and browser evidence have different meanings and must never be conflated.

## Governing guidance

AGENTS, this policy, owner index, coherence procedure, catalog, selector/runner,
tooling tests and CI wiring use the governing-guidance lane. Follow the complete
[coherence procedure](../tools/CODEX_SCAFFOLDING_COHERENCE_REVIEW.md), run the
stdlib tooling validation, review all eight required findings and maintain
concise routes rather than synchronized policy copies. Adding a dependency,
business meaning, runtime registry or private guidance requires separate review.
