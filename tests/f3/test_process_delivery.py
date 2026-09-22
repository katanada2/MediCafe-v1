from __future__ import annotations

import uuid

import psycopg
from django.test import Client
from django.test import override_settings
from django.urls import reverse
from psycopg import sql

from medicafe_v1.claims.delivery_commands import reconcile_delivery, request_delivery
from medicafe_v1.claims.delivery_adapter import FrozenDelivery, LoopbackReceiverAdapter, RECEIVER_ID
from medicafe_v1.claims.models import ReceiverObservation
from tests.helpers.workflow_boundary_contract import assert_delivery_boundary

from .base import F3TransactionTestCase
from .process_helpers import ReceiverProcess, postgres_kwargs


class ProcessDeliveryTests(F3TransactionTestCase):
    def setUp(self):
        super().setUp()
        self.receiver = ReceiverProcess()

    def tearDown(self):
        self.receiver.stop()
        self.receiver.drop_schema()
        super().tearDown()

    def test_exact_bytes_each_receiver_survive_receiver_and_worker_restart(self):
        self.receiver.start()
        delivered = []
        for version in ("v1", "v2"):
            with self.subTest(version=version):
                _, revision, _ = self.approved_claim(route_version=version)
                requested = request_delivery(
                    actor=self.alpha_user, organization_id=self.alpha.id,
                    request_id=uuid.uuid4(), claim_revision_id=revision.id,
                    expected_envelope_digest=revision.envelope_digest,
                )
                worker = self.receiver.run_worker()
                self.assertEqual(worker.returncode, 0, worker.stderr)
                self.assertIn("receiver_evidence_recorded", worker.stdout)
                observation = ReceiverObservation.objects.get(intent_id=requested.intent_id)
                self.assertTrue(observation.binding_valid)
                self.assertEqual(bytes(observation.received_bytes), bytes(revision.envelope_bytes))
                assert_delivery_boundary(
                    self, intent=observation.intent, expected_state="receiver_accepted",
                    expected_possible_attempts=1, expected_valid_observations=1,
                )
                with psycopg.connect(**postgres_kwargs()) as conn, conn.cursor() as cursor:
                    cursor.execute(sql.SQL("""
                        SELECT received_bytes,envelope_digest,attempt_id,receipt_id
                        FROM {}.accepted_receipt
                        WHERE receiver_version=%s AND organization_id=%s AND delivery_key=%s
                    """).format(sql.Identifier(self.receiver.schema)), (
                        version, self.alpha.id, requested.intent_id,
                    ))
                    stored = cursor.fetchone()
                self.assertIsNotNone(stored)
                self.assertEqual(bytes(stored[0]), bytes(revision.envelope_bytes))
                self.assertEqual(stored[1], revision.envelope_digest)
                self.assertEqual(str(stored[2]), str(observation.reported_attempt_id))
                self.assertEqual(stored[3], observation.receipt_id)
                delivered.append((revision, requested, observation))
        self.receiver.stop()
        self.receiver.start()
        with override_settings(SYNTHETIC_RECEIVER_ENDPOINTS=self.receiver.endpoints):
            adapter = LoopbackReceiverAdapter(timeout=1)
            for revision, requested, original in delivered:
                evidence = adapter.readback(FrozenDelivery(
                    organization_id=str(self.alpha.id), intent_id=str(requested.intent_id),
                    claim_revision_id=str(revision.id), delivery_key=str(requested.intent_id),
                    attempt_id=str(original.reported_attempt_id), receiver_id=RECEIVER_ID,
                    receiver_version=revision.route_version,
                    envelope_digest=revision.envelope_digest,
                    byte_length=len(bytes(revision.envelope_bytes)),
                    payload=bytes(revision.envelope_bytes),
                ))
                self.assertIsNotNone(evidence)
                self.assertEqual(evidence.receipt_id, original.receipt_id)
                self.assertEqual(evidence.reported_attempt_id, str(original.reported_attempt_id))
                self.assertEqual(evidence.delivery_key, str(requested.intent_id))
                self.assertEqual(evidence.received_bytes, bytes(revision.envelope_bytes))


class ReceiverOutageTests(F3TransactionTestCase):
    def setUp(self):
        super().setUp()
        self.receiver = ReceiverProcess()

    def tearDown(self):
        self.receiver.stop()
        self.receiver.drop_schema()
        super().tearDown()

    def test_receiver_outage_has_no_false_completion_resend_or_route_fallback(self):
        claim, revision, _ = self.approved_claim(route_version="v2")
        requested = request_delivery(
            actor=self.alpha_user, organization_id=self.alpha.id,
            request_id=uuid.uuid4(), claim_revision_id=revision.id,
            expected_envelope_digest=revision.envelope_digest,
        )

        unavailable = self.receiver.run_worker()

        self.assertEqual(unavailable.returncode, 0, unavailable.stderr)
        self.assertIn("dispatch_outcome_unknown", unavailable.stdout)
        client = Client()
        client.force_login(self.alpha_user)
        claim_page = client.get(reverse("claim_detail", kwargs={
            "organization_id": self.alpha.id, "claim_id": claim.id,
        }))
        self.assertEqual(claim_page.status_code, 200)
        self.assertContains(claim_page, "Synthetic only")

        self.receiver.start()
        with override_settings(SYNTHETIC_RECEIVER_ENDPOINTS=self.receiver.endpoints):
            reconciled = reconcile_delivery(
                actor=self.alpha_user, organization_id=self.alpha.id,
                intent_id=requested.intent_id,
            )
        self.assertEqual(reconciled.reason_code, "receiver_not_observed")
        self.assertEqual(reconciled.current_status, "uncertain")
        no_work = self.receiver.run_worker()
        self.assertIn("no_delivery_work", no_work.stdout)
        with psycopg.connect(**postgres_kwargs()) as conn, conn.cursor() as cursor:
            cursor.execute(sql.SQL("SELECT count(*) FROM {}.accepted_receipt").format(
                sql.Identifier(self.receiver.schema)
            ))
            self.assertEqual(cursor.fetchone()[0], 0)
