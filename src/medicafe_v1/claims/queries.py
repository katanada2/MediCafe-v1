import hashlib
import json
from dataclasses import dataclass

from django.db import connection

from medicafe_v1.access.services import require_active_membership
from medicafe_v1.records.queries import locked_encounter, service_dependencies
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


@dataclass(frozen=True)
class HistoricalClaimLine:
    ordinal: int
    claim_line_id: object
    original_charge: object


@dataclass(frozen=True)
class HistoricalDeliveryAttribution:
    organization_id: object
    encounter_id: object
    claim_id: object
    claim_revision_id: object
    claim_approval_id: object
    intent_id: object
    delivery_key: object
    receiver_id: str
    receiver_version: str
    receiver_receipt_id: str
    receiver_observation_id: object
    evidence_fingerprint: str
    reported_attempt_id: object
    envelope_digest: str
    byte_length: int
    currency: str
    original_charge: object
    lines: tuple[HistoricalClaimLine, ...]


@dataclass(frozen=True)
class ArchiveClaimLineSnapshot:
    claim_line_id: object
    ordinal: int
    service_id: object
    service_revision_id: object
    code: str
    units: int
    unit_amount: object
    line_amount: object
    currency: str


@dataclass(frozen=True)
class ArchiveDeliverySnapshot:
    intent_id: object
    claim_revision_id: object
    delivery_key: object
    receiver_version: str
    observation_id: object
    receipt_id: str
    evidence_fingerprint: str


@dataclass(frozen=True)
class ArchiveClaimRevisionSnapshot:
    revision_id: object
    revision_number: int
    envelope_digest: str
    currency: str
    total_amount: object
    lines: tuple[ArchiveClaimLineSnapshot, ...]


@dataclass(frozen=True)
class ClaimArchiveSnapshot:
    organization_id: object
    encounter_id: object
    claim_id: object | None
    current_revision_id: object | None
    envelope_digest: str
    currency: str
    total_amount: object | None
    lines: tuple[ArchiveClaimLineSnapshot, ...]
    deliveries: tuple[ArchiveDeliverySnapshot, ...]
    revisions: tuple[ArchiveClaimRevisionSnapshot, ...]


def _require_read_committed_atomic():
    if not connection.in_atomic_block:
        raise CommandError("acceptance_transaction_required")
    with connection.cursor() as cursor:
        cursor.execute("SHOW transaction_isolation")
        isolation = cursor.fetchone()[0].replace(" ", "_").lower()
    if isolation != "read_committed":
        raise CommandError("acceptance_isolation_incompatible")


