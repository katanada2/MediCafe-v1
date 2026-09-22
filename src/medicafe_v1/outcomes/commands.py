from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass
from decimal import Decimal

from django.db import transaction
from django.db.models import Q, Sum
from django.utils import timezone

from medicafe_v1.access.services import require_active_membership
from medicafe_v1.claims.models import ClaimLine
from medicafe_v1.claims.queries import historical_delivery_attribution
from medicafe_v1.sources.domain import CommandError
from medicafe_v1.sources.models import Delivery
from medicafe_v1.sources.queries import verified_delivery_bytes

from .models import (
    AcceptedEvent, AcceptedEventEvidence, ChargeBasis, FinancialAccount,
    InboundAttempt, InboundCandidate, InboundCandidateLine, InboundConflict,
    OutcomesCommandReceipt, PostingBatch, PostingEntry,
)
from .parsers import INTERPRETER_VERSION, SENDER_RECEIVERS, parse_inbound


@dataclass(frozen=True)
class OutcomeCommandResult:
    reason_code: str
    candidate_id: object | None = None
    event_id: object | None = None
    batch_id: object | None = None
    attempt_id: object | None = None
    current_blockers: tuple[str, ...] = ()


def _digest(value):
    return hashlib.sha256(json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
    ).encode("utf-8")).hexdigest()


def _candidate_conflicts(candidate):
    return InboundConflict.objects.filter(
        Q(existing_candidate=candidate) | Q(conflicting_candidate=candidate)
    ).exists()


def _record_candidate_conflicts(candidate):
    identity = InboundCandidate.objects.filter(
        organization_id=candidate.organization_id,
        sender_id=candidate.sender_id,
        kind=candidate.kind,
        event_id=candidate.event_id,
    ).exclude(id=candidate.id).order_by("interpreted_at", "id")
    for existing in identity:
        if existing.semantic_digest != candidate.semantic_digest:
            InboundConflict.objects.get_or_create(
                organization_id=candidate.organization_id,
                existing_candidate=existing,
                conflicting_candidate=candidate,
                reason_code="conflicting_identity_or_content",
            )
    if candidate.kind == InboundCandidate.KIND_LIFECYCLE:
        occupied = InboundCandidate.objects.filter(
            organization_id=candidate.organization_id,
            sender_id=candidate.sender_id,
            kind=candidate.kind,
            intent_id=candidate.intent_id,
            lifecycle_sequence=candidate.lifecycle_sequence,
        ).exclude(id=candidate.id).order_by("interpreted_at", "id")
        for existing in occupied:
            if (
                existing.event_id != candidate.event_id
                or existing.semantic_digest != candidate.semantic_digest
            ):
                InboundConflict.objects.get_or_create(
                    organization_id=candidate.organization_id,
                    existing_candidate=existing,
                    conflicting_candidate=candidate,
                    reason_code="conflicting_identity_or_content",
                )


