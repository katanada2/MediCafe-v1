"""PostgreSQL-leased F3 worker with a committed effect boundary."""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass
from datetime import timedelta

from django.db import connection, transaction
from django.db.models import Q
from django.utils import timezone

from medicafe_v1.access.services import AuthorizationError, require_active_membership
from medicafe_v1.records.queries import locked_encounter
from medicafe_v1.sources.domain import CommandError

from .delivery_adapter import LoopbackReceiverAdapter, RECEIVER_ID
from .delivery_commands import (
    _frozen, _observation_valid_for_attempt, _record_evidence,
)
from .models import (
    AttemptOutcome,
    Claim,
    ClaimDeliveryControl,
    DeliveryAttempt,
    DeliveryIntent,
    DeliveryWork,
    SyntheticPolicySelection,
)
from .queries import claim_actionability, delivery_effect_state


MAX_SAFE_PREFLIGHT_ATTEMPTS = 3


@dataclass(frozen=True)
class WorkerResult:
    reason_code: str
    work_id: object | None = None
    attempt_id: object | None = None


def _database_now():
    with connection.cursor() as cursor:
        cursor.execute("SELECT statement_timestamp()")
        return cursor.fetchone()[0]


def _finish_with_token(*, work, worker_id, generation, state, reason):
    now = _database_now()
    return DeliveryWork.objects.filter(
        pk=work.pk, state=DeliveryWork.STATE_LEASED,
        lease_owner=worker_id, fencing_generation=generation,
        lease_expires_at__gt=now,
    ).update(
        state=state, blocking_reason=reason, lease_owner="", lease_expires_at=None,
    )


def _recover_expired_marked_work(*, work_id, attempt_id, generation):
    with transaction.atomic():
        marked = DeliveryAttempt.objects.select_for_update().get(
            id=attempt_id, work_id=work_id, fencing_generation=generation,
            possible_dispatch=True,
        )
        work = DeliveryWork.objects.select_for_update().get(id=work_id)
        now = _database_now()
        if (
            work.state != DeliveryWork.STATE_LEASED
            or work.fencing_generation != generation
            or work.lease_expires_at > now
        ):
            return WorkerResult("recovery_fence_changed", work.id, marked.id)
        outcome = AttemptOutcome.objects.filter(attempt=marked).first()
        if outcome is None:
            outcome = AttemptOutcome.objects.create(
                organization_id=work.organization_id, attempt=marked,
                kind=AttemptOutcome.UNKNOWN, reason="lease_expired_after_dispatch_marker",
                ended_at=now,
            )
        effect_state = delivery_effect_state(marked.intent)
        if effect_state == "receiver_conflict":
            work_state = DeliveryWork.STATE_BLOCKED
            blocking_reason = "receiver_evidence_conflict"
            result_reason = "receiver_evidence_conflict"
        elif effect_state in {"receiver_accepted", "receiver_rejected"}:
            work_state = DeliveryWork.STATE_FINISHED
            blocking_reason = ""
            result_reason = "receiver_evidence_recorded"
        else:
            work_state = DeliveryWork.STATE_FINISHED
            blocking_reason = "dispatch_outcome_unknown"
            result_reason = "dispatch_outcome_unknown"
        DeliveryWork.objects.filter(pk=work.pk).update(
            state=work_state, blocking_reason=blocking_reason,
            lease_owner="", lease_expires_at=None,
        )
    return WorkerResult(result_reason, work.id, marked.id)


