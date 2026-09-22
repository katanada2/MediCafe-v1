# F4 synthetic outcomes and delayed archive walkthrough

This walkthrough extends the accepted public-synthetic F1–F3 foundation with
inbound lifecycle/remittance evidence, a conserved derived ledger, coherent
archive projections, and a separate loopback archive target. Exact review and
execution evidence belongs in the [delivery handoff](DELIVERY_HANDOFF.md).
Nothing here authorizes real patient data, live payer/archive endpoints, private
V0 material, deployment, production use, or an authority transfer.

## Prerequisites

Use the locked versions and PostgreSQL 17 setup in the
[F1 setup](F1_SETUP.md), then complete the [F3 walkthrough](F3_SETUP.md) through
independent receiver acceptance of an exact synthetic claim delivery.

```powershell
uv sync --locked
uv run python manage.py migrate --noinput
uv run python manage.py check
uv run python manage.py makemigrations --check --dry-run
uv run python manage.py seed_demo
```

F4 history migrations refuse reversal once outcomes or archive history exists.
Repair forward or restore a coherent pre-F4 backup; do not delete accepted
events, postings, projections, attempts, outcomes, readback, or command receipts.

## Admit and interpret outcome evidence

Use the authenticated upload page to admit a UTF-8 JSON document under exactly
`synthetic-lifecycle` or `synthetic-remittance`, with media type
`application/json`. The one-mebibyte limit is enforced before and during
materialization. The schema is intentionally narrow and synthetic; the tests
construct canonical examples in `tests/f4/base.py`.

Open **Review lifecycle/remittance outcomes**, interpret the retained bytes, and
review the candidate page. Lifecycle acceptance requires contiguous sequence
and the exact historical delivery attribution. Remittance posting creates one
immutable event and a complete conserved batch. Alternate valid money spellings
such as `1`, `1.2`, and `1.20` canonicalize to the same two-decimal semantics.
Accepted facts remain visible when current artifact or conflict alerts later
appear. No screen describes reported credits as cash, payer approval, liability,
or production completion.

## Start the separate synthetic archive target

The target is a separate loopback HTTP process and stores exact projection bytes
in its own PostgreSQL schema. Application transactions do not write or query
that schema. Its connection inherits `POSTGRES_*`; these optional variables
override only the archive connection:

- `MEDICAFE_ARCHIVE_DB_NAME`
- `MEDICAFE_ARCHIVE_DB_USER`
- `MEDICAFE_ARCHIVE_DB_PASSWORD`
- `MEDICAFE_ARCHIVE_DB_HOST`
- `MEDICAFE_ARCHIVE_DB_PORT`
- `MEDICAFE_ARCHIVE_SCHEMA`

```powershell
$env:MEDICAFE_ARCHIVE_SCHEMA = "synthetic_archive_f4"
uv run python manage.py run_synthetic_archive --host 127.0.0.1 --port 8875 --schema synthetic_archive_f4
```

The target refuses non-loopback binding. In the application and worker shell,
pin the exact loopback `/v1` endpoint and finite timeout:

```powershell
$env:MEDICAFE_SYNTHETIC_ARCHIVE_URL = "http://127.0.0.1:8875/v1"
$env:MEDICAFE_SYNTHETIC_ARCHIVE_TIMEOUT = "2.0"
uv run python manage.py run_archive_worker --once --worker-id local-f4-worker --lease-seconds 10
```

`--once` is required. One invocation performs at most one due work or recovery
decision. The lease must be strictly longer than the adapter timeout. There is
no supplied background service or deployment unit.

## Archive operator walkthrough

1. From a synthetic claim page, open the encounter archive page. Its lag result
   recomputes all owner snapshots in one read-only REPEATABLE READ transaction.
2. Capture the expected head. An unchanged current fingerprint reuses the head;
   a change creates exactly one successor projection.
3. Queue the exact projection. This creates a three-possible-write initial grant
   and fenced work; it performs no network request.
4. Run the bounded worker. A successful send remains unknown until independent
   per-item readback returns the exact organization, encounter, projection,
   version, digest, length, and bytes.
5. Review attempts and readback on the projection page. Missing readback is
   `unknown_possible_write`, not evidence that no write occurred.
6. Reconcile without sending. If an immutable unknown attempt is later confirmed
   by readback, the unknown outcome remains historical while the item becomes
   historically confirmed.
7. After a finished rejected, pre-write-failed, or unknown item, authorize one
   exact manual retry against the latest attempt. Pending or leased automatic
   retry work is coalesced and never has its authorization, lease, or fence
   replaced.

Archive failure does not block canonical claim or remittance work. A batch is
complete only when every requested item has independently verified exact bytes.

## Verification

The definitive suite runs on a fresh PostgreSQL 17 service:

```powershell
uv run python manage.py migrate --noinput
uv run python manage.py check
uv run python manage.py makemigrations --check --dry-run
uv run python manage.py test tests.f1 tests.f2 tests.f3 tests.f4 --verbosity 2
```

F4 coverage includes strict JSON and semantic replay, historical attribution,
lifecycle order, conserved posting, direct-SQL relationship guards, authenticated
forms, coherent capture/lag, bounded retry/fencing, wrong-item readback, actual
separate-process archive storage/restart, and archive outage with canonical
remittance continuity. A green run is public-synthetic integration evidence,
not deployed qualification, live interoperability, compliance evidence,
production readiness, backup qualification, or V0 authority transfer.
