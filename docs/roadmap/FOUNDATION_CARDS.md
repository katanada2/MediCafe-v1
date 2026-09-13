# Foundation work cards

Status: F1 admitted for synthetic implementation after this planning milestone merges. F2-F4 are ordered milestone contracts; their detailed policy/interface cards require Astra review before implementation. No live external effect or real data is admitted.

Read the [charter](../architecture/CHARTER.md) and [stack decision](../decisions/0001-foundation-stack.md). Sol owns delivery; Astra owns architectural exceptions and acceptance.

## F1: attributable intake and identity review

Outcome: an authenticated operator uploads synthetic CSV/DOCX, sees retained observations and reasons, resolves an observation to a patient/encounter, restarts the application, and sees the same decisions without duplicate canonical entities.

### Ownership and entry

One implementation owner for access, sources, records, migrations, UI and project setup. A second lane may create disjoint fixtures/tests only after schema and interfaces are written by the owner. No parallel writers to models, migrations, shared settings, lockfile or URL wiring.

Allowed surface: src/medicafe_v1, manage.py, pyproject.toml, uv.lock, tests, .github/workflows/foundation.yml, .env.example, setup documentation, and the delivery handoff. No real adapter, secret, private source copy, cloud provisioning or V0 change. Prefer a single cohesive F1 PR.

### Minimum model and constraints

Use UUID primary keys and UTC timestamps. Every tenant-owned model carries organization_id. Add a unique (organization_id, id) target key and PostgreSQL composite foreign keys for tenant-owned relationships, alongside ordinary Django references. Use explicit SQL migrations for these constraints where the ORM does not express them; do not pretend model validation alone protects direct writes.

| Model | Required meaning and uniqueness |
| --- | --- |
| Organization / Membership | Unique user/organization membership; active membership required on every command/query |
| Artifact | Unique organization/SHA-256, byte length, media type and server-generated storage key; immutable bytes |
| Delivery | Unique organization/source_namespace/source_key; artifact, admitted actor/time, optional supersedes delivery; parse summaries derived from version-scoped records, no delivery revision counter |
| ParseResult | Unique delivery/parser_version; complete observations only after atomic parse commit |
| ParseAttempt | Append-only terminal attempt UUID, delivery/parser_version, start/end time, succeeded/failed and reason code; no source values in failure text |
| Observation | Unique parse result/row ordinal; raw and normalized row values, warnings and source locator |
| Patient / PatientAlias | Synthetic display name; alias unique organization/namespace/value, kept as string |
| Encounter | Patient, service date, internal identity; multiple same-day encounters allowed |
| IdentityDecision | Observation, patient, encounter, actor/time/reason, request UUID and canonical input digest; unique organization/request UUID and at most one accepted decision per observation in F1 |

Same-organization constraints also apply to supersedes and identity-decision references. Ensure an identity decision's encounter belongs to its selected patient. Keep accepted decisions immutable in F1; reversal after acceptance is a later explicit policy, not a silent edit action.

### Commands and authorization

Use application commands for admit_delivery, parse_delivery and resolve_identity. resolve_identity owns the atomic attach-existing versus create-patient/create-encounter flow; creation helpers are internal to that transaction, not separately submitted UI commands. They receive an authenticated actor and organization explicitly, verify active membership, and scope all lookups. Return stable reason codes with target IDs and persisted status. Domain IDs supplied by a caller never bypass admission.

Use Django session login and POST with CSRF for every mutation. No public registration or domain model writes through Django admin. A local seed_demo management command creates two synthetic organizations and users, with passwords supplied at invocation or generated locally; never commit or log a fixed password. A user belongs to only one organization in the isolation fixture.

Observation detail can suggest an exact same-organization alias match. Confirming it is an explicit operator command. Missing or conflicting evidence stays unresolved; no fuzzy or name/date auto-merge. To create another legitimate encounter on the same day, the operator explicitly selects create rather than attach-existing. Source parsing never creates a patient or encounter automatically.

