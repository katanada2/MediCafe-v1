# O1: derived operator exception review

Status: architecture-reviewed planning after Astra's review of `18ccb97`.
Four owner families, default 25/max 50 per section, bounded evaluated windows,
immutable exact-target links and no new effect/business authority are accepted
scope decisions. This card is NOT runtime-admitted or authorized for publication.
Verification tooling and browser gates remain explicit below.

## Outcome and scope

An active synthetic operator opens one organization-scoped page, sees four
bounded sections of unresolved owner work with reason codes and exact target
links, and reaches the existing detail page to make any authorized decision.
Refresh and restart derive the view again from durable owner state. No second
queue, duplicate business status or cross-owner completion badge is stored.

The proposed inclusion predicates below use existing owner meanings. They are
part of the reviewed planning contract, not implemented queries. Owners classify
their own evidence; composition must not reconstruct predicates or invent urgency.

| Family | Include in the evaluated window | Exclude / preserve distinctions |
| --- | --- | --- |
| sources | Organization-scoped observations for which the owner finds no accepted identity decision (`unresolved_only=True`) | Resolved observations are not unresolved work; source row identity is not patient identity |
| claims | Owner effect state `pending`, `leased` (pending execution), `blocked`, `uncertain` or `receiver_conflict`; also an intent with owner-reported current alerts/blockers even when historical receiver acceptance exists | Accepted history alone, safely cancelled or definitely-unsent history without a current alert is not an exception; retain acceptance alongside applicable current alerts, never erase it |
| outcomes | Candidate with no accepted-event evidence, or any owner-ordered current blocker; accepted-event evidence remains included alongside current artifact availability or identity/content conflict alerts | Accepted facts without current alerts are not unresolved work; unmatched attribution stays absent and posting is not cash |
| archival | Captured head whose exact item is unconfirmed/not queued/pending/unknown/rejected/conflicting, or whose separately observed lag is `projection_lag`; include unavailable or refresh-needed classification | Historical confirmation alone is not current export; a confirmed exact current head without alerts is excluded from exceptions; no invented uncaptured-encounter work |

Each owner publishes exact state/reason mappings before UI implementation; a
new policy meaning returns to Astra. Do not scan all encounters to invent
uncaptured-archive work, or add service/pricing/coverage policy.

O1 adds only owner read queries and immutable summaries, server-rendered
composition/navigation, synthetic tests and setup/evidence docs. No schema
change, worker change, dependency, frontend build, API consumer, network call,
mutation endpoint, batch action, automatic retry/reevaluation, assignment,
notification, dismissal or export is authorized. Existing command/form behavior
is unchanged. A GET must not parse, reconcile, capture, queue or post anything,
including invoking a mutating reevaluation command to obtain a summary.

## Ownership and prerequisites

Astra owns shared interface acceptance and final milestone acceptance. One
implementation owner owns all four query seams, composition, templates and URL
wiring. After the contracts are fixed, one optional disjoint lane may own new
synthetic fixtures/tests only. Maximum two lanes; every assignment declares
file ownership and preserves other writers' edits. Do not reopen F1–F4 business
contracts as mechanical O1 work.

Prerequisites: merged F1–F4 baseline from the [handoff](DELIVERY_HANDOFF.md),
accepted owner predicates/DTOs, active-membership/scoped-query rules, safe
synthetic PostgreSQL 17 test environment and explicit implementation admission.
The accepted feature-evidence design uses concrete
`tests/helpers/workflow_boundary_contract.py` tests and a named acceptance
matrix. This does not satisfy the separate unresolved tooling prerequisite:
the skill-required policy/registry/selector integration is absent. Required
integration must receive separate tooling review/admission before O1 runtime
admission or completion claims that require it. No integrated coverage, waiver
of skill requirements or broad tooling implementation is authorized by this
documentation packet.

## Owner interfaces and rendering contract

The following are proposed new query contracts, not existing API promises.
Existing queries are evidence inputs, not an invitation for composition to
inspect mutable ORM rows or reproduce business rules.

