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
    accepted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, on_delete=models.PROTECT,
        related_name="claims_command_receipts",
    )
    result_delivery_intent = models.ForeignKey(
        "DeliveryIntent", null=True, blank=True, on_delete=models.PROTECT,
        related_name="command_receipts",
    )
    result_delivery_work = models.ForeignKey(
        "DeliveryWork", null=True, blank=True, on_delete=models.PROTECT,
        related_name="command_receipts",
    )
    result_attempt = models.ForeignKey(
        "DeliveryAttempt", null=True, blank=True, on_delete=models.PROTECT,
        related_name="command_receipts",
    )
    result_code = models.CharField(max_length=80, blank=True)
    accepted_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "request_uuid"], name="claims_receipt_org_request_uniq"
            ),
            models.UniqueConstraint(fields=["organization", "id"], name="claims_receipt_org_id_uniq"),
        ]


class DeliveryIntent(TenantModel):
    claim = models.ForeignKey(Claim, on_delete=models.PROTECT, related_name="delivery_intents")
    claim_revision = models.ForeignKey(
        ClaimRevision, on_delete=models.PROTECT, related_name="delivery_intents"
    )
    claim_approval = models.ForeignKey(
        ClaimApproval, on_delete=models.PROTECT, related_name="delivery_intents"
    )
    envelope_digest = models.CharField(max_length=64)
    byte_length = models.PositiveIntegerField()
    format_version = models.CharField(max_length=20)
    route_id = models.CharField(max_length=80)
    receiver_version = models.CharField(max_length=20)
    delivery_key = models.UUIDField()
    initial_authorization_receipt = models.ForeignKey(
        ClaimsCommandReceipt, on_delete=models.PROTECT, related_name="initial_delivery_intents"
    )
    authorized_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="authorized_delivery_intents"
    )
    authorized_at = models.DateTimeField()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "claim_revision"], name="claims_intent_org_revision_uniq"
            ),
            models.UniqueConstraint(
                fields=["organization", "id"], name="claims_intent_org_id_uniq"
            ),
            models.UniqueConstraint(
                fields=["organization", "claim", "id"], name="claims_intent_org_claim_id_uniq"
            ),
            models.UniqueConstraint(
                fields=["organization", "delivery_key"], name="claims_intent_org_key_uniq"
            ),
        ]


class ClaimDeliveryControl(TenantModel):
    claim = models.OneToOneField(Claim, on_delete=models.PROTECT, related_name="delivery_control")
    current_intent = models.ForeignKey(
        DeliveryIntent, on_delete=models.PROTECT, related_name="current_for_controls"
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "claim"], name="claims_delivery_control_org_claim_uniq"
            ),
            models.UniqueConstraint(
                fields=["organization", "id"], name="claims_delivery_control_org_id_uniq"
            ),
        ]


class DeliveryWork(TenantModel):
    STATE_PENDING = "pending"
    STATE_LEASED = "leased"
    STATE_BLOCKED = "blocked"
    STATE_FINISHED = "finished"
    STATES = (
        (STATE_PENDING, "Pending"),
        (STATE_LEASED, "Leased"),
        (STATE_BLOCKED, "Blocked"),
        (STATE_FINISHED, "Finished"),
    )

    intent = models.OneToOneField(DeliveryIntent, on_delete=models.PROTECT, related_name="work")
    scheduled_authorization_receipt = models.ForeignKey(
        ClaimsCommandReceipt, on_delete=models.PROTECT, related_name="scheduled_delivery_work"
    )
    state = models.CharField(max_length=20, choices=STATES, default=STATE_PENDING)
    due_at = models.DateTimeField()
    lease_owner = models.CharField(max_length=120, blank=True)
    lease_expires_at = models.DateTimeField(null=True, blank=True)
    fencing_generation = models.PositiveIntegerField(default=0)
    safe_preflight_failures = models.PositiveSmallIntegerField(default=0)
    blocking_reason = models.CharField(max_length=100, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "intent"], name="claims_work_org_intent_uniq"
            ),
            models.UniqueConstraint(
                fields=["organization", "id"], name="claims_work_org_id_uniq"
            ),
        ]


