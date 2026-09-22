from __future__ import annotations

import uuid
import tempfile
import time
from pathlib import Path

import psycopg
from psycopg import sql
from django.test import override_settings
from django.utils import timezone

from medicafe_v1.claims.delivery_adapter import LoopbackReceiverAdapter
from medicafe_v1.claims.delivery_commands import (
    reconcile_delivery, request_delivery, retry_idempotent_delivery,
)
from medicafe_v1.claims.models import (
    AttemptOutcome, DeliveryAttempt, DeliveryWork, ReceiverObservation,
)
from medicafe_v1.sources.domain import CommandError

from .base import F3TransactionTestCase
from .process_helpers import ReceiverProcess, postgres_kwargs


class CrashWindowProcessTests(F3TransactionTestCase):
    def setUp(self):
        super().setUp()
        self.receiver = ReceiverProcess()
        self.receiver.start()

    def tearDown(self):
        self.receiver.stop()
        self.receiver.drop_schema()
        super().tearDown()

    def request(self, version):
        _, revision, _ = self.approved_claim(route_version=version)
        return request_delivery(
            actor=self.alpha_user, organization_id=self.alpha.id,
            request_id=uuid.uuid4(), claim_revision_id=revision.id,
            expected_envelope_digest=revision.envelope_digest,
        )

    def ledger_count(self, version, intent_id):
        with psycopg.connect(**postgres_kwargs()) as conn, conn.cursor() as cursor:
            cursor.execute(sql.SQL("""
                SELECT count(*) FROM {}.accepted_receipt
                WHERE receiver_version=%s AND organization_id=%s AND delivery_key=%s
            """).format(sql.Identifier(self.receiver.schema)), (
                version, self.alpha.id, intent_id,
            ))
            return cursor.fetchone()[0]

    def terminate_at_barrier(self, *, phase, test_mode=None):
        with tempfile.TemporaryDirectory() as directory:
            barrier = Path(directory) / "reached"
            process = self.receiver.start_barrier_worker(
                barrier_path=barrier, phase=phase, test_mode=test_mode,
            )
            deadline = time.monotonic() + 10
            try:
                while not barrier.exists():
                    if process.poll() is not None:
                        stdout, stderr = process.communicate(timeout=1)
                        self.fail(
                            f"worker exited before {phase}: {process.returncode} {stdout} {stderr}"
                        )
                    if time.monotonic() >= deadline:
                        self.fail(f"worker did not reach {phase} barrier")
                    time.sleep(0.02)
                process.terminate()
                process.wait(timeout=5)
            finally:
                if process.poll() is None:
                    process.kill()
                    process.wait(timeout=5)

    def wait_for_lease_expiry(self, work_id):
        deadline = time.monotonic() + 4
        while DeliveryWork.objects.get(id=work_id).lease_expires_at > timezone.now():
            if time.monotonic() >= deadline:
                self.fail("subprocess delivery lease did not expire")
            time.sleep(0.02)

    def test_kill_after_marker_before_call_recovers_unknown_without_send(self):
        requested = self.request("v1")
        self.terminate_at_barrier(phase="after_marker")
        attempt = DeliveryAttempt.objects.get(intent_id=requested.intent_id)
        self.assertFalse(AttemptOutcome.objects.filter(attempt=attempt).exists())
        self.assertEqual(self.ledger_count("v1", requested.intent_id), 0)
        self.wait_for_lease_expiry(requested.work_id)

        recovered = self.receiver.run_worker()

        self.assertEqual(recovered.returncode, 0, recovered.stderr)
        self.assertIn("dispatch_outcome_unknown", recovered.stdout)
        self.assertEqual(self.ledger_count("v1", requested.intent_id), 0)
        self.assertEqual(attempt.outcome.kind, AttemptOutcome.UNKNOWN)

    def test_kill_after_receiver_commit_before_outcome_recovers_then_reconciles(self):
        requested = self.request("v1")
        self.terminate_at_barrier(phase="after_transport")
        attempt = DeliveryAttempt.objects.get(intent_id=requested.intent_id)
        self.assertFalse(AttemptOutcome.objects.filter(attempt=attempt).exists())
        self.assertEqual(self.ledger_count("v1", requested.intent_id), 1)
        self.wait_for_lease_expiry(requested.work_id)

        recovered = self.receiver.run_worker()
        self.assertEqual(recovered.returncode, 0, recovered.stderr)
        self.assertIn("dispatch_outcome_unknown", recovered.stdout)
        with override_settings(SYNTHETIC_RECEIVER_ENDPOINTS=self.receiver.endpoints):
            reconciled = reconcile_delivery(
                actor=self.alpha_user, organization_id=self.alpha.id,
                intent_id=requested.intent_id, adapter=LoopbackReceiverAdapter(timeout=1),
            )

        self.assertEqual(reconciled.reason_code, "receiver_evidence_recorded")
        attempt.refresh_from_db()
        self.assertEqual(attempt.outcome.kind, AttemptOutcome.UNKNOWN)
        observation = ReceiverObservation.objects.get(intent_id=requested.intent_id)
        self.assertTrue(observation.binding_valid)
        self.assertEqual(observation.reported_attempt_id, attempt.id)
        self.assertEqual(self.ledger_count("v1", requested.intent_id), 1)

    def test_v1_commit_response_loss_then_explicit_retry_has_one_durable_acceptance(self):
        requested = self.request("v1")
        pending = self.receiver.query_state(requested.intent_id)
        self.assertEqual((pending["state"], pending["attempts"]), ("pending", 0))
        crashed = self.receiver.run_test_worker(
            test_mode="commit_acceptance_then_drop_response"
        )
        self.assertEqual(crashed.returncode, 0, crashed.stderr)
        self.assertIn("dispatch_outcome_unknown", crashed.stdout)
        original = DeliveryAttempt.objects.get(intent_id=requested.intent_id)
        self.assertEqual(original.outcome.kind, AttemptOutcome.UNKNOWN)
        uncertain = self.receiver.query_state(requested.intent_id)
        self.assertEqual(
            (uncertain["state"], uncertain["attempts"], uncertain["outcomes"]),
            ("uncertain", 1, 1),
        )
        self.assertEqual(self.ledger_count("v1", requested.intent_id), 1)
        retry_idempotent_delivery(
            actor=self.alpha_user, organization_id=self.alpha.id,
            request_id=uuid.uuid4(), intent_id=requested.intent_id,
            expected_attempt_id=original.id,
        )

        retried = self.receiver.run_worker()

        self.assertEqual(retried.returncode, 0, retried.stderr)
        self.assertIn("receiver_evidence_recorded", retried.stdout)
        self.assertEqual(self.ledger_count("v1", requested.intent_id), 1)
        observation = ReceiverObservation.objects.get(intent_id=requested.intent_id)
        self.assertEqual(observation.reported_attempt_id, original.id)
        self.assertEqual(DeliveryAttempt.objects.filter(intent_id=requested.intent_id).count(), 2)
        accepted = self.receiver.query_state(requested.intent_id)
        self.assertEqual(
            (accepted["state"], accepted["attempts"], accepted["observations"]),
            ("receiver_accepted", 2, 1),
        )

    def test_v2_commit_response_loss_stays_unknown_and_never_posts_again(self):
        requested = self.request("v2")
        crashed = self.receiver.run_test_worker(
            test_mode="commit_acceptance_then_drop_response"
        )
        self.assertEqual(crashed.returncode, 0, crashed.stderr)
        self.assertIn("dispatch_outcome_unknown", crashed.stdout)
        attempt = DeliveryAttempt.objects.get(intent_id=requested.intent_id)
        self.assertEqual(self.ledger_count("v2", requested.intent_id), 1)
        with self.assertRaises(CommandError) as raised:
            retry_idempotent_delivery(
                actor=self.alpha_user, organization_id=self.alpha.id,
                request_id=uuid.uuid4(), intent_id=requested.intent_id,
                expected_attempt_id=attempt.id,
            )
        self.assertEqual(raised.exception.reason_code, "receiver_retry_not_idempotent")

        no_work = self.receiver.run_worker()
        self.assertEqual(no_work.returncode, 0, no_work.stderr)
        self.assertIn("no_delivery_work", no_work.stdout)
        self.assertEqual(self.ledger_count("v2", requested.intent_id), 1)
