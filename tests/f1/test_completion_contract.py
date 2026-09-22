from __future__ import annotations

import os
import subprocess
import sys
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from django.db import DatabaseError, IntegrityError, close_old_connections, connection, transaction
from django.urls import reverse

from medicafe_v1.access.models import User
from medicafe_v1.records.commands import ResolutionIntent, resolve_identity
from medicafe_v1.records.models import Encounter, IdentityDecision, Patient
from medicafe_v1.sources.domain import CommandError
from medicafe_v1.sources.models import ParseAttempt, ParseResult

from tests.f1.base import F1TestCase, F1TransactionTestCase
from tests.fixtures.synthetic_inputs import DOCX_MEDIA_TYPE, csv_bytes, docx_bytes, synthetic_rows


class CompletedSurfaceTests(F1TestCase):
    def test_authenticated_docx_command_path_and_log_redaction(self):
        docx_result = self.admit(
            content=docx_bytes(synthetic_rows(note="SYNTHETIC_DOCX_COMMAND")),
            media_type=DOCX_MEDIA_TYPE,
        )
        parsed = self.parse(docx_result.delivery_id)
        self.assertEqual(parsed.reason_code, "parse_succeeded")
        self.assertEqual(self.first_observation(docx_result.delivery_id).raw_values["note"], "SYNTHETIC_DOCX_COMMAND")

        sentinel = "SYNTHETIC_SENSITIVE_LOG_SENTINEL_9381"
        with self.assertLogs("medicafe_v1.sources.commands", level="INFO") as captured:
            admitted = self.admit(content=(sentinel + "\nnot,a,valid,header\n").encode())
            with self.assertRaises(CommandError):
                self.parse(admitted.delivery_id)
        self.assertNotIn(sentinel, "\n".join(captured.output))
        self.assertEqual(ParseAttempt.objects.get(delivery_id=admitted.delivery_id).reason_code, "invalid_header")
        self.assertEqual(ParseResult.objects.filter(delivery_id=admitted.delivery_id).count(), 0)

    def test_historical_result_requires_current_artifact_verification_before_replay_or_resolution(self):
        content = csv_bytes(synthetic_rows(note="SYNTHETIC_HISTORICAL_RESULT"))
        admitted = self.admit(content=content)
        parsed = self.parse(admitted.delivery_id)
        delivery = self.delivery(admitted.delivery_id)
        observation = self.first_observation(delivery.id)
        path = self.store.root / delivery.artifact.storage_key
        result_count = ParseResult.objects.filter(delivery=delivery).count()
        observation_count = delivery.parseresult_set.get(pk=parsed.parse_result_id).observations.count()
        attempt_count = ParseAttempt.objects.filter(delivery=delivery).count()

        path.unlink()
        with self.assertRaises(CommandError) as unavailable:
            self.parse(delivery.id)
        self.assertEqual(unavailable.exception.reason_code, "artifact_unavailable")
        with self.assertRaises(CommandError) as blocked_resolution:
            resolve_identity(
                actor=self.alpha_user, organization_id=self.alpha.id, observation_id=observation.id,
                request_uuid=uuid.uuid4(), intent=ResolutionIntent(
                    mode="create", reason="Synthetic unavailable artifact",
                    display_name="Synthetic Must Not Exist", service_date="2026-01-15",
                ),
            )
        self.assertEqual(blocked_resolution.exception.reason_code, "artifact_unavailable")
        self.assertEqual(IdentityDecision.objects.filter(observation=observation).count(), 0)

        self.client.force_login(self.alpha_user)
        detail = self.client.get(reverse("delivery_detail", kwargs={
            "organization_id": self.alpha.id, "delivery_id": delivery.id,
        }))
        self.assertContains(detail, "artifact_unavailable")
        self.assertContains(detail, "historical results remain retained")
        worklist = self.client.get(reverse("worklist", kwargs={"organization_id": self.alpha.id}))
        self.assertContains(worklist, "historical f1-v1 result retained")
        self.assertContains(worklist, "artifact_unavailable")

        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        replay = self.parse(delivery.id)
        self.assertEqual(replay.reason_code, "parse_replayed")
        self.assertEqual(replay.parse_result_id, parsed.parse_result_id)
        self.assertEqual(ParseResult.objects.filter(delivery=delivery).count(), result_count)
        self.assertEqual(delivery.parseresult_set.get(pk=parsed.parse_result_id).observations.count(), observation_count)
        self.assertEqual(ParseAttempt.objects.filter(delivery=delivery).count(), attempt_count + 1)


