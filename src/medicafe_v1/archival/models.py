import uuid

from django.conf import settings
from django.db import models

from medicafe_v1.access.models import Organization
from medicafe_v1.records.models import Encounter


class TenantModel(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(Organization, on_delete=models.PROTECT)

    class Meta:
        abstract = True


class ArchiveProjection(TenantModel):
    encounter = models.ForeignKey(Encounter, on_delete=models.PROTECT, related_name="archive_projections")
    version = models.PositiveIntegerField()
    predecessor = models.OneToOneField(
        "self", null=True, blank=True, on_delete=models.PROTECT, related_name="successor"
    )
    source_fingerprint = models.CharField(max_length=64)
    schema_version = models.CharField(max_length=40)
    projection_bytes = models.BinaryField()
    projection_digest = models.CharField(max_length=64)
    byte_length = models.PositiveIntegerField()
    captured_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    captured_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["encounter", "version"], name="arc_projection_enc_version_uniq"
            ),
            models.UniqueConstraint(fields=["organization", "id"], name="arc_projection_org_id_uniq"),
            models.CheckConstraint(condition=models.Q(version__gte=1), name="arc_projection_version_ck"),
        ]


class ArchiveHead(TenantModel):
    encounter = models.OneToOneField(
        Encounter, on_delete=models.PROTECT, related_name="archive_head"
    )
    projection = models.OneToOneField(
        ArchiveProjection, on_delete=models.PROTECT, related_name="head_for"
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["organization", "id"], name="arc_head_org_id_uniq"),
        ]


class ArchiveBatch(TenantModel):
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["organization", "id"], name="arc_batch_org_id_uniq"),
        ]


class ArchiveCommandReceipt(TenantModel):
    request_uuid = models.UUIDField()
    command_kind = models.CharField(max_length=40)
    target_key = models.CharField(max_length=200)
    intent_digest = models.CharField(max_length=64)
    accepted_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    result_projection = models.ForeignKey(
        ArchiveProjection, null=True, blank=True, on_delete=models.PROTECT
    )
    result_batch = models.ForeignKey(
        ArchiveBatch, null=True, blank=True, on_delete=models.PROTECT
    )
    result_authorization = models.ForeignKey(
        "ArchiveAuthorization", null=True, blank=True, on_delete=models.PROTECT
    )
    result_code = models.CharField(max_length=80)
    accepted_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "request_uuid"], name="arc_receipt_org_request_uniq"
            ),
            models.UniqueConstraint(fields=["organization", "id"], name="arc_receipt_org_id_uniq"),
        ]


class ArchiveAuthorization(TenantModel):
    KIND_INITIAL = "initial_queue"
    KIND_MANUAL = "manual_retry"
    KINDS = ((KIND_INITIAL, "Initial queue"), (KIND_MANUAL, "Manual retry"))

    projection = models.ForeignKey(
        ArchiveProjection, on_delete=models.PROTECT, related_name="authorizations"
    )
    receiver_id = models.CharField(max_length=80)
    receiver_version = models.CharField(max_length=20)
    kind = models.CharField(max_length=20, choices=KINDS)
    command_receipt = models.ForeignKey(
        ArchiveCommandReceipt, on_delete=models.PROTECT, related_name="authorizations"
    )
    expected_predecessor_attempt = models.ForeignKey(
        "ArchiveAttempt", null=True, blank=True, on_delete=models.PROTECT,
        related_name="retry_authorizations",
    )
    allowed_attempts = models.PositiveSmallIntegerField()
    authorized_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    authorized_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["organization", "id"], name="arc_auth_org_id_uniq"),
            models.CheckConstraint(
                condition=(
                    models.Q(kind="initial_queue", allowed_attempts=3, expected_predecessor_attempt__isnull=True)
                    | models.Q(kind="manual_retry", allowed_attempts=1, expected_predecessor_attempt__isnull=False)
                ),
                name="arc_auth_kind_budget_ck",
            ),
        ]


class ArchiveWork(TenantModel):
    STATE_PENDING = "pending"
    STATE_LEASED = "leased"
    STATE_FINISHED = "finished"
    STATE_BLOCKED = "blocked"
    STATES = tuple((value, value.title()) for value in (
        STATE_PENDING, STATE_LEASED, STATE_FINISHED, STATE_BLOCKED,
    ))

    projection = models.OneToOneField(
        ArchiveProjection, on_delete=models.PROTECT, related_name="work"
    )
    scheduled_authorization = models.ForeignKey(
        ArchiveAuthorization, on_delete=models.PROTECT, related_name="scheduled_work"
    )
    state = models.CharField(max_length=20, choices=STATES, default=STATE_PENDING)
    due_at = models.DateTimeField()
    lease_owner = models.CharField(max_length=120, blank=True)
    lease_expires_at = models.DateTimeField(null=True, blank=True)
    fencing_generation = models.PositiveIntegerField(default=0)
    blocking_reason = models.CharField(max_length=100, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["organization", "id"], name="arc_work_org_id_uniq"),
        ]


