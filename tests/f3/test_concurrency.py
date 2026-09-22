from __future__ import annotations

import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor

from django.db import close_old_connections
from django.utils import timezone

from medicafe_v1.claims.delivery_adapter import ReceiverEvidence
from medicafe_v1.claims.delivery_commands import (
    reconcile_delivery, request_delivery, retry_idempotent_delivery,
)
from medicafe_v1.claims.delivery_worker import _finish_with_token, run_delivery_worker_once
from medicafe_v1.claims.models import (
    AttemptOutcome, ClaimsCommandReceipt, DeliveryAttempt, DeliveryWork,
    ReceiverObservation,
)

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

    def test_expired_worker_can_physically_finish_but_not_retake_newer_fence(self):
        _, revision, _ = self.approved_claim()
        requested = request_delivery(
            actor=self.alpha_user, organization_id=self.alpha.id,
            request_id=uuid.uuid4(), claim_revision_id=revision.id,
            expected_envelope_digest=revision.envelope_digest,
        )
        adapter = BlockingAcceptedAdapter()

        def delayed_worker():
            close_old_connections()
            try:
                return run_delivery_worker_once(
                    worker_id="delayed-authorized", lease_seconds=1, adapter=adapter,
                )
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(delayed_worker)
            self.assertTrue(adapter.entered.wait(timeout=5))
            deadline = time.monotonic() + 2
            while DeliveryWork.objects.get(id=requested.work_id).lease_expires_at > timezone.now():
                if time.monotonic() >= deadline:
                    self.fail("delayed worker lease did not expire")
                time.sleep(0.02)
            recovered = run_delivery_worker_once(
                worker_id="recovery-fence", lease_seconds=2, adapter=AcceptedAdapter(),
            )
            adapter.release.set()
            delayed = future.result(timeout=10)

        self.assertEqual(recovered.reason_code, "dispatch_outcome_unknown")
        self.assertEqual(delayed.reason_code, "receiver_evidence_recorded")
        attempt = DeliveryAttempt.objects.get(intent_id=requested.intent_id)
        self.assertEqual(attempt.outcome.kind, AttemptOutcome.UNKNOWN)
        self.assertEqual(len(adapter.sent), 1)
        observation = ReceiverObservation.objects.get(intent_id=requested.intent_id)
        self.assertTrue(observation.binding_valid)
        work = DeliveryWork.objects.get(id=requested.work_id)
        self.assertEqual(work.state, DeliveryWork.STATE_FINISHED)
        self.assertEqual(work.blocking_reason, "dispatch_outcome_unknown")

    def test_concurrent_retry_commands_schedule_once(self):
        _, revision, _ = self.approved_claim()
        requested = request_delivery(
            actor=self.alpha_user, organization_id=self.alpha.id,
            request_id=uuid.uuid4(), claim_revision_id=revision.id,
            expected_envelope_digest=revision.envelope_digest,
        )
        run_delivery_worker_once(
            worker_id="retry-uncertain", lease_seconds=2,
            adapter=UnknownTransportAdapter(),
        )
        attempt = DeliveryAttempt.objects.get(intent_id=requested.intent_id)
        barrier = threading.Barrier(2)

        def retry():
            close_old_connections()
            try:
                barrier.wait(timeout=5)
                return retry_idempotent_delivery(
                    actor=self.alpha_user, organization_id=self.alpha.id,
                    request_id=uuid.uuid4(), intent_id=requested.intent_id,
                    expected_attempt_id=attempt.id,
                )
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _index: retry(), range(2)))

        self.assertEqual(
            sorted(result.reason_code for result in results),
            ["delivery_retry_already_scheduled", "delivery_retry_scheduled"],
        )
        receipts = ClaimsCommandReceipt.objects.filter(
            command_kind="retry_idempotent_delivery",
            result_delivery_intent_id=requested.intent_id,
        )
        self.assertEqual(receipts.count(), 2)
        scheduled = receipts.get(result_code="delivery_retry_scheduled")
        self.assertEqual(
            DeliveryWork.objects.get(id=requested.work_id).scheduled_authorization_receipt_id,
            scheduled.id,
        )

    def test_stale_completion_cannot_finish_newer_unmarked_lease(self):
        _, revision, _ = self.approved_claim()
        requested = request_delivery(
            actor=self.alpha_user, organization_id=self.alpha.id,
            request_id=uuid.uuid4(), claim_revision_id=revision.id,
            expected_envelope_digest=revision.envelope_digest,
        )
        with self.assertRaises(RuntimeError):
            run_delivery_worker_once(
                worker_id="stale-owner", lease_seconds=1, adapter=AcceptedAdapter(),
                before_membership_lock=lambda: (_ for _ in ()).throw(RuntimeError("stop")),
            )
        stale_work = DeliveryWork.objects.get(id=requested.work_id)
        deadline = time.monotonic() + 2
        while stale_work.lease_expires_at > timezone.now():
            if time.monotonic() >= deadline:
                self.fail("stale lease did not expire")
            time.sleep(0.02)

        entered = threading.Event()
        release = threading.Event()

        def replacement_worker():
            close_old_connections()
            try:
                return run_delivery_worker_once(
                    worker_id="new-owner", lease_seconds=5, adapter=AcceptedAdapter(),
                    before_membership_lock=lambda: (
                        entered.set(),
                        release.wait(timeout=5) or (_ for _ in ()).throw(
                            RuntimeError("replacement release timeout")
                        ),
                    ),
                )
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(replacement_worker)
            self.assertTrue(entered.wait(timeout=5))
            current = DeliveryWork.objects.get(id=requested.work_id)
            self.assertEqual(current.fencing_generation, stale_work.fencing_generation + 1)
            stale_finish = _finish_with_token(
                work=stale_work, worker_id="stale-owner",
                generation=stale_work.fencing_generation,
                state=DeliveryWork.STATE_FINISHED, reason="stale_completion",
            )
            release.set()
            replacement = future.result(timeout=10)

        self.assertEqual(stale_finish, 0)
        self.assertEqual(replacement.reason_code, "receiver_evidence_recorded")

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
