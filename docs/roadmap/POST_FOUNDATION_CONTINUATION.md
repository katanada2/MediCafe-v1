# Post-foundation continuation packet

Status: 2026-09-30 architecture-reviewed planning. Astra accepted the baseline
corrections, ranked plan and four-family O1 recommendation after reviewing
`18ccb97`. Documentation only; publication authorized on 2026-10-03. NOT runtime-admitted,
deployment-qualified or an authority transfer.

## Baseline and decision authority

The public-synthetic F1–F4 foundation is accepted and merged through
[PR #10](https://github.com/katanada2/MediCafe-v1/pull/10), merge SHA
`7432930536dfc26b48f3d57077256cc7e244c377`. Final reviewed head
`dbaeb6c91aa4893c0dbda3d801e5be5d288c4cbb` passed
[CI 36617022085](https://github.com/katanada2/MediCafe-v1/actions/runs/36617022085):
225 tests, including 76 F4 tests, in 262.205 seconds. Exact runtime-head evidence,
locked versions and older diagnostic runs remain in the
[handoff](DELIVERY_HANDOFF.md). Neither that CI nor this packet proves manual
browser, private/deployed or real-provider qualification.

This proposal follows the [charter](../architecture/CHARTER.md),
[V1 plan](../architecture/MEDICAFE_V1_PLAN.md),
[capability/gap map](../architecture/CAPABILITY_MAP.md) and the F1–F4 cards,
setup guides and acceptance matrices. Source inspection confirms existing
owner worklist/detail queries; it does not establish a cross-owner operator
review surface. No private V0 material was imported.

Astra owns architecture, policy, shared interfaces and milestone acceptance.
Sol owns this packet only. An accepted draft must receive explicit implementation
admission before code work; merging planning text alone must not silently admit
an unspecified runtime scope. V0 retains production authority.

## Ranked next work

Order is a dependency/value recommendation, not a delivery schedule. Private
requirements gathering can proceed independently when separately authorized;
no real integration becomes safe because it appears earlier in this table.

| Rank | Bounded work | Operator value and prerequisites | Remaining gate |
| --- | --- | --- | --- |
| 1 | O1 derived operator exception review | Find unresolved intake, delivery, inbound and archive work through existing owners; already grounded in F1–F4, no new money or retry policy | Separate runtime admission, reviewed tooling prerequisite and synthetic browser evidence |
| 2 | Source/identity correction specification (G1/G2) | Correct mistaken attribution without losing downstream history; prerequisite to meaningful real intake and migration | Reviewed correction-after-effects, merge/split and alias collision rules; synthetic card before implementation |
| 3 | Coding/pricing/coverage specification (G3) | Prepare actual billable service inputs instead of arbitrary synthetic values | Owner-approved versioned policy, provenance, applicability and examples; do not infer payer rules |
| 4 | Provider transport/inbound contract qualification (G4) | Make send uncertainty and received responses interpretable outside fixtures | Selected provider, payload/response rights, enrollment, identity/auth, idempotency/readback and resubmission rules; private qualification |
| 5 | Financial correction and opening-state specification (G5) | Resolve denials, corrections/reversals and COB without duplicate money; depends on attribution/provider meanings and reviewed posting policy | Financial owner acceptance and opening-state reconciliation; no inferred balances |
| 6 | Liability, communications and cash reconciliation (G5) | Patient billing and actual settlement; depends on accepted financial policy and independent payment/consent evidence | Separate receivable, send and cash authorities; no ERA-to-cash shortcut |
| 7 | Actual Medisoft archive mapping | Makes delayed archive useful to real operators; depends on stable canonical representation and qualified target behavior | Private mapping, correction/readback and XP recovery qualification; no live writes from this packet |
| Parallel qualification track | Production operations and migration/cutover (G2/G6) | IAM, retention, backups, egress, observability, recovery and migration population support all real operation | Separate private environment and authority-transfer reviews; blockers remain even if all public cards pass |

The recommended smallest useful milestone is [O1](O1_OPERATOR_REVIEW_CARD.md):
one read-only, organization-scoped exception review page with bounded owner
sections and links to existing detail pages. It improves visibility across
the completed foundation without expanding clinical, financial or effect
authority. It is deliberately not a complete billing-office dashboard: service
preparation, unapproved claims and unspecified follow-up policy remain on their
existing screens or future cards.

## Alternatives and open decisions

- Browser verification alone is the smallest evidence task and should occur
  when a safe runtime is available. It closes an unrun verification gap but adds
  no operator capability; it can precede O1 without substituting for its tests.
- Financial correction first has high product value, but unknown reversal/COB
  policy makes it a specification milestone, not a small implementation slice.
- Real-provider/Medisoft integration first has high eventual value but requires
  private contracts, environment authority and qualification absent here.
- Persistent global work items, assignments, snooze/dismissal and automatic
  recovery are rejected for O1. They introduce competing state/authority and
  are not needed to link existing owner explanations. Astra accepted this O1
  scope boundary; it is not a permanent architectural ban.

Astra accepted all four owner families, default 25/max 50 per section, bounded
evaluated windows rather than history scans to fill filtered pages, immutable
exact-target links and no new global work state, policy, mutations or effects.
The revised [card](O1_OPERATOR_REVIEW_CARD.md) publishes owner inclusion
predicates, empty-window semantics, independently observed archive enumeration/
item/lag identities and timestamps, and pure read-only classification requirements.
It does not promise coherent pages or aggregate completion.

Remaining gates are explicit runtime admission,
safe browser execution/evidence and separately reviewed skill-required tooling
integration. Concrete boundary-helper tests plus the named feature matrix are
accepted feature-evidence design, not integrated registry/selector coverage.
No owner reason may become severity, deadline or next-action policy without a
reviewed rule. Real format inventories, provider selection and financial policy
owners remain open requirements.

## Bounded local browser assessment

On 2026-09-30, the continuation checkout was clean at the merge SHA. Main and
the completed F3/F4 worktrees were preserved. No app terminal was attached and
no tracked running command session required resumption. Read-only environment
checks found no PostgreSQL service from `Get-Service '*postgres*'`, no listeners
on documented PostgreSQL/app/receiver/archive ports 5432, 8000, 8765 and 8875,
no `uv` or `psql` from `Get-Command`, and no main-checkout `.venv`.

These observations establish that an already available safe PostgreSQL 17 and
locked runtime was not verified, not that no installation exists anywhere on
the host. No database connection, dependency install, environment provisioning,
server launch or browser mutation was attempted. The exact blocker is the lack
of a verified available synthetic PostgreSQL/runtime environment required by
the setup guides. Manual browser and local PostgreSQL verification remain unrun.
Responsive shell calls are not repository performance measurements; no new
transport stall was observed in these bounded probes.

### Reproducible walkthrough when prerequisites are supplied

1. Use an explicitly designated disposable synthetic PostgreSQL 17 database,
   local artifact directory and locked F1 versions. Follow [F1 setup](F1_SETUP.md)
   for environment placeholders, `uv sync --locked`, migrations, check/drift,
   `seed_demo` and localhost server. Choose credentials locally; do not put them
   or operational `.env` content in evidence or commits.
2. Complete [F1](F1_SETUP.md) and [F2](F2_SETUP.md) browser paths: upload/parse,
   resolve identity, accept/correct services, prepare and approve exact revision.
   Record IDs, redacted reason codes and expected/observed page state. Verify
   second-organization denial and form retention on invalid input.
3. Follow [F3](F3_SETUP.md) with its separate receiver at 127.0.0.1:8765 and
   bounded `--once` worker. Inspect independent exact-byte receiver acceptance;
   distinguish pending, uncertainty and reconciliation from permission to retry.
4. Follow [F4](F4_SETUP.md) with supported synthetic JSON fixtures from
   `tests/f4/base.py`, explicit inbound decisions, conserved ledger and separate
   archive at 127.0.0.1:8875. Capture/queue exact projection, run bounded worker,
   then inspect independent item readback and current lag separately. Include
   archive outage without blocking canonical outcomes; do not infer cash.
5. Restart the local processes and revisit the same IDs. Capture persistence,
   unknown/conflict explanations and cross-organization denial. Stop only the
   processes started for this walkthrough; preserve any unrelated sessions.
6. Record commit, locked versions, fixture IDs, steps, pass/fail/unrun outcomes
   and redacted screenshots after public-boundary review. Failures return to
   the owner; never relabel source inspection/CI as browser execution. No full
   suite rerun is required merely to produce this documentation packet.

## Review and stop

This packet reconciles merged status and proposes the next card; it closes no
production gap. Documentation checks cover whitespace, local file links and
documentation-only scope. The workflow-boundary policy, registry and selector
are not integrated yet in this repository. The existing feature contract helper
is available, but no runtime tests or registry-backed selection are claimed for
this planning packet. O1 must use the accepted concrete feature-boundary test
design. Required policy/registry/selector integration is a separate reviewed
tooling prerequisite before runtime admission/completion claims requiring it;
this packet neither waives that requirement nor implements broad tooling.

The earlier local-only handoff boundary was superseded on 2026-10-03 when the user authorized proceeding with publication and prerequisite preparation. O1 runtime implementation still requires its concrete admission record. The earlier instruction was: do not push, open a
PR or implement O1 until separately authorized. Keep any corrections within
this packet; architectural scope changes return to Astra.
