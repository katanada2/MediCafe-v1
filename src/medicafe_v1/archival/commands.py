from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import asdict, dataclass, is_dataclass
from datetime import date, datetime
from decimal import Decimal

from django.db import IntegrityError, OperationalError, connection, transaction
from django.utils import timezone

from medicafe_v1.access.services import require_active_membership
from medicafe_v1.claims.queries import archive_claim_snapshot
from medicafe_v1.outcomes.queries import archive_outcome_snapshot
from medicafe_v1.records.queries import archive_encounter_snapshot, locked_encounter
from medicafe_v1.sources.domain import CommandError

from .models import (
    ArchiveAttempt, ArchiveAuthorization, ArchiveBatch, ArchiveBatchItem,
    ArchiveCommandReceipt, ArchiveHead, ArchiveProjection, ArchiveWork,
)


ARCHIVE_SCHEMA_VERSION = "synthetic-archive-v1"
ARCHIVE_RECEIVER_ID = "synthetic-archive"
ARCHIVE_RECEIVER_VERSION = "v1"


@dataclass(frozen=True)
class ArchiveCommandResult:
    reason_code: str
    projection_id: object | None = None
    batch_id: object | None = None
    authorization_id: object | None = None
    work_id: object | None = None
    attempt_id: object | None = None
    replayed: bool = False


def _json_value(value):
    if is_dataclass(value):
        return {key: _json_value(item) for key, item in asdict(value).items()}
    if isinstance(value, dict):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_json_value(item) for item in value]
    if isinstance(value, (uuid.UUID, Decimal, date, datetime)):
        return str(value)
    return value


def _canonical(value):
    encoded = json.dumps(
        _json_value(value), sort_keys=True, separators=(",", ":"), ensure_ascii=False,
    ).encode("utf-8")
    return encoded, hashlib.sha256(encoded).hexdigest()


def _request_uuid(value):
    try:
        return uuid.UUID(str(value))
    except (ValueError, AttributeError) as exc:
        raise CommandError("request_id_invalid") from exc


def _projection_uuid(value, *, allow_none=False):
    if value in (None, "") and allow_none:
        return None
    try:
        return uuid.UUID(str(value))
    except (ValueError, AttributeError) as exc:
        raise CommandError("projection_id_invalid") from exc


def _receipt_replay(*, organization_id, request_uuid, command_kind, intent_digest):
    receipt = ArchiveCommandReceipt.objects.filter(
        organization_id=organization_id, request_uuid=request_uuid
    ).first()
    if receipt and (
        receipt.command_kind != command_kind or receipt.intent_digest != intent_digest
    ):
        raise CommandError("request_reused_with_different_intent")
    return receipt


def _result_from_receipt(receipt):
    work_id = None
    if receipt.result_projection_id:
        work_id = ArchiveWork.objects.filter(
            projection_id=receipt.result_projection_id
        ).values_list("id", flat=True).first()
    return ArchiveCommandResult(
        receipt.result_code, receipt.result_projection_id, receipt.result_batch_id,
        receipt.result_authorization_id, work_id, replayed=True,
    )


def _serialization_failure(exc):
    cause = getattr(exc, "__cause__", None)
    return getattr(cause, "sqlstate", None) == "40001"


def _capture_head_race(exc):
    cause = getattr(exc, "__cause__", None)
    constraint = getattr(getattr(cause, "diag", None), "constraint_name", None)
    return constraint in {
        "arc_projection_enc_version_uniq",
        "archival_archivehead_encounter_id_key",
        "archival_archivehead_projection_id_key",
    }