def _claim_work(*, worker_id, lease_seconds):
    with transaction.atomic():
        now = _database_now()
        work = DeliveryWork.objects.select_for_update(skip_locked=True).filter(
            Q(state=DeliveryWork.STATE_PENDING, due_at__lte=now)
            | Q(state=DeliveryWork.STATE_LEASED, lease_expires_at__lte=now)
        ).order_by("due_at", "id").first()
        if not work:
            return None, None
        if work.state == DeliveryWork.STATE_LEASED:
            marked_id = DeliveryAttempt.objects.filter(
                work=work, fencing_generation=work.fencing_generation,
                possible_dispatch=True,
            ).values_list("id", flat=True).first()
            if marked_id:
                return ("recover", work.id, work.fencing_generation, marked_id), None
        work.state = DeliveryWork.STATE_LEASED
        work.lease_owner = worker_id
        work.lease_expires_at = now + timedelta(seconds=lease_seconds)
        work.fencing_generation += 1
        work.blocking_reason = ""
        work.save(update_fields=(
            "state", "lease_owner", "lease_expires_at", "fencing_generation",
            "blocking_reason", "updated_at",
        ))
        return (work.id, work.fencing_generation), None


def _append_attempt(*, work, intent, authorizer, receipt, possible_dispatch, now):
    ordinal = (
        DeliveryAttempt.objects.filter(intent=intent).order_by("-ordinal")
        .values_list("ordinal", flat=True).first() or 0
    ) + 1
    return DeliveryAttempt.objects.create(
        organization_id=intent.organization_id, intent=intent, ordinal=ordinal,
        authorization_receipt=receipt, effective_authorizer=authorizer,
        work=work, lease_owner=work.lease_owner,
        fencing_generation=work.fencing_generation,
        payload_digest=intent.envelope_digest, byte_length=intent.byte_length,
        route_id=intent.route_id, receiver_version=intent.receiver_version,
        started_at=now, possible_dispatch=possible_dispatch,
    )


def _preflight_failure(*, work_id, worker_id, generation, reason, transient=False):
    with transaction.atomic():
        work = DeliveryWork.objects.select_for_update(of=("self",)).select_related(
            "intent__claim_revision", "scheduled_authorization_receipt__accepted_by"
        ).get(pk=work_id)
        now = _database_now()
        if (
            work.state != DeliveryWork.STATE_LEASED or work.lease_owner != worker_id
            or work.fencing_generation != generation or work.lease_expires_at <= now
        ):
            return WorkerResult("worker_fence_stale", work.id)
        receipt = work.scheduled_authorization_receipt
        attempt = _append_attempt(
            work=work, intent=work.intent, authorizer=receipt.accepted_by,
            receipt=receipt, possible_dispatch=False, now=now,
        )
        AttemptOutcome.objects.create(
            organization_id=work.organization_id, attempt=attempt,
            kind=AttemptOutcome.PRE_DISPATCH_FAILED, reason=reason, ended_at=now,
        )
        failures = work.safe_preflight_failures + 1
        if transient and failures < MAX_SAFE_PREFLIGHT_ATTEMPTS:
            DeliveryWork.objects.filter(pk=work.pk).update(
                state=DeliveryWork.STATE_PENDING, due_at=now,
                safe_preflight_failures=failures, blocking_reason=reason,
                lease_owner="", lease_expires_at=None,
            )
            return WorkerResult("preflight_retry_scheduled", work.id, attempt.id)
        DeliveryWork.objects.filter(pk=work.pk).update(
            state=DeliveryWork.STATE_BLOCKED,
            safe_preflight_failures=failures,
            blocking_reason=("preflight_retry_limit" if transient else reason),
            lease_owner="", lease_expires_at=None,
        )
        return WorkerResult(
            "preflight_retry_limit" if transient else "delivery_blocked",
            work.id, attempt.id,
        )


