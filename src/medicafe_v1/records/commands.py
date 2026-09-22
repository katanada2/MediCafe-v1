import hashlib
import json
import uuid
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation

from django.db import IntegrityError, transaction

from medicafe_v1.access.services import require_active_membership
from medicafe_v1.sources.artifacts import LocalArtifactStore
from medicafe_v1.sources.domain import CommandError, CommandResult
from medicafe_v1.sources.models import Observation

from .models import (
    Encounter, IdentityDecision, Patient, PatientAlias, RecordsCommandReceipt,
    Service, ServiceRevision,
)


@dataclass(frozen=True)
class ResolutionIntent:
    mode: str
    reason: str
    patient_id: str | None = None
    encounter_id: str | None = None
    display_name: str | None = None
    alias_namespace: str | None = None
    alias_value: str | None = None
    service_date: str | None = None

    def digest(self):
        payload = {key: value for key, value in vars(self).items()}
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
        return hashlib.sha256(encoded).hexdigest()


def _result(decision, reason_code):
    return CommandResult(
        reason_code, decision_id=decision.id, patient_id=decision.patient_id,
        encounter_id=decision.encounter_id,
    )


def resolve_identity(*, actor, organization_id, observation_id, request_uuid, intent, artifact_store=None):
    require_active_membership(actor=actor, organization_id=organization_id)
    digest_input = f"{observation_id}:{intent.digest()}".encode("ascii")
    input_digest = hashlib.sha256(digest_input).hexdigest()
    with transaction.atomic():
        require_active_membership(actor=actor, organization_id=organization_id, for_update=True)
        prior_request = IdentityDecision.objects.filter(
            organization_id=organization_id, request_uuid=request_uuid
        ).first()
        if prior_request:
            if prior_request.input_digest != input_digest:
                raise CommandError("request_input_conflict")
            return _result(prior_request, "resolution_replayed")
        try:
            observation = Observation.objects.select_for_update().select_related(
                "parse_result__delivery__artifact"
            ).get(
                organization_id=organization_id, id=observation_id
            )
        except Observation.DoesNotExist as exc:
            raise CommandError("observation_not_found") from exc
        (artifact_store or LocalArtifactStore()).read_verified(
            observation.parse_result.delivery.artifact
        )
        # A concurrent identical request may have committed while this caller waited for the observation lock.
        prior_request = IdentityDecision.objects.filter(
            organization_id=organization_id, request_uuid=request_uuid
        ).first()
        if prior_request:
            if prior_request.input_digest != input_digest:
                raise CommandError("request_input_conflict")
            return _result(prior_request, "resolution_replayed")
        accepted = IdentityDecision.objects.filter(observation=observation).first()
        if accepted:
            if (intent.mode == "attach" and str(accepted.patient_id) == str(intent.patient_id)
                    and str(accepted.encounter_id) == str(intent.encounter_id)):
                return _result(accepted, "already_resolved_same_target")
            raise CommandError("observation_resolution_conflict")
        if not intent.reason.strip():
            raise CommandError("resolution_reason_required")
        if intent.mode == "attach":
            try:
                patient = Patient.objects.get(organization_id=organization_id, id=intent.patient_id)
                encounter = Encounter.objects.get(
                    organization_id=organization_id, id=intent.encounter_id, patient=patient
                )
            except (Patient.DoesNotExist, Encounter.DoesNotExist, ValueError) as exc:
                raise CommandError("resolution_target_not_found") from exc
        elif intent.mode == "create":
            if not (intent.display_name or "").strip():
                raise CommandError("display_name_required")
            try:
                service_date = date.fromisoformat(intent.service_date or "")
            except ValueError as exc:
                raise CommandError("service_date_invalid") from exc
            patient = Patient.objects.create(
                organization_id=organization_id, display_name=intent.display_name.strip()
            )
            if intent.alias_value:
                if not (intent.alias_namespace or "").strip():
                    raise CommandError("alias_namespace_required")
                try:
                    PatientAlias.objects.create(
                        organization_id=organization_id, patient=patient,
                        namespace=intent.alias_namespace.strip(), value=intent.alias_value.strip(),
                    )
                except IntegrityError as exc:
                    raise CommandError("alias_conflict") from exc
            encounter = Encounter.objects.create(
                organization_id=organization_id, patient=patient, service_date=service_date
            )
        else:
            raise CommandError("resolution_mode_invalid")
        decision = IdentityDecision.objects.create(
            organization_id=organization_id, observation=observation, patient=patient,
            encounter=encounter, decided_by=actor, reason=intent.reason.strip(),
            request_uuid=request_uuid, input_digest=input_digest,
        )
    return _result(decision, "identity_resolved")


SERVICE_CODES = {"SYN-A", "SYN-B"}


@dataclass(frozen=True)
class ServiceCommandResult:
    reason_code: str
    service_id: object
    revision_id: object
    replayed: bool = False