def interpret_inbound(
        *, actor, organization_id, delivery_id,
        interpreter_version=INTERPRETER_VERSION, artifact_store=None):
    require_active_membership(actor=actor, organization_id=organization_id)
    existing = InboundCandidate.objects.filter(
        organization_id=organization_id, delivery_id=delivery_id,
        interpreter_version=interpreter_version,
    ).first()
    if existing:
        return OutcomeCommandResult("interpretation_replayed", candidate_id=existing.id)
    started_at = timezone.now()
    try:
        verified = verified_delivery_bytes(
            actor=actor, organization_id=organization_id, delivery_id=delivery_id,
            artifact_store=artifact_store,
        )
        parsed = parse_inbound(
            verified.content, source_namespace=verified.source_namespace,
            media_type=verified.media_type,
        )
        failure = None
    except CommandError as exc:
        verified = None
        parsed = None
        failure = exc

    candidate = None
    with transaction.atomic():
        require_active_membership(
            actor=actor, organization_id=organization_id, for_update=True
        )
        try:
            delivery = Delivery.objects.select_for_update(of=("self",)).get(
                organization_id=organization_id, id=delivery_id
            )
        except (Delivery.DoesNotExist, ValueError) as exc:
            raise CommandError("delivery_not_found") from exc
        existing = InboundCandidate.objects.filter(
            organization_id=organization_id, delivery=delivery,
            interpreter_version=interpreter_version,
        ).first()
        if failure:
            attempt = InboundAttempt.objects.create(
                organization_id=organization_id, delivery=delivery,
                interpreter_version=interpreter_version, started_at=started_at,
                ended_at=timezone.now(), succeeded=False,
                reason_code=failure.reason_code,
            )
        else:
            if existing:
                candidate = existing
            else:
                candidate = InboundCandidate.objects.create(
                    organization_id=organization_id, delivery=delivery,
                    interpreter_version=interpreter_version,
                    schema_version=parsed.schema_version, kind=parsed.kind,
                    sender_id=parsed.sender_id, event_id=parsed.event_id,
                    delivery_key=parsed.delivery_key, intent_id=parsed.intent_id,
                    claim_revision_id=parsed.claim_revision_id,
                    receiver_receipt_id=parsed.receiver_receipt_id,
                    currency=parsed.currency,
                    lifecycle_sequence=parsed.lifecycle_sequence,
                    predecessor_event_id=parsed.predecessor_event_id,
                    lifecycle_status=parsed.lifecycle_status,
                    normalized_content=parsed.normalized_content,
                    semantic_bytes=parsed.semantic_bytes,
                    semantic_digest=parsed.semantic_digest,
                )
                InboundCandidateLine.objects.bulk_create([
                    InboundCandidateLine(
                        organization_id=organization_id, candidate=candidate,
                        line_ordinal=line.line_ordinal, paid_amount=line.paid_amount,
                        contractual_adjustment=line.contractual_adjustment,
                    )
                    for line in parsed.lines
                ])
                _record_candidate_conflicts(candidate)
            attempt = InboundAttempt.objects.create(
                organization_id=organization_id, delivery=delivery,
                interpreter_version=interpreter_version, started_at=started_at,
                ended_at=timezone.now(), succeeded=True,
                reason_code="interpretation_succeeded",
            )
    if failure:
        raise failure
    return OutcomeCommandResult(
        "interpretation_succeeded", candidate_id=candidate.id, attempt_id=attempt.id
    )


def _candidate(actor, organization_id, candidate_id, expected_kind):
    require_active_membership(actor=actor, organization_id=organization_id)
    filters = {"organization_id": organization_id, "id": candidate_id}
    if expected_kind is not None:
        filters["kind"] = expected_kind
    try:
        return InboundCandidate.objects.select_related("delivery__artifact").prefetch_related(
            "lines"
        ).get(**filters)
    except (InboundCandidate.DoesNotExist, ValueError) as exc:
        raise CommandError("unmatched_target") from exc


def _verify_candidate_bytes(*, actor, candidate, artifact_store=None):
    try:
        verified = verified_delivery_bytes(
            actor=actor, organization_id=candidate.organization_id,
            delivery_id=candidate.delivery_id, artifact_store=artifact_store,
        )
    except CommandError as exc:
        if exc.reason_code == "artifact_unavailable":
            raise
        raise CommandError("artifact_unavailable") from exc
    try:
        parsed = parse_inbound(
            verified.content, source_namespace=verified.source_namespace,
            media_type=verified.media_type,
        )
    except CommandError as exc:
        raise CommandError("artifact_unavailable") from exc
    if (
        parsed.semantic_digest != candidate.semantic_digest
        or parsed.semantic_bytes != bytes(candidate.semantic_bytes)
    ):
        raise CommandError("conflicting_identity_or_content")


def _command_intent(candidate, command_kind):
    value = {
        "organization_id": str(candidate.organization_id),
        "command_kind": command_kind,
        "candidate_id": str(candidate.id),
        "intent_id": str(candidate.intent_id),
        "semantic_digest": candidate.semantic_digest,
    }
    return _digest(value)


