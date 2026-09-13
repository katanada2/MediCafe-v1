# Working guidance

MediCafe V1 is currently a public architecture and foundation-planning repository. Keep changes small, reviewable, and within the stated work item. Do not add runtime code, dependencies, deployment configuration, or operational data until the architecture decisions and roadmap authorize that work.

## Public boundary

- Commit only public, PII-clean material. Use synthetic examples and fixtures.
- Never commit patient information, credentials, clinic configuration, private operational outputs, or migration evidence. Transfer V0 material only after an explicit review establishes its publication suitability and redistribution rights; never import private Git history wholesale.
- Review generated files, logs, document metadata, and examples before publication. A scanner supports review; it does not replace human judgment.

## Architecture and coordination

- Astra owns the architecture charter, domain boundaries, shared interfaces, consequential decisions, and milestone acceptance.
- Delegate bounded investigations, synthetic fixtures, settled implementation cards, and focused verification to right-sized agents. Every assignment states its outcome, inputs, ownership, dependencies, acceptance evidence, privacy classification, and stop condition.
- Use at most two implementation lanes and one writer per shared production seam. Resolve shared interfaces before parallel work.
- Record accepted decisions, open questions, rejected alternatives, and handoffs in the repository’s planning records.
- Treat the private MediCafe repository as historical evidence and a proving ground. V0 retains current production authority; V1 is a design target until an explicit, reviewed authority transfer is complete.

## Review standard

Review changes for clear ownership, explicit authority, durable state, operator explanations, and public-boundary safety. Do not describe planning artifacts as compliance evidence, production readiness, or a completed migration.
