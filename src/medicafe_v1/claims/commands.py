import hashlib
import json
import uuid
from dataclasses import dataclass
from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from medicafe_v1.access.services import require_active_membership
from medicafe_v1.records.queries import exact_current_service_selection, locked_encounter
from medicafe_v1.sources.domain import CommandError

from .models import (
    Claim, ClaimApproval, ClaimLine, ClaimRevision, ClaimsCommandReceipt,
    SyntheticPolicySelection,
)
from .policies import ENVELOPE_FORMAT, MAX_ENVELOPE_BYTES, POLICIES, ROUTES
from .queries import claim_actionability, envelope_payload, serialize_payload


@dataclass(frozen=True)
class ClaimCommandResult:
    reason_code: str
    claim_id: object | None = None
    revision_id: object | None = None
    approval_id: object | None = None
    policy_version: str | None = None
    policy_generation: int | None = None
    current_policy_version: str | None = None
    current_policy_generation: int | None = None
    replayed: bool = False
    blockers: tuple[str, ...] = ()


def _uuid_text(value, reason_code):
    try:
        return str(uuid.UUID(str(value)))
    except (ValueError, TypeError, AttributeError) as exc:
        raise CommandError(reason_code) from exc


def _reason(value):
    normalized = (value or "").strip()
    if not normalized:
        raise CommandError("claim_reason_required")
    if len(normalized) > 500:
        raise CommandError("claim_reason_too_long")
    return normalized


def _intent_digest(payload):
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _claim_replay(*, organization_id, request_uuid, digest):
    receipt = ClaimsCommandReceipt.objects.filter(
        organization_id=organization_id, request_uuid=request_uuid
    ).first()
    if not receipt:
        return None
    if receipt.intent_digest != digest:
        raise CommandError("request_input_conflict")
    current = SyntheticPolicySelection.objects.filter(organization_id=organization_id).first()
    blockers = ()
    if receipt.result_revision_id:
        # The actor-specific actionability check is added by command callers when needed.
        blockers = ()
    return ClaimCommandResult(
        "claim_request_replayed", receipt.result_claim_id, receipt.result_revision_id,
        receipt.result_approval_id, receipt.result_policy_version or None,
        receipt.result_policy_generation,
        current.version if current else None,
        current.activation_generation if current else None,
        True, blockers,
    )


def _with_actionability(*, actor, organization_id, result):
    if not result or not result.revision_id:
        return result
    actionability = claim_actionability(
        actor=actor, organization_id=organization_id, claim_revision_id=result.revision_id
    )
    return ClaimCommandResult(**{**result.__dict__, "blockers": actionability.blockers})


def initialize_synthetic_policy(*, actor, organization_id):
    """Explicit provisioning used by the synthetic demo/test setup."""
    require_active_membership(actor=actor, organization_id=organization_id)
    with transaction.atomic():
        require_active_membership(actor=actor, organization_id=organization_id, for_update=True)
        selection, _ = SyntheticPolicySelection.objects.get_or_create(
            organization_id=organization_id,
            defaults={"version": "synthetic-v1", "activation_generation": 1, "selected_by": actor},
        )
    return selection


def select_synthetic_policy(*, actor, organization_id, request_id, expected_version,
                            expected_generation, version):
    require_active_membership(actor=actor, organization_id=organization_id)
    request_uuid = _uuid_text(request_id, "request_uuid_invalid")
    if version not in POLICIES or expected_version not in POLICIES:
        raise CommandError("policy_version_unsupported")
    try:
        generation = int(expected_generation)
    except (TypeError, ValueError) as exc:
        raise CommandError("policy_generation_invalid") from exc
    payload = {
        "organization": _uuid_text(organization_id, "organization_invalid"),
        "command_kind": "select_synthetic_policy", "expected_version": expected_version,
        "expected_generation": generation, "version": version,
    }
    digest = _intent_digest(payload)
    replay = _claim_replay(organization_id=organization_id, request_uuid=request_uuid, digest=digest)
    if replay:
        return _with_actionability(actor=actor, organization_id=organization_id, result=replay)
    with transaction.atomic():
        try:
            selection = SyntheticPolicySelection.objects.select_for_update().get(
                organization_id=organization_id
            )
        except SyntheticPolicySelection.DoesNotExist as exc:
            raise CommandError("synthetic_policy_not_selected") from exc
        replay = _claim_replay(organization_id=organization_id, request_uuid=request_uuid, digest=digest)
        if replay:
            return _with_actionability(actor=actor, organization_id=organization_id, result=replay)
        if selection.version != expected_version or selection.activation_generation != generation:
            raise CommandError("policy_selection_conflict")
        selected_generation = generation
        reason_code = "policy_selection_unchanged"
        if selection.version != version:
            selected_generation += 1
            SyntheticPolicySelection.objects.filter(pk=selection.pk).update(
                version=version, activation_generation=selected_generation,
                selected_by=actor, selected_at=timezone.now(),
            )
            reason_code = "policy_selection_changed"
        ClaimsCommandReceipt.objects.create(
            organization_id=organization_id, request_uuid=request_uuid,
            command_kind="select_synthetic_policy", target_key=str(organization_id),
            expected_predecessor_id=None, intent_digest=digest,
            result_policy_version=version, result_policy_generation=selected_generation,
        )
    return ClaimCommandResult(
        reason_code, policy_version=version, policy_generation=selected_generation,
        current_policy_version=version, current_policy_generation=selected_generation,
    )


