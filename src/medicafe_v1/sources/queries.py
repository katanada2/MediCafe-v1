from django.db.models import Exists, OuterRef

from medicafe_v1.access.services import require_active_membership
from medicafe_v1.records.models import IdentityDecision

from .models import Delivery, Observation


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

