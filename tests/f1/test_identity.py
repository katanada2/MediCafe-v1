from __future__ import annotations

import uuid
from datetime import date

from django.db import IntegrityError, transaction

from medicafe_v1.access.services import AuthorizationError
from medicafe_v1.records.commands import ResolutionIntent, resolve_identity
from medicafe_v1.records.models import Encounter, IdentityDecision, Patient, PatientAlias
from medicafe_v1.records.queries import exact_alias_suggestion
from medicafe_v1.sources.domain import CommandError
from medicafe_v1.sources.models import Artifact, Delivery
from medicafe_v1.sources.queries import scoped_deliveries, scoped_observations

from tests.fixtures.synthetic_inputs import csv_bytes, synthetic_rows
from tests.f1.base import F1TestCase, F1TransactionTestCase


class IdentityResolutionTests(F1TestCase):
    def _parsed_observation(self, *, note="SYNTHETIC_IDENTITY"):
        admitted = self.admit(content=csv_bytes(synthetic_rows(note=note)))
        self.parse(admitted.delivery_id)
        return self.first_observation(admitted.delivery_id)

    def test_exact_alias_and_explicit_same_day_creation(self):
        existing_patient = Patient.objects.create(organization=self.alpha, display_name="Synthetic Existing")
        existing_alias = PatientAlias.objects.create(
            organization=self.alpha, patient=existing_patient,
            namespace="synthetic-patient-ref", value="000042",
        )
        suggestion = exact_alias_suggestion(
            actor=self.alpha_user, organization_id=self.alpha.id,
            namespace=existing_alias.namespace, value=existing_alias.value,
        )
        self.assertEqual(suggestion.patient_id, existing_patient.id)

        observation_one = self._parsed_observation(note="SYNTHETIC_SAME_DAY_ONE")
        observation_two = self._parsed_observation(note="SYNTHETIC_SAME_DAY_TWO")
        first = resolve_identity(
            actor=self.alpha_user, organization_id=self.alpha.id, observation_id=observation_one.id,
            request_uuid=uuid.uuid4(),
            intent=ResolutionIntent(
                mode="create", reason="Synthetic first same-day review", display_name="Synthetic Patient One",
                alias_namespace="synthetic", alias_value="same-day-001", service_date="2026-01-15",
            ),
        )
        second = resolve_identity(
            actor=self.alpha_user, organization_id=self.alpha.id, observation_id=observation_two.id,
            request_uuid=uuid.uuid4(),
            intent=ResolutionIntent(
                mode="create", reason="Synthetic second same-day review", display_name="Synthetic Patient Two",
                alias_namespace="synthetic", alias_value="same-day-002", service_date="2026-01-15",
            ),
        )
        self.assertNotEqual(first.patient_id, second.patient_id)
        self.assertNotEqual(first.encounter_id, second.encounter_id)
        self.assertEqual(Encounter.objects.filter(organization=self.alpha, service_date=date(2026, 1, 15)).count(), 2)

    def test_resolution_request_replay_conflict_and_atomic_creation(self):
        observation = self._parsed_observation(note="SYNTHETIC_RESOLUTION_REPLAY")
        request_uuid = uuid.uuid4()
        intent = ResolutionIntent(
            mode="create", reason="Synthetic operator reason", display_name="Synthetic Replay Patient",
            alias_namespace="synthetic", alias_value="replay-001", service_date="2026-01-15",
        )

        accepted = resolve_identity(
            actor=self.alpha_user, organization_id=self.alpha.id,
            observation_id=observation.id, request_uuid=request_uuid, intent=intent,
        )
        replay = resolve_identity(
            actor=self.alpha_user, organization_id=self.alpha.id,
            observation_id=observation.id, request_uuid=request_uuid, intent=intent,
        )
        self.assertEqual(replay.reason_code, "resolution_replayed")
        self.assertEqual(replay.decision_id, accepted.decision_id)
        self.assertEqual(Patient.objects.filter(organization=self.alpha).count(), 1)
        self.assertEqual(Encounter.objects.filter(organization=self.alpha).count(), 1)
        self.assertEqual(IdentityDecision.objects.filter(organization=self.alpha).count(), 1)

        other_observation = self._parsed_observation(note="SYNTHETIC_CROSS_OBSERVATION_REQUEST")
        with self.assertRaises(CommandError) as cross_observation_request:
            resolve_identity(
                actor=self.alpha_user, organization_id=self.alpha.id,
                observation_id=other_observation.id, request_uuid=request_uuid, intent=intent,
            )
        self.assertEqual(cross_observation_request.exception.reason_code, "request_input_conflict")
        self.assertFalse(IdentityDecision.objects.filter(observation=other_observation).exists())
        self.assertEqual(Patient.objects.filter(organization=self.alpha).count(), 1)
        self.assertEqual(Encounter.objects.filter(organization=self.alpha).count(), 1)

        changed = ResolutionIntent(
            mode="create", reason="Synthetic changed intent", display_name="Synthetic Different Patient",
            alias_namespace="synthetic", alias_value="replay-002", service_date="2026-01-15",
        )
        with self.assertRaises(CommandError) as request_conflict:
            resolve_identity(
                actor=self.alpha_user, organization_id=self.alpha.id,
                observation_id=observation.id, request_uuid=request_uuid, intent=changed,
            )
        self.assertEqual(request_conflict.exception.reason_code, "request_input_conflict")
        self.assertEqual(Patient.objects.filter(organization=self.alpha).count(), 1)

        competing = ResolutionIntent(
            mode="create", reason="Synthetic competing request", display_name="Synthetic Competing Patient",
            alias_namespace="synthetic", alias_value="replay-003", service_date="2026-01-15",
        )
        with self.assertRaises(CommandError) as observation_conflict:
            resolve_identity(
                actor=self.alpha_user, organization_id=self.alpha.id,
                observation_id=observation.id, request_uuid=uuid.uuid4(), intent=competing,
            )
        self.assertEqual(observation_conflict.exception.reason_code, "observation_resolution_conflict")

        accepted_again = resolve_identity(
            actor=self.alpha_user, organization_id=self.alpha.id,
            observation_id=observation.id, request_uuid=uuid.uuid4(),
            intent=ResolutionIntent(
                mode="attach", reason="Synthetic same target confirmation",
                patient_id=str(accepted.patient_id), encounter_id=str(accepted.encounter_id),
            ),
        )
        self.assertEqual(accepted_again.reason_code, "already_resolved_same_target")
        self.assertEqual(accepted_again.decision_id, accepted.decision_id)

        invalid_alias_observation = self._parsed_observation(note="SYNTHETIC_ATOMIC_ROLLBACK")
        invalid_alias_intent = ResolutionIntent(
            mode="create", reason="Synthetic invalid alias", display_name="Synthetic Should Roll Back",
            alias_namespace=" ", alias_value="non-empty", service_date="2026-01-15",
        )
        with self.assertRaises(CommandError) as alias_error:
            resolve_identity(
                actor=self.alpha_user, organization_id=self.alpha.id,
                observation_id=invalid_alias_observation.id, request_uuid=uuid.uuid4(), intent=invalid_alias_intent,
            )
        self.assertEqual(alias_error.exception.reason_code, "alias_namespace_required")
        self.assertEqual(Patient.objects.filter(organization=self.alpha).count(), 1)
        self.assertEqual(Encounter.objects.filter(organization=self.alpha).count(), 1)
        self.assertEqual(IdentityDecision.objects.filter(organization=self.alpha).count(), 1)

    def test_rejected_request_uuid_can_be_reused_after_correction(self):
        observation = self._parsed_observation(note="SYNTHETIC_CORRECTED_REQUEST")
        request_uuid = uuid.uuid4()
        rejected = ResolutionIntent(mode="create", reason=" ", display_name="Synthetic Corrected", service_date="2026-01-15")
        with self.assertRaises(CommandError) as missing_reason:
            resolve_identity(
                actor=self.alpha_user, organization_id=self.alpha.id,
                observation_id=observation.id, request_uuid=request_uuid, intent=rejected,
            )
        self.assertEqual(missing_reason.exception.reason_code, "resolution_reason_required")
        self.assertEqual(IdentityDecision.objects.filter(organization=self.alpha).count(), 0)

        corrected = ResolutionIntent(
            mode="create", reason="Synthetic corrected reason", display_name="Synthetic Corrected",
            service_date="2026-01-15",
        )
        result = resolve_identity(
            actor=self.alpha_user, organization_id=self.alpha.id,
            observation_id=observation.id, request_uuid=request_uuid, intent=corrected,
        )
        self.assertEqual(result.reason_code, "identity_resolved")
        self.assertEqual(IdentityDecision.objects.filter(organization=self.alpha).count(), 1)

    def test_cross_organization_commands_and_queries_are_denied(self):
        # Make a genuinely beta-owned target separately from the default alpha fixture.
        beta_admitted = self.admit(
            actor=self.beta_user, organization=self.beta,
            content=csv_bytes(synthetic_rows(note="SYNTHETIC_BETA_DATA")),
            source_key=str(uuid.uuid4()),
        )
        self.parse(beta_admitted.delivery_id, actor=self.beta_user, organization=self.beta)
        beta_observation = self.first_observation(beta_admitted.delivery_id)
        beta_patient, beta_encounter = self.create_patient_encounter(organization=self.beta)

        with self.assertRaises(AuthorizationError):
            scoped_deliveries(actor=self.alpha_user, organization_id=self.beta.id)
        with self.assertRaises(AuthorizationError):
            scoped_observations(actor=self.alpha_user, organization_id=self.beta.id)
        with self.assertRaises(AuthorizationError):
            self.parse(beta_admitted.delivery_id, actor=self.alpha_user, organization=self.beta)
        with self.assertRaises(AuthorizationError):
            resolve_identity(
                actor=self.alpha_user, organization_id=self.beta.id, observation_id=beta_observation.id,
                request_uuid=uuid.uuid4(), intent=ResolutionIntent(
                    mode="attach", reason="Synthetic unauthorized", patient_id=str(beta_patient.id),
                    encounter_id=str(beta_encounter.id),
                ),
            )

        alpha_observation = self._parsed_observation(note="SYNTHETIC_ALPHA_TARGET_SUBSTITUTION")
        with self.assertRaises(CommandError) as wrong_target:
            resolve_identity(
                actor=self.alpha_user, organization_id=self.alpha.id, observation_id=alpha_observation.id,
                request_uuid=uuid.uuid4(), intent=ResolutionIntent(
                    mode="attach", reason="Synthetic cross-org target", patient_id=str(beta_patient.id),
                    encounter_id=str(beta_encounter.id),
                ),
            )
        self.assertEqual(wrong_target.exception.reason_code, "resolution_target_not_found")

        with self.assertRaises(CommandError) as wrong_supersedes:
            self.admit(
                content=csv_bytes(synthetic_rows(note="SYNTHETIC_WRONG_SUPERSEDES")),
                source_key=str(uuid.uuid4()), supersedes_id=beta_admitted.delivery_id,
            )
        self.assertEqual(wrong_supersedes.exception.reason_code, "supersedes_not_found")


class CompositeConstraintTests(F1TransactionTestCase):
    def test_direct_cross_organization_artifact_reference_fails_in_postgres(self):
        artifact_result = self.admit(content=csv_bytes(synthetic_rows(note="SYNTHETIC_CONSTRAINT")))
        artifact = Artifact.objects.get(id=Delivery.objects.get(id=artifact_result.delivery_id).artifact_id)

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Delivery.objects.create(
                    organization=self.beta,
                    source_namespace="synthetic-direct-write",
                    source_key=str(uuid.uuid4()),
                    artifact=artifact,
                    admitted_by=self.beta_user,
                )
