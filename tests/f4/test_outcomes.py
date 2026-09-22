from __future__ import annotations

import uuid

from django.db import DatabaseError, transaction
from django.utils import timezone

from medicafe_v1.claims.models import ReceiverObservation
from medicafe_v1.outcomes.commands import (
    accept_lifecycle, interpret_inbound, post_remittance, reevaluate_candidate,
)
from medicafe_v1.outcomes.models import (
    AcceptedEvent, AcceptedEventEvidence, FinancialAccount, InboundAttempt,
    InboundCandidate, InboundCandidateLine, OutcomesCommandReceipt,
    PostingEntry,
)
from medicafe_v1.sources.domain import CommandError
from tests.helpers.workflow_boundary_contract import assert_outcome_boundary

from .base import F4TestCase, F4TransactionTestCase


class OutcomesAcceptanceTests(F4TestCase):
    def _record_delivery_conflict(self, *, intent, accepted):
        conflict = ReceiverObservation.objects.create(
            organization=self.alpha, intent=intent,
            claim_revision_id=intent.claim_revision_id,
            origin=ReceiverObservation.ORIGIN_RECONCILIATION,
            receiver_id=accepted.receiver_id,
            receiver_version=accepted.receiver_version,
            lookup_key=uuid.uuid4(),
            receipt_id=f"conflicting-{uuid.uuid4()}",
            reported_attempt_id=accepted.reported_attempt_id,
            envelope_digest=accepted.envelope_digest,
            byte_length=accepted.byte_length,
            received_bytes=bytes(accepted.received_bytes),
            observed_state=ReceiverObservation.STATE_ACCEPTED,
            no_acceptance_guaranteed=False, binding_valid=True,
            conflict_reason="", observed_at=timezone.now(),
            evidence_fingerprint=uuid.uuid4().hex * 2,
            reported_organization_id=self.alpha.id,
            reported_intent_id=intent.id,
            reported_claim_revision_id=intent.claim_revision_id,
            reported_delivery_key=uuid.uuid4(),
            reported_receiver_id=accepted.receiver_id,
            reported_receiver_version=accepted.receiver_version,
            reported_envelope_digest=accepted.envelope_digest,
            reported_byte_length=accepted.byte_length,
        )
        conflict.refresh_from_db()
        self.assertEqual(conflict.observed_state, ReceiverObservation.STATE_CONFLICT)
        return conflict

    def test_interpret_replay_has_one_candidate_and_one_actual_attempt(self):
        _revision, intent, observation, _result = self.delivered_claim()
        admitted, interpreted = self.admit_inbound(
            kind="lifecycle", intent=intent, observation=observation,
        )

        replay = interpret_inbound(
            actor=self.alpha_user, organization_id=self.alpha.id,
            delivery_id=admitted.delivery_id, artifact_store=self.store,
        )

        self.assertEqual(interpreted.reason_code, "interpretation_succeeded")
        self.assertEqual(replay.reason_code, "interpretation_replayed")
        self.assertEqual(replay.candidate_id, interpreted.candidate_id)
        self.assertEqual(InboundCandidate.objects.count(), 1)
        self.assertEqual(InboundAttempt.objects.count(), 1)

    def test_duplicate_json_key_records_terminal_failure_without_candidate(self):
        _revision, intent, observation, _result = self.delivered_claim()
        valid = self.inbound_document(
            kind="lifecycle", intent=intent, observation=observation,
        )
        malformed = valid[:-1] + b',"kind":"remittance"}'
        admitted = self.admit(
            content=malformed, source_namespace="synthetic-lifecycle",
            media_type="application/json",
        )

        with self.assertRaisesMessage(CommandError, "malformed_or_unsupported"):
            interpret_inbound(
                actor=self.alpha_user, organization_id=self.alpha.id,
                delivery_id=admitted.delivery_id, artifact_store=self.store,
            )

        attempt = InboundAttempt.objects.get(delivery_id=admitted.delivery_id)
        self.assertFalse(attempt.succeeded)
        self.assertEqual(attempt.reason_code, "malformed_or_unsupported")
        self.assertFalse(InboundCandidate.objects.filter(delivery_id=admitted.delivery_id).exists())

    def test_lifecycle_acceptance_binds_exact_historical_delivery(self):
        _revision, intent, observation, _result = self.delivered_claim()
        _admitted, interpreted = self.admit_inbound(
            kind="lifecycle", intent=intent, observation=observation,
        )

        accepted = accept_lifecycle(
            actor=self.alpha_user, organization_id=self.alpha.id,
            request_id=uuid.uuid4(), candidate_id=interpreted.candidate_id,
            artifact_store=self.store,
        )

        event = AcceptedEvent.objects.get(id=accepted.event_id)
        self.assertEqual(event.receiver_observation_id, observation.id)
        self.assertEqual(event.intent_id, intent.id)
        assert_outcome_boundary(
            self, candidate=InboundCandidate.objects.get(id=interpreted.candidate_id),
            expected_event=event, expected_entries=0,
        )

    def test_remittance_posts_conserved_entries_once(self):
        revision, intent, observation, _result = self.delivered_claim()
        _admitted, interpreted = self.admit_inbound(
            kind="remittance", intent=intent, observation=observation,
        )
        request_id = uuid.uuid4()

        posted = post_remittance(
            actor=self.alpha_user, organization_id=self.alpha.id,
            request_id=request_id, candidate_id=interpreted.candidate_id,
            artifact_store=self.store,
        )
        replay = post_remittance(
            actor=self.alpha_user, organization_id=self.alpha.id,
            request_id=request_id, candidate_id=interpreted.candidate_id,
            artifact_store=self.store,
        )

        self.assertEqual(posted.reason_code, "remittance_posted")
        self.assertEqual(replay.reason_code, "remittance_post_replayed")
        self.assertEqual(replay.batch_id, posted.batch_id)
        self.assertEqual(PostingEntry.objects.count(), 2)
        account = FinancialAccount.objects.get(claim_revision=revision)
        self.assertEqual(account.original_charge, revision.total_amount)
        self.assertEqual(sum(entry.amount for entry in PostingEntry.objects.all()), 5)
        self.assertEqual(OutcomesCommandReceipt.objects.count(), 1)
        assert_outcome_boundary(
            self, candidate=InboundCandidate.objects.get(id=interpreted.candidate_id),
            expected_event=AcceptedEvent.objects.get(id=posted.event_id),
            expected_entries=2,
        )

    def test_overallocated_line_rolls_back_event_batch_and_receipt(self):
        _revision, intent, observation, _result = self.delivered_claim()
        _admitted, interpreted = self.admit_inbound(
            kind="remittance", intent=intent, observation=observation,
            lines=[{
                "line_ordinal": 1, "paid_amount": "11.00",
                "contractual_adjustment": "0.00",
            }],
        )

        with self.assertRaisesMessage(CommandError, "overallocated_line"):
            post_remittance(
                actor=self.alpha_user, organization_id=self.alpha.id,
                request_id=uuid.uuid4(), candidate_id=interpreted.candidate_id,
                artifact_store=self.store,
            )

        self.assertFalse(AcceptedEvent.objects.exists())
        self.assertFalse(PostingEntry.objects.exists())
        self.assertFalse(OutcomesCommandReceipt.objects.exists())

    def test_money_spellings_share_semantics_and_never_double_post(self):
        _revision, intent, observation, _result = self.delivered_claim()
        event_id = uuid.uuid4()
        first_bytes = self.inbound_document(
            kind="remittance", intent=intent, observation=observation,
            event_id=event_id,
            lines=[{
                "line_ordinal": 1, "paid_amount": "4",
                "contractual_adjustment": "1.2",
            }],
        )
        second_bytes = self.inbound_document(
            kind="remittance", intent=intent, observation=observation,
            event_id=event_id,
            lines=[{
                "line_ordinal": 1, "paid_amount": "4.00",
                "contractual_adjustment": "1.20",
            }],
        )
        _first_delivery, first = self.admit_inbound(
            kind="remittance", intent=intent, observation=observation,
            content=first_bytes,
        )
        _second_delivery, second = self.admit_inbound(
            kind="remittance", intent=intent, observation=observation,
            content=second_bytes,
        )
        first_candidate = InboundCandidate.objects.get(id=first.candidate_id)
        second_candidate = InboundCandidate.objects.get(id=second.candidate_id)
        self.assertEqual(first_candidate.semantic_digest, second_candidate.semantic_digest)

        initial = post_remittance(
            actor=self.alpha_user, organization_id=self.alpha.id,
            request_id=uuid.uuid4(), candidate_id=first.candidate_id,
            artifact_store=self.store,
        )
        replayed_semantics = post_remittance(
            actor=self.alpha_user, organization_id=self.alpha.id,
            request_id=uuid.uuid4(), candidate_id=second.candidate_id,
            artifact_store=self.store,
        )

        self.assertEqual(replayed_semantics.event_id, initial.event_id)
        self.assertEqual(replayed_semantics.batch_id, initial.batch_id)
        self.assertEqual(AcceptedEvent.objects.count(), 1)
        self.assertEqual(AcceptedEventEvidence.objects.count(), 2)
        self.assertEqual(PostingEntry.objects.count(), 2)

    def test_later_delivery_conflict_blocks_new_acceptance_but_retains_fact(self):
        _revision, intent, observation, _result = self.delivered_claim()
        _admitted, lifecycle = self.admit_inbound(
            kind="lifecycle", intent=intent, observation=observation,
        )
        accepted = accept_lifecycle(
            actor=self.alpha_user, organization_id=self.alpha.id,
            request_id=uuid.uuid4(), candidate_id=lifecycle.candidate_id,
            artifact_store=self.store,
        )
        self._record_delivery_conflict(intent=intent, accepted=observation)
        _remittance_delivery, remittance = self.admit_inbound(
            kind="remittance", intent=intent, observation=observation,
        )

        with self.assertRaisesMessage(CommandError, "conflicting_identity_or_content"):
            post_remittance(
                actor=self.alpha_user, organization_id=self.alpha.id,
                request_id=uuid.uuid4(), candidate_id=remittance.candidate_id,
                artifact_store=self.store,
            )

        self.assertTrue(AcceptedEvent.objects.filter(id=accepted.event_id).exists())
        alert = reevaluate_candidate(
            actor=self.alpha_user, organization_id=self.alpha.id,
            candidate_id=lifecycle.candidate_id, artifact_store=self.store,
        )
        self.assertEqual(alert.current_blockers, ("conflicting_identity_or_content",))

    def test_reevaluation_reports_conflict_and_sequence_gap_in_order(self):
        _revision, intent, observation, _result = self.delivered_claim()
        _admitted, interpreted = self.admit_inbound(
            kind="lifecycle", intent=intent, observation=observation,
            sequence=2, predecessor_event_id=uuid.uuid4(),
        )
        self._record_delivery_conflict(intent=intent, accepted=observation)

        result = reevaluate_candidate(
            actor=self.alpha_user, organization_id=self.alpha.id,
            candidate_id=interpreted.candidate_id, artifact_store=self.store,
        )

        self.assertEqual(result.current_blockers, (
            "conflicting_identity_or_content", "pending_sequence_gap",
        ))

    def test_reevaluation_reports_overallocation_without_mutation(self):
        _revision, intent, observation, _result = self.delivered_claim()
        _admitted, interpreted = self.admit_inbound(
            kind="remittance", intent=intent, observation=observation,
            lines=[{
                "line_ordinal": 1, "paid_amount": "11",
                "contractual_adjustment": "0",
            }],
        )

        result = reevaluate_candidate(
            actor=self.alpha_user, organization_id=self.alpha.id,
            candidate_id=interpreted.candidate_id, artifact_store=self.store,
        )

        self.assertEqual(result.current_blockers, ("overallocated_line",))
        self.assertFalse(AcceptedEvent.objects.exists())
        self.assertFalse(PostingEntry.objects.exists())


