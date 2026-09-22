from __future__ import annotations

import uuid
from decimal import Decimal

from django.test import Client
from django.urls import reverse

from medicafe_v1.claims.commands import prepare_claim_revision
from medicafe_v1.claims.models import Claim, ClaimApproval, ClaimRevision, SyntheticPolicySelection
from medicafe_v1.records.models import ServiceRevision

from tests.f2.base import F2TestCase


class F2WebBoundaryTests(F2TestCase):
    def setUp(self):
        super().setUp()
        self.browser = Client(enforce_csrf_checks=True)
        self.browser.force_login(self.alpha_user)

    def _csrf(self):
        return self.browser.cookies["csrftoken"].value

    def test_invalid_service_claim_and_policy_posts_preserve_request_ids_without_mutation(self):
        _delivery, observation, resolved = self.resolved_observation(
            note="SYNTHETIC_F2_WEB_FORM_ERRORS"
        )
        service = self.accepted_service(
            resolved,
            observation,
            code="SYN-A",
            units=1,
            unit_amount=Decimal("4.00"),
            reason="Synthetic web form service",
        )
        service_revision_count = ServiceRevision.objects.filter(
            service_id=service.service_id
        ).count()

        services_url = reverse("encounter_services", kwargs={
            "organization_id": self.alpha.id,
            "encounter_id": resolved.encounter_id,
        })
        self.assertEqual(self.browser.get(services_url).status_code, 200)
        service_request = uuid.uuid4()
        invalid_service = self.browser.post(services_url, data={
            "csrfmiddlewaretoken": self._csrf(),
            "request_uuid": str(service_request),
            "identity_decision_id": str(resolved.decision_id),
            "code": "SYN-A",
            "units": "1",
            "unit_amount": "1.00",
            "currency": "USD",
            "reason": "",
        })
        self.assertEqual(invalid_service.status_code, 200)
        self.assertContains(invalid_service, str(service_request))
        self.assertContains(invalid_service, "This field is required.")
        self.assertEqual(
            ServiceRevision.objects.filter(service_id=service.service_id).count(),
            service_revision_count,
        )

        csrf_rejected_service = self.browser.post(services_url, data={
            "request_uuid": str(uuid.uuid4()),
            "identity_decision_id": str(resolved.decision_id),
            "code": "SYN-A",
            "units": "1",
            "unit_amount": "1.00",
            "currency": "USD",
            "reason": "Synthetic missing CSRF service",
        })
        self.assertEqual(csrf_rejected_service.status_code, 403)
        self.assertEqual(
            ServiceRevision.objects.filter(service_id=service.service_id).count(),
            service_revision_count,
        )

        service_detail_url = reverse("service_detail", kwargs={
            "organization_id": self.alpha.id,
            "service_id": service.service_id,
        })
        self.assertEqual(self.browser.get(service_detail_url).status_code, 200)
        revision_request = uuid.uuid4()
        invalid_revision = self.browser.post(service_detail_url, data={
            "csrfmiddlewaretoken": self._csrf(),
            "request_uuid": str(revision_request),
            "expected_revision_id": str(service.revision_id),
            "identity_decision_id": str(resolved.decision_id),
            "disposition": "accepted",
            "code": "SYN-A",
            "units": "1",
            "unit_amount": "4.00",
            "currency": "USD",
            "reason": "",
        })
        self.assertEqual(invalid_revision.status_code, 200)
        self.assertContains(invalid_revision, str(revision_request))
        self.assertContains(invalid_revision, "This field is required.")
        self.assertEqual(
            ServiceRevision.objects.filter(service_id=service.service_id).count(),
            service_revision_count,
        )

        prepare_url = reverse("prepare_claim", kwargs={
            "organization_id": self.alpha.id,
            "encounter_id": resolved.encounter_id,
        })
        self.assertEqual(self.browser.get(prepare_url).status_code, 200)
        prepare_request = uuid.uuid4()
        invalid_prepare = self.browser.post(prepare_url, data={
            "csrfmiddlewaretoken": self._csrf(),
            "request_uuid": str(prepare_request),
            "expected_claim_revision_id": "",
            "route": "synthetic-receiver/v1",
            "reason": "Synthetic missing selection",
        })
        self.assertEqual(invalid_prepare.status_code, 200)
        self.assertContains(invalid_prepare, str(prepare_request))
        self.assertContains(invalid_prepare, "This field is required.")
        self.assertEqual(Claim.objects.filter(organization=self.alpha).count(), 0)

        csrf_rejected_prepare = self.browser.post(prepare_url, data={
            "request_uuid": str(uuid.uuid4()),
            "expected_claim_revision_id": "",
            "selected_service_revision_ids": [str(service.revision_id)],
            "route": "synthetic-receiver/v1",
            "reason": "Synthetic missing CSRF claim",
        })
        self.assertEqual(csrf_rejected_prepare.status_code, 403)
        self.assertEqual(Claim.objects.filter(organization=self.alpha).count(), 0)

        prepared = prepare_claim_revision(
            actor=self.alpha_user,
            organization_id=self.alpha.id,
            request_id=uuid.uuid4(),
            encounter_id=resolved.encounter_id,
            expected_claim_revision_id=None,
            selected_service_revision_ids=[service.revision_id],
            route_id="synthetic-receiver",
            route_version="v1",
            reason="Synthetic web claim review",
        )
        claim_revision = ClaimRevision.objects.get(pk=prepared.revision_id)
        claim_url = reverse("claim_detail", kwargs={
            "organization_id": self.alpha.id,
            "claim_id": prepared.claim_id,
        })
        self.assertEqual(self.browser.get(claim_url).status_code, 200)
        approval_request = uuid.uuid4()
        invalid_approval = self.browser.post(claim_url, data={
            "csrfmiddlewaretoken": self._csrf(),
            "request_uuid": str(approval_request),
            "claim_revision_id": str(claim_revision.id),
            "expected_envelope_digest": "0" * 64,
        })
        self.assertEqual(invalid_approval.status_code, 200)
        self.assertContains(invalid_approval, str(approval_request))
        self.assertContains(invalid_approval, "claim_envelope_digest_conflict")
        self.assertEqual(ClaimApproval.objects.filter(claim_revision=claim_revision).count(), 0)

        csrf_rejected_approval = self.browser.post(claim_url, data={
            "request_uuid": str(uuid.uuid4()),
            "claim_revision_id": str(claim_revision.id),
            "expected_envelope_digest": claim_revision.envelope_digest,
        })
        self.assertEqual(csrf_rejected_approval.status_code, 403)
        self.assertEqual(ClaimApproval.objects.filter(claim_revision=claim_revision).count(), 0)

        policy_url = reverse("policy_settings", kwargs={
            "organization_id": self.alpha.id,
        })
        self.assertEqual(self.browser.get(policy_url).status_code, 200)
        policy_request = uuid.uuid4()
        invalid_policy = self.browser.post(policy_url, data={
            "csrfmiddlewaretoken": self._csrf(),
            "request_uuid": str(policy_request),
            "expected_version": "synthetic-v1",
            "expected_generation": "999",
            "version": "synthetic-v2",
        })
        self.assertEqual(invalid_policy.status_code, 200)
        self.assertContains(invalid_policy, str(policy_request))
        self.assertContains(invalid_policy, "policy_selection_conflict")
        selection = SyntheticPolicySelection.objects.get(organization=self.alpha)
        self.assertEqual((selection.version, selection.activation_generation), ("synthetic-v1", 1))

        csrf_rejected_policy = self.browser.post(policy_url, data={
            "request_uuid": str(uuid.uuid4()),
            "expected_version": "synthetic-v1",
            "expected_generation": "1",
            "version": "synthetic-v2",
        })
        self.assertEqual(csrf_rejected_policy.status_code, 403)
        selection.refresh_from_db()
        self.assertEqual((selection.version, selection.activation_generation), ("synthetic-v1", 1))