def _accepted_receipt(*, candidate, request_id, command_kind, intent_digest):
    try:
        request_uuid = uuid.UUID(str(request_id))
    except (ValueError, AttributeError) as exc:
        raise CommandError("request_id_invalid") from exc
    receipt = OutcomesCommandReceipt.objects.filter(
        organization_id=candidate.organization_id, request_uuid=request_uuid
    ).select_related("result_event", "result_batch").first()
    if receipt and (
        receipt.command_kind != command_kind
        or receipt.target_candidate_id != candidate.id
        or receipt.target_intent_id != candidate.intent_id
        or receipt.intent_digest != intent_digest
    ):
        raise CommandError("request_reused_with_different_intent")
    return request_uuid, receipt


def _historical_attribution(*, actor, candidate, for_acceptance):
    receiver_id, receiver_version = SENDER_RECEIVERS[candidate.sender_id]
    ordinals = tuple(candidate.lines.values_list("line_ordinal", flat=True))
    return historical_delivery_attribution(
        actor=actor, organization_id=candidate.organization_id,
        intent_id=candidate.intent_id, delivery_key=candidate.delivery_key,
        claim_revision_id=candidate.claim_revision_id,
        expected_receiver_id=receiver_id,
        expected_receiver_version=receiver_version,
        receiver_receipt_id=candidate.receiver_receipt_id,
        line_ordinals=ordinals, for_acceptance=for_acceptance,
    )


def _ensure_no_candidate_conflict(candidate):
    if _candidate_conflicts(candidate):
        raise CommandError("conflicting_identity_or_content")
    changed_identity = InboundCandidate.objects.filter(
        organization_id=candidate.organization_id, sender_id=candidate.sender_id,
        kind=candidate.kind, event_id=candidate.event_id,
    ).exclude(semantic_digest=candidate.semantic_digest).exists()
    if changed_identity:
        raise CommandError("conflicting_identity_or_content")


def _existing_event(candidate):
    event = AcceptedEvent.objects.select_for_update().filter(
        organization_id=candidate.organization_id, sender_id=candidate.sender_id,
        kind=candidate.kind, event_id=candidate.event_id,
    ).first()
    if event and event.semantic_digest != candidate.semantic_digest:
        raise CommandError("conflicting_identity_or_content")
    return event


def _link_evidence(event, candidate):
    link, _created = AcceptedEventEvidence.objects.get_or_create(
        organization_id=candidate.organization_id, candidate=candidate,
        defaults={"event": event},
    )
    if link.event_id != event.id:
        raise CommandError("conflicting_identity_or_content")


def _create_event(*, actor, candidate, attribution):
    return AcceptedEvent.objects.create(
        organization_id=candidate.organization_id, primary_candidate=candidate,
        kind=candidate.kind, sender_id=candidate.sender_id,
        event_id=candidate.event_id, semantic_digest=candidate.semantic_digest,
        intent_id=attribution.intent_id,
        claim_revision_id=attribution.claim_revision_id,
        receiver_observation_id=attribution.receiver_observation_id,
        receiver_evidence_fingerprint=attribution.evidence_fingerprint,
        receiver_receipt_id=attribution.receiver_receipt_id,
        lifecycle_sequence=candidate.lifecycle_sequence,
        predecessor_event_id=candidate.predecessor_event_id,
        lifecycle_status=candidate.lifecycle_status,
        accepted_by=actor,
    )


