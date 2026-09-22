# F2: accepted services and approved claim revisions

Status: reviewed detailed synthetic contract, accepted and admitted for implementation by merge of PR #3. F1 evidence is accepted. On main containing this card, F2 may proceed; an unmerged review branch alone does not grant entry. F3 remains closed. Decision owner: Astra; delivery owner: Sol.

## Outcome and boundary

An authenticated operator turns an identity-resolved observation into explicit synthetic services, corrects or excludes a service with provenance, selects exact service revisions into a claim, and approves the immutable claim revision they inspected. Reparse and restart preserve accepted decisions. A service, selection, route or policy change makes earlier approval unavailable for further action while retaining its history.

This card extends records and introduces claims. It adds no coverage lookup, clinical inference, real procedure code, actual payer payload, dispatch, worker, posting or archive. The envelope is labeled synthetic JSON, not 837P. All fixtures, screenshots and logs remain public and synthetic. Existing F1 behavior remains supported.

## Ownership and allowed surface

Records owns Service and append-only ServiceRevision, accepted correction provenance, and current-service queries. Claims owns Claim, append-only ClaimRevision and ClaimLine, immutable ClaimApproval, and synthetic policy selection. Composition owns forms and pages and calls commands. Claims reads records through narrow owning queries; records never imports claims or updates approvals.

One implementation owner writes models, migrations, commands, queries, forms, settings and URL wiring. After those interfaces settle, a second agent may own disjoint fixtures and tests. Allowed changes are exercised records/claims code, composition, tests, migrations and setup/handoff documentation. Keep the existing stack and lock unless a demonstrated dependency need is reviewed. Do not add generic event, workflow, repository or authorization frameworks.

## Decisions and constraints

Use existing UUID, UTC, membership and organization conventions. Every command and query admits an active member and scopes supplied IDs before resolving them. Enforce same-organization relationships with PostgreSQL composite foreign keys, in addition to application checks.

| Entity | Meaning and enforced invariants |
| --- | --- |
| Service | Stable explicit service UUID; immutable encounter and accepted IdentityDecision reference; current_revision pointer; decision must identify that encounter and its patient |
| ServiceRevision | Append-only accepted version of one Service; predecessor, actor, timestamp, nonempty reason, evidence observation, disposition, synthetic code, units, unit amount and currency; unique service/revision number and at most one successor per predecessor |
| Claim | One synthetic claim case per organization/encounter in F2; current_revision pointer; no inferred claim identity from patient/date |
| ClaimRevision | Append-only snapshot; predecessor, actor/time/reason, policy version and activation generation, synthetic route identity/version, envelope format version, exact UTF-8 envelope bytes and SHA-256, Decimal total and currency |
| ClaimLine | Append-only ordered membership of one revision; stable Service ID and exact ServiceRevision reference, code/quantity/price/amount snapshot; unique revision/ordinal and revision/service; service encounter must equal claim encounter |
| ClaimApproval | Immutable actor/time, exact ClaimRevision and envelope digest; at most one accepted approval per revision |
| SyntheticPolicySelection | One row per organization selecting a known immutable fixture policy version with a monotonically increasing activation generation; explicit command compares the expected version/generation |

Source bytes, observations, F1 identity decisions, service revisions, claim revisions, lines and approvals cannot be edited or deleted through ordinary SQL application writes. Service and Claim head pointers are the only mutable current-version selectors. Their pointers must belong to their own aggregate and organization. A correction appends a successor and advances the head atomically. Protect immutable aggregate identity fields from later update. Use SQL constraints/triggers for relationships the ORM cannot express; test direct writes as well as commands.

F2 does not correct patient/encounter identity, merge entities or move a service between encounters. A wrong identity remains an explicit unsupported case. Excluding a mistaken service preserves its identity and history. No deletion, silent reassignment or downstream reversal policy is inferred.

### Database relationship and head contract

