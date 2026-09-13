# MediCafe V1

The first admitted runtime milestone is the synthetic F1 intake and identity-review foundation. See the [F1 setup and walkthrough](docs/roadmap/F1_SETUP.md) for PostgreSQL 17 setup, locked versions, verification commands and the public-data boundary.

MediCafe V1 is the public planning home for a cloud-authoritative medical billing application. It is intended to become a clean, open-source application core under the `katanada2` owner while the private MediCafe repository remains the historical proving ground for workflows and operational evidence.

## Current status

This repository contains the accepted architecture and a draft synthetic F1 application foundation under review. It contains no deployment configuration or production readiness claim. Public examples and fixtures must remain synthetic and free of protected health information, credentials, clinic configuration, and private operational data.

The V1 plan is the source for the proposed product shape, authority model, repository boundary, roadmap, and multi-agent working model:

- [Architecture charter](docs/architecture/CHARTER.md)
- [Foundation cards](docs/roadmap/FOUNDATION_CARDS.md)
- [Delivery handoff](docs/roadmap/DELIVERY_HANDOFF.md)
- [MediCafe V1 plan](docs/architecture/MEDICAFE_V1_PLAN.md)
- [Architecture index](docs/architecture/README.md)
- [Decision records](docs/decisions/README.md)
- [Roadmap](docs/roadmap/README.md)

## Intended product

The application will support a billing office from intake through financial reconciliation and archival export. Operator review, explanations, recovery, and unresolved work are part of the product. The first target is one clinic, with organization-scoped identity and relationships reserved for future growth without committing to a multi-clinic platform now.

The proposed architecture is a modular monolith with PostgreSQL, protected artifact storage, authenticated application entrypoints, and durable workers. Web requests and workers use the same business owners. The design keeps current business state authoritative in V1 while treating Medisoft as a delayed archive after each authority transfer is explicitly reviewed.

## Contributing during planning

Read [CONTRIBUTING.md](CONTRIBUTING.md) before opening a change. Architectural decisions are recorded before runtime implementation begins, and each contribution must preserve the public/private boundary. [SECURITY.md](SECURITY.md) describes how to report a suspected vulnerability or accidental sensitive-data exposure.

## License

The project is released under the [MIT License](LICENSE).
