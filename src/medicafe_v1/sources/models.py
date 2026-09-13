import uuid

from django.conf import settings
from django.db import models

from medicafe_v1.access.models import Organization


class TenantModel(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(Organization, on_delete=models.PROTECT)

    class Meta:
        abstract = True


class Artifact(TenantModel):
    sha256 = models.CharField(max_length=64)
    byte_length = models.PositiveIntegerField()
    media_type = models.CharField(max_length=100)
    storage_key = models.CharField(max_length=255)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["organization", "sha256"], name="sources_artifact_org_sha_uniq"),
            models.UniqueConstraint(fields=["organization", "id"], name="sources_artifact_org_id_uniq"),
        ]


class Delivery(TenantModel):
    source_namespace = models.CharField(max_length=100)
    source_key = models.CharField(max_length=200)
    artifact = models.ForeignKey(Artifact, on_delete=models.PROTECT)
    admitted_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    admitted_at = models.DateTimeField(auto_now_add=True)
    supersedes = models.ForeignKey("self", null=True, blank=True, on_delete=models.PROTECT)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["organization", "source_namespace", "source_key"], name="sources_delivery_source_uniq"),
            models.UniqueConstraint(fields=["organization", "id"], name="sources_delivery_org_id_uniq"),
        ]


class ParseResult(TenantModel):
    delivery = models.ForeignKey(Delivery, on_delete=models.PROTECT)
    parser_version = models.CharField(max_length=50)
    completed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["delivery", "parser_version"], name="sources_result_delivery_version_uniq"),
            models.UniqueConstraint(fields=["organization", "id"], name="sources_result_org_id_uniq"),
        ]


class ParseAttempt(TenantModel):
    delivery = models.ForeignKey(Delivery, on_delete=models.PROTECT)
    parser_version = models.CharField(max_length=50)
    started_at = models.DateTimeField()
    ended_at = models.DateTimeField()
    succeeded = models.BooleanField()
    reason_code = models.CharField(max_length=80)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["organization", "id"], name="sources_attempt_org_id_uniq")]


class Observation(TenantModel):
    parse_result = models.ForeignKey(ParseResult, on_delete=models.PROTECT, related_name="observations")
    row_ordinal = models.PositiveIntegerField()
    raw_values = models.JSONField()
    normalized_values = models.JSONField()
    warnings = models.JSONField(default=list)
    source_locator = models.JSONField()

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["parse_result", "row_ordinal"], name="sources_observation_result_row_uniq"),
            models.UniqueConstraint(fields=["organization", "id"], name="sources_observation_org_id_uniq"),
        ]