def historical_delivery_attribution(
        *, actor, organization_id, intent_id, delivery_key, claim_revision_id,
        expected_receiver_id, expected_receiver_version, receiver_receipt_id,
        line_ordinals, for_acceptance=False):
    """Resolve exact historical F3 delivery evidence without current-head policy."""
    require_active_membership(actor=actor, organization_id=organization_id)
    try:
        intent = DeliveryIntent.objects.select_related(
            "claim", "claim_revision", "claim_approval"
        ).get(
            organization_id=organization_id, id=intent_id,
            delivery_key=delivery_key, claim_revision_id=claim_revision_id,
        )
    except (DeliveryIntent.DoesNotExist, ValueError) as exc:
        raise CommandError("unmatched_target") from exc
    if (
        expected_receiver_id != "synthetic-receiver"
        or intent.receiver_version != expected_receiver_version
        or intent.claim_id != intent.claim_revision.claim_id
        or intent.claim_approval.claim_revision_id != intent.claim_revision_id
        or intent.claim_approval.envelope_digest != intent.envelope_digest
    ):
        raise CommandError("unmatched_target")

    requested_ordinals = tuple(line_ordinals or ())
    if len(set(requested_ordinals)) != len(requested_ordinals):
        raise CommandError("unmatched_target")
    revision_lines = {
        line.ordinal: line
        for line in intent.claim_revision.lines.order_by("ordinal", "id")
    }
    if any(ordinal not in revision_lines for ordinal in requested_ordinals):
        raise CommandError("unmatched_target")

    if for_acceptance:
        _require_read_committed_atomic()
        require_active_membership(
            actor=actor, organization_id=organization_id, for_update=True
        )
        # Revalidate after the membership row is locked, before owner locks.
        require_active_membership(actor=actor, organization_id=organization_id)
        locked_encounter(
            actor=actor, organization_id=organization_id,
            encounter_id=intent.claim_revision.encounter_id,
        )
        try:
            Claim.objects.select_for_update(of=("self",)).get(
                organization_id=organization_id, id=intent.claim_id
            )
            intent = DeliveryIntent.objects.select_for_update(of=("self",)).select_related(
                "claim", "claim_revision", "claim_approval"
            ).get(organization_id=organization_id, id=intent.id)
        except (Claim.DoesNotExist, DeliveryIntent.DoesNotExist) as exc:
            raise CommandError("unmatched_target") from exc
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT evidence_fingerprint
                  FROM claims_receiverreceiptidentity
                 WHERE receiver_id=%s AND receiver_version=%s AND receipt_id=%s
                 FOR UPDATE
                """,
                [expected_receiver_id, expected_receiver_version, receiver_receipt_id],
            )
            anchor = cursor.fetchone()
        if anchor is None:
            raise CommandError("pending_delivery_evidence")

    namespace = ReceiverObservation.objects.filter(
        receiver_id=expected_receiver_id,
        receiver_version=expected_receiver_version,
        receipt_id=receiver_receipt_id,
    )
    target = namespace.filter(organization_id=organization_id, intent=intent)
    if ReceiverObservation.objects.filter(
        organization_id=organization_id, intent=intent,
        observed_state=ReceiverObservation.STATE_CONFLICT,
    ).exists():
        raise CommandError("conflicting_identity_or_content")
    if namespace.filter(observed_state=ReceiverObservation.STATE_CONFLICT).exists():
        raise CommandError("conflicting_identity_or_content")
    observation = target.filter(
        observed_state=ReceiverObservation.STATE_ACCEPTED, binding_valid=True,
    ).order_by("recorded_at", "id").first()
    if observation is None:
        if namespace.exclude(organization_id=organization_id, intent=intent).exists():
            raise CommandError("conflicting_identity_or_content")
        raise CommandError("pending_delivery_evidence")
    if for_acceptance and anchor[0] != observation.evidence_fingerprint:
        raise CommandError("conflicting_identity_or_content")

    revision = intent.claim_revision
    payload = bytes(revision.envelope_bytes)
    if (
        observation.received_bytes is None
        or bytes(observation.received_bytes) != payload
        or hashlib.sha256(payload).hexdigest() != intent.envelope_digest
        or len(payload) != intent.byte_length
        or observation.lookup_key != intent.delivery_key
        or observation.claim_revision_id != intent.claim_revision_id
        or observation.reported_organization_id != intent.organization_id
        or observation.reported_intent_id != intent.id
        or observation.reported_claim_revision_id != intent.claim_revision_id
        or observation.reported_delivery_key != intent.delivery_key
        or observation.reported_receiver_id != expected_receiver_id
        or observation.reported_receiver_version != expected_receiver_version
        or observation.reported_envelope_digest != intent.envelope_digest
        or observation.reported_byte_length != intent.byte_length
    ):
        raise CommandError("conflicting_identity_or_content")

    selected = requested_ordinals or tuple(revision_lines)
    lines = tuple(
        HistoricalClaimLine(
            ordinal, revision_lines[ordinal].id, revision_lines[ordinal].line_amount
        )
        for ordinal in selected
    )
    return HistoricalDeliveryAttribution(
        intent.organization_id, revision.encounter_id, intent.claim_id, revision.id,
        intent.claim_approval_id, intent.id, intent.delivery_key,
        expected_receiver_id, intent.receiver_version, receiver_receipt_id,
        observation.id, observation.evidence_fingerprint,
        observation.reported_attempt_id, intent.envelope_digest, intent.byte_length,
        revision.currency, revision.total_amount, lines,
    )


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


def archive_claim_snapshot(*, actor, organization_id, encounter_id):
    """Return deterministic claim and accepted-delivery state in caller snapshot."""
    require_active_membership(actor=actor, organization_id=organization_id)
    claim = Claim.objects.select_related("current_revision").filter(
        organization_id=organization_id, encounter_id=encounter_id
    ).first()
    if claim is None or claim.current_revision_id is None:
        return ClaimArchiveSnapshot(
            organization_id, encounter_id, claim.id if claim else None,
            None, "", "", None, (), (), (),
        )
    revision = ClaimRevision.objects.get(
        organization_id=organization_id, id=claim.current_revision_id, claim=claim
    )
    lines = tuple(ArchiveClaimLineSnapshot(
        line.id, line.ordinal, line.service_id, line.service_revision_id,
        line.code, line.units, line.unit_amount, line.line_amount, line.currency,
    ) for line in revision.lines.order_by("ordinal", "id"))
    observations = ReceiverObservation.objects.filter(
        organization_id=organization_id, intent__claim=claim,
        observed_state=ReceiverObservation.STATE_ACCEPTED, binding_valid=True,
    ).select_related("intent").order_by("recorded_at", "id")
    deliveries = tuple(ArchiveDeliverySnapshot(
        item.intent_id, item.intent.claim_revision_id, item.intent.delivery_key,
        item.receiver_version, item.id, item.receipt_id, item.evidence_fingerprint,
    ) for item in observations)
    revision_ids = {revision.id, *(item.intent.claim_revision_id for item in observations)}
    revisions = []
    for historical in ClaimRevision.objects.filter(
        organization_id=organization_id, claim=claim, id__in=revision_ids,
    ).order_by("revision_number", "id"):
        historical_lines = tuple(ArchiveClaimLineSnapshot(
            line.id, line.ordinal, line.service_id, line.service_revision_id,
            line.code, line.units, line.unit_amount, line.line_amount, line.currency,
        ) for line in historical.lines.order_by("ordinal", "id"))
        revisions.append(ArchiveClaimRevisionSnapshot(
            historical.id, historical.revision_number, historical.envelope_digest,
            historical.currency, historical.total_amount, historical_lines,
        ))
    return ClaimArchiveSnapshot(
        organization_id, encounter_id, claim.id, revision.id,
        revision.envelope_digest, revision.currency, revision.total_amount,
        lines, deliveries, tuple(revisions),
    )