def _admit_dispatch(*, work_id, worker_id, generation, before_membership_lock=None):
    scoped_work = DeliveryWork.objects.select_related(
        "intent__claim_revision", "scheduled_authorization_receipt__accepted_by"
    ).get(pk=work_id)
    scoped_intent = scoped_work.intent
    authorizer = scoped_work.scheduled_authorization_receipt.accepted_by
    if authorizer is None:
        return None, _preflight_failure(
            work_id=work_id, worker_id=worker_id, generation=generation,
            reason="dispatch_authorizer_missing",
        )
    try:
        with transaction.atomic():
            if before_membership_lock:
                before_membership_lock()
            require_active_membership(
                actor=authorizer, organization_id=scoped_intent.organization_id,
                for_update=True,
            )
            locked_encounter(
                actor=authorizer, organization_id=scoped_intent.organization_id,
                encounter_id=scoped_intent.claim_revision.encounter_id,
            )
            SyntheticPolicySelection.objects.select_for_update().get(
                organization_id=scoped_intent.organization_id
            )
            claim = Claim.objects.select_for_update().get(
                organization_id=scoped_intent.organization_id, id=scoped_intent.claim_id
            )
            control = ClaimDeliveryControl.objects.select_for_update().get(
                organization_id=scoped_intent.organization_id, claim=claim
            )
            intent = DeliveryIntent.objects.select_for_update().select_related(
                "claim_revision"
            ).get(organization_id=scoped_intent.organization_id, id=scoped_intent.id)
            work = DeliveryWork.objects.select_for_update(of=("self",)).select_related(
                "scheduled_authorization_receipt__accepted_by"
            ).get(pk=work_id, intent=intent)
            now = _database_now()
            if (
                work.state != DeliveryWork.STATE_LEASED or work.lease_owner != worker_id
                or work.fencing_generation != generation or work.lease_expires_at <= now
            ):
                return None, WorkerResult("worker_fence_stale", work.id)
            receipt = work.scheduled_authorization_receipt
            if (
                receipt.accepted_by_id != authorizer.id
                or receipt.result_delivery_intent_id != intent.id
                or receipt.result_delivery_work_id != work.id
                or receipt.command_kind not in ("request_delivery", "retry_idempotent_delivery")
            ):
                raise CommandError("dispatch_authorization_mismatch")
            if control.current_intent_id != intent.id:
                raise CommandError("delivery_intent_not_current")
            effect_state = delivery_effect_state(intent)
            if receipt.command_kind == "request_delivery" and effect_state not in {"leased", "pending"}:
                _finish_with_token(
                    work=work, worker_id=worker_id, generation=generation,
                    state=(DeliveryWork.STATE_BLOCKED if effect_state == "receiver_conflict"
                           else DeliveryWork.STATE_FINISHED),
                    reason="delivery_effect_state_changed",
                )
                return None, WorkerResult("delivery_effect_state_changed", work.id)
            if receipt.command_kind == "retry_idempotent_delivery" and effect_state != "uncertain":
                _finish_with_token(
                    work=work, worker_id=worker_id, generation=generation,
                    state=(DeliveryWork.STATE_BLOCKED if effect_state == "receiver_conflict"
                           else DeliveryWork.STATE_FINISHED),
                    reason="delivery_retry_evidence_changed",
                )
                return None, WorkerResult("delivery_retry_evidence_changed", work.id)
            actionability = claim_actionability(
                actor=authorizer, organization_id=intent.organization_id,
                claim_revision_id=intent.claim_revision_id,
            )
            if actionability.blockers:
                raise CommandError(actionability.primary_reason)
            payload = bytes(intent.claim_revision.envelope_bytes)
            if (
                intent.claim_revision_id != claim.current_revision_id
                or intent.envelope_digest != intent.claim_revision.envelope_digest
                or intent.byte_length != len(payload)
                or hashlib.sha256(payload).hexdigest() != intent.envelope_digest
                or intent.format_version != intent.claim_revision.envelope_format_version
                or intent.route_id != intent.claim_revision.route_id
                or intent.receiver_version != intent.claim_revision.route_version
            ):
                raise CommandError("envelope_unavailable")
            attempt = _append_attempt(
                work=work, intent=intent, authorizer=authorizer, receipt=receipt,
                possible_dispatch=True, now=now,
            )
            frozen = _frozen(intent, attempt)
        return frozen, WorkerResult("dispatch_admitted", work_id, attempt.id)
    except AuthorizationError:
        return None, _preflight_failure(
            work_id=work_id, worker_id=worker_id, generation=generation,
            reason="dispatch_authorizer_inactive",
        )
    except CommandError as exc:
        return None, _preflight_failure(
            work_id=work_id, worker_id=worker_id, generation=generation,
            reason=exc.reason_code,
        )


