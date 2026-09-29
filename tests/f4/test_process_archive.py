from __future__ import annotations

import base64
import hashlib
import os
import uuid
from decimal import Decimal
from unittest.mock import patch

import psycopg
from psycopg import sql

from medicafe_v1.archival.commands import capture_archive_projection, queue_archive_batch
from medicafe_v1.archival.models import ArchiveProjection, ArchiveReadbackObservation
from medicafe_v1.archival.queries import (
    archive_batch_status,
    archive_current_lag,
    archive_item_status,
)
from medicafe_v1.claims.commands import prepare_claim_revision
from medicafe_v1.claims.queries import claim_detail
from medicafe_v1.outcomes.commands import post_remittance
from medicafe_v1.outcomes.models import AcceptedEvent, PostingEntry
from medicafe_v1.records.commands import revise_service
from medicafe_v1.records.queries import current_services_for_encounter
from medicafe_v1.synthetic_archive import ArchiveLedger
from tests.helpers.workflow_boundary_contract import assert_archive_boundary

from .base import F4TransactionTestCase
from .process_helpers import ArchiveProcess, postgres_env, postgres_kwargs


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
        revision = intent.claim_revision

        unavailable = self.target.run_worker()

        self.assertEqual(unavailable.returncode, 0, unavailable.stderr)
        self.assertIn("archive_retry_pending", unavailable.stdout)
        service = revision.lines.select_related(
            "service__current_revision"
        ).first().service
        current = service.current_revision
        revised = revise_service(
            actor=self.alpha_user, organization_id=self.alpha.id,
            request_id=uuid.uuid4(), service_id=service.id,
            expected_revision_id=current.id,
            evidence_observation_id=current.evidence_observation_id,
            disposition="accepted", code=current.code, units=current.units,
            unit_amount=current.unit_amount + Decimal("1.00"),
            currency=current.currency, reason="Synthetic archive outage review",
            artifact_store=self.store,
        )
        prepared = prepare_claim_revision(
            actor=self.alpha_user, organization_id=self.alpha.id,
            request_id=uuid.uuid4(), encounter_id=revision.encounter_id,
            expected_claim_revision_id=revision.id,
            selected_service_revision_ids=[revised.revision_id],
            route_id=revision.route_id, route_version=revision.route_version,
            reason="Synthetic archive outage claim review",
        )
        reviewed_services = current_services_for_encounter(
            actor=self.alpha_user, organization_id=self.alpha.id,
            encounter_id=revision.encounter_id,
        )
        reviewed_claim = claim_detail(
            actor=self.alpha_user, organization_id=self.alpha.id,
            claim_id=revision.claim_id,
        )
        self.assertEqual(reviewed_services.get(id=service.id).current_revision_id,
                         revised.revision_id)
        self.assertEqual(reviewed_claim.current_revision_id, prepared.revision_id)
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
        self.assertEqual(archive_current_lag(
            actor=self.alpha_user, organization_id=self.alpha.id,
            encounter_id=revision.encounter_id,
        ).state, "projection_lag")

    def test_target_rejects_same_id_changed_bytes_and_delayed_older_head(self):
        with patch.dict(os.environ, postgres_env()):
            ledger = ArchiveLedger(self.target.schema)
        organization_id = str(uuid.uuid4())
        encounter_id = str(uuid.uuid4())
        older_id = str(uuid.uuid4())
        newer_id = str(uuid.uuid4())

        def value(projection_id, version, payload):
            return {
                "organization_id": organization_id,
                "encounter_id": encounter_id,
                "projection_id": projection_id,
                "projection_version": version,
                "attempt_id": str(uuid.uuid4()),
                "projection_digest": hashlib.sha256(payload).hexdigest(),
                "byte_length": len(payload),
                "payload_b64": base64.b64encode(payload).decode("ascii"),
            }

        newer = value(newer_id, 2, b'{"version":2}')
        older = value(older_id, 1, b'{"version":1}')
        self.assertEqual(ledger.store(newer), "stored")
        self.assertEqual(ledger.store(older), "stored")
        changed = value(newer_id, 2, b'{"version":2,"changed":true}')
        self.assertEqual(ledger.store(changed), "conflict")

        with psycopg.connect(**postgres_kwargs()) as conn, conn.cursor() as cursor:
            cursor.execute(sql.SQL("""
                SELECT projection_id,projection_version
                  FROM {}.archive_head
                 WHERE organization_id=%s AND encounter_id=%s
            """).format(sql.Identifier(self.target.schema)), [
                organization_id, encounter_id,
            ])
            head = cursor.fetchone()
        self.assertEqual(str(head[0]), newer_id)
        self.assertEqual(head[1], 2)

    def test_one_item_acknowledgment_never_completes_partial_batch(self):
        _first_intent, _first_observation, first = self._queued()
        _revision, second_intent, _observation, _result = self.delivered_claim()
        second = capture_archive_projection(
            actor=self.alpha_user,
            organization_id=self.alpha.id,
            request_id=uuid.uuid4(),
            encounter_id=second_intent.claim_revision.encounter_id,
            expected_projection_id=None,
        )
        queued = queue_archive_batch(
            actor=self.alpha_user,
            organization_id=self.alpha.id,
            request_id=uuid.uuid4(),
            projection_ids=[first.projection_id, second.projection_id],
        )
        self.target.start()

        first_worker = self.target.run_worker()

        self.assertEqual(first_worker.returncode, 0, first_worker.stderr)
        self.assertIn("archive_item_confirmed", first_worker.stdout)
        states = [item.state for item in archive_batch_status(
            actor=self.alpha_user,
            organization_id=self.alpha.id,
            batch_id=queued.batch_id,
        )]
        self.assertEqual(states.count("historically_confirmed"), 1)
        self.assertEqual(states.count("pending_execution"), 1)

        second_worker = self.target.run_worker()

        self.assertEqual(second_worker.returncode, 0, second_worker.stderr)
        self.assertEqual(
            [item.state for item in archive_batch_status(
                actor=self.alpha_user,
                organization_id=self.alpha.id,
                batch_id=queued.batch_id,
            )],
            ["historically_confirmed", "historically_confirmed"],
        )


