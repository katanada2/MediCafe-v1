import uuid

from django.conf import settings
from django.db import models

from medicafe_v1.access.models import Organization
from medicafe_v1.sources.models import Observation


class TenantModel(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(Organization, on_delete=models.PROTECT)

    class Meta:
        abstract = True


class Patient(TenantModel):
    display_name = models.CharField(max_length=200)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["organization", "id"], name="records_patient_org_id_uniq")]


class PatientAlias(TenantModel):
    patient = models.ForeignKey(Patient, on_delete=models.PROTECT, related_name="aliases")
    namespace = models.CharField(max_length=100)
    value = models.CharField(max_length=200)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["organization", "namespace", "value"], name="records_alias_org_ns_value_uniq"),
            models.UniqueConstraint(fields=["organization", "id"], name="records_alias_org_id_uniq"),
        ]


class Encounter(TenantModel):
    patient = models.ForeignKey(Patient, on_delete=models.PROTECT, related_name="encounters")
    service_date = models.DateField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["organization", "id"], name="records_encounter_org_id_uniq"),
            models.UniqueConstraint(fields=["organization", "patient", "id"], name="records_encounter_org_patient_id_uniq"),
        ]


class IdentityDecision(TenantModel):
    observation = models.ForeignKey(Observation, on_delete=models.PROTECT, related_name="identity_decisions")
    patient = models.ForeignKey(Patient, on_delete=models.PROTECT)
    encounter = models.ForeignKey(Encounter, on_delete=models.PROTECT)
    decided_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    decided_at = models.DateTimeField(auto_now_add=True)
    reason = models.CharField(max_length=500)
    request_uuid = models.UUIDField(default=uuid.uuid4)
    input_digest = models.CharField(max_length=64)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["organization", "request_uuid"], name="records_decision_org_request_uniq"),
            models.UniqueConstraint(fields=["observation"], name="records_decision_observation_uniq"),
            models.UniqueConstraint(fields=["organization", "id"], name="records_decision_org_id_uniq"),
        ]

