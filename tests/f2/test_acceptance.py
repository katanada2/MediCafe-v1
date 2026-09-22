from __future__ import annotations

import uuid
from decimal import Decimal
from unittest.mock import patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client
from django.urls import reverse

from medicafe_v1.claims.commands import (
    approve_claim_revision,
    prepare_claim_revision,
    select_synthetic_policy,
)
from medicafe_v1.claims.models import Claim, ClaimApproval, ClaimLine, ClaimRevision
from medicafe_v1.records.commands import ResolutionIntent, resolve_identity, revise_service
from medicafe_v1.records.models import IdentityDecision, Service, ServiceRevision
from medicafe_v1.sources.domain import CommandError
from medicafe_v1.sources.models import Delivery

from tests.f2.base import F2TestCase
from tests.fixtures.synthetic_inputs import (
    CSV_MEDIA_TYPE,
    DOCX_MEDIA_TYPE,
    csv_bytes,
    docx_bytes,
    synthetic_rows,
)
from tests.helpers.f2_claim_boundary import assert_claim_boundary


class F2AcceptanceTests(F2TestCase):
    def _csrf(self, client):
        return client.cookies["csrftoken"].value

    def _post_with_csrf(self, client, url, data):
        return client.post(url, {**data, "csrfmiddlewaretoken": self._csrf(client)})

    def _run_authenticated_source_claim_flow(self, *, content, media_type, filename, note):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.alpha_user)

        upload_url = reverse("upload", kwargs={"organization_id": self.alpha.id})
        self.assertEqual(client.get(upload_url).status_code, 200)
        source_key = uuid.uuid4()
        upload = self._post_with_csrf(client, upload_url, {
            "source_namespace": "synthetic-acceptance",
            "source_key": str(source_key),
            "source_file": SimpleUploadedFile(filename, content, content_type=media_type),
        })
        self.assertEqual(upload.status_code, 302)
        delivery = Delivery.objects.get(organization=self.alpha, source_key=str(source_key))

        parse_url = reverse("parse_delivery", kwargs={
            "organization_id": self.alpha.id,
            "delivery_id": delivery.id,
        })
        parsed = self._post_with_csrf(client, parse_url, {})
        self.assertEqual(parsed.status_code, 302)
        observation = self.first_observation(delivery.id)

        observation_url = reverse("observation_detail", kwargs={
            "organization_id": self.alpha.id,
            "observation_id": observation.id,
        })
        self.assertEqual(client.get(observation_url).status_code, 200)
        identity_request = uuid.uuid4()
        resolved = self._post_with_csrf(client, observation_url, {
            "request_uuid": str(identity_request),
            "mode": "create",
            "reason": f"Synthetic authenticated {note} identity",
            "display_name": f"Synthetic {note} Patient",
            "service_date": "2026-01-15",
            "alias_namespace": "",
            "alias_value": "",
        })
        self.assertEqual(resolved.status_code, 302)
        decision = IdentityDecision.objects.get(
            organization=self.alpha, observation=observation
        )

        services_url = reverse("encounter_services", kwargs={
            "organization_id": self.alpha.id,
            "encounter_id": decision.encounter_id,
        })
        self.assertEqual(client.get(services_url).status_code, 200)
        accepted = self._post_with_csrf(client, services_url, {
            "request_uuid": str(uuid.uuid4()),
            "identity_decision_id": str(decision.id),
            "code": "SYN-A",
            "units": "2",
            "unit_amount": "4.25",
            "currency": "USD",
            "reason": f"Synthetic authenticated {note} service",
        })
        self.assertEqual(accepted.status_code, 302)
        service = Service.objects.get(organization=self.alpha, identity_decision=decision)

        prepare_url = reverse("prepare_claim", kwargs={
            "organization_id": self.alpha.id,
            "encounter_id": decision.encounter_id,
        })
        self.assertEqual(client.get(prepare_url).status_code, 200)
        prepared = self._post_with_csrf(client, prepare_url, {
            "request_uuid": str(uuid.uuid4()),
            "expected_claim_revision_id": "",
            "selected_service_revision_ids": [str(service.current_revision_id)],
            "route": "synthetic-receiver/v1",
            "reason": f"Synthetic authenticated {note} claim",
        })
        self.assertEqual(prepared.status_code, 302)
        claim = Claim.objects.get(organization=self.alpha, encounter_id=decision.encounter_id)
        revision = ClaimRevision.objects.get(pk=claim.current_revision_id)
        assert_claim_boundary(
            self,
            delivery=delivery,
            claim_revision=revision,
            expected_service_revisions=[service.current_revision_id],
            expected_total=Decimal("8.50"),
        )

        claim_url = reverse("claim_detail", kwargs={
            "organization_id": self.alpha.id,
            "claim_id": claim.id,
        })
        self.assertEqual(client.get(claim_url).status_code, 200)
        approved = self._post_with_csrf(client, claim_url, {
            "request_uuid": str(uuid.uuid4()),
            "claim_revision_id": str(revision.id),
            "expected_envelope_digest": revision.envelope_digest,
        })
        self.assertEqual(approved.status_code, 302)
        detail = client.get(claim_url)
        self.assertEqual(detail.status_code, 200)
        self.assertContains(detail, "Approved for current synthetic inputs")
        self.assertContains(detail, "Synthetic only")
        self.assertContains(detail, "not payer submission or payment approval")
        self.assertEqual(ClaimApproval.objects.filter(claim_revision=revision).count(), 1)
        return delivery, observation, decision, service, claim, revision

    def test_authenticated_csv_and_docx_flow_through_service_claim_and_approval_views(self):
        self._run_authenticated_source_claim_flow(
            content=csv_bytes(synthetic_rows(note="SYNTHETIC_AUTHENTICATED_CSV")),
            media_type=CSV_MEDIA_TYPE,
            filename="synthetic.csv",
            note="CSV",
        )
        self._run_authenticated_source_claim_flow(
            content=docx_bytes(synthetic_rows(note="SYNTHETIC_AUTHENTICATED_DOCX")),
            media_type=DOCX_MEDIA_TYPE,
            filename="synthetic.docx",
            note="DOCX",
        )

    def test_service_revision_post_without_csrf_is_rejected_without_mutation(self):
        _delivery, observation, resolved = self.resolved_observation(
            note="SYNTHETIC_SERVICE_REVISION_CSRF"
        )
        accepted = self.accepted_service(
            resolved,
            observation,
            code="SYN-A",
            units=1,
            unit_amount="4.00",
            reason="Synthetic CSRF service",
        )
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.alpha_user)
        url = reverse("service_detail", kwargs={
            "organization_id": self.alpha.id,
            "service_id": accepted.service_id,
        })
        self.assertEqual(client.get(url).status_code, 200)
        before = ServiceRevision.objects.filter(service_id=accepted.service_id).count()
        rejected = client.post(url, {
            "request_uuid": str(uuid.uuid4()),
            "expected_revision_id": str(accepted.revision_id),
            "identity_decision_id": str(resolved.decision_id),
            "disposition": "accepted",
            "code": "SYN-A",
            "units": "1",
            "unit_amount": "5.00",
            "currency": "USD",
            "reason": "Synthetic missing CSRF revision",
        })
        self.assertEqual(rejected.status_code, 403)
        self.assertEqual(ServiceRevision.objects.filter(service_id=accepted.service_id).count(), before)

    def test_reparse_and_corrected_source_preserve_service_history_then_record_exclusion_reinstatement(self):
        original, observation, resolved = self.resolved_observation(
            note="SYNTHETIC_ORIGINAL_SOURCE"
        )
        accepted = self.accepted_service(
            resolved,
            observation,
            code="SYN-A",
            units=2,
            unit_amount="4.00",
            reason="Synthetic original accepted service",
        )
        original_revision = ServiceRevision.objects.get(pk=accepted.revision_id)
        original_snapshot = {
            "code": original_revision.code,
            "units": original_revision.units,
            "unit_amount": original_revision.unit_amount,
            "evidence_observation_id": original_revision.evidence_observation_id,
        }

        self.assertEqual(self.parse(original.id).reason_code, "parse_replayed")
        corrected_result = self.admit(
            content=csv_bytes(synthetic_rows(note="SYNTHETIC_CORRECTED_SOURCE", row_id="row-002")),
            source_key=str(uuid.uuid4()),
            supersedes_id=original.id,
        )
        self.assertEqual(self.parse(corrected_result.delivery_id).reason_code, "parse_succeeded")
        corrected_delivery = self.delivery(corrected_result.delivery_id)
        corrected_observation = self.first_observation(corrected_delivery.id)
        attached = resolve_identity(
            actor=self.alpha_user,
            organization_id=self.alpha.id,
            observation_id=corrected_observation.id,
            request_uuid=uuid.uuid4(),
            intent=ResolutionIntent(
                mode="attach",
                reason="Synthetic corrected source confirms same encounter",
                patient_id=str(resolved.patient_id),
                encounter_id=str(resolved.encounter_id),
            ),
            artifact_store=self.store,
        )
        self.assertEqual(attached.encounter_id, resolved.encounter_id)
        self.assertEqual(ServiceRevision.objects.filter(service_id=accepted.service_id).count(), 1)
        unchanged = ServiceRevision.objects.get(pk=original_revision.id)
        self.assertEqual({
            "code": unchanged.code,
            "units": unchanged.units,
            "unit_amount": unchanged.unit_amount,
            "evidence_observation_id": unchanged.evidence_observation_id,
        }, original_snapshot)

        excluded = revise_service(
            actor=self.alpha_user,
            organization_id=self.alpha.id,
            request_id=uuid.uuid4(),
            service_id=accepted.service_id,
            expected_revision_id=accepted.revision_id,
            evidence_observation_id=corrected_observation.id,
            disposition="excluded",
            reason="Synthetic explicit exclusion",
            artifact_store=self.store,
        )
        excluded_revision = ServiceRevision.objects.get(pk=excluded.revision_id)
        reinstated = revise_service(
            actor=self.alpha_user,
            organization_id=self.alpha.id,
            request_id=uuid.uuid4(),
            service_id=accepted.service_id,
            expected_revision_id=excluded.revision_id,
            evidence_observation_id=corrected_observation.id,
            disposition="accepted",
            code="SYN-B",
            units=1,
            unit_amount="6.50",
            currency="USD",
            reason="Synthetic explicit reinstatement",
            artifact_store=self.store,
        )
        reinstated_revision = ServiceRevision.objects.get(pk=reinstated.revision_id)
        self.assertEqual(excluded_revision.disposition, "excluded")
        self.assertEqual(excluded_revision.predecessor_id, original_revision.id)
        self.assertEqual(excluded_revision.evidence_observation_id, corrected_observation.id)
        self.assertEqual(excluded_revision.reason, "Synthetic explicit exclusion")
        self.assertEqual(reinstated_revision.disposition, "accepted")
        self.assertEqual(reinstated_revision.predecessor_id, excluded_revision.id)
        self.assertEqual(reinstated_revision.evidence_observation_id, corrected_observation.id)
        self.assertEqual(reinstated_revision.reason, "Synthetic explicit reinstatement")

    def test_logs_and_error_summaries_redact_sentinel_but_authorized_detail_shows_it(self):
        sentinel = "SYNTHETIC_SENSITIVE_ACCEPTANCE_SENTINEL"
        malformed = (sentinel + "\nnot,a,valid,header\n").encode()
        with self.assertLogs("medicafe_v1.sources.commands", level="INFO") as captured:
            admitted = self.admit(content=malformed, source_key=str(uuid.uuid4()))
            with self.assertRaises(CommandError) as failure:
                self.parse(admitted.delivery_id)
        self.assertNotIn(sentinel, "\n".join(captured.output))
        self.assertNotIn(sentinel, str(failure.exception))

        delivery, _observation, _resolved = self.resolved_observation(note=sentinel)
        client = Client()
        client.force_login(self.alpha_user)
        detail = client.get(reverse("delivery_detail", kwargs={
            "organization_id": self.alpha.id,
            "delivery_id": delivery.id,
        }))
        self.assertEqual(detail.status_code, 200)
        self.assertNotContains(detail, sentinel)
        observation = self.first_observation(delivery.id)
        observation_detail = client.get(reverse("observation_detail", kwargs={
            "organization_id": self.alpha.id,
            "observation_id": observation.id,
        }))
        self.assertContains(observation_detail, sentinel)

    def test_maximum_lines_and_amounts_and_oversize_envelope_are_atomic(self):
        _delivery, observation, resolved = self.resolved_observation(
            note="SYNTHETIC_MAXIMUM_CLAIM"
        )
        services = [self.accepted_service(
            resolved,
            observation,
            request_id=uuid.uuid5(uuid.NAMESPACE_URL, f"synthetic-maximum-{index}"),
            code="SYN-A",
            units=100,
            unit_amount="9999.99",
            reason=f"Synthetic maximum line {index}",
        ) for index in range(100)]
        prepared = prepare_claim_revision(
            actor=self.alpha_user,
            organization_id=self.alpha.id,
            request_id=uuid.uuid4(),
            encounter_id=resolved.encounter_id,
            expected_claim_revision_id=None,
            selected_service_revision_ids=[item.revision_id for item in services],
            route_id="synthetic-receiver",
            route_version="v1",
            reason="Synthetic maximum claim",
        )
        revision = ClaimRevision.objects.get(pk=prepared.revision_id)
        self.assertEqual(revision.lines.count(), 100)
        self.assertEqual(revision.total_amount, Decimal("99999900.00"))
        self.assertEqual(ClaimLine.objects.filter(claim_revision=revision).count(), 100)

        _delivery, oversized_observation, oversized_resolved = self.resolved_observation(
            note="SYNTHETIC_OVERSIZE_ENVELOPE"
        )
        oversized_service = self.accepted_service(
            oversized_resolved,
            oversized_observation,
            code="SYN-A",
            units=1,
            unit_amount="1.00",
            reason="Synthetic oversize envelope service",
        )
        before = (
            Claim.objects.filter(organization=self.alpha).count(),
            ClaimRevision.objects.filter(organization=self.alpha).count(),
            ClaimLine.objects.filter(organization=self.alpha).count(),
        )
        with patch("medicafe_v1.claims.commands.MAX_ENVELOPE_BYTES", 1):
            with self.assertRaises(CommandError) as oversized:
                prepare_claim_revision(
                    actor=self.alpha_user,
                    organization_id=self.alpha.id,
                    request_id=uuid.uuid4(),
                    encounter_id=oversized_resolved.encounter_id,
                    expected_claim_revision_id=None,
                    selected_service_revision_ids=[oversized_service.revision_id],
                    route_id="synthetic-receiver",
                    route_version="v1",
                    reason="Synthetic forced oversize envelope",
                )
        self.assertEqual(oversized.exception.reason_code, "claim_envelope_too_large")
        self.assertEqual(before, (
            Claim.objects.filter(organization=self.alpha).count(),
            ClaimRevision.objects.filter(organization=self.alpha).count(),
            ClaimLine.objects.filter(organization=self.alpha).count(),
        ))

    def test_invalid_selections_leave_no_partial_claim_rows(self):
        _delivery, observation, resolved = self.resolved_observation(
            note="SYNTHETIC_INVALID_SELECTIONS"
        )
        first = self.accepted_service(
            resolved, observation, code="SYN-A", unit_amount="4.00",
            reason="Synthetic selection A",
        )
        duplicate_before = self._claim_counts()
        with self.assertRaises(CommandError) as duplicate:
            self._prepare(resolved, [first.revision_id, first.revision_id])
        self.assertEqual(duplicate.exception.reason_code, "claim_service_duplicate")
        self.assertEqual(self._claim_counts(), duplicate_before)

        old_revision = first.revision_id
        current = revise_service(
            actor=self.alpha_user,
            organization_id=self.alpha.id,
            request_id=uuid.uuid4(),
            service_id=first.service_id,
            expected_revision_id=old_revision,
            evidence_observation_id=observation.id,
            disposition="accepted",
            code="SYN-A",
            units=1,
            unit_amount="5.00",
            currency="USD",
            reason="Synthetic current head correction",
            artifact_store=self.store,
        )
        old_head_before = self._claim_counts()
        with self.assertRaises(CommandError) as old_head:
            self._prepare(resolved, [old_revision])
        self.assertEqual(old_head.exception.reason_code, "selected_service_not_current")
        self.assertEqual(self._claim_counts(), old_head_before)

        excluded = self.accepted_service(
            resolved, observation, code="SYN-A", unit_amount="3.00",
            reason="Synthetic exclusion candidate",
        )
        excluded_result = revise_service(
            actor=self.alpha_user,
            organization_id=self.alpha.id,
            request_id=uuid.uuid4(),
            service_id=excluded.service_id,
            expected_revision_id=excluded.revision_id,
            evidence_observation_id=observation.id,
            disposition="excluded",
            reason="Synthetic excluded service",
            artifact_store=self.store,
        )
        excluded_before = self._claim_counts()
        with self.assertRaises(CommandError) as excluded_error:
            self._prepare(resolved, [excluded_result.revision_id])
        self.assertEqual(excluded_error.exception.reason_code, "selected_service_excluded")
        self.assertEqual(self._claim_counts(), excluded_before)

        _other_delivery, other_observation, other_resolved = self.resolved_observation(
            note="SYNTHETIC_MIXED_ENCOUNTER"
        )
        other = self.accepted_service(
            other_resolved, other_observation, code="SYN-A", unit_amount="2.00",
            reason="Synthetic other encounter service",
        )
        mixed_before = self._claim_counts()
        with self.assertRaises(CommandError) as mixed:
            self._prepare(resolved, [current.revision_id, other.revision_id])
        self.assertEqual(mixed.exception.reason_code, "selected_service_not_current")
        self.assertEqual(self._claim_counts(), mixed_before)

        policy_service = self.accepted_service(
            other_resolved, other_observation, code="SYN-B", unit_amount="2.00",
            reason="Synthetic policy rejection service",
        )
        changed = select_synthetic_policy(
            actor=self.alpha_user,
            organization_id=self.alpha.id,
            request_id=uuid.uuid4(),
            expected_version="synthetic-v1",
            expected_generation=1,
            version="synthetic-v2",
        )
        self.assertEqual(changed.policy_version, "synthetic-v2")
        policy_before = self._claim_counts()
        with self.assertRaises(CommandError) as policy_rejected:
            self._prepare(other_resolved, [policy_service.revision_id])
        self.assertEqual(policy_rejected.exception.reason_code, "selected_service_policy_rejected")
        self.assertEqual(self._claim_counts(), policy_before)

    def _claim_counts(self):
        return (
            Claim.objects.filter(organization=self.alpha).count(),
            ClaimRevision.objects.filter(organization=self.alpha).count(),
            ClaimLine.objects.filter(organization=self.alpha).count(),
        )

    def _prepare(self, resolved, revision_ids):
        return prepare_claim_revision(
            actor=self.alpha_user,
            organization_id=self.alpha.id,
            request_id=uuid.uuid4(),
            encounter_id=resolved.encounter_id,
            expected_claim_revision_id=None,
            selected_service_revision_ids=revision_ids,
            route_id="synthetic-receiver",
            route_version="v1",
            reason="Synthetic invalid selection",
        )

    def test_equivalent_uuid_and_money_representations_replay_but_order_change_conflicts(self):
        _delivery, observation, resolved = self.resolved_observation(
            note="SYNTHETIC_EQUIVALENT_REPLAY"
        )
        service_request = uuid.uuid4()
        accepted = self.accepted_service(
            resolved,
            observation,
            request_id=str(service_request),
            code="SYN-A",
            units=1,
            unit_amount=Decimal("4.00"),
            reason="Synthetic equivalent money service",
        )
        replay = self.accepted_service(
            resolved,
            observation,
            request_id=service_request,
            code="SYN-A",
            units=1,
            unit_amount="4.00",
            reason="Synthetic equivalent money service",
        )
        self.assertEqual(replay.reason_code, "service_request_replayed")
        self.assertEqual(replay.revision_id, accepted.revision_id)

        second = self.accepted_service(
            resolved,
            observation,
            code="SYN-A",
            units=1,
            unit_amount="2.00",
            reason="Synthetic ordered replay service",
        )
        claim_request = uuid.uuid4()
        prepared = self._prepare_ordered(resolved, claim_request, [accepted.revision_id, second.revision_id])
        claim_replay = self._prepare_ordered(
            resolved, str(claim_request), [accepted.revision_id, second.revision_id]
        )
        self.assertEqual(claim_replay.reason_code, "claim_request_replayed")
        self.assertEqual(claim_replay.revision_id, prepared.revision_id)
        with self.assertRaises(CommandError) as reordered:
            self._prepare_ordered(
                resolved, claim_request, [second.revision_id, accepted.revision_id]
            )
        self.assertEqual(reordered.exception.reason_code, "request_input_conflict")
        self.assertEqual(ClaimRevision.objects.filter(claim_id=prepared.claim_id).count(), 1)

    def _prepare_ordered(self, resolved, request_id, revision_ids):
        return prepare_claim_revision(
            actor=self.alpha_user,
            organization_id=self.alpha.id,
            request_id=request_id,
            encounter_id=resolved.encounter_id,
            expected_claim_revision_id=None,
            selected_service_revision_ids=revision_ids,
            route_id="synthetic-receiver",
            route_version="v1",
            reason="Synthetic equivalent ordered claim",
        )