Use explicit composite unique target keys and foreign keys, or constraint triggers where a join is required. Duplicate the minimum organization/encounter/patient identifiers needed for these constraints; callers cannot choose inconsistent copies. The required relationship matrix is:

- Service's accepted IdentityDecision must match its organization, encounter and patient; Encounter must match that patient. ServiceRevision must match its Service and organization, and its predecessor must belong to that Service.
- Every ServiceRevision records the identity decision used to admit its evidence observation. That decision must reference the exact observation and match the Service's encounter/patient; same organization alone is insufficient. The owner derives this reference rather than accepting an unrelated caller-supplied decision.
- Claim's encounter/patient pair must match records. ClaimRevision must match its Claim and encounter; predecessor must belong to the same Claim. Use unique claim/revision number and enforce one successor per predecessor, as for services.
- ClaimLine's ServiceRevision must belong to its stated Service; its Service encounter must match its ClaimRevision's Claim encounter. Enforce both pairs, not only independent same-organization references. Its ordinal and Service are unique within that ClaimRevision.
- ClaimApproval's organization/revision/digest triple must reference the same immutable ClaimRevision/digest. A digest copied from another revision cannot form a valid approval.
- Service and Claim head references must match their own aggregate. First revision has ordinal 1 and no predecessor; every subsequent revision has the prior ordinal plus one and that predecessor. A noninitial head change may only advance to its direct successor. Reject rewinds, skipped predecessors and adoption of another aggregate's revision in database triggers. A same-head no-op is harmless. If insertion needs a temporarily null head, use deferred constraints to require a valid nonnull head at transaction commit.
- PolicySelection cannot be deleted or reset. Its database guard requires a known fixture version, generation 1 on initialization, unchanged generation on a same-version no-op and exactly prior generation plus one on every version change. Receipts and all accepted history retain update/delete protection.

The ORM command owns validation of economic snapshot content and deterministic serialization; approval/actionability independently verify those snapshots and bytes before claiming usability. Direct SQL constraints establish relationships and irreversible head progression, not permission to bypass owner commands. No database-superuser tamperproof claim is made.

## Records commands and provenance

`accept_service(actor, organization, request_id, identity_decision_id, evidence_observation_id, code, units, unit_amount, currency, reason)` creates a Service and its first accepted revision in one transaction. The operator explicitly enters the synthetic values; source note text is not parsed as clinical coding or price authority. Multiple services may originate from the same observation only through distinct explicit requests.

`revise_service(actor, organization, request_id, service_id, expected_revision_id, evidence_observation_id, disposition, code, units, unit_amount, currency, reason)` appends a correction or exclusion. An excluded revision retains the previous accepted economic values and adds its exclusion reason; it is unavailable for new claim selection. Reinstatement is another accepted revision with an explicit reason and values. Reject a stale expected head without mutation.

Evidence must be a retained same-organization observation whose accepted identity decision identifies the service's patient and encounter. New acceptance/correction verifies its referenced artifact bytes using the F1 store before committing. A later source delivery or reparse cannot update any accepted service. Missing bytes block new service acceptance/correction, and remain visible as an availability issue; retained accepted decisions are still historical facts. F2 claim preparation consumes accepted records and does not re-interpret or require rereading raw artifacts.

Expose records queries for service detail/history and an exact current selection for one encounter, with an optional transaction lock. Return stable IDs, accepted revision IDs, evidence references and explicit included/excluded reasons. No view reads raw records tables to reconstruct acceptance rules independently.

## Synthetic economics and policy

Only the explicitly synthetic codes SYN-A and SYN-B, USD, integer units 1 through 100 and nonnegative unit amounts with at most two fractional digits are supported. Unit amounts are operator-entered synthetic values from 0.00 through 9999.99. Reject floats, nonfinite values, negative amounts, unsupported codes/currencies and excess precision; never silently round accepted input. Use Decimal throughout and PostgreSQL numeric sized for the maximum 100 lines. Line amount equals units times unit amount, and claim total equals the sum of exact selected line amounts. Display zero-valued lines explicitly.

