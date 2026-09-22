from __future__ import annotations

import time
import uuid
from datetime import timedelta

from django.db import DatabaseError, connection, transaction
from django.utils import timezone

from medicafe_v1.claims.delivery_commands import request_delivery
from medicafe_v1.claims.models import (
    AttemptOutcome,
    ClaimsCommandReceipt,
    DeliveryAttempt,
    DeliveryIntent,
    DeliveryWork,
    ReceiverObservation,
)

from .base import F3FixtureMixin
from tests.f2.base import F2TransactionTestCase


class F3RelationshipSQLTests(F3FixtureMixin, F2TransactionTestCase):
    def setUp(self):
        super().setUp()
        _, self.revision, self.approval = self.approved_claim(
            note="SYNTHETIC_F3_RELATION_BASELINE"
        )
        requested = request_delivery(
            actor=self.alpha_user,
            organization_id=self.alpha.id,
            request_id=uuid.uuid4(),
            claim_revision_id=self.revision.id,
            expected_envelope_digest=self.revision.envelope_digest,
        )
        self.intent = DeliveryIntent.objects.get(id=requested.intent_id)
        self.work = DeliveryWork.objects.get(id=requested.work_id)

    def _lease_work(self, *, owner="relationship-worker", seconds=30, generation=1):
        DeliveryWork.objects.filter(pk=self.work.pk).update(
            state=DeliveryWork.STATE_LEASED,
            lease_owner=owner,
            lease_expires_at=timezone.now() + timedelta(seconds=seconds),
            fencing_generation=generation,
        )
        self.work.refresh_from_db()
        return self.work

    def _finish_work(self):
        DeliveryWork.objects.filter(pk=self.work.pk).update(
            state=DeliveryWork.STATE_FINISHED,
            lease_owner="",
            lease_expires_at=None,
        )
        self.work.refresh_from_db()

    def _attempt(
        self,
        *,
        ordinal=1,
        attempt_id=None,
        authorization_receipt=None,
        owner=None,
        generation=None,
        possible_dispatch=True
    ):
        self.work.refresh_from_db()
        return DeliveryAttempt.objects.create(
            id=attempt_id or uuid.uuid4(),
            organization=self.alpha,
            intent=self.intent,
            ordinal=ordinal,
            authorization_receipt_id=(
                authorization_receipt.id
                if authorization_receipt is not None
                else self.work.scheduled_authorization_receipt_id
            ),
            effective_authorizer=self.alpha_user,
            work=self.work,
            lease_owner=owner if owner is not None else self.work.lease_owner,
            fencing_generation=(
                generation if generation is not None else self.work.fencing_generation
            ),
            payload_digest=self.intent.envelope_digest,
            byte_length=self.intent.byte_length,
            route_id=self.intent.route_id,
            receiver_version=self.intent.receiver_version,
            started_at=timezone.now(),
            possible_dispatch=possible_dispatch,
        )

    def _receipt(
        self,
        *,
        command_kind,
        target_key,
        result_code,
        result_claim=None,
        result_revision=None,
        result_approval=None,
        result_intent=None,
        result_work=None,
        result_attempt=None,
        expected_predecessor_id=None,
    ):
        return ClaimsCommandReceipt.objects.create(
            organization=self.alpha,
            request_uuid=uuid.uuid4(),
            command_kind=command_kind,
            target_key=target_key,
            expected_predecessor_id=expected_predecessor_id,
            intent_digest=uuid.uuid4().hex * 2,
            result_claim=result_claim,
            result_revision=result_revision,
            result_approval=result_approval,
            result_delivery_intent=result_intent,
            result_delivery_work=result_work,
            result_attempt=result_attempt,
            result_code=result_code,
            accepted_by=self.alpha_user,
        )

    def _observation(
        self,
        attempt,
        *,
        state=ReceiverObservation.STATE_ACCEPTED,
        receipt_id=None,
        reported_attempt_id=None,
        reported_envelope_digest=None,
        no_acceptance_guaranteed=False,
        received_bytes=None,
        evidence_fingerprint=None
    ):
        if state == ReceiverObservation.STATE_ACCEPTED and received_bytes is None:
            received_bytes = bytes(self.revision.envelope_bytes)
        observation = ReceiverObservation.objects.create(
            organization=self.alpha,
            intent=self.intent,
            claim_revision=self.revision,
            origin=ReceiverObservation.ORIGIN_RECONCILIATION,
            receiver_id="synthetic-receiver",
            receiver_version=self.intent.receiver_version,
            lookup_key=self.intent.delivery_key,
            receipt_id=receipt_id or f"synthetic-receipt-{uuid.uuid4().hex}",
            reported_attempt_id=reported_attempt_id or attempt.id,
            envelope_digest=self.intent.envelope_digest,
            byte_length=self.intent.byte_length,
            received_bytes=received_bytes,
            observed_state=state,
            no_acceptance_guaranteed=no_acceptance_guaranteed,
            binding_valid=True,
            conflict_reason="",
            evidence_fingerprint=evidence_fingerprint or uuid.uuid4().hex * 2,
            reported_organization_id=self.alpha.id,
            reported_intent_id=self.intent.id,
            reported_claim_revision_id=self.revision.id,
            reported_delivery_key=self.intent.delivery_key,
            reported_receiver_id="synthetic-receiver",
            reported_receiver_version=self.intent.receiver_version,
            reported_envelope_digest=(
                reported_envelope_digest or self.intent.envelope_digest
            ),
            reported_byte_length=self.intent.byte_length,
            observed_at=timezone.now(),
        )
        observation.refresh_from_db()
        return observation

    def test_direct_intent_tuple_guards_reject_one_mismatched_component(self):
        self.assertEqual(self.intent.claim_revision_id, self.revision.id)
        self.assertEqual(self.intent.claim_approval_id, self.approval.id)

        cases = ("organization", "claim", "approval", "digest")
        for label in cases:
            with self.subTest(component=label):
                _, revision, approval = self.approved_claim(
                    note=f"SYNTHETIC_F3_INTENT_{label.upper()}"
                )
                intent_id = uuid.uuid4()
                values = {
                    "organization": self.alpha,
                    "claim": revision.claim,
                    "claim_revision": revision,
                    "claim_approval": approval,
                    "envelope_digest": revision.envelope_digest,
                    "byte_length": len(revision.envelope_bytes),
                    "format_version": revision.envelope_format_version,
                    "route_id": revision.route_id,
                    "receiver_version": revision.route_version,
                    "delivery_key": intent_id,
                    "initial_authorization_receipt": self.intent.initial_authorization_receipt,
                    "authorized_by": self.alpha_user,
                    "authorized_at": timezone.now(),
                }
                if label == "organization":
                    values["organization"] = self.beta
                    values["authorized_by"] = self.beta_user
                elif label == "claim":
                    values["claim"] = self.intent.claim
                elif label == "approval":
                    values["claim_approval"] = self.approval
                else:
                    values["envelope_digest"] = (
                        self.intent.envelope_digest
                        if self.intent.envelope_digest != revision.envelope_digest
                        else "f" * 64
                    )

                with self.assertRaisesMessage(
                    DatabaseError,
                    "delivery intent revision, approval, bytes, or route mismatch",
                ):
                    with transaction.atomic():
                        DeliveryIntent.objects.create(id=intent_id, **values)

    def test_request_receipt_result_work_binding_rejects_cross_intent_work(self):
        _, other_revision, _ = self.approved_claim(
            note="SYNTHETIC_F3_REQUEST_RESULT_OTHER"
        )
        other_requested = request_delivery(
            actor=self.alpha_user,
            organization_id=self.alpha.id,
            request_id=uuid.uuid4(),
            claim_revision_id=other_revision.id,
            expected_envelope_digest=other_revision.envelope_digest,
        )
        other_work = DeliveryWork.objects.get(id=other_requested.work_id)
        self.assertNotEqual(other_work.intent_id, self.intent.id)

        with self.assertRaisesMessage(
            DatabaseError,
            "F3 receipt actor, intent, or work binding mismatch",
        ):
            with transaction.atomic():
                self._receipt(
                    command_kind="request_delivery",
                    target_key=str(self.revision.id),
                    result_code="delivery_coalesced",
                    result_claim=self.revision.claim,
                    result_revision=self.revision,
                    result_approval=self.approval,
                    result_intent=self.intent,
                    result_work=other_work,
                )

    def test_retry_receipt_predecessor_binding_rejects_another_real_attempt(self):
        self._lease_work()
        predecessor = self._attempt(ordinal=1, possible_dispatch=True)
        other_attempt = self._attempt(ordinal=2, possible_dispatch=False)

        valid = self._receipt(
            command_kind="retry_idempotent_delivery",
            target_key=str(self.intent.id),
            result_code="delivery_retry_already_scheduled",
            result_intent=self.intent,
            result_work=self.work,
            result_attempt=predecessor,
            expected_predecessor_id=predecessor.id,
        )
        self.assertEqual(valid.result_attempt_id, predecessor.id)

        with self.assertRaisesMessage(
            DatabaseError,
            "retry receipt predecessor or schedule mismatch",
        ):
            with transaction.atomic():
                self._receipt(
                    command_kind="retry_idempotent_delivery",
                    target_key=str(self.intent.id),
                    result_code="delivery_retry_already_scheduled",
                    result_intent=self.intent,
                    result_work=self.work,
                    result_attempt=predecessor,
                    expected_predecessor_id=other_attempt.id,
                )

    def test_attempt_rejects_a_valid_but_wrong_kind_authorization_receipt(self):
        self._lease_work()
        baseline = self._attempt(ordinal=1, possible_dispatch=False)
        self.assertEqual(
            baseline.authorization_receipt_id,
            self.work.scheduled_authorization_receipt_id,
        )
        wrong_receipt = self._receipt(
            command_kind="cancel_before_dispatch",
            target_key=str(self.intent.id),
            result_code="delivery_cancelled",
            result_intent=self.intent,
            result_work=self.work,
        )

        with self.assertRaisesMessage(
            DatabaseError,
            "delivery attempt lease, fence, authorization, or payload mismatch",
        ):
            with transaction.atomic():
                self._attempt(
                    ordinal=2,
                    authorization_receipt=wrong_receipt,
                    possible_dispatch=False,
                )

    def test_attempt_insert_rejects_a_real_expired_lease(self):
        self._lease_work(seconds=0.1)
        time.sleep(0.25)

        with self.assertRaisesMessage(
            DatabaseError,
            "delivery attempt lease, fence, authorization, or payload mismatch",
        ):
            with transaction.atomic():
                self._attempt()

    def test_work_fence_rejects_rewind_and_skip(self):
        self._lease_work()
        for new_generation in (0, 3):
            with self.subTest(new_generation=new_generation):
                with self.assertRaisesMessage(
                    DatabaseError,
                    "delivery work fence cannot rewind or skip",
                ):
                    with transaction.atomic():
                        DeliveryWork.objects.filter(pk=self.work.pk).update(
                            fencing_generation=new_generation
                        )
                self.work.refresh_from_db()
                self.assertEqual(self.work.fencing_generation, 1)

    def test_immutable_intent_attempt_and_observation_reject_update_and_delete(self):
        self._lease_work()
        attempt = self._attempt()
        observation = self._observation(attempt)
        self.assertTrue(observation.binding_valid)

        immutable_rows = (
            (
                "intent",
                "claims_deliveryintent",
                "authorized_by_id",
                self.beta_user.id,
                self.intent.id,
                DeliveryIntent,
            ),
            (
                "attempt",
                "claims_deliveryattempt",
                "lease_owner",
                "rewritten-history-worker",
                attempt.id,
                DeliveryAttempt,
            ),
            (
                "observation",
                "claims_receiverobservation",
                "conflict_reason",
                "rewritten-history",
                observation.id,
                ReceiverObservation,
            ),
        )
        for label, table, column, value, row_id, model in immutable_rows:
            for operation in ("update", "delete"):
                with self.subTest(row=label, operation=operation):
                    with self.assertRaisesMessage(
                        DatabaseError,
                        "immutable F3 claims row",
                    ):
                        with transaction.atomic():
                            with connection.cursor() as cursor:
                                if operation == "update":
                                    cursor.execute(
                                        f"UPDATE {table} SET {column}=%s WHERE id=%s",
                                        (value, row_id),
                                    )
                                else:
                                    cursor.execute(
                                        f"DELETE FROM {table} WHERE id=%s",
                                        (row_id,),
                                    )
                    self.assertTrue(model.objects.filter(pk=row_id).exists())

    def test_observation_rejects_wrong_reported_envelope_evidence(self):
        self._lease_work()
        attempt = self._attempt()
        wrong_digest = (
            "0" * 64
            if self.intent.envelope_digest != "0" * 64
            else "1" * 64
        )
        observation = self._observation(
            attempt,
            receipt_id="synthetic-wrong-reported-digest",
            reported_envelope_digest=wrong_digest,
        )

        self.assertFalse(observation.binding_valid)
        self.assertEqual(observation.observed_state, ReceiverObservation.STATE_CONFLICT)
        self.assertEqual(observation.conflict_reason, "binding_mismatch")

    def test_rejected_outcome_cannot_use_another_attempts_evidence(self):
        self._lease_work(owner="relationship-worker-one", generation=1)
        first = self._attempt(
            ordinal=1,
            owner="relationship-worker-one",
            generation=1,
            possible_dispatch=True,
        )
        self._finish_work()
        self._lease_work(owner="relationship-worker-two", generation=2)
        second = self._attempt(
            ordinal=2,
            owner="relationship-worker-two",
            generation=2,
            possible_dispatch=True,
        )
        rejection = self._observation(
            second,
            state=ReceiverObservation.STATE_REJECTED,
            receipt_id="synthetic-rejection-second-attempt",
            no_acceptance_guaranteed=True,
            received_bytes=None,
        )
        self.assertTrue(rejection.binding_valid)

        with self.assertRaisesMessage(
            DatabaseError,
            "rejected outcome requires attempt-specific no-acceptance evidence",
        ):
            with transaction.atomic():
                AttemptOutcome.objects.create(
                    organization=self.alpha,
                    attempt=first,
                    kind=AttemptOutcome.RECEIVER_REJECTED,
                    reason="Synthetic wrong attempt evidence",
                    ended_at=timezone.now(),
                    receiver_observation=rejection,
                )

    def test_rejected_outcome_requires_no_acceptance_guarantee(self):
        self._lease_work()
        attempt = self._attempt()
        rejected = self._observation(
            attempt,
            state=ReceiverObservation.STATE_REJECTED,
            receipt_id="synthetic-missing-rejection-guarantee",
            no_acceptance_guaranteed=False,
            received_bytes=None,
        )
        self.assertFalse(rejected.binding_valid)
        self.assertEqual(rejected.observed_state, ReceiverObservation.STATE_CONFLICT)

        with self.assertRaisesMessage(
            DatabaseError,
            "delivery outcome receiver evidence mismatch",
        ):
            with transaction.atomic():
                AttemptOutcome.objects.create(
                    organization=self.alpha,
                    attempt=attempt,
                    kind=AttemptOutcome.RECEIVER_REJECTED,
                    reason="Synthetic missing rejection guarantee",
                    ended_at=timezone.now(),
                    receiver_observation=rejected,
                )
