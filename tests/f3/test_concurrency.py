from __future__ import annotations

import threading
import uuid
from concurrent.futures import ThreadPoolExecutor

from django.db import close_old_connections
from django.utils import timezone

from medicafe_v1.claims.delivery_adapter import ReceiverEvidence
from medicafe_v1.claims.delivery_commands import reconcile_delivery, request_delivery
from medicafe_v1.claims.delivery_worker import run_delivery_worker_once
from medicafe_v1.claims.models import DeliveryAttempt, ReceiverObservation

from .base import F3TransactionTestCase
from .test_worker import AcceptedAdapter
from .test_reconciliation import UnknownTransportAdapter


class BlockingAcceptedAdapter(AcceptedAdapter):
    def __init__(self):
        super().__init__()
        self.entered = threading.Event()
        self.release = threading.Event()

    def send(self, frozen, *, test_mode=None):
        self.entered.set()
        if not self.release.wait(timeout=5):
            raise RuntimeError("test release timeout")
        return super().send(frozen, test_mode=test_mode)


class BarrierReadbackAdapter:
    timeout = 0.1

    def __init__(self, barrier):
        self.barrier = barrier

    def readback(self, frozen):
        self.barrier.wait(timeout=5)
        return ReceiverEvidence(
            state="accepted", receiver_id=frozen.receiver_id,
            receiver_version=frozen.receiver_version,
            organization_id=frozen.organization_id, intent_id=frozen.intent_id,
            claim_revision_id=frozen.claim_revision_id, delivery_key=frozen.delivery_key,
            receipt_id="concurrent-shared-receipt",
            reported_attempt_id=frozen.attempt_id,
            envelope_digest=frozen.envelope_digest, byte_length=frozen.byte_length,
            received_bytes=frozen.payload, no_acceptance_guaranteed=False,
            observed_at=timezone.now().isoformat(),
        )


class WorkerFenceRaceTests(F3TransactionTestCase):
    def test_competing_workers_and_duplicate_pickup_create_one_dispatch_marker(self):
        _, revision, _ = self.approved_claim()
        requested = request_delivery(
            actor=self.alpha_user, organization_id=self.alpha.id,
            request_id=uuid.uuid4(), claim_revision_id=revision.id,
            expected_envelope_digest=revision.envelope_digest,
        )
        adapter = BlockingAcceptedAdapter()

        def first_worker():
            close_old_connections()
            try:
                return run_delivery_worker_once(
                    worker_id="competing-1", lease_seconds=10, adapter=adapter
                )
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(first_worker)
            self.assertTrue(adapter.entered.wait(timeout=5))
            second = run_delivery_worker_once(
                worker_id="competing-2", lease_seconds=10, adapter=AcceptedAdapter()
            )
            adapter.release.set()
            first = future.result(timeout=10)

        self.assertEqual(second.reason_code, "no_delivery_work")
        self.assertEqual(first.reason_code, "receiver_evidence_recorded")
        self.assertEqual(
            DeliveryAttempt.objects.filter(
                intent_id=requested.intent_id, possible_dispatch=True
            ).count(), 1,
        )

    def test_concurrent_same_receipt_different_intents_yields_one_binding_and_one_conflict(self):
        requested = []
        for index in range(2):
            _, revision, _ = self.approved_claim()
            item = request_delivery(
                actor=self.alpha_user, organization_id=self.alpha.id,
                request_id=uuid.uuid4(), claim_revision_id=revision.id,
                expected_envelope_digest=revision.envelope_digest,
            )
            run_delivery_worker_once(
                worker_id=f"uncertain-{index}", lease_seconds=10,
                adapter=UnknownTransportAdapter(),
            )
            requested.append(item)
        barrier = threading.Barrier(2)

        def reconcile(item):
            close_old_connections()
            try:
                return reconcile_delivery(
                    actor=self.alpha_user, organization_id=self.alpha.id,
                    intent_id=item.intent_id, adapter=BarrierReadbackAdapter(barrier),
                )
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(reconcile, requested))

        self.assertEqual(
            sorted(result.reason_code for result in results),
            ["receiver_evidence_conflict", "receiver_evidence_recorded"],
        )
        observations = ReceiverObservation.objects.filter(
            receipt_id="concurrent-shared-receipt"
        )
        self.assertEqual(observations.count(), 2)
        self.assertEqual(observations.filter(binding_valid=True).count(), 1)
        self.assertEqual(observations.filter(observed_state="conflict").count(), 1)
