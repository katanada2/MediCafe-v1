import uuid

from django.conf import settings
from django.db import models

from medicafe_v1.access.models import Organization
from medicafe_v1.claims.models import (
    ClaimLine, ClaimRevision, DeliveryIntent, ReceiverObservation,
)
from medicafe_v1.sources.models import Delivery


class TenantModel(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(Organization, on_delete=models.PROTECT)

    class Meta:
        abstract = True


class InboundAttempt(TenantModel):
    delivery = models.ForeignKey(Delivery, on_delete=models.PROTECT, related_name="inbound_attempts")
    interpreter_version = models.CharField(max_length=50)
    started_at = models.DateTimeField()
    ended_at = models.DateTimeField()
    succeeded = models.BooleanField()
    reason_code = models.CharField(max_length=80)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["organization", "id"], name="out_inatt_org_id_uniq"),
        ]


class InboundCandidate(TenantModel):
    KIND_LIFECYCLE = "lifecycle"
    KIND_REMITTANCE = "remittance"
    KINDS = ((KIND_LIFECYCLE, "Lifecycle"), (KIND_REMITTANCE, "Remittance"))

    delivery = models.ForeignKey(Delivery, on_delete=models.PROTECT, related_name="inbound_candidates")
    interpreter_version = models.CharField(max_length=50)
    schema_version = models.CharField(max_length=40)
    kind = models.CharField(max_length=20, choices=KINDS)
    sender_id = models.CharField(max_length=80)
    event_id = models.UUIDField()
    delivery_key = models.UUIDField()
    intent_id = models.UUIDField()
    claim_revision_id = models.UUIDField()
    receiver_receipt_id = models.CharField(max_length=100)
    currency = models.CharField(max_length=3, blank=True)
    lifecycle_sequence = models.PositiveIntegerField(null=True, blank=True)
    predecessor_event_id = models.UUIDField(null=True, blank=True)
    lifecycle_status = models.CharField(max_length=30, blank=True)
    normalized_content = models.JSONField()
    semantic_bytes = models.BinaryField()
    semantic_digest = models.CharField(max_length=64)
    interpreted_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["delivery", "interpreter_version"], name="out_candidate_delivery_ver_uniq"
            ),
            models.UniqueConstraint(fields=["organization", "id"], name="out_candidate_org_id_uniq"),
            models.CheckConstraint(
                condition=(
                    models.Q(
                        kind="lifecycle", currency="", lifecycle_sequence__isnull=False,
                        lifecycle_status__in=("ACK_ACCEPTED", "ACK_REJECTED"),
                    )
                    | models.Q(
                        kind="remittance", currency="USD", lifecycle_sequence__isnull=True,
                        predecessor_event_id__isnull=True, lifecycle_status="",
                    )
                ),
                name="out_candidate_kind_shape_ck",
            ),
        ]


class InboundCandidateLine(TenantModel):
    candidate = models.ForeignKey(
        InboundCandidate, on_delete=models.PROTECT, related_name="lines"
    )
    line_ordinal = models.PositiveSmallIntegerField()
    paid_amount = models.DecimalField(max_digits=10, decimal_places=2)
    contractual_adjustment = models.DecimalField(max_digits=10, decimal_places=2)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["candidate", "line_ordinal"], name="out_candline_candidate_ord_uniq"
            ),
            models.UniqueConstraint(fields=["organization", "id"], name="out_candline_org_id_uniq"),
            models.CheckConstraint(
                condition=models.Q(line_ordinal__gte=1) & models.Q(line_ordinal__lte=100),
                name="out_candline_ordinal_ck",
            ),
            models.CheckConstraint(
                condition=models.Q(paid_amount__gte=0) & models.Q(contractual_adjustment__gte=0),
                name="out_candline_amount_ck",
            ),
            models.CheckConstraint(
                condition=models.Q(paid_amount__gt=0) | models.Q(contractual_adjustment__gt=0),
                name="out_candline_nonzero_ck",
            ),
        ]


class InboundConflict(TenantModel):
    existing_candidate = models.ForeignKey(
        InboundCandidate, on_delete=models.PROTECT, related_name="conflicts_as_existing"
    )
    conflicting_candidate = models.ForeignKey(
        InboundCandidate, on_delete=models.PROTECT, related_name="conflicts_as_conflicting"
    )
    reason_code = models.CharField(max_length=80)
    recorded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["existing_candidate", "conflicting_candidate", "reason_code"],
                name="out_conflict_pair_reason_uniq",
            ),
            models.UniqueConstraint(fields=["organization", "id"], name="out_conflict_org_id_uniq"),
        ]


