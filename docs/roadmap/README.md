# Roadmap

MediCafe V1 is in architecture and foundation planning. The roadmap has no dates and does not represent production readiness.

See [foundation cards](FOUNDATION_CARDS.md) for the admitted F1 implementation scope and [delivery handoff](DELIVERY_HANDOFF.md) for ownership and evidence requirements. F2-F4 remain gated.

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
