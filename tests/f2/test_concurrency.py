from __future__ import annotations

import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from unittest.mock import patch

from django.db import close_old_connections

from medicafe_v1.access.models import User
from medicafe_v1.claims.commands import (
    approve_claim_revision,
    prepare_claim_revision,
    select_synthetic_policy,
)
from medicafe_v1.claims.models import ClaimApproval, ClaimRevision
from medicafe_v1.claims.queries import claim_actionability
from medicafe_v1.records.commands import revise_service
from medicafe_v1.records.models import RecordsCommandReceipt, Service, ServiceRevision
from medicafe_v1.sources.artifacts import LocalArtifactStore
from medicafe_v1.sources.domain import CommandError

from tests.f2.base import F2TransactionTestCase


class F2ConcurrencyTests(F2TransactionTestCase):
    def _run(self, callables):
        gate = threading.Barrier(len(callables))
        results, errors = [], []

        def worker(callable_):
            close_old_connections()
            try:
                gate.wait(timeout=15)
                results.append(callable_())
            except Exception as exc:
                errors.append(exc)
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=len(callables)) as executor:
            futures = [executor.submit(worker, callable_) for callable_ in callables]
            for future in futures:
                future.result(timeout=30)
        return results, errors

    def _fixture(self, note):
        _delivery, observation, resolved = self.resolved_observation(note=note)
        service = self.accepted_service(
            resolved, observation, code="SYN-A", units=1, unit_amount="4.00",
            reason="Synthetic concurrent service",
        )
        return observation, resolved, service

    def test_competing_service_revisions_and_claim_preparations_have_one_successor(self):
        observation, resolved, service = self._fixture("SYNTHETIC_F2_COMPETING_SUCCESSORS")

        def correction(amount):
            def call():
                actor = User.objects.get(pk=self.alpha_user.pk)
                return revise_service(
                    actor=actor, organization_id=self.alpha.id, request_id=uuid.uuid4(),
                    service_id=service.service_id, expected_revision_id=service.revision_id,
                    evidence_observation_id=observation.id, disposition="accepted", code="SYN-A",
                    units=1, unit_amount=amount, currency="USD", reason=f"Synthetic correction {amount}",
                    artifact_store=LocalArtifactStore(self.store.root),
                )
            return call

        results, errors = self._run([correction("5.00"), correction("6.00")])
        self.assertEqual(len(results), 1)
        self.assertEqual([error.reason_code for error in errors], ["service_revision_conflict"])
        self.assertEqual(ServiceRevision.objects.filter(predecessor_id=service.revision_id).count(), 1)
        current = Service.objects.get(pk=service.service_id).current_revision

        first_claim = prepare_claim_revision(
            actor=self.alpha_user, organization_id=self.alpha.id, request_id=uuid.uuid4(),
            encounter_id=resolved.encounter_id, expected_claim_revision_id=None,
            selected_service_revision_ids=[current.id], route_id="synthetic-receiver",
            route_version="v1", reason="Synthetic initial concurrent claim",
        )

        def preparation(route_version):
            def call():
                actor = User.objects.get(pk=self.alpha_user.pk)
                return prepare_claim_revision(
                    actor=actor, organization_id=self.alpha.id, request_id=uuid.uuid4(),
                    encounter_id=resolved.encounter_id,
                    expected_claim_revision_id=first_claim.revision_id,
                    selected_service_revision_ids=[current.id], route_id="synthetic-receiver",
                    route_version=route_version, reason=f"Synthetic competing claim {route_version}",
                )
            return call

        results, errors = self._run([preparation("v1"), preparation("v2")])
        self.assertEqual(len(results), 1)
        self.assertEqual([error.reason_code for error in errors], ["claim_revision_conflict"])
        self.assertEqual(ClaimRevision.objects.filter(predecessor_id=first_claim.revision_id).count(), 1)

    def test_identical_concurrent_request_creates_one_revision_and_one_receipt(self):
        observation, _resolved, service = self._fixture("SYNTHETIC_F2_IDENTICAL_REQUEST")
        request_id = uuid.uuid4()

        def correction():
            actor = User.objects.get(pk=self.alpha_user.pk)
            return revise_service(
                actor=actor, organization_id=self.alpha.id, request_id=request_id,
                service_id=service.service_id, expected_revision_id=service.revision_id,
                evidence_observation_id=observation.id, disposition="accepted", code="SYN-A",
                units=1, unit_amount="5.00", currency="USD", reason="Synthetic identical correction",
                artifact_store=LocalArtifactStore(self.store.root),
            )

        results, errors = self._run([correction, correction])
        self.assertEqual(errors, [])
        self.assertEqual(len(results), 2)
        self.assertEqual({result.revision_id for result in results}, {results[0].revision_id})
        self.assertEqual(sorted(result.replayed for result in results), [False, True])
        self.assertEqual(ServiceRevision.objects.filter(predecessor_id=service.revision_id).count(), 1)
        self.assertEqual(RecordsCommandReceipt.objects.filter(
            organization=self.alpha, request_uuid=request_id
        ).count(), 1)

    def test_correction_vs_approval_is_serialized_and_never_currently_approves_stale_input(self):
        observation, resolved, service = self._fixture("SYNTHETIC_F2_CORRECTION_APPROVAL_RACE")
        prepared = prepare_claim_revision(
            actor=self.alpha_user, organization_id=self.alpha.id, request_id=uuid.uuid4(),
            encounter_id=resolved.encounter_id, expected_claim_revision_id=None,
            selected_service_revision_ids=[service.revision_id], route_id="synthetic-receiver",
            route_version="v1", reason="Synthetic race claim",
        )
        revision = ClaimRevision.objects.get(pk=prepared.revision_id)

        def approve():
            actor = User.objects.get(pk=self.alpha_user.pk)
            return approve_claim_revision(
                actor=actor, organization_id=self.alpha.id, request_id=uuid.uuid4(),
                claim_revision_id=revision.id, expected_envelope_digest=revision.envelope_digest,
            )

        def correct():
            actor = User.objects.get(pk=self.alpha_user.pk)
            return revise_service(
                actor=actor, organization_id=self.alpha.id, request_id=uuid.uuid4(),
                service_id=service.service_id, expected_revision_id=service.revision_id,
                evidence_observation_id=observation.id, disposition="accepted", code="SYN-A",
                units=1, unit_amount="5.00", currency="USD", reason="Synthetic racing correction",
                artifact_store=LocalArtifactStore(self.store.root),
            )

        _results, errors = self._run([approve, correct])
        self.assertTrue(all(isinstance(error, CommandError) for error in errors))
        actionability = claim_actionability(
            actor=self.alpha_user, organization_id=self.alpha.id, claim_revision_id=revision.id
        )
        self.assertIn("selected_service_changed", actionability.blockers)
        if ClaimApproval.objects.filter(claim_revision=revision).exists():
            self.assertEqual(actionability.reason_code, "claim_not_actionable")

    def test_policy_change_vs_approval_is_serialized_and_never_currently_approves_stale_policy(self):
        _observation, resolved, service = self._fixture("SYNTHETIC_F2_POLICY_APPROVAL_RACE")
        prepared = prepare_claim_revision(
            actor=self.alpha_user, organization_id=self.alpha.id, request_id=uuid.uuid4(),
            encounter_id=resolved.encounter_id, expected_claim_revision_id=None,
            selected_service_revision_ids=[service.revision_id], route_id="synthetic-receiver",
            route_version="v1", reason="Synthetic policy race claim",
        )
        revision = ClaimRevision.objects.get(pk=prepared.revision_id)

        def approve():
            actor = User.objects.get(pk=self.alpha_user.pk)
            return approve_claim_revision(
                actor=actor, organization_id=self.alpha.id, request_id=uuid.uuid4(),
                claim_revision_id=revision.id, expected_envelope_digest=revision.envelope_digest,
            )

        def change_policy():
            actor = User.objects.get(pk=self.alpha_user.pk)
            return select_synthetic_policy(
                actor=actor, organization_id=self.alpha.id, request_id=uuid.uuid4(),
                expected_version="synthetic-v1", expected_generation=1, version="synthetic-v2",
            )

        results, errors = self._run([approve, change_policy])
        self.assertEqual(len(results) + len(errors), 2)
        self.assertTrue(all(isinstance(error, CommandError) for error in errors))
        actionability = claim_actionability(
            actor=self.alpha_user, organization_id=self.alpha.id, claim_revision_id=revision.id
        )
        self.assertIn("policy_changed", actionability.blockers)
        self.assertNotEqual(actionability.reason_code, "approved_current")

    def test_no_deadlock_when_claim_holds_encounter_and_service_holds_organization(self):
        observation, resolved, service = self._fixture("SYNTHETIC_F2_LOCK_ORDER")
        prepared = prepare_claim_revision(
            actor=self.alpha_user, organization_id=self.alpha.id, request_id=uuid.uuid4(),
            encounter_id=resolved.encounter_id, expected_claim_revision_id=None,
            selected_service_revision_ids=[service.revision_id], route_id="synthetic-receiver",
            route_version="v1", reason="Synthetic lock-order claim",
        )
        revision = ClaimRevision.objects.get(pk=prepared.revision_id)
        encounter_locked = threading.Event()
        organization_locked = threading.Event()
        import medicafe_v1.claims.commands as claim_commands
        import medicafe_v1.records.commands as record_commands
        original_lock_encounter = claim_commands.locked_encounter
        original_membership = record_commands.require_active_membership

        def coordinated_encounter(**kwargs):
            value = original_lock_encounter(**kwargs)
            encounter_locked.set()
            if not organization_locked.wait(timeout=15):
                raise RuntimeError("organization lock was not acquired")
            return value

        def coordinated_membership(**kwargs):
            value = original_membership(**kwargs)
            if kwargs.get("for_update"):
                organization_locked.set()
            return value

        results, errors = [], []

        def approval_worker():
            close_old_connections()
            try:
                actor = User.objects.get(pk=self.alpha_user.pk)
                results.append(approve_claim_revision(
                    actor=actor, organization_id=self.alpha.id, request_id=uuid.uuid4(),
                    claim_revision_id=revision.id, expected_envelope_digest=revision.envelope_digest,
                ))
            except Exception as exc:
                errors.append(exc)
            finally:
                close_old_connections()

        def correction_worker():
            close_old_connections()
            try:
                if not encounter_locked.wait(timeout=15):
                    raise RuntimeError("encounter lock was not acquired")
                actor = User.objects.get(pk=self.alpha_user.pk)
                results.append(revise_service(
                    actor=actor, organization_id=self.alpha.id, request_id=uuid.uuid4(),
                    service_id=service.service_id, expected_revision_id=service.revision_id,
                    evidence_observation_id=observation.id, disposition="accepted", code="SYN-A",
                    units=1, unit_amount="5.00", currency="USD", reason="Synthetic lock-order correction",
                    artifact_store=LocalArtifactStore(self.store.root),
                ))
            except Exception as exc:
                errors.append(exc)
            finally:
                close_old_connections()

        with patch.object(claim_commands, "locked_encounter", side_effect=coordinated_encounter), \
             patch.object(record_commands, "require_active_membership", side_effect=coordinated_membership):
            with ThreadPoolExecutor(max_workers=2) as executor:
                futures = [executor.submit(approval_worker), executor.submit(correction_worker)]
                for future in futures:
                    future.result(timeout=30)
        self.assertEqual(errors, [])
        self.assertEqual(len(results), 2)
        self.assertIn("selected_service_changed", claim_actionability(
            actor=self.alpha_user, organization_id=self.alpha.id, claim_revision_id=revision.id
        ).blockers)
