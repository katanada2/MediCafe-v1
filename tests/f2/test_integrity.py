from __future__ import annotations

import uuid
from decimal import Decimal

from django.db import DatabaseError, IntegrityError, connection, transaction

from medicafe_v1.claims.commands import (
    approve_claim_revision,
    prepare_claim_revision,
    select_synthetic_policy,
)
from medicafe_v1.claims.models import (
    Claim,
    ClaimApproval,
    ClaimLine,
    ClaimRevision,
    ClaimsCommandReceipt,
)
from medicafe_v1.records.commands import revise_service
from medicafe_v1.records.models import Service, ServiceRevision

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

    def _candidate_revision(self, predecessor):
        return ClaimRevision.objects.create(
            organization_id=predecessor.organization_id,
            claim_id=predecessor.claim_id,
            encounter_id=predecessor.encounter_id,
            patient_id=predecessor.patient_id,
            revision_number=predecessor.revision_number + 1,
            predecessor=predecessor,
            prepared_by=self.alpha_user,
            reason="Synthetic relationship candidate",
            policy_version=predecessor.policy_version,
            policy_generation=predecessor.policy_generation,
            route_id=predecessor.route_id,
            route_version=predecessor.route_version,
            envelope_format_version=predecessor.envelope_format_version,
            envelope_bytes=b"{}",
            envelope_digest="0" * 64,
            total_amount=Decimal("0.00"),
            currency="USD",
        )

    def test_cross_row_identity_and_head_guards_reject_mismatched_f2_rows(self):
        _delivery_a, _observation_a, resolved_a, service_a, claim_a = self._claim_fixture(
            note="SYNTHETIC_F2_RELATION_A"
        )
        _delivery_b, _observation_b, resolved_b, service_b, claim_b = self._claim_fixture(
            note="SYNTHETIC_F2_RELATION_B"
        )

        wrong_patient, _wrong_patient_encounter = self.create_patient_encounter(
            display_name="Synthetic wrong claim patient"
        )
        _right_patient, unclaimed_encounter = self.create_patient_encounter(
            display_name="Synthetic unclaimed encounter patient",
            service_date="2026-01-16",
        )
        with self.assertRaisesMessage(IntegrityError, "claims_case_encounter_patient_fk"):
            with transaction.atomic():
                Claim.objects.create(
                    organization=self.alpha,
                    encounter=unclaimed_encounter,
                    patient=wrong_patient,
                )
                with connection.cursor() as cursor:
                    cursor.execute("SET CONSTRAINTS claims_case_encounter_patient_fk IMMEDIATE")

        service_a_row = Service.objects.get(pk=service_a.service_id)
        claim_a_row = Claim.objects.get(pk=claim_a.claim_id)
        head_cases = (
            (
                "service",
                "UPDATE records_service SET current_revision_id = %s WHERE id = %s",
                [str(service_b.revision_id), str(service_a_row.id)],
                "service head target invalid",
            ),
            (
                "claim",
                "UPDATE claims_claim SET current_revision_id = %s WHERE id = %s",
                [str(claim_b.id), str(claim_a_row.id)],
                "claim head target invalid",
            ),
        )
        for label, statement, parameters, expected_error in head_cases:
            with self.subTest(head=label):
                with self.assertRaisesMessage(DatabaseError, expected_error):
                    with transaction.atomic():
                        with connection.cursor() as cursor:
                            cursor.execute(statement, parameters)

        with self.assertRaisesMessage(IntegrityError, "claims_approval_revision_digest_fk"):
            with transaction.atomic():
                ClaimApproval.objects.create(
                    organization=self.beta,
                    claim_revision=claim_a,
                    envelope_digest=claim_a.envelope_digest,
                    approved_by=self.beta_user,
                )
                with connection.cursor() as cursor:
                    cursor.execute("SET CONSTRAINTS claims_approval_revision_digest_fk IMMEDIATE")

        with self.assertRaisesMessage(IntegrityError, "claims_rev_case_target_fk"):
            with transaction.atomic():
                ClaimRevision.objects.create(
                    organization=self.alpha,
                    claim_id=claim_a.claim_id,
                    encounter_id=resolved_b.encounter_id,
                    patient_id=resolved_b.patient_id,
                    revision_number=2,
                    predecessor=claim_a,
                    prepared_by=self.alpha_user,
                    reason="Synthetic mismatched successor identity",
                    policy_version=claim_a.policy_version,
                    policy_generation=claim_a.policy_generation,
                    route_id=claim_a.route_id,
                    route_version=claim_a.route_version,
                    envelope_format_version=claim_a.envelope_format_version,
                    envelope_bytes=b"{}",
                    envelope_digest="0" * 64,
                    total_amount=Decimal("0.00"),
                    currency="USD",
                )
                with connection.cursor() as cursor:
                    cursor.execute("SET CONSTRAINTS claims_rev_case_target_fk IMMEDIATE")

    def test_claim_lines_can_only_be_inserted_during_revision_construction(self):
        _delivery, observation, resolved, service, first_revision = self._claim_fixture(
            note="SYNTHETIC_F2_LINE_SEAL"
        )
        extra_service = self.accepted_service(
            resolved,
            observation,
            code="SYN-B",
            units=1,
            unit_amount="2.00",
            reason="Synthetic line sealing probe",
        )

        def append_to(revision):
            ClaimLine.objects.create(
                organization=self.alpha,
                claim_revision=revision,
                claim_id=revision.claim_id,
                service_id=extra_service.service_id,
                service_revision_id=extra_service.revision_id,
                encounter_id=revision.encounter_id,
                patient_id=revision.patient_id,
                ordinal=2,
                code="SYN-B",
                units=1,
                unit_amount=Decimal("2.00"),
                line_amount=Decimal("2.00"),
                currency="USD",
            )

        with self.subTest(state="current"):
            with self.assertRaisesMessage(
                DatabaseError, "claim lines may only be inserted while revision is under construction"
            ):
                with transaction.atomic():
                    append_to(first_revision)

        approve_claim_revision(
            actor=self.alpha_user,
            organization_id=self.alpha.id,
            request_id=uuid.uuid4(),
            claim_revision_id=first_revision.id,
            expected_envelope_digest=first_revision.envelope_digest,
        )
        with self.subTest(state="approved"):
            with self.assertRaisesMessage(
                DatabaseError, "claim lines may only be inserted while revision is under construction"
            ):
                with transaction.atomic():
                    append_to(first_revision)

        revised_service = revise_service(
            actor=self.alpha_user,
            organization_id=self.alpha.id,
            request_id=uuid.uuid4(),
            service_id=service.service_id,
            expected_revision_id=service.revision_id,
            evidence_observation_id=observation.id,
            disposition="accepted",
            code="SYN-A",
            units=1,
            unit_amount="5.00",
            currency="USD",
            reason="Synthetic successor claim input",
            artifact_store=self.store,
        )
        prepare_claim_revision(
            actor=self.alpha_user,
            organization_id=self.alpha.id,
            request_id=uuid.uuid4(),
            encounter_id=resolved.encounter_id,
            expected_claim_revision_id=first_revision.id,
            selected_service_revision_ids=[revised_service.revision_id],
            route_id="synthetic-receiver",
            route_version="v1",
            reason="Synthetic successor claim",
        )
        with self.subTest(state="historical"):
            with self.assertRaisesMessage(
                DatabaseError, "claim lines may only be inserted while revision is under construction"
            ):
                with transaction.atomic():
                    append_to(first_revision)

    def test_receipts_bind_consistent_results_and_enforce_command_shapes(self):
        _delivery_a, _observation_a, _resolved_a, _service_a, claim_a = self._claim_fixture(
            note="SYNTHETIC_F2_RECEIPT_PAIR_A"
        )
        _delivery_b, _observation_b, _resolved_b, _service_b, claim_b = self._claim_fixture(
            note="SYNTHETIC_F2_RECEIPT_PAIR_B"
        )
        approval_b = ClaimApproval.objects.create(
            organization=self.alpha,
            claim_revision=claim_b,
            envelope_digest=claim_b.envelope_digest,
            approved_by=self.alpha_user,
        )

        with self.assertRaisesMessage(IntegrityError, "claims_receipt_claim_revision_pair_fk"):
            with transaction.atomic():
                ClaimsCommandReceipt.objects.create(
                    organization=self.alpha,
                    request_uuid=uuid.uuid4(),
                    command_kind="prepare_claim_revision",
                    target_key=f"encounter:{claim_a.encounter_id}",
                    expected_predecessor_id=None,
                    intent_digest="1" * 64,
                    result_claim_id=claim_a.claim_id,
                    result_revision=claim_b,
                    result_policy_version=claim_b.policy_version,
                    result_policy_generation=claim_b.policy_generation,
                )

        with self.assertRaisesMessage(IntegrityError, "claims_receipt_revision_approval_pair_fk"):
            with transaction.atomic():
                ClaimsCommandReceipt.objects.create(
                    organization=self.alpha,
                    request_uuid=uuid.uuid4(),
                    command_kind="approve_claim_revision",
                    target_key=f"claim-revision:{claim_a.id}",
                    expected_predecessor_id=claim_a.id,
                    intent_digest="2" * 64,
                    result_claim_id=claim_a.claim_id,
                    result_revision=claim_a,
                    result_approval=approval_b,
                    result_policy_version=claim_a.policy_version,
                    result_policy_generation=claim_a.policy_generation,
                )

        with self.assertRaisesMessage(IntegrityError, "claims_receipt_revision_policy_pair_fk"):
            with transaction.atomic():
                ClaimsCommandReceipt.objects.create(
                    organization=self.alpha,
                    request_uuid=uuid.uuid4(),
                    command_kind="prepare_claim_revision",
                    target_key=f"encounter:{claim_a.encounter_id}",
                    expected_predecessor_id=None,
                    intent_digest="4" * 64,
                    result_claim_id=claim_a.claim_id,
                    result_revision=claim_a,
                    result_policy_version="synthetic-v2",
                    result_policy_generation=claim_a.policy_generation,
                )

        with self.assertRaisesMessage(IntegrityError, "claims_receipt_result_shape_ck"):
            with transaction.atomic():
                ClaimsCommandReceipt.objects.create(
                    organization=self.alpha,
                    request_uuid=uuid.uuid4(),
                    command_kind="prepare_claim_revision",
                    target_key=f"encounter:{claim_a.encounter_id}",
                    expected_predecessor_id=None,
                    intent_digest="3" * 64,
                )

        no_op_request = uuid.uuid4()
        result = select_synthetic_policy(
            actor=self.alpha_user,
            organization_id=self.alpha.id,
            request_id=no_op_request,
            expected_version="synthetic-v1",
            expected_generation=1,
            version="synthetic-v1",
        )
        self.assertEqual(result.reason_code, "policy_selection_unchanged")
        receipt = ClaimsCommandReceipt.objects.get(
            organization=self.alpha, request_uuid=no_op_request
        )
        self.assertIsNone(receipt.result_claim_id)
        self.assertIsNone(receipt.result_revision_id)
        self.assertIsNone(receipt.result_approval_id)
        self.assertEqual(receipt.result_policy_version, "synthetic-v1")
        self.assertEqual(receipt.result_policy_generation, 1)

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

        with self.assertRaisesMessage(DatabaseError, "immutable F2 records row"):
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
        with self.assertRaisesMessage(DatabaseError, "immutable F2 claims row"):
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

        with self.assertRaisesMessage(DatabaseError, "service head must advance to direct successor"):
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
        with self.assertRaisesMessage(DatabaseError, "claim head must advance to direct successor"):
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
        _delivery_b, observation_b, resolved_b, service_b, claim_b = self._claim_fixture(
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

        with self.assertRaisesMessage(IntegrityError, "claims_approval_revision_digest_fk"):
            with transaction.atomic():
                ClaimApproval.objects.create(
                    organization=self.alpha,
                    claim_revision=claim_a,
                    envelope_digest=claim_b.envelope_digest,
                    approved_by=self.alpha_user,
                )
        service_b_revision = service_b
        with self.assertRaisesMessage(IntegrityError, "claims_line_service_target_fk"):
            with transaction.atomic():
                candidate_a = self._candidate_revision(claim_a)
                ClaimLine.objects.create(
                    organization=self.alpha,
                    claim_revision=candidate_a,
                    claim_id=claim_a.claim_id,
                    service_id=service_b.service_id,
                    service_revision_id=service_b_revision.revision_id,
                    encounter_id=claim_a.encounter_id,
                    patient_id=claim_a.patient_id,
                    ordinal=1,
                    code="SYN-A",
                    units=1,
                    unit_amount=Decimal("6.00"),
                    line_amount=Decimal("6.00"),
                    currency="USD",
                )
                with connection.cursor() as cursor:
                    cursor.execute("SET CONSTRAINTS claims_line_service_target_fk IMMEDIATE")

        other_same_encounter = self.accepted_service(
            resolved_b,
            observation_b,
            code="SYN-B",
            units=1,
            unit_amount="7.00",
            reason="Synthetic same-encounter relationship probe",
        )
        with self.assertRaisesMessage(IntegrityError, "claims_line_srev_target_fk"):
            with transaction.atomic():
                candidate_b = self._candidate_revision(claim_b)
                ClaimLine.objects.create(
                    organization=self.alpha,
                    claim_revision=candidate_b,
                    claim_id=claim_b.claim_id,
                    service_id=other_same_encounter.service_id,
                    service_revision_id=service_b.revision_id,
                    encounter_id=claim_b.encounter_id,
                    patient_id=claim_b.patient_id,
                    ordinal=1,
                    code="SYN-A",
                    units=1,
                    unit_amount=Decimal("6.00"),
                    line_amount=Decimal("6.00"),
                    currency="USD",
                )
                with connection.cursor() as cursor:
                    cursor.execute("SET CONSTRAINTS claims_line_srev_target_fk IMMEDIATE")
