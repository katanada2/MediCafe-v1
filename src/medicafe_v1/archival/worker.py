from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass
from datetime import timedelta

from django.db import IntegrityError, connection, transaction
from django.db.models import Q
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from medicafe_v1.access.services import require_active_membership
from medicafe_v1.sources.domain import CommandError

from .adapter import FrozenArchiveProjection, LoopbackArchiveAdapter
from .commands import ARCHIVE_RECEIVER_ID, ARCHIVE_RECEIVER_VERSION
from .models import (
    ArchiveAttempt, ArchiveAttemptOutcome, ArchiveProjection,
    ArchiveReadbackObservation, ArchiveWork,
)


@dataclass(frozen=True)
class ArchiveWorkerResult:
    reason_code: str
    work_id: object | None = None
    attempt_id: object | None = None
    observation_id: object | None = None


def _database_now():
    with connection.cursor() as cursor:
        cursor.execute("SELECT statement_timestamp()")
        return cursor.fetchone()[0]


def _frozen(projection, attempt):
    return FrozenArchiveProjection(
        str(projection.organization_id), str(projection.encounter_id),
        str(projection.id), projection.version, str(attempt.id),
        ARCHIVE_RECEIVER_ID, ARCHIVE_RECEIVER_VERSION,
        projection.projection_digest, projection.byte_length,
        bytes(projection.projection_bytes),
    )


def _finish(*, work, worker_id, generation, state, reason):
    now = _database_now()
    updated = ArchiveWork.objects.filter(
        pk=work.pk, state=ArchiveWork.STATE_LEASED,
        lease_owner=worker_id, fencing_generation=generation,
        lease_expires_at__gt=now,
    ).update(
        state=state, blocking_reason=reason,
        lease_owner="", lease_expires_at=None,
    )
    return bool(updated)


def _remaining_budget(authorization):
    used = ArchiveAttempt.objects.filter(
        authorization=authorization, possible_write=True
    ).count()
    return max(authorization.allowed_attempts - used, 0)


def _recover_expired(work):
    latest = work.attempts.filter(possible_write=True).order_by("-started_at", "id").first()
    if latest is None or hasattr(latest, "outcome"):
        ArchiveWork.objects.filter(pk=work.pk).update(
            state=ArchiveWork.STATE_PENDING, lease_owner="", lease_expires_at=None,
            blocking_reason="",
        )
        return ArchiveWorkerResult("archive_lease_released", work.id)
    ArchiveAttemptOutcome.objects.create(
        organization_id=work.organization_id, attempt=latest,
        kind=ArchiveAttemptOutcome.UNKNOWN,
        reason="lease_expired_after_possible_write", ended_at=timezone.now(),
    )
    if _remaining_budget(work.scheduled_authorization):
        state, reason, result = (
            ArchiveWork.STATE_PENDING, "archive_write_unknown", "archive_retry_pending"
        )
    else:
        state, reason, result = (
            ArchiveWork.STATE_FINISHED, "archive_write_unknown", "archive_write_unknown"
        )
    ArchiveWork.objects.filter(pk=work.pk).update(
        state=state, due_at=timezone.now(), blocking_reason=reason,
        lease_owner="", lease_expires_at=None,
    )
    return ArchiveWorkerResult(result, work.id, latest.id)


def _claim_work(*, worker_id, lease_seconds):
    with transaction.atomic():
        now = _database_now()
        expired = ArchiveWork.objects.select_for_update(skip_locked=True).select_related(
            "scheduled_authorization"
        ).filter(
            state=ArchiveWork.STATE_LEASED, lease_expires_at__lte=now,
        ).order_by("due_at", "id").first()
        if expired:
            return None, _recover_expired(expired)
        work = ArchiveWork.objects.select_for_update(skip_locked=True).filter(
            state=ArchiveWork.STATE_PENDING, due_at__lte=now,
        ).order_by("due_at", "id").first()
        if work is None:
            return None, None
        generation = work.fencing_generation + 1
        work.state = ArchiveWork.STATE_LEASED
        work.lease_owner = worker_id
        work.lease_expires_at = now + timedelta(seconds=lease_seconds)
        work.fencing_generation = generation
        work.blocking_reason = ""
        work.save(update_fields=[
            "state", "lease_owner", "lease_expires_at", "fencing_generation",
            "blocking_reason", "updated_at",
        ])
        return (work.id, generation), None


