import logging

from django.db import IntegrityError, transaction
from django.utils import timezone

from medicafe_v1.access.services import require_active_membership

from .artifacts import LocalArtifactStore
from .domain import CommandError, CommandResult
from .models import Artifact, Delivery, Observation, ParseAttempt, ParseResult
from .parsers import PARSER_VERSION, parse


logger = logging.getLogger(__name__)
MAX_UPLOAD_BYTES = 5 * 1024 * 1024
ALLOWED_MEDIA_TYPES = {
    "text/csv",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}


def admit_delivery(*, actor, organization_id, source_namespace, source_key, content, media_type,
                   supersedes_id=None, artifact_store=None):
    require_active_membership(actor=actor, organization_id=organization_id)
    namespace = source_namespace.strip()
    key = source_key.strip()
    if not namespace or not key:
        raise CommandError("source_identity_required")
    if not content:
        raise CommandError("upload_empty")
    if len(content) > MAX_UPLOAD_BYTES:
        raise CommandError("upload_too_large")
    if media_type not in ALLOWED_MEDIA_TYPES:
        raise CommandError("media_type_unsupported")
    store = artifact_store or LocalArtifactStore()
    digest, storage_key = store.put(organization_id, content)

    with transaction.atomic():
        require_active_membership(actor=actor, organization_id=organization_id, for_update=True)
        existing = Delivery.objects.filter(
            organization_id=organization_id, source_namespace=namespace, source_key=key
        ).select_related("artifact").first()
        if existing:
            if existing.artifact.sha256 != digest:
                raise CommandError("delivery_source_conflict")
            store.read_verified(existing.artifact)
            return CommandResult("delivery_replayed", delivery_id=existing.id)
        supersedes = None
        if supersedes_id:
            try:
                supersedes = Delivery.objects.get(organization_id=organization_id, id=supersedes_id)
            except Delivery.DoesNotExist as exc:
                raise CommandError("supersedes_not_found") from exc
        try:
            with transaction.atomic():
                artifact, created = Artifact.objects.get_or_create(
                    organization_id=organization_id,
                    sha256=digest,
                    defaults={"byte_length": len(content), "media_type": media_type, "storage_key": storage_key},
                )
        except IntegrityError:
            artifact = Artifact.objects.get(organization_id=organization_id, sha256=digest)
            created = False
        if not created:
            store.read_verified(artifact)
            if artifact.media_type != media_type:
                raise CommandError("artifact_media_type_conflict")
        try:
            with transaction.atomic():
                delivery = Delivery.objects.create(
                    organization_id=organization_id, source_namespace=namespace, source_key=key,
                    artifact=artifact, admitted_by=actor, supersedes=supersedes,
                )
        except IntegrityError as exc:
            existing = Delivery.objects.select_related("artifact").get(
                organization_id=organization_id, source_namespace=namespace, source_key=key
            )
            if existing.artifact.sha256 != digest:
                raise CommandError("delivery_source_conflict") from exc
            return CommandResult("delivery_replayed", delivery_id=existing.id)
    logger.info("delivery_admitted organization_id=%s delivery_id=%s", organization_id, delivery.id)
    return CommandResult("delivery_admitted", delivery_id=delivery.id)


def parse_delivery(*, actor, organization_id, delivery_id, parser_version=PARSER_VERSION, artifact_store=None):
    require_active_membership(actor=actor, organization_id=organization_id)
    store = artifact_store or LocalArtifactStore()
    started_at = timezone.now()
    try:
        delivery = Delivery.objects.select_related("artifact").get(
            organization_id=organization_id, id=delivery_id
        )
    except Delivery.DoesNotExist as exc:
        raise CommandError("delivery_not_found") from exc
    existing = ParseResult.objects.filter(delivery=delivery, parser_version=parser_version).first()
    if existing:
        return CommandResult("parse_replayed", delivery_id=delivery.id, parse_result_id=existing.id)
    try:
        content = store.read_verified(delivery.artifact)
        parsed_rows = parse(content, delivery.artifact.media_type)
        failure = None
    except CommandError as exc:
        parsed_rows = None
        failure = exc

    with transaction.atomic():
        require_active_membership(actor=actor, organization_id=organization_id, for_update=True)
        delivery = Delivery.objects.select_for_update().get(organization_id=organization_id, id=delivery_id)
        existing = ParseResult.objects.filter(delivery=delivery, parser_version=parser_version).first()
        if failure:
            ParseAttempt.objects.create(
                organization_id=organization_id, delivery=delivery, parser_version=parser_version,
                started_at=started_at, ended_at=timezone.now(), succeeded=False, reason_code=failure.reason_code,
            )
            logger.warning("parse_failed organization_id=%s delivery_id=%s reason_code=%s",
                           organization_id, delivery.id, failure.reason_code)
        else:
            if existing:
                result = existing
            else:
                result = ParseResult.objects.create(
                    organization_id=organization_id, delivery=delivery, parser_version=parser_version
                )
                Observation.objects.bulk_create([Observation(
                    organization_id=organization_id, parse_result=result, row_ordinal=row.row_ordinal,
                    raw_values=row.raw_values, normalized_values=row.normalized_values,
                    warnings=row.warnings, source_locator=row.source_locator,
                ) for row in parsed_rows])
            ParseAttempt.objects.create(
                organization_id=organization_id, delivery=delivery, parser_version=parser_version,
                started_at=started_at, ended_at=timezone.now(), succeeded=True, reason_code="parse_succeeded",
            )
    if failure:
        raise failure
    logger.info("parse_succeeded organization_id=%s delivery_id=%s parse_result_id=%s",
                organization_id, delivery.id, result.id)
    return CommandResult("parse_succeeded", delivery_id=delivery.id, parse_result_id=result.id)
