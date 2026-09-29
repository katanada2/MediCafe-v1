from __future__ import annotations

import json
import uuid
from decimal import Decimal

from medicafe_v1.claims.commands import (
    approve_claim_revision,
    prepare_claim_revision,
)
from medicafe_v1.claims.delivery_commands import request_delivery
from medicafe_v1.claims.delivery_worker import run_delivery_worker_once
from medicafe_v1.claims.models import ClaimApproval, ClaimRevision, DeliveryIntent, ReceiverObservation
from medicafe_v1.outcomes.commands import (
    accept_lifecycle,
    interpret_inbound,
    post_remittance,
    reevaluate_candidate,
)
from medicafe_v1.outcomes.models import (
    AcceptedEvent,
    FinancialAccount,
    InboundAttempt,
    InboundCandidate,
    OutcomesCommandReceipt,
    PostingEntry,
)
from medicafe_v1.outcomes.queries import current_lifecycle, ledger_detail
from medicafe_v1.records.commands import revise_service
from medicafe_v1.sources.domain import CommandError
from medicafe_v1.sources.models import Delivery

from .base import AcceptedAdapter, F4TestCase


class F4AcceptanceMatrixTests(F4TestCase):
    def _admit_value(self, value, *, namespace):
        admitted = self.admit(
            content=json.dumps(value, separators=(",", ":")).encode("utf-8"),
            source_namespace=namespace,
            media_type="application/json",
        )
        return admitted, interpret_inbound(
            actor=self.alpha_user,
            organization_id=self.alpha.id,
            delivery_id=admitted.delivery_id,
            artifact_store=self.store,
        )

    def _two_line_delivery(self):
        _delivery, source_observation, resolved = self.resolved_observation(
            note="SYNTHETIC_F4_TWO_LINE",
        )
        first = self.accepted_service(
            resolved,
            source_observation,
            code="SYN-A",
            unit_amount="6.00",
            reason="Synthetic F4 line one",
        )
        second = self.accepted_service(
            resolved,
            source_observation,
            code="SYN-B",
            unit_amount="4.00",
            reason="Synthetic F4 line two",
        )
        prepared = prepare_claim_revision(
            actor=self.alpha_user,
            organization_id=self.alpha.id,
            request_id=uuid.uuid4(),
            encounter_id=resolved.encounter_id,
            expected_claim_revision_id=None,
            selected_service_revision_ids=[first.revision_id, second.revision_id],
            route_id="synthetic-receiver",
            route_version="v1",
            reason="Synthetic F4 two-line claim",
        )
        revision = ClaimRevision.objects.get(id=prepared.revision_id)
        approval = approve_claim_revision(
            actor=self.alpha_user,
            organization_id=self.alpha.id,
            request_id=uuid.uuid4(),
            claim_revision_id=revision.id,
            expected_envelope_digest=revision.envelope_digest,
        )
        requested = request_delivery(
            actor=self.alpha_user,
            organization_id=self.alpha.id,
            request_id=uuid.uuid4(),
            claim_revision_id=revision.id,
            expected_envelope_digest=revision.envelope_digest,
        )
        run_delivery_worker_once(
            worker_id=f"f4-two-line-{uuid.uuid4()}",
            lease_seconds=2,
            adapter=AcceptedAdapter(),
        )
        intent = DeliveryIntent.objects.get(id=requested.intent_id)
        observation = ReceiverObservation.objects.get(
            intent=intent,
            observed_state=ReceiverObservation.STATE_ACCEPTED,
            binding_valid=True,
        )
        self.assertTrue(ClaimApproval.objects.filter(id=approval.approval_id).exists())
        return revision, intent, observation

    def test_json_bounds_and_semantic_failures_are_attributable_and_atomic(self):
        _revision, intent, observation, _result = self.delivered_claim()
        before = Delivery.objects.count()
        with self.assertRaisesMessage(CommandError, "upload_too_large"):
            self.admit(
                content=b"x" * (1024 * 1024 + 1),
                source_namespace="synthetic-remittance",
                media_type="application/json",
            )
        self.assertEqual(Delivery.objects.count(), before)

        base = json.loads(self.inbound_document(
            kind="remittance", intent=intent, observation=observation,
        ))
        invalid = []
        extra = dict(base)
        extra["unexpected"] = True
        invalid.append(extra)
        wrong_schema = dict(base)
        wrong_schema["schema_version"] = "unsupported-v9"
        invalid.append(wrong_schema)
        wrong_currency = dict(base)
        wrong_currency["currency"] = "EUR"
        invalid.append(wrong_currency)
        negative = json.loads(json.dumps(base))
        negative["lines"][0]["paid_amount"] = "-1.00"
        invalid.append(negative)
        precision = json.loads(json.dumps(base))
        precision["lines"][0]["paid_amount"] = "1.001"
        invalid.append(precision)
        zero = json.loads(json.dumps(base))
        zero["lines"][0]["paid_amount"] = "0"
        zero["lines"][0]["contractual_adjustment"] = "0.00"
        invalid.append(zero)
        omitted = dict(base)
        omitted.pop("lines")
        invalid.append(omitted)

        for index, value in enumerate(invalid):
            with self.subTest(index=index):
                admitted = self.admit(
                    content=json.dumps(value, separators=(",", ":")).encode("utf-8"),
                    source_namespace="synthetic-remittance",
                    media_type="application/json",
                )
                with self.assertRaisesMessage(CommandError, "malformed_or_unsupported"):
                    interpret_inbound(
                        actor=self.alpha_user,
                        organization_id=self.alpha.id,
                        delivery_id=admitted.delivery_id,
                        artifact_store=self.store,
                    )
                attempt = InboundAttempt.objects.get(delivery_id=admitted.delivery_id)
                self.assertFalse(attempt.succeeded)
                self.assertFalse(InboundCandidate.objects.filter(
                    delivery_id=admitted.delivery_id,
                ).exists())
        self.assertFalse(AcceptedEvent.objects.exists())
        self.assertFalse(PostingEntry.objects.exists())

    def test_missing_or_corrupt_inbound_bytes_fail_before_candidate(self):
        _revision, intent, observation, _result = self.delivered_claim()
        for mode in ("missing", "corrupt"):
            with self.subTest(mode=mode):
                content = self.inbound_document(
                    kind="lifecycle", intent=intent, observation=observation,
                )
                admitted = self.admit(
                    content=content,
                    source_namespace="synthetic-lifecycle",
                    media_type="application/json",
                )
                delivery = Delivery.objects.select_related("artifact").get(
                    id=admitted.delivery_id,
                )
                path = self.store.root / delivery.artifact.storage_key
                if mode == "missing":
                    path.unlink()
                else:
                    path.write_bytes(b"corrupt synthetic bytes")
                with self.assertRaisesMessage(CommandError, "artifact_unavailable"):
                    interpret_inbound(
                        actor=self.alpha_user,
                        organization_id=self.alpha.id,
                        delivery_id=delivery.id,
                        artifact_store=self.store,
                    )
                self.assertEqual(
                    InboundAttempt.objects.get(delivery=delivery).reason_code,
                    "artifact_unavailable",
                )
                self.assertFalse(InboundCandidate.objects.filter(delivery=delivery).exists())

    def test_source_replay_conflict_event_conflict_and_request_namespace(self):
        _revision, intent, observation, _result = self.delivered_claim()
        source_key = str(uuid.uuid4())
        first_bytes = self.inbound_document(
            kind="lifecycle", intent=intent, observation=observation,
        )
        first = self.admit(
            content=first_bytes,
            source_key=source_key,
            source_namespace="synthetic-lifecycle",
            media_type="application/json",
        )
        replay = self.admit(
            content=first_bytes,
            source_key=source_key,
            source_namespace="synthetic-lifecycle",
            media_type="application/json",
        )
        self.assertEqual(first.delivery_id, replay.delivery_id)
        changed = json.loads(first_bytes)
        changed["status"] = "ACK_REJECTED"
        with self.assertRaisesMessage(CommandError, "delivery_source_conflict"):
            self.admit(
                content=json.dumps(changed).encode("utf-8"),
                source_key=source_key,
                source_namespace="synthetic-lifecycle",
                media_type="application/json",
            )

        interpreted = interpret_inbound(
            actor=self.alpha_user,
            organization_id=self.alpha.id,
            delivery_id=first.delivery_id,
            artifact_store=self.store,
        )
        event_id = InboundCandidate.objects.get(id=interpreted.candidate_id).event_id
        request_id = uuid.uuid4()
        accept_lifecycle(
            actor=self.alpha_user,
            organization_id=self.alpha.id,
            request_id=request_id,
            candidate_id=interpreted.candidate_id,
            artifact_store=self.store,
        )
        conflicting_bytes = self.inbound_document(
            kind="lifecycle",
            intent=intent,
            observation=observation,
            event_id=event_id,
        )
        conflicting = json.loads(conflicting_bytes)
        conflicting["status"] = "ACK_REJECTED"
        _delivery, conflict = self._admit_value(
            conflicting,
            namespace="synthetic-lifecycle",
        )
        with self.assertRaisesMessage(CommandError, "request_reused_with_different_intent"):
            accept_lifecycle(
                actor=self.alpha_user,
                organization_id=self.alpha.id,
                request_id=request_id,
                candidate_id=conflict.candidate_id,
                artifact_store=self.store,
            )
        with self.assertRaisesMessage(CommandError, "conflicting_identity_or_content"):
            accept_lifecycle(
                actor=self.alpha_user,
                organization_id=self.alpha.id,
                request_id=uuid.uuid4(),
                candidate_id=conflict.candidate_id,
                artifact_store=self.store,
            )
        self.assertEqual(AcceptedEvent.objects.count(), 1)
        self.assertEqual(OutcomesCommandReceipt.objects.count(), 1)

    def test_historical_attribution_survives_current_change_and_mismatches_fail_closed(self):
        revision, intent, observation, _result = self.delivered_claim()
        service = revision.lines.select_related("service__current_revision").first().service
        current = service.current_revision
        revised = revise_service(
            actor=self.alpha_user,
            organization_id=self.alpha.id,
            request_id=uuid.uuid4(),
            service_id=service.id,
            expected_revision_id=current.id,
            evidence_observation_id=current.evidence_observation_id,
            disposition="accepted",
            code=current.code,
            units=current.units,
            unit_amount=current.unit_amount + Decimal("1.00"),
            currency=current.currency,
            reason="Synthetic current change after delivery",
            artifact_store=self.store,
        )
        prepare_claim_revision(
            actor=self.alpha_user,
            organization_id=self.alpha.id,
            request_id=uuid.uuid4(),
            encounter_id=revision.encounter_id,
            expected_claim_revision_id=revision.id,
            selected_service_revision_ids=[revised.revision_id],
            route_id=revision.route_id,
            route_version=revision.route_version,
            reason="Synthetic successor claim",
        )
        _delivery, historical = self.admit_inbound(
            kind="lifecycle", intent=intent, observation=observation,
        )
        accepted = accept_lifecycle(
            actor=self.alpha_user,
            organization_id=self.alpha.id,
            request_id=uuid.uuid4(),
            candidate_id=historical.candidate_id,
            artifact_store=self.store,
        )
        self.assertEqual(
            AcceptedEvent.objects.get(id=accepted.event_id).claim_revision_id,
            revision.id,
        )

        for field, replacement, reason in (
            ("sender_id", "synthetic-sender-v2", "unmatched_target"),
            (
                "receiver_receipt_id",
                f"missing-{uuid.uuid4()}",
                "pending_delivery_evidence",
            ),
        ):
            _case_revision, case_intent, case_observation, _case_result = (
                self.delivered_claim()
            )
            value = json.loads(self.inbound_document(
                kind="lifecycle",
                intent=case_intent,
                observation=case_observation,
            ))
            value[field] = replacement
            _delivery, candidate = self._admit_value(
                value,
                namespace="synthetic-lifecycle",
            )
            with self.assertRaisesMessage(CommandError, reason):
                accept_lifecycle(
                    actor=self.alpha_user,
                    organization_id=self.alpha.id,
                    request_id=uuid.uuid4(),
                    candidate_id=candidate.candidate_id,
                    artifact_store=self.store,
                )
            reevaluated = reevaluate_candidate(
                actor=self.alpha_user,
                organization_id=self.alpha.id,
                candidate_id=candidate.candidate_id,
                artifact_store=self.store,
            )
            self.assertIn(reason, reevaluated.current_blockers)

        _line_revision, line_intent, line_observation, _line_result = (
            self.delivered_claim()
        )
        _delivery, wrong_line = self.admit_inbound(
            kind="remittance",
            intent=line_intent,
            observation=line_observation,
            lines=[{
                "line_ordinal": 2,
                "paid_amount": "1.00",
                "contractual_adjustment": "0.00",
            }],
        )
        with self.assertRaisesMessage(CommandError, "unmatched_target"):
            post_remittance(
                actor=self.alpha_user,
                organization_id=self.alpha.id,
                request_id=uuid.uuid4(),
                candidate_id=wrong_line.candidate_id,
                artifact_store=self.store,
            )

        cross_content = self.inbound_document(
            kind="lifecycle",
            intent=line_intent,
            observation=line_observation,
        )
        cross_delivery = self.admit(
            actor=self.beta_user,
            organization=self.beta,
            content=cross_content,
            source_namespace="synthetic-lifecycle",
            media_type="application/json",
        )
        cross_candidate = interpret_inbound(
            actor=self.beta_user,
            organization_id=self.beta.id,
            delivery_id=cross_delivery.delivery_id,
            artifact_store=self.store,
        )
        with self.assertRaisesMessage(CommandError, "unmatched_target"):
            accept_lifecycle(
                actor=self.beta_user,
                organization_id=self.beta.id,
                request_id=uuid.uuid4(),
                candidate_id=cross_candidate.candidate_id,
                artifact_store=self.store,
            )

    def test_lifecycle_predecessor_arrival_conflict_and_current_sequence(self):
        _revision, intent, observation, _result = self.delivered_claim()
        first_event_id = uuid.uuid4()
        _second_delivery, second = self.admit_inbound(
            kind="lifecycle",
            intent=intent,
            observation=observation,
            sequence=2,
            predecessor_event_id=first_event_id,
        )
        with self.assertRaisesMessage(CommandError, "pending_sequence_gap"):
            accept_lifecycle(
                actor=self.alpha_user,
                organization_id=self.alpha.id,
                request_id=uuid.uuid4(),
                candidate_id=second.candidate_id,
                artifact_store=self.store,
            )
        _first_delivery, first = self.admit_inbound(
            kind="lifecycle",
            intent=intent,
            observation=observation,
            event_id=first_event_id,
        )
        accept_lifecycle(
            actor=self.alpha_user,
            organization_id=self.alpha.id,
            request_id=uuid.uuid4(),
            candidate_id=first.candidate_id,
            artifact_store=self.store,
        )
        accepted_second = accept_lifecycle(
            actor=self.alpha_user,
            organization_id=self.alpha.id,
            request_id=uuid.uuid4(),
            candidate_id=second.candidate_id,
            artifact_store=self.store,
        )
        self.assertEqual(
            [item.lifecycle_sequence for item in current_lifecycle(
                actor=self.alpha_user,
                organization_id=self.alpha.id,
                intent_id=intent.id,
            )],
            [1, 2],
        )
        conflict_bytes = self.inbound_document(
            kind="lifecycle",
            intent=intent,
            observation=observation,
            sequence=2,
            predecessor_event_id=first_event_id,
        )
        conflict_value = json.loads(conflict_bytes)
        conflict_value["status"] = "ACK_REJECTED"
        _delivery, conflict = self._admit_value(
            conflict_value,
            namespace="synthetic-lifecycle",
        )
        with self.assertRaisesMessage(CommandError, "conflicting_identity_or_content"):
            accept_lifecycle(
                actor=self.alpha_user,
                organization_id=self.alpha.id,
                request_id=uuid.uuid4(),
                candidate_id=conflict.candidate_id,
                artifact_store=self.store,
            )
        self.assertTrue(AcceptedEvent.objects.filter(id=accepted_second.event_id).exists())

    def test_partial_multievent_and_multiline_overallocation_is_all_or_nothing(self):
        revision, intent, observation = self._two_line_delivery()
        _first_delivery, first = self.admit_inbound(
            kind="remittance",
            intent=intent,
            observation=observation,
            lines=[{
                "line_ordinal": 1,
                "paid_amount": "6.00",
                "contractual_adjustment": "0.00",
            }],
        )
        post_remittance(
            actor=self.alpha_user,
            organization_id=self.alpha.id,
            request_id=uuid.uuid4(),
            candidate_id=first.candidate_id,
            artifact_store=self.store,
        )
        _bad_delivery, bad = self.admit_inbound(
            kind="remittance",
            intent=intent,
            observation=observation,
            lines=[
                {
                    "line_ordinal": 1,
                    "paid_amount": "0.00",
                    "contractual_adjustment": "0.50",
                },
                {
                    "line_ordinal": 2,
                    "paid_amount": "5.00",
                    "contractual_adjustment": "0.00",
                },
            ],
        )
        with self.assertRaisesMessage(CommandError, "overallocated_line"):
            post_remittance(
                actor=self.alpha_user,
                organization_id=self.alpha.id,
                request_id=uuid.uuid4(),
                candidate_id=bad.candidate_id,
                artifact_store=self.store,
            )
        view = ledger_detail(
            actor=self.alpha_user,
            organization_id=self.alpha.id,
            claim_revision_id=revision.id,
        )
        self.assertEqual(view.original_charge, Decimal("10.00"))
        self.assertEqual(view.payer_reported_credits, Decimal("6.00"))
        self.assertEqual(view.contractual_adjustments, Decimal("0.00"))
        self.assertEqual(view.residual, Decimal("4.00"))
        self.assertEqual(PostingEntry.objects.count(), 1)
        self.assertFalse(AcceptedEvent.objects.filter(
            primary_candidate_id=bad.candidate_id,
        ).exists())

        _second_delivery, second = self.admit_inbound(
            kind="remittance",
            intent=intent,
            observation=observation,
            lines=[{
                "line_ordinal": 2,
                "paid_amount": "0.00",
                "contractual_adjustment": "4.00",
            }],
        )
        post_remittance(
            actor=self.alpha_user,
            organization_id=self.alpha.id,
            request_id=uuid.uuid4(),
            candidate_id=second.candidate_id,
            artifact_store=self.store,
        )
        final = ledger_detail(
            actor=self.alpha_user,
            organization_id=self.alpha.id,
            claim_revision_id=revision.id,
        )
        self.assertEqual(final.payer_reported_credits, Decimal("6.00"))
        self.assertEqual(final.contractual_adjustments, Decimal("4.00"))
        self.assertEqual(final.residual, Decimal("0.00"))
        self.assertEqual(PostingEntry.objects.count(), 2)
        self.assertFalse(hasattr(view, "patient_liability"))
        self.assertFalse(hasattr(view, "cash_settlement"))

    def test_zero_component_precision_maximum_and_explicit_reevaluation(self):
        _revision, intent, observation, _result = self.delivered_claim()
        maximum = json.loads(self.inbound_document(
            kind="remittance", intent=intent, observation=observation,
        ))
        maximum["lines"][0]["paid_amount"] = "99999999.99"
        maximum["lines"][0]["contractual_adjustment"] = "0"
        _delivery, max_candidate = self._admit_value(
            maximum,
            namespace="synthetic-remittance",
        )
        max_line = InboundCandidate.objects.get(
            id=max_candidate.candidate_id,
        ).lines.get()
        self.assertEqual(max_line.paid_amount, Decimal("99999999.99"))
        blockers = reevaluate_candidate(
            actor=self.alpha_user,
            organization_id=self.alpha.id,
            candidate_id=max_candidate.candidate_id,
            artifact_store=self.store,
        )
        self.assertEqual(blockers.current_blockers, ("overallocated_line",))
        self.assertFalse(AcceptedEvent.objects.exists())
        self.assertFalse(FinancialAccount.objects.exists())
