from __future__ import annotations

import uuid

from medicafe_v1.access.models import Membership
from medicafe_v1.access.services import AuthorizationError
from medicafe_v1.archival.commands import (
    capture_archive_projection, queue_archive_batch, retry_archive_item,
)
from medicafe_v1.archival.models import (
    ArchiveAttempt, ArchiveBatch, ArchiveCommandReceipt, ArchiveProjection,
)
from medicafe_v1.archival.queries import (
    archive_batch_detail, archive_batch_status, archive_current_lag,
    archive_heads, archive_item_status, archive_projection_detail,
)
from medicafe_v1.archival.worker import reconcile_archive_item, run_archive_worker_once
from medicafe_v1.claims.queries import (
    archive_claim_snapshot, historical_delivery_attribution,
)
from medicafe_v1.outcomes.commands import (
    accept_lifecycle, interpret_inbound, post_remittance, reevaluate_candidate,
)
from medicafe_v1.outcomes.models import AcceptedEvent, OutcomesCommandReceipt, PostingEntry
from medicafe_v1.outcomes.queries import (
    archive_outcome_snapshot, candidate_detail, current_lifecycle,
    inbound_candidates, ledger_detail,
)
from medicafe_v1.records.queries import archive_encounter_snapshot
from medicafe_v1.sources.queries import outcome_deliveries, verified_delivery_bytes

from .base import F4TransactionTestCase
from .test_archive import MemoryArchiveAdapter