def prepare_claim_revision(*, actor, organization_id, request_id, encounter_id,
                           expected_claim_revision_id, selected_service_revision_ids,
                           route_id, route_version, reason):
    require_active_membership(actor=actor, organization_id=organization_id)
    request_uuid = _uuid_text(request_id, "request_uuid_invalid")
    encounter_uuid = _uuid_text(encounter_id, "encounter_id_invalid")
    expected_uuid = (
        _uuid_text(expected_claim_revision_id, "claim_revision_id_invalid")
        if expected_claim_revision_id else None
    )
    selected = [
        _uuid_text(value, "service_revision_id_invalid")
        for value in (selected_service_revision_ids or [])
    ]
    if not 1 <= len(selected) <= 100:
        raise CommandError("claim_line_count_invalid")
    if len(set(selected)) != len(selected):
        raise CommandError("claim_service_duplicate")
    if (route_id, route_version) not in ROUTES:
        raise CommandError("claim_route_unsupported")
    reason = _reason(reason)
    payload = {
        "organization": _uuid_text(organization_id, "organization_invalid"),
        "command_kind": "prepare_claim_revision", "encounter": encounter_uuid,
        "expected_claim_revision": expected_uuid,
        "selected_service_revisions": selected, "route_id": route_id,
        "route_version": route_version, "reason": reason,
    }
    digest = _intent_digest(payload)
    replay = _claim_replay(organization_id=organization_id, request_uuid=request_uuid, digest=digest)
    if replay:
        return _with_actionability(actor=actor, organization_id=organization_id, result=replay)
    with transaction.atomic():
        encounter = locked_encounter(actor=actor, organization_id=organization_id, encounter_id=encounter_uuid)
        try:
            policy = SyntheticPolicySelection.objects.select_for_update().get(
                organization_id=organization_id
            )
        except SyntheticPolicySelection.DoesNotExist as exc:
            raise CommandError("synthetic_policy_not_selected") from exc
        claim = Claim.objects.select_for_update().filter(
            organization_id=organization_id, encounter=encounter
        ).first()
        replay = _claim_replay(organization_id=organization_id, request_uuid=request_uuid, digest=digest)
        if replay:
            return _with_actionability(actor=actor, organization_id=organization_id, result=replay)
        if claim:
            if expected_uuid is None or str(claim.current_revision_id) != expected_uuid:
                raise CommandError("claim_revision_conflict")
            predecessor = claim.current_revision
        else:
            if expected_uuid is not None:
                raise CommandError("claim_revision_conflict")
            predecessor = None
        selected_services = exact_current_service_selection(
            actor=actor, organization_id=organization_id, encounter_id=encounter.id,
            revision_ids=selected, for_update=True,
        )
        ordered_revisions = [service.current_revision for service in selected_services]
        if any(item.disposition != "accepted" for item in ordered_revisions):
            raise CommandError("selected_service_excluded")
        if any(item.code not in POLICIES[policy.version] for item in ordered_revisions):
            raise CommandError("selected_service_policy_rejected")
        claim_id = claim.id if claim else uuid.uuid4()
        revision_id = uuid.uuid4()
        revision_number = predecessor.revision_number + 1 if predecessor else 1
        line_values = []
        total = Decimal("0.00")
        for ordinal, (service, service_revision) in enumerate(
            zip(selected_services, ordered_revisions, strict=True), start=1
        ):
            amount = service_revision.units * service_revision.unit_amount
            total += amount
            line_values.append({
                "id": uuid.uuid4(), "ordinal": ordinal, "service": service,
                "service_revision": service_revision, "code": service_revision.code,
                "units": service_revision.units, "unit_amount": service_revision.unit_amount,
                "line_amount": amount,
            })
        revision_shell = ClaimRevision(
            id=revision_id, organization_id=organization_id, claim_id=claim_id,
            encounter=encounter, patient=encounter.patient, revision_number=revision_number,
            predecessor=predecessor, prepared_by=actor, reason=reason,
            policy_version=policy.version, policy_generation=policy.activation_generation,
            route_id=route_id, route_version=route_version,
            envelope_format_version=ENVELOPE_FORMAT, total_amount=total, currency="USD",
        )
        line_shells = [ClaimLine(
            id=value["id"], organization_id=organization_id, claim_id=claim_id,
            claim_revision_id=revision_id, encounter=encounter, patient=encounter.patient,
            service=value["service"], service_revision=value["service_revision"],
            ordinal=value["ordinal"], code=value["code"], units=value["units"],
            unit_amount=value["unit_amount"], line_amount=value["line_amount"], currency="USD",
        ) for value in line_values]
        envelope = serialize_payload(envelope_payload(revision_shell, line_shells))
        if len(envelope) > MAX_ENVELOPE_BYTES:
            raise CommandError("claim_envelope_too_large")
        envelope_digest = hashlib.sha256(envelope).hexdigest()
        if not claim:
            claim = Claim.objects.create(
                id=claim_id, organization_id=organization_id, encounter=encounter,
                patient=encounter.patient,
            )
        revision = ClaimRevision.objects.create(
            id=revision_id, organization_id=organization_id, claim=claim,
            encounter=encounter, patient=encounter.patient, revision_number=revision_number,
            predecessor=predecessor, prepared_by=actor, reason=reason,
            policy_version=policy.version, policy_generation=policy.activation_generation,
            route_id=route_id, route_version=route_version,
            envelope_format_version=ENVELOPE_FORMAT, envelope_bytes=envelope,
            envelope_digest=envelope_digest, total_amount=total, currency="USD",
        )
        ClaimLine.objects.bulk_create(line_shells)
        Claim.objects.filter(pk=claim.pk).update(current_revision=revision)
        ClaimsCommandReceipt.objects.create(
            organization_id=organization_id, request_uuid=request_uuid,
            command_kind="prepare_claim_revision", target_key=encounter_uuid,
            expected_predecessor_id=predecessor.id if predecessor else None,
            intent_digest=digest, result_claim=claim, result_revision=revision,
            result_policy_version=policy.version,
            result_policy_generation=policy.activation_generation,
        )
    return ClaimCommandResult(
        "claim_revision_prepared", claim.id, revision.id,
        policy_version=policy.version, policy_generation=policy.activation_generation,
        current_policy_version=policy.version,
        current_policy_generation=policy.activation_generation,
    )