Use two immutable, repository-defined fixture policies: synthetic-v1 allows SYN-A and SYN-B; synthetic-v2 allows SYN-A only. Both use the same arithmetic and limits. These are test rules, not medical coding or coverage policy. Service acceptance recognizes the fixture code vocabulary; claim preparation validates the selected lines against the currently selected policy. Changing policy does not rewrite accepted services.

Seed synthetic-v1 for demo organizations. `select_synthetic_policy(actor, organization, request_id, expected_version, expected_generation, version)` only selects a known fixture and uses compare-and-set. Selecting the already-current version is an unchanged result. Every actual change increments the generation, including switching back to an earlier version. Claim revisions bind both version and generation, so restoring a policy never resurrects an old approval. An authenticated synthetic settings form exposes the current version and consequences. No editable rule engine, payer configuration or privileged production role is implied. Active membership is sufficient for this synthetic milestone, including same-actor preparation and approval; separation of duties is a production policy gap.

Route inputs are a labeled fake destination plus immutable route version, never a URL or credential. The permitted fixtures are synthetic-receiver/v1 and synthetic-receiver/v2. Neither sends anything. A route change requires a new ClaimRevision.

## Claim preparation and approval

`prepare_claim_revision(actor, organization, request_id, encounter_id, expected_claim_revision_id, selected_service_revision_ids, route_id, route_version, reason)` creates the case if absent or appends a new revision. Null expected revision means create only; it cannot overwrite an existing head. Require 1 through 100 unique services, all current accepted heads of the exact encounter, and the current synthetic policy. An excluded or superseded revision, mixed encounter, duplicate service or unsupported policy input rejects the whole command.

The submitted order is the exact line order. Do not add, omit or deduplicate lines silently. Store only selected lines; show available unselected and excluded services with their reasons beside the preview. A newly added unselected service does not invalidate a deliberately fixed selection. A correction to any selected service does invalidate it, even if that correction happens to preserve its price.

Create the immutable envelope and line snapshots atomically in PostgreSQL. Use a versioned deterministic serializer: UTF-8 JSON with sorted object keys, fixed separators, no floating-point values and money represented as two-decimal strings. Include synthetic-only marker, format version, organization/case/revision IDs, patient/encounter IDs, selected line/revision identities and values, policy version/activation generation and route identities, currency and total. Generate IDs before serialization. Preserve exact bytes and digest; approval never regenerates the payload from mutable records. Limit envelope bytes to 1 MiB; reject oversize before commit. No external artifact promotion or filesystem payload store is needed for F2.

`approve_claim_revision(actor, organization, request_id, claim_revision_id, expected_envelope_digest)` approves only the current claim head after verifying its exact stored bytes/digest, line snapshots, selected service heads, policy and route inputs. Display these inputs before POST. A stale digest, superseded revision, changed selected service or changed policy yields a specific conflict with no new approval. A different request confirming the same still-current approved revision returns its existing approval and records only the new accepted-command receipt; it cannot change the original approving actor/time. Approval is an internal synthetic decision, not dispatch permission.

`claim_actionability(actor, organization, claim_revision_id)` is the single claims-owned query for current approval usability. It checks current case head, selected service heads/dispositions, current policy version and activation generation, envelope integrity and exact approval binding. After membership and scoped target admission, return all applicable blockers in this fixed order: envelope_unavailable (missing bytes, digest mismatch or invalid snapshot binding), superseded_revision, selected_service_changed (including exclusion), policy_changed, unapproved (no approval bound to this exact revision/digest). The first item is the primary operator reason; retain the full ordered list and historical approval details. Return approved_current only when the list is empty. For example, a superseded revision with changed policy and corrupt bytes has envelope_unavailable as primary, followed by superseded_revision and policy_changed, plus unapproved if applicable. A presentation layer must not choose a different precedence. Route/selection changes are new case heads and therefore supersede old revisions. Missing or damaged historical source bytes are a separately displayed provenance-availability issue, not a silent rewrite of an accepted service or claim.

