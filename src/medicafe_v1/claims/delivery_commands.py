"""Claims-owned F3 delivery authorization and reconciliation commands."""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass

from django.db import IntegrityError, transaction
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from medicafe_v1.access.services import require_active_membership
from medicafe_v1.records.queries import locked_encounter
from medicafe_v1.sources.domain import CommandError

from .delivery_adapter import FrozenDelivery, LoopbackReceiverAdapter, RECEIVER_ID
from .models import (
    AttemptOutcome,
    Claim,
    ClaimApproval,
    ClaimDeliveryControl,
    ClaimRevision,
    ClaimsCommandReceipt,
    DeliveryAttempt,
    DeliveryIntent,
    DeliveryWork,
    ReceiverObservation,
    SyntheticPolicySelection,
)
from .queries import claim_actionability, delivery_effect_state


@dataclass(frozen=True)
class DeliveryCommandResult:
    reason_code: str
    intent_id: object
    work_id: object
    attempt_id: object | None = None
    replayed: bool = False
    historical_status: str | None = None
    current_status: str | None = None
    current_blockers: tuple[str, ...] = ()


def _uuid(value, reason):
    try:
        return uuid.UUID(str(value))
    except (ValueError, TypeError, AttributeError) as exc:
        raise CommandError(reason) from exc


def _digest(value):
    normalized = (value or "").strip().lower()
    if len(normalized) != 64 or any(char not in "0123456789abcdef" for char in normalized):
        raise CommandError("claim_envelope_digest_invalid")
    return normalized


def _intent_hash(payload):
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _receipt_replay(*, organization_id, request_id, digest, command_kind):
    receipt = ClaimsCommandReceipt.objects.filter(
        organization_id=organization_id, request_uuid=request_id
    ).first()
    if not receipt:
        return None
    if receipt.intent_digest != digest or receipt.command_kind != command_kind:
        raise CommandError("request_input_conflict")
    return receipt


def _result_from_receipt(receipt, *, replayed, actor):
    intent = receipt.result_delivery_intent
    actionability = claim_actionability(
        actor=actor, organization_id=receipt.organization_id,
        claim_revision_id=intent.claim_revision_id,
    )
    return DeliveryCommandResult(
        receipt.result_code,
        intent.id,
        receipt.result_delivery_work_id,
        receipt.result_attempt_id,
        replayed,
        receipt.result_code,
        delivery_effect_state(intent),
        actionability.blockers,
    )


def _slot_releasable(intent):
    if intent.observations.filter(
        observed_state__in=(ReceiverObservation.STATE_ACCEPTED, ReceiverObservation.STATE_CONFLICT)
    ).exists():
        return False
    possible = list(intent.attempts.filter(possible_dispatch=True))
    if not possible:
        return ClaimsCommandReceipt.objects.filter(
            command_kind="cancel_before_dispatch", result_delivery_intent=intent,
            result_code__in=("delivery_cancelled", "delivery_already_cancelled"),
        ).exists()
    rejected_attempts = set(intent.observations.filter(
        observed_state=ReceiverObservation.STATE_REJECTED,
        binding_valid=True,
        no_acceptance_guaranteed=True,
    ).values_list("reported_attempt_id", flat=True))
    return all(attempt.id in rejected_attempts for attempt in possible)


def _lock_delivery_aggregate(*, actor, organization_id, intent):
    locked_encounter(
        actor=actor, organization_id=organization_id,
        encounter_id=intent.claim_revision.encounter_id,
    )
    SyntheticPolicySelection.objects.select_for_update().get(organization_id=organization_id)
    claim = Claim.objects.select_for_update().get(organization_id=organization_id, id=intent.claim_id)
    control = ClaimDeliveryControl.objects.select_for_update().get(
        organization_id=organization_id, claim=claim
    )
    locked_intent = DeliveryIntent.objects.select_for_update().get(
        organization_id=organization_id, id=intent.id
    )
    work = DeliveryWork.objects.select_for_update().get(
        organization_id=organization_id, intent=locked_intent
    )
    return claim, control, locked_intent, work


