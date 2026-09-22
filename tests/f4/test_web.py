from __future__ import annotations

import uuid

from django.test import Client
from django.urls import reverse

from medicafe_v1.archival.commands import capture_archive_projection
from medicafe_v1.archival.models import ArchiveBatch, ArchiveProjection
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
