from __future__ import annotations

import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

from django.db import close_old_connections

from medicafe_v1.records.commands import ResolutionIntent, resolve_identity
from medicafe_v1.records.models import IdentityDecision, Patient
from medicafe_v1.sources import commands as source_commands
from medicafe_v1.sources.domain import CommandError
from medicafe_v1.sources.models import Observation, ParseAttempt, ParseResult
from medicafe_v1.sources.parsers import parse as parse_source

from tests.fixtures.synthetic_inputs import csv_bytes, synthetic_rows
from tests.f1.base import F1TestCase, F1TransactionTestCase
from tests.helpers.workflow_boundary_contract import assert_parse_boundary


class ParseLifecycleTests(F1TestCase):
    def test_success_replay_has_one_result_observation_set_and_no_new_attempt(self):
        admitted = self.admit(content=csv_bytes(synthetic_rows(note="SYNTHETIC_PARSE_REPLAY")))
        first = self.parse(admitted.delivery_id)
        self.assertEqual(first.reason_code, "parse_succeeded")
        delivery = self.delivery(admitted.delivery_id)
        result = assert_parse_boundary(
            self, delivery=delivery, parser_version="f1-v1", expected_observations=1,
            expected_attempts=1, expected_successes=1,
        )
        self.assertEqual(result.observations.first().raw_values["note"], "SYNTHETIC_PARSE_REPLAY")
        self.assertEqual(Patient.objects.filter(organization=self.alpha).count(), 0)

        replay = self.parse(admitted.delivery_id)
        self.assertEqual(replay.reason_code, "parse_replayed")
        self.assertEqual(replay.parse_result_id, first.parse_result_id)
        assert_parse_boundary(
            self, delivery=delivery, parser_version="f1-v1", expected_observations=1,
            expected_attempts=1, expected_successes=1,
        )

    def test_failed_attempt_retries_replays_and_keeps_version_history(self):
        content = csv_bytes(synthetic_rows(note="SYNTHETIC_RETRY_SENTINEL"))
        admitted = self.admit(content=content)
        calls = 0

        def fail_once(payload, media_type):
            nonlocal calls
            calls += 1
            if calls == 1:
                raise CommandError("synthetic_transient_parse_failure")
            return parse_source(payload, media_type)

        with patch("medicafe_v1.sources.commands.parse", side_effect=fail_once):
            with self.assertRaises(CommandError) as failed:
                self.parse(admitted.delivery_id)
            self.assertEqual(failed.exception.reason_code, "synthetic_transient_parse_failure")
            failed_state = assert_parse_boundary(
                self, delivery=self.delivery(admitted.delivery_id), parser_version="f1-v1",
                expected_observations=0, expected_attempts=1, expected_successes=0,
            )
            self.assertIsNone(failed_state)

            retried = self.parse(admitted.delivery_id)
            self.assertEqual(retried.reason_code, "parse_succeeded")

        replay = self.parse(admitted.delivery_id)
        self.assertEqual(replay.reason_code, "parse_replayed")
        delivery = self.delivery(admitted.delivery_id)
        result = assert_parse_boundary(
            self, delivery=delivery, parser_version="f1-v1", expected_observations=1,
            expected_attempts=2, expected_successes=1,
        )
        self.assertEqual(result.id, retried.parse_result_id)
        self.assertEqual(
            list(ParseAttempt.objects.filter(delivery=delivery).order_by("started_at", "ended_at").values_list("reason_code", flat=True)),
            ["synthetic_transient_parse_failure", "parse_succeeded"],
        )

        resolved = resolve_identity(
            actor=self.alpha_user,
            organization_id=self.alpha.id,
            observation_id=Observation.objects.get(parse_result=result).id,
            request_uuid=uuid.uuid4(),
            intent=ResolutionIntent(
                mode="create", reason="Synthetic operator review", display_name="Synthetic retry patient",
                alias_namespace="synthetic", alias_value="000042", service_date="2026-01-15",
            ),
        )
        self.assertEqual(IdentityDecision.objects.filter(organization=self.alpha).count(), 1)

        versioned = self.parse(admitted.delivery_id, parser_version="f1-v2-test")
        self.assertEqual(versioned.reason_code, "parse_succeeded")
        self.assertEqual(ParseResult.objects.filter(delivery=delivery).count(), 2)
        self.assertEqual(IdentityDecision.objects.get(id=resolved.decision_id).patient_id, resolved.patient_id)
        self.assertEqual(
            IdentityDecision.objects.filter(observation__parse_result__parser_version="f1-v2-test").count(), 0,
        )

    def test_newer_parser_failure_does_not_demote_older_success(self):
        admitted = self.admit(content=csv_bytes(synthetic_rows(note="SYNTHETIC_VERSION_HISTORY")))
        self.parse(admitted.delivery_id, parser_version="f1-v1")

        with patch("medicafe_v1.sources.commands.parse", side_effect=CommandError("synthetic_v2_failure")):
            with self.assertRaises(CommandError) as failed:
                self.parse(admitted.delivery_id, parser_version="f1-v2-test")
        self.assertEqual(failed.exception.reason_code, "synthetic_v2_failure")
        delivery = self.delivery(admitted.delivery_id)
        assert_parse_boundary(
            self, delivery=delivery, parser_version="f1-v1", expected_observations=1,
            expected_attempts=1, expected_successes=1,
        )
        assert_parse_boundary(
            self, delivery=delivery, parser_version="f1-v2-test", expected_observations=0,
            expected_attempts=1, expected_successes=0,
        )


