from __future__ import annotations

import uuid
from decimal import Decimal
from unittest.mock import patch

from medicafe_v1.access.models import Membership
from medicafe_v1.access.services import AuthorizationError
from medicafe_v1.claims.commands import (
    approve_claim_revision,
    initialize_synthetic_policy,
    prepare_claim_revision,
    select_synthetic_policy,
)
from medicafe_v1.claims.models import ClaimRevision, ClaimsCommandReceipt
from medicafe_v1.claims.queries import claim_actionability, claim_detail
from medicafe_v1.records.commands import revise_service
from medicafe_v1.records.models import ServiceRevision
from medicafe_v1.sources.domain import CommandError

from tests.f2.base import F2TestCase
from tests.helpers.f2_claim_boundary import assert_claim_boundary


class ClaimCommandTests(F2TestCase):
    def _two_services(self, *, note="SYNTHETIC_F2_CLAIM"):
        delivery, observation, resolved = self.resolved_observation(note=note)
        first = self.accepted_service(
            resolved,
            observation,
            code="SYN-A",
            units=2,
            unit_amount=Decimal("10.25"),
            reason="Synthetic claim service A",
        )
        second = self.accepted_service(
            resolved,
            observation,
            code="SYN-B",
            units=1,
            unit_amount=Decimal("3.40"),
            reason="Synthetic claim service B",
        )
        return delivery, observation, resolved, first, second

    def test_prepare_exact_order_decimal_total_and_approval_replay(self):
        delivery, _observation, resolved, first, second = self._two_services(
            note="SYNTHETIC_F2_CLAIM_HAPPY_PATH"
        )
        prepare_request = uuid.uuid4()
        prepared = prepare_claim_revision(
            actor=self.alpha_user,
            organization_id=self.alpha.id,
            request_id=prepare_request,
            encounter_id=resolved.encounter_id,
            expected_claim_revision_id=None,
            selected_service_revision_ids=[second.revision_id, first.revision_id],
            route_id="synthetic-receiver",
            route_version="v1",
            reason="Synthetic exact ordered selection",
        )
        self.assertEqual(prepared.reason_code, "claim_revision_prepared")
        revision = ClaimRevision.objects.prefetch_related("lines").get(pk=prepared.revision_id)
        assert_claim_boundary(
            self,
            delivery=delivery,
            claim_revision=revision,
            expected_service_revisions=[second.revision_id, first.revision_id],
            expected_total=Decimal("23.90"),
        )
        lines = list(revision.lines.order_by("ordinal"))
        self.assertEqual([line.code for line in lines], ["SYN-B", "SYN-A"])
        self.assertEqual([line.units for line in lines], [1, 2])
        self.assertEqual([line.line_amount for line in lines], [Decimal("3.40"), Decimal("20.50")])
        self.assertEqual(revision.policy_version, "synthetic-v1")
        self.assertEqual(revision.policy_generation, 1)

        replay = prepare_claim_revision(
            actor=self.alpha_user,
            organization_id=self.alpha.id,
            request_id=prepare_request,
            encounter_id=resolved.encounter_id,
            expected_claim_revision_id=None,
            selected_service_revision_ids=[second.revision_id, first.revision_id],
            route_id="synthetic-receiver",
            route_version="v1",
            reason="Synthetic exact ordered selection",
        )
        self.assertEqual(replay.reason_code, "claim_request_replayed")
        self.assertTrue(replay.replayed)
        self.assertEqual(replay.claim_id, prepared.claim_id)
        self.assertEqual(replay.revision_id, prepared.revision_id)
        self.assertEqual(ClaimRevision.objects.filter(claim_id=prepared.claim_id).count(), 1)

        with self.assertRaises(CommandError) as changed_order:
            prepare_claim_revision(
                actor=self.alpha_user,
                organization_id=self.alpha.id,
                request_id=prepare_request,
                encounter_id=resolved.encounter_id,
                expected_claim_revision_id=None,
                selected_service_revision_ids=[first.revision_id, second.revision_id],
                route_id="synthetic-receiver",
                route_version="v1",
                reason="Synthetic changed line order",
            )
        self.assertEqual(changed_order.exception.reason_code, "request_input_conflict")

        approval_request = uuid.uuid4()
        approved = approve_claim_revision(
            actor=self.alpha_user,
            organization_id=self.alpha.id,
            request_id=approval_request,
            claim_revision_id=revision.id,
            expected_envelope_digest=revision.envelope_digest,
        )
        self.assertEqual(approved.reason_code, "claim_revision_approved")
        self.assertIsNotNone(approved.approval_id)
        actionability = claim_actionability(
            actor=self.alpha_user,
            organization_id=self.alpha.id,
            claim_revision_id=revision.id,
        )
        self.assertEqual(actionability.reason_code, "approved_current")
        self.assertEqual(actionability.blockers, ())

        approval_replay = approve_claim_revision(
            actor=self.alpha_user,
            organization_id=self.alpha.id,
            request_id=approval_request,
            claim_revision_id=revision.id,
            expected_envelope_digest=revision.envelope_digest,
        )
        self.assertEqual(approval_replay.reason_code, "claim_request_replayed")
        self.assertTrue(approval_replay.replayed)
        self.assertEqual(approval_replay.approval_id, approved.approval_id)
        self.assertEqual(ClaimsCommandReceipt.objects.filter(
            organization=self.alpha, command_kind="approve_claim_revision"
        ).count(), 1)

        with self.assertRaises(CommandError) as changed_digest:
            approve_claim_revision(
                actor=self.alpha_user,
                organization_id=self.alpha.id,
                request_id=approval_request,
                claim_revision_id=revision.id,
                expected_envelope_digest="0" * 64,
            )
        self.assertEqual(changed_digest.exception.reason_code, "request_input_conflict")

        # A newly added, unselected service does not change this revision's actionability.
        self.accepted_service(
            resolved,
            _observation,
            code="SYN-A",
            units=1,
            unit_amount=Decimal("1.00"),
            reason="Synthetic deliberately unselected service",
        )
        still_current = claim_actionability(
            actor=self.alpha_user,
            organization_id=self.alpha.id,
            claim_revision_id=revision.id,
        )
        self.assertEqual(still_current.reason_code, "approved_current")

    def test_policy_compare_and_set_replay_preserves_original_result(self):
        unchanged = select_synthetic_policy(
            actor=self.alpha_user,
            organization_id=self.alpha.id,
            request_id=uuid.uuid4(),
            expected_version="synthetic-v1",
            expected_generation=1,
            version="synthetic-v1",
        )
        self.assertEqual(unchanged.reason_code, "policy_selection_unchanged")
        self.assertEqual(unchanged.policy_generation, 1)

        switch_request = uuid.uuid4()
        switched = select_synthetic_policy(
            actor=self.alpha_user,
            organization_id=self.alpha.id,
            request_id=switch_request,
            expected_version="synthetic-v1",
            expected_generation=1,
            version="synthetic-v2",
        )
        self.assertEqual(switched.reason_code, "policy_selection_changed")
        self.assertEqual(switched.policy_version, "synthetic-v2")
        self.assertEqual(switched.policy_generation, 2)

        switched_back = select_synthetic_policy(
            actor=self.alpha_user,
            organization_id=self.alpha.id,
            request_id=uuid.uuid4(),
            expected_version="synthetic-v2",
            expected_generation=2,
            version="synthetic-v1",
        )
        self.assertEqual(switched_back.policy_generation, 3)

        replay = select_synthetic_policy(
            actor=self.alpha_user,
            organization_id=self.alpha.id,
            request_id=switch_request,
            expected_version="synthetic-v1",
            expected_generation=1,
            version="synthetic-v2",
        )
        self.assertEqual(replay.reason_code, "claim_request_replayed")
        self.assertTrue(replay.replayed)
        self.assertEqual(replay.policy_version, "synthetic-v2")
        self.assertEqual(replay.policy_generation, 2)
        self.assertEqual(replay.current_policy_version, "synthetic-v1")
        self.assertEqual(replay.current_policy_generation, 3)

        with self.assertRaises(CommandError) as changed_request:
            select_synthetic_policy(
                actor=self.alpha_user,
                organization_id=self.alpha.id,
                request_id=switch_request,
                expected_version="synthetic-v1",
                expected_generation=1,
                version="synthetic-v1",
            )
        self.assertEqual(changed_request.exception.reason_code, "request_input_conflict")

        with self.assertRaises(CommandError) as stale_selection:
            select_synthetic_policy(
                actor=self.alpha_user,
                organization_id=self.alpha.id,
                request_id=uuid.uuid4(),
                expected_version="synthetic-v2",
                expected_generation=2,
                version="synthetic-v2",
            )
        self.assertEqual(stale_selection.exception.reason_code, "policy_selection_conflict")

    def test_actionability_returns_all_blockers_in_fixed_order(self):
        delivery, observation, resolved = self.resolved_observation(
            note="SYNTHETIC_F2_BLOCKER_ORDER"
        )
        service = self.accepted_service(
            resolved,
            observation,
            code="SYN-A",
            units=1,
            unit_amount=Decimal("4.00"),
            reason="Synthetic blocker service",
        )
        first_claim = prepare_claim_revision(
            actor=self.alpha_user,
            organization_id=self.alpha.id,
            request_id=uuid.uuid4(),
            encounter_id=resolved.encounter_id,
            expected_claim_revision_id=None,
            selected_service_revision_ids=[service.revision_id],
            route_id="synthetic-receiver",
            route_version="v1",
            reason="Synthetic unapproved blocker revision",
        )
        first_revision = ClaimRevision.objects.get(pk=first_claim.revision_id)

        corrected = revise_service(
            actor=self.alpha_user,
            organization_id=self.alpha.id,
            request_id=uuid.uuid4(),
            service_id=service.service_id,
            expected_revision_id=service.revision_id,
            evidence_observation_id=observation.id,
            disposition="accepted",
            code="SYN-A",
            units=1,
            unit_amount=Decimal("5.00"),
            currency="USD",
            reason="Synthetic selected service correction",
            artifact_store=self.store,
        )
        changed_policy = select_synthetic_policy(
            actor=self.alpha_user,
            organization_id=self.alpha.id,
            request_id=uuid.uuid4(),
            expected_version="synthetic-v1",
            expected_generation=1,
            version="synthetic-v2",
        )
        self.assertEqual(changed_policy.policy_generation, 2)
        second_claim = prepare_claim_revision(
            actor=self.alpha_user,
            organization_id=self.alpha.id,
            request_id=uuid.uuid4(),
            encounter_id=resolved.encounter_id,
            expected_claim_revision_id=first_revision.id,
            selected_service_revision_ids=[corrected.revision_id],
            route_id="synthetic-receiver",
            route_version="v2",
            reason="Synthetic superseding blocker revision",
        )
        self.assertNotEqual(second_claim.revision_id, first_claim.revision_id)

        with patch("medicafe_v1.claims.queries._revision_envelope_valid", return_value=False):
            actionability = claim_actionability(
                actor=self.alpha_user,
                organization_id=self.alpha.id,
                claim_revision_id=first_revision.id,
            )
        self.assertEqual(actionability.reason_code, "claim_not_actionable")
        self.assertEqual(actionability.primary_reason, "envelope_unavailable")
        self.assertEqual(actionability.blockers, (
            "envelope_unavailable",
            "superseded_revision",
            "selected_service_changed",
            "policy_changed",
            "unapproved",
        ))

    def test_claim_cross_organization_and_inactive_membership_fail_closed(self):
        initialize_synthetic_policy(
            actor=self.beta_user, organization_id=self.beta.id
        )
        _delivery, observation, resolved = self.resolved_observation(
            actor=self.beta_user,
            organization=self.beta,
            note="SYNTHETIC_F2_BETA_CLAIM",
        )
        service = self.accepted_service(
            resolved,
            observation,
            actor=self.beta_user,
            organization=self.beta,
            reason="Synthetic beta claim service",
        )
        prepared = prepare_claim_revision(
            actor=self.beta_user,
            organization_id=self.beta.id,
            request_id=uuid.uuid4(),
            encounter_id=resolved.encounter_id,
            expected_claim_revision_id=None,
            selected_service_revision_ids=[service.revision_id],
            route_id="synthetic-receiver",
            route_version="v1",
            reason="Synthetic beta claim",
        )
        revision = ClaimRevision.objects.get(pk=prepared.revision_id)

        with self.assertRaises(AuthorizationError):
            claim_detail(
                actor=self.alpha_user,
                organization_id=self.beta.id,
                claim_id=prepared.claim_id,
            )
        with self.assertRaises(AuthorizationError):
            claim_actionability(
                actor=self.alpha_user,
                organization_id=self.beta.id,
                claim_revision_id=revision.id,
            )
        with self.assertRaises(AuthorizationError):
            prepare_claim_revision(
                actor=self.alpha_user,
                organization_id=self.beta.id,
                request_id=uuid.uuid4(),
                encounter_id=resolved.encounter_id,
                expected_claim_revision_id=None,
                selected_service_revision_ids=[service.revision_id],
                route_id="synthetic-receiver",
                route_version="v1",
                reason="Synthetic unauthorized claim",
            )
        with self.assertRaises(AuthorizationError):
            approve_claim_revision(
                actor=self.alpha_user,
                organization_id=self.beta.id,
                request_id=uuid.uuid4(),
                claim_revision_id=revision.id,
                expected_envelope_digest=revision.envelope_digest,
            )
        with self.assertRaises(CommandError) as wrong_scope:
            prepare_claim_revision(
                actor=self.alpha_user,
                organization_id=self.alpha.id,
                request_id=uuid.uuid4(),
                encounter_id=resolved.encounter_id,
                expected_claim_revision_id=None,
                selected_service_revision_ids=[service.revision_id],
                route_id="synthetic-receiver",
                route_version="v1",
                reason="Synthetic cross-organization claim",
            )
        self.assertEqual(wrong_scope.exception.reason_code, "encounter_not_found")

        beta_membership = Membership.objects.get(
            organization=self.beta, user=self.beta_user
        )
        beta_membership.is_active = False
        beta_membership.save(update_fields=["is_active"])
        with self.assertRaises(AuthorizationError):
            claim_detail(
                actor=self.beta_user,
                organization_id=self.beta.id,
                claim_id=prepared.claim_id,
            )
        with self.assertRaises(AuthorizationError):
            approve_claim_revision(
                actor=self.beta_user,
                organization_id=self.beta.id,
                request_id=uuid.uuid4(),
                claim_revision_id=revision.id,
                expected_envelope_digest=revision.envelope_digest,
            )
