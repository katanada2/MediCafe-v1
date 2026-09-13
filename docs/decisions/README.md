# Architecture decisions

This directory will hold concise decision records for choices that affect product boundaries, authority, data ownership, public/private separation, shared interfaces, or the order of foundation work.

## Record format

Each record should include:

- a stable identifier and title;
- status (`proposed`, `accepted`, or `superseded`);
- the context and forces behind the choice;
- the decision and its consequences;
- affected capabilities and interfaces;
- public/private classification and synthetic examples where useful;
- links to the plan and acceptance evidence.

Record a material architecture choice before runtime work depends on it. Keep unresolved business policy visible instead of silently turning an assumption into an authority rule. V0 evidence can inform a record, but private source, data, credentials, and operational artifacts do not belong in this public directory.

[ADR 0001: integrated Python foundation](0001-foundation-stack.md) is accepted when the charter milestone merges. The [charter](../architecture/CHARTER.md) governs the foundation; the [V1 plan](../architecture/MEDICAFE_V1_PLAN.md) preserves the earlier planning baseline.