def request_delivery(*, actor, organization_id, request_id, claim_revision_id,
                     expected_envelope_digest):
    require_active_membership(actor=actor, organization_id=organization_id)
    request_uuid = _uuid(request_id, "request_uuid_invalid")
    revision_id = _uuid(claim_revision_id, "claim_revision_id_invalid")
    envelope_digest = _digest(expected_envelope_digest)
    payload = {
        "organization": str(_uuid(organization_id, "organization_invalid")),
        "command_kind": "request_delivery",
        "claim_revision_id": str(revision_id),
        "expected_envelope_digest": envelope_digest,
    }
    digest = _intent_hash(payload)
    replay = _receipt_replay(
        organization_id=organization_id, request_id=request_uuid, digest=digest,
        command_kind="request_delivery",
    )
    if replay:
        return _result_from_receipt(replay, replayed=True, actor=actor)
    try:
        scoped = ClaimRevision.objects.select_related("claim").get(
            organization_id=organization_id, id=revision_id
        )
    except ClaimRevision.DoesNotExist as exc:
        raise CommandError("claim_revision_not_found") from exc
    with transaction.atomic():
        locked_encounter(
            actor=actor, organization_id=organization_id, encounter_id=scoped.encounter_id
        )
        SyntheticPolicySelection.objects.select_for_update().get(organization_id=organization_id)
        claim = Claim.objects.select_for_update().get(
            organization_id=organization_id, id=scoped.claim_id
        )
        control = ClaimDeliveryControl.objects.select_for_update().filter(
            organization_id=organization_id, claim=claim
        ).first()
        replay = _receipt_replay(
            organization_id=organization_id, request_id=request_uuid, digest=digest,
            command_kind="request_delivery",
        )
        if replay:
            return _result_from_receipt(replay, replayed=True, actor=actor)
        if scoped.envelope_digest != envelope_digest:
            raise CommandError("claim_envelope_digest_conflict")
        existing = DeliveryIntent.objects.filter(
            organization_id=organization_id, claim_revision=scoped
        ).select_related("work", "claim_approval").first()
        if existing:
            if (
                existing.claim_id != claim.id
                or existing.envelope_digest != envelope_digest
                or existing.claim_approval.claim_revision_id != scoped.id
            ):
                raise CommandError("claim_envelope_digest_conflict")
            receipt = ClaimsCommandReceipt.objects.create(
                organization_id=organization_id, request_uuid=request_uuid,
                command_kind="request_delivery", target_key=str(revision_id),
                intent_digest=digest, result_claim=claim, result_revision=scoped,
                result_approval=existing.claim_approval, result_delivery_intent=existing,
                result_delivery_work=existing.work, result_code="delivery_coalesced",
                accepted_by=actor,
            )
            return _result_from_receipt(receipt, replayed=False, actor=actor)
        envelope = bytes(scoped.envelope_bytes)
        if hashlib.sha256(envelope).hexdigest() != envelope_digest:
            raise CommandError("envelope_unavailable")
        approval = ClaimApproval.objects.get(
            organization_id=organization_id, claim_revision=scoped,
            envelope_digest=envelope_digest,
        )
        actionability = claim_actionability(
            actor=actor, organization_id=organization_id, claim_revision_id=scoped.id
        )
        if actionability.blockers:
            raise CommandError(actionability.primary_reason)
        if control and not _slot_releasable(control.current_intent):
            prior = delivery_effect_state(control.current_intent)
            raise CommandError(
                "prior_delivery_accepted" if prior == "receiver_accepted"
                else "prior_delivery_unresolved"
            )
        intent_id = uuid.uuid4()
        work_id = uuid.uuid4()
        receipt_id = uuid.uuid4()
        receipt = ClaimsCommandReceipt.objects.create(
            id=receipt_id, organization_id=organization_id, request_uuid=request_uuid,
            command_kind="request_delivery", target_key=str(revision_id),
            intent_digest=digest, result_claim=claim, result_revision=scoped,
            result_approval=approval, result_delivery_intent_id=intent_id,
            result_delivery_work_id=work_id, result_code="delivery_requested",
            accepted_by=actor,
        )
        intent = DeliveryIntent.objects.create(
            id=intent_id, organization_id=organization_id, claim=claim,
            claim_revision=scoped, claim_approval=approval,
            envelope_digest=envelope_digest, byte_length=len(envelope),
            format_version=scoped.envelope_format_version, route_id=scoped.route_id,
            receiver_version=scoped.route_version, delivery_key=intent_id,
            initial_authorization_receipt=receipt, authorized_by=actor,
            authorized_at=receipt.accepted_at,
        )
        work = DeliveryWork.objects.create(
            id=work_id, organization_id=organization_id, intent=intent,
            scheduled_authorization_receipt=receipt, due_at=timezone.now(),
        )
        if control:
            ClaimDeliveryControl.objects.filter(pk=control.pk).update(current_intent=intent)
        else:
            ClaimDeliveryControl.objects.create(
                organization_id=organization_id, claim=claim, current_intent=intent
            )
    return DeliveryCommandResult(
        "delivery_requested", intent.id, work.id, current_status="pending"
    )