class DeliveryAttempt(TenantModel):
    intent = models.ForeignKey(DeliveryIntent, on_delete=models.PROTECT, related_name="attempts")
    ordinal = models.PositiveIntegerField()
    authorization_receipt = models.ForeignKey(
        ClaimsCommandReceipt, on_delete=models.PROTECT, related_name="authorized_delivery_attempts"
    )
    effective_authorizer = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="delivery_attempts"
    )
    work = models.ForeignKey(DeliveryWork, on_delete=models.PROTECT, related_name="attempts")
    lease_owner = models.CharField(max_length=120)
    fencing_generation = models.PositiveIntegerField()
    payload_digest = models.CharField(max_length=64)
    byte_length = models.PositiveIntegerField()
    route_id = models.CharField(max_length=80)
    receiver_version = models.CharField(max_length=20)
    started_at = models.DateTimeField()
    possible_dispatch = models.BooleanField(default=False)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["intent", "ordinal"], name="claims_attempt_intent_ordinal_uniq"
            ),
            models.UniqueConstraint(
                fields=["organization", "id"], name="claims_attempt_org_id_uniq"
            ),
            models.UniqueConstraint(
                fields=["work", "fencing_generation"],
                condition=models.Q(possible_dispatch=True),
                name="claims_attempt_work_fence_dispatch_uniq",
            ),
        ]


class ReceiverObservation(TenantModel):
    ORIGIN_DISPATCH = "dispatch_readback"
    ORIGIN_RECONCILIATION = "reconciliation_readback"
    STATE_ACCEPTED = "accepted"
    STATE_REJECTED = "rejected"
    STATE_CONFLICT = "conflict"

    intent = models.ForeignKey(DeliveryIntent, on_delete=models.PROTECT, related_name="observations")
    claim_revision = models.ForeignKey(ClaimRevision, on_delete=models.PROTECT)
    origin = models.CharField(max_length=40)
    receiver_id = models.CharField(max_length=80)
    receiver_version = models.CharField(max_length=20)
    lookup_key = models.UUIDField()
    receipt_id = models.CharField(max_length=100)
    reported_attempt_id = models.UUIDField(null=True, blank=True)
    envelope_digest = models.CharField(max_length=64)
    byte_length = models.PositiveIntegerField()
    received_bytes = models.BinaryField(null=True, blank=True)
    observed_state = models.CharField(max_length=20)
    no_acceptance_guaranteed = models.BooleanField(default=False)
    binding_valid = models.BooleanField(default=False)
    conflict_reason = models.CharField(max_length=100, blank=True)
    evidence_fingerprint = models.CharField(max_length=64, null=True)
    reported_organization_id = models.UUIDField(null=True)
    reported_intent_id = models.UUIDField(null=True)
    reported_claim_revision_id = models.UUIDField(null=True)
    reported_delivery_key = models.UUIDField(null=True)
    reported_receiver_id = models.CharField(max_length=80, null=True)
    reported_receiver_version = models.CharField(max_length=20, null=True)
    reported_envelope_digest = models.CharField(max_length=64, null=True)
    reported_byte_length = models.PositiveIntegerField(null=True)
    observed_at = models.DateTimeField()
    recorded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "id"], name="claims_observation_org_id_uniq"
            ),
        ]


class AttemptOutcome(TenantModel):
    PRE_DISPATCH_FAILED = "pre_dispatch_failed"
    RECEIVER_ACCEPTED = "receiver_accepted"
    RECEIVER_REJECTED = "receiver_rejected"
    UNKNOWN = "unknown"
    KINDS = (
        (PRE_DISPATCH_FAILED, "Pre-dispatch failed"),
        (RECEIVER_ACCEPTED, "Receiver accepted"),
        (RECEIVER_REJECTED, "Receiver rejected"),
        (UNKNOWN, "Unknown"),
    )

    attempt = models.OneToOneField(DeliveryAttempt, on_delete=models.PROTECT, related_name="outcome")
    kind = models.CharField(max_length=30, choices=KINDS)
    reason = models.CharField(max_length=100)
    ended_at = models.DateTimeField()
    receiver_observation = models.ForeignKey(
        ReceiverObservation, null=True, blank=True, on_delete=models.PROTECT,
        related_name="attempt_outcomes",
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "id"], name="claims_outcome_org_id_uniq"
            ),
        ]
