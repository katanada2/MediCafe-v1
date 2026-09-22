from __future__ import annotations

import hashlib
import unittest
import uuid
from datetime import date

import django
from django.apps import apps
from django.db import DatabaseError, IntegrityError, connection, transaction
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase

if not apps.ready:
    django.setup()

from medicafe_v1.access.models import Membership, Organization, User
from medicafe_v1.claims.commands import (
    approve_claim_revision,
    prepare_claim_revision,
    select_synthetic_policy,
)
from medicafe_v1.claims.delivery_commands import request_delivery
from medicafe_v1.claims.models import (
    ClaimApproval,
    ClaimRevision,
    ClaimsCommandReceipt,
    DeliveryIntent,
    SyntheticPolicySelection,
)
from medicafe_v1.records.models import Encounter, Patient

from tests.f2.base import F2TransactionTestCase


class ClaimsUpgradeRegressionTests(TransactionTestCase):
    """Exercise the claims0003-to-current upgrade on PostgreSQL only."""

    migrate_from = ("claims", "0003_f2_claim_integrity")
    migrate_to = ("claims", "0009_f3_receipt_and_observation_targets")

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        if connection.vendor != "postgresql":
            raise unittest.SkipTest("claims migration regression requires PostgreSQL")

    def setUp(self):
        super().setUp()
        self.executor = MigrationExecutor(connection)
        self.addCleanup(self._restore_latest_migrations)
        self.executor.migrate([self.migrate_from])

    def _restore_latest_migrations(self):
        MigrationExecutor(connection).migrate([self.migrate_to])

    @staticmethod
    def _normalized_receipts(receipt_model):
        fields = (
            "id",
            "request_uuid",
            "command_kind",
            "target_key",
            "expected_predecessor_id",
            "intent_digest",
            "result_claim_id",
            "result_revision_id",
            "result_approval_id",
            "result_policy_version",
            "result_policy_generation",
            "accepted_at",
        )
        rows = receipt_model.objects.order_by("command_kind").values(*fields)
        normalized = []
        for row in rows:
            normalized.append({
                field: (
                    value.isoformat()
                    if hasattr(value, "isoformat")
                    else str(value)
                    if isinstance(value, uuid.UUID)
                    else value
                )
                for field, value in row.items()
            })
        return normalized

    def _seed_claims0003_history(self):
        historical_apps = self.executor.loader.project_state([self.migrate_from]).apps
        HistoricalApproval = historical_apps.get_model("claims", "ClaimApproval")
        HistoricalClaim = historical_apps.get_model("claims", "Claim")
        HistoricalClaimRevision = historical_apps.get_model("claims", "ClaimRevision")
        HistoricalReceipt = historical_apps.get_model("claims", "ClaimsCommandReceipt")
        HistoricalPolicy = historical_apps.get_model("claims", "SyntheticPolicySelection")

        organization = Organization.objects.create(name="Synthetic Upgrade Organization")
        actor = User.objects.create_user(
            username="synthetic-upgrade-actor", password="synthetic-password"
        )
        patient = Patient.objects.create(
            organization=organization, display_name="Synthetic Upgrade Patient"
        )
        encounter = Encounter.objects.create(
            organization=organization, patient=patient, service_date=date(2026, 1, 15)
        )
        policy = HistoricalPolicy.objects.create(
            id=uuid.uuid4(), organization_id=organization.id,
            version="synthetic-v1", activation_generation=1, selected_by_id=actor.id,
        )
        with transaction.atomic():
            claim = HistoricalClaim.objects.create(
                id=uuid.uuid4(), organization_id=organization.id,
                encounter_id=encounter.id, patient_id=patient.id,
            )
            payload = b'{"synthetic":true,"upgrade":"claims0003"}'
            envelope_digest = hashlib.sha256(payload).hexdigest()
            revision = HistoricalClaimRevision.objects.create(
                id=uuid.uuid4(), organization_id=organization.id, claim_id=claim.id,
                encounter_id=encounter.id, patient_id=patient.id, revision_number=1,
                predecessor_id=None, prepared_by_id=actor.id, reason="Synthetic upgrade history",
                policy_version=policy.version, policy_generation=policy.activation_generation,
                route_id="synthetic-receiver", route_version="v1",
                envelope_format_version="synthetic-json-v1", envelope_bytes=payload,
                envelope_digest=envelope_digest, total_amount="0.00", currency="USD",
            )
            HistoricalClaim.objects.filter(pk=claim.id).update(
                current_revision_id=revision.id
            )
            approval = HistoricalApproval.objects.create(
                id=uuid.uuid4(), organization_id=organization.id,
                claim_revision_id=revision.id, envelope_digest=envelope_digest,
                approved_by_id=actor.id,
            )
            historical_prepare_receipt = HistoricalReceipt.objects.create(
                id=uuid.uuid4(), organization_id=organization.id,
                request_uuid=uuid.uuid4(), command_kind="prepare_claim_revision",
                target_key=str(encounter.id), expected_predecessor_id=None,
                intent_digest=hashlib.sha256(b"synthetic-prepare-receipt").hexdigest(),
                result_claim_id=claim.id, result_revision_id=revision.id,
                result_approval_id=None, result_policy_version=policy.version,
                result_policy_generation=policy.activation_generation,
            )
            historical_policy_receipt = HistoricalReceipt.objects.create(
                id=uuid.uuid4(), organization_id=organization.id,
                request_uuid=uuid.uuid4(), command_kind="select_synthetic_policy",
                target_key=str(organization.id), expected_predecessor_id=None,
                intent_digest=hashlib.sha256(b"synthetic-policy-receipt").hexdigest(),
                result_claim_id=None, result_revision_id=None, result_approval_id=None,
                result_policy_version=policy.version,
                result_policy_generation=policy.activation_generation,
            )
            historical_approval_receipt = HistoricalReceipt.objects.create(
                id=uuid.uuid4(), organization_id=organization.id,
                request_uuid=uuid.uuid4(), command_kind="approve_claim_revision",
                target_key=str(revision.id), expected_predecessor_id=None,
                intent_digest=hashlib.sha256(b"synthetic-approval-receipt").hexdigest(),
                result_claim_id=claim.id, result_revision_id=revision.id,
                result_approval_id=approval.id, result_policy_version=policy.version,
                result_policy_generation=policy.activation_generation,
            )
            self.assertIsNotNone(historical_prepare_receipt.id)
            self.assertIsNotNone(historical_policy_receipt.id)
            self.assertIsNotNone(historical_approval_receipt.id)
        snapshot = self._normalized_receipts(HistoricalReceipt)
        return snapshot

    def test_claims0003_receipts_survive_current_f3_upgrade_unchanged(self):
        historical_snapshot = self._seed_claims0003_history()

        self.executor = MigrationExecutor(connection)
        self.executor.migrate([self.migrate_to])
        current_apps = self.executor.loader.project_state([self.migrate_to]).apps
        CurrentReceipt = current_apps.get_model("claims", "ClaimsCommandReceipt")
        current_snapshot = self._normalized_receipts(CurrentReceipt)

        self.assertEqual(current_snapshot, historical_snapshot)
        for receipt in CurrentReceipt.objects.all():
            self.assertIsNone(receipt.accepted_by_id)
            self.assertEqual(receipt.result_code, "")


