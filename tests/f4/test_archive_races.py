from __future__ import annotations

import hashlib
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import timedelta

from django.db import close_old_connections
from django.utils import timezone

from medicafe_v1.archival.commands import (
    capture_archive_projection,
    queue_archive_batch,
    retry_archive_item,
)
from medicafe_v1.archival.models import (
    ArchiveAttempt,
    ArchiveAttemptOutcome,
    ArchiveAuthorization,
    ArchiveBatch,
    ArchiveReadbackObservation,
    ArchiveWork,
)
from medicafe_v1.archival.queries import archive_batch_status
from medicafe_v1.archival.worker import run_archive_worker_once
from medicafe_v1.sources.domain import CommandError

from .base import F4TransactionTestCase
from .test_archive import MemoryArchiveAdapter


class EvidenceVariantAdapter(MemoryArchiveAdapter):
    def __init__(self, variant):
        super().__init__()
        self.variant = variant

    def readback(self, frozen):
        evidence = super().readback(frozen)
        if self.variant == "receiver":
            return replace(evidence, receiver_id="wrong-archive")
        if self.variant == "version":
            return replace(evidence, projection_version=evidence.projection_version + 1)
        if self.variant == "bytes":
            changed = evidence.received_bytes + b"x"
            return replace(
                evidence,
                projection_digest=hashlib.sha256(changed).hexdigest(),
                byte_length=len(changed),
                received_bytes=changed,
            )
        raise AssertionError(self.variant)


class SelectiveReadbackAdapter(MemoryArchiveAdapter):
    def __init__(self, hidden_projection_id):
        super().__init__()
        self.hidden_projection_id = str(hidden_projection_id)

    def readback(self, frozen):
        if frozen.projection_id == self.hidden_projection_id:
            return None
        return super().readback(frozen)