class OutcomesSqlRelationshipTests(F4TransactionTestCase):
    def test_candidate_lines_are_sealed_after_interpretation(self):
        _revision, intent, observation, _result = self.delivered_claim()
        _admitted, interpreted = self.admit_inbound(
            kind="remittance", intent=intent, observation=observation,
        )
        candidate = InboundCandidate.objects.get(id=interpreted.candidate_id)

        with self.assertRaises(DatabaseError), transaction.atomic():
            InboundCandidateLine.objects.create(
                organization=self.alpha, candidate=candidate, line_ordinal=2,
                paid_amount="1.00", contractual_adjustment="0.00",
            )

    def test_direct_lifecycle_event_must_equal_retained_candidate(self):
        _revision, intent, observation, _result = self.delivered_claim()
        _admitted, interpreted = self.admit_inbound(
            kind="lifecycle", intent=intent, observation=observation,
        )
        candidate = InboundCandidate.objects.get(id=interpreted.candidate_id)

        with self.assertRaises(DatabaseError), transaction.atomic():
            AcceptedEvent.objects.create(
                organization=self.alpha, primary_candidate=candidate,
                kind=candidate.kind, sender_id=candidate.sender_id,
                event_id=candidate.event_id, semantic_digest=candidate.semantic_digest,
                intent=intent, claim_revision_id=intent.claim_revision_id,
                receiver_observation=observation,
                receiver_evidence_fingerprint=observation.evidence_fingerprint,
                receiver_receipt_id=observation.receipt_id,
                lifecycle_sequence=candidate.lifecycle_sequence,
                predecessor_event_id=candidate.predecessor_event_id,
                lifecycle_status="ACK_REJECTED", accepted_by=self.alpha_user,
            )

    def test_direct_receipt_kind_must_match_remittance_result(self):
        _revision, intent, observation, _result = self.delivered_claim()
        _admitted, interpreted = self.admit_inbound(
            kind="remittance", intent=intent, observation=observation,
        )
        posted = post_remittance(
            actor=self.alpha_user, organization_id=self.alpha.id,
            request_id=uuid.uuid4(), candidate_id=interpreted.candidate_id,
            artifact_store=self.store,
        )
        candidate = InboundCandidate.objects.get(id=interpreted.candidate_id)
        event = AcceptedEvent.objects.get(id=posted.event_id)

        with self.assertRaises(DatabaseError), transaction.atomic():
            OutcomesCommandReceipt.objects.create(
                organization=self.alpha, request_uuid=uuid.uuid4(),
                command_kind="accept_lifecycle", target_candidate=candidate,
                target_intent_id=candidate.intent_id, intent_digest="d" * 64,
                accepted_by=self.alpha_user, result_event=event,
                result_batch=None,
            )

    def test_posted_batch_rejects_later_arbitrary_entry(self):
        _revision, intent, observation, _result = self.delivered_claim()
        _admitted, interpreted = self.admit_inbound(
            kind="remittance", intent=intent, observation=observation,
        )
        posted = post_remittance(
            actor=self.alpha_user, organization_id=self.alpha.id,
            request_id=uuid.uuid4(), candidate_id=interpreted.candidate_id,
            artifact_store=self.store,
        )
        existing = PostingEntry.objects.filter(batch_id=posted.batch_id).first()

        with self.assertRaises(DatabaseError), transaction.atomic():
            PostingEntry.objects.create(
                organization=self.alpha, batch_id=posted.batch_id,
                event_id=posted.event_id, account=existing.account,
                charge_basis=existing.charge_basis,
                claim_line=existing.claim_line, kind="invented_credit",
                amount="1.00", currency=existing.currency,
            )
