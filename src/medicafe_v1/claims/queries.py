import hashlib
import json
from dataclasses import dataclass

from medicafe_v1.access.services import require_active_membership
from medicafe_v1.records.queries import service_dependencies
from medicafe_v1.sources.domain import CommandError

from .models import (
    AttemptOutcome, Claim, ClaimApproval, ClaimDeliveryControl, ClaimRevision,
    ClaimsCommandReceipt, DeliveryIntent, DeliveryWork, ReceiverObservation,
    SyntheticPolicySelection,
)
from .policies import POLICIES


BLOCKER_ORDER = (
    "envelope_unavailable",
    "superseded_revision",
    "selected_service_changed",
    "policy_changed",
    "unapproved",
)


@dataclass(frozen=True)
class ClaimActionability:
    reason_code: str
    primary_reason: str | None
    blockers: tuple[str, ...]
    claim_id: object
    revision_id: object
    approval_id: object | None


@dataclass(frozen=True)
class DeliveryDetailView:
    intent: object
    work: object
    attempts: tuple
    observations: tuple
    current_state: str
    blocking_reasons: tuple[str, ...]
    permitted_actions: tuple[str, ...]


def delivery_effect_state(intent):
    observations = intent.observations.all()
    if observations.filter(observed_state=ReceiverObservation.STATE_CONFLICT).exists():
        return "receiver_conflict"
    if observations.filter(
        observed_state=ReceiverObservation.STATE_ACCEPTED, binding_valid=True
    ).exists():
        return "receiver_accepted"
    attempts = intent.attempts.all()
    rejected_ids = ReceiverObservation.objects.filter(
        intent=intent, observed_state=ReceiverObservation.STATE_REJECTED,
        binding_valid=True, no_acceptance_guaranteed=True,
    ).values("reported_attempt_id")
    if attempts.filter(possible_dispatch=True).exclude(id__in=rejected_ids).exists():
        return "uncertain"
    if ClaimsCommandReceipt.objects.filter(
        command_kind="cancel_before_dispatch", result_delivery_intent=intent,
        result_code__in=("delivery_cancelled", "delivery_already_cancelled"),
    ).exists():
        return "cancelled"
    if attempts.filter(possible_dispatch=True).exists():
        return "receiver_rejected"
    work = intent.work
    if work.state == DeliveryWork.STATE_BLOCKED:
        return "blocked"
    if work.state == DeliveryWork.STATE_LEASED:
        return "leased"
    if work.state == DeliveryWork.STATE_PENDING:
        return "pending"
    return "definitely_unsent"


def delivery_detail(*, actor, organization_id, intent_id):
    require_active_membership(actor=actor, organization_id=organization_id)
    try:
        intent = DeliveryIntent.objects.select_related(
            "claim", "claim_revision", "claim_approval", "authorized_by", "work"
        ).prefetch_related(
            "attempts__outcome", "attempts__effective_authorizer", "observations"
        ).get(organization_id=organization_id, id=intent_id)
    except (DeliveryIntent.DoesNotExist, ValueError) as exc:
        raise CommandError("delivery_intent_not_found") from exc
    attempts = tuple(intent.attempts.order_by("ordinal"))
    observations = tuple(intent.observations.order_by("recorded_at", "id"))
    state = delivery_effect_state(intent)
    actionability = claim_actionability(
        actor=actor, organization_id=organization_id,
        claim_revision_id=intent.claim_revision_id,
    )
    reasons = list(actionability.blockers)
    if state == "receiver_conflict":
        reasons.insert(0, "receiver_conflict")
    elif state == "uncertain":
        reasons.insert(0, "dispatch_outcome_unknown")
    elif state == "blocked" and intent.work.blocking_reason:
        reasons.insert(0, intent.work.blocking_reason)
    actions = []
    if not any(attempt.possible_dispatch for attempt in attempts) and state not in {
        "cancelled", "receiver_accepted", "receiver_conflict"
    }:
        actions.append("cancel")
    if any(attempt.possible_dispatch for attempt in attempts):
        actions.append("reconcile")
    latest = next((attempt for attempt in reversed(attempts) if attempt.possible_dispatch), None)
    if (
        latest and intent.receiver_version == "v1" and state == "uncertain"
        and hasattr(latest, "outcome") and latest.outcome.kind == AttemptOutcome.UNKNOWN
        and not actionability.blockers
    ):
        actions.append("retry")
    return DeliveryDetailView(
        intent, intent.work, attempts, observations, state,
        tuple(dict.fromkeys(reasons)), tuple(actions),
    )


def delivery_worklist(*, actor, organization_id):
    require_active_membership(actor=actor, organization_id=organization_id)
    intents = DeliveryIntent.objects.filter(organization_id=organization_id).select_related(
        "claim", "claim_revision", "work"
    ).prefetch_related("attempts", "observations").order_by("-authorized_at", "id")
    return tuple((intent, delivery_effect_state(intent)) for intent in intents)


def delivery_for_revision(*, actor, organization_id, claim_revision_id):
    require_active_membership(actor=actor, organization_id=organization_id)
    return DeliveryIntent.objects.filter(
        organization_id=organization_id, claim_revision_id=claim_revision_id
    ).first()


def delivery_for_claim(*, actor, organization_id, claim_id):
    require_active_membership(actor=actor, organization_id=organization_id)
    control = ClaimDeliveryControl.objects.select_related("current_intent").filter(
        organization_id=organization_id, claim_id=claim_id
    ).first()
    return control.current_intent if control else None