class ArchiveReplayAndEvidenceTests(F4TransactionTestCase):
    def _capture(self):
        _revision, intent, _observation, _result = self.delivered_claim()
        return capture_archive_projection(
            actor=self.alpha_user,
            organization_id=self.alpha.id,
            request_id=uuid.uuid4(),
            encounter_id=intent.claim_revision.encounter_id,
            expected_projection_id=None,
        )

    def test_batch_request_replay_order_conflict_and_later_batch_do_not_reset_budget(self):
        first = self._capture()
        second = self._capture()
        request_id = uuid.uuid4()
        ordered = [first.projection_id, second.projection_id]
        created = queue_archive_batch(
            actor=self.alpha_user,
            organization_id=self.alpha.id,
            request_id=request_id,
            projection_ids=ordered,
        )
        replayed = queue_archive_batch(
            actor=self.alpha_user,
            organization_id=self.alpha.id,
            request_id=request_id,
            projection_ids=ordered,
        )
        self.assertTrue(replayed.replayed)
        self.assertEqual(replayed.batch_id, created.batch_id)
        with self.assertRaisesMessage(
            CommandError, "request_reused_with_different_intent",
        ):
            queue_archive_batch(
                actor=self.alpha_user,
                organization_id=self.alpha.id,
                request_id=request_id,
                projection_ids=list(reversed(ordered)),
            )
        self.assertEqual(ArchiveBatch.objects.count(), 1)

        adapter = MemoryArchiveAdapter(readback=False)
        first_attempt = run_archive_worker_once(
            worker_id="budget-first", lease_seconds=2, adapter=adapter,
        )
        work = ArchiveWork.objects.get(projection_id=first.projection_id)
        initial_authorization = work.scheduled_authorization_id
        later = queue_archive_batch(
            actor=self.alpha_user,
            organization_id=self.alpha.id,
            request_id=uuid.uuid4(),
            projection_ids=[first.projection_id],
        )
        work.refresh_from_db()
        self.assertEqual(work.scheduled_authorization_id, initial_authorization)
        self.assertIsNotNone(later.batch_id)
        self.assertEqual(ArchiveAuthorization.objects.get(
            id=initial_authorization,
        ).allowed_attempts, 3)
        self.assertEqual(first_attempt.reason_code, "archive_retry_pending")

        # The second projection remains pending, so drive this exact work directly
        # by making it the oldest due row before consuming the final two attempts.
        ArchiveWork.objects.filter(projection_id=second.projection_id).update(
            due_at=work.due_at + timedelta(days=1),
        )
        results = [run_archive_worker_once(
            worker_id=f"budget-{index}", lease_seconds=2, adapter=adapter,
        ) for index in (2, 3)]
        self.assertEqual(
            [item.reason_code for item in results],
            ["archive_retry_pending", "archive_not_observed"],
        )
        self.assertEqual(ArchiveAttempt.objects.filter(
            authorization_id=initial_authorization,
            possible_write=True,
        ).count(), 3)

    def test_manual_retry_exact_replay_and_changed_or_stale_attempt_conflict(self):
        captured = self._capture()
        queue_archive_batch(
            actor=self.alpha_user,
            organization_id=self.alpha.id,
            request_id=uuid.uuid4(),
            projection_ids=[captured.projection_id],
        )
        adapter = MemoryArchiveAdapter(readback=False)
        attempts = [run_archive_worker_once(
            worker_id=f"manual-seed-{index}", lease_seconds=2, adapter=adapter,
        ) for index in range(3)]
        latest = attempts[-1].attempt_id
        request_id = uuid.uuid4()
        scheduled = retry_archive_item(
            actor=self.alpha_user,
            organization_id=self.alpha.id,
            request_id=request_id,
            projection_id=captured.projection_id,
            expected_attempt_id=latest,
        )
        replayed = retry_archive_item(
            actor=self.alpha_user,
            organization_id=self.alpha.id,
            request_id=request_id,
            projection_id=captured.projection_id,
            expected_attempt_id=latest,
        )
        self.assertEqual(scheduled.reason_code, "archive_retry_scheduled")
        self.assertTrue(replayed.replayed)
        self.assertEqual(replayed.authorization_id, scheduled.authorization_id)
        with self.assertRaisesMessage(
            CommandError, "request_reused_with_different_intent",
        ):
            retry_archive_item(
                actor=self.alpha_user,
                organization_id=self.alpha.id,
                request_id=request_id,
                projection_id=captured.projection_id,
                expected_attempt_id=attempts[0].attempt_id,
            )
        with self.assertRaisesMessage(CommandError, "archive_retry_attempt_stale"):
            retry_archive_item(
                actor=self.alpha_user,
                organization_id=self.alpha.id,
                request_id=uuid.uuid4(),
                projection_id=captured.projection_id,
                expected_attempt_id=attempts[0].attempt_id,
            )
        self.assertEqual(ArchiveAuthorization.objects.filter(
            projection_id=captured.projection_id,
            kind=ArchiveAuthorization.KIND_MANUAL,
        ).count(), 1)

    def test_partial_batch_and_each_wrong_identity_variant_remain_attributable(self):
        first = self._capture()
        second = self._capture()
        queued = queue_archive_batch(
            actor=self.alpha_user,
            organization_id=self.alpha.id,
            request_id=uuid.uuid4(),
            projection_ids=[first.projection_id, second.projection_id],
        )
        adapter = SelectiveReadbackAdapter(second.projection_id)
        run_archive_worker_once(worker_id="partial-first", lease_seconds=2, adapter=adapter)
        run_archive_worker_once(worker_id="partial-second", lease_seconds=2, adapter=adapter)
        states = [item.state for item in archive_batch_status(
            actor=self.alpha_user,
            organization_id=self.alpha.id,
            batch_id=queued.batch_id,
        )]
        self.assertEqual(states, ["historically_confirmed", "unknown_possible_write"])

        for variant in ("receiver", "version", "bytes"):
            with self.subTest(variant=variant):
                captured = self._capture()
                queue_archive_batch(
                    actor=self.alpha_user,
                    organization_id=self.alpha.id,
                    request_id=uuid.uuid4(),
                    projection_ids=[captured.projection_id],
                )
                result = run_archive_worker_once(
                    worker_id=f"variant-{variant}",
                    lease_seconds=2,
                    adapter=EvidenceVariantAdapter(variant),
                )
                self.assertEqual(result.reason_code, "archive_evidence_conflict")
                observation = ArchiveReadbackObservation.objects.get(
                    id=result.observation_id,
                )
                self.assertEqual(
                    observation.observed_state,
                    ArchiveReadbackObservation.STATE_CONFLICT,
                )
                self.assertFalse(ArchiveAttemptOutcome.objects.filter(
                    attempt__projection_id=captured.projection_id,
                    kind=ArchiveAttemptOutcome.TARGET_CONFIRMED,
                ).exists())


