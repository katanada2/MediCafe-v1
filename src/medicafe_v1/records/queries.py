from dataclasses import dataclass

from medicafe_v1.access.services import require_active_membership
from medicafe_v1.sources.domain import CommandError

from .models import Encounter, PatientAlias, Service, ServiceRevision


@dataclass(frozen=True)
class ServiceDependency:
    service_id: object
    revision_id: object
    encounter_id: object
    patient_id: object
    code: str
    units: int
    unit_amount: object
    currency: str
    current_revision_id: object
    current_disposition: str


def exact_alias_suggestion(*, actor, organization_id, namespace, value):
    require_active_membership(actor=actor, organization_id=organization_id)
    return PatientAlias.objects.select_related("patient").filter(
        organization_id=organization_id, namespace=namespace, value=value
    ).first()


def locked_encounter(*, actor, organization_id, encounter_id):
    require_active_membership(actor=actor, organization_id=organization_id)
    try:
        return Encounter.objects.select_for_update(of=("self",)).select_related("patient").get(
            organization_id=organization_id, id=encounter_id
        )
    except Encounter.DoesNotExist as exc:
        raise CommandError("encounter_not_found") from exc


def current_services_for_encounter(*, actor, organization_id, encounter_id, for_update=False):
    require_active_membership(actor=actor, organization_id=organization_id)
    query = Service.objects.filter(
        organization_id=organization_id, encounter_id=encounter_id
    ).select_related(
        "current_revision", "identity_decision", "patient", "encounter"
    ).order_by("created_at", "id")
    if for_update:
        query = query.select_for_update(of=("self",))
    return query


def service_detail(*, actor, organization_id, service_id):
    require_active_membership(actor=actor, organization_id=organization_id)
    try:
        return Service.objects.select_related(
            "current_revision", "identity_decision", "patient", "encounter"
        ).prefetch_related("revisions").get(organization_id=organization_id, id=service_id)
    except Service.DoesNotExist as exc:
        raise CommandError("service_not_found") from exc


def exact_current_service_selection(*, actor, organization_id, encounter_id,
                                    revision_ids, for_update=False):
    """Return records-owned current services in the caller's exact submitted order."""
    require_active_membership(actor=actor, organization_id=organization_id)
    query = Service.objects.filter(
        organization_id=organization_id, encounter_id=encounter_id,
        current_revision_id__in=revision_ids,
    ).select_related("current_revision", "patient", "encounter")
    if for_update:
        query = query.select_for_update(of=("self",))
    by_revision = {str(item.current_revision_id): item for item in query}
    try:
        return [by_revision[str(revision_id)] for revision_id in revision_ids]
    except KeyError as exc:
        raise CommandError("selected_service_not_current") from exc


def service_dependencies(*, actor, organization_id, encounter_id, selections):
    """Resolve exact immutable revisions and current heads without leaking records rules."""
    require_active_membership(actor=actor, organization_id=organization_id)
    service_ids = [service_id for service_id, _ in selections]
    revision_ids = [revision_id for _, revision_id in selections]
    services = Service.objects.filter(
        organization_id=organization_id, encounter_id=encounter_id, id__in=service_ids,
    ).select_related("current_revision")
    revisions = ServiceRevision.objects.filter(
        organization_id=organization_id, encounter_id=encounter_id,
        service_id__in=service_ids, id__in=revision_ids,
    )
    service_by_id = {str(item.id): item for item in services}
    revision_by_pair = {(str(item.service_id), str(item.id)): item for item in revisions}
    dependencies = []
    for service_id, revision_id in selections:
        service = service_by_id.get(str(service_id))
        revision = revision_by_pair.get((str(service_id), str(revision_id)))
        if not service or not revision:
            raise CommandError("selected_service_reference_invalid")
        dependencies.append(ServiceDependency(
            service.id, revision.id, service.encounter_id, service.patient_id,
            revision.code, revision.units, revision.unit_amount, revision.currency,
            service.current_revision_id, service.current_revision.disposition,
        ))
    return dependencies