The UI must distinguish approved historically from approved for current inputs. Records does not mutate ClaimApproval when a service changes: the query detects stale dependencies. F3 must recheck this owner contract transactionally at its future effect-authorization boundary; a prior F2 screen or boolean cannot authorize dispatch.

## Retry and concurrency contract

Service acceptance/correction, claim preparation/approval and policy selection all carry a client request UUID generated before POST. A per-owner immutable accepted-command receipt binds organization, command kind, target identity, expected predecessor, complete canonical intent digest and resulting IDs. Insert the receipt in the same transaction as the accepted mutation. The request UUID namespace is unique within each owner and organization, including across its command kinds. Policy selection uses claims-owned receipts for both a committed switch and an accepted same-version no-op; replay returns the original selected version/generation alongside the current selection, even after subsequent policy changes. Same UUID and identical intent returns the original IDs; changed target or input conflicts. Check accepted replay before current-head preconditions; successful replay reports historical replay and current actionability separately. Rejected requests leave no receipt or partial business state and may be corrected using the same UUID.

Canonical receipt intent uses UTF-8 JSON with sorted object keys and fixed separators, like the envelope. Normalize UUIDs to lowercase hyphenated strings, money to exact two-decimal strings after precision validation, units/generations to integers and reason to its stored trimmed text. Preserve ordered selection arrays; do not sort them. Include organization, command kind, target IDs, expected predecessor/digest and every accepted input, with explicit null for absent optional values. Exclude request UUID and generated result IDs from the digest. Specifically:

- accept_service: identity decision, evidence observation, code, units, unit amount, currency and reason;
- revise_service: Service, expected revision, evidence observation, disposition, accepted values and reason (excluded values are canonicalized from the expected retained revision and cannot be overridden);
- prepare_claim_revision: encounter, expected claim revision or null, ordered selected ServiceRevision IDs, route ID/version and reason;
- approve_claim_revision: exact ClaimRevision and expected envelope digest;
- select_synthetic_policy: expected version/generation and requested version.

Record the policy version/generation actually bound by preparation in its result; it is not a caller input and does not change the digest of a replay. An accepted replay does not recalculate its result using today's policy. Validate/normalize input deterministically before comparing an accepted receipt, with active membership always required.

For multi-row operations use this lock order: encounter via the records-owned locking query, then organization SyntheticPolicySelection, then Claim if present. Service mutation locks encounter before Service. Policy selection locks only its own selection row. Resolve/scoped-validate IDs first and recheck all mutable preconditions under locks. Claim prepare/approve holds the encounter lock while comparing selected service heads, preventing a correction from slipping between validation and commit. The organization policy row serializes approval with policy changes. Claim uniqueness and receipt uniqueness handle absent-row races; use savepoints/reload to classify a uniqueness race without leaving a broken transaction.

Do not hold these locks across network calls. F2 has no network effect. A correction immediately after approval makes that approval historical and unusable when actionability is next queried; it does not erase the legitimately committed approval.

## Operator surface

Extend the existing intake and identity detail into service review, accepted service history, claim selection/preview, claim revision history and explicit approval. Forms carry request UUIDs and expected heads/digests through validation errors. Every mutation requires session authentication and CSRF; management commands use the same owners. Do not expose domain writes through Django admin.

Show source locator and accepted identity, the exact values being accepted, correction/exclusion reasons, available versus selected lines, policy/route versions, total, historical approvals and current blocking reason. Label every claim envelope synthetic and unsent. No generic completed, submitted or paid badge. Worklists derive from owning queries, with no separate mutable WorkItem queue.

## Acceptance evidence

Run the complete F1 suite and the following focused F2 tests against PostgreSQL 17, including fresh migrations, system checks and migration-drift check. Use separate connections/TransactionTestCase for races and a fresh process for durability.