def accept_lifecycle(
        *, actor, organization_id, request_id, candidate_id, artifact_store=None):
    candidate = _candidate(
        actor, organization_id, candidate_id, InboundCandidate.KIND_LIFECYCLE
    )
    intent_digest = _command_intent(candidate, "accept_lifecycle")
    request_uuid, receipt = _accepted_receipt(
        candidate=candidate, request_id=request_id,
        command_kind="accept_lifecycle", intent_digest=intent_digest,
    )
    if receipt:
        return OutcomeCommandResult(
            "lifecycle_acceptance_replayed", candidate.id, receipt.result_event_id
        )
    with transaction.atomic():
        require_active_membership(
            actor=actor, organization_id=organization_id, for_update=True
        )
        request_uuid, receipt = _accepted_receipt(
            candidate=candidate, request_id=request_uuid,
            command_kind="accept_lifecycle", intent_digest=intent_digest,
        )
        if receipt:
            return OutcomeCommandResult(
                "lifecycle_acceptance_replayed", candidate.id, receipt.result_event_id
            )
        _verify_candidate_bytes(actor=actor, candidate=candidate, artifact_store=artifact_store)
        attribution = _historical_attribution(
            actor=actor, candidate=candidate, for_acceptance=True
        )
        _ensure_no_candidate_conflict(candidate)
        event = _existing_event(candidate)
        if event is None:
            sequence = candidate.lifecycle_sequence
            if sequence == 1:
                if candidate.predecessor_event_id is not None:
                    raise CommandError("pending_sequence_gap")
            else:
                predecessor = AcceptedEvent.objects.select_for_update().filter(
                    organization_id=organization_id, sender_id=candidate.sender_id,
                    kind=InboundCandidate.KIND_LIFECYCLE,
                    intent_id=attribution.intent_id,
                    lifecycle_sequence=sequence - 1,
                    event_id=candidate.predecessor_event_id,
                ).first()
                if predecessor is None:
                    raise CommandError("pending_sequence_gap")
            occupied = AcceptedEvent.objects.select_for_update().filter(
                organization_id=organization_id, sender_id=candidate.sender_id,
                kind=InboundCandidate.KIND_LIFECYCLE,
                intent_id=attribution.intent_id,
                lifecycle_sequence=sequence,
            ).first()
            if occupied is not None:
                raise CommandError("conflicting_identity_or_content")
            event = _create_event(actor=actor, candidate=candidate, attribution=attribution)
        _link_evidence(event, candidate)
        OutcomesCommandReceipt.objects.create(
            organization_id=organization_id, request_uuid=request_uuid,
            command_kind="accept_lifecycle", target_candidate=candidate,
            target_intent_id=candidate.intent_id, intent_digest=intent_digest,
            accepted_by=actor, result_event=event,
        )
    return OutcomeCommandResult("lifecycle_accepted", candidate.id, event.id)


