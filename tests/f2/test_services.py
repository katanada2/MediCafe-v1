from __future__ import annotations

import uuid
from decimal import Decimal

from django.db.models import Count

from medicafe_v1.access.models import Membership
from medicafe_v1.access.services import AuthorizationError
from medicafe_v1.records.commands import revise_service
from medicafe_v1.records.models import Service, ServiceRevision
from medicafe_v1.records.queries import current_services_for_encounter, service_detail
from medicafe_v1.sources.domain import CommandError

from tests.f2.base import F2TestCase


class ServiceCommandTests(F2TestCase):
    def test_accept_replay_conflict_and_revision_provenance(self):
        _delivery, observation, resolved = self.resolved_observation(
            note="SYNTHETIC_F2_SERVICE_HISTORY"
        )
        request_id = uuid.uuid4()
        accepted = self.accepted_service(
            resolved,
            observation,
            request_id=request_id,
            code="SYN-A",
            units=2,
            unit_amount=Decimal("10.25"),
            reason="Synthetic initial service",
        )
        service = Service.objects.get(pk=accepted.service_id)
        first_revision = ServiceRevision.objects.get(pk=accepted.revision_id)
        self.assertEqual(accepted.reason_code, "service_accepted")
        self.assertEqual(service.current_revision_id, first_revision.id)
        self.assertEqual(first_revision.revision_number, 1)
        self.assertEqual(first_revision.disposition, "accepted")
        self.assertEqual(first_revision.unit_amount, Decimal("10.25"))
        self.assertEqual(first_revision.evidence_observation_id, observation.id)
        self.assertEqual(first_revision.identity_decision_id, resolved.decision_id)

        replay = self.accepted_service(
            resolved,
            observation,
            request_id=request_id,
            code="SYN-A",
            units=2,
            unit_amount="10.25",
            reason="Synthetic initial service",
        )
        self.assertEqual(replay.reason_code, "service_request_replayed")
        self.assertTrue(replay.replayed)
        self.assertEqual(replay.service_id, accepted.service_id)
        self.assertEqual(replay.revision_id, accepted.revision_id)
        self.assertEqual(Service.objects.filter(organization=self.alpha).count(), 1)
        self.assertEqual(ServiceRevision.objects.filter(organization=self.alpha).count(), 1)

        with self.assertRaises(CommandError) as changed_request:
            self.accepted_service(
                resolved,
                observation,
                request_id=request_id,
                code="SYN-B",
                units=2,
                unit_amount="10.25",
                reason="Synthetic changed service intent",
            )
        self.assertEqual(changed_request.exception.reason_code, "request_input_conflict")

        corrected = revise_service(
            actor=self.alpha_user,
            organization_id=self.alpha.id,
            request_id=uuid.uuid4(),
            service_id=accepted.service_id,
            expected_revision_id=accepted.revision_id,
            evidence_observation_id=observation.id,
            disposition="accepted",
            code="SYN-B",
            units=1,
            unit_amount=Decimal("3.40"),
            currency="USD",
            reason="Synthetic correction with provenance",
            artifact_store=self.store,
        )
        second_revision = ServiceRevision.objects.get(pk=corrected.revision_id)
        self.assertEqual(corrected.reason_code, "service_revised")
        self.assertEqual(second_revision.revision_number, 2)
        self.assertEqual(second_revision.predecessor_id, first_revision.id)
        self.assertEqual(second_revision.decided_by_id, self.alpha_user.id)
        self.assertEqual(second_revision.reason, "Synthetic correction with provenance")
        self.assertEqual(second_revision.evidence_observation_id, observation.id)
        self.assertEqual(second_revision.identity_decision_id, resolved.decision_id)
        self.assertEqual(second_revision.code, "SYN-B")
        self.assertEqual(second_revision.unit_amount, Decimal("3.40"))
        self.assertEqual(Service.objects.get(pk=accepted.service_id).current_revision_id, second_revision.id)
        self.assertTrue(ServiceRevision.objects.filter(pk=first_revision.id).exists())

        with self.assertRaises(CommandError) as stale_revision:
            revise_service(
                actor=self.alpha_user,
                organization_id=self.alpha.id,
                request_id=uuid.uuid4(),
                service_id=accepted.service_id,
                expected_revision_id=first_revision.id,
                evidence_observation_id=observation.id,
                disposition="accepted",
                code="SYN-A",
                units=1,
                unit_amount="1.00",
                currency="USD",
                reason="Synthetic stale correction",
                artifact_store=self.store,
            )
        self.assertEqual(stale_revision.exception.reason_code, "service_revision_conflict")

        excluded = revise_service(
            actor=self.alpha_user,
            organization_id=self.alpha.id,
            request_id=uuid.uuid4(),
            service_id=accepted.service_id,
            expected_revision_id=second_revision.id,
            evidence_observation_id=observation.id,
            disposition="excluded",
            reason="Synthetic exclusion after review",
            artifact_store=self.store,
        )
        excluded_revision = ServiceRevision.objects.get(pk=excluded.revision_id)
        self.assertEqual(excluded_revision.disposition, "excluded")
        self.assertEqual(excluded_revision.predecessor_id, second_revision.id)
        self.assertEqual(excluded_revision.code, second_revision.code)
        self.assertEqual(excluded_revision.units, second_revision.units)
        self.assertEqual(excluded_revision.unit_amount, second_revision.unit_amount)
        self.assertEqual(excluded_revision.currency, second_revision.currency)
        self.assertEqual(ServiceRevision.objects.filter(service=service).count(), 3)

    def test_decimal_bounds_zero_and_policy_input_rejections_are_atomic(self):
        _delivery, observation, resolved = self.resolved_observation(
            note="SYNTHETIC_F2_DECIMAL_RULES"
        )
        invalid_inputs = (
            ("SYN-C", 1, "1.00", "USD", "service_code_unsupported"),
            ("SYN-A", 0, "1.00", "USD", "service_units_invalid"),
            ("SYN-A", 101, "1.00", "USD", "service_units_invalid"),
            ("SYN-A", 1, 1.25, "USD", "service_amount_invalid"),
            ("SYN-A", 1, "NaN", "USD", "service_amount_invalid"),
            ("SYN-A", 1, "-0.01", "USD", "service_amount_invalid"),
            ("SYN-A", 1, "1.001", "USD", "service_amount_precision"),
            ("SYN-A", 1, "1.00", "CAD", "service_currency_unsupported"),
        )
        for index, (code, units, amount, currency, reason_code) in enumerate(invalid_inputs):
            with self.assertRaises(CommandError) as invalid:
                self.accepted_service(
                    resolved,
                    observation,
                    request_id=uuid.uuid5(uuid.NAMESPACE_URL, f"synthetic-f2-invalid-{index}"),
                    code=code,
                    units=units,
                    unit_amount=amount,
                    currency=currency,
                    reason="Synthetic rejected economics",
                )
            self.assertEqual(invalid.exception.reason_code, reason_code)
        self.assertEqual(Service.objects.filter(organization=self.alpha).count(), 0)
        self.assertEqual(ServiceRevision.objects.filter(organization=self.alpha).count(), 0)

        zero = self.accepted_service(
            resolved,
            observation,
            code="SYN-A",
            units=100,
            unit_amount=Decimal("0.00"),
            reason="Synthetic zero-valued service",
        )
        maximum = self.accepted_service(
            resolved,
            observation,
            code="SYN-B",
            units=100,
            unit_amount=Decimal("9999.99"),
            reason="Synthetic maximum-valued service",
        )
        zero_revision = ServiceRevision.objects.get(pk=zero.revision_id)
        maximum_revision = ServiceRevision.objects.get(pk=maximum.revision_id)
        self.assertEqual(zero_revision.unit_amount, Decimal("0.00"))
        self.assertEqual(zero_revision.units, 100)
        self.assertEqual(maximum_revision.unit_amount, Decimal("9999.99"))
        self.assertEqual(maximum_revision.units, 100)
        self.assertEqual(
            Service.objects.filter(organization=self.alpha).annotate(revisions=Count("revisions")).count(),
            2,
        )

    def test_cross_organization_and_inactive_membership_fail_closed(self):
        _alpha_delivery, alpha_observation, alpha_resolved = self.resolved_observation(
            note="SYNTHETIC_F2_ALPHA_SERVICE"
        )
        alpha_request = uuid.uuid4()
        alpha_service = self.accepted_service(
            alpha_resolved,
            alpha_observation,
            request_id=alpha_request,
            reason="Synthetic alpha service",
        )
        _beta_delivery, beta_observation, beta_resolved = self.resolved_observation(
            actor=self.beta_user,
            organization=self.beta,
            note="SYNTHETIC_F2_BETA_SERVICE",
        )
        beta_service = self.accepted_service(
            beta_resolved,
            beta_observation,
            actor=self.beta_user,
            organization=self.beta,
            reason="Synthetic beta service",
        )

        with self.assertRaises(AuthorizationError):
            service_detail(
                actor=self.alpha_user,
                organization_id=self.beta.id,
                service_id=beta_service.service_id,
            )
        with self.assertRaises(CommandError) as scoped_not_found:
            service_detail(
                actor=self.alpha_user,
                organization_id=self.alpha.id,
                service_id=beta_service.service_id,
            )
        self.assertEqual(scoped_not_found.exception.reason_code, "service_not_found")
        with self.assertRaises(AuthorizationError):
            self.accepted_service(
                beta_resolved,
                beta_observation,
                actor=self.alpha_user,
                organization=self.beta,
                reason="Synthetic unauthorized service",
            )
        with self.assertRaises(CommandError) as wrong_scope:
            self.accepted_service(
                beta_resolved,
                beta_observation,
                actor=self.alpha_user,
                organization=self.alpha,
                reason="Synthetic wrong organization service",
            )
        self.assertEqual(wrong_scope.exception.reason_code, "service_evidence_not_resolved")

        alpha_membership = Membership.objects.get(
            organization=self.alpha, user=self.alpha_user
        )
        alpha_membership.is_active = False
        alpha_membership.save(update_fields=["is_active"])
        with self.assertRaises(AuthorizationError):
            service_detail(
                actor=self.alpha_user,
                organization_id=self.alpha.id,
                service_id=alpha_service.service_id,
            )
        with self.assertRaises(AuthorizationError):
            self.accepted_service(
                alpha_resolved,
                alpha_observation,
                request_id=alpha_request,
                reason="Synthetic replay while inactive",
            )
        with self.assertRaises(AuthorizationError):
            list(current_services_for_encounter(
                actor=self.alpha_user,
                organization_id=self.alpha.id,
                encounter_id=alpha_resolved.encounter_id,
            ))

