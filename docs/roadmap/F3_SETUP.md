# F3 durable synthetic delivery walkthrough

This walkthrough extends the accepted public-synthetic F1 and F2 foundations.
Astra has accepted the F3 runtime implementation and evidence in ready-for-review
PR #8, subject to final documentation and normal review/merge; the PR is not
merged. Nothing here authorizes real patient data, live payer endpoints, private
V0 material, deployment, production use, or F4 runtime.

## Prerequisites and database setup

Use the locked versions and PostgreSQL 17 setup in the [F1 setup](F1_SETUP.md),
then complete the [F2 walkthrough](F2_SETUP.md) through approval of a current
synthetic claim revision. Initialize and verify the complete current schema:

```powershell
uv sync --locked
uv run python manage.py migrate --noinput
uv run python manage.py check
uv run python manage.py makemigrations --check --dry-run
uv run python manage.py seed_demo
```

The canonical application database uses `POSTGRES_DB`, `POSTGRES_USER`,
`POSTGRES_PASSWORD`, `POSTGRES_HOST`, `POSTGRES_PORT`, and optional
`POSTGRES_CONNECT_TIMEOUT`. There is no SQLite fallback.

## Start the separate synthetic receiver

The receiver is a separate loopback HTTP process. It opens its own psycopg
connection and stores its ledger in a dedicated PostgreSQL schema; application
transactions neither write nor query that ledger. By default its connection
inherits the `POSTGRES_*` values. The following optional variables override only
the receiver connection:

- `MEDICAFE_RECEIVER_DB_NAME`
- `MEDICAFE_RECEIVER_DB_USER`
- `MEDICAFE_RECEIVER_DB_PASSWORD`
- `MEDICAFE_RECEIVER_DB_HOST`
- `MEDICAFE_RECEIVER_DB_PORT`
- `MEDICAFE_RECEIVER_SCHEMA`
- `MEDICAFE_RECEIVER_SOCKET_TIMEOUT` (per accepted connection, default `5.0` seconds)

In a dedicated terminal, start the loopback-only receiver on an unused local
port. The schema name must be a simple PostgreSQL identifier:

```powershell
$env:MEDICAFE_RECEIVER_SCHEMA = "synthetic_receiver_f3"
uv run python manage.py run_synthetic_receiver --host 127.0.0.1 --port 8765 --schema synthetic_receiver_f3
```

`--host` defaults to `127.0.0.1`, `--port` defaults to `8765` and must be in
`1..65535`, and `--schema` defaults to `MEDICAFE_RECEIVER_SCHEMA` or
`synthetic_receiver`. The receiver rejects non-loopback binding.

## Configure and run the bounded worker

Set both pinned fixture endpoints in the application/worker shell before Django
starts. The adapter accepts only exact `/v1` and `/v2` loopback URLs, ignores
proxy environment variables, rejects redirects, and never falls back to another
route.

```powershell
$env:MEDICAFE_SYNTHETIC_RECEIVER_V1_URL = "http://127.0.0.1:8765/v1"
$env:MEDICAFE_SYNTHETIC_RECEIVER_V2_URL = "http://127.0.0.1:8765/v2"
$env:MEDICAFE_SYNTHETIC_RECEIVER_TIMEOUT = "2.0"
uv run python manage.py run_delivery_worker --once --worker-id local-f3-worker --lease-seconds 10
```

`--once` is required. `--worker-id` is optional; an opaque UUID-based ID is
generated when omitted. `--lease-seconds` defaults to 10 and must be in
`1..300`; it must be strictly longer than the finite receiver timeout. One
invocation handles at most one due work item or one recovery decision and prints
a stable reason code. Run it again explicitly to process another item. No
background service or deployment unit is supplied by F3.

## Operator walkthrough

1. Start Django with the endpoint variables above, log in, and open an approved,
   currently actionable synthetic claim.
2. Choose **Request delivery of exact approved bytes**. This creates one durable
   intent and work row but does not itself make an HTTP call.
3. Before a possible-dispatch marker exists, **Cancel before dispatch** is
   permitted. After any possible dispatch, cancellation cannot erase the
   possibility of an external effect.
4. Run the worker once. Review the delivery page for the immutable attempt,
   current effect state, blocking reasons, and independently read receiver
   evidence. Receiver acceptance means only that this synthetic receiver stored
   the exact bytes; it does not mean payer submission, adjudication, remittance,
   payment, or completion.
5. Use **Read receiver evidence** to reconcile without sending bytes. A missing
   receipt is `not_observed`, not proof that no effect occurred.
6. For an uncertain `synthetic-receiver/v1` attempt, the page may offer
   **Authorize exact idempotent v1 retry**. The receiver retains one stable key
   and deduplicates exact bytes. The retry keeps the original intent/key and
   records a new attempt and authorization.
7. An uncertain `v2` attempt is never resent. Reconciliation may supplement it
   with later evidence, but negative lookup leaves it uncertain.

The principal current states are:

- `pending` or `leased`: queued or owned by a live fenced worker;
- `blocked`: definitely unsent and stopped by a pre-dispatch check;
- `definitely_unsent`: finished without any possible-dispatch marker;
- `cancelled`: durably canceled before possible dispatch;
- `uncertain`: at least one possible dispatch lacks definitive receiver proof;
- `receiver_rejected`: every possible attempt has verified no-acceptance proof;
- `receiver_accepted`: exact stored bytes and the full identity tuple were
  independently verified;
- `receiver_conflict`: evidence exists but cannot establish the required exact
  binding and must remain visible for review.

Restarting Django, the worker, or the receiver must preserve the intent,
attempt/outcome history, receiver ledger, and current explanation.

## Verification

The definitive foundation suite runs against PostgreSQL 17:

```powershell
uv run python manage.py migrate --noinput
uv run python manage.py check
uv run python manage.py makemigrations --check --dry-run
uv run python manage.py test tests.f1 tests.f2 tests.f3 --verbosity 2
```

The F3 tests start separate receiver and worker processes, use independent
receiver-ledger reads, terminate workers in bounded crash windows, and exercise
PostgreSQL locking and integrity guards. Passing them is public-synthetic
integration evidence only—not a manual browser walkthrough, deployed
qualification, live interoperability, compliance evidence, production
readiness, or an authority transfer from V0.
