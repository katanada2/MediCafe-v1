from __future__ import annotations

import uuid

from django.utils import timezone

from medicafe_v1.archival.adapter import ArchiveEvidence, ArchiveTransportResult
from medicafe_v1.archival.commands import capture_archive_projection, queue_archive_batch
from medicafe_v1.archival.models import (
    ArchiveAttemptOutcome, ArchiveBatchItem, ArchiveProjection,
)
from medicafe_v1.archival.queries import archive_batch_status, archive_item_status
from medicafe_v1.archival.worker import run_archive_worker_once
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
