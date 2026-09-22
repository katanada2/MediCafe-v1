import uuid

from django.conf import settings
from django.db import models

from medicafe_v1.access.models import Organization
from medicafe_v1.records.models import Encounter, Patient, Service, ServiceRevision


class TenantModel(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(Organization, on_delete=models.PROTECT)

    class Meta:
        abstract = True


class SyntheticPolicySelection(TenantModel):
    version = models.CharField(max_length=40)
    activation_generation = models.PositiveIntegerField()
    selected_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    selected_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["organization"], name="claims_policy_org_uniq"),
            models.UniqueConstraint(fields=["organization", "id"], name="claims_policy_org_id_uniq"),
            models.CheckConstraint(
                condition=models.Q(activation_generation__gte=1), name="claims_policy_generation_positive_ck"
            ),
        ]


class Claim(TenantModel):
    encounter = models.ForeignKey(Encounter, on_delete=models.PROTECT, related_name="claims")
    patient = models.ForeignKey(Patient, on_delete=models.PROTECT)
    current_revision = models.ForeignKey(
        "ClaimRevision", null=True, blank=True, on_delete=models.PROTECT,
        related_name="current_for_claims",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["organization", "encounter"], name="claims_case_org_encounter_uniq"),
            models.UniqueConstraint(fields=["organization", "id"], name="claims_case_org_id_uniq"),
            models.UniqueConstraint(
                fields=["organization", "encounter", "patient", "id"],
                name="claims_case_org_enc_patient_id_uniq",
            ),
        ]


class ClaimRevision(TenantModel):
    claim = models.ForeignKey(Claim, on_delete=models.PROTECT, related_name="revisions")
    encounter = models.ForeignKey(Encounter, on_delete=models.PROTECT)
    patient = models.ForeignKey(Patient, on_delete=models.PROTECT)
    revision_number = models.PositiveIntegerField()
    predecessor = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.PROTECT, related_name="successors"
    )
    prepared_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    prepared_at = models.DateTimeField(auto_now_add=True)
    reason = models.CharField(max_length=500)
    policy_version = models.CharField(max_length=40)
    policy_generation = models.PositiveIntegerField()
    route_id = models.CharField(max_length=80)
    route_version = models.CharField(max_length=20)
    envelope_format_version = models.CharField(max_length=20)
    envelope_bytes = models.BinaryField()
    envelope_digest = models.CharField(max_length=64)
    total_amount = models.DecimalField(max_digits=10, decimal_places=2)
    currency = models.CharField(max_length=3)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["organization", "id"], name="claims_rev_org_id_uniq"),
            models.UniqueConstraint(
                fields=["organization", "claim", "id"], name="claims_rev_org_claim_id_uniq"
            ),
            models.UniqueConstraint(
                fields=["claim", "revision_number"], name="claims_rev_claim_number_uniq"
            ),
            models.UniqueConstraint(
                fields=["predecessor"], condition=models.Q(predecessor__isnull=False),
                name="claims_rev_predecessor_uniq",
            ),
            models.CheckConstraint(
                condition=models.Q(revision_number__gte=1), name="claims_rev_number_positive_ck"
            ),
            models.CheckConstraint(
                condition=models.Q(policy_generation__gte=1), name="claims_rev_policy_generation_positive_ck"
            ),
            models.CheckConstraint(
                condition=models.Q(total_amount__gte=0), name="claims_rev_total_nonnegative_ck"
            ),
        ]


class ClaimLine(TenantModel):
    claim_revision = models.ForeignKey(ClaimRevision, on_delete=models.PROTECT, related_name="lines")
    claim = models.ForeignKey(Claim, on_delete=models.PROTECT)
    service = models.ForeignKey(Service, on_delete=models.PROTECT)
    service_revision = models.ForeignKey(ServiceRevision, on_delete=models.PROTECT)
    encounter = models.ForeignKey(Encounter, on_delete=models.PROTECT)
    patient = models.ForeignKey(Patient, on_delete=models.PROTECT)
    ordinal = models.PositiveSmallIntegerField()
    code = models.CharField(max_length=20)
    units = models.PositiveSmallIntegerField()
    unit_amount = models.DecimalField(max_digits=6, decimal_places=2)
    line_amount = models.DecimalField(max_digits=8, decimal_places=2)
    currency = models.CharField(max_length=3)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["organization", "id"], name="claims_line_org_id_uniq"),
            models.UniqueConstraint(
                fields=["claim_revision", "ordinal"], name="claims_line_revision_ordinal_uniq"
            ),
            models.UniqueConstraint(
                fields=["claim_revision", "service"], name="claims_line_revision_service_uniq"
            ),
            models.CheckConstraint(
                condition=models.Q(ordinal__gte=1) & models.Q(ordinal__lte=100),
                name="claims_line_ordinal_range_ck",
            ),
            models.CheckConstraint(
                condition=models.Q(line_amount__gte=0), name="claims_line_amount_nonnegative_ck"
            ),
        ]


class ClaimApproval(TenantModel):
    claim_revision = models.ForeignKey(ClaimRevision, on_delete=models.PROTECT, related_name="approvals")
    envelope_digest = models.CharField(max_length=64)
    approved_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    approved_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["claim_revision"], name="claims_approval_revision_uniq"),
            models.UniqueConstraint(fields=["organization", "id"], name="claims_approval_org_id_uniq"),
        ]


class ClaimsCommandReceipt(TenantModel):
    request_uuid = models.UUIDField()
    command_kind = models.CharField(max_length=40)
    target_key = models.CharField(max_length=200)
    expected_predecessor_id = models.UUIDField(null=True, blank=True)
    intent_digest = models.CharField(max_length=64)
    result_claim = models.ForeignKey(Claim, null=True, blank=True, on_delete=models.PROTECT)
    result_revision = models.ForeignKey(ClaimRevision, null=True, blank=True, on_delete=models.PROTECT)
    result_approval = models.ForeignKey(ClaimApproval, null=True, blank=True, on_delete=models.PROTECT)
    result_policy_version = models.CharField(max_length=40, blank=True)
    result_policy_generation = models.PositiveIntegerField(null=True, blank=True)
    accepted_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "request_uuid"], name="claims_receipt_org_request_uniq"
            ),
            models.UniqueConstraint(fields=["organization", "id"], name="claims_receipt_org_id_uniq"),
        ]
