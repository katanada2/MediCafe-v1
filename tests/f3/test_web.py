from __future__ import annotations

import uuid

from django.test import Client
from django.urls import reverse

from medicafe_v1.claims.delivery_commands import request_delivery
from medicafe_v1.claims.delivery_worker import run_delivery_worker_once
from medicafe_v1.claims.models import ClaimsCommandReceipt, DeliveryAttempt, ReceiverObservation

from .base import F3TransactionTestCase
from .test_reconciliation import UnknownTransportAdapter
from .test_worker import AcceptedAdapter


class DeliveryWebTests(F3TransactionTestCase):
    def _intent(self):
        _, revision, _ = self.approved_claim()
        return request_delivery(
            actor=self.alpha_user, organization_id=self.alpha.id,
            request_id=uuid.uuid4(), claim_revision_id=revision.id,
            expected_envelope_digest=revision.envelope_digest,
        )

    def test_all_action_forms_bind_hidden_intent_to_url_target(self):
        first = self._intent()
        second = self._intent()
        client = Client()
        client.force_login(self.alpha_user)
        url = reverse("delivery_detail", kwargs={
            "organization_id": self.alpha.id, "intent_id": first.intent_id,
        })

        cancel_uuid = uuid.uuid4()
        cancel = client.post(url, {
            "action": "cancel", "cancel-request_uuid": str(cancel_uuid),
            "cancel-intent_id": str(second.intent_id),
        })
        self.assertEqual(cancel.status_code, 200)
        self.assertContains(cancel, "delivery_intent_not_for_page")
        self.assertFalse(ClaimsCommandReceipt.objects.filter(request_uuid=cancel_uuid).exists())

        reconcile = client.post(url, {
            "action": "reconcile", "reconcile-intent_id": str(second.intent_id),
        })
        self.assertEqual(reconcile.status_code, 200)
        self.assertContains(reconcile, "delivery_intent_not_for_page")
        self.assertFalse(ReceiverObservation.objects.exists())

        adapter = UnknownTransportAdapter()
        run_delivery_worker_once(worker_id="web-unknown-1", lease_seconds=2, adapter=adapter)
        run_delivery_worker_once(worker_id="web-unknown-2", lease_seconds=2, adapter=adapter)
        uncertain_page = client.get(url)
        self.assertContains(uncertain_page, "uncertain")
        self.assertContains(uncertain_page, "not payer submission")
        second_attempt = DeliveryAttempt.objects.get(intent_id=second.intent_id)
        retry_uuid = uuid.uuid4()
        retry = client.post(url, {
            "action": "retry", "retry-request_uuid": str(retry_uuid),
            "retry-intent_id": str(second.intent_id),
            "retry-expected_attempt_id": str(second_attempt.id),
        })
        self.assertEqual(retry.status_code, 200)
        self.assertContains(retry, "delivery_intent_not_for_page")
        self.assertFalse(ClaimsCommandReceipt.objects.filter(request_uuid=retry_uuid).exists())

    def test_confirmed_receiver_acceptance_is_not_presented_as_payer_completion(self):
        requested = self._intent()
        delivered = run_delivery_worker_once(
            worker_id="web-accepted", lease_seconds=2, adapter=AcceptedAdapter()
        )
        self.assertEqual(delivered.reason_code, "receiver_evidence_recorded")
        client = Client()
        client.force_login(self.alpha_user)
        response = client.get(reverse("delivery_detail", kwargs={
            "organization_id": self.alpha.id, "intent_id": requested.intent_id,
        }))
        self.assertContains(response, "receiver_accepted")
        self.assertContains(response, "not payer submission")
        self.assertNotContains(response, "approved for payment")

    def test_delivery_mutation_requires_csrf(self):
        requested = self._intent()
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.alpha_user)
        url = reverse("delivery_detail", kwargs={
            "organization_id": self.alpha.id, "intent_id": requested.intent_id,
        })
        response = client.post(url, {
            "action": "cancel", "cancel-request_uuid": str(uuid.uuid4()),
            "cancel-intent_id": str(requested.intent_id),
        })
        self.assertEqual(response.status_code, 403)