class F4AuthorizationTests(F4TransactionTestCase):
    def setUp(self):
        super().setUp()
        revision, intent, observation, _result = self.delivered_claim()
        lifecycle_delivery, lifecycle = self.admit_inbound(
            kind="lifecycle", intent=intent, observation=observation,
        )
        _remittance_delivery, remittance = self.admit_inbound(
            kind="remittance", intent=intent, observation=observation,
        )
        self.lifecycle_request_id = uuid.uuid4()
        accepted = accept_lifecycle(
            actor=self.alpha_user, organization_id=self.alpha.id,
            request_id=self.lifecycle_request_id,
            candidate_id=lifecycle.candidate_id,
            artifact_store=self.store,
        )
        self.remittance_request_id = uuid.uuid4()
        posted = post_remittance(
            actor=self.alpha_user, organization_id=self.alpha.id,
            request_id=self.remittance_request_id,
            candidate_id=remittance.candidate_id,
            artifact_store=self.store,
        )
        self.capture_request_id = uuid.uuid4()
        captured = capture_archive_projection(
            actor=self.alpha_user, organization_id=self.alpha.id,
            request_id=self.capture_request_id, encounter_id=revision.encounter_id,
            expected_projection_id=None,
        )
        self.queue_request_id = uuid.uuid4()
        queued = queue_archive_batch(
            actor=self.alpha_user, organization_id=self.alpha.id,
            request_id=self.queue_request_id,
            projection_ids=[captured.projection_id],
        )
        unknown = run_archive_worker_once(
            worker_id="authorization-unknown", lease_seconds=2,
            adapter=MemoryArchiveAdapter(readback=False),
        )
        self.revision = revision
        self.intent = intent
        self.lifecycle_delivery_id = lifecycle_delivery.delivery_id
        self.lifecycle_candidate_id = lifecycle.candidate_id
        self.remittance_candidate_id = remittance.candidate_id
        self.event_id = accepted.event_id
        self.batch_id = posted.batch_id
        self.projection_id = captured.projection_id
        self.archive_batch_id = queued.batch_id
        self.archive_attempt_id = unknown.attempt_id
        self.retry_request_id = uuid.uuid4()
        retry_archive_item(
            actor=self.alpha_user, organization_id=self.alpha.id,
            request_id=self.retry_request_id, projection_id=captured.projection_id,
            expected_attempt_id=unknown.attempt_id,
        )
        self.observation = observation

    def _operations(self, actor):
        organization_id = self.alpha.id
        return (
            ("interpret_inbound", lambda: interpret_inbound(
                actor=actor, organization_id=organization_id,
                delivery_id=self.lifecycle_delivery_id, artifact_store=self.store,
            )),
            ("accept_lifecycle", lambda: accept_lifecycle(
                actor=actor, organization_id=organization_id,
                request_id=self.lifecycle_request_id,
                candidate_id=self.lifecycle_candidate_id,
                artifact_store=self.store,
            )),
            ("post_remittance", lambda: post_remittance(
                actor=actor, organization_id=organization_id,
                request_id=self.remittance_request_id,
                candidate_id=self.remittance_candidate_id,
                artifact_store=self.store,
            )),
            ("reevaluate_candidate", lambda: reevaluate_candidate(
                actor=actor, organization_id=organization_id,
                candidate_id=self.lifecycle_candidate_id, artifact_store=self.store,
            )),
            ("inbound_candidates", lambda: tuple(inbound_candidates(
                actor=actor, organization_id=organization_id,
            ))),
            ("candidate_detail", lambda: candidate_detail(
                actor=actor, organization_id=organization_id,
                candidate_id=self.lifecycle_candidate_id,
            )),
            ("current_lifecycle", lambda: current_lifecycle(
                actor=actor, organization_id=organization_id,
                intent_id=self.intent.id,
            )),
            ("ledger_detail", lambda: ledger_detail(
                actor=actor, organization_id=organization_id,
                claim_revision_id=self.revision.id,
            )),
            ("archive_outcome_snapshot", lambda: archive_outcome_snapshot(
                actor=actor, organization_id=organization_id,
                encounter_id=self.revision.encounter_id,
            )),
            ("verified_delivery_bytes", lambda: verified_delivery_bytes(
                actor=actor, organization_id=organization_id,
                delivery_id=self.lifecycle_delivery_id, artifact_store=self.store,
            )),
            ("outcome_deliveries", lambda: outcome_deliveries(
                actor=actor, organization_id=organization_id,
            )),
            ("historical_delivery_attribution", lambda: historical_delivery_attribution(
                actor=actor, organization_id=organization_id,
                intent_id=self.intent.id, delivery_key=self.intent.delivery_key,
                claim_revision_id=self.revision.id,
                expected_receiver_id="synthetic-receiver",
                expected_receiver_version=self.intent.receiver_version,
                receiver_receipt_id=self.observation.receipt_id,
                line_ordinals=(), for_acceptance=False,
            )),
            ("archive_claim_snapshot", lambda: archive_claim_snapshot(
                actor=actor, organization_id=organization_id,
                encounter_id=self.revision.encounter_id,
            )),
            ("archive_encounter_snapshot", lambda: archive_encounter_snapshot(
                actor=actor, organization_id=organization_id,
                encounter_id=self.revision.encounter_id,
            )),
            ("capture_archive_projection", lambda: capture_archive_projection(
                actor=actor, organization_id=organization_id,
                request_id=self.capture_request_id,
                encounter_id=self.revision.encounter_id,
                expected_projection_id=None,
            )),
            ("queue_archive_batch", lambda: queue_archive_batch(
                actor=actor, organization_id=organization_id,
                request_id=self.queue_request_id,
                projection_ids=[self.projection_id],
            )),
            ("retry_archive_item", lambda: retry_archive_item(
                actor=actor, organization_id=organization_id,
                request_id=self.retry_request_id,
                projection_id=self.projection_id,
                expected_attempt_id=self.archive_attempt_id,
            )),
            ("reconcile_archive_item", lambda: reconcile_archive_item(
                actor=actor, organization_id=organization_id,
                projection_id=self.projection_id,
                adapter=MemoryArchiveAdapter(readback=False),
            )),
            ("archive_current_lag", lambda: archive_current_lag(
                actor=actor, organization_id=organization_id,
                encounter_id=self.revision.encounter_id,
            )),
            ("archive_item_status", lambda: archive_item_status(
                actor=actor, organization_id=organization_id,
                projection_id=self.projection_id,
            )),
            ("archive_batch_status", lambda: archive_batch_status(
                actor=actor, organization_id=organization_id,
                batch_id=self.archive_batch_id,
            )),
            ("archive_heads", lambda: tuple(archive_heads(
                actor=actor, organization_id=organization_id,
            ))),
            ("archive_projection_detail", lambda: archive_projection_detail(
                actor=actor, organization_id=organization_id,
                projection_id=self.projection_id,
            )),
            ("archive_batch_detail", lambda: archive_batch_detail(
                actor=actor, organization_id=organization_id,
                batch_id=self.archive_batch_id,
            )),
        )

    def _assert_all_denied(self, actor):
        before = (
            AcceptedEvent.objects.count(), PostingEntry.objects.count(),
            OutcomesCommandReceipt.objects.count(), ArchiveProjection.objects.count(),
            ArchiveBatch.objects.count(), ArchiveCommandReceipt.objects.count(),
            ArchiveAttempt.objects.count(),
        )
        for name, operation in self._operations(actor):
            with self.subTest(operation=name):
                with self.assertRaisesMessage(
                    AuthorizationError, "active_membership_required",
                ):
                    operation()
        after = (
            AcceptedEvent.objects.count(), PostingEntry.objects.count(),
            OutcomesCommandReceipt.objects.count(), ArchiveProjection.objects.count(),
            ArchiveBatch.objects.count(), ArchiveCommandReceipt.objects.count(),
            ArchiveAttempt.objects.count(),
        )
        self.assertEqual(after, before)

    def test_wrong_organization_member_is_denied_every_f4_command_and_query(self):
        self._assert_all_denied(self.beta_user)

    def test_inactive_member_is_denied_every_f4_command_and_query(self):
        Membership.objects.filter(
            organization=self.alpha, user=self.alpha_user,
        ).update(is_active=False)
        self._assert_all_denied(self.alpha_user)