Lock the observation before resolving it. The form carries a request UUID generated before POST. Store that UUID and a canonical digest of the submitted resolution intent with the accepted decision. Retrying the same request and input returns the original decision and created IDs without creating anything. After a request is accepted, reusing its UUID with changed input is a conflict. Rejected requests persist no receipt or business mutation, so their UUID may be reused with corrected input. A different request attaching the same already-accepted target returns that decision; a competing different target or fresh create intent conflicts. resolve_identity encloses all entity creation and decision persistence in one transaction, so rejected, failed or repeated resolutions leave no stray patient/encounter.

### Synthetic formats and replay

Both formats use the columns row_id, patient_ref, service_date, note. CSV is UTF-8 with an optional BOM and a header. DOCX uses exactly one top-level table with that header; reject unsupported shapes with a reason code. Preserve raw strings; normalize surrounding whitespace and ISO dates without inferring a missing value. Invalid or absent patient/date values produce review warnings, not invented facts.

Source locator records CSV data-row ordinal or DOCX table/row ordinal. Retain duplicate row_id values as separate observations with a warning; row_id is never global identity. Ignore no unsupported additional populated table silently.

Admission requires a non-empty source_namespace and source_key. For the UI, generate a UUID source_key before POST and retain it for retries. Same key/same digest returns the existing delivery; same key/different bytes is a conflict. New key/same bytes creates a separate delivery referencing the same artifact. New key/changed bytes retains a new artifact; optional supersedes records intent without changing earlier observations or accepted decisions. No lineage version is inferred; the corrected-source test asserts both deliveries survive and the optional explicit link is retained.

Replay of a successful delivery/parser_version returns its ParseResult without new observations. ParseResult is success-only: a failed/incomplete parse creates neither a ParseResult nor observations. Persist every completed computation as an immutable ParseAttempt for that delivery/parser version, including failures. Retry creates a new attempt, never overwrites earlier failure evidence, and reads the same immutable bytes. The first successful computation commits its attempt, canonical result and observations together. A concurrent successful computation that finds the canonical result already committed records its own successful terminal attempt and reuses that result without new observations. Only a call that finds a result before performing computation is replay with no new attempt. On parsing error, persist only the failed terminal attempt. Lock Delivery when applying an outcome and recheck for an existing successful result. A concurrent failure remains visible history but cannot demote a successful result for that version. Derive the worklist summary from requested-version results and attempts, keeping a failed newer version distinct from a usable older result. A killed process with no terminal commit proves no completed attempt; absence of a result remains retryable. No persistent running state or lease engine is needed for synchronous F1 parsing. Changing parser version creates another result but cannot rewrite prior decisions; F1 ships one explicit parser version.

Bound uploads to 5 MiB and parsed rows to 1,000. For DOCX, also bound total declared uncompressed ZIP content to 25 MiB and reject encrypted/unsupported documents. These are synthetic foundation limits, not clinic requirements.

### Artifact and transaction boundary

Validate the upload media envelope and size before admission; retain admitted bytes even if content/header parsing subsequently fails. Stage bytes in the configured private local artifact root, compute SHA-256, and atomically promote to an organization-scoped server-generated content key before committing the Delivery/Artifact rows. Never use the supplied filename as a path. Verify an existing blob before reuse. If blob promotion fails, no successful delivery commits.

A crash after promotion but before database commit, including a losing concurrent database commit or rollback after promotion, can leave an unreferenced blob. This is allowed inert residue; no automatic deletion or generic reconciliation framework in F1. Repeating admission can reuse it. A missing/corrupt blob referenced by a delivery yields artifact_unavailable and blocks parse/identity acceptance until exact bytes are restored and verified. Retained historical decisions remain historical facts; the UI must show the availability problem.

No distributed atomicity claim. Test both failure windows using the real local adapter and PostgreSQL. Artifact download is not required in F1; protected detail views show observations only. Application logs contain IDs/reason codes, not row contents, filenames, secrets, or raw exception payloads.

### Operator surface and validation