def _uuid_text(value, reason_code):
    try:
        return str(uuid.UUID(str(value)))
    except (ValueError, TypeError, AttributeError) as exc:
        raise CommandError(reason_code) from exc


def _reason(value):
    normalized = (value or "").strip()
    if not normalized:
        raise CommandError("service_reason_required")
    if len(normalized) > 500:
        raise CommandError("service_reason_too_long")
    return normalized


def _economics(code, units, unit_amount, currency):
    if code not in SERVICE_CODES:
        raise CommandError("service_code_unsupported")
    if isinstance(units, (bool, float)):
        raise CommandError("service_units_invalid")
    try:
        normalized_units = int(units)
    except (TypeError, ValueError) as exc:
        raise CommandError("service_units_invalid") from exc
    if (
        not 1 <= normalized_units <= 100
        or (isinstance(units, str) and not units.strip().isdigit())
        or (not isinstance(units, str) and units != normalized_units)
    ):
        raise CommandError("service_units_invalid")
    if isinstance(unit_amount, float):
        raise CommandError("service_amount_invalid")
    try:
        amount = Decimal(str(unit_amount))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise CommandError("service_amount_invalid") from exc
    if not amount.is_finite() or amount < 0 or amount > Decimal("9999.99"):
        raise CommandError("service_amount_invalid")
    if amount.as_tuple().exponent < -2:
        raise CommandError("service_amount_precision")
    amount = amount.quantize(Decimal("0.01"))
    if currency != "USD":
        raise CommandError("service_currency_unsupported")
    return code, normalized_units, amount, currency


def _intent_digest(payload):
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _service_replay(*, organization_id, request_uuid, digest):
    receipt = RecordsCommandReceipt.objects.filter(
        organization_id=organization_id, request_uuid=request_uuid
    ).first()
    if not receipt:
        return None
    if receipt.intent_digest != digest:
        raise CommandError("request_input_conflict")
    return ServiceCommandResult(
        "service_request_replayed", receipt.result_service_id, receipt.result_revision_id, True
    )


def _service_evidence(*, organization_id, identity_decision_id, evidence_observation_id,
                      artifact_store, verify_artifact=True):
    try:
        decision = IdentityDecision.objects.select_related(
            "observation__parse_result__delivery__artifact", "encounter", "patient"
        ).get(
            organization_id=organization_id,
            id=identity_decision_id,
            observation_id=evidence_observation_id,
        )
    except (IdentityDecision.DoesNotExist, ValueError) as exc:
        raise CommandError("service_evidence_not_resolved") from exc
    if verify_artifact:
        (artifact_store or LocalArtifactStore()).read_verified(
            decision.observation.parse_result.delivery.artifact
        )
    return decision


def accept_service(*, actor, organization_id, request_id, identity_decision_id,
                   evidence_observation_id, code, units, unit_amount, currency, reason,
                   artifact_store=None):
    require_active_membership(actor=actor, organization_id=organization_id)
    request_uuid = _uuid_text(request_id, "request_uuid_invalid")
    decision_id = _uuid_text(identity_decision_id, "identity_decision_invalid")
    observation_id = _uuid_text(evidence_observation_id, "evidence_observation_invalid")
    reason = _reason(reason)
    code, units, amount, currency = _economics(code, units, unit_amount, currency)
    payload = {
        "organization": _uuid_text(organization_id, "organization_invalid"),
        "command_kind": "accept_service", "identity_decision": decision_id,
        "evidence_observation": observation_id, "code": code, "units": units,
        "unit_amount": f"{amount:.2f}", "currency": currency, "reason": reason,
    }
    digest = _intent_digest(payload)
    replay = _service_replay(organization_id=organization_id, request_uuid=request_uuid, digest=digest)
    if replay:
        return replay
    decision = _service_evidence(
        organization_id=organization_id, identity_decision_id=decision_id,
        evidence_observation_id=observation_id, artifact_store=artifact_store,
    )
    with transaction.atomic():
        require_active_membership(actor=actor, organization_id=organization_id, for_update=True)
        Encounter.objects.select_for_update().get(
            organization_id=organization_id, id=decision.encounter_id, patient_id=decision.patient_id
        )
        replay = _service_replay(organization_id=organization_id, request_uuid=request_uuid, digest=digest)
        if replay:
            return replay
        service = Service.objects.create(
            organization_id=organization_id, encounter_id=decision.encounter_id,
            patient_id=decision.patient_id, identity_decision=decision,
        )
        revision = ServiceRevision.objects.create(
            organization_id=organization_id, service=service, encounter_id=decision.encounter_id,
            patient_id=decision.patient_id, revision_number=1, predecessor=None,
            decided_by=actor, reason=reason, evidence_observation_id=observation_id,
            identity_decision=decision, disposition="accepted", code=code, units=units,
            unit_amount=amount, currency=currency,
        )
        Service.objects.filter(pk=service.pk).update(current_revision=revision)
        RecordsCommandReceipt.objects.create(
            organization_id=organization_id, request_uuid=request_uuid,
            command_kind="accept_service", target_key=decision_id,
            expected_predecessor_id=None, intent_digest=digest,
            result_service=service, result_revision=revision,
        )
    return ServiceCommandResult("service_accepted", service.id, revision.id)