def _admit_attempt(*, work_id, worker_id, generation, possible_write=True):
    with transaction.atomic():
        work = ArchiveWork.objects.select_for_update().select_related(
            "projection", "scheduled_authorization"
        ).get(id=work_id)
        now = _database_now()
        authorization = work.scheduled_authorization
        if (
            work.state != ArchiveWork.STATE_LEASED or work.lease_owner != worker_id
            or work.fencing_generation != generation or work.lease_expires_at <= now
        ):
            return None
        if _remaining_budget(authorization) <= 0:
            _finish(
                work=work, worker_id=worker_id, generation=generation,
                state=ArchiveWork.STATE_FINISHED, reason="archive_attempt_budget_exhausted",
            )
            return None
        ordinal = ArchiveAttempt.objects.filter(authorization=authorization).count() + 1
        attempt = ArchiveAttempt.objects.create(
            organization_id=work.organization_id, projection=work.projection,
            authorization=authorization, work=work, ordinal=ordinal,
            receiver_id=ARCHIVE_RECEIVER_ID,
            receiver_version=ARCHIVE_RECEIVER_VERSION,
            projection_digest=work.projection.projection_digest,
            byte_length=work.projection.byte_length,
            lease_owner=worker_id, fencing_generation=generation,
            started_at=now, possible_write=possible_write,
        )
        frozen = _frozen(work.projection, attempt)
    return frozen