def cancel_before_dispatch(*, actor, organization_id, request_id, intent_id):
    require_active_membership(actor=actor, organization_id=organization_id)
    request_uuid = _uuid(request_id, "request_uuid_invalid")
    target_id = _uuid(intent_id, "delivery_intent_id_invalid")
    digest = _intent_hash({
        "organization": str(_uuid(organization_id, "organization_invalid")),
        "command_kind": "cancel_before_dispatch", "intent_id": str(target_id),
    })
    replay = _receipt_replay(
        organization_id=organization_id, request_id=request_uuid, digest=digest,
        command_kind="cancel_before_dispatch",
    )
    if replay:
        return _result_from_receipt(replay, replayed=True, actor=actor)
    try:
        scoped = DeliveryIntent.objects.select_related("claim_revision").get(
            organization_id=organization_id, id=target_id
        )
    except DeliveryIntent.DoesNotExist as exc:
        raise CommandError("delivery_intent_not_found") from exc
    with transaction.atomic():
        _, control, intent, work = _lock_delivery_aggregate(
            actor=actor, organization_id=organization_id, intent=scoped
        )
        replay = _receipt_replay(
            organization_id=organization_id, request_id=request_uuid, digest=digest,
            command_kind="cancel_before_dispatch",
        )
        if replay:
            return _result_from_receipt(replay, replayed=True, actor=actor)
        if control.current_intent_id != intent.id:
            raise CommandError("delivery_intent_not_current")
        if intent.attempts.filter(possible_dispatch=True).exists():
            raise CommandError("cancellation_lost_dispatch_race")
        prior_cancel = ClaimsCommandReceipt.objects.filter(
            command_kind="cancel_before_dispatch", result_delivery_intent=intent
        ).exists()
        result_code = "delivery_already_cancelled" if prior_cancel else "delivery_cancelled"
        DeliveryWork.objects.filter(pk=work.pk).update(
            state=DeliveryWork.STATE_FINISHED, blocking_reason="cancelled_before_dispatch",
            lease_owner="", lease_expires_at=None,
        )
        receipt = ClaimsCommandReceipt.objects.create(
            organization_id=organization_id, request_uuid=request_uuid,
            command_kind="cancel_before_dispatch", target_key=str(intent.id),
            intent_digest=digest, result_delivery_intent=intent,
            result_delivery_work=work, result_code=result_code, accepted_by=actor,
        )
    return _result_from_receipt(receipt, replayed=False, actor=actor)


def retry_idempotent_delivery(*, actor, organization_id, request_id, intent_id,
                              expected_attempt_id):
    require_active_membership(actor=actor, organization_id=organization_id)
    request_uuid = _uuid(request_id, "request_uuid_invalid")
    target_id = _uuid(intent_id, "delivery_intent_id_invalid")
    attempt_id = _uuid(expected_attempt_id, "delivery_attempt_id_invalid")
    digest = _intent_hash({
        "organization": str(_uuid(organization_id, "organization_invalid")),
        "command_kind": "retry_idempotent_delivery", "intent_id": str(target_id),
        "expected_attempt_id": str(attempt_id),
    })
    replay = _receipt_replay(
        organization_id=organization_id, request_id=request_uuid, digest=digest,
        command_kind="retry_idempotent_delivery",
    )
    if replay:
        return _result_from_receipt(replay, replayed=True, actor=actor)
    try:
        scoped = DeliveryIntent.objects.select_related("claim_revision").get(
            organization_id=organization_id, id=target_id
        )
    except DeliveryIntent.DoesNotExist as exc:
        raise CommandError("delivery_intent_not_found") from exc
    if scoped.receiver_version != "v1":
        raise CommandError("receiver_retry_not_idempotent")
    with transaction.atomic():
        _, control, intent, work = _lock_delivery_aggregate(
            actor=actor, organization_id=organization_id, intent=scoped
        )
        replay = _receipt_replay(
            organization_id=organization_id, request_id=request_uuid, digest=digest,
            command_kind="retry_idempotent_delivery",
        )
        if replay:
            return _result_from_receipt(replay, replayed=True, actor=actor)
        if control.current_intent_id != intent.id:
            raise CommandError("delivery_intent_not_current")
        try:
            predecessor = intent.attempts.select_related("outcome").get(id=attempt_id)
        except DeliveryAttempt.DoesNotExist as exc:
            raise CommandError("delivery_attempt_not_found") from exc
        latest = intent.attempts.filter(possible_dispatch=True).order_by("-ordinal").first()
        if latest is None or latest.id != predecessor.id:
            raise CommandError("delivery_retry_attempt_stale")
        if not hasattr(predecessor, "outcome") or predecessor.outcome.kind != AttemptOutcome.UNKNOWN:
            raise CommandError("delivery_retry_not_uncertain")
        if delivery_effect_state(intent) != "uncertain":
            raise CommandError("delivery_retry_evidence_changed")
        actionability = claim_actionability(
            actor=actor, organization_id=organization_id,
            claim_revision_id=intent.claim_revision_id,
        )
        if actionability.blockers:
            raise CommandError(actionability.primary_reason)
        already_scheduled = (
            work.state in (DeliveryWork.STATE_PENDING, DeliveryWork.STATE_LEASED)
            and work.scheduled_authorization_receipt.command_kind == "retry_idempotent_delivery"
        )
        result_code = (
            "delivery_retry_already_scheduled" if already_scheduled
            else "delivery_retry_scheduled"
        )
        receipt = ClaimsCommandReceipt.objects.create(
            organization_id=organization_id, request_uuid=request_uuid,
            command_kind="retry_idempotent_delivery", target_key=str(intent.id),
            expected_predecessor_id=predecessor.id, intent_digest=digest,
            result_delivery_intent=intent, result_delivery_work=work,
            result_attempt=predecessor, result_code=result_code, accepted_by=actor,
        )
        if not already_scheduled:
            DeliveryWork.objects.filter(pk=work.pk).update(
                scheduled_authorization_receipt=receipt, state=DeliveryWork.STATE_PENDING,
                due_at=timezone.now(), lease_owner="", lease_expires_at=None,
                blocking_reason="",
            )
    return _result_from_receipt(receipt, replayed=False, actor=actor)


