from dataclasses import dataclass

from django.db.models import Exists, OuterRef

from medicafe_v1.access.services import require_active_membership
from medicafe_v1.records.models import IdentityDecision

from .models import Delivery, Observation


@dataclass(frozen=True)
class VerifiedDeliveryBytes:
    organization_id: object
    delivery_id: object
    artifact_id: object
    source_namespace: str
    source_key: str
    media_type: str
    content: bytes
    sha256: str
    byte_length: int


def verified_delivery_bytes(*, actor, organization_id, delivery_id, artifact_store=None):
    """Return exact retained bytes through the sources-owned verification seam."""
    require_active_membership(actor=actor, organization_id=organization_id)
    try:
        delivery = Delivery.objects.select_related("artifact").get(
            organization_id=organization_id, id=delivery_id
        )
    except (Delivery.DoesNotExist, ValueError) as exc:
        from .domain import CommandError

        raise CommandError("delivery_not_found") from exc
    from .artifacts import LocalArtifactStore

    content = (artifact_store or LocalArtifactStore()).read_verified(delivery.artifact)
    return VerifiedDeliveryBytes(
        delivery.organization_id, delivery.id, delivery.artifact_id,
        delivery.source_namespace, delivery.source_key, delivery.artifact.media_type,
        bytes(content), delivery.artifact.sha256, delivery.artifact.byte_length,
    )


def scoped_deliveries(*, actor, organization_id):
    require_active_membership(actor=actor, organization_id=organization_id)
    return Delivery.objects.filter(organization_id=organization_id).select_related("artifact").order_by("-admitted_at")


def scoped_observations(*, actor, organization_id, delivery_id=None, unresolved_only=False):
    require_active_membership(actor=actor, organization_id=organization_id)
    decisions = IdentityDecision.objects.filter(observation_id=OuterRef("pk"))
    query = Observation.objects.filter(organization_id=organization_id).annotate(resolved=Exists(decisions))
    if delivery_id:
        query = query.filter(parse_result__delivery_id=delivery_id)
    if unresolved_only:
        query = query.filter(resolved=False)
    return query.order_by("parse_result__delivery__admitted_at", "row_ordinal")
