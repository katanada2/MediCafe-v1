import hashlib
import json
from dataclasses import dataclass
from datetime import date

from django.db import IntegrityError, transaction

from medicafe_v1.access.services import require_active_membership
from medicafe_v1.sources.domain import CommandError, CommandResult
from medicafe_v1.sources.models import Observation

from .models import Encounter, IdentityDecision, Patient, PatientAlias


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


def resolve_identity(*, actor, organization_id, observation_id, request_uuid, intent):
    require_active_membership(actor=actor, organization_id=organization_id)
    input_digest = intent.digest()
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
            observation = Observation.objects.select_for_update().get(
                organization_id=organization_id, id=observation_id
            )
        except Observation.DoesNotExist as exc:
            raise CommandError("observation_not_found") from exc
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