def _frozen(intent, attempt):
    payload = bytes(intent.claim_revision.envelope_bytes)
    return FrozenDelivery(
        organization_id=str(intent.organization_id), intent_id=str(intent.id),
        claim_revision_id=str(intent.claim_revision_id), delivery_key=str(intent.delivery_key),
        attempt_id=str(attempt.id), receiver_id=RECEIVER_ID,
        receiver_version=intent.receiver_version, envelope_digest=intent.envelope_digest,
        byte_length=intent.byte_length, payload=payload,
    )


def _record_evidence(*, intent, attempt, evidence, origin, finish_work=True):
    payload = bytes(intent.claim_revision.envelope_bytes)
    common_valid = (
        evidence.receiver_id == RECEIVER_ID
        and evidence.receiver_version == intent.receiver_version
        and evidence.organization_id == str(intent.organization_id)
        and evidence.intent_id == str(intent.id)
        and evidence.claim_revision_id == str(intent.claim_revision_id)
        and evidence.delivery_key == str(intent.delivery_key)
        and evidence.envelope_digest == intent.envelope_digest
        and evidence.byte_length == intent.byte_length
    )
    binding_valid = False
    if evidence.state == "accepted":
        binding_valid = (
            common_valid and evidence.received_bytes == payload
            and hashlib.sha256(evidence.received_bytes or b"").hexdigest() == intent.envelope_digest
            and not evidence.no_acceptance_guaranteed
        )
    elif evidence.state == "rejected":
        binding_valid = (
            common_valid and evidence.reported_attempt_id == str(attempt.id)
            and evidence.no_acceptance_guaranteed
        )
    fingerprint_payload = {
        "state": evidence.state, "receiver_id": evidence.receiver_id,
        "receiver_version": evidence.receiver_version,
        "organization_id": evidence.organization_id, "intent_id": evidence.intent_id,
        "claim_revision_id": evidence.claim_revision_id,
        "delivery_key": evidence.delivery_key, "receipt_id": evidence.receipt_id,
        "reported_attempt_id": evidence.reported_attempt_id,
        "envelope_digest": evidence.envelope_digest, "byte_length": evidence.byte_length,
        "received_digest": hashlib.sha256(evidence.received_bytes or b"").hexdigest(),
        "no_acceptance_guaranteed": evidence.no_acceptance_guaranteed,
    }
    fingerprint = _intent_hash(fingerprint_payload)
    existing = ReceiverObservation.objects.filter(
        receiver_id=RECEIVER_ID, receiver_version=intent.receiver_version,
        receipt_id=evidence.receipt_id, organization_id=intent.organization_id,
        intent=intent,
    ).order_by("recorded_at").first()
    if existing and getattr(existing, "evidence_fingerprint", None) == fingerprint:
        return existing
    conflict = existing is not None or not binding_valid
    observed_at = parse_datetime(evidence.observed_at)
    if observed_at is None:
        observed_at = timezone.now()
        conflict = True
    values = {
        "organization_id": intent.organization_id, "intent": intent,
        "claim_revision": intent.claim_revision, "origin": origin,
        "receiver_id": RECEIVER_ID, "receiver_version": intent.receiver_version,
        "lookup_key": intent.delivery_key, "receipt_id": evidence.receipt_id,
        "reported_attempt_id": evidence.reported_attempt_id,
        "envelope_digest": intent.envelope_digest, "byte_length": intent.byte_length,
        "received_bytes": evidence.received_bytes,
        "observed_state": (ReceiverObservation.STATE_CONFLICT if conflict else evidence.state),
        "no_acceptance_guaranteed": evidence.no_acceptance_guaranteed,
        "binding_valid": (binding_valid and not conflict),
        "conflict_reason": ("receipt_identity_conflict" if existing else "binding_mismatch") if conflict else "",
        "observed_at": observed_at, "evidence_fingerprint": fingerprint,
        "reported_organization_id": evidence.organization_id,
        "reported_intent_id": evidence.intent_id,
        "reported_claim_revision_id": evidence.claim_revision_id,
        "reported_delivery_key": evidence.delivery_key,
        "reported_receiver_id": evidence.receiver_id,
        "reported_receiver_version": evidence.receiver_version,
        "reported_envelope_digest": evidence.envelope_digest,
        "reported_byte_length": evidence.byte_length,
    }
    try:
        with transaction.atomic():
            observation = ReceiverObservation.objects.create(**values)
    except IntegrityError:
        observation = ReceiverObservation.objects.filter(
            organization_id=intent.organization_id, intent=intent,
            receiver_id=RECEIVER_ID, receiver_version=intent.receiver_version,
            receipt_id=evidence.receipt_id, evidence_fingerprint=fingerprint,
        ).first()
        if observation is None:
            raise
    observation.refresh_from_db()
    if observation.binding_valid and not hasattr(attempt, "outcome"):
        kind = (
            AttemptOutcome.RECEIVER_ACCEPTED
            if evidence.state == "accepted" else AttemptOutcome.RECEIVER_REJECTED
        )
        AttemptOutcome.objects.create(
            organization_id=intent.organization_id, attempt=attempt, kind=kind,
            reason=evidence.state, ended_at=timezone.now(), receiver_observation=observation,
        )
    if finish_work and observation.binding_valid and (
        observation.observed_state == ReceiverObservation.STATE_ACCEPTED
        or _slot_releasable(intent)
    ):
        DeliveryWork.objects.filter(intent=intent).update(
            state=DeliveryWork.STATE_FINISHED, lease_owner="", lease_expires_at=None,
            blocking_reason="",
        )
    return observation