def capture_archive_projection(
        *, actor, organization_id, request_id, encounter_id,
        expected_projection_id):
    require_active_membership(actor=actor, organization_id=organization_id)
    request_uuid = _request_uuid(request_id)
    expected_id = _projection_uuid(expected_projection_id, allow_none=True)
    intent_bytes, intent_digest = _canonical({
        "organization_id": organization_id,
        "command_kind": "capture_archive_projection",
        "encounter_id": encounter_id,
        "expected_projection_id": expected_id,
    })
    del intent_bytes
    replay = _receipt_replay(
        organization_id=organization_id, request_uuid=request_uuid,
        command_kind="capture_archive_projection", intent_digest=intent_digest,
    )
    if replay:
        return _result_from_receipt(replay)
    for attempt_number in range(3):
        try:
            with transaction.atomic():
                with connection.cursor() as cursor:
                    cursor.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
                require_active_membership(
                    actor=actor, organization_id=organization_id, for_update=True
                )
                encounter = locked_encounter(
                    actor=actor, organization_id=organization_id,
                    encounter_id=encounter_id,
                )
                replay = _receipt_replay(
                    organization_id=organization_id, request_uuid=request_uuid,
                    command_kind="capture_archive_projection", intent_digest=intent_digest,
                )
                if replay:
                    return _result_from_receipt(replay)
                head = ArchiveHead.objects.select_for_update().filter(
                    organization_id=organization_id, encounter=encounter
                ).select_related("projection").first()
                current_id = head.projection_id if head else None
                if current_id != expected_id:
                    raise CommandError("archive_projection_head_conflict")
                records_state = archive_encounter_snapshot(
                    actor=actor, organization_id=organization_id,
                    encounter_id=encounter.id,
                )
                claims_state = archive_claim_snapshot(
                    actor=actor, organization_id=organization_id,
                    encounter_id=encounter.id,
                )
                outcomes_state = archive_outcome_snapshot(
                    actor=actor, organization_id=organization_id,
                    encounter_id=encounter.id,
                )
                payload = {
                    "schema_version": ARCHIVE_SCHEMA_VERSION,
                    "organization_id": str(organization_id),
                    "encounter_id": str(encounter.id),
                    "records": records_state,
                    "claims": claims_state,
                    "outcomes": outcomes_state,
                }
                projection_bytes, fingerprint = _canonical(payload)
                if head and head.projection.source_fingerprint == fingerprint:
                    projection = head.projection
                    reason = "archive_projection_unchanged"
                else:
                    projection = ArchiveProjection.objects.create(
                        organization_id=organization_id, encounter=encounter,
                        version=(head.projection.version + 1 if head else 1),
                        predecessor=(head.projection if head else None),
                        source_fingerprint=fingerprint,
                        schema_version=ARCHIVE_SCHEMA_VERSION,
                        projection_bytes=projection_bytes,
                        projection_digest=hashlib.sha256(projection_bytes).hexdigest(),
                        byte_length=len(projection_bytes), captured_by=actor,
                    )
                    if head:
                        ArchiveHead.objects.filter(pk=head.pk).update(projection=projection)
                    else:
                        ArchiveHead.objects.create(
                            organization_id=organization_id, encounter=encounter,
                            projection=projection,
                        )
                    reason = "archive_projection_captured"
                ArchiveCommandReceipt.objects.create(
                    organization_id=organization_id, request_uuid=request_uuid,
                    command_kind="capture_archive_projection",
                    target_key=str(encounter.id), intent_digest=intent_digest,
                    accepted_by=actor, result_projection=projection,
                    result_code=reason,
                )
            return ArchiveCommandResult(reason, projection_id=projection.id)
        except (IntegrityError, OperationalError) as exc:
            retryable = _serialization_failure(exc) or _capture_head_race(exc)
            if not retryable or attempt_number == 2:
                if retryable:
                    raise CommandError("capture_conflict") from exc
                raise
    raise CommandError("capture_conflict")


def queue_archive_batch(
        *, actor, organization_id, request_id, projection_ids):
    require_active_membership(actor=actor, organization_id=organization_id)
    request_uuid = _request_uuid(request_id)
    ordered_ids = tuple(_projection_uuid(item) for item in projection_ids)
    if not 1 <= len(ordered_ids) <= 100 or len(set(ordered_ids)) != len(ordered_ids):
        raise CommandError("archive_batch_membership_invalid")
    _intent_bytes, intent_digest = _canonical({
        "organization_id": organization_id,
        "command_kind": "queue_archive_batch",
        "projection_ids": ordered_ids,
    })
    replay = _receipt_replay(
        organization_id=organization_id, request_uuid=request_uuid,
        command_kind="queue_archive_batch", intent_digest=intent_digest,
    )
    if replay:
        return _result_from_receipt(replay)
    with transaction.atomic():
        require_active_membership(
            actor=actor, organization_id=organization_id, for_update=True
        )
        replay = _receipt_replay(
            organization_id=organization_id, request_uuid=request_uuid,
            command_kind="queue_archive_batch", intent_digest=intent_digest,
        )
        if replay:
            return _result_from_receipt(replay)
        projections = ArchiveProjection.objects.filter(
            organization_id=organization_id, id__in=ordered_ids
        )
        by_id = {item.id: item for item in projections}
        if len(by_id) != len(ordered_ids):
            raise CommandError("archive_projection_not_found")
        existing_work = {
            item.projection_id: item
            for item in ArchiveWork.objects.select_for_update().filter(
                organization_id=organization_id, projection_id__in=sorted(ordered_ids)
            ).select_related("scheduled_authorization")
        }
        batch = ArchiveBatch.objects.create(
            organization_id=organization_id, created_by=actor
        )
        receipt = ArchiveCommandReceipt.objects.create(
            organization_id=organization_id, request_uuid=request_uuid,
            command_kind="queue_archive_batch", target_key=str(batch.id),
            intent_digest=intent_digest, accepted_by=actor, result_batch=batch,
            result_code="archive_batch_queued",
        )
        for ordinal, projection_id in enumerate(ordered_ids, start=1):
            projection = by_id[projection_id]
            work = existing_work.get(projection_id)
            if work is None:
                authorization = ArchiveAuthorization.objects.create(
                    organization_id=organization_id, projection=projection,
                    receiver_id=ARCHIVE_RECEIVER_ID,
                    receiver_version=ARCHIVE_RECEIVER_VERSION,
                    kind=ArchiveAuthorization.KIND_INITIAL,
                    command_receipt=receipt, allowed_attempts=3,
                    authorized_by=actor,
                )
                work = ArchiveWork.objects.create(
                    organization_id=organization_id, projection=projection,
                    scheduled_authorization=authorization,
                    state=ArchiveWork.STATE_PENDING, due_at=timezone.now(),
                )
                existing_work[projection_id] = work
            else:
                authorization = work.scheduled_authorization
            ArchiveBatchItem.objects.create(
                organization_id=organization_id, batch=batch, ordinal=ordinal,
                projection=projection, work=work, authorization=authorization,
            )
    return ArchiveCommandResult("archive_batch_queued", batch_id=batch.id)


