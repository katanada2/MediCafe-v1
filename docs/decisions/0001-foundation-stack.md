# ADR 0001: integrated Python foundation

Status: accepted on merge of this planning milestone.
Decision owner: Astra.
Applies to: synthetic F1 foundation, with a review before production deployment.

## Decision

Use Python 3.13, Django 5.2 LTS, PostgreSQL 17, psycopg 3, and python-docx for bounded DOCX table intake. Use the Python standard CSV parser. Use Django ORM, migrations, forms, templates, sessions, CSRF middleware, and its test runner. No Django REST Framework, SPA, Redis, Celery, or cloud SDK is needed for F1.

Use uv for the Python environment and committed lockfile. Resolve supported current patch versions within these selected series during implementation, commit the lock, and record the actual resolved versions. Do not silently switch a major series. Provide local PostgreSQL connection instructions and a GitHub Actions PostgreSQL service for integration tests; no cloud resources or mandatory Docker desktop setup.

Python code lives under src/medicafe_v1, with access, sources, and records created by F1. Keep manage.py at the repository root, tests under tests, fixtures under tests/fixtures, and local artifacts outside tracked files. There is no dependency on a private sibling checkout.

Use a local content-addressed artifact adapter for synthetic F1 and expose only the exercised put/read/verify interface. A production object-storage adapter and its access/retention policy are deferred. The interface does not claim distributed atomicity.

## Why

An integrated framework supplies identity sessions, forms, migrations, transaction primitives, and a small operator UI without requiring several independent platforms. Django models inside owning modules are acceptable; pure rules and adapter interfaces should remain independent where that separation is actually useful.

PostgreSQL is already the accepted canonical store. Use it in integration tests from the first card; SQLite cannot establish this foundation's constraints or concurrency behavior.

Alternatives deferred: FastAPI plus separate auth/admin/UI assembly, SPA frontend, external broker, generalized workflow engine, full event sourcing, and microservices. Revisit only for a concrete limitation shown by a consumer or deployment requirement.

## Support evidence

Reviewed 2026-09-13. Django 5.2 is an LTS release and supports Python 3.13; PostgreSQL 17 remains a supported major series. Check patch availability again when resolving the lock.

- [Django 5.2 release and Python compatibility](https://docs.djangoproject.com/en/5.2/releases/5.2/)
- [PostgreSQL support policy](https://www.postgresql.org/support/versioning/)
- [python-docx documentation](https://python-docx.readthedocs.io/en/stable/)

This selects a foundation stack. It does not establish a compliant deployment, vulnerability-free dependencies, vendor integration qualification, or operating cost.