def reconcile_delivery(*, actor, organization_id, intent_id, adapter=None):
    require_active_membership(actor=actor, organization_id=organization_id)
    target_id = _uuid(intent_id, "delivery_intent_id_invalid")
    try:
        intent = DeliveryIntent.objects.select_related("claim_revision").get(
            organization_id=organization_id, id=target_id
        )
    except DeliveryIntent.DoesNotExist as exc:
        raise CommandError("delivery_intent_not_found") from exc
    attempt = intent.attempts.filter(possible_dispatch=True).order_by("-ordinal").first()
    if not attempt:
        return DeliveryCommandResult(
            "delivery_not_dispatched", intent.id, intent.work.id,
            current_status=delivery_effect_state(intent),
        )
    evidence = (adapter or LoopbackReceiverAdapter()).readback(_frozen(intent, attempt))
    if evidence is None:
        return DeliveryCommandResult(
            "receiver_not_observed", intent.id, intent.work.id, attempt.id,
            current_status=delivery_effect_state(intent),
        )
    with transaction.atomic():
        locked_intent = DeliveryIntent.objects.select_for_update().select_related(
            "claim_revision"
        ).get(organization_id=organization_id, id=intent.id)
        locked_attempt = DeliveryAttempt.objects.select_for_update().get(
            organization_id=organization_id, id=attempt.id, intent=locked_intent
        )
        observation = _record_evidence(
            intent=locked_intent, attempt=locked_attempt, evidence=evidence,
            origin=ReceiverObservation.ORIGIN_RECONCILIATION,
        )
    reason = (
        "receiver_evidence_recorded" if observation.binding_valid
        else "receiver_evidence_conflict"
    )
    return DeliveryCommandResult(
        reason, intent.id, intent.work.id, attempt.id,
        current_status=delivery_effect_state(intent),
    )