class OutcomeProcessDurabilityTests(F4TransactionTestCase):
    def test_fresh_process_reads_accepted_ledger_and_never_logs_sentinel(self):
        sentinel = f"SYNTHETIC_PRIVATE_SENTINEL_{uuid.uuid4().hex}"
        revision, intent, observation, _result = self.delivered_claim(note=sentinel)
        event_id = uuid.uuid4()
        _delivery, candidate = self.admit_inbound(
            kind="remittance", intent=intent, observation=observation,
            event_id=event_id,
        )
        posted = post_remittance(
            actor=self.alpha_user, organization_id=self.alpha.id,
            request_id=uuid.uuid4(), candidate_id=candidate.candidate_id,
            artifact_store=self.store,
        )
        self.assertEqual(posted.reason_code, "remittance_posted")
        helper = ArchiveProcess()

        before, process = helper.query_outcome_state(
            organization_id=self.alpha.id, user_id=self.alpha_user.id,
            claim_revision_id=revision.id,
        )

        self.assertNotIn(sentinel, process.stdout)
        self.assertNotIn(sentinel, process.stderr)
        self.assertEqual(before, {
            "events": 1, "entries": 2, "original_charge": "10.00",
            "payer_reported_credits": "4.00",
            "contractual_adjustments": "1.00", "residual": "5.00",
        })
        equivalent = self.inbound_document(
            kind="remittance", intent=intent, observation=observation,
            event_id=event_id, lines=[{
                "line_ordinal": 1, "paid_amount": "4",
                "contractual_adjustment": "1.0",
            }],
        )
        self.admit_inbound(
            kind="remittance", intent=intent, observation=observation,
            content=equivalent,
        )
        after, _process = helper.query_outcome_state(
            organization_id=self.alpha.id, user_id=self.alpha_user.id,
            claim_revision_id=revision.id,
        )
        self.assertEqual(after, before)
        self.assertEqual(AcceptedEvent.objects.count(), 1)
        self.assertEqual(PostingEntry.objects.count(), 2)