Implement login, organization-scoped intake worklist, upload, delivery/observation detail, and explicit identity resolution forms. Derive unresolved work from durable source/decision state; do not create a parallel WorkItem model. Provide keyboard-accessible labels and visible reasons. Display synthetic-only status prominently.

Acceptance suite on real PostgreSQL:

1. Fresh migrations and seed setup; authenticated happy path for CSV and DOCX.
2. Duplicate key/same bytes, duplicate key/changed bytes, new key/same bytes, corrected source and replay; concurrent same-digest admissions produce one artifact and distinct keyed deliveries.
3. Leading-zero aliases, blank identity, invalid date, duplicate source rows, malformed DOCX and size limits.
4. Exact alias suggestion and explicit resolution; distinct same-day encounters; no automatic entity creation.
5. Concurrent identical/different resolution; durable accepted decision after fresh database connection/process restart.
6. User A cannot list/read/resolve user B's data, substitute references or supersedes targets; direct database cross-organization insert fails.
7. Blob failure before commit, crash residue after promotion, and missing/corrupt referenced bytes.
8. Reparse preserves accepted decisions; failure has a terminal ParseAttempt but no ParseResult or partial observations; retry retains the failure and produces one successful result. A concurrent failure cannot demote it. A test-only newer parser failure remains attributable to its version after retry, while the older successful result stays intact.
9. Synthetic sensitive sentinel absent from captured application logs and error summaries; present only in authorized detail where appropriate.
10. Web entrypoints invoke commands; a direct command caller cannot bypass membership or relation checks.

Use Django TestCase for ordinary cases and TransactionTestCase with separate database connections for concurrency. Run migrations, system checks, migration-drift check and the complete F1 test suite in GitHub Actions against PostgreSQL 17. No SQLite fallback. Add these checks as required on main only after the first workflow run succeeds.

Deliver exact setup/test commands, locked dependency versions, a synthetic walkthrough, test results, and a draft PR. If PostgreSQL cannot run locally, use the authorized GitHub Actions service for evidence; do not substitute an in-memory result or claim an unrun test passed.

Stop after the F1 PR and evidence packet. Astra reviews before merge and before F2. Escalate a contract contradiction or two failed attempts at the same approach instead of redesigning the charter.

## F2: accepted services and approved claim revision

Entry: Astra accepts F1 evidence and a detailed service/claim card. Build accepted corrections with provenance, bounded synthetic service policy, Decimal amounts and currency, exact line membership, immutable claim revisions and revision-scoped approvals. Material service/policy changes invalidate prior approval. No clinical inference or live claim payload assertion.

Prove accepted correction survives reparse/restart, excluded work has a reason, exact selected membership is conserved, and stale approval cannot authorize an action. Use a labeled synthetic envelope unless actual 837P mapping is independently specified and reviewed.

## F3: durable effects and uncertainty

Entry: F2 accepted and attempt/authorization/route schema reviewed. Add a PostgreSQL durable work owner and a separately observing fake receiver. Bind authorization, exact bytes, destination and attempt. Exercise pre-dispatch failure, post-dispatch loss, worker restart, duplicate pickup and receiver without idempotency.

Prove supported duplicates are suppressed and uncertain effects remain unresolved without automatic resend. Independent received bytes/identity establish receiver observations; producer booleans do not. No real payer endpoint.

## F4: inbound outcomes and delayed archive

Entry: F3 accepted and synthetic posting semantics approved. Ingest synthetic lifecycle and remittance separately; match explicit identities, deduplicate inbound deliveries and keep conflicting/unmatched items in review. Add only the financial posting semantics the reviewed fixture contract establishes.

Send versioned projections to a fake archival target with item readback. Prove partial failure, unknown completion, repeated batch and normal canonical operation during archive outage. Do not infer adjudication from acknowledgment or cash settlement from remittance.

## Later roadmap

After F4, refine real integrations and remaining policy from the gap register. Separate private qualification covers migration, actual provider transport, Medisoft archive, financial opening state, cloud controls and operator recovery. No synthetic milestone authorizes production cutover.
