from __future__ import annotations

import uuid

from django.test import Client
from django.urls import reverse

from medicafe_v1.archival.commands import capture_archive_projection
from medicafe_v1.archival.models import ArchiveBatch, ArchiveProjection
from medicafe_v1.outcomes.commands import post_remittance
from medicafe_v1.outcomes.models import AcceptedEvent, OutcomesCommandReceipt

from .base import F4TransactionTestCase


class F4WebTests(F4TransactionTestCase):
    def _candidate(self):
        _revision, intent, observation, _result = self.delivered_claim()
        _delivery, candidate = self.admit_inbound(
            kind="lifecycle", intent=intent, observation=observation,
        )
        return intent, candidate

    def _projection(self):
        _revision, intent, _observation, _result = self.delivered_claim()
        return capture_archive_projection(
            actor=self.alpha_user, organization_id=self.alpha.id,
            request_id=uuid.uuid4(), encounter_id=intent.claim_revision.encounter_id,
            expected_projection_id=None,
        )

    def test_candidate_action_rejects_hidden_target_substitution(self):
        _first_intent, first = self._candidate()
        _second_intent, second = self._candidate()
        client = Client()
        client.force_login(self.alpha_user)
        url = reverse("outcomes_candidate_detail", kwargs={
            "organization_id": self.alpha.id, "candidate_id": first.candidate_id,
        })
        request_uuid = uuid.uuid4()

        response = client.post(url, {
            "action": "accept", "accept-request_uuid": str(request_uuid),
            "accept-target_id": str(second.candidate_id),
        })

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "candidate_not_for_page")
        self.assertFalse(OutcomesCommandReceipt.objects.filter(
            request_uuid=request_uuid,
        ).exists())
        self.assertFalse(AcceptedEvent.objects.exists())

    def test_outcome_action_requires_csrf_and_labels_reported_evidence(self):
        _intent, candidate = self._candidate()
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.alpha_user)
        url = reverse("outcomes_candidate_detail", kwargs={
            "organization_id": self.alpha.id,
            "candidate_id": candidate.candidate_id,
        })
        page = client.get(url)
        self.assertContains(page, "not payer approval")
        response = client.post(url, {
            "action": "accept", "accept-request_uuid": str(uuid.uuid4()),
            "accept-target_id": str(candidate.candidate_id),
        })
        self.assertEqual(response.status_code, 403)
        self.assertFalse(AcceptedEvent.objects.exists())

    def test_archive_action_rejects_hidden_projection_substitution(self):
        first = self._projection()
        second = self._projection()
        client = Client()
        client.force_login(self.alpha_user)
        url = reverse("archive_projection_detail", kwargs={
            "organization_id": self.alpha.id,
            "projection_id": first.projection_id,
        })
        request_uuid = uuid.uuid4()

        response = client.post(url, {
            "action": "queue", "queue-request_uuid": str(request_uuid),
            "queue-target_id": str(second.projection_id),
        })

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "archive_projection_not_for_page")
        self.assertFalse(ArchiveBatch.objects.exists())

    def test_archive_capture_requires_csrf_and_never_claims_send_confirmation(self):
        _revision, intent, _observation, _result = self.delivered_claim()
        encounter_id = intent.claim_revision.encounter_id
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.alpha_user)
        url = reverse("archive_encounter", kwargs={
            "organization_id": self.alpha.id, "encounter_id": encounter_id,
        })
        page = client.get(url)
        self.assertContains(page, "not a production record-retention system")

        response = client.post(url, {
            "request_uuid": str(uuid.uuid4()), "target_id": str(encounter_id),
            "expected_projection_id": "",
        })

        self.assertEqual(response.status_code, 403)
        self.assertFalse(ArchiveProjection.objects.exists())

    def test_every_f4_mutation_route_requires_csrf(self):
        _revision, intent, observation, _result = self.delivered_claim()
        admitted = self.admit(
            content=self.inbound_document(
                kind="lifecycle", intent=intent, observation=observation,
            ),
            source_namespace="synthetic-lifecycle", media_type="application/json",
        )
        _delivery, lifecycle = self.admit_inbound(
            kind="lifecycle", intent=intent, observation=observation,
        )
        _remittance_delivery, remittance = self.admit_inbound(
            kind="remittance", intent=intent, observation=observation,
        )
        projection = capture_archive_projection(
            actor=self.alpha_user, organization_id=self.alpha.id,
            request_id=uuid.uuid4(), encounter_id=intent.claim_revision.encounter_id,
            expected_projection_id=None,
        )
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.alpha_user)
        cases = (
            ("interpret", reverse("outcomes_interpret", kwargs={
                "organization_id": self.alpha.id, "delivery_id": admitted.delivery_id,
            }), {"target_id": str(admitted.delivery_id)}),
            ("accept", reverse("outcomes_candidate_detail", kwargs={
                "organization_id": self.alpha.id, "candidate_id": lifecycle.candidate_id,
            }), {
                "action": "accept", "accept-request_uuid": str(uuid.uuid4()),
                "accept-target_id": str(lifecycle.candidate_id),
            }),
            ("post", reverse("outcomes_candidate_detail", kwargs={
                "organization_id": self.alpha.id, "candidate_id": remittance.candidate_id,
            }), {
                "action": "post", "post-request_uuid": str(uuid.uuid4()),
                "post-target_id": str(remittance.candidate_id),
            }),
            ("reevaluate", reverse("outcomes_candidate_detail", kwargs={
                "organization_id": self.alpha.id, "candidate_id": lifecycle.candidate_id,
            }), {
                "action": "reevaluate",
                "reevaluate-target_id": str(lifecycle.candidate_id),
            }),
            ("capture", reverse("archive_encounter", kwargs={
                "organization_id": self.alpha.id,
                "encounter_id": intent.claim_revision.encounter_id,
            }), {
                "request_uuid": str(uuid.uuid4()),
                "target_id": str(intent.claim_revision.encounter_id),
                "expected_projection_id": str(projection.projection_id),
            }),
            ("queue", reverse("archive_projection_detail", kwargs={
                "organization_id": self.alpha.id,
                "projection_id": projection.projection_id,
            }), {
                "action": "queue", "queue-request_uuid": str(uuid.uuid4()),
                "queue-target_id": str(projection.projection_id),
            }),
            ("retry", reverse("archive_projection_detail", kwargs={
                "organization_id": self.alpha.id,
                "projection_id": projection.projection_id,
            }), {
                "action": "retry", "retry-request_uuid": str(uuid.uuid4()),
                "retry-target_id": str(projection.projection_id),
                "retry-expected_attempt_id": str(uuid.uuid4()),
            }),
            ("reconcile", reverse("archive_projection_detail", kwargs={
                "organization_id": self.alpha.id,
                "projection_id": projection.projection_id,
            }), {
                "action": "reconcile",
                "reconcile-target_id": str(projection.projection_id),
            }),
        )
        before = (
            AcceptedEvent.objects.count(), OutcomesCommandReceipt.objects.count(),
            ArchiveBatch.objects.count(), ArchiveProjection.objects.count(),
        )
        for name, url, payload in cases:
            with self.subTest(route=name):
                self.assertEqual(client.post(url, payload).status_code, 403)
        self.assertEqual((
            AcceptedEvent.objects.count(), OutcomesCommandReceipt.objects.count(),
            ArchiveBatch.objects.count(), ArchiveProjection.objects.count(),
        ), before)

    def test_receipt_bearing_forms_preserve_request_and_target_fields_on_error(self):
        _revision, intent, observation, _result = self.delivered_claim()
        _delivery, lifecycle = self.admit_inbound(
            kind="lifecycle", intent=intent, observation=observation,
        )
        _delivery, remittance = self.admit_inbound(
            kind="remittance", intent=intent, observation=observation,
        )
        projection = capture_archive_projection(
            actor=self.alpha_user,
            organization_id=self.alpha.id,
            request_id=uuid.uuid4(),
            encounter_id=intent.claim_revision.encounter_id,
            expected_projection_id=None,
        )
        client = Client()
        client.force_login(self.alpha_user)
        cases = (
            (
                "accept",
                reverse("outcomes_candidate_detail", kwargs={
                    "organization_id": self.alpha.id,
                    "candidate_id": lifecycle.candidate_id,
                }),
                "accept",
                "accept-request_uuid",
                "accept-target_id",
                None,
            ),
            (
                "post",
                reverse("outcomes_candidate_detail", kwargs={
                    "organization_id": self.alpha.id,
                    "candidate_id": remittance.candidate_id,
                }),
                "post",
                "post-request_uuid",
                "post-target_id",
                None,
            ),
            (
                "capture",
                reverse("archive_encounter", kwargs={
                    "organization_id": self.alpha.id,
                    "encounter_id": intent.claim_revision.encounter_id,
                }),
                None,
                "request_uuid",
                "target_id",
                ("expected_projection_id", str(projection.projection_id)),
            ),
            (
                "queue",
                reverse("archive_projection_detail", kwargs={
                    "organization_id": self.alpha.id,
                    "projection_id": projection.projection_id,
                }),
                "queue",
                "queue-request_uuid",
                "queue-target_id",
                None,
            ),
            (
                "retry",
                reverse("archive_projection_detail", kwargs={
                    "organization_id": self.alpha.id,
                    "projection_id": projection.projection_id,
                }),
                "retry",
                "retry-request_uuid",
                "retry-target_id",
                ("retry-expected_attempt_id", str(uuid.uuid4())),
            ),
        )
        for name, url, action, request_key, target_key, extra in cases:
            with self.subTest(action=name):
                request_id = str(uuid.uuid4())
                wrong_target = str(uuid.uuid4())
                payload = {request_key: request_id, target_key: wrong_target}
                if action:
                    payload["action"] = action
                if extra:
                    payload[extra[0]] = extra[1]
                response = client.post(url, payload)
                self.assertEqual(response.status_code, 200)
                self.assertContains(response, request_id)
                self.assertContains(response, wrong_target)
                if extra:
                    self.assertContains(response, extra[1])

    def test_zero_residual_page_uses_bounded_financial_wording(self):
        _revision, intent, observation, _result = self.delivered_claim()
        _delivery, remittance = self.admit_inbound(
            kind="remittance", intent=intent, observation=observation,
            lines=[{
                "line_ordinal": 1,
                "paid_amount": "9.00",
                "contractual_adjustment": "1.00",
            }],
        )
        post_remittance(
            actor=self.alpha_user,
            organization_id=self.alpha.id,
            request_id=uuid.uuid4(),
            candidate_id=remittance.candidate_id,
            artifact_store=self.store,
        )
        client = Client()
        client.force_login(self.alpha_user)
        response = client.get(reverse("outcomes_candidate_detail", kwargs={
            "organization_id": self.alpha.id,
            "candidate_id": remittance.candidate_id,
        }))

        self.assertContains(response, "Derived synthetic ledger")
        self.assertContains(response, "payer-reported credits 9.00")
        self.assertContains(response, "contractual adjustments 1.00")
        self.assertContains(response, "residual 0.00")
        self.assertNotContains(response, "patient liability")
        self.assertNotContains(response, "cash settlement")

    def test_synthetic_sentinel_is_absent_from_error_and_unauthorized_views(self):
        sentinel = f"SYNTHETIC_PRIVATE_SENTINEL_{uuid.uuid4().hex}"
        _revision, intent, observation, _result = self.delivered_claim(note=sentinel)
        _delivery, candidate = self.admit_inbound(
            kind="lifecycle", intent=intent, observation=observation,
        )
        candidate_url = reverse("outcomes_candidate_detail", kwargs={
            "organization_id": self.alpha.id,
            "candidate_id": candidate.candidate_id,
        })
        authorized = Client()
        authorized.force_login(self.alpha_user)
        error_response = authorized.post(candidate_url, {
            "action": "accept",
            "accept-request_uuid": str(uuid.uuid4()),
            "accept-target_id": str(uuid.uuid4()),
        })
        self.assertEqual(error_response.status_code, 200)
        self.assertNotContains(error_response, sentinel)

        unauthorized = Client()
        unauthorized.force_login(self.beta_user)
        for url in (
            candidate_url,
            reverse("archive_encounter", kwargs={
                "organization_id": self.alpha.id,
                "encounter_id": intent.claim_revision.encounter_id,
            }),
        ):
            with self.subTest(url=url):
                response = unauthorized.get(url)
                self.assertEqual(response.status_code, 404)
                self.assertNotContains(response, sentinel, status_code=404)