def post_remittance(
        *, actor, organization_id, request_id, candidate_id, artifact_store=None):
    candidate = _candidate(
        actor, organization_id, candidate_id, InboundCandidate.KIND_REMITTANCE
    )
    intent_digest = _command_intent(candidate, "post_remittance")
    request_uuid, receipt = _accepted_receipt(
        candidate=candidate, request_id=request_id,
        command_kind="post_remittance", intent_digest=intent_digest,
    )
    if receipt:
        return OutcomeCommandResult(
            "remittance_post_replayed", candidate.id,
            receipt.result_event_id, receipt.result_batch_id,
        )
    with transaction.atomic():
        require_active_membership(
            actor=actor, organization_id=organization_id, for_update=True
        )
        request_uuid, receipt = _accepted_receipt(
            candidate=candidate, request_id=request_uuid,
            command_kind="post_remittance", intent_digest=intent_digest,
        )
        if receipt:
            return OutcomeCommandResult(
                "remittance_post_replayed", candidate.id,
                receipt.result_event_id, receipt.result_batch_id,
            )
        _verify_candidate_bytes(actor=actor, candidate=candidate, artifact_store=artifact_store)
        attribution = _historical_attribution(
            actor=actor, candidate=candidate, for_acceptance=True
        )
        _ensure_no_candidate_conflict(candidate)
        event = _existing_event(candidate)
        if event is not None:
            try:
                batch = event.posting_batch
            except PostingBatch.DoesNotExist as exc:
                raise CommandError("conflicting_identity_or_content") from exc
            _link_evidence(event, candidate)
        else:
            event = _create_event(actor=actor, candidate=candidate, attribution=attribution)
            try:
                account = FinancialAccount.objects.select_for_update().get(
                    organization_id=organization_id,
                    claim_revision_id=attribution.claim_revision_id,
                )
                if (
                    account.currency != attribution.currency
                    or account.original_charge != attribution.original_charge
                ):
                    raise CommandError("conflicting_identity_or_content")
            except FinancialAccount.DoesNotExist:
                account = FinancialAccount.objects.create(
                    organization_id=organization_id,
                    claim_revision_id=attribution.claim_revision_id,
                    currency=attribution.currency,
                    original_charge=attribution.original_charge,
                )
            lines = {line.line_ordinal: line for line in candidate.lines.all()}
            attribution_lines = {line.ordinal: line for line in attribution.lines}
            bases = {}
            for ordinal, attributed in attribution_lines.items():
                claim_line = ClaimLine.objects.get(
                    organization_id=organization_id, id=attributed.claim_line_id,
                    claim_revision_id=attribution.claim_revision_id,
                )
                basis, _ = ChargeBasis.objects.get_or_create(
                    organization_id=organization_id, claim_line=claim_line,
                    defaults={
                        "account": account, "line_ordinal": ordinal,
                        "original_charge": attributed.original_charge,
                        "currency": attribution.currency,
                    },
                )
                if (
                    basis.account_id != account.id
                    or basis.line_ordinal != ordinal
                    or basis.original_charge != attributed.original_charge
                    or basis.currency != attribution.currency
                ):
                    raise CommandError("conflicting_identity_or_content")
                prior = PostingEntry.objects.filter(
                    organization_id=organization_id, charge_basis=basis,
                ).aggregate(total=Sum("amount"))["total"] or Decimal("0.00")
                proposed = lines[ordinal].paid_amount + lines[ordinal].contractual_adjustment
                if prior + proposed > basis.original_charge:
                    raise CommandError("overallocated_line")
                bases[ordinal] = basis
            batch = PostingBatch.objects.create(
                organization_id=organization_id, event=event, account=account
            )
            entries = []
            for ordinal, line in lines.items():
                if line.paid_amount:
                    entries.append(PostingEntry(
                        organization_id=organization_id, batch=batch, event=event,
                        account=account, charge_basis=bases[ordinal],
                        claim_line_id=bases[ordinal].claim_line_id,
                        kind=PostingEntry.KIND_PAYMENT, amount=line.paid_amount,
                        currency=attribution.currency,
                    ))
                if line.contractual_adjustment:
                    entries.append(PostingEntry(
                        organization_id=organization_id, batch=batch, event=event,
                        account=account, charge_basis=bases[ordinal],
                        claim_line_id=bases[ordinal].claim_line_id,
                        kind=PostingEntry.KIND_ADJUSTMENT,
                        amount=line.contractual_adjustment,
                        currency=attribution.currency,
                    ))
            PostingEntry.objects.bulk_create(entries)
            _link_evidence(event, candidate)
        OutcomesCommandReceipt.objects.create(
            organization_id=organization_id, request_uuid=request_uuid,
            command_kind="post_remittance", target_candidate=candidate,
            target_intent_id=candidate.intent_id, intent_digest=intent_digest,
            accepted_by=actor, result_event=event, result_batch=batch,
        )
    return OutcomeCommandResult("remittance_posted", candidate.id, event.id, batch.id)


def reevaluate_candidate(*, actor, organization_id, candidate_id, artifact_store=None):
    candidate = _candidate(actor, organization_id, candidate_id, expected_kind=None)
    blockers = []
    try:
        _verify_candidate_bytes(actor=actor, candidate=candidate, artifact_store=artifact_store)
    except CommandError as exc:
        blockers.append(exc.reason_code)
    if _candidate_conflicts(candidate):
        blockers.append("conflicting_identity_or_content")
    if not blockers:
        try:
            _historical_attribution(actor=actor, candidate=candidate, for_acceptance=False)
        except CommandError as exc:
            blockers.append(exc.reason_code)
    if not blockers and not AcceptedEventEvidence.objects.filter(
        organization_id=organization_id, candidate=candidate
    ).exists():
        blockers.append("unaccepted")
    return OutcomeCommandResult(
        "candidate_reevaluated", candidate_id=candidate.id,
        current_blockers=tuple(dict.fromkeys(blockers)),
    )
