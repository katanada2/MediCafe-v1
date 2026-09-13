# Contributing to MediCafe V1

The repository is in public architecture and foundation planning. Contributions should make the intended system easier to understand, review, and build while preserving a clean separation from private clinic operations.

## Before opening a change

- Read [AGENTS.md](AGENTS.md) and the relevant [V1 plan](docs/architecture/MEDICAFE_V1_PLAN.md).
- State the problem, intended outcome, affected capability, and any authority or privacy implications.
- Use synthetic names, identifiers, documents, and outcomes. Do not include patient information, credentials, clinic configuration, private logs, or migration evidence. Any deliberately selected V0 material requires explicit publication and redistribution review.
- Record a material architecture choice in [docs/decisions/](docs/decisions/README.md) before relying on it in runtime work.

## Pull requests

Keep each pull request focused on one coherent outcome. Include the acceptance examples or review evidence that support the change, identify unresolved policy, and link the relevant plan or decision record. Do not add placeholder frameworks, dependencies, deployment files, or generated artifacts merely to suggest a future implementation.

Before requesting review, check that:

1. The changed files are appropriate for a public repository.
2. Links and Markdown structure are valid.
3. Synthetic examples cannot be mistaken for real records.
4. The change does not silently change an authority boundary or claim production readiness.

Maintainers may request a narrower change when a proposal combines independent architecture decisions or crosses an ownership boundary without an explicit handoff.