class ResolutionConcurrencyAndDurabilityTests(F1TransactionTestCase):
    def _observation(self):
        admitted = self.admit(content=csv_bytes(synthetic_rows(note="SYNTHETIC_CONCURRENT_IDENTITY")))
        self.parse(admitted.delivery_id)
        return self.first_observation(admitted.delivery_id)

    def _run_resolutions(self, observation, requests_and_intents):
        gate = threading.Barrier(len(requests_and_intents))
        results, errors = [], []

        def worker(request_uuid, intent):
            close_old_connections()
            try:
                actor = User.objects.get(pk=self.alpha_user.pk)
                gate.wait(timeout=15)
                results.append(resolve_identity(
                    actor=actor, organization_id=self.alpha.id, observation_id=observation.id,
                    request_uuid=request_uuid, intent=intent,
                ))
            except Exception as exc:
                errors.append(exc)
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=len(requests_and_intents)) as executor:
            futures = [executor.submit(worker, request_uuid, intent) for request_uuid, intent in requests_and_intents]
            for future in futures:
                future.result(timeout=30)
        return results, errors

    def test_concurrent_identical_retry_and_competing_create_leave_one_canonical_pair(self):
        observation = self._observation()
        request_uuid = uuid.uuid4()
        identical = ResolutionIntent(
            mode="create", reason="Synthetic identical concurrent request",
            display_name="Synthetic Concurrent Patient", service_date="2026-01-15",
        )
        results, errors = self._run_resolutions(observation, [(request_uuid, identical), (request_uuid, identical)])
        self.assertEqual(errors, [])
        self.assertEqual(len(results), 2)
        self.assertEqual(results[0].decision_id, results[1].decision_id)
        self.assertEqual(Patient.objects.filter(organization=self.alpha).count(), 1)
        self.assertEqual(Encounter.objects.filter(organization=self.alpha).count(), 1)

        second_observation = self._observation()
        first = ResolutionIntent(
            mode="create", reason="Synthetic competing first", display_name="Synthetic First",
            service_date="2026-01-16",
        )
        second = ResolutionIntent(
            mode="create", reason="Synthetic competing second", display_name="Synthetic Second",
            service_date="2026-01-17",
        )
        results, errors = self._run_resolutions(
            second_observation, [(uuid.uuid4(), first), (uuid.uuid4(), second)]
        )
        self.assertEqual(len(results), 1)
        self.assertEqual(len(errors), 1)
        self.assertEqual(errors[0].reason_code, "observation_resolution_conflict")
        self.assertEqual(Patient.objects.filter(organization=self.alpha).count(), 2)
        self.assertEqual(Encounter.objects.filter(organization=self.alpha).count(), 2)

    def test_decision_is_visible_from_a_fresh_python_process(self):
        observation = self._observation()
        accepted = resolve_identity(
            actor=self.alpha_user, organization_id=self.alpha.id, observation_id=observation.id,
            request_uuid=uuid.uuid4(), intent=ResolutionIntent(
                mode="create", reason="Synthetic restart evidence", display_name="Synthetic Durable Patient",
                service_date="2026-01-15",
            ),
        )
        database = connection.settings_dict
        environment = os.environ.copy()
        environment.update({
            "PYTHONPATH": str(Path(__file__).resolve().parents[2] / "src"),
            "DJANGO_SETTINGS_MODULE": "medicafe_v1.settings",
            "POSTGRES_DB": database["NAME"],
            "POSTGRES_USER": database["USER"],
            "POSTGRES_PASSWORD": database["PASSWORD"],
            "POSTGRES_HOST": database["HOST"],
            "POSTGRES_PORT": str(database["PORT"]),
        })
        completed = subprocess.run(
            [sys.executable, "-c", (
                "import django;django.setup();"
                "from medicafe_v1.records.models import IdentityDecision;"
                f"d=IdentityDecision.objects.get(pk='{accepted.decision_id}');"
                "print(d.patient_id, d.encounter_id)"
            )],
            check=True, capture_output=True, text=True, env=environment, timeout=20,
        )
        self.assertIn(str(accepted.patient_id), completed.stdout)
        self.assertIn(str(accepted.encounter_id), completed.stdout)

    def test_database_rejects_decision_whose_encounter_belongs_to_another_patient(self):
        observation = self._observation()
        selected_patient = Patient.objects.create(organization=self.alpha, display_name="Synthetic Selected")
        other_patient = Patient.objects.create(organization=self.alpha, display_name="Synthetic Other")
        other_encounter = Encounter.objects.create(
            organization=self.alpha, patient=other_patient, service_date="2026-01-15"
        )
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                IdentityDecision.objects.create(
                    organization=self.alpha, observation=observation, patient=selected_patient,
                    encounter=other_encounter, decided_by=self.alpha_user,
                    reason="Synthetic invalid direct relationship", request_uuid=uuid.uuid4(),
                    input_digest="0" * 64,
                )

    def test_immutable_decision_attempt_and_observation_reject_direct_delete(self):
        observation = self._observation()
        decision = resolve_identity(
            actor=self.alpha_user, organization_id=self.alpha.id, observation_id=observation.id,
            request_uuid=uuid.uuid4(), intent=ResolutionIntent(
                mode="create", reason="Synthetic immutable decision",
                display_name="Synthetic Immutable Patient", service_date="2026-01-15",
            ),
        )
        attempt = ParseAttempt.objects.get(delivery=observation.parse_result.delivery)
        unreferenced_observation = self._observation()
        for model, object_id in (
            (IdentityDecision, decision.decision_id),
            (ParseAttempt, attempt.id),
            (type(unreferenced_observation), unreferenced_observation.id),
        ):
            with self.assertRaises(DatabaseError):
                with transaction.atomic():
                    model.objects.get(pk=object_id).delete()
            self.assertTrue(model.objects.filter(pk=object_id).exists())