class AcceptedEvent(TenantModel):
    primary_candidate = models.ForeignKey(
        InboundCandidate, on_delete=models.PROTECT, related_name="primary_accepted_events"
    )
    kind = models.CharField(max_length=20, choices=InboundCandidate.KINDS)
    sender_id = models.CharField(max_length=80)
    event_id = models.UUIDField()
    semantic_digest = models.CharField(max_length=64)
    intent = models.ForeignKey(DeliveryIntent, on_delete=models.PROTECT)
    claim_revision = models.ForeignKey(ClaimRevision, on_delete=models.PROTECT)
    receiver_observation = models.ForeignKey(ReceiverObservation, on_delete=models.PROTECT)
    receiver_evidence_fingerprint = models.CharField(max_length=64)
    receiver_receipt_id = models.CharField(max_length=100)
    lifecycle_sequence = models.PositiveIntegerField(null=True, blank=True)
    predecessor_event_id = models.UUIDField(null=True, blank=True)
    lifecycle_status = models.CharField(max_length=30, blank=True)
    accepted_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    accepted_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "sender_id", "kind", "event_id"],
                name="out_event_semantic_identity_uniq",
            ),
            models.UniqueConstraint(
                fields=["organization", "sender_id", "intent", "lifecycle_sequence"],
                condition=models.Q(kind=InboundCandidate.KIND_LIFECYCLE),
                name="out_event_lifecycle_sequence_uniq",
            ),
            models.UniqueConstraint(fields=["organization", "id"], name="out_event_org_id_uniq"),
        ]


class AcceptedEventEvidence(TenantModel):
    event = models.ForeignKey(AcceptedEvent, on_delete=models.PROTECT, related_name="evidence_links")
    candidate = models.OneToOneField(
        InboundCandidate, on_delete=models.PROTECT, related_name="accepted_evidence"
    )
    linked_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["organization", "id"], name="out_evlink_org_id_uniq"),
        ]


class FinancialAccount(TenantModel):
    claim_revision = models.OneToOneField(
        ClaimRevision, on_delete=models.PROTECT, related_name="financial_account"
    )
    currency = models.CharField(max_length=3)
    original_charge = models.DecimalField(max_digits=10, decimal_places=2)
    posting_generation = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["organization", "id"], name="out_account_org_id_uniq"),
            models.CheckConstraint(
                condition=models.Q(original_charge__gte=0), name="out_account_charge_ck"
            ),
        ]


class ChargeBasis(TenantModel):
    account = models.ForeignKey(FinancialAccount, on_delete=models.PROTECT, related_name="charge_lines")
    claim_line = models.OneToOneField(ClaimLine, on_delete=models.PROTECT)
    line_ordinal = models.PositiveSmallIntegerField()
    original_charge = models.DecimalField(max_digits=10, decimal_places=2)
    currency = models.CharField(max_length=3)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["account", "line_ordinal"], name="out_basis_account_ord_uniq"
            ),
            models.UniqueConstraint(fields=["organization", "id"], name="out_basis_org_id_uniq"),
            models.CheckConstraint(
                condition=models.Q(original_charge__gte=0), name="out_basis_charge_ck"
            ),
        ]


class PostingBatch(TenantModel):
    event = models.OneToOneField(AcceptedEvent, on_delete=models.PROTECT, related_name="posting_batch")
    account = models.ForeignKey(FinancialAccount, on_delete=models.PROTECT, related_name="posting_batches")
    posted_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["organization", "id"], name="out_batch_org_id_uniq"),
        ]


class PostingEntry(TenantModel):
    KIND_PAYMENT = "payer_reported_payment"
    KIND_ADJUSTMENT = "contractual_adjustment"
    KINDS = ((KIND_PAYMENT, "Payer-reported payment"), (KIND_ADJUSTMENT, "Contractual adjustment"))

    batch = models.ForeignKey(PostingBatch, on_delete=models.PROTECT, related_name="entries")
    event = models.ForeignKey(AcceptedEvent, on_delete=models.PROTECT)
    account = models.ForeignKey(FinancialAccount, on_delete=models.PROTECT, related_name="entries")
    charge_basis = models.ForeignKey(ChargeBasis, on_delete=models.PROTECT, related_name="entries")
    claim_line = models.ForeignKey(ClaimLine, on_delete=models.PROTECT)
    kind = models.CharField(max_length=40, choices=KINDS)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    currency = models.CharField(max_length=3)
    posted_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["event", "claim_line", "kind"], name="out_entry_event_line_kind_uniq"
            ),
            models.UniqueConstraint(fields=["organization", "id"], name="out_entry_org_id_uniq"),
            models.CheckConstraint(condition=models.Q(amount__gt=0), name="out_entry_amount_positive_ck"),
        ]


class OutcomesCommandReceipt(TenantModel):
    request_uuid = models.UUIDField()
    command_kind = models.CharField(max_length=40)
    target_candidate = models.ForeignKey(InboundCandidate, on_delete=models.PROTECT)
    target_intent_id = models.UUIDField()
    intent_digest = models.CharField(max_length=64)
    accepted_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    result_event = models.ForeignKey(AcceptedEvent, on_delete=models.PROTECT)
    result_batch = models.ForeignKey(PostingBatch, null=True, blank=True, on_delete=models.PROTECT)
    accepted_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "request_uuid"], name="out_receipt_org_request_uniq"
            ),
            models.UniqueConstraint(fields=["organization", "id"], name="out_receipt_org_id_uniq"),
        ]