class F2ReceiptAttributionRegressionTests(F2TransactionTestCase):
    """Check caller attribution on coalesced F2 receipts and policy history."""

    def _add_second_alpha_member(self):
        Membership.objects.create(organization=self.alpha, user=self.beta_user)

    def _approved_revision(self, *, note):
        _delivery, observation, resolved = self.resolved_observation(note=note)
        service = self.accepted_service(
            resolved, observation, code="SYN-A", units=1, unit_amount="4.00",
            reason="Synthetic upgrade receipt attribution service",
        )
        prepared = prepare_claim_revision(
            actor=self.alpha_user,
            organization_id=self.alpha.id,
            request_id=uuid.uuid4(),
            encounter_id=resolved.encounter_id,
            expected_claim_revision_id=None,
            selected_service_revision_ids=[service.revision_id],
            route_id="synthetic-receiver",
            route_version="v1",
            reason="Synthetic upgrade receipt attribution revision",
        )
        revision = ClaimRevision.objects.get(pk=prepared.revision_id)
        approved = approve_claim_revision(
            actor=self.alpha_user,
            organization_id=self.alpha.id,
            request_id=uuid.uuid4(),
            claim_revision_id=revision.id,
            expected_envelope_digest=revision.envelope_digest,
        )
        return revision, approved

    def test_later_caller_coalesced_approval_receipt_keeps_its_actor(self):
        self._add_second_alpha_member()
        revision, approved = self._approved_revision(
            note="SYNTHETIC_F2_APPROVAL_RECEIPT_ACTORS"
        )
        first_receipt = ClaimsCommandReceipt.objects.get(
            command_kind="approve_claim_revision", result_approval_id=approved.approval_id
        )

        later_request = uuid.uuid4()
        later = approve_claim_revision(
            actor=self.beta_user,
            organization_id=self.alpha.id,
            request_id=later_request,
            claim_revision_id=revision.id,
            expected_envelope_digest=revision.envelope_digest,
        )
        later_receipt = ClaimsCommandReceipt.objects.get(request_uuid=later_request)
        approval = ClaimApproval.objects.get(pk=approved.approval_id)

        self.assertEqual(later.approval_id, approved.approval_id)
        self.assertEqual(first_receipt.accepted_by_id, self.alpha_user.id)
        self.assertEqual(later_receipt.accepted_by_id, self.beta_user.id)
        self.assertEqual(approval.approved_by_id, self.alpha_user.id)

    def test_old_policy_receipt_keeps_actor_when_selector_changes(self):
        self._add_second_alpha_member()
        first_request = uuid.uuid4()
        first = select_synthetic_policy(
            actor=self.alpha_user, organization_id=self.alpha.id,
            request_id=first_request, expected_version="synthetic-v1",
            expected_generation=1, version="synthetic-v2",
        )
        first_receipt = ClaimsCommandReceipt.objects.get(request_uuid=first_request)

        second_request = uuid.uuid4()
        second = select_synthetic_policy(
            actor=self.beta_user, organization_id=self.alpha.id,
            request_id=second_request, expected_version="synthetic-v2",
            expected_generation=2, version="synthetic-v1",
        )
        second_receipt = ClaimsCommandReceipt.objects.get(request_uuid=second_request)
        current = SyntheticPolicySelection.objects.get(organization_id=self.alpha.id)

        self.assertEqual(first.policy_version, "synthetic-v2")
        self.assertEqual(first.policy_generation, 2)
        self.assertEqual(second.policy_version, "synthetic-v1")
        self.assertEqual(second.policy_generation, 3)
        self.assertEqual(first_receipt.accepted_by_id, self.alpha_user.id)
        self.assertEqual(second_receipt.accepted_by_id, self.beta_user.id)
        self.assertEqual(first_receipt.result_policy_version, "synthetic-v2")
        self.assertEqual(first_receipt.result_policy_generation, 2)
        self.assertEqual(current.version, "synthetic-v1")
        self.assertEqual(current.activation_generation, 3)
        self.assertEqual(current.selected_by_id, self.beta_user.id)

    def test_new_f3_null_actor_receipt_hits_named_shape_guard(self):
        revision, _approved = self._approved_revision(
            note="SYNTHETIC_F3_RECEIPT_SHAPE_GUARD"
        )
        requested = request_delivery(
            actor=self.alpha_user,
            organization_id=self.alpha.id,
            request_id=uuid.uuid4(),
            claim_revision_id=revision.id,
            expected_envelope_digest=revision.envelope_digest,
        )
        intent = requested.intent_id
        work = requested.work_id
        current_intent = revision.delivery_intents.get(pk=intent)
        current_work = current_intent.work
        self.assertEqual(current_work.id, work)

        with self.assertRaises(IntegrityError) as raised:
            with transaction.atomic():
                ClaimsCommandReceipt.objects.create(
                    organization_id=self.alpha.id,
                    request_uuid=uuid.uuid4(),
                    command_kind="request_delivery",
                    target_key=str(revision.id),
                    intent_digest="0" * 64,
                    result_claim_id=revision.claim_id,
                    result_revision_id=revision.id,
                    result_approval_id=revision.approvals.get().id,
                    result_delivery_intent_id=current_intent.id,
                    result_delivery_work_id=current_work.id,
                    result_code="delivery_coalesced",
                    accepted_by_id=None,
                )

        cause = raised.exception.__cause__
        diagnostic = getattr(cause, "diag", None)
        self.assertEqual(
            getattr(diagnostic, "constraint_name", None),
            "claims_receipt_result_shape_ck",
        )
        self.assertNotIn("foreign key", str(raised.exception).lower())

    def test_populated_f3_downgrade_is_refused_before_history_changes(self):
        revision, _approved = self._approved_revision(
            note="SYNTHETIC_F3_DOWNGRADE_REFUSAL"
        )
        requested = request_delivery(
            actor=self.alpha_user, organization_id=self.alpha.id,
            request_id=uuid.uuid4(), claim_revision_id=revision.id,
            expected_envelope_digest=revision.envelope_digest,
        )
        receipt_ids = set(ClaimsCommandReceipt.objects.values_list("id", flat=True))

        with self.assertRaisesMessage(
            DatabaseError,
            "populated F3 rollback is unsupported",
        ):
            MigrationExecutor(connection).migrate([
                ("claims", "0008_f3_work_transition_guards")
            ])

        applied = MigrationExecutor(connection).loader.applied_migrations
        self.assertIn(("claims", "0009_f3_receipt_and_observation_targets"), applied)
        self.assertEqual(
            set(ClaimsCommandReceipt.objects.values_list("id", flat=True)), receipt_ids
        )
        self.assertTrue(DeliveryIntent.objects.filter(id=requested.intent_id).exists())
