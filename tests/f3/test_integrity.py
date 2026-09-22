from __future__ import annotations

import uuid
from datetime import timedelta

from django.db import DatabaseError, IntegrityError, connection, transaction
from django.utils import timezone

from medicafe_v1.claims.delivery_commands import request_delivery
from medicafe_v1.claims.models import (
    AttemptOutcome, ClaimsCommandReceipt, DeliveryAttempt, DeliveryIntent,
    DeliveryWork, ReceiverObservation,
)

from .base import F3TransactionTestCase


class DispatchFenceSQLTests(F3TransactionTestCase):
    def setUp(self):
        super().setUp()
        _, self.revision, _ = self.approved_claim()
        requested = request_delivery(
            actor=self.alpha_user, organization_id=self.alpha.id,
            request_id=uuid.uuid4(), claim_revision_id=self.revision.id,
            expected_envelope_digest=self.revision.envelope_digest,
        )
        self.intent = DeliveryIntent.objects.get(id=requested.intent_id)
        self.work = DeliveryWork.objects.get(id=requested.work_id)
        DeliveryWork.objects.filter(pk=self.work.pk).update(
            state=DeliveryWork.STATE_LEASED, lease_owner="sql-worker",
            lease_expires_at=timezone.now() + timedelta(seconds=30),
            fencing_generation=1,
        )
        self.work.refresh_from_db()

    def _attempt_values(self, *, attempt_id=None, owner="sql-worker", generation=1):
        return (
            attempt_id or uuid.uuid4(), self.alpha.id, self.intent.id, 1,
            self.work.scheduled_authorization_receipt_id, self.alpha_user.id,
            self.work.id, owner, generation, self.intent.envelope_digest,
            self.intent.byte_length, self.intent.route_id, self.intent.receiver_version,
            timezone.now(), True,
        )

    def _insert_attempt(self, values):
        with connection.cursor() as cursor:
            cursor.execute("""
                INSERT INTO claims_deliveryattempt
                  (id,organization_id,intent_id,ordinal,authorization_receipt_id,
                   effective_authorizer_id,work_id,lease_owner,fencing_generation,
                   payload_digest,byte_length,route_id,receiver_version,started_at,
                   possible_dispatch)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            """, values)

    def test_direct_stale_owner_insert_fails_named_attempt_guard(self):
        with self.assertRaises(DatabaseError), transaction.atomic():
            self._insert_attempt(self._attempt_values(owner="stale-worker"))
        self.assertFalse(DeliveryAttempt.objects.exists())

    def test_direct_stale_generation_insert_fails_named_attempt_guard(self):
        with self.assertRaises(DatabaseError), transaction.atomic():
            self._insert_attempt(self._attempt_values(generation=2))
        self.assertFalse(DeliveryAttempt.objects.exists())

    def test_direct_same_generation_lease_owner_replacement_fails(self):
        with self.assertRaises(DatabaseError), transaction.atomic():
            DeliveryWork.objects.filter(pk=self.work.pk).update(
                lease_owner="replacement-worker",
            )
        self.work.refresh_from_db()
        self.assertEqual(self.work.lease_owner, "sql-worker")

    def test_direct_same_generation_lease_extension_fails(self):
        original_expiry = self.work.lease_expires_at
        with self.assertRaises(DatabaseError), transaction.atomic():
            DeliveryWork.objects.filter(pk=self.work.pk).update(
                lease_expires_at=original_expiry + timedelta(minutes=5),
            )
        self.work.refresh_from_db()
        self.assertEqual(self.work.lease_expires_at, original_expiry)

    def test_direct_coalescing_receipt_cannot_replace_authorization(self):
        coalesced = ClaimsCommandReceipt.objects.create(
            organization=self.alpha, request_uuid=uuid.uuid4(),
            command_kind="request_delivery", target_key=str(self.revision.id),
            intent_digest="c" * 64, result_claim_id=self.revision.claim_id,
            result_revision=self.revision,
            result_approval=self.intent.claim_approval,
            result_delivery_intent=self.intent, result_delivery_work=self.work,
            result_code="delivery_coalesced", accepted_by=self.alpha_user,
        )
        DeliveryWork.objects.filter(pk=self.work.pk).update(
            state=DeliveryWork.STATE_FINISHED, lease_owner="", lease_expires_at=None,
        )
        with self.assertRaises(DatabaseError), transaction.atomic():
            DeliveryWork.objects.filter(pk=self.work.pk).update(
                state=DeliveryWork.STATE_PENDING,
                scheduled_authorization_receipt=coalesced,
            )
        self.work.refresh_from_db()
        self.assertNotEqual(self.work.scheduled_authorization_receipt_id, coalesced.id)

    def test_direct_authorizer_substitution_fails_named_attempt_guard(self):
        with self.assertRaises(DatabaseError), transaction.atomic():
            values = list(self._attempt_values())
            values[5] = self.beta_user.id
            self._insert_attempt(tuple(values))
        self.assertFalse(DeliveryAttempt.objects.exists())

    def test_direct_accepted_outcome_requires_exact_stored_bytes(self):
        attempt_id = uuid.uuid4()
        self._insert_attempt(self._attempt_values(attempt_id=attempt_id))
        attempt = DeliveryAttempt.objects.get(id=attempt_id)
        wrong = b"x" * self.intent.byte_length
        observation = ReceiverObservation.objects.create(
            organization=self.alpha, intent=self.intent, claim_revision=self.revision,
            origin=ReceiverObservation.ORIGIN_RECONCILIATION,
            receiver_id="synthetic-receiver", receiver_version=self.intent.receiver_version,
            lookup_key=self.intent.delivery_key, receipt_id="wrong-byte-receipt",
            reported_attempt_id=attempt.id, envelope_digest=self.intent.envelope_digest,
            byte_length=self.intent.byte_length, received_bytes=wrong,
            observed_state=ReceiverObservation.STATE_ACCEPTED,
            no_acceptance_guaranteed=False, binding_valid=True, conflict_reason="",
            evidence_fingerprint="a" * 64,
            reported_organization_id=self.alpha.id, reported_intent_id=self.intent.id,
            reported_claim_revision_id=self.revision.id,
            reported_delivery_key=self.intent.delivery_key,
            reported_receiver_id="synthetic-receiver",
            reported_receiver_version=self.intent.receiver_version,
            reported_envelope_digest=self.intent.envelope_digest,
            reported_byte_length=self.intent.byte_length, observed_at=timezone.now(),
        )
        observation.refresh_from_db()
        self.assertFalse(observation.binding_valid)
        self.assertEqual(observation.observed_state, ReceiverObservation.STATE_CONFLICT)
        with self.assertRaises(DatabaseError), transaction.atomic():
            AttemptOutcome.objects.create(
                organization=self.alpha, attempt=attempt,
                kind=AttemptOutcome.RECEIVER_ACCEPTED, reason="forged",
                ended_at=timezone.now(), receiver_observation=observation,
            )

    def test_unknown_outcome_is_immutable(self):
        attempt_id = uuid.uuid4()
        self._insert_attempt(self._attempt_values(attempt_id=attempt_id))
        outcome = AttemptOutcome.objects.create(
            organization=self.alpha, attempt_id=attempt_id,
            kind=AttemptOutcome.UNKNOWN, reason="crash_window", ended_at=timezone.now(),
        )
        with self.assertRaises(DatabaseError), transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute(
                    "UPDATE claims_attemptoutcome SET reason='rewritten' WHERE id=%s",
                    (outcome.id,),
                )

    def test_f3_receipt_without_actor_fails_result_shape(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            ClaimsCommandReceipt.objects.create(
                organization=self.alpha, request_uuid=uuid.uuid4(),
                command_kind="cancel_before_dispatch", target_key=str(self.intent.id),
                intent_digest="b" * 64, result_delivery_intent=self.intent,
                result_delivery_work=self.work, result_code="delivery_cancelled",
                accepted_by=None,
            )