def revise_service(*, actor, organization_id, request_id, service_id, expected_revision_id,
                   evidence_observation_id, disposition, code=None, units=None, unit_amount=None,
                   currency=None, reason=None, artifact_store=None):
    require_active_membership(actor=actor, organization_id=organization_id)
    request_uuid = _uuid_text(request_id, "request_uuid_invalid")
    service_uuid = _uuid_text(service_id, "service_id_invalid")
    expected_uuid = _uuid_text(expected_revision_id, "service_revision_id_invalid")
    observation_uuid = _uuid_text(evidence_observation_id, "evidence_observation_invalid")
    reason = _reason(reason)
    if disposition not in {"accepted", "excluded"}:
        raise CommandError("service_disposition_invalid")
    try:
        service = Service.objects.select_related("current_revision").get(
            organization_id=organization_id, id=service_uuid
        )
    except Service.DoesNotExist as exc:
        raise CommandError("service_not_found") from exc
    if str(service.current_revision_id) != expected_uuid:
        # Replay must still win over a now-stale head.
        prior = RecordsCommandReceipt.objects.filter(
            organization_id=organization_id, request_uuid=request_uuid
        ).first()
        if prior:
            # Build the canonical excluded intent from the original expected revision below.
            expected = ServiceRevision.objects.filter(
                organization_id=organization_id, service=service, id=expected_uuid
            ).first()
        else:
            raise CommandError("service_revision_conflict")
    else:
        expected = service.current_revision
    if not expected:
        raise CommandError("service_revision_not_found")
    if disposition == "excluded":
        code, units, amount, currency = expected.code, expected.units, expected.unit_amount, expected.currency
    else:
        code, units, amount, currency = _economics(code, units, unit_amount, currency)
    try:
        evidence_decision = IdentityDecision.objects.get(
            organization_id=organization_id, observation_id=observation_uuid,
            patient_id=service.patient_id, encounter_id=service.encounter_id,
        )
    except IdentityDecision.DoesNotExist as exc:
        raise CommandError("service_evidence_not_resolved") from exc
    _service_evidence(
        organization_id=organization_id, identity_decision_id=evidence_decision.id,
        evidence_observation_id=observation_uuid, artifact_store=artifact_store,
        verify_artifact=False,
    )
    payload = {
        "organization": _uuid_text(organization_id, "organization_invalid"),
        "command_kind": "revise_service", "service": service_uuid,
        "expected_revision": expected_uuid, "evidence_observation": observation_uuid,
        "disposition": disposition, "code": code, "units": units,
        "unit_amount": f"{amount:.2f}", "currency": currency, "reason": reason,
    }
    digest = _intent_digest(payload)
    replay = _service_replay(organization_id=organization_id, request_uuid=request_uuid, digest=digest)
    if replay:
        return replay
    (artifact_store or LocalArtifactStore()).read_verified(
        evidence_decision.observation.parse_result.delivery.artifact
    )
    with transaction.atomic():
        require_active_membership(actor=actor, organization_id=organization_id, for_update=True)
        Encounter.objects.select_for_update().get(
            organization_id=organization_id, id=service.encounter_id, patient_id=service.patient_id
        )
        locked = Service.objects.select_for_update(of=("self",)).select_related("current_revision").get(
            organization_id=organization_id, id=service_uuid
        )
        replay = _service_replay(organization_id=organization_id, request_uuid=request_uuid, digest=digest)
        if replay:
            return replay
        if str(locked.current_revision_id) != expected_uuid:
            raise CommandError("service_revision_conflict")
        revision = ServiceRevision.objects.create(
            organization_id=organization_id, service=locked, encounter_id=locked.encounter_id,
            patient_id=locked.patient_id, revision_number=expected.revision_number + 1,
            predecessor=expected, decided_by=actor, reason=reason,
            evidence_observation_id=observation_uuid, identity_decision=evidence_decision,
            disposition=disposition, code=code, units=units, unit_amount=amount, currency=currency,
        )
        Service.objects.filter(pk=locked.pk).update(current_revision=revision)
        RecordsCommandReceipt.objects.create(
            organization_id=organization_id, request_uuid=request_uuid,
            command_kind="revise_service", target_key=service_uuid,
            expected_predecessor_id=expected.id, intent_digest=digest,
            result_service=locked, result_revision=revision,
        )
    return ServiceCommandResult("service_revised", locked.id, revision.id)
