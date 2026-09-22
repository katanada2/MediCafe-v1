import hashlib
import json
from dataclasses import dataclass

from medicafe_v1.access.services import require_active_membership
from medicafe_v1.records.queries import service_dependencies
from medicafe_v1.sources.domain import CommandError

from .models import Claim, ClaimApproval, ClaimRevision, SyntheticPolicySelection
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


def claim_for_encounter(*, actor, organization_id, encounter_id):
    require_active_membership(actor=actor, organization_id=organization_id)
    return Claim.objects.select_related("current_revision").filter(
        organization_id=organization_id, encounter_id=encounter_id
    ).first()
