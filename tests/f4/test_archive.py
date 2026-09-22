from __future__ import annotations

import uuid
from datetime import timedelta

from django.db import DatabaseError, transaction
from django.utils import timezone

from medicafe_v1.archival.adapter import ArchiveEvidence, ArchiveTransportResult
from medicafe_v1.archival.commands import (
    capture_archive_projection, queue_archive_batch, retry_archive_item,
)
from medicafe_v1.archival.models import (
    ArchiveAttemptOutcome, ArchiveBatchItem, ArchiveProjection,
    ArchiveReadbackObservation, ArchiveWork,
)
from medicafe_v1.archival.queries import (
    archive_batch_status, archive_current_lag, archive_item_status,
)
from medicafe_v1.archival.worker import reconcile_archive_item, run_archive_worker_once
from medicafe_v1.outcomes.commands import accept_lifecycle
from medicafe_v1.sources.domain import CommandError
from tests.helpers.workflow_boundary_contract import assert_archive_boundary

from .base import F4TransactionTestCase


class MemoryArchiveAdapter:
    timeout = 0.1

    def __init__(self, *, readback=True):
        self.readback_enabled = readback
        self.rows = {}

    def validate_configuration(self, receiver_id, receiver_version):
        return None

    def send(self, frozen):
        existing = self.rows.get(frozen.projection_id)
        if existing and existing.payload != frozen.payload:
            return ArchiveTransportResult("rejected", "archive_target_conflict")
        if existing is None:
            self.rows[frozen.projection_id] = frozen
        return ArchiveTransportResult("accepted", "archive_target_response")

    def readback(self, frozen):
        if not self.readback_enabled:
            return None
        stored = self.rows.get(frozen.projection_id)
        if stored is None:
            return None
        return ArchiveEvidence(
            "synthetic-archive", "v1", f"archive-{stored.projection_id}",
            stored.organization_id, stored.encounter_id, stored.projection_id,
            stored.projection_version, stored.attempt_id,
            stored.projection_digest, stored.byte_length, stored.payload,
            timezone.now().isoformat(),
        )


class WrongProjectionReadbackAdapter(MemoryArchiveAdapter):
    def __init__(self, wrong_projection_id):
        super().__init__(readback=True)
        self.wrong_projection_id = str(wrong_projection_id)

    def readback(self, frozen):
        wrong = self.rows[self.wrong_projection_id]
        return ArchiveEvidence(
            "synthetic-archive", "v1", f"archive-{wrong.projection_id}",
            wrong.organization_id, wrong.encounter_id, wrong.projection_id,
            wrong.projection_version, wrong.attempt_id,
            wrong.projection_digest, wrong.byte_length, wrong.payload,
            timezone.now().isoformat(),
        )


