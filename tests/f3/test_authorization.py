from __future__ import annotations

import uuid

from medicafe_v1.access.models import Membership
from medicafe_v1.access.services import AuthorizationError
from medicafe_v1.claims.delivery_commands import (
    cancel_before_dispatch,
    reconcile_delivery,
    request_delivery,
    retry_idempotent_delivery,
)
from medicafe_v1.claims.delivery_worker import run_delivery_worker_once
from medicafe_v1.claims.models import ClaimsCommandReceipt, DeliveryAttempt, DeliveryWork
from medicafe_v1.claims.queries import (
    delivery_detail,
    delivery_for_claim,
    delivery_for_revision,
    delivery_worklist,
)

from .base import F3TransactionTestCase
from .test_reconciliation import UnknownTransportAdapter


class DeliveryAuthorizationTests(F3TransactionTestCase):
    def _requested(self):
        _, revision, _ = self.approved_claim()
        requested = request_delivery(
            actor=self.alpha_user,
            organization_id=self.alpha.id,
            request_id=uuid.uuid4(),
            claim_revision_id=revision.id,
            expected_envelope_digest=revision.envelope_digest,
        )
        return revision, requested

    def _uncertain(self):
        revision, requested = self._requested()
        result = run_delivery_worker_once(
            worker_id=f"authorization-{uuid.uuid4()}",
            lease_seconds=2,
            adapter=UnknownTransportAdapter(),
        )
        self.assertEqual(result.reason_code, "dispatch_outcome_unknown")
        return revision, requested, DeliveryAttempt.objects.get(id=result.attempt_id)

    def _assert_denied(self, operation):
        with self.assertRaises(AuthorizationError) as denied:
            operation()
        self.assertEqual(denied.exception.reason_code, "active_membership_required")

    def _assert_delivery_operations_denied(self, *, actor, revision, requested, retry_attempt):
        operations = (
            (
                "request_delivery",
                lambda: request_delivery(
                    actor=actor,
                    organization_id=self.alpha.id,
                    request_id=uuid.uuid4(),
                    claim_revision_id=revision.id,
                    expected_envelope_digest=revision.envelope_digest,
                ),
            ),
            (
                "delivery_detail",
                lambda: delivery_detail(
                    actor=actor,
                    organization_id=self.alpha.id,
                    intent_id=requested.intent_id,
                ),
            ),
            (
                "delivery_worklist",
                lambda: delivery_worklist(
                    actor=actor,
                    organization_id=self.alpha.id,
                ),
            ),
            (
                "delivery_for_revision",
                lambda: delivery_for_revision(
                    actor=actor,
                    organization_id=self.alpha.id,
                    claim_revision_id=revision.id,
                ),
            ),
            (
                "delivery_for_claim",
                lambda: delivery_for_claim(
                    actor=actor,
                    organization_id=self.alpha.id,
                    claim_id=revision.claim_id,
                ),
            ),
            (
                "cancel_before_dispatch",
                lambda: cancel_before_dispatch(
                    actor=actor,
                    organization_id=self.alpha.id,
                    request_id=uuid.uuid4(),
                    intent_id=requested.intent_id,
                ),
            ),
            (
                "reconcile_delivery",
                lambda: reconcile_delivery(
                    actor=actor,
                    organization_id=self.alpha.id,
                    intent_id=requested.intent_id,
                ),
            ),
            (
                "retry_idempotent_delivery",
                lambda: retry_idempotent_delivery(
                    actor=actor,
                    organization_id=self.alpha.id,
                    request_id=uuid.uuid4(),
                    intent_id=retry_attempt.intent_id,
                    expected_attempt_id=retry_attempt.id,
                ),
            ),
        )
        for operation, call in operations:
            with self.subTest(operation=operation):
                self._assert_denied(call)

    def test_wrong_organization_caller_is_denied_for_delivery_commands_and_queries(self):
        revision, requested = self._requested()
        _, _, retry_attempt = self._uncertain()
        before_receipts = ClaimsCommandReceipt.objects.count()
        before_attempts = DeliveryAttempt.objects.count()
        before_work_states = dict(DeliveryWork.objects.values_list("id", "state"))

        self._assert_delivery_operations_denied(
            actor=self.beta_user,
            revision=revision,
            requested=requested,
            retry_attempt=retry_attempt,
        )

        self.assertEqual(ClaimsCommandReceipt.objects.count(), before_receipts)
        self.assertEqual(DeliveryAttempt.objects.count(), before_attempts)
        self.assertEqual(dict(DeliveryWork.objects.values_list("id", "state")), before_work_states)

    def test_inactive_caller_is_denied_for_delivery_commands_and_queries(self):
        revision, requested = self._requested()
        _, _, retry_attempt = self._uncertain()
        Membership.objects.filter(
            organization=self.alpha,
            user=self.alpha_user,
        ).update(is_active=False)
        before_receipts = ClaimsCommandReceipt.objects.count()
        before_attempts = DeliveryAttempt.objects.count()
        before_work_states = dict(DeliveryWork.objects.values_list("id", "state"))

        self._assert_delivery_operations_denied(
            actor=self.alpha_user,
            revision=revision,
            requested=requested,
            retry_attempt=retry_attempt,
        )

        self.assertEqual(ClaimsCommandReceipt.objects.count(), before_receipts)
        self.assertEqual(DeliveryAttempt.objects.count(), before_attempts)
        self.assertEqual(dict(DeliveryWork.objects.values_list("id", "state")), before_work_states)
