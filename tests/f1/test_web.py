from __future__ import annotations

import uuid

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client
from django.urls import reverse

from medicafe_v1.records.models import IdentityDecision
from medicafe_v1.sources.models import Delivery, ParseResult

from tests.fixtures.synthetic_inputs import CSV_MEDIA_TYPE, SYNTHETIC_SENTINEL, csv_bytes, synthetic_rows
from tests.f1.base import F1TestCase


class WebScopingAndPostTests(F1TestCase):
    def _login(self, user):
        client = Client(enforce_csrf_checks=True)
        self.assertTrue(client.login(username=user.username, password="synthetic-test-password"))
        return client

    def _csrf(self, client, url):
        response = client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertIn("SYNTHETIC FOUNDATION", response.content.decode())
        return client.cookies["csrftoken"].value

    def test_worklist_and_detail_are_organization_scoped(self):
        alpha_delivery = self.admit(
            source_namespace="synthetic-alpha-web",
            content=csv_bytes(synthetic_rows(note="SYNTHETIC_ALPHA_WEB")),
        )
        beta_delivery = self.admit(
            actor=self.beta_user, organization=self.beta, source_namespace="synthetic-beta-web",
            content=csv_bytes(synthetic_rows(note="SYNTHETIC_BETA_WEB")),
        )
        self.parse(alpha_delivery.delivery_id)
        self.parse(beta_delivery.delivery_id, actor=self.beta_user, organization=self.beta)

        alpha_client = self._login(self.alpha_user)
        alpha_worklist = alpha_client.get(reverse("worklist", kwargs={"organization_id": self.alpha.id}))
        self.assertEqual(alpha_worklist.status_code, 200)
        body = alpha_worklist.content.decode()
        self.assertIn("synthetic-alpha-web", body)
        self.assertNotIn("synthetic-beta-web", body)

        alpha_detail = alpha_client.get(reverse(
            "delivery_detail", kwargs={"organization_id": self.alpha.id, "delivery_id": alpha_delivery.delivery_id},
        ))
        self.assertEqual(alpha_detail.status_code, 200)
        self.assertIn("synthetic-alpha-web", alpha_detail.content.decode())
        self.assertNotIn("synthetic-beta-web", alpha_detail.content.decode())
        self.assertEqual(alpha_client.get(reverse(
            "worklist", kwargs={"organization_id": self.beta.id},
        )).status_code, 404)
        self.assertEqual(alpha_client.get(reverse(
            "delivery_detail", kwargs={"organization_id": self.alpha.id, "delivery_id": beta_delivery.delivery_id},
        )).status_code, 404)

        beta_client = self._login(self.beta_user)
        beta_worklist = beta_client.get(reverse("worklist", kwargs={"organization_id": self.beta.id}))
        self.assertEqual(beta_worklist.status_code, 200)
        beta_body = beta_worklist.content.decode()
        self.assertIn("synthetic-beta-web", beta_body)
        self.assertNotIn("synthetic-alpha-web", beta_body)

    def test_upload_and_parse_entrypoints_require_csrf_and_call_commands(self):
        client = self._login(self.alpha_user)
        upload_url = reverse("upload", kwargs={"organization_id": self.alpha.id})
        token = self._csrf(client, upload_url)
        source_key = str(uuid.uuid4())
        content = csv_bytes(synthetic_rows(note="SYNTHETIC_WEB_UPLOAD"))

        no_csrf = client.post(upload_url, {
            "source_namespace": "synthetic-web-upload",
            "source_key": source_key,
            "source_file": SimpleUploadedFile("synthetic.csv", content, content_type=CSV_MEDIA_TYPE),
        })
        self.assertEqual(no_csrf.status_code, 403)

        admitted_response = client.post(upload_url, {
            "csrfmiddlewaretoken": token,
            "source_namespace": "synthetic-web-upload",
            "source_key": source_key,
            "source_file": SimpleUploadedFile("synthetic.csv", content, content_type=CSV_MEDIA_TYPE),
        })
        self.assertEqual(admitted_response.status_code, 302)
        delivery = Delivery.objects.get(organization=self.alpha, source_namespace="synthetic-web-upload")
        self.assertEqual(admitted_response.url, reverse(
            "delivery_detail", kwargs={"organization_id": self.alpha.id, "delivery_id": delivery.id},
        ))

        parse_url = reverse("parse_delivery", kwargs={"organization_id": self.alpha.id, "delivery_id": delivery.id})
        self.assertEqual(client.get(parse_url).status_code, 405)
        parsed_response = client.post(parse_url, {"csrfmiddlewaretoken": token})
        self.assertEqual(parsed_response.status_code, 302)
        self.assertEqual(ParseResult.objects.filter(delivery=delivery).count(), 1)

    def test_observation_resolution_post_is_explicit_and_scoped(self):
        admitted = self.admit(content=csv_bytes(synthetic_rows(note=SYNTHETIC_SENTINEL)))
        self.parse(admitted.delivery_id)
        observation = self.first_observation(admitted.delivery_id)
        client = self._login(self.alpha_user)
        detail_url = reverse("observation_detail", kwargs={"organization_id": self.alpha.id, "observation_id": observation.id})
        token = self._csrf(client, detail_url)
        request_uuid = str(uuid.uuid4())

        response = client.post(detail_url, {
            "csrfmiddlewaretoken": token,
            "request_uuid": request_uuid,
            "mode": "create",
            "reason": "Synthetic explicit web review",
            "display_name": "Synthetic Web Patient",
            "alias_namespace": "synthetic-web",
            "alias_value": "000042",
            "service_date": "2026-01-15",
        })
        self.assertEqual(response.status_code, 302)
        self.assertEqual(IdentityDecision.objects.filter(organization=self.alpha, observation=observation).count(), 1)
        self.assertEqual(response.url, detail_url)

        detail = client.get(detail_url)
        self.assertEqual(detail.status_code, 200)
        self.assertIn(SYNTHETIC_SENTINEL, detail.content.decode())
        self.assertIn("Accepted identity", detail.content.decode())

        beta_client = self._login(self.beta_user)
        self.assertEqual(beta_client.get(detail_url).status_code, 404)

    def test_anonymous_user_is_redirected_to_login(self):
        response = Client().get(reverse("worklist", kwargs={"organization_id": self.alpha.id}))
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("login"), response.url)
