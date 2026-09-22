from __future__ import annotations

import uuid

from medicafe_v1.outcomes.commands import (
    accept_lifecycle, interpret_inbound, post_remittance,
)
from medicafe_v1.outcomes.models import (
    AcceptedEvent, FinancialAccount, InboundAttempt, InboundCandidate,
    OutcomesCommandReceipt, PostingEntry,
)
from medicafe_v1.sources.domain import CommandError
from tests.helpers.workflow_boundary_contract import assert_outcome_boundary

from .base import F4TestCase


class OutcomesAcceptanceTests(F4TestCase):
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
