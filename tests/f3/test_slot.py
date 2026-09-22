from __future__ import annotations

import uuid

from django.db import DatabaseError, connection, transaction
from django.utils import timezone

from medicafe_v1.claims.commands import approve_claim_revision, prepare_claim_revision
from medicafe_v1.claims.delivery_adapter import ReceiverEvidence, TransportResult
from medicafe_v1.claims.delivery_commands import (
    cancel_before_dispatch, request_delivery, retry_idempotent_delivery,
)
from medicafe_v1.claims.delivery_worker import run_delivery_worker_once
from medicafe_v1.claims.models import ClaimDeliveryControl, ClaimRevision
from medicafe_v1.sources.domain import CommandError

from .base import F3TransactionTestCase
from .test_reconciliation import UnknownTransportAdapter
from .test_worker import AcceptedAdapter


class RejectedAdapter:
    timeout = 0.1

    def validate_configuration(self, receiver_id, version):
        return None

    def send(self, frozen, *, test_mode=None):
        return TransportResult("rejected", "receiver_rejected")

    def readback(self, frozen):
        return ReceiverEvidence(
            state="rejected", receiver_id=frozen.receiver_id,
            receiver_version=frozen.receiver_version,
            organization_id=frozen.organization_id, intent_id=frozen.intent_id,
            claim_revision_id=frozen.claim_revision_id, delivery_key=frozen.delivery_key,
            receipt_id=f"rejection-{frozen.attempt_id}",
            reported_attempt_id=frozen.attempt_id,
            envelope_digest=frozen.envelope_digest, byte_length=frozen.byte_length,
            received_bytes=frozen.payload, no_acceptance_guaranteed=True,
            observed_at=timezone.now().isoformat(),
        )


class ClaimDeliveryControlTests(F3TransactionTestCase):
    def next_revision(self, revision, *, route_version=None):
        prepared = prepare_claim_revision(
            actor=self.alpha_user, organization_id=self.alpha.id,
            request_id=uuid.uuid4(), encounter_id=revision.encounter_id,
            expected_claim_revision_id=revision.id,
            selected_service_revision_ids=list(
                revision.lines.order_by("ordinal").values_list("service_revision_id", flat=True)
            ),
            route_id="synthetic-receiver",
            route_version=route_version or revision.route_version,
            reason="Synthetic next delivery revision",
        )
        successor = ClaimRevision.objects.get(id=prepared.revision_id)
        approve_claim_revision(
            actor=self.alpha_user, organization_id=self.alpha.id,
            request_id=uuid.uuid4(), claim_revision_id=successor.id,
            expected_envelope_digest=successor.envelope_digest,
        )
        return successor

    def request(self, revision):
        return request_delivery(
            actor=self.alpha_user, organization_id=self.alpha.id,
            request_id=uuid.uuid4(), claim_revision_id=revision.id,
            expected_envelope_digest=revision.envelope_digest,
        )

    def test_safe_cancellation_allows_only_monotone_successor_slot_advance(self):
        claim, revision, _ = self.approved_claim()
        first = self.request(revision)
        cancel_before_dispatch(
            actor=self.alpha_user, organization_id=self.alpha.id,
            request_id=uuid.uuid4(), intent_id=first.intent_id,
        )
        successor = self.next_revision(revision, route_version="v2")
        second = self.request(successor)
        control = ClaimDeliveryControl.objects.get(claim=claim)
        self.assertEqual(control.current_intent_id, second.intent_id)

        with self.assertRaises(DatabaseError), transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute(
                    "UPDATE claims_claimdeliverycontrol SET current_intent_id=%s WHERE id=%s",
                    (first.intent_id, control.id),
                )

    def test_unknown_or_accepted_prior_effect_blocks_new_revision(self):
        for adapter, expected_reason in (
            (UnknownTransportAdapter(), "prior_delivery_unresolved"),
            (AcceptedAdapter(), "prior_delivery_accepted"),
        ):
            with self.subTest(expected_reason=expected_reason):
                _, revision, _ = self.approved_claim()
                first = self.request(revision)
                run_delivery_worker_once(
                    worker_id=f"slot-{uuid.uuid4()}", lease_seconds=2, adapter=adapter
                )
                successor = self.next_revision(revision)
                with self.assertRaises(CommandError) as raised:
                    self.request(successor)
                self.assertEqual(raised.exception.reason_code, expected_reason)
                self.assertEqual(
                    ClaimDeliveryControl.objects.get(claim=revision.claim).current_intent_id,
                    first.intent_id,
                )

    def test_verified_rejection_for_every_possible_attempt_releases_slot(self):
        claim, revision, _ = self.approved_claim()
        first = self.request(revision)
        result = run_delivery_worker_once(
            worker_id="rejected-slot", lease_seconds=2, adapter=RejectedAdapter()
        )
        self.assertEqual(result.reason_code, "receiver_evidence_recorded")
        successor = self.next_revision(revision)
        second = self.request(successor)
        self.assertNotEqual(first.intent_id, second.intent_id)
        self.assertEqual(ClaimDeliveryControl.objects.get(claim=claim).current_intent_id, second.intent_id)

    def test_retry_rejection_does_not_release_earlier_unknown_attempt(self):
        _, revision, _ = self.approved_claim()
        first = self.request(revision)
        unknown = run_delivery_worker_once(
            worker_id="unknown-slot", lease_seconds=2, adapter=UnknownTransportAdapter()
        )
        retry_idempotent_delivery(
            actor=self.alpha_user, organization_id=self.alpha.id,
            request_id=uuid.uuid4(), intent_id=first.intent_id,
            expected_attempt_id=unknown.attempt_id,
        )
        run_delivery_worker_once(
            worker_id="rejected-retry", lease_seconds=2, adapter=RejectedAdapter()
        )
        successor = self.next_revision(revision)
        with self.assertRaises(CommandError) as raised:
            self.request(successor)
        self.assertEqual(raised.exception.reason_code, "prior_delivery_unresolved")