def _fingerprint(evidence):
    value = {
        "receiver_id": evidence.receiver_id,
        "receiver_version": evidence.receiver_version,
        "target_receipt_id": evidence.target_receipt_id,
        "organization_id": evidence.organization_id,
        "encounter_id": evidence.encounter_id,
        "projection_id": evidence.projection_id,
        "projection_version": evidence.projection_version,
        "reported_attempt_id": evidence.reported_attempt_id,
        "projection_digest": evidence.projection_digest,
        "byte_length": evidence.byte_length,
        "received_digest": hashlib.sha256(evidence.received_bytes).hexdigest(),
    }
    return hashlib.sha256(json.dumps(
        value, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")).hexdigest()


def _evidence_well_formed(evidence):
    try:
        identifiers = (
            evidence.organization_id, evidence.encounter_id,
            evidence.projection_id,
        )
        if any(str(uuid.UUID(value)) != value for value in identifiers):
            return False
        if evidence.reported_attempt_id is not None and (
            str(uuid.UUID(evidence.reported_attempt_id)) != evidence.reported_attempt_id
        ):
            return False
    except (ValueError, TypeError, AttributeError):
        return False
    observed_at = parse_datetime(evidence.observed_at) if isinstance(
        evidence.observed_at, str
    ) else None
    return (
        isinstance(evidence.receiver_id, str)
        and isinstance(evidence.receiver_version, str)
        and isinstance(evidence.target_receipt_id, str)
        and 1 <= len(evidence.target_receipt_id) <= 100
        and isinstance(evidence.projection_version, int)
        and not isinstance(evidence.projection_version, bool)
        and evidence.projection_version >= 1
        and isinstance(evidence.projection_digest, str)
        and len(evidence.projection_digest) == 64
        and all(character in "0123456789abcdef" for character in evidence.projection_digest)
        and isinstance(evidence.byte_length, int)
        and not isinstance(evidence.byte_length, bool)
        and evidence.byte_length >= 1
        and isinstance(evidence.received_bytes, bytes)
        and observed_at is not None and observed_at.utcoffset() is not None
    )


def _observation_matches_projection(observation, projection):
    return (
        observation.observed_state == ArchiveReadbackObservation.STATE_VERIFIED
        and observation.organization_id == projection.organization_id
        and observation.lookup_projection_id == projection.id
        and observation.receiver_id == ARCHIVE_RECEIVER_ID
        and observation.receiver_version == ARCHIVE_RECEIVER_VERSION
        and observation.reported_organization_id == projection.organization_id
        and observation.reported_encounter_id == projection.encounter_id
        and observation.reported_projection_id == projection.id
        and observation.reported_projection_version == projection.version
        and observation.reported_digest == projection.projection_digest
        and observation.reported_byte_length == projection.byte_length
        and bytes(observation.received_bytes) == bytes(projection.projection_bytes)
        and hashlib.sha256(bytes(observation.received_bytes)).hexdigest()
        == projection.projection_digest
    )


def _record_observation(*, projection, attempt, evidence):
    fingerprint = _fingerprint(evidence)
    existing = ArchiveReadbackObservation.objects.filter(
        organization_id=projection.organization_id,
        lookup_projection=projection,
        receiver_id=ARCHIVE_RECEIVER_ID,
        receiver_version=ARCHIVE_RECEIVER_VERSION,
        target_receipt_id=evidence.target_receipt_id,
        evidence_fingerprint=fingerprint,
    ).first()
    if existing:
        existing.refresh_from_db()
        return existing
    observed_at = parse_datetime(evidence.observed_at)
    valid = (
        evidence.receiver_id == ARCHIVE_RECEIVER_ID
        and evidence.receiver_version == ARCHIVE_RECEIVER_VERSION
        and evidence.organization_id == str(projection.organization_id)
        and evidence.encounter_id == str(projection.encounter_id)
        and evidence.projection_id == str(projection.id)
        and evidence.projection_version == projection.version
        and evidence.projection_digest == projection.projection_digest
        and evidence.byte_length == projection.byte_length
        and evidence.received_bytes == bytes(projection.projection_bytes)
        and hashlib.sha256(evidence.received_bytes).hexdigest() == projection.projection_digest
        and observed_at is not None
    )
    receipt_reused = ArchiveReadbackObservation.objects.filter(
        receiver_id=ARCHIVE_RECEIVER_ID,
        receiver_version=ARCHIVE_RECEIVER_VERSION,
        target_receipt_id=evidence.target_receipt_id,
    ).exclude(evidence_fingerprint=fingerprint).exists()
    try:
        with transaction.atomic():
            observation = ArchiveReadbackObservation.objects.create(
                organization_id=projection.organization_id,
                source_attempt=attempt, lookup_projection=projection,
                reported_attempt_id=evidence.reported_attempt_id,
                receiver_id=ARCHIVE_RECEIVER_ID,
                receiver_version=ARCHIVE_RECEIVER_VERSION,
                target_receipt_id=evidence.target_receipt_id,
                reported_organization_id=evidence.organization_id,
                reported_encounter_id=evidence.encounter_id,
                reported_projection_id=evidence.projection_id,
                reported_projection_version=evidence.projection_version,
                reported_digest=evidence.projection_digest,
                reported_byte_length=evidence.byte_length,
                received_bytes=evidence.received_bytes,
                evidence_fingerprint=fingerprint,
                observed_state=(
                    ArchiveReadbackObservation.STATE_VERIFIED
                    if valid and not receipt_reused
                    else ArchiveReadbackObservation.STATE_CONFLICT
                ),
                conflict_reason=(
                    "" if valid and not receipt_reused
                    else "archive_receipt_identity_conflict" if receipt_reused
                    else "archive_binding_mismatch"
                ),
                observed_at=observed_at or timezone.now(),
            )
    except IntegrityError:
        observation = ArchiveReadbackObservation.objects.filter(
            organization_id=projection.organization_id,
            lookup_projection=projection,
            receiver_id=ARCHIVE_RECEIVER_ID,
            receiver_version=ARCHIVE_RECEIVER_VERSION,
            target_receipt_id=evidence.target_receipt_id,
            evidence_fingerprint=fingerprint,
        ).first()
        if observation is None:
            raise
        observation.refresh_from_db()
        return observation
    observation.refresh_from_db()
    return observation


def _record_terminal(*, work, attempt, worker_id, generation, kind, reason,
                     observation=None, retry_unknown=False,
                     evidence_conflict=False, reported_observation_id=None):
    with transaction.atomic():
        attempt = ArchiveAttempt.objects.select_for_update().get(id=attempt.id)
        outcome, _created = ArchiveAttemptOutcome.objects.get_or_create(
            organization_id=attempt.organization_id, attempt=attempt,
            defaults={
                "kind": kind, "reason": reason, "ended_at": timezone.now(),
                "readback_observation": observation,
            },
        )
        work = ArchiveWork.objects.select_for_update().get(id=work.id)
        now = _database_now()
        if (
            work.state != ArchiveWork.STATE_LEASED or work.lease_owner != worker_id
            or work.fencing_generation != generation or work.lease_expires_at <= now
        ):
            return ArchiveWorkerResult(
                "archive_worker_fence_stale", work.id, attempt.id,
                reported_observation_id or (observation.id if observation else None),
            )
        if kind == ArchiveAttemptOutcome.TARGET_CONFIRMED:
            state, blocker, result = ArchiveWork.STATE_FINISHED, "", "archive_item_confirmed"
        elif kind == ArchiveAttemptOutcome.UNKNOWN and retry_unknown and _remaining_budget(
            attempt.authorization
        ):
            state, blocker, result = (
                ArchiveWork.STATE_PENDING, reason, "archive_retry_pending"
            )
            ArchiveWork.objects.filter(pk=work.pk).update(
                state=state, due_at=timezone.now(), blocking_reason=blocker,
                lease_owner="", lease_expires_at=None,
            )
            return ArchiveWorkerResult(result, work.id, attempt.id,
                                       observation.id if observation else None)
        else:
            state = ArchiveWork.STATE_BLOCKED if evidence_conflict else ArchiveWork.STATE_FINISHED
            blocker, result = reason, reason
        _finish(
            work=work, worker_id=worker_id, generation=generation,
            state=state, reason=blocker,
        )
    return ArchiveWorkerResult(
        result, work.id, attempt.id, observation.id if observation else None
        if reported_observation_id is None else reported_observation_id
    )


def run_archive_worker_once(*, worker_id=None, lease_seconds=10, adapter=None,
                            after_marker=None, after_transport=None):
    worker_id = worker_id or f"archive-worker-{uuid.uuid4()}"
    adapter = adapter or LoopbackArchiveAdapter()
    if lease_seconds <= float(getattr(adapter, "timeout", 0)):
        return ArchiveWorkerResult("archive_lease_not_longer_than_timeout")
    claim, recovered = _claim_work(worker_id=worker_id, lease_seconds=lease_seconds)
    if recovered:
        return recovered
    if claim is None:
        return ArchiveWorkerResult("no_archive_work")
    work_id, generation = claim
    work = ArchiveWork.objects.select_related("projection").get(id=work_id)
    try:
        adapter.validate_configuration(ARCHIVE_RECEIVER_ID, ARCHIVE_RECEIVER_VERSION)
    except CommandError as exc:
        frozen = _admit_attempt(
            work_id=work_id, worker_id=worker_id, generation=generation,
            possible_write=False,
        )
        if frozen is None:
            return ArchiveWorkerResult("archive_worker_fence_stale", work_id)
        attempt = ArchiveAttempt.objects.get(id=frozen.attempt_id)
        return _record_terminal(
            work=work, attempt=attempt, worker_id=worker_id, generation=generation,
            kind=ArchiveAttemptOutcome.PRE_WRITE_FAILED, reason=exc.reason_code,
        )
    frozen = _admit_attempt(work_id=work_id, worker_id=worker_id, generation=generation)
    if frozen is None:
        return ArchiveWorkerResult("archive_worker_fence_stale", work_id)
    if after_marker:
        after_marker(frozen)
    transport = adapter.send(frozen)
    if after_transport:
        after_transport(frozen, transport)
    attempt = ArchiveAttempt.objects.get(id=frozen.attempt_id)
    if transport.status == "rejected":
        return _record_terminal(
            work=work, attempt=attempt, worker_id=worker_id, generation=generation,
            kind=ArchiveAttemptOutcome.TARGET_REJECTED, reason=transport.reason,
        )
    if transport.status != "accepted":
        return _record_terminal(
            work=work, attempt=attempt, worker_id=worker_id, generation=generation,
            kind=ArchiveAttemptOutcome.UNKNOWN, reason=transport.reason,
            retry_unknown=True,
        )
    try:
        evidence = adapter.readback(frozen)
    except CommandError as exc:
        return _record_terminal(
            work=work, attempt=attempt, worker_id=worker_id, generation=generation,
            kind=ArchiveAttemptOutcome.UNKNOWN, reason=exc.reason_code,
            retry_unknown=True,
        )
    if evidence is None:
        return _record_terminal(
            work=work, attempt=attempt, worker_id=worker_id, generation=generation,
            kind=ArchiveAttemptOutcome.UNKNOWN, reason="archive_not_observed",
            retry_unknown=True,
        )
    if not _evidence_well_formed(evidence):
        return _record_terminal(
            work=work, attempt=attempt, worker_id=worker_id, generation=generation,
            kind=ArchiveAttemptOutcome.UNKNOWN, reason="archive_readback_invalid",
            retry_unknown=True,
        )
    with transaction.atomic():
        projection = ArchiveProjection.objects.select_for_update().get(id=frozen.projection_id)
        observation = _record_observation(
            projection=projection, attempt=attempt, evidence=evidence
        )
    if not _observation_matches_projection(observation, projection):
        return _record_terminal(
            work=work, attempt=attempt, worker_id=worker_id, generation=generation,
            kind=ArchiveAttemptOutcome.UNKNOWN, reason="archive_evidence_conflict",
            evidence_conflict=True, reported_observation_id=observation.id,
        )
    return _record_terminal(
        work=work, attempt=attempt, worker_id=worker_id, generation=generation,
        kind=ArchiveAttemptOutcome.TARGET_CONFIRMED,
        reason="archive_exact_readback", observation=observation,
    )


def reconcile_archive_item(*, actor, organization_id, projection_id, adapter=None):
    require_active_membership(actor=actor, organization_id=organization_id)
    try:
        projection = ArchiveProjection.objects.get(
            organization_id=organization_id, id=projection_id
        )
    except (ArchiveProjection.DoesNotExist, ValueError) as exc:
        raise CommandError("archive_projection_not_found") from exc
    attempt = projection.attempts.filter(possible_write=True).order_by(
        "-started_at", "id"
    ).first()
    if attempt is None:
        return ArchiveWorkerResult("archive_not_dispatched", projection.work.id)
    frozen = _frozen(projection, attempt)
    evidence = (adapter or LoopbackArchiveAdapter()).readback(frozen)
    if evidence is None:
        return ArchiveWorkerResult("archive_not_observed", projection.work.id, attempt.id)
    if not _evidence_well_formed(evidence):
        return ArchiveWorkerResult("archive_readback_invalid", projection.work.id, attempt.id)
    with transaction.atomic():
        projection = ArchiveProjection.objects.select_for_update().get(id=projection.id)
        observation = _record_observation(
            projection=projection, attempt=attempt, evidence=evidence
        )
        if _observation_matches_projection(observation, projection):
            if not hasattr(attempt, "outcome"):
                ArchiveAttemptOutcome.objects.create(
                    organization_id=organization_id, attempt=attempt,
                    kind=ArchiveAttemptOutcome.TARGET_CONFIRMED,
                    reason="archive_exact_readback", ended_at=timezone.now(),
                    readback_observation=observation,
                )
            ArchiveWork.objects.filter(projection=projection).update(
                state=ArchiveWork.STATE_FINISHED, blocking_reason="",
                lease_owner="", lease_expires_at=None,
            )
            return ArchiveWorkerResult(
                "archive_item_confirmed", projection.work.id, attempt.id, observation.id
            )
        ArchiveWork.objects.filter(projection=projection).update(
            state=ArchiveWork.STATE_BLOCKED,
            blocking_reason="archive_evidence_conflict",
            lease_owner="", lease_expires_at=None,
        )
    return ArchiveWorkerResult(
        "archive_evidence_conflict", projection.work.id, attempt.id, observation.id
    )