| Producer | Existing basis | Proposed summary responsibility |
| --- | --- | --- |
| sources | `scoped_observations(..., unresolved_only=True)` and retained parse evidence | Unresolved observation identity, source delivery/parse-result IDs, owner reason and detail target; no raw notes |
| claims | `delivery_worklist`, `delivery_detail`, `delivery_effect_state` | Exact intent/revision and relevant latest attempt, owner effect state and blockers; preserve historical receiver evidence separately |
| outcomes | `inbound_candidates`, `candidate_detail`, pure owner classification of current blockers | Candidate/delivery and attributed target when known, accepted historical event when present, ordered current blockers; no inferred attribution or posting |
| archival | `archive_heads`, `archive_item_status`, `archive_current_lag` | Exact captured head/projection/version, item evidence plus separately computed coherent owner lag; confirmation of an older item never implies current export |

Each owner supplies `operator_review_page(actor, organization_id, cursor=None,
limit=25)` returning a frozen page of frozen summary values and an owner-specific
continuation cursor. Names may be adjusted before admission, not semantics.
Required fields are organization, owner/family, exact target kind/UUID, stable
detail-route key, state and ordered reason codes, relevant durable evidence IDs,
historical-fact summary separate from current alerts, and observation time.
Unknown target relationships remain absent, not backfilled from the latest
claim/encounter. No artifact bytes, raw patient/source fields, credentials or
mutable models cross into composition.

Summary population invokes only read queries and pure owner classification.
If existing detail/reevaluation code writes conflicts, observations, evidence or
attempts, expose a narrow pure read-only classification seam instead; do not
call the mutating command and try to undo its writes. Existing pure classification
may be reused only after verifying that property. Artifact verification remains
an owner read with bounded bytes/items and explicit unavailable status, never a
repair, parse or new persisted observation. No GET creates any evidence row.

Limit is 1–50; default 25 per section. Use deterministic owner ordering with
UUID tie-breakers and owner-validated, organization/filter-bound cursors. Return
`has_more` rather than a misleading total. Changed state may move items between
requests: pagination is not a persistent global snapshot. No global cross-owner
sort, urgency score or complete/empty aggregate status is defined.

Where current exception filtering needs per-item evaluation (notably archive
lag), evaluate at most the page limit of owner candidates and advance the cursor
through that evaluated window. Label the window and `has_more`; an empty filtered
window means only “no matching exceptions in this evaluated window,” including
when it is the last window: earlier windows may have matched and state may have
changed since they were read. It never means the whole family is clear. An owner
enumeration with zero candidates means only no candidates observed at that
enumeration time, not a completed workflow. Do not scan an unbounded history to
fill a page; no whole-family-clear assertion is part of O1.

No coherent page snapshot is promised. Ordinary owners declare their actual read
contract: a scoped enumeration statement observes one database snapshot; further
classification/detail statements may observe later state under READ COMMITTED.
Publish enumeration and per-summary observation times/IDs, and preserve any
stronger existing owner-local snapshot guarantee without inventing new locks,
global transactions or a dashboard-wide snapshot requirement. Artifact reads
are separate observations too. Timestamp labels are observation metadata, not
proof of atomicity or terminal evidence.

Archive explicitly has a scoped captured-head enumeration snapshot, followed
by independently observed exact-item evidence and per-item lag. Each lag read
retains its standalone read-only REPEATABLE READ transaction and cannot be
nested inside composition. This does NOT make the archive page coherent across
items or with enumeration. Carry enumeration time and head/projection/version
IDs, item-evidence observation time and exact projection ID, and lag observation
time and the lag query's head/projection IDs. Compare the scoped head/projection
identities: changed or missing head identity yields refresh-needed, never a newer
head's result attached as current evidence to an older row. Bound evaluation to
the selected window. A later change can stale the displayed observations;
refresh/detail revalidates them. No aggregate completion follows from any of
these independently observed results.

Every owner rechecks active membership and scopes targets before lookup.
Composition admits the actor too. Authentication/authorization failure denies
the whole request without partial target leakage. An unavailable owner produces
an explicit unavailable section without a zero count, resolved label or cached
success. Other authorized sections may render; unexpected failures are reported
through existing sanitized diagnostics, not suppressed as empty work.

Only stable detail links are shown. Permitted actions remain on existing owner
detail pages after fresh validation. Summary state is neither authorization nor
a captured command payload. Old links must fail scoped lookup or explain changed
state, never operate on a substituted target. Historical accepted facts remain
visible alongside current alerts; disappearance from this exception view is not
proof of acceptance, successful send, posted money, cash or archive completion.

