from __future__ import annotations

from dataclasses import dataclass

from medicafe_v1.access.services import require_active_membership
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
    verified = projection.readback_observations.filter(
        observed_state=ArchiveReadbackObservation.STATE_VERIFIED
    ).order_by("recorded_at", "id").first()
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