class ParseConcurrencyTests(F1TransactionTestCase):
    def _run_two_parses(self, delivery_id, *, parser_version="f1-v1", failing_second=False):
        gate = threading.Barrier(2)
        call_lock = threading.Lock()
        call_count = 0
        original = parse_source

        def synchronized_parse(payload, media_type):
            nonlocal call_count
            with call_lock:
                call_count += 1
                call_number = call_count
            rows = original(payload, media_type)
            gate.wait(timeout=15)
            if failing_second and call_number == 2:
                raise CommandError("synthetic_concurrent_failure")
            return rows

        results = []
        errors = []

        def worker():
            close_old_connections()
            try:
                from medicafe_v1.access.models import User
                results.append(source_commands.parse_delivery(
                    actor=User.objects.get(pk=self.alpha_user.pk),
                    organization_id=self.alpha.id,
                    delivery_id=delivery_id,
                    parser_version=parser_version,
                    artifact_store=self.store,
                ))
            except Exception as exc:  # surfaced below with both thread outcomes
                errors.append(exc)
            finally:
                close_old_connections()

        with patch("medicafe_v1.sources.commands.parse", side_effect=synchronized_parse):
            with ThreadPoolExecutor(max_workers=2) as executor:
                futures = [executor.submit(worker) for _ in range(2)]
                for future in futures:
                    future.result(timeout=30)
        return results, errors

    def test_two_successful_computations_record_two_attempts_but_one_canonical_result(self):
        admitted = self.admit(content=csv_bytes(synthetic_rows(note="SYNTHETIC_RACE_SUCCESS")))
        results, errors = self._run_two_parses(admitted.delivery_id)

        self.assertEqual(errors, [])
        self.assertEqual(len(results), 2)
        self.assertTrue(all(result.reason_code == "parse_succeeded" for result in results))
        self.assertEqual(results[0].parse_result_id, results[1].parse_result_id)
        assert_parse_boundary(
            self, delivery=self.delivery(admitted.delivery_id), parser_version="f1-v1",
            expected_observations=1, expected_attempts=2, expected_successes=2,
        )

    def test_concurrent_failure_is_history_and_cannot_demote_success(self):
        admitted = self.admit(content=csv_bytes(synthetic_rows(note="SYNTHETIC_RACE_FAILURE")))
        results, errors = self._run_two_parses(admitted.delivery_id, failing_second=True)

        self.assertEqual(len(errors), 1)
        self.assertEqual(errors[0].reason_code, "synthetic_concurrent_failure")
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].reason_code, "parse_succeeded")
        delivery = self.delivery(admitted.delivery_id)
        assert_parse_boundary(
            self, delivery=delivery, parser_version="f1-v1", expected_observations=1,
            expected_attempts=2, expected_successes=1,
        )
        self.assertEqual(
            ParseAttempt.objects.filter(delivery=delivery, succeeded=False).values_list("reason_code", flat=True).get(),
            "synthetic_concurrent_failure",
        )
        self.assertEqual(ParseResult.objects.filter(delivery=delivery, parser_version="f1-v1").count(), 1)
