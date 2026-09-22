from __future__ import annotations

import uuid

from medicafe_v1.access.models import Membership
from medicafe_v1.claims.commands import prepare_claim_revision, select_synthetic_policy
from medicafe_v1.claims.delivery_commands import request_delivery
from medicafe_v1.claims.delivery_worker import run_delivery_worker_once
from medicafe_v1.claims.models import DeliveryAttempt
from medicafe_v1.records.commands import revise_service

from .base import F3TransactionTestCase
from .test_worker import AcceptedAdapter


class DispatchBoundaryRaceTests(F3TransactionTestCase):
    def prepared_delivery(self):
        _, revision, _ = self.approved_claim()
        requested = request_delivery(
            actor=self.alpha_user, organization_id=self.alpha.id,
            request_id=uuid.uuid4(), claim_revision_id=revision.id,
            expected_envelope_digest=revision.envelope_digest,
        )
        return revision, requested

    def mutate_service(self, revision):
        service = revision.lines.select_related("service__current_revision").first().service
        current = service.current_revision
        revise_service(
            actor=self.alpha_user, organization_id=self.alpha.id,
            request_id=uuid.uuid4(), service_id=service.id,
            expected_revision_id=current.id,
            evidence_observation_id=current.evidence_observation_id,
            disposition="accepted", code=current.code, units=current.units,
            unit_amount=current.unit_amount, currency=current.currency,
            reason="Synthetic boundary correction", artifact_store=self.store,
        )

    def mutate_claim(self, revision):
        prepare_claim_revision(
            actor=self.alpha_user, organization_id=self.alpha.id,
            request_id=uuid.uuid4(), encounter_id=revision.encounter_id,
            expected_claim_revision_id=revision.id,
            selected_service_revision_ids=list(
                revision.lines.order_by("ordinal").values_list("service_revision_id", flat=True)
            ),
            route_id=revision.route_id, route_version=revision.route_version,
            reason="Synthetic boundary claim revision",
        )

    def mutate_policy(self, revision):
        select_synthetic_policy(
            actor=self.alpha_user, organization_id=self.alpha.id,
            request_id=uuid.uuid4(), expected_version="synthetic-v1",
            expected_generation=1, version="synthetic-v2",
        )

    def mutate_membership(self, revision):
        Membership.objects.filter(
            organization=self.alpha, user=self.alpha_user
        ).update(is_active=False)

    def test_each_mutation_class_committed_before_marker_prevents_send(self):
        mutations = (
            ("service", self.mutate_service),
            ("claim", self.mutate_claim),
            ("policy", self.mutate_policy),
            ("membership", self.mutate_membership),
        )
        for name, mutation in mutations:
            with self.subTest(mutation=name):
                revision, requested = self.prepared_delivery()
                mutation(revision)
                adapter = AcceptedAdapter()
                result = run_delivery_worker_once(
                    worker_id=f"before-{name}-{uuid.uuid4()}",
                    lease_seconds=2, adapter=adapter,
                )
                self.assertEqual(result.reason_code, "delivery_blocked")
                self.assertEqual(adapter.sent, [])
                attempt = DeliveryAttempt.objects.get(intent_id=requested.intent_id)
                self.assertFalse(attempt.possible_dispatch)
                if name == "membership":
                    Membership.objects.filter(
                        organization=self.alpha, user=self.alpha_user
                    ).update(is_active=True)
                if name == "policy":
                    select_synthetic_policy(
                        actor=self.alpha_user, organization_id=self.alpha.id,
                        request_id=uuid.uuid4(), expected_version="synthetic-v2",
                        expected_generation=2, version="synthetic-v1",
                    )

    def test_policy_change_after_marker_keeps_frozen_authorized_bytes(self):
        revision, requested = self.prepared_delivery()
        adapter = AcceptedAdapter()

        result = run_delivery_worker_once(
            worker_id="after-boundary", lease_seconds=2, adapter=adapter,
            after_marker=lambda frozen: self.mutate_policy(revision),
        )

        self.assertEqual(result.reason_code, "receiver_evidence_recorded")
        self.assertEqual(len(adapter.sent), 1)
        self.assertEqual(adapter.sent[0].payload, bytes(revision.envelope_bytes))
        attempt = DeliveryAttempt.objects.get(intent_id=requested.intent_id)
        self.assertTrue(attempt.possible_dispatch)
        self.assertEqual(str(attempt.id), adapter.sent[0].attempt_id)