1. CSV and DOCX observation to explicit service to exact selected claim and approval, through authenticated CSRF-protected views and direct commands; restart preserves the same IDs and bytes.
2. Service correction/exclusion/reinstatement retains actor, reason, evidence and predecessor. Reparse and corrected source leave accepted history intact; wrong or unresolved evidence and unavailable bytes block new service decisions.
3. Exact Decimal arithmetic, zero amounts and maximum bounds; reject float/nonfinite/negative/excess-precision inputs and unsupported codes, currencies, quantities and oversize envelope without partial rows.
4. Exact ordered selection conserves service membership and amounts. Reject duplicates, old heads, excluded services and mixed encounters. Unselected additions leave approval usable; selected corrections make it stale.
5. Same accepted request replays stable IDs; changed observation/identity/service/encounter, command kind, predecessor or intent conflicts. Rejected input may reuse its UUID. Policy response loss replays the original switch or no-op even after later activation; equivalent UUID/money representations canonicalize consistently and changed line order conflicts. Concurrent identical requests produce one mutation and receipt.
6. Competing service corrections and claim preparations with the same predecessor produce one successor. Concurrent correction versus approval cannot commit an approval that passes current checks against an already superseded input. Concurrent policy change versus approval is serialized and subsequent actionability reflects the committed policy.
7. Changed policy, route, selected service or claim selection prevents old approval from authorizing current inputs. Combined corrupt-envelope, superseded-revision, selected-service-change, policy-change and unapproved cases return the specified ordered blockers consistently, including primary reason in the UI. Restoring an earlier policy has a new activation generation and cannot reactivate its old approval; an equal-valued service correction likewise cannot reactivate approval of its predecessor. No automatic approval transfer to a new revision.
8. Envelope bytes/digest and snapshot identities survive replay/restart. Tampered or unavailable envelope fails closed; failed approval leaves no receipt. Ordinary direct update/delete attempts on immutable history fail in PostgreSQL. Direct head rewind/skip and policy generation rollback attempts fail; wrong ServiceRevision/Service, ClaimRevision/Claim and approval/revision/digest pairings fail.
9. Organization A cannot read, reference, revise, prepare or approve B's rows. Direct SQL wrong-organization, wrong aggregate head, wrong encounter/patient and wrong line references fail constraints. Inactive membership blocks every new command/query, including replay.
10. Invalid web forms preserve request identity and field errors without mutation; every new mutation entrypoint enforces CSRF. Captured logs/error summaries contain IDs/reason codes only; synthetic sensitive sentinel appears only in authorized detail.

Deliver a focused draft PR, exact head, resolved versions, setup/walkthrough, executed evidence and unrun checks. The existing required PostgreSQL workflow must run both suites. Do not claim manual browser, live interoperability or production qualification from server tests.

## Decisions, alternatives and handoff

Accepted direction from the charter: records owns accepted services; claims owns immutable revisions and approvals; exact membership and current inputs determine actionability. Merge of PR #3 accepts the detailed choices above and admits F2 implementation.

Deliberately bounded choices: one claim case per encounter, integer quantities, USD-only synthetic values, manual synthetic service entry, fixed fixture policy versions, immutable database envelope, dynamic approval invalidation and one operator role. Rejected for F2: deriving billing codes from notes, generic policy engines, broad identity correction, automatic service inclusion, automatic approval carry-forward and durable dispatch infrastructure.

Remaining production questions: actual coding/coverage/pricing, fractional units and currencies, split or corrected claims after external effects, separation of duties, identity reversal and private retention. None is answered by these fixtures. F3 still requires an explicit intent/authorization/attempt/receiver card after F2 acceptance.

Sol's assignment begins only after the entry gate is recorded. Outcome and ownership are this card; inputs are the merged F1, charter and this file. Privacy classification is public synthetic only. Dependencies are the accepted records query and schema seams before a test lane begins. Acceptance evidence is the suite above. Stop after draft PR/evidence for Astra, or escalate a contract contradiction or two failed attempts at one approach. No F3 work or merge by the delivery agent.
