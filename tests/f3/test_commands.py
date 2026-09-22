from __future__ import annotations

import uuid

from medicafe_v1.claims.commands import select_synthetic_policy
from medicafe_v1.claims.delivery_commands import (
    cancel_before_dispatch, request_delivery,
)
from medicafe_v1.claims.models import (
    ClaimDeliveryControl, ClaimsCommandReceipt, DeliveryIntent, DeliveryWork,
)
from medicafe_v1.sources.domain import CommandError

from .base import F3TransactionTestCase


class DeliveryCommandTests(F3TransactionTestCase):
    def test_request_receipts_replay_conflict_and_coalesce(self):
        claim, revision, approval = self.approved_claim()
        request_id = uuid.uuid4()

        created = request_delivery(
            actor=self.alpha_user, organization_id=self.alpha.id,
            request_id=request_id, claim_revision_id=revision.id,
            expected_envelope_digest=revision.envelope_digest,
        )
        replayed = request_delivery(
            actor=self.alpha_user, organization_id=self.alpha.id,
            request_id=request_id, claim_revision_id=revision.id,
            expected_envelope_digest=revision.envelope_digest,
        )
        coalesced = request_delivery(
            actor=self.alpha_user, organization_id=self.alpha.id,
            request_id=uuid.uuid4(), claim_revision_id=revision.id,
            expected_envelope_digest=revision.envelope_digest,
        )

        self.assertEqual(created.intent_id, replayed.intent_id)
        self.assertEqual(created.intent_id, coalesced.intent_id)
        self.assertTrue(replayed.replayed)
        self.assertEqual(coalesced.reason_code, "delivery_coalesced")
        self.assertEqual(DeliveryIntent.objects.count(), 1)
        self.assertEqual(DeliveryWork.objects.count(), 1)
        self.assertEqual(ClaimDeliveryControl.objects.get(claim=claim).current_intent_id, created.intent_id)
        intent = DeliveryIntent.objects.get(id=created.intent_id)
        self.assertEqual(intent.claim_approval_id, approval.id)
        self.assertEqual(intent.delivery_key, intent.id)
        self.assertEqual(bytes(revision.envelope_bytes), bytes(intent.claim_revision.envelope_bytes))
        authorizing = ClaimsCommandReceipt.objects.get(id=intent.initial_authorization_receipt_id)
        self.assertEqual(authorizing.accepted_by_id, self.alpha_user.id)
        self.assertEqual(authorizing.result_delivery_intent_id, intent.id)
        self.assertEqual(authorizing.result_delivery_work_id, intent.work.id)

        with self.assertRaises(CommandError) as raised:
            request_delivery(
                actor=self.alpha_user, organization_id=self.alpha.id,
                request_id=request_id, claim_revision_id=revision.id,
                expected_envelope_digest="f" * 64,
            )
        self.assertEqual(raised.exception.reason_code, "request_input_conflict")
        self.assertEqual(DeliveryIntent.objects.count(), 1)

    def test_new_exact_request_coalesces_after_policy_staleness_without_reauthorization(self):
        _, revision, _ = self.approved_claim()
        created = request_delivery(
            actor=self.alpha_user, organization_id=self.alpha.id,
            request_id=uuid.uuid4(), claim_revision_id=revision.id,
            expected_envelope_digest=revision.envelope_digest,
        )
        intent = DeliveryIntent.objects.get(id=created.intent_id)
        original_receipt_id = intent.initial_authorization_receipt_id
        original_authorizer_id = intent.authorized_by_id
        select_synthetic_policy(
            actor=self.alpha_user, organization_id=self.alpha.id,
            request_id=uuid.uuid4(), expected_version="synthetic-v1",
            expected_generation=1, version="synthetic-v2",
        )

        coalesced = request_delivery(
            actor=self.alpha_user, organization_id=self.alpha.id,
            request_id=uuid.uuid4(), claim_revision_id=revision.id,
            expected_envelope_digest=revision.envelope_digest,
        )

        self.assertEqual(coalesced.reason_code, "delivery_coalesced")
        self.assertEqual(coalesced.intent_id, intent.id)
        self.assertIn("policy_changed", coalesced.current_blockers)
        intent.refresh_from_db()
        self.assertEqual(intent.initial_authorization_receipt_id, original_receipt_id)
        self.assertEqual(intent.authorized_by_id, original_authorizer_id)
        self.assertEqual(DeliveryIntent.objects.count(), 1)

    def test_safe_cancellation_is_receipted_and_replayed_without_dispatch(self):
        _, revision, _ = self.approved_claim()
        requested = request_delivery(
            actor=self.alpha_user, organization_id=self.alpha.id,
            request_id=uuid.uuid4(), claim_revision_id=revision.id,
            expected_envelope_digest=revision.envelope_digest,
        )
        cancel_id = uuid.uuid4()
        cancelled = cancel_before_dispatch(
            actor=self.alpha_user, organization_id=self.alpha.id,
            request_id=cancel_id, intent_id=requested.intent_id,
        )
        replayed = cancel_before_dispatch(
            actor=self.alpha_user, organization_id=self.alpha.id,
            request_id=cancel_id, intent_id=requested.intent_id,
        )

        self.assertEqual(cancelled.reason_code, "delivery_cancelled")
        self.assertTrue(replayed.replayed)
        self.assertEqual(replayed.intent_id, requested.intent_id)
        work = DeliveryWork.objects.get(id=requested.work_id)
        self.assertEqual(work.state, DeliveryWork.STATE_FINISHED)
        self.assertEqual(work.blocking_reason, "cancelled_before_dispatch")
        receipt = ClaimsCommandReceipt.objects.get(
            organization=self.alpha, request_uuid=cancel_id
        )
        self.assertEqual(receipt.accepted_by_id, self.alpha_user.id)
        self.assertEqual(receipt.result_code, "delivery_cancelled")
