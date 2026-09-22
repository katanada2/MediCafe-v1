from __future__ import annotations

import time
import uuid

from django.utils import timezone

from medicafe_v1.access.models import Membership
from medicafe_v1.claims.delivery_adapter import ReceiverEvidence, TransportResult
from medicafe_v1.claims.delivery_commands import request_delivery
from medicafe_v1.claims.delivery_worker import run_delivery_worker_once
from medicafe_v1.claims.models import AttemptOutcome, DeliveryAttempt, DeliveryWork
from medicafe_v1.sources.domain import CommandError

from .base import F3TransactionTestCase


class AcceptedAdapter:
    timeout = 0.1

    def __init__(self):
        self.sent = []

    def validate_configuration(self, receiver_id, version):
        return None

    def send(self, frozen, *, test_mode=None):
        self.sent.append(frozen)
        return TransportResult("accepted", "receiver_response")

    def readback(self, frozen):
        return ReceiverEvidence(
            state="accepted", receiver_id=frozen.receiver_id,
            receiver_version=frozen.receiver_version,
            organization_id=frozen.organization_id, intent_id=frozen.intent_id,
            claim_revision_id=frozen.claim_revision_id,
            delivery_key=frozen.delivery_key, receipt_id=f"receipt-{frozen.attempt_id}",
            reported_attempt_id=frozen.attempt_id,
            envelope_digest=frozen.envelope_digest, byte_length=frozen.byte_length,
            received_bytes=frozen.payload, no_acceptance_guaranteed=False,
            observed_at=timezone.now().isoformat(),
        )


class TransientPreflightAdapter(AcceptedAdapter):
    def validate_configuration(self, receiver_id, version):
        raise CommandError("receiver_preflight_transient")


class CrashSignal(Exception):
    pass


class WorkerPreflightTests(F3TransactionTestCase):
    def request(self):
        _, revision, _ = self.approved_claim()
        result = request_delivery(
            actor=self.alpha_user, organization_id=self.alpha.id,
            request_id=uuid.uuid4(), claim_revision_id=revision.id,
            expected_envelope_digest=revision.envelope_digest,
        )
        return revision, result

    def test_exact_evidence_finishes_one_possible_dispatch_attempt(self):
        revision, requested = self.request()
        adapter = AcceptedAdapter()

        result = run_delivery_worker_once(
            worker_id="accepted-worker", lease_seconds=2, adapter=adapter
        )

        self.assertEqual(result.reason_code, "receiver_evidence_recorded")
        self.assertEqual(len(adapter.sent), 1)
        self.assertEqual(adapter.sent[0].payload, bytes(revision.envelope_bytes))
        attempt = DeliveryAttempt.objects.get(id=result.attempt_id)
        self.assertTrue(attempt.possible_dispatch)
        self.assertEqual(attempt.outcome.kind, AttemptOutcome.RECEIVER_ACCEPTED)
        self.assertEqual(DeliveryWork.objects.get(id=requested.work_id).state, "finished")

    def test_transient_preflight_limit_records_three_definitely_unsent_attempts(self):
        _, requested = self.request()
        adapter = TransientPreflightAdapter()

        results = [run_delivery_worker_once(
            worker_id=f"preflight-{index}", lease_seconds=2, adapter=adapter
        ) for index in range(3)]

        self.assertEqual(
            [item.reason_code for item in results],
            ["preflight_retry_scheduled", "preflight_retry_scheduled", "preflight_retry_limit"],
        )
        attempts = DeliveryAttempt.objects.filter(intent_id=requested.intent_id).order_by("ordinal")
        self.assertEqual(attempts.count(), 3)
        self.assertFalse(attempts.filter(possible_dispatch=True).exists())
        self.assertTrue(all(item.outcome.kind == AttemptOutcome.PRE_DISPATCH_FAILED for item in attempts))
        work = DeliveryWork.objects.get(id=requested.work_id)
        self.assertEqual((work.state, work.safe_preflight_failures), ("blocked", 3))
        self.assertEqual(adapter.sent, [])

    def test_revoked_effective_authorizer_blocks_before_marker(self):
        _, requested = self.request()
        Membership.objects.filter(
            organization=self.alpha, user=self.alpha_user
        ).update(is_active=False)
        adapter = AcceptedAdapter()

        result = run_delivery_worker_once(
            worker_id="revoked-worker", lease_seconds=2, adapter=adapter
        )

        self.assertEqual(result.reason_code, "delivery_blocked")
        attempt = DeliveryAttempt.objects.get(intent_id=requested.intent_id)
        self.assertFalse(attempt.possible_dispatch)
        self.assertEqual(attempt.outcome.reason, "dispatch_authorizer_inactive")
        self.assertEqual(adapter.sent, [])

    def test_expired_marker_recovers_unknown_without_resend(self):
        _, requested = self.request()
        adapter = AcceptedAdapter()
        with self.assertRaises(CrashSignal):
            run_delivery_worker_once(
                worker_id="crash-worker", lease_seconds=1, adapter=adapter,
                after_marker=lambda frozen: (_ for _ in ()).throw(CrashSignal()),
            )
        attempt = DeliveryAttempt.objects.get(intent_id=requested.intent_id)
        self.assertFalse(AttemptOutcome.objects.filter(attempt=attempt).exists())
        deadline = time.monotonic() + 2
        while DeliveryWork.objects.get(id=requested.work_id).lease_expires_at > timezone.now():
            if time.monotonic() >= deadline:
                self.fail("delivery lease did not expire within bounded wait")
            time.sleep(0.02)

        recovered_adapter = AcceptedAdapter()
        recovered = run_delivery_worker_once(
            worker_id="recovery-worker", lease_seconds=2, adapter=recovered_adapter
        )

        self.assertEqual(recovered.reason_code, "dispatch_outcome_unknown")
        self.assertEqual(AttemptOutcome.objects.get(attempt=attempt).kind, AttemptOutcome.UNKNOWN)
        self.assertEqual(recovered_adapter.sent, [])
        self.assertEqual(DeliveryAttempt.objects.filter(intent_id=requested.intent_id).count(), 1)