def _money(value):
    return f"{value:.2f}"


def envelope_payload(revision, lines):
    return {
        "synthetic_only": True,
        "format_version": revision.envelope_format_version,
        "organization_id": str(revision.organization_id),
        "claim_id": str(revision.claim_id),
        "revision_id": str(revision.id),
        "patient_id": str(revision.patient_id),
        "encounter_id": str(revision.encounter_id),
        "policy": {
            "version": revision.policy_version,
            "activation_generation": revision.policy_generation,
        },
        "route": {"id": revision.route_id, "version": revision.route_version},
        "currency": revision.currency,
        "total": _money(revision.total_amount),
        "lines": [{
            "ordinal": line.ordinal,
            "service_id": str(line.service_id),
            "service_revision_id": str(line.service_revision_id),
            "code": line.code,
            "units": line.units,
            "unit_amount": _money(line.unit_amount),
            "line_amount": _money(line.line_amount),
        } for line in lines],
    }


def serialize_payload(payload):
    return json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")


def _revision_envelope_valid(*, actor, revision, lines):
    stored = bytes(revision.envelope_bytes or b"")
    if not stored or hashlib.sha256(stored).hexdigest() != revision.envelope_digest:
        return False
    if stored != serialize_payload(envelope_payload(revision, lines)):
        return False
    try:
        dependencies = service_dependencies(
            actor=actor, organization_id=revision.organization_id,
            encounter_id=revision.encounter_id,
            selections=[(line.service_id, line.service_revision_id) for line in lines],
        )
    except CommandError:
        return False
    if len(dependencies) != len(lines) or not 1 <= len(lines) <= 100:
        return False
    allowed_codes = POLICIES.get(revision.policy_version)
    if allowed_codes is None:
        return False
    if [line.ordinal for line in lines] != list(range(1, len(lines) + 1)):
        return False
    total = 0
    for line, dependency in zip(lines, dependencies, strict=True):
        expected_amount = dependency.units * dependency.unit_amount
        if (
            line.encounter_id != revision.encounter_id
            or line.patient_id != revision.patient_id
            or line.code != dependency.code
            or line.units != dependency.units
            or line.unit_amount != dependency.unit_amount
            or line.currency != dependency.currency
            or line.line_amount != expected_amount
            or line.code not in allowed_codes
        ):
            return False
        total += expected_amount
    return total == revision.total_amount and revision.currency == "USD"


def claim_actionability(*, actor, organization_id, claim_revision_id):
    require_active_membership(actor=actor, organization_id=organization_id)
    try:
        revision = ClaimRevision.objects.select_related("claim").prefetch_related("lines").get(
            organization_id=organization_id, id=claim_revision_id
        )
    except (ClaimRevision.DoesNotExist, ValueError) as exc:
        raise CommandError("claim_revision_not_found") from exc
    lines = list(revision.lines.order_by("ordinal"))
    approval = ClaimApproval.objects.filter(
        organization_id=organization_id, claim_revision=revision,
        envelope_digest=revision.envelope_digest,
    ).first()
    policy = SyntheticPolicySelection.objects.filter(organization_id=organization_id).first()
    try:
        dependencies = service_dependencies(
            actor=actor, organization_id=organization_id, encounter_id=revision.encounter_id,
            selections=[(line.service_id, line.service_revision_id) for line in lines],
        )
    except CommandError:
        dependencies = []
    applicable = {
        "envelope_unavailable": not _revision_envelope_valid(actor=actor, revision=revision, lines=lines),
        "superseded_revision": revision.claim.current_revision_id != revision.id,
        "selected_service_changed": any(
            dependency.current_revision_id != dependency.revision_id
            or dependency.current_disposition != "accepted"
            for dependency in dependencies
        ) or len(dependencies) != len(lines),
        "policy_changed": (
            policy is None or policy.version != revision.policy_version
            or policy.activation_generation != revision.policy_generation
        ),
        "unapproved": approval is None,
    }
    blockers = tuple(reason for reason in BLOCKER_ORDER if applicable[reason])
    return ClaimActionability(
        "approved_current" if not blockers else "claim_not_actionable",
        blockers[0] if blockers else None, blockers, revision.claim_id, revision.id,
        approval.id if approval else None,
    )


def claim_detail(*, actor, organization_id, claim_id):
    require_active_membership(actor=actor, organization_id=organization_id)
    try:
        return Claim.objects.select_related(
            "patient", "encounter", "current_revision"
        ).prefetch_related("revisions__lines", "revisions__approvals").get(
            organization_id=organization_id, id=claim_id
        )
    except (Claim.DoesNotExist, ValueError) as exc:
        raise CommandError("claim_not_found") from exc


def claim_revision_for_claim(*, actor, organization_id, claim_id, claim_revision_id):
    """Resolve the exact submitted revision while binding it to the presented claim."""
    require_active_membership(actor=actor, organization_id=organization_id)
    try:
        return ClaimRevision.objects.get(
            organization_id=organization_id,
            claim_id=claim_id,
            id=claim_revision_id,
        )
    except (ClaimRevision.DoesNotExist, ValueError) as exc:
        raise CommandError("claim_revision_not_for_claim") from exc


def claim_for_encounter(*, actor, organization_id, encounter_id):
    require_active_membership(actor=actor, organization_id=organization_id)
    return Claim.objects.select_related("current_revision").filter(
        organization_id=organization_id, encounter_id=encounter_id
    ).first()