class ArchiveFoundationTests(F4TransactionTestCase):
    def capture(self):
        _revision, intent, _observation, _result = self.delivered_claim()
        return capture_archive_projection(
            actor=self.alpha_user, organization_id=self.alpha.id,
            request_id=uuid.uuid4(), encounter_id=intent.claim_revision.encounter_id,
            expected_projection_id=None,
        )

    def test_capture_replays_same_fingerprint_without_new_version(self):
        first = self.capture()
        second = capture_archive_projection(
            actor=self.alpha_user, organization_id=self.alpha.id,
            request_id=uuid.uuid4(),
            encounter_id=ArchiveProjection.objects.get(id=first.projection_id).encounter_id,
            expected_projection_id=first.projection_id,
        )

        self.assertEqual(first.reason_code, "archive_projection_captured")
        self.assertEqual(second.reason_code, "archive_projection_unchanged")
        self.assertEqual(second.projection_id, first.projection_id)
        self.assertEqual(ArchiveProjection.objects.count(), 1)

    def test_worker_confirms_only_independent_exact_item_readback(self):
        captured = self.capture()
        queued = queue_archive_batch(
            actor=self.alpha_user, organization_id=self.alpha.id,
            request_id=uuid.uuid4(), projection_ids=[captured.projection_id],
        )
        adapter = MemoryArchiveAdapter()

        result = run_archive_worker_once(
            worker_id="archive-exact", lease_seconds=2, adapter=adapter
        )

        self.assertEqual(result.reason_code, "archive_item_confirmed")
        status = archive_item_status(
            actor=self.alpha_user, organization_id=self.alpha.id,
            projection_id=captured.projection_id,
        )
        self.assertEqual(status.state, "historically_confirmed")
        batch = archive_batch_status(
            actor=self.alpha_user, organization_id=self.alpha.id,
            batch_id=queued.batch_id,
        )
        self.assertEqual([item.state for item in batch], ["historically_confirmed"])
        assert_archive_boundary(
            self, projection=ArchiveProjection.objects.get(id=captured.projection_id),
            expected_attempts=1, expected_confirmed=True,
        )

    def test_send_success_without_readback_remains_unknown_and_retries_bounded(self):
        captured = self.capture()
        queued = queue_archive_batch(
            actor=self.alpha_user, organization_id=self.alpha.id,
            request_id=uuid.uuid4(), projection_ids=[captured.projection_id],
        )
        adapter = MemoryArchiveAdapter(readback=False)

        results = [run_archive_worker_once(
            worker_id=f"archive-unknown-{index}", lease_seconds=2, adapter=adapter
        ) for index in range(3)]

        self.assertEqual(
            [item.reason_code for item in results],
            ["archive_retry_pending", "archive_retry_pending", "archive_not_observed"],
        )
        item = ArchiveBatchItem.objects.get(batch_id=queued.batch_id)
        self.assertEqual(item.work.attempts.count(), 3)
        self.assertEqual(
            item.work.attempts.filter(outcome__kind=ArchiveAttemptOutcome.UNKNOWN).count(), 3
        )
        status = archive_item_status(
            actor=self.alpha_user, organization_id=self.alpha.id,
            projection_id=captured.projection_id,
        )
        self.assertEqual(status.state, "unknown_possible_write")
        assert_archive_boundary(
            self, projection=item.projection, expected_attempts=3,
            expected_confirmed=False,
        )

    def test_retry_coalesces_pending_automatic_authorization(self):
        captured = self.capture()
        queue_archive_batch(
            actor=self.alpha_user, organization_id=self.alpha.id,
            request_id=uuid.uuid4(), projection_ids=[captured.projection_id],
        )
        adapter = MemoryArchiveAdapter(readback=False)
        first = run_archive_worker_once(
            worker_id="archive-auto-unknown", lease_seconds=2, adapter=adapter,
        )
        work = ArchiveWork.objects.get(projection_id=captured.projection_id)
        authorization_id = work.scheduled_authorization_id

        retry = retry_archive_item(
            actor=self.alpha_user, organization_id=self.alpha.id,
            request_id=uuid.uuid4(), projection_id=captured.projection_id,
            expected_attempt_id=first.attempt_id,
        )

        work.refresh_from_db()
        self.assertEqual(retry.reason_code, "archive_retry_already_scheduled")
        self.assertEqual(retry.authorization_id, authorization_id)
        self.assertEqual(work.scheduled_authorization_id, authorization_id)
        self.assertEqual(work.state, ArchiveWork.STATE_PENDING)

    def test_retry_preserves_original_reported_attempt_after_replayed_target_write(self):
        captured = self.capture()
        queue_archive_batch(
            actor=self.alpha_user, organization_id=self.alpha.id,
            request_id=uuid.uuid4(), projection_ids=[captured.projection_id],
        )
        adapter = MemoryArchiveAdapter(readback=False)
        first = run_archive_worker_once(
            worker_id="archive-original-write", lease_seconds=2, adapter=adapter,
        )
        adapter.readback_enabled = True

        second = run_archive_worker_once(
            worker_id="archive-replayed-write", lease_seconds=2, adapter=adapter,
        )

        observation = ArchiveReadbackObservation.objects.get(id=second.observation_id)
        self.assertEqual(second.reason_code, "archive_item_confirmed")
        self.assertEqual(observation.source_attempt_id, second.attempt_id)
        self.assertEqual(observation.reported_attempt_id, first.attempt_id)

    def test_independent_confirmation_prevents_retry_of_immutable_unknown(self):
        captured = self.capture()
        queue_archive_batch(
            actor=self.alpha_user, organization_id=self.alpha.id,
            request_id=uuid.uuid4(), projection_ids=[captured.projection_id],
        )
        adapter = MemoryArchiveAdapter(readback=False)
        results = [run_archive_worker_once(
            worker_id=f"archive-late-{index}", lease_seconds=2, adapter=adapter,
        ) for index in range(3)]
        adapter.readback_enabled = True
        reconciled = reconcile_archive_item(
            actor=self.alpha_user, organization_id=self.alpha.id,
            projection_id=captured.projection_id, adapter=adapter,
        )
        latest = results[-1]

        self.assertEqual(reconciled.reason_code, "archive_item_confirmed")
        with self.assertRaisesMessage(CommandError, "archive_retry_not_allowed"):
            retry_archive_item(
                actor=self.alpha_user, organization_id=self.alpha.id,
                request_id=uuid.uuid4(), projection_id=captured.projection_id,
                expected_attempt_id=latest.attempt_id,
            )

    def test_wrong_projection_readback_cannot_confirm_item_with_existing_unknown(self):
        first = self.capture()
        queue_archive_batch(
            actor=self.alpha_user, organization_id=self.alpha.id,
            request_id=uuid.uuid4(), projection_ids=[first.projection_id],
        )
        seed = MemoryArchiveAdapter(readback=False)
        for index in range(3):
            run_archive_worker_once(
                worker_id=f"archive-first-{index}", lease_seconds=2, adapter=seed,
            )
        seed.readback_enabled = True
        reconcile_archive_item(
            actor=self.alpha_user, organization_id=self.alpha.id,
            projection_id=first.projection_id, adapter=seed,
        )

        second = self.capture()
        queue_archive_batch(
            actor=self.alpha_user, organization_id=self.alpha.id,
            request_id=uuid.uuid4(), projection_ids=[second.projection_id],
        )
        wrong = WrongProjectionReadbackAdapter(first.projection_id)
        wrong.rows.update(seed.rows)
        result = run_archive_worker_once(
            worker_id="archive-wrong-item", lease_seconds=2, adapter=wrong,
        )

        self.assertEqual(result.reason_code, "archive_evidence_conflict")
        self.assertEqual(archive_item_status(
            actor=self.alpha_user, organization_id=self.alpha.id,
            projection_id=second.projection_id,
        ).state, "evidence_conflict")
        self.assertFalse(ArchiveAttemptOutcome.objects.filter(
            attempt__projection_id=second.projection_id,
            kind=ArchiveAttemptOutcome.TARGET_CONFIRMED,
        ).exists())

    def test_current_lag_uses_coherent_owner_snapshot(self):
        _revision, intent, observation, _result = self.delivered_claim()
        captured = capture_archive_projection(
            actor=self.alpha_user, organization_id=self.alpha.id,
            request_id=uuid.uuid4(), encounter_id=intent.claim_revision.encounter_id,
            expected_projection_id=None,
        )
        current = archive_current_lag(
            actor=self.alpha_user, organization_id=self.alpha.id,
            encounter_id=intent.claim_revision.encounter_id,
        )
        _delivery, candidate = self.admit_inbound(
            kind="lifecycle", intent=intent, observation=observation,
        )
        accept_lifecycle(
            actor=self.alpha_user, organization_id=self.alpha.id,
            request_id=uuid.uuid4(), candidate_id=candidate.candidate_id,
            artifact_store=self.store,
        )
        lagged = archive_current_lag(
            actor=self.alpha_user, organization_id=self.alpha.id,
            encounter_id=intent.claim_revision.encounter_id,
        )

        self.assertEqual(current.state, "current_projection")
        self.assertEqual(current.head_projection_id, captured.projection_id)
        self.assertEqual(lagged.state, "projection_lag")

    def test_capture_rejects_nested_transaction_before_isolation_change(self):
        _revision, intent, _observation, _result = self.delivered_claim()
        with transaction.atomic():
            with self.assertRaisesMessage(
                CommandError, "archive_snapshot_outer_transaction_forbidden",
            ):
                capture_archive_projection(
                    actor=self.alpha_user, organization_id=self.alpha.id,
                    request_id=uuid.uuid4(),
                    encounter_id=intent.claim_revision.encounter_id,
                    expected_projection_id=None,
                )

    def test_direct_work_lease_requires_fresh_generation(self):
        captured = self.capture()
        queue_archive_batch(
            actor=self.alpha_user, organization_id=self.alpha.id,
            request_id=uuid.uuid4(), projection_ids=[captured.projection_id],
        )
        work = ArchiveWork.objects.get(projection_id=captured.projection_id)
        with self.assertRaises(DatabaseError), transaction.atomic():
            ArchiveWork.objects.filter(id=work.id).update(
                state=ArchiveWork.STATE_LEASED,
                lease_owner="forged-worker",
                lease_expires_at=timezone.now() + timedelta(seconds=30),
            )