class ArchiveBatchItem(TenantModel):
    batch = models.ForeignKey(ArchiveBatch, on_delete=models.PROTECT, related_name="items")
    ordinal = models.PositiveSmallIntegerField()
    projection = models.ForeignKey(ArchiveProjection, on_delete=models.PROTECT)
    work = models.ForeignKey(ArchiveWork, on_delete=models.PROTECT)
    authorization = models.ForeignKey(ArchiveAuthorization, on_delete=models.PROTECT)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["batch", "ordinal"], name="arc_item_batch_ordinal_uniq"),
            models.UniqueConstraint(fields=["batch", "projection"], name="arc_item_batch_projection_uniq"),
            models.UniqueConstraint(fields=["organization", "id"], name="arc_item_org_id_uniq"),
            models.CheckConstraint(
                condition=models.Q(ordinal__gte=1) & models.Q(ordinal__lte=100),
                name="arc_item_ordinal_ck",
            ),
        ]


class ArchiveAttempt(TenantModel):
    projection = models.ForeignKey(
        ArchiveProjection, on_delete=models.PROTECT, related_name="attempts"
    )
    authorization = models.ForeignKey(
        ArchiveAuthorization, on_delete=models.PROTECT, related_name="attempts"
    )
    work = models.ForeignKey(ArchiveWork, on_delete=models.PROTECT, related_name="attempts")
    ordinal = models.PositiveIntegerField()
    receiver_id = models.CharField(max_length=80)
    receiver_version = models.CharField(max_length=20)
    projection_digest = models.CharField(max_length=64)
    byte_length = models.PositiveIntegerField()
    lease_owner = models.CharField(max_length=120)
    fencing_generation = models.PositiveIntegerField()
    started_at = models.DateTimeField()
    possible_write = models.BooleanField(default=False)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["authorization", "ordinal"], name="arc_attempt_auth_ordinal_uniq"
            ),
            models.UniqueConstraint(
                fields=["work", "fencing_generation"],
                condition=models.Q(possible_write=True),
                name="arc_attempt_work_fence_uniq",
            ),
            models.UniqueConstraint(fields=["organization", "id"], name="arc_attempt_org_id_uniq"),
        ]


class ArchiveReadbackObservation(TenantModel):
    STATE_VERIFIED = "verified"
    STATE_CONFLICT = "conflict"
    STATES = ((STATE_VERIFIED, "Verified"), (STATE_CONFLICT, "Conflict"))

    source_attempt = models.ForeignKey(
        ArchiveAttempt, null=True, blank=True, on_delete=models.PROTECT,
        related_name="readback_observations",
    )
    lookup_projection = models.ForeignKey(
        ArchiveProjection, on_delete=models.PROTECT, related_name="readback_observations"
    )
    receiver_id = models.CharField(max_length=80)
    receiver_version = models.CharField(max_length=20)
    target_receipt_id = models.CharField(max_length=100)
    reported_organization_id = models.UUIDField()
    reported_encounter_id = models.UUIDField()
    reported_projection_id = models.UUIDField()
    reported_projection_version = models.PositiveIntegerField()
    reported_digest = models.CharField(max_length=64)
    reported_byte_length = models.PositiveIntegerField()
    received_bytes = models.BinaryField()
    evidence_fingerprint = models.CharField(max_length=64)
    observed_state = models.CharField(max_length=20, choices=STATES)
    conflict_reason = models.CharField(max_length=100, blank=True)
    observed_at = models.DateTimeField()
    recorded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["receiver_id", "receiver_version", "target_receipt_id", "evidence_fingerprint"],
                name="arc_observation_receipt_fp_uniq",
            ),
            models.UniqueConstraint(fields=["organization", "id"], name="arc_observation_org_id_uniq"),
        ]


class ArchiveAttemptOutcome(TenantModel):
    PRE_WRITE_FAILED = "pre_write_failed"
    TARGET_REJECTED = "target_rejected"
    TARGET_CONFIRMED = "target_confirmed"
    UNKNOWN = "unknown"
    KINDS = tuple((value, value.replace("_", " ").title()) for value in (
        PRE_WRITE_FAILED, TARGET_REJECTED, TARGET_CONFIRMED, UNKNOWN,
    ))

    attempt = models.OneToOneField(
        ArchiveAttempt, on_delete=models.PROTECT, related_name="outcome"
    )
    kind = models.CharField(max_length=30, choices=KINDS)
    reason = models.CharField(max_length=100)
    ended_at = models.DateTimeField()
    readback_observation = models.ForeignKey(
        ArchiveReadbackObservation, null=True, blank=True, on_delete=models.PROTECT,
        related_name="attempt_outcomes",
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["organization", "id"], name="arc_outcome_org_id_uniq"),
        ]
