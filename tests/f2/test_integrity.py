from __future__ import annotations

import uuid
from decimal import Decimal

from django.db import DatabaseError, IntegrityError, connection, transaction

from medicafe_v1.claims.commands import (
    prepare_claim_revision,
    select_synthetic_policy,
)
from medicafe_v1.claims.models import ClaimApproval, ClaimLine, ClaimRevision
from medicafe_v1.records.commands import revise_service
from medicafe_v1.records.models import ServiceRevision

from tests.f2.base import F2TransactionTestCase


class F2PostgresIntegrityTests(F2TransactionTestCase):
    def _claim_fixture(self, *, note, amount="4.00"):
        delivery, observation, resolved = self.resolved_observation(note=note)
        service = self.accepted_service(
            resolved,
            observation,
            code="SYN-A",
            units=1,
            unit_amount=Decimal(amount),
            reason="Synthetic integrity service",
        )
        claim = prepare_claim_revision(
            actor=self.alpha_user,
            organization_id=self.alpha.id,
            request_id=uuid.uuid4(),
            encounter_id=resolved.encounter_id,
            expected_claim_revision_id=None,
            selected_service_revision_ids=[service.revision_id],
            route_id="synthetic-receiver",
            route_version="v1",
            reason="Synthetic integrity claim",
        )
        return delivery, observation, resolved, service, ClaimRevision.objects.get(pk=claim.revision_id)

    def test_immutable_history_and_service_claim_head_rewind_or_skip_fail(self):
        _delivery, observation, resolved, service, first_claim_revision = self._claim_fixture(
            note="SYNTHETIC_F2_IMMUTABLE_HEADS"
        )
        first_service_revision = ServiceRevision.objects.get(pk=service.revision_id)
        second_service = revise_service(
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
            reason="Synthetic second service revision",
            artifact_store=self.store,
        )
        second_service_revision = ServiceRevision.objects.get(pk=second_service.revision_id)
        second_claim = prepare_claim_revision(
            actor=self.alpha_user,
            organization_id=self.alpha.id,
            request_id=uuid.uuid4(),
            encounter_id=resolved.encounter_id,
            expected_claim_revision_id=first_claim_revision.id,
            selected_service_revision_ids=[second_service.revision_id],
            route_id="synthetic-receiver",
            route_version="v2",
            reason="Synthetic second claim revision",
        )
        second_claim_revision = ClaimRevision.objects.get(pk=second_claim.revision_id)
        first_claim_line = first_claim_revision.lines.get(ordinal=1)

        with self.assertRaises(DatabaseError):
            with transaction.atomic():
                with connection.cursor() as cursor:
                    cursor.execute(
                        "UPDATE records_servicerevision SET reason = %s WHERE id = %s",
                        ["Synthetic direct immutable update", str(first_service_revision.id)],
                    )
        with self.assertRaises(DatabaseError):
            with transaction.atomic():
                with connection.cursor() as cursor:
                    cursor.execute(
                        "DELETE FROM records_servicerevision WHERE id = %s",
                        [str(second_service_revision.id)],
                    )
        with self.assertRaises(DatabaseError):
            with transaction.atomic():
                with connection.cursor() as cursor:
                    cursor.execute(
                        "UPDATE claims_claimline SET code = %s WHERE id = %s",
                        ["SYN-B", str(first_claim_line.id)],
                    )
        with self.assertRaises(DatabaseError):
            with transaction.atomic():
                with connection.cursor() as cursor:
                    cursor.execute(
                        "DELETE FROM claims_claimline WHERE id = %s",
                        [str(first_claim_line.id)],
                    )

        with self.assertRaises(DatabaseError):
            with transaction.atomic():
                with connection.cursor() as cursor:
                    cursor.execute(
                        "UPDATE records_service SET current_revision_id = %s WHERE id = %s",
                        [str(first_service_revision.id), str(service.service_id)],
                    )
        with self.assertRaises(DatabaseError):
            with transaction.atomic():
                ServiceRevision.objects.create(
                    organization=self.alpha,
                    service_id=service.service_id,
                    encounter_id=resolved.encounter_id,
                    patient_id=resolved.patient_id,
                    revision_number=4,
                    predecessor=first_service_revision,
                    decided_by=self.alpha_user,
                    reason="Synthetic skipped service revision",
                    evidence_observation_id=observation.id,
                    identity_decision_id=resolved.decision_id,
                    disposition="accepted",
                    code="SYN-A",
                    units=1,
                    unit_amount=Decimal("5.00"),
                    currency="USD",
                )
        with self.assertRaises(DatabaseError):
            with transaction.atomic():
                with connection.cursor() as cursor:
                    cursor.execute(
                        "UPDATE claims_claim SET current_revision_id = %s WHERE id = %s",
                        [str(first_claim_revision.id), str(second_claim_revision.claim_id)],
                    )
        with self.assertRaises(DatabaseError):
            with transaction.atomic():
                ClaimRevision.objects.create(
                    organization=self.alpha,
                    claim_id=second_claim_revision.claim_id,
                    encounter_id=resolved.encounter_id,
                    patient_id=resolved.patient_id,
                    revision_number=4,
                    predecessor=first_claim_revision,
                    prepared_by=self.alpha_user,
                    reason="Synthetic skipped claim revision",
                    policy_version="synthetic-v1",
                    policy_generation=1,
                    route_id="synthetic-receiver",
                    route_version="v1",
                    envelope_format_version="synthetic-json-v1",
                    envelope_bytes=b"{}",
                    envelope_digest="0" * 64,
                    total_amount=Decimal("0.00"),
                    currency="USD",
                )

    def test_policy_rollback_and_wrong_aggregate_or_digest_pairs_fail(self):
        _delivery_a, _observation_a, _resolved_a, _service_a, claim_a = self._claim_fixture(
            note="SYNTHETIC_F2_PAIR_A"
        )
        _delivery_b, _observation_b, resolved_b, service_b, claim_b = self._claim_fixture(
            note="SYNTHETIC_F2_PAIR_B",
            amount="6.00",
        )
        switched = select_synthetic_policy(
            actor=self.alpha_user,
            organization_id=self.alpha.id,
            request_id=uuid.uuid4(),
            expected_version="synthetic-v1",
            expected_generation=1,
            version="synthetic-v2",
        )
        self.assertEqual(switched.policy_generation, 2)
        with self.assertRaises(DatabaseError):
            with transaction.atomic():
                with connection.cursor() as cursor:
                    cursor.execute(
                        "UPDATE claims_syntheticpolicyselection "
                        "SET version = %s WHERE organization_id = %s",
                        ["synthetic-v1", str(self.alpha.id)],
                    )

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                ClaimApproval.objects.create(
                    organization=self.alpha,
                    claim_revision=claim_a,
                    envelope_digest=claim_b.envelope_digest,
                    approved_by=self.alpha_user,
                )
        service_b_revision = service_b
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                ClaimLine.objects.create(
                    organization=self.alpha,
                    claim_revision=claim_a,
                    claim_id=claim_a.claim_id,
                    service_id=service_b.service_id,
                    service_revision_id=service_b_revision.revision_id,
                    encounter_id=claim_a.encounter_id,
                    patient_id=claim_a.patient_id,
                    ordinal=2,
                    code="SYN-A",
                    units=1,
                    unit_amount=Decimal("6.00"),
                    line_amount=Decimal("6.00"),
                    currency="USD",
                )

