from medicafe_v1.access.services import require_active_membership

from .models import PatientAlias


def exact_alias_suggestion(*, actor, organization_id, namespace, value):
    require_active_membership(actor=actor, organization_id=organization_id)
    return PatientAlias.objects.select_related("patient").filter(
        organization_id=organization_id, namespace=namespace, value=value
    ).first()