class ArchiveWorkerRaceTests(F4TransactionTestCase):
    def _queued(self):
        _revision, intent, _observation, _result = self.delivered_claim()
        captured = capture_archive_projection(
            actor=self.alpha_user,
            organization_id=self.alpha.id,
            request_id=uuid.uuid4(),
            encounter_id=intent.claim_revision.encounter_id,
            expected_projection_id=None,
        )
        queue_archive_batch(
            actor=self.alpha_user,
            organization_id=self.alpha.id,
            request_id=uuid.uuid4(),
            projection_ids=[captured.projection_id],
        )
        return captured

    def test_concurrent_workers_cannot_duplicate_grant_or_target_version(self):
        captured = self._queued()
        marked = threading.Event()
        release = threading.Event()
        adapter = MemoryArchiveAdapter()

        def first_worker():
            close_old_connections()
            try:
                return run_archive_worker_once(
                    worker_id="lease-winner",
                    lease_seconds=5,
                    adapter=adapter,
                    after_marker=lambda _frozen: (
                        marked.set(), self.assertTrue(release.wait(timeout=10))
                    ),
                )
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(first_worker)
            self.assertTrue(marked.wait(timeout=5))
            loser = run_archive_worker_once(
                worker_id="lease-loser", lease_seconds=5, adapter=adapter,
            )
            release.set()
            winner = future.result(timeout=10)

        self.assertEqual(loser.reason_code, "no_archive_work")
        self.assertEqual(winner.reason_code, "archive_item_confirmed")
        self.assertEqual(ArchiveAttempt.objects.filter(
            projection_id=captured.projection_id,
        ).count(), 1)
        self.assertEqual(len(adapter.rows), 1)

    def test_expired_possible_write_is_closed_and_delayed_older_worker_is_fenced(self):
        captured = self._queued()
        marked = threading.Event()
        release = threading.Event()
        old_adapter = MemoryArchiveAdapter(readback=False)

        def old_worker():
            close_old_connections()
            try:
                return run_archive_worker_once(
                    worker_id="expired-old",
                    lease_seconds=1,
                    adapter=old_adapter,
                    after_marker=lambda _frozen: (
                        marked.set(), self.assertTrue(release.wait(timeout=10))
                    ),
                )
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(old_worker)
            self.assertTrue(marked.wait(timeout=5))
            work = ArchiveWork.objects.get(projection_id=captured.projection_id)
            deadline = time.monotonic() + 2
            while work.lease_expires_at > timezone.now():
                if time.monotonic() >= deadline:
                    self.fail("archive possible-write lease did not expire")
                time.sleep(0.02)
                work.refresh_from_db()
            recovered = run_archive_worker_once(
                worker_id="expired-recovery",
                lease_seconds=2,
                adapter=MemoryArchiveAdapter(),
            )
            newer = run_archive_worker_once(
                worker_id="new-fence", lease_seconds=2, adapter=MemoryArchiveAdapter(),
            )
            release.set()
            delayed = future.result(timeout=10)

        self.assertEqual(recovered.reason_code, "archive_retry_pending")
        self.assertEqual(newer.reason_code, "archive_item_confirmed")
        self.assertEqual(delayed.reason_code, "archive_worker_fence_stale")
        work.refresh_from_db()
        self.assertEqual(work.fencing_generation, 2)
        self.assertEqual(work.state, ArchiveWork.STATE_FINISHED)
        outcomes = ArchiveAttemptOutcome.objects.filter(
            attempt__projection_id=captured.projection_id,
        ).order_by("attempt__fencing_generation")
        self.assertEqual(
            list(outcomes.values_list("kind", flat=True)),
            [ArchiveAttemptOutcome.UNKNOWN, ArchiveAttemptOutcome.TARGET_CONFIRMED],
        )
