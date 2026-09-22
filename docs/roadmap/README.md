# Roadmap

MediCafe V1 has accepted synthetic intake/identity (F1), service/claim approval (F2), and durable synthetic delivery with explicit uncertainty (F3). Exact implementation evidence and PR provenance are recorded in the delivery handoff. Later milestones remain gated. The roadmap has no dates and does not represent production readiness.

See [foundation cards](FOUNDATION_CARDS.md) for foundation milestone scope, the [F3 setup](F3_SETUP.md) for the reproducible synthetic receiver/worker walkthrough, and [delivery handoff](DELIVERY_HANDOFF.md) for ownership, exact evidence, and PR history. F4 runtime remains gated on a separate explicit reviewed admission record.

## Milestones

1. **Charter** — agree on product intent, authority boundaries, repository boundary, and architectural direction.
2. **Specification** — map capabilities and facts, inventory the Medisoft authority transfer, record decisions, and define synthetic acceptance scenarios.
3. **Foundation** — demonstrate a synthetic end-to-end workflow from intake through review, claim revision, simulated delivery, inbound outcomes, and archival projection.
4. **Operational completeness** — add qualified integration contracts, financial workflows, operator recovery, and remaining business policies in dependency order.
5. **Private qualification** — perform representative migration rehearsals, deployment validation, integration qualification, and operator acceptance in private environments.
6. **Controlled transition** — transfer each authority explicitly, reconcile outstanding work, and retire superseded V0 responsibilities.

## Planning rules

Each milestone needs a demonstrable outcome, acceptance evidence, and a clear owner before it is considered complete. The foundation grows the same running application through the dependency-ordered sequence in the [V1 plan](../architecture/MEDICAFE_V1_PLAN.md). Policy gaps stay visible and block only the affected capability.

Work is coordinated through bounded assignments: Astra owns architecture and consequential decisions; right-sized agents handle settled, reviewable slices; at most two implementation lanes run at once; and each shared production seam has one writer.

## Detailed foundation contracts

- [F2: accepted services and approved claim revisions](F2_SERVICE_CLAIM_CARD.md) defines the service, claim, approval and concurrency interfaces accepted by merge of PR #3. Main containing that card admits F2 implementation.

- [F3 durable delivery and uncertainty contract](F3_DELIVERY_CARD.md) defines the reviewed effect boundary and independent receiver evidence. F3 runtime is admitted only when its explicit admission record in the handoff is merged.

- [F4 inbound outcomes and delayed archive contract](F4_OUTCOMES_ARCHIVE_CARD.md) defines synthetic attribution, conserved postings and independent archive readback. F4 runtime remains gated on accepted F3 evidence and an explicit reviewed admission record.

- [F4 implementation admission](F4_IMPLEMENTATION_ADMISSION.md) records accepted F3 evidence, historical attribution, conflict serialization and the bounded Sol delivery assignment. Main containing the merged record admits F4 runtime.
