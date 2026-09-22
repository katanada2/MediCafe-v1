# F2 synthetic service and claim walkthrough

This walkthrough extends the public synthetic F1 foundation. It does not authorize real patient data, payer rules, clinic configuration, dispatch, private V0 material, or production use.

## Resolved stack

F2 keeps the locked foundation stack unchanged: Python 3.13.15, Django 5.2.17, PostgreSQL 17, psycopg 3.2.13 with its 3.2.13 binary package, python-docx 1.2.0, and uv 0.12.13 in CI.

## Setup and verification

Follow the [F1 PostgreSQL setup](F1_SETUP.md), then apply the current migrations and seed the two isolated synthetic organizations:

```powershell
uv sync --locked
uv run python manage.py migrate --noinput
uv run python manage.py check
uv run python manage.py makemigrations --check --dry-run
uv run python manage.py seed_demo
uv run python manage.py test tests.f1 tests.f2 --verbosity 2
```

`seed_demo` selects immutable fixture policy `synthetic-v1` at activation generation 1 for each demo organization. It creates no services or claims.

## Synthetic walkthrough

1. Complete the F1 CSV or DOCX intake and explicitly resolve an observation to a patient and encounter.
2. Follow **Review accepted services and claims**. Enter an explicit `SYN-A` or `SYN-B` service, integer units, USD amount, evidence observation, and operator reason. Source notes are not code or price authority.
3. Append a correction, exclusion, or reinstatement and review the immutable predecessor, actor, evidence, and reason history.
4. Prepare a claim by checking the exact current service revisions in the intended line order and choosing `synthetic-receiver/v1` or `/v2`. The stored deterministic JSON envelope is labeled synthetic and unsent.
5. Inspect the exact lines, total, policy version/generation, route, and SHA-256 before approving the current revision. Approval is an internal synthetic decision, never dispatch permission.
6. Change a selected service or the synthetic fixture policy and revisit the prior claim. Its historical approval remains visible while the ordered current blockers explain why it is no longer actionable.
7. Restart the application and verify the same service, revision, envelope bytes, digest, claim, and approval IDs remain present.

The supported fixture policies are deliberately small: `synthetic-v1` allows `SYN-A` and `SYN-B`; `synthetic-v2` allows only `SYN-A`. Switching back creates a new activation generation and does not revive an older approval.

Passing the PostgreSQL suite is synthetic integration evidence only. It is not a manual browser walkthrough, live payer interoperability, compliance evidence, deployed qualification, production readiness, or an authority transfer from V0.