def _record_unknown(*, work_id, attempt_id, worker_id, generation, reason):
    with transaction.atomic():
        attempt = DeliveryAttempt.objects.select_for_update().get(pk=attempt_id)
        outcome, _ = AttemptOutcome.objects.get_or_create(
            organization_id=attempt.organization_id, attempt=attempt,
            defaults={"kind": AttemptOutcome.UNKNOWN, "reason": reason, "ended_at": timezone.now()},
        )
        _finish_with_token(
            work=attempt.work, worker_id=worker_id, generation=generation,
            state=DeliveryWork.STATE_FINISHED, reason="dispatch_outcome_unknown",
        )
    return WorkerResult("dispatch_outcome_unknown", work_id, outcome.attempt_id)


def run_delivery_worker_once(*, worker_id=None, lease_seconds=10, adapter=None,
                             test_mode=None, after_marker=None, after_transport=None,
                             before_membership_lock=None):
    worker_id = worker_id or f"worker-{uuid.uuid4()}"
    adapter = adapter or LoopbackReceiverAdapter()
    adapter_timeout = float(getattr(adapter, "timeout", 0))
    if lease_seconds <= adapter_timeout:
        return WorkerResult("lease_not_longer_than_adapter_timeout")
    claim, recovered = _claim_work(worker_id=worker_id, lease_seconds=lease_seconds)
    if recovered:
        return recovered
    if not claim:
        return WorkerResult("no_delivery_work")
    if claim[0] == "recover":
        _, recovery_work_id, recovery_generation, recovery_attempt_id = claim
        return _recover_expired_marked_work(
            work_id=recovery_work_id, attempt_id=recovery_attempt_id,
            generation=recovery_generation,
        )
    work_id, generation = claim
    work = DeliveryWork.objects.select_related("intent").get(pk=work_id)
    try:
        adapter.validate_configuration(RECEIVER_ID, work.intent.receiver_version)
    except CommandError as exc:
        return _preflight_failure(
            work_id=work_id, worker_id=worker_id, generation=generation,
            reason=exc.reason_code,
            transient=exc.reason_code == "receiver_preflight_transient",
        )
    frozen, admitted = _admit_dispatch(
        work_id=work_id, worker_id=worker_id, generation=generation,
        before_membership_lock=before_membership_lock,
    )
    if frozen is None:
        return admitted
    if after_marker:
        after_marker(frozen)
    transport = adapter.send(frozen, test_mode=test_mode)
    if after_transport:
        after_transport(frozen, transport)
    if transport.status not in {"accepted", "rejected"}:
        return _record_unknown(
            work_id=work_id, attempt_id=admitted.attempt_id,
            worker_id=worker_id, generation=generation, reason=transport.reason,
        )
    try:
        evidence = adapter.readback(frozen)
    except CommandError as exc:
        return _record_unknown(
            work_id=work_id, attempt_id=admitted.attempt_id,
            worker_id=worker_id, generation=generation, reason=exc.reason_code,
        )
    if evidence is None:
        return _record_unknown(
            work_id=work_id, attempt_id=admitted.attempt_id,
            worker_id=worker_id, generation=generation, reason="receiver_not_observed",
        )
    with transaction.atomic():
        intent = DeliveryIntent.objects.select_for_update().select_related(
            "claim_revision"
        ).get(id=frozen.intent_id)
        attempt = DeliveryAttempt.objects.select_for_update().get(id=frozen.attempt_id)
        observation = _record_evidence(
            intent=intent, attempt=attempt, evidence=evidence,
            origin="dispatch_readback", finish_work=False,
        )
        if _observation_valid_for_attempt(observation=observation, attempt=attempt):
            _finish_with_token(
                work=attempt.work, worker_id=worker_id, generation=generation,
                state=DeliveryWork.STATE_FINISHED, reason="",
            )
            return WorkerResult("receiver_evidence_recorded", work_id, attempt.id)
    return _record_unknown(
        work_id=work_id, attempt_id=admitted.attempt_id,
        worker_id=worker_id, generation=generation, reason="receiver_evidence_conflict",
    )
