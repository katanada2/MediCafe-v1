# MediCafe V1 architecture charter

Status: accepted architectural direction for the synthetic foundation upon merge of this planning milestone. No production authority is transferred.

## Product and release envelope

Build a billing-office application whose deployed PostgreSQL database owns patient, encounter, accepted service, claim, and financial-workflow state. The public repository contains the application, including identity and financial logic. Private deployments hold real records, credentials, clinic policy, retained evidence, and migration data. Public source does not mean public patient records or an intentionally incomplete workflow core.

V1 initially serves one clinic at roughly 5,000 claims per year. Ordinary operation requires connectivity. CSV and DOCX remain intake families; provider responses add contextual observations. Medisoft becomes a delayed downstream archive only after explicit capability-level cutover. Its outage must not stop ordinary V1 processing or make its data authoritative again.

The complete product includes operator review, source corrections, coverage, service preparation, claim delivery, inbound lifecycle, reconciliation, patient responsibility, and eventually cash confirmation. Unknown business policies remain explicit gaps. No inferred clinical or payer rule becomes an accepted fact through this charter.

## Structural decisions

Use one domain-oriented Django application, PostgreSQL, protected artifact storage, and shared application commands. Start with server-rendered forms and worklists, using Django sessions and CSRF protection. Introduce a JSON API only when a named consumer needs it; do not add a frontend build system for the foundation.

Django ORM models and migrations may live inside each owning module. Business commands own mutations and transactions; views, management commands, and later workers call them. Pure matching and decision functions stay independent of HTTP and external integrations. Do not add generic repositories merely to hide the ORM.

| Owner | Owns | Allowed dependency direction |
| --- | --- | --- |
| access | Organization, membership, actor admission | No business-module imports |
| sources | Artifact admission, delivery identity, parsing, immutable observations | access and artifact/parser ports |
| records | Patient aliases, encounters, accepted identity and service decisions | access; source observation queries |
| claims | Claim revisions, approval, routing, delivery intent and attempts | access; accepted records queries |
| outcomes | Inbound evidence, attribution, posting and reconciliation | access; claims identity queries |
| archival adapter | Projection delivery and item readback | Published queries from records, claims, outcomes |
| application composition | Settings, URL wiring, adapter construction, operator screens | Calls owners; owns no competing business state |

Only create modules exercised by the current card. Later owners in this table are reserved responsibilities, not empty packages to scaffold. Cross-module writes use the owning command. Cross-module reads use narrow owning queries; database constraints may still express necessary relationships.

## Identity, authority, and transactions

Use durable internal UUIDs; preserve external identifiers as namespaced strings, including leading zeros. Patient plus date, source row number, and artifact digest are matching evidence rather than universal business identity.

Organization ownership is explicit on domain rows. Check active membership at every application command and query; user-provided organization or object IDs are never authority. Enforce same-organization relationships in PostgreSQL as well as application checks. Reads must scope by organization before resolving object IDs. Foundation access tests cover a user who belongs to only one of two synthetic organizations.

Raw source bytes and observations remain immutable. An accepted correction records target, evidence, actor, reason, time, and superseded decision. Reparse never silently changes accepted truth. Source correction is a new identified delivery, not modification-time precedence.

Claim approval binds exact revision, line membership, payload inputs, and applicable routing/policy version. Material changes require another revision and approval. Money uses Decimal and PostgreSQL numeric with currency. Acknowledgment, adjudication, remittance, posting, patient liability, and cash confirmation remain separate facts.

Keep database transactions local and short. A durable work item is execution bookkeeping, not fresh permission for a consequential external effect. Record intent, authorization, payload identity, attempt, independently observed result, and unresolved outcome. Reconciliation determines whether retry is safe after possible dispatch; worker restart alone never authorizes another send.

Use a PostgreSQL work table when F3 first exercises durable external work. Do not introduce Redis, a broker, event sourcing, a workflow engine, or a global evidence registry for the foundation.

## Operator experience

The first screen is a scoped intake worklist. A detail page explains source location, observed value, accepted identity, outstanding issue, and permitted next action. Business state drives the worklist; it is not a second mutable queue. Add work assignment or notifications only when required.

Later screens extend this pattern through service review, claim approval, uncertain delivery, unmatched remittance, and archive lag. Show distinctions such as unknown, rejected, pending, and confirmed rather than a single green completion badge.

## Public boundary and transition

The public application must run from synthetic examples without reading private V0 files. Generic vendor adapters may be public when redistribution rights permit. Real source data, diagnostic bundles, screenshots containing records, secrets, and migration evidence remain private. Review publication content; ignore rules and scanners are supporting controls.

Treat the earlier V0 spine investigation as historical discovery, not fresh production qualification. Maintain its private evidence references outside this repository. New V0 lessons enter as reviewed requirement deltas. Do not copy its file/process/XP architecture, entire guidance layer, or Git history.

Before each production authority transfer, separately establish replacement coverage, migration population, identity mapping, financial opening state, outstanding/unknown effects, cutover writer, reconciliation, and recovery. Restoring a database does not undo an external send. No live data, provisioning, payer enrollment, deployment, patient communication, or XP write is authorized here.

## Execution and acceptance

Astra owns this charter, shared contracts, material design changes, and milestone acceptance. Sol owns delivery of an admitted card, with at most two implementation lanes and one writer per shared seam. Mechanical choices inside a card are delegated; changes to meaning or ownership are escalated with evidence and a concrete proposal.

The first runtime authorization is limited to F1 in [foundation cards](../roadmap/FOUNDATION_CARDS.md), after this milestone merges. Later cards require their entry gate and Astra acceptance of the preceding evidence. Passing F1 is a synthetic foundation claim only.

See the [capability map](CAPABILITY_MAP.md), [stack decision](../decisions/0001-foundation-stack.md), and [handoff](../roadmap/DELIVERY_HANDOFF.md).
