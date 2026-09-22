from __future__ import annotations

import uuid

from django.utils import timezone

from medicafe_v1.claims.delivery_adapter import ReceiverEvidence, TransportResult
from medicafe_v1.claims.delivery_commands import (
    reconcile_delivery, request_delivery, retry_idempotent_delivery,
)
from medicafe_v1.claims.delivery_worker import run_delivery_worker_once
from medicafe_v1.claims.models import (
    AttemptOutcome, DeliveryAttempt, DeliveryIntent, ReceiverObservation,
)
from medicafe_v1.claims.queries import delivery_effect_state
from medicafe_v1.sources.domain import CommandError

from .base import F3TransactionTestCase


class UnknownTransportAdapter:
    timeout = 0.1

    def validate_configuration(self, receiver_id, version):
        return None

    def send(self, frozen, *, test_mode=None):
        return TransportResult("unknown", "response_lost")


class ReadbackAdapter:
    timeout = 0.1

    def __init__(self, evidence):
        self.evidence = evidence
        self.sent = []

    def validate_configuration(self, receiver_id, version):
        return None

    def send(self, frozen, *, test_mode=None):
        self.sent.append(frozen)
        return TransportResult("accepted", "receiver_response")

    def readback(self, frozen):
        return self.evidence(frozen) if callable(self.evidence) else self.evidence


def accepted_evidence(frozen, *, reported_attempt_id=None, receipt_id=None,
                      payload=None):
    received = frozen.payload if payload is None else payload
    return ReceiverEvidence(
        state="accepted", receiver_id=frozen.receiver_id,
        receiver_version=frozen.receiver_version,
        organization_id=frozen.organization_id, intent_id=frozen.intent_id,
        claim_revision_id=frozen.claim_revision_id, delivery_key=frozen.delivery_key,
        receipt_id=receipt_id or f"receipt-{frozen.intent_id}",
        reported_attempt_id=reported_attempt_id or frozen.attempt_id,
        envelope_digest=frozen.envelope_digest, byte_length=frozen.byte_length,
        received_bytes=received, no_acceptance_guaranteed=False,
        observed_at=timezone.now().isoformat(),
    )


class ReconciliationEvidenceTests(F3TransactionTestCase):
    def uncertain_intent(self, *, version="v1"):
        _, revision, _ = self.approved_claim(route_version=version)
        requested = request_delivery(
            actor=self.alpha_user, organization_id=self.alpha.id,
            request_id=uuid.uuid4(), claim_revision_id=revision.id,
            expected_envelope_digest=revision.envelope_digest,
        )
        result = run_delivery_worker_once(
            worker_id=f"unknown-{version}", lease_seconds=2,
            adapter=UnknownTransportAdapter(),
        )
        self.assertEqual(result.reason_code, "dispatch_outcome_unknown")
        attempt = DeliveryAttempt.objects.get(id=result.attempt_id)
        return revision, requested, attempt

    def test_late_acceptance_supplements_immutable_unknown_and_duplicate_replays(self):
        revision, requested, attempt = self.uncertain_intent()
        frozen_evidence = lambda frozen: accepted_evidence(
            frozen, reported_attempt_id=str(attempt.id)
        )
        adapter = ReadbackAdapter(frozen_evidence)

        first = reconcile_delivery(
            actor=self.alpha_user, organization_id=self.alpha.id,
            intent_id=requested.intent_id, adapter=adapter,
        )
        second = reconcile_delivery(
            actor=self.alpha_user, organization_id=self.alpha.id,
            intent_id=requested.intent_id, adapter=adapter,
        )

        self.assertEqual(first.reason_code, "receiver_evidence_recorded")
        self.assertEqual(second.reason_code, "receiver_evidence_recorded")
        attempt.refresh_from_db()
        self.assertEqual(attempt.outcome.kind, AttemptOutcome.UNKNOWN)
        self.assertEqual(attempt.outcome.reason, "response_lost")
        self.assertEqual(ReceiverObservation.objects.filter(intent_id=requested.intent_id).count(), 1)
        self.assertEqual(
            delivery_effect_state(DeliveryIntent.objects.get(id=requested.intent_id)),
            "receiver_accepted",
        )
        self.assertEqual(bytes(revision.envelope_bytes), bytes(
            ReceiverObservation.objects.get(intent_id=requested.intent_id).received_bytes
        ))

    def test_v1_retry_preserves_key_and_original_attempt_attribution(self):
        _, requested, original = self.uncertain_intent(version="v1")
        retry = retry_idempotent_delivery(
            actor=self.alpha_user, organization_id=self.alpha.id,
            request_id=uuid.uuid4(), intent_id=requested.intent_id,
            expected_attempt_id=original.id,
        )
        adapter = ReadbackAdapter(lambda frozen: accepted_evidence(
            frozen, reported_attempt_id=str(original.id)
        ))

        delivered = run_delivery_worker_once(
            worker_id="v1-retry", lease_seconds=2, adapter=adapter
        )

        self.assertEqual(retry.reason_code, "delivery_retry_scheduled")
        self.assertEqual(delivered.reason_code, "receiver_evidence_recorded")
        self.assertEqual(len(adapter.sent), 1)
        self.assertEqual(adapter.sent[0].delivery_key, str(requested.intent_id))
        self.assertNotEqual(adapter.sent[0].attempt_id, str(original.id))
        observation = ReceiverObservation.objects.get(intent_id=requested.intent_id)
        self.assertEqual(observation.reported_attempt_id, original.id)
        self.assertEqual(DeliveryAttempt.objects.filter(intent_id=requested.intent_id).count(), 2)

    def test_v2_unknown_has_no_retry_authority(self):
        _, requested, attempt = self.uncertain_intent(version="v2")
        with self.assertRaises(CommandError) as raised:
            retry_idempotent_delivery(
                actor=self.alpha_user, organization_id=self.alpha.id,
                request_id=uuid.uuid4(), intent_id=requested.intent_id,
                expected_attempt_id=attempt.id,
            )
        self.assertEqual(raised.exception.reason_code, "receiver_retry_not_idempotent")
        self.assertEqual(DeliveryAttempt.objects.filter(intent_id=requested.intent_id).count(), 1)

    def test_changed_evidence_under_same_receipt_is_retained_as_conflict(self):
        revision, requested, attempt = self.uncertain_intent()
        reconcile_delivery(
            actor=self.alpha_user, organization_id=self.alpha.id,
            intent_id=requested.intent_id,
            adapter=ReadbackAdapter(lambda frozen: accepted_evidence(
                frozen, reported_attempt_id=str(attempt.id), receipt_id="reused-receipt"
            )),
        )
        wrong = b"x" * len(bytes(revision.envelope_bytes))
        result = reconcile_delivery(
            actor=self.alpha_user, organization_id=self.alpha.id,
            intent_id=requested.intent_id,
            adapter=ReadbackAdapter(lambda frozen: accepted_evidence(
                frozen, reported_attempt_id=str(attempt.id), receipt_id="reused-receipt",
                payload=wrong,
            )),
        )

        self.assertEqual(result.reason_code, "receiver_evidence_conflict")
        observations = ReceiverObservation.objects.filter(intent_id=requested.intent_id)
        self.assertEqual(observations.count(), 2)
        self.assertEqual(observations.filter(observed_state="conflict").count(), 1)
        self.assertEqual(
            delivery_effect_state(DeliveryIntent.objects.get(id=requested.intent_id)),
            "receiver_conflict",
        )
