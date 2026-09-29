from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import asdict
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal

from django.db import connection, transaction

from medicafe_v1.access.services import require_active_membership
from medicafe_v1.claims.queries import archive_claim_snapshot
from medicafe_v1.outcomes.queries import archive_outcome_snapshot
from medicafe_v1.records.queries import archive_encounter_snapshot
from medicafe_v1.sources.domain import CommandError

from .models import (
    ArchiveAttemptOutcome, ArchiveBatch, ArchiveHead, ArchiveProjection,
    ArchiveReadbackObservation, ArchiveWork,
)


@dataclass(frozen=True)
class ArchiveItemStatus:
    projection_id: object
    projection_version: int
    state: str
    reason: str
    confirmed_observation_id: object | None


@dataclass(frozen=True)
class ArchiveLagStatus:
    encounter_id: object
    state: str
    current_fingerprint: str
    head_projection_id: object | None
    head_version: int | None
    head_fingerprint: str


def _json_value(value):
    if hasattr(value, "__dataclass_fields__"):
        return {key: _json_value(item) for key, item in asdict(value).items()}
    if isinstance(value, dict):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_json_value(item) for item in value]
    if isinstance(value, (uuid.UUID, Decimal, date, datetime)):
        return str(value)
    return value


def _current_fingerprint(*, actor, organization_id, encounter_id):
    payload = {
        "schema_version": "synthetic-archive-v1",
        "organization_id": str(organization_id),
        "encounter_id": str(encounter_id),
        "records": archive_encounter_snapshot(
            actor=actor, organization_id=organization_id, encounter_id=encounter_id,
        ),
        "claims": archive_claim_snapshot(
            actor=actor, organization_id=organization_id, encounter_id=encounter_id,
        ),
        "outcomes": archive_outcome_snapshot(
            actor=actor, organization_id=organization_id, encounter_id=encounter_id,
        ),
    }
    encoded = json.dumps(
        _json_value(payload), sort_keys=True, separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def archive_current_lag(*, actor, organization_id, encounter_id):
    """Compare the head with one coherent current owner snapshot."""
    if connection.in_atomic_block:
        raise CommandError("archive_snapshot_outer_transaction_forbidden")
    with transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
        require_active_membership(actor=actor, organization_id=organization_id)
        fingerprint = _current_fingerprint(
            actor=actor, organization_id=organization_id,
            encounter_id=encounter_id,
        )
        head = ArchiveHead.objects.select_related("projection").filter(
            organization_id=organization_id, encounter_id=encounter_id,
        ).first()
        if head is None:
            return ArchiveLagStatus(
                encounter_id, "not_captured", fingerprint, None, None, "",
            )
        state = (
            "current_projection"
            if head.projection.source_fingerprint == fingerprint
            else "projection_lag"
        )
        return ArchiveLagStatus(
            encounter_id, state, fingerprint, head.projection_id,
            head.projection.version, head.projection.source_fingerprint,
        )


def _verified_observations(projection):
    return projection.readback_observations.filter(
        observed_state=ArchiveReadbackObservation.STATE_VERIFIED,
        organization_id=projection.organization_id,
        reported_organization_id=projection.organization_id,
        reported_encounter_id=projection.encounter_id,
        reported_projection_id=projection.id,
        reported_projection_version=projection.version,
        reported_digest=projection.projection_digest,
        reported_byte_length=projection.byte_length,
        received_bytes=projection.projection_bytes,
    )


def archive_item_status(*, actor, organization_id, projection_id):
    require_active_membership(actor=actor, organization_id=organization_id)
    try:
        projection = ArchiveProjection.objects.get(
            organization_id=organization_id, id=projection_id
        )
    except (ArchiveProjection.DoesNotExist, ValueError) as exc:
        raise CommandError("archive_projection_not_found") from exc
    conflict = projection.readback_observations.filter(
        observed_state=ArchiveReadbackObservation.STATE_CONFLICT
    ).order_by("recorded_at", "id").first()
    verified = _verified_observations(projection).order_by("recorded_at", "id").first()
    if conflict:
        return ArchiveItemStatus(
            projection.id, projection.version, "evidence_conflict",
            conflict.conflict_reason, None,
        )
    if verified:
        return ArchiveItemStatus(
            projection.id, projection.version, "historically_confirmed",
            "archive_exact_readback", verified.id,
        )
    work = ArchiveWork.objects.filter(projection=projection).first()
    if work is None:
        return ArchiveItemStatus(
            projection.id, projection.version, "not_queued",
            "archive_projection_not_queued", None,
        )
    if work.attempts.filter(outcome__kind=ArchiveAttemptOutcome.UNKNOWN).exists():
        return ArchiveItemStatus(
            projection.id, projection.version, "unknown_possible_write",
            work.blocking_reason or "archive_write_unknown", None,
        )
    return ArchiveItemStatus(
        projection.id, projection.version,
        "pending_execution" if work.state in {"pending", "leased"} else "failed_execution",
        work.blocking_reason, None,
    )


def archive_batch_status(*, actor, organization_id, batch_id):
    require_active_membership(actor=actor, organization_id=organization_id)
    try:
        batch = ArchiveBatch.objects.prefetch_related("items__projection").get(
            organization_id=organization_id, id=batch_id
        )
    except (ArchiveBatch.DoesNotExist, ValueError) as exc:
        raise CommandError("archive_batch_not_found") from exc
    return tuple(archive_item_status(
        actor=actor, organization_id=organization_id,
        projection_id=item.projection_id,
    ) for item in batch.items.order_by("ordinal"))


def archive_heads(*, actor, organization_id):
    require_active_membership(actor=actor, organization_id=organization_id)
    return ArchiveHead.objects.filter(organization_id=organization_id).select_related(
        "encounter", "projection"
    ).order_by("encounter_id")


def archive_projection_detail(*, actor, organization_id, projection_id):
    require_active_membership(actor=actor, organization_id=organization_id)
    try:
        return ArchiveProjection.objects.select_related(
            "encounter", "predecessor", "work__scheduled_authorization",
        ).prefetch_related(
            "attempts__outcome", "readback_observations",
        ).get(organization_id=organization_id, id=projection_id)
    except (ArchiveProjection.DoesNotExist, ValueError) as exc:
        raise CommandError("archive_projection_not_found") from exc


def archive_batch_detail(*, actor, organization_id, batch_id):
    require_active_membership(actor=actor, organization_id=organization_id)
    try:
        return ArchiveBatch.objects.prefetch_related(
            "items__projection", "items__work", "items__authorization",
        ).get(organization_id=organization_id, id=batch_id)
    except (ArchiveBatch.DoesNotExist, ValueError) as exc:
        raise CommandError("archive_batch_not_found") from exc
