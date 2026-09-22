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


class Service(TenantModel):
    encounter = models.ForeignKey(Encounter, on_delete=models.PROTECT, related_name="services")
    patient = models.ForeignKey(Patient, on_delete=models.PROTECT)
    identity_decision = models.ForeignKey(IdentityDecision, on_delete=models.PROTECT)
    current_revision = models.ForeignKey(
        "ServiceRevision", null=True, blank=True, on_delete=models.PROTECT,
        related_name="current_for_services",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["organization", "id"], name="records_service_org_id_uniq"),
            models.UniqueConstraint(
                fields=["organization", "encounter", "patient", "id"],
                name="records_service_org_enc_patient_id_uniq",
            ),
        ]


class ServiceRevision(TenantModel):
    service = models.ForeignKey(Service, on_delete=models.PROTECT, related_name="revisions")
    encounter = models.ForeignKey(Encounter, on_delete=models.PROTECT)
    patient = models.ForeignKey(Patient, on_delete=models.PROTECT)
    revision_number = models.PositiveIntegerField()
    predecessor = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.PROTECT, related_name="successors"
    )
    decided_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    decided_at = models.DateTimeField(auto_now_add=True)
    reason = models.CharField(max_length=500)
    evidence_observation = models.ForeignKey(Observation, on_delete=models.PROTECT)
    identity_decision = models.ForeignKey(IdentityDecision, on_delete=models.PROTECT)
    disposition = models.CharField(
        max_length=20, choices=[("accepted", "Accepted"), ("excluded", "Excluded")]
    )
    code = models.CharField(max_length=20)
    units = models.PositiveSmallIntegerField()
    unit_amount = models.DecimalField(max_digits=6, decimal_places=2)
    currency = models.CharField(max_length=3)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["organization", "id"], name="records_srev_org_id_uniq"),
            models.UniqueConstraint(
                fields=["organization", "service", "id"], name="records_srev_org_service_id_uniq"
            ),
            models.UniqueConstraint(
                fields=["service", "revision_number"], name="records_srev_service_number_uniq"
            ),
            models.UniqueConstraint(
                fields=["predecessor"], condition=models.Q(predecessor__isnull=False),
                name="records_srev_predecessor_uniq",
            ),
            models.CheckConstraint(
                condition=models.Q(revision_number__gte=1), name="records_srev_number_positive_ck"
            ),
            models.CheckConstraint(
                condition=models.Q(units__gte=1) & models.Q(units__lte=100),
                name="records_srev_units_range_ck",
            ),
            models.CheckConstraint(
                condition=models.Q(unit_amount__gte=0), name="records_srev_amount_nonnegative_ck"
            ),
        ]


class RecordsCommandReceipt(TenantModel):
    request_uuid = models.UUIDField()
    command_kind = models.CharField(max_length=40)
    target_key = models.CharField(max_length=200)
    expected_predecessor_id = models.UUIDField(null=True, blank=True)
    intent_digest = models.CharField(max_length=64)
    result_service = models.ForeignKey(Service, on_delete=models.PROTECT)
    result_revision = models.ForeignKey(ServiceRevision, on_delete=models.PROTECT)
    accepted_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "request_uuid"], name="records_receipt_org_request_uniq"
            ),
            models.UniqueConstraint(fields=["organization", "id"], name="records_receipt_org_id_uniq"),
        ]