def retry_archive_item(
        *, actor, organization_id, request_id, projection_id,
        expected_attempt_id):
    require_active_membership(actor=actor, organization_id=organization_id)
    request_uuid = _request_uuid(request_id)
    projection_uuid = _projection_uuid(projection_id)
    try:
        attempt_uuid = uuid.UUID(str(expected_attempt_id))
    except (ValueError, AttributeError) as exc:
        raise CommandError("archive_attempt_id_invalid") from exc
    _intent_bytes, intent_digest = _canonical({
        "organization_id": organization_id,
        "command_kind": "retry_archive_item",
        "projection_id": projection_uuid,
        "expected_attempt_id": attempt_uuid,
    })
    replay = _receipt_replay(
        organization_id=organization_id, request_uuid=request_uuid,
        command_kind="retry_archive_item", intent_digest=intent_digest,
    )
    if replay:
        return _result_from_receipt(replay)
    with transaction.atomic():
        require_active_membership(
            actor=actor, organization_id=organization_id, for_update=True
        )
        try:
            projection = ArchiveProjection.objects.get(
                organization_id=organization_id, id=projection_uuid
            )
            work = ArchiveWork.objects.select_for_update().select_related(
                "scheduled_authorization"
            ).get(organization_id=organization_id, projection=projection)
        except (ArchiveProjection.DoesNotExist, ArchiveWork.DoesNotExist) as exc:
            raise CommandError("archive_projection_not_found") from exc
        replay = _receipt_replay(
            organization_id=organization_id, request_uuid=request_uuid,
            command_kind="retry_archive_item", intent_digest=intent_digest,
        )
        if replay:
            return _result_from_receipt(replay)
        latest = ArchiveAttempt.objects.filter(
            organization_id=organization_id, projection=projection,
        ).select_related("outcome").order_by("-started_at", "id").first()
        if latest is None or latest.id != attempt_uuid:
            raise CommandError("archive_retry_attempt_stale")
        if not hasattr(latest, "outcome") or latest.outcome.kind not in {
            "unknown", "target_rejected", "pre_write_failed",
        }:
            raise CommandError("archive_retry_not_allowed")
        if work.state in {ArchiveWork.STATE_PENDING, ArchiveWork.STATE_LEASED} and (
            work.scheduled_authorization.kind == ArchiveAuthorization.KIND_MANUAL
            and work.scheduled_authorization.expected_predecessor_attempt_id == latest.id
        ):
            authorization = work.scheduled_authorization
            result_code = "archive_retry_already_scheduled"
            receipt = ArchiveCommandReceipt.objects.create(
                organization_id=organization_id, request_uuid=request_uuid,
                command_kind="retry_archive_item", target_key=str(projection.id),
                intent_digest=intent_digest, accepted_by=actor,
                result_projection=projection, result_authorization=authorization,
                result_code=result_code,
            )
        else:
            authorization_id = uuid.uuid4()
            receipt = ArchiveCommandReceipt.objects.create(
                organization_id=organization_id, request_uuid=request_uuid,
                command_kind="retry_archive_item", target_key=str(projection.id),
                intent_digest=intent_digest, accepted_by=actor,
                result_projection=projection,
                result_authorization_id=authorization_id,
                result_code="archive_retry_scheduled",
            )
            authorization = ArchiveAuthorization.objects.create(
                id=authorization_id, organization_id=organization_id,
                projection=projection, receiver_id=ARCHIVE_RECEIVER_ID,
                receiver_version=ARCHIVE_RECEIVER_VERSION,
                kind=ArchiveAuthorization.KIND_MANUAL,
                command_receipt=receipt, expected_predecessor_attempt=latest,
                allowed_attempts=1, authorized_by=actor,
            )
            ArchiveWork.objects.filter(pk=work.pk).update(
                scheduled_authorization=authorization,
                state=ArchiveWork.STATE_PENDING, due_at=timezone.now(),
                lease_owner="", lease_expires_at=None, blocking_reason="",
            )
            result_code = "archive_retry_scheduled"
    return ArchiveCommandResult(
        result_code, projection.id, authorization_id=authorization.id, work_id=work.id
    )