## Failure and recovery semantics

- Missing/currently unavailable artifact, conflicting identity/content, sequence
  gap, pending execution, possible external effect and confirmed historical fact
  stay distinct according to the owner contract; no generic failed/success badge.
- Repeated GET/refresh, cursor reuse and process restart perform zero mutations
  and zero external calls. They grant no retries and clear no attempts or alerts.
- Concurrent correction, dispatch/reconciliation or head change can stale a
  section. Label the observation and refresh; navigate to exact owner detail
  for current truth. No stale summary may trigger an action.
- Owner outage remains unavailable, not “all caught up.” Recovery is a fresh
  read after the dependency returns, not a producer boolean or file timestamp.
- Unsupported source/provider/financial policy remains unsupported. A helpful
  link cannot manufacture an authorized resolution.

## Synthetic fixtures and acceptance evidence

Use two synthetic organizations and distinct memberships, no real names/data.
Reuse foundation factories without weakening their constraints. Add fixtures
for unresolved/resolved observation, blocked intent, v1/v2 unknown effect,
conflicting receiver evidence, accepted lifecycle plus a sequence gap/conflict,
unmatched remittance, conserved accepted posting plus current artifact alert,
unknown archive write, old confirmed projection plus new current lag, and more
than one page per family. No live provider or archive is required for summary
tests; test evidence remains exact-target and durable.

Acceptance requires executable PostgreSQL-backed owner and authenticated-view
tests, with named matrix rows and exact commit/run evidence:

1. Each admitted inclusion predicate is exercised positively and negatively;
   owner reason ordering and state distinctions survive composition unchanged.
2. Cross-organization IDs/cursors, inactive membership, anonymous access and
   membership revoked between composition admission and owner query fail closed.
3. Repeated GET, refresh, pagination and restart create no domain, receipt, work,
   attempt, conflict, observation or evidence rows and perform no external calls;
   mutating classification commands are not invoked. Links lead only to exact
   scoped targets; bounded artifact read failures remain unavailable.
4. Owner outage, missing evidence and wrong-target evidence are unavailable or
   blocked, never empty/resolved/accepted; accepted history remains separate.
5. Forced interleavings exercise delivery uncertainty changing after summary,
   candidate blockers changing and archive head/lag change between enumeration,
   item evidence and independent lag transactions. Observation metadata and
   refresh-needed identity checks prevent wrong-head attachment; no coherent
   page, aggregate completion or stale action claim is rendered.
6. Every section respects page/query bounds and stable tie-break ordering;
   cursor tampering fails safely. Empty filtered and last windows never imply
   whole-family-clear. No unbounded per-encounter lag scan is added.
7. Same-target owner-to-summary-to-detail propagation and wrong-target fail-closed
   tests use the feature boundary helper. Record target identity, producer,
   consumer, intent/attempt, terminal evidence, artifacts and wording. No registry
   coverage claim without integrated registry-backed selection and evidence.
8. Existing F1–F4 PostgreSQL suite, migrations/check/drift and applicable public
   scanners stay green on the exact candidate. Record executed and unrun checks
   separately; a source review is not a browser result.
9. Manual synthetic browser walkthrough verifies navigation, readable distinctions,
   independent section paging, unavailable presentation, invalid-link denial and
   restart. If unavailable, retain an explicit acceptance limitation for Astra;
   do not silently substitute CI for operator usability evidence.

Review public screenshots/logs for source notes, identifiers and credentials;
only synthetic, redacted examples enter the packet. The complete foundation
walkthrough plan and current local environment blocker are in the
[continuation packet](POST_FOUNDATION_CONTINUATION.md).

## Stop conditions and handoff

Stop before implementation until admitted. During delivery, return to Astra if
scope needs persistent business/worklist state, an owner-boundary change,
schema/dependency/command modification, global snapshot semantics, guessed policy,
automatic external effect or private environment authority. Report exact stalled
commands and observed sessions; avoid duplicate jobs/repeated retries.

Deliver one bounded candidate with exact SHA, changed-file ownership, immutable
interface matrix, predicate/scenario evidence, privacy review and unrun checks.
Do not merge, publish, claim production readiness, close G1–G6 or transfer V0
authority. Astra accepts/rejects the milestone and authorizes subsequent work.
