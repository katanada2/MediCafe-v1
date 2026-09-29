from __future__ import annotations

import json
import uuid

from django.utils import timezone

from medicafe_v1.claims.delivery_adapter import ReceiverEvidence, TransportResult
from medicafe_v1.claims.delivery_commands import request_delivery
from medicafe_v1.claims.delivery_worker import run_delivery_worker_once
from medicafe_v1.claims.models import DeliveryIntent, ReceiverObservation
from medicafe_v1.outcomes.commands import interpret_inbound

from tests.f3.base import F3TestCase, F3TransactionTestCase


class AcceptedAdapter:
    timeout = 0.1

    def validate_configuration(self, receiver_id, version):
        return None

    def send(self, frozen, *, test_mode=None):
        return TransportResult("accepted", "receiver_response")

    def readback(self, frozen):
        return ReceiverEvidence(
            state="accepted", receiver_id=frozen.receiver_id,
            receiver_version=frozen.receiver_version,
            organization_id=frozen.organization_id, intent_id=frozen.intent_id,
            claim_revision_id=frozen.claim_revision_id,
            delivery_key=frozen.delivery_key,
            receipt_id=f"outcomes-receipt-{frozen.attempt_id}",
            reported_attempt_id=frozen.attempt_id,
            envelope_digest=frozen.envelope_digest, byte_length=frozen.byte_length,
            received_bytes=frozen.payload, no_acceptance_guaranteed=False,
            observed_at=timezone.now().isoformat(),
        )


class F4FixtureMixin:
    def delivered_claim(self, *, route_version="v1", note="SYNTHETIC_F2_OBSERVATION"):
        _claim, revision, _approval = self.approved_claim(
            route_version=route_version,
            note=note,
        )
        requested = request_delivery(
            actor=self.alpha_user, organization_id=self.alpha.id,
            request_id=uuid.uuid4(), claim_revision_id=revision.id,
            expected_envelope_digest=revision.envelope_digest,
        )
        result = run_delivery_worker_once(
            worker_id=f"f4-delivery-{uuid.uuid4()}", lease_seconds=2,
            adapter=AcceptedAdapter(),
        )
        intent = DeliveryIntent.objects.get(id=requested.intent_id)
        observation = ReceiverObservation.objects.get(
            intent=intent, observed_state=ReceiverObservation.STATE_ACCEPTED,
            binding_valid=True,
        )
        return revision, intent, observation, result

    def inbound_document(self, *, kind, intent, observation, event_id=None,
                         lines=None, sequence=1, predecessor_event_id=None):
        value = {
            "schema_version": "synthetic-outcomes-v1",
            "kind": kind,
            "sender_id": f"synthetic-sender-{intent.receiver_version}",
            "event_id": str(event_id or uuid.uuid4()),
            "delivery_key": str(intent.delivery_key),
            "intent_id": str(intent.id),
            "claim_revision_id": str(intent.claim_revision_id),
            "receiver_receipt_id": observation.receipt_id,
        }
        if kind == "lifecycle":
            value.update({
                "lifecycle_sequence": sequence,
                "predecessor_event_id": (
                    str(predecessor_event_id) if predecessor_event_id else None
                ),
                "status": "ACK_ACCEPTED",
            })
        else:
            value.update({
                "currency": "USD",
                "lines": lines or [{
                    "line_ordinal": 1,
                    "paid_amount": "4.00",
                    "contractual_adjustment": "1.00",
                }],
            })
        return json.dumps(value, separators=(",", ":")).encode("utf-8")

    def admit_inbound(self, *, kind, intent, observation, content=None,
                      source_key=None, **document_kwargs):
        content = content or self.inbound_document(
            kind=kind, intent=intent, observation=observation, **document_kwargs
        )
        admitted = self.admit(
            content=content, source_key=source_key,
            source_namespace=f"synthetic-{kind}", media_type="application/json",
        )
        interpreted = interpret_inbound(
            actor=self.alpha_user, organization_id=self.alpha.id,
            delivery_id=admitted.delivery_id, artifact_store=self.store,
        )
        return admitted, interpreted


class F4TestCase(F4FixtureMixin, F3TestCase):
    pass


class F4TransactionTestCase(F4FixtureMixin, F3TransactionTestCase):
    pass
