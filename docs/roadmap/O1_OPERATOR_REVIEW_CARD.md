# O1: derived operator exception review

Status: proposed implementation card, not admitted. Astra must accept the scope,
interfaces and verification disposition before assigning runtime work.

## Outcome and scope

An active synthetic operator opens one organization-scoped page, sees four
bounded sections of unresolved owner work with reason codes and exact target
links, and reaches the existing detail page to make any authorized decision.
Refresh and restart derive the view again from durable owner state. No second
queue, duplicate business status or cross-owner completion badge is stored.

Include unresolved intake observations; delivery intents with blocked, uncertain
or conflicting effect evidence; inbound candidates with outstanding acceptance
or blockers; and captured archive heads with unconfirmed/conflicting item
evidence or current projection lag. The inclusion predicate belongs to each
owner and must be published before UI implementation. Do not scan all encounters
to invent uncaptured-archive work, or add service/pricing/coverage policy.

O1 adds only owner read queries and immutable summaries, server-rendered
composition/navigation, synthetic tests and setup/evidence docs. No schema
change, worker change, dependency, frontend build, API consumer, network call,
mutation endpoint, batch action, automatic retry/reevaluation, assignment,
notification, dismissal or export is authorized. Existing command/form behavior
is unchanged. A GET must not parse, reconcile, capture, queue or post anything.

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
Admission must decide the registry/policy/selector integration gap. The existing
`tests/helpers/workflow_boundary_contract.py` must be used in concrete feature
tests; if registry-backed tooling is required, admit that separate tooling scope
first rather than silently copying unrelated guidance into O1.

## Owner interfaces and rendering contract

The following are proposed new query contracts, not existing API promises.
Existing queries are evidence inputs, not an invitation for composition to
inspect mutable ORM rows or reproduce business rules.

| Producer | Existing basis | Proposed summary responsibility |
| --- | --- | --- |
| sources | `scoped_observations(..., unresolved_only=True)` and retained parse evidence | Unresolved observation identity, source delivery/parse-result IDs, owner reason and detail target; no raw notes |
| claims | `delivery_worklist`, `delivery_detail`, `delivery_effect_state` | Exact intent/revision and relevant latest attempt, owner effect state and blockers; preserve historical receiver evidence separately |
| outcomes | `inbound_candidates`, `candidate_detail`, current owner reevaluation logic | Candidate/delivery and attributed target when known, accepted historical event when present, ordered current blockers; no inferred attribution or posting |
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

Limit is 1–50; default 25 per section. Use deterministic owner ordering with
UUID tie-breakers and owner-validated, organization/filter-bound cursors. Return
`has_more` rather than a misleading total. Changed state may move items between
requests: pagination is not a persistent global snapshot. No global cross-owner
sort, urgency score or complete/empty aggregate status is defined.

Where current exception filtering needs per-item evaluation (notably archive
lag), evaluate at most the page limit of owner candidates and advance the cursor
through that evaluated window. Label the window and `has_more`; an empty filtered
window is not “no exceptions.” Do not scan an unbounded history to fill a page.

Each page is a bounded coherent read within its owner. The four sections are
separate observations, explicitly labelled as such; no global transaction is
claimed. In particular archival lag retains its existing standalone read-only
REPEATABLE READ semantics and cannot be nested inside a composition transaction.
Bound lag evaluation to selected captured heads. If evidence changes between
head enumeration and lag query, return owner-defined stale/refresh-needed state
with exact observed IDs rather than attach a newer head's result to an older row.

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
3. Repeated GET, refresh, pagination and restart create no domain/receipt/work
   rows and perform no external calls; links lead only to exact scoped targets.
4. Owner outage, missing evidence and wrong-target evidence are unavailable or
   blocked, never empty/resolved/accepted; accepted history remains separate.
5. Forced interleavings exercise delivery uncertainty changing after summary,
   candidate blockers changing and archive head/lag change. No stale action or
   wrong-head evidence is rendered as current completion.
6. Every section respects page/query bounds and stable tie-break ordering;
   cursor tampering fails safely. No unbounded per-encounter lag scan is added.
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
