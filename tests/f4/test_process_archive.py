from __future__ import annotations

import uuid

import psycopg
from psycopg import sql

from medicafe_v1.archival.commands import capture_archive_projection, queue_archive_batch
from medicafe_v1.archival.models import ArchiveProjection, ArchiveReadbackObservation
from medicafe_v1.archival.queries import archive_item_status
from medicafe_v1.outcomes.commands import post_remittance
from tests.helpers.workflow_boundary_contract import assert_archive_boundary

from .base import F4TransactionTestCase
from .process_helpers import ArchiveProcess, postgres_kwargs


class ArchiveProcessTests(F4TransactionTestCase):
    def setUp(self):
        super().setUp()
        self.target = ArchiveProcess()

    def tearDown(self):
        self.target.stop()
        self.target.drop_schema()
        super().tearDown()

    def _queued(self):
        _revision, intent, observation, _result = self.delivered_claim()
        captured = capture_archive_projection(
            actor=self.alpha_user, organization_id=self.alpha.id,
            request_id=uuid.uuid4(), encounter_id=intent.claim_revision.encounter_id,
            expected_projection_id=None,
        )
        queue_archive_batch(
            actor=self.alpha_user, organization_id=self.alpha.id,
            request_id=uuid.uuid4(), projection_ids=[captured.projection_id],
        )
        return intent, observation, captured

    def test_exact_projection_survives_target_and_worker_restart(self):
        _intent, _observation, captured = self._queued()
        projection = ArchiveProjection.objects.get(id=captured.projection_id)
        self.target.start()

        worker = self.target.run_worker()

        self.assertEqual(worker.returncode, 0, worker.stderr)
        self.assertIn("archive_item_confirmed", worker.stdout)
        projection.refresh_from_db()
        assert_archive_boundary(
            self, projection=projection, expected_attempts=1,
            expected_confirmed=True,
        )
        with psycopg.connect(**postgres_kwargs()) as conn, conn.cursor() as cursor:
            cursor.execute(sql.SQL("""
                SELECT projection_digest,byte_length,received_bytes
                  FROM {}.archive_projection WHERE projection_id=%s
            """).format(sql.Identifier(self.target.schema)), [projection.id])
            stored = cursor.fetchone()
        self.assertEqual(stored[0], projection.projection_digest)
        self.assertEqual(stored[1], projection.byte_length)
        self.assertEqual(bytes(stored[2]), bytes(projection.projection_bytes))

        self.target.stop()
        self.target.start()
        no_work = self.target.run_worker()
        self.assertEqual(no_work.returncode, 0, no_work.stderr)
        self.assertIn("no_archive_work", no_work.stdout)
        self.assertEqual(ArchiveReadbackObservation.objects.filter(
            lookup_projection=projection,
            observed_state=ArchiveReadbackObservation.STATE_VERIFIED,
        ).count(), 1)

    def test_archive_outage_does_not_block_canonical_remittance_and_later_recovers(self):
        intent, observation, captured = self._queued()

        unavailable = self.target.run_worker()

        self.assertEqual(unavailable.returncode, 0, unavailable.stderr)
        self.assertIn("archive_retry_pending", unavailable.stdout)
        _delivery, candidate = self.admit_inbound(
            kind="remittance", intent=intent, observation=observation,
        )
        posted = post_remittance(
            actor=self.alpha_user, organization_id=self.alpha.id,
            request_id=uuid.uuid4(), candidate_id=candidate.candidate_id,
            artifact_store=self.store,
        )
        self.assertEqual(posted.reason_code, "remittance_posted")
        self.target.start()
        recovered = self.target.run_worker()
        self.assertIn("archive_item_confirmed", recovered.stdout)
        self.assertEqual(archive_item_status(
            actor=self.alpha_user, organization_id=self.alpha.id,
            projection_id=captured.projection_id,
        ).state, "historically_confirmed")