def approve_claim_revision(*, actor, organization_id, request_id, claim_revision_id,
                           expected_envelope_digest):
    require_active_membership(actor=actor, organization_id=organization_id)
    request_uuid = _uuid_text(request_id, "request_uuid_invalid")
    revision_uuid = _uuid_text(claim_revision_id, "claim_revision_id_invalid")
    digest_value = (expected_envelope_digest or "").strip().lower()
    if len(digest_value) != 64 or any(char not in "0123456789abcdef" for char in digest_value):
        raise CommandError("claim_envelope_digest_invalid")
    payload = {
        "organization": _uuid_text(organization_id, "organization_invalid"),
        "command_kind": "approve_claim_revision", "claim_revision": revision_uuid,
        "expected_envelope_digest": digest_value,
    }
    digest = _intent_digest(payload)
    replay = _claim_replay(organization_id=organization_id, request_uuid=request_uuid, digest=digest)
    if replay:
        return _with_actionability(actor=actor, organization_id=organization_id, result=replay)
    try:
        scoped_revision = ClaimRevision.objects.select_related("claim").get(
            organization_id=organization_id, id=revision_uuid
        )
    except ClaimRevision.DoesNotExist as exc:
        raise CommandError("claim_revision_not_found") from exc
    with transaction.atomic():
        locked_encounter(
            actor=actor, organization_id=organization_id,
            encounter_id=scoped_revision.encounter_id,
        )
        SyntheticPolicySelection.objects.select_for_update().get(organization_id=organization_id)
        claim = Claim.objects.select_for_update().get(
            organization_id=organization_id, id=scoped_revision.claim_id
        )
        replay = _claim_replay(organization_id=organization_id, request_uuid=request_uuid, digest=digest)
        if replay:
            return _with_actionability(actor=actor, organization_id=organization_id, result=replay)
        if claim.current_revision_id != scoped_revision.id:
            raise CommandError("superseded_revision")
        if scoped_revision.envelope_digest != digest_value:
            raise CommandError("claim_envelope_digest_conflict")
        actionability = claim_actionability(
            actor=actor, organization_id=organization_id, claim_revision_id=revision_uuid
        )
        nonapproval_blockers = tuple(item for item in actionability.blockers if item != "unapproved")
        if nonapproval_blockers:
            raise CommandError(nonapproval_blockers[0])
        approval = ClaimApproval.objects.filter(
            organization_id=organization_id, claim_revision=scoped_revision,
            envelope_digest=digest_value,
        ).first()
        reason_code = "claim_already_approved"
        if not approval:
            approval = ClaimApproval.objects.create(
                organization_id=organization_id, claim_revision=scoped_revision,
                envelope_digest=digest_value, approved_by=actor,
            )
            reason_code = "claim_revision_approved"
        ClaimsCommandReceipt.objects.create(
            organization_id=organization_id, request_uuid=request_uuid,
            command_kind="approve_claim_revision", target_key=revision_uuid,
            expected_predecessor_id=None, intent_digest=digest,
            result_claim=claim, result_revision=scoped_revision, result_approval=approval,
            result_policy_version=scoped_revision.policy_version,
            result_policy_generation=scoped_revision.policy_generation,
        )
    return ClaimCommandResult(
        reason_code, claim.id, scoped_revision.id, approval.id,
        scoped_revision.policy_version, scoped_revision.policy_generation,
        scoped_revision.policy_version, scoped_revision.policy_generation,
    )
