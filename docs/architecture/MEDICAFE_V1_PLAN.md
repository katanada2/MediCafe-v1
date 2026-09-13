# MediCafe V1 plan

**Status:** architecture and foundation planning only. This document describes a target direction; it does not authorize runtime implementation, migration, deployment, or a production-readiness claim.

## Purpose and relationship to V0

MediCafe V1 is intended to become a clean, open-source application core under the `katanada2` owner. The private MediCafe repository is the historical proving ground for workflows, operational discoveries, and business evidence. V1 is a separate public repository and authority.

V0 remains the current production authority until a capability has an explicit, reviewed transfer. V1 may learn from V0 through a private evidence register and small requirement updates. Selected requirements or reusable code require explicit publication and redistribution review before transfer. Private operational artifacts, credentials, clinic configuration, protected data, and private Git history must not be imported.

## Product intent

The target is a cloud-authoritative billing-office application, initially serving one clinic. It should cover:

**Intake → identity → coverage → service preparation → claim review → delivery → acknowledgments → remittance → financial posting and reconciliation → patient responsibility → cash confirmation.**

Archival export and operator worklists sit alongside that flow. Operator review, explanations, recovery, and unresolved work are product capabilities rather than afterthoughts.

The design should preserve organization-scoped identity and relationships for future growth without committing the first release to a multi-clinic platform.

## Architectural direction

The proposed foundation is a modular monolith with:

- PostgreSQL as the durable system of record for current business state.
- Protected artifact storage with provenance, timestamps, and a clear relationship to the business record that produced or accepted an artifact.
- Authenticated application entrypoints for operators and integrations.
- Durable workers for work that may outlive an HTTP request, including retries and recovery of uncertain outcomes.
- Shared business owners used by web requests and workers so that asynchronous execution does not create a second authority path.

Keep domain ownership explicit and the number of concepts small. Introduce another service or framework only when an exercised requirement justifies it. The architecture should be understandable through its transactions, invariants, interfaces, and operator explanations.

## Authority model

The system must distinguish these states and their evidence:

- source observations received from an external system;
- accepted corrections made through an identified, reviewable operation;
- approved claim revisions;
- attempts to produce an external effect;
- confirmed outcomes observed from outside the application.

Medisoft is a delayed archive after authority transfer. Archive export failure cannot restore its authority over current V1 business state. Every fact currently obtained from Medisoft needs a replacement owner, migration treatment, archival role, or an explicitly recorded unresolved gap.

The capability map and transfer inventory should identify the owner, evidence, invariant, unresolved policy, and acceptance examples for each fact. Public documents use synthetic examples; private source references belong in the private evidence register.

## Public and private boundary

Public material may include generic application code, generic integration contracts, architecture decisions, documentation, and synthetic tests or fixtures. Private material includes real patient or clinic data, credentials and tokens, clinic-specific configuration, operational outputs, migration evidence, and any vendor material whose redistribution rights are not established.

Before publication, review source files, fixtures, logs, document metadata, generated artifacts, and repository history. Automated scanning is useful evidence but does not establish that material is safe to publish.

## Roadmap

The roadmap is organized around demonstrable outcomes rather than dates:

1. **Charter:** settle product, authority, repository, and architectural boundaries.
2. **Specification:** produce the capability map, Medisoft transfer inventory, decision register, and synthetic acceptance scenarios.
3. **Foundation:** demonstrate one executable synthetic workflow from intake through review, claim revision, simulated delivery, inbound outcomes, and archival projection.
4. **Operational completeness:** incrementally cover real integration contracts, financial workflows, operator recovery, and remaining business policies.
5. **Private qualification:** run representative migration rehearsals, deployment validation, integration qualification, and operator acceptance in private environments.
6. **Controlled transition:** explicitly transfer each authority, reconcile outstanding work, and retire superseded V0 responsibilities.

See the [roadmap](../roadmap/README.md) for the milestone view and [decision records](../decisions/README.md) for how consequential choices are recorded.

## Foundation sequence

The first executable foundation should grow one running application through four dependency-ordered cards:

1. Persistence, artifact provenance, identity, and a minimal operator view.
2. Accepted corrections, service decisions, claim revisions, and approval.
3. Durable outbound intent, independently observed simulated delivery, and recovery of uncertain remote effects.
4. Inbound matching, bounded financial semantics, and archival readback.

Each card extends and demonstrates the same application. A policy gap blocks only the affected capability and remains visible as unresolved work.

## Multi-agent execution model

Astra owns the charter, domain boundaries, shared interfaces, consequential design decisions, and milestone acceptance. Right-sized agents may handle bounded source investigation, synthetic fixtures, settled implementation cards, and focused verification.

Every assignment should state its concrete outcome, authoritative inputs, owned files or responsibility, dependencies, prohibited scope, acceptance evidence, public/private classification, and stop condition. Use at most two implementation lanes and one writer per shared production seam. Resolve shared interfaces before parallel implementation, and use independent review for consequential boundaries.

Maintain a compact decision and handoff record containing accepted decisions, open questions, rejected approaches, integration status, and the next work. Measure cost per accepted milestone, including rework and review effort, rather than the cost of an individual response.

## Acceptance scenarios

The foundation and later milestones must exercise, at minimum:

- duplicate and corrected inputs;
- ambiguous identity and cross-organization rejection;
- durable corrections and stale approvals;
- exact outbound membership;
- worker restart and retry behavior;
- uncertain remote effects and independently observed outcomes;
- duplicate inbound events;
- archive outage without authority reversal;
- exclusion of sensitive tokens from diagnostics.

Use real PostgreSQL when making transaction or concurrency claims, and an independent receiver when making external-effect claims. These scenarios describe design acceptance; they are not evidence of compliance or production readiness.

## Defaults and planning completion

Use a maintained modern Python stack as the starting direction, internet-dependent ordinary operation, single-clinic scale, and synthetic foundation data. Choose framework versions and deployment details during foundation specification using current support information. Offline authoritative writes and a generalized multi-clinic platform are outside the initial foundation.

The planning package is complete when an implementer can execute its first foundation cards without inventing business policy or architectural ownership. Escalate ambiguous business semantics, cross-module decisions, and failed architectural assumptions to Astra. Keep acknowledgments, adjudication, remittance, posting, patient responsibility, and cash confirmation distinct; an uncertain remote effect must not trigger an unauthorized duplicate action.

The repository uses the MIT license. This planning baseline does not authorize application implementation, infrastructure provisioning, production migration, live claim submission, or patient communications; those require subsequent scoped work.
