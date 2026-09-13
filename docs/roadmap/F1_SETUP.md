# F1 synthetic setup and walkthrough

This setup exercises only the public, synthetic F1 foundation. Do not upload real patient data, private V0 material, credentials, clinic configuration or operational evidence.

## Resolved foundation versions

- Python 3.13.15
- Django 5.2.17
- PostgreSQL 17 (the CI service and required local major series)
- psycopg 3.2.13 with its 3.2.13 binary package
- python-docx 1.2.0
- uv 0.12.13 used to resolve `uv.lock`

## Local PostgreSQL setup

Create an empty PostgreSQL 17 database and role using values you choose locally. Copy `.env.example` to `.env`, replace every placeholder, and export those variables in your shell. The application has no SQLite fallback.

Install the locked environment and initialize the schema:

```powershell
uv sync --locked
uv run python manage.py migrate --noinput
uv run python manage.py check
uv run python manage.py makemigrations --check --dry-run
uv run python manage.py seed_demo
```

`seed_demo` creates two synthetic organizations and two users, each with membership in only its own organization. Supply `--alpha-password` and `--beta-password`, or capture the locally generated one-time values from the command output. No fixed password is committed.

Start the local server with `uv run python manage.py runserver`, log in, and follow this synthetic walkthrough:

1. Open the intake worklist and upload a UTF-8 CSV or DOCX with columns `row_id, patient_ref, service_date, note`.
2. Admit the delivery, then explicitly parse its retained bytes. Parsing never creates patients or encounters.
3. Open an observation and choose either an existing patient/encounter or explicit creation. Provide a reason and submit the CSRF-protected form.
4. Restart the server and revisit the delivery. The observation, accepted identity decision and canonical IDs remain durable.
5. Log in as the other synthetic user and verify that the first organization's delivery is neither listed nor readable.

Uploads are limited to 5 MiB and 1,000 parsed rows. DOCX declared uncompressed ZIP content is limited to 25 MiB. Local artifacts are content-addressed below `MEDICAFE_ARTIFACT_ROOT` and are not tracked.

## Verification

The definitive suite runs against PostgreSQL 17:

```powershell
uv run python manage.py migrate --noinput
uv run python manage.py check
uv run python manage.py makemigrations --check --dry-run
uv run python manage.py test tests.f1 --verbosity 2
```

GitHub Actions runs the same checks with a PostgreSQL 17 service. Passing this suite establishes only the synthetic F1 foundation contract; it is not deployed qualification, compliance evidence, production readiness or migration acceptance.

