from __future__ import annotations

import json
import queue
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from unittest.mock import patch

from django.db import DatabaseError, close_old_connections, connection, transaction
from django.utils import timezone

from medicafe_v1.archival.commands import capture_archive_projection
from medicafe_v1.archival.models import ArchiveCommandReceipt, ArchiveProjection
from medicafe_v1.archival.queries import archive_current_lag
from medicafe_v1.claims.models import ReceiverObservation
from medicafe_v1.outcomes.commands import accept_lifecycle, post_remittance
from medicafe_v1.outcomes.models import (
    AcceptedEvent, AcceptedEventEvidence, ChargeBasis, FinancialAccount,
    InboundCandidate, OutcomesCommandReceipt, PostingBatch, PostingEntry,
)
from medicafe_v1.sources.domain import CommandError

from .base import F4TransactionTestCase


class ReceiptAnchorConcurrencyTests(F4TransactionTestCase):
    def setUp(self):
        super().setUp()
        _revision, self.intent, self.observation, _result = self.delivered_claim()
        _delivery, candidate = self.admit_inbound(
            kind="lifecycle", intent=self.intent, observation=self.observation,
        )
        self.candidate_id = candidate.candidate_id

    def _insert_conflict(self, *, inserted=None, release=None, backend_pids=None):
        close_old_connections()
        try:
            connection.ensure_connection()
            if backend_pids is not None:
                backend_pids.put(connection.connection.info.backend_pid)
            with transaction.atomic():
                accepted = ReceiverObservation.objects.get(id=self.observation.id)
                conflict = ReceiverObservation.objects.create(
                    organization_id=accepted.organization_id,
                    intent_id=accepted.intent_id,
                    claim_revision_id=accepted.claim_revision_id,
                    origin=ReceiverObservation.ORIGIN_RECONCILIATION,
                    receiver_id=accepted.receiver_id,
                    receiver_version=accepted.receiver_version,
                    lookup_key=accepted.lookup_key,
                    receipt_id=accepted.receipt_id,
                    reported_attempt_id=accepted.reported_attempt_id,
                    envelope_digest=accepted.envelope_digest,
                    byte_length=accepted.byte_length,
                    received_bytes=bytes(accepted.received_bytes),
                    observed_state=ReceiverObservation.STATE_ACCEPTED,
                    no_acceptance_guaranteed=False, binding_valid=True,
                    conflict_reason="", observed_at=timezone.now(),
                    evidence_fingerprint=uuid.uuid4().hex * 2,
                    reported_organization_id=accepted.organization_id,
                    reported_intent_id=accepted.intent_id,
                    reported_claim_revision_id=accepted.claim_revision_id,
                    reported_delivery_key=uuid.uuid4(),
                    reported_receiver_id=accepted.receiver_id,
                    reported_receiver_version=accepted.receiver_version,
                    reported_envelope_digest=accepted.envelope_digest,
                    reported_byte_length=accepted.byte_length,
                )
                conflict.refresh_from_db()
                if inserted:
                    inserted.set()
                if release:
                    self.assertTrue(release.wait(timeout=10))
            return conflict.id
        finally:
            close_old_connections()

    def _accept_in_thread(self, started=None, backend_pids=None):
        close_old_connections()
        try:
            connection.ensure_connection()
            if backend_pids is not None:
                backend_pids.put(connection.connection.info.backend_pid)
            if started:
                started.set()
            try:
                result = accept_lifecycle(
                    actor=self.alpha_user, organization_id=self.alpha.id,
                    request_id=uuid.uuid4(), candidate_id=self.candidate_id,
                    artifact_store=self.store,
                )
                return result.reason_code
            except CommandError as exc:
                return exc.reason_code
        finally:
            close_old_connections()

    def _wait_for_lock_wait(self, backend_pid):
        deadline = time.monotonic() + 5
        while True:
            with connection.cursor() as cursor:
                cursor.execute("""
                    SELECT wait_event_type FROM pg_stat_activity WHERE pid=%s
                """, [backend_pid])
                row = cursor.fetchone()
            if row and row[0] == "Lock":
                return
            if time.monotonic() >= deadline:
                self.fail(f"backend {backend_pid} did not reach lock wait")
            time.sleep(0.01)

    def test_acceptance_first_commits_fact_then_later_conflict_remains_alert(self):
        conflict_started = threading.Event()
        backend_pids = queue.Queue()

        def conflict_writer():
            conflict_started.set()
            return self._insert_conflict(backend_pids=backend_pids)

        with ThreadPoolExecutor(max_workers=1) as pool:
            with transaction.atomic():
                with connection.cursor() as cursor:
                    cursor.execute("""
                        SELECT evidence_fingerprint
                          FROM claims_receiverreceiptidentity
                         WHERE receiver_id=%s AND receiver_version=%s AND receipt_id=%s
                         FOR UPDATE
                    """, [
                        self.observation.receiver_id,
                        self.observation.receiver_version,
                        self.observation.receipt_id,
                    ])
                    self.assertIsNotNone(cursor.fetchone())
                future = pool.submit(conflict_writer)
                self.assertTrue(conflict_started.wait(timeout=5))
                self._wait_for_lock_wait(backend_pids.get(timeout=5))
                accepted = accept_lifecycle(
                    actor=self.alpha_user, organization_id=self.alpha.id,
                    request_id=uuid.uuid4(), candidate_id=self.candidate_id,
                    artifact_store=self.store,
                )
                self.assertEqual(accepted.reason_code, "lifecycle_accepted")
            conflict_id = future.result(timeout=10)

        conflict = ReceiverObservation.objects.get(id=conflict_id)
        self.assertEqual(conflict.observed_state, ReceiverObservation.STATE_CONFLICT)
        self.assertTrue(AcceptedEvent.objects.filter(id=accepted.event_id).exists())

    def test_conflict_first_forces_waiting_acceptance_to_fail_closed(self):
        inserted = threading.Event()
        release = threading.Event()
        acceptance_started = threading.Event()
        backend_pids = queue.Queue()
        with ThreadPoolExecutor(max_workers=2) as pool:
            conflict_future = pool.submit(
                self._insert_conflict, inserted=inserted, release=release,
            )
            self.assertTrue(inserted.wait(timeout=5))
            acceptance_future = pool.submit(
                self._accept_in_thread, acceptance_started, backend_pids,
            )
            self.assertTrue(acceptance_started.wait(timeout=5))
            self._wait_for_lock_wait(backend_pids.get(timeout=5))
            release.set()
            conflict_future.result(timeout=10)
            reason = acceptance_future.result(timeout=10)

        self.assertEqual(reason, "conflicting_identity_or_content")
        self.assertFalse(AcceptedEvent.objects.exists())

    def test_acceptance_rejects_repeatable_read_transaction(self):
        with transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
            with self.assertRaisesMessage(
                CommandError, "acceptance_isolation_incompatible",
            ):
                accept_lifecycle(
                    actor=self.alpha_user, organization_id=self.alpha.id,
                    request_id=uuid.uuid4(), candidate_id=self.candidate_id,
                    artifact_store=self.store,
                )
        self.assertFalse(AcceptedEvent.objects.exists())

    def _race_acceptance_requests(self, request_ids):
        barrier = threading.Barrier(2)

        def accept(request_id):
            close_old_connections()
            try:
                barrier.wait(timeout=10)
                return accept_lifecycle(
                    actor=self.alpha_user,
                    organization_id=self.alpha.id,
                    request_id=request_id,
                    candidate_id=self.candidate_id,
                    artifact_store=self.store,
                ).reason_code
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=2) as pool:
            return [future.result(timeout=15) for future in (
                pool.submit(accept, request_ids[0]),
                pool.submit(accept, request_ids[1]),
            )]

    def test_identical_concurrent_request_replays_one_receipt(self):
        request_id = uuid.uuid4()
        results = self._race_acceptance_requests((request_id, request_id))
        self.assertCountEqual(results, (
            "lifecycle_accepted", "lifecycle_acceptance_replayed",
        ))
        self.assertEqual(AcceptedEvent.objects.count(), 1)
        self.assertEqual(OutcomesCommandReceipt.objects.count(), 1)

    def test_distinct_concurrent_requests_share_fact_but_retain_each_receipt(self):
        results = self._race_acceptance_requests((uuid.uuid4(), uuid.uuid4()))
        self.assertEqual(results.count("lifecycle_accepted"), 2)
        self.assertEqual(AcceptedEvent.objects.count(), 1)
        self.assertEqual(OutcomesCommandReceipt.objects.count(), 2)


class DirectPostingConcurrencyTests(F4TransactionTestCase):
    def _candidate_pair(self):
        revision, intent, observation, _result = self.delivered_claim()
        candidates = []
        for _index in range(2):
            _delivery, interpreted = self.admit_inbound(
                kind="remittance", intent=intent, observation=observation,
                lines=[{
                    "line_ordinal": 1, "paid_amount": "6.00",
                    "contractual_adjustment": "0.00",
                }],
            )
            candidates.append(InboundCandidate.objects.get(id=interpreted.candidate_id))
        account = FinancialAccount.objects.create(
            organization=self.alpha, claim_revision=revision,
            currency=revision.currency, original_charge=revision.total_amount,
        )
        line = revision.lines.get(ordinal=1)
        basis = ChargeBasis.objects.create(
            organization=self.alpha, account=account, claim_line=line,
            line_ordinal=line.ordinal, original_charge=line.line_amount,
            currency=line.currency,
        )
        return revision, candidates, account, basis, observation

    def _post_owner_command(self, *, candidate_id, barrier):
        close_old_connections()
        try:
            barrier.wait(timeout=10)
            try:
                result = post_remittance(
                    actor=self.alpha_user,
                    organization_id=self.alpha.id,
                    request_id=uuid.uuid4(),
                    candidate_id=candidate_id,
                    artifact_store=self.store,
                )
                return result.reason_code
            except CommandError as exc:
                return exc.reason_code
        finally:
            close_old_connections()

    def test_distinct_owner_commands_compete_for_one_residual_balance(self):
        revision, candidates, account, _basis, _observation = self._candidate_pair()
        barrier = threading.Barrier(2)

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = [future.result(timeout=15) for future in (
                pool.submit(
                    self._post_owner_command,
                    candidate_id=candidates[0].id,
                    barrier=barrier,
                ),
                pool.submit(
                    self._post_owner_command,
                    candidate_id=candidates[1].id,
                    barrier=barrier,
                ),
            )]

        self.assertEqual(results.count("remittance_posted"), 1, results)
        self.assertEqual(results.count("overallocated_line"), 1, results)
        self.assertEqual(PostingEntry.objects.filter(account=account).count(), 1)
        self.assertEqual(
            sum(PostingEntry.objects.filter(account=account).values_list(
                "amount", flat=True,
            )),
            Decimal("6.00"),
        )
        self.assertEqual(AcceptedEvent.objects.filter(
            claim_revision=revision,
        ).count(), 1)
        self.assertEqual(OutcomesCommandReceipt.objects.filter(
            target_candidate_id__in=[candidate.id for candidate in candidates],
        ).count(), 1)

    def _insert_direct_posting(self, *, isolation, candidate_id, account_id,
                               basis_id, observation_id, barrier):
        close_old_connections()
        try:
            try:
                with transaction.atomic():
                    if isolation == "repeatable_read":
                        with connection.cursor() as cursor:
                            cursor.execute(
                                "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ"
                            )
                    candidate = InboundCandidate.objects.get(id=candidate_id)
                    account = FinancialAccount.objects.get(id=account_id)
                    basis = ChargeBasis.objects.get(id=basis_id)
                    observation = ReceiverObservation.objects.get(id=observation_id)
                    # Establish the transaction snapshot before either credit INSERT.
                    FinancialAccount.objects.filter(id=account.id).values_list(
                        "posting_generation", flat=True,
                    ).get()
                    event = AcceptedEvent.objects.create(
                        organization_id=candidate.organization_id,
                        primary_candidate=candidate, kind=candidate.kind,
                        sender_id=candidate.sender_id, event_id=candidate.event_id,
                        semantic_digest=candidate.semantic_digest,
                        intent_id=candidate.intent_id,
                        claim_revision_id=candidate.claim_revision_id,
                        receiver_observation=observation,
                        receiver_evidence_fingerprint=observation.evidence_fingerprint,
                        receiver_receipt_id=observation.receipt_id,
                        lifecycle_sequence=None, predecessor_event_id=None,
                        lifecycle_status="", accepted_by=self.alpha_user,
                    )
                    AcceptedEventEvidence.objects.create(
                        organization_id=candidate.organization_id,
                        event=event, candidate=candidate,
                    )
                    batch = PostingBatch.objects.create(
                        organization_id=candidate.organization_id,
                        event=event, account=account,
                    )
                    barrier.wait(timeout=10)
                    PostingEntry.objects.create(
                        organization_id=candidate.organization_id,
                        batch=batch, event=event, account=account,
                        charge_basis=basis, claim_line=basis.claim_line,
                        kind=PostingEntry.KIND_PAYMENT,
                        amount=Decimal("6.00"), currency=account.currency,
                    )
                return "committed"
            except DatabaseError as exc:
                cause = exc.__cause__
                return (
                    "database_error",
                    getattr(cause, "sqlstate", None),
                    str(cause or exc),
                )
        finally:
            close_old_connections()

    def test_direct_sql_conservation_serializes_rc_and_rejects_stale_rr(self):
        for isolation in ("read_committed", "repeatable_read"):
            with self.subTest(isolation=isolation):
                revision, candidates, account, basis, observation = self._candidate_pair()
                barrier = threading.Barrier(2)
                with ThreadPoolExecutor(max_workers=2) as pool:
                    futures = [pool.submit(
                        self._insert_direct_posting,
                        isolation=isolation, candidate_id=candidate.id,
                        account_id=account.id, basis_id=basis.id,
                        observation_id=observation.id, barrier=barrier,
                    ) for candidate in candidates]
                    results = [future.result(timeout=15) for future in futures]

                self.assertEqual(results.count("committed"), 1, results)
                loser = next(result for result in results if result != "committed")
                self.assertEqual(loser[0], "database_error", results)
                if isolation == "read_committed":
                    self.assertEqual(loser[1], "23514", results)
                    self.assertIn("overallocated_line", loser[2])
                else:
                    self.assertEqual(loser[1], "40001", results)
                self.assertEqual(PostingEntry.objects.filter(account=account).count(), 1)
                self.assertEqual(sum(
                    PostingEntry.objects.filter(account=account).values_list(
                        "amount", flat=True,
                    )
                ), Decimal("6.00"))
                self.assertEqual(AcceptedEvent.objects.filter(
                    claim_revision=revision,
                ).count(), 1)
                self.assertEqual(PostingBatch.objects.filter(
                    account=account,
                ).count(), 1)
                self.assertEqual(AcceptedEventEvidence.objects.filter(
                    event__claim_revision=revision,
                ).count(), 1)


class CapturePostingConcurrencyTests(F4TransactionTestCase):
    def _wait_for_lock_wait(self, backend_pid):
        deadline = time.monotonic() + 5
        while True:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT wait_event_type FROM pg_stat_activity WHERE pid=%s",
                    [backend_pid],
                )
                row = cursor.fetchone()
            if row and row[0] == "Lock":
                return
            if time.monotonic() >= deadline:
                self.fail(f"backend {backend_pid} did not reach lock wait")
            time.sleep(0.01)

    def test_capture_is_one_before_snapshot_and_posting_waits_then_creates_lag(self):
        revision, intent, observation, _result = self.delivered_claim()
        _delivery, candidate = self.admit_inbound(
            kind="remittance", intent=intent, observation=observation,
        )
        snapshot_ready = threading.Event()
        release_capture = threading.Event()
        capture_backend_pids = queue.Queue()
        posting_backend_pids = queue.Queue()

        from medicafe_v1.archival import commands as archive_commands

        real_snapshot = archive_commands.archive_outcome_snapshot

        def paused_snapshot(*args, **kwargs):
            result = real_snapshot(*args, **kwargs)
            snapshot_ready.set()
            self.assertTrue(release_capture.wait(timeout=10))
            return result

        def capture():
            close_old_connections()
            try:
                connection.ensure_connection()
                capture_backend_pids.put(connection.connection.info.backend_pid)
                with patch.object(
                    archive_commands, "archive_outcome_snapshot", paused_snapshot,
                ):
                    return capture_archive_projection(
                        actor=self.alpha_user, organization_id=self.alpha.id,
                        request_id=uuid.uuid4(), encounter_id=revision.encounter_id,
                        expected_projection_id=None,
                    )
            finally:
                close_old_connections()

        def post():
            close_old_connections()
            try:
                connection.ensure_connection()
                posting_backend_pids.put(connection.connection.info.backend_pid)
                return post_remittance(
                    actor=self.alpha_user, organization_id=self.alpha.id,
                    request_id=uuid.uuid4(), candidate_id=candidate.candidate_id,
                    artifact_store=self.store,
                )
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=2) as pool:
            capture_future = pool.submit(capture)
            self.assertTrue(snapshot_ready.wait(timeout=5))
            self.assertIsInstance(capture_backend_pids.get(timeout=5), int)
            posting_future = pool.submit(post)
            posting_pid = posting_backend_pids.get(timeout=5)
            self._wait_for_lock_wait(posting_pid)
            release_capture.set()
            captured = capture_future.result(timeout=10)
            posted = posting_future.result(timeout=10)

        projection = ArchiveProjection.objects.get(id=captured.projection_id)
        payload = json.loads(bytes(projection.projection_bytes))
        self.assertEqual(payload["outcomes"]["events"], [])
        self.assertEqual(payload["outcomes"]["entries"], [])
        self.assertEqual(payload["outcomes"]["accounts"], [])
        self.assertEqual(payload["outcomes"]["conflict_ids"], [])
        self.assertEqual(posted.reason_code, "remittance_posted")
        self.assertEqual(archive_current_lag(
            actor=self.alpha_user, organization_id=self.alpha.id,
            encounter_id=revision.encounter_id,
        ).state, "projection_lag")

        successor = capture_archive_projection(
            actor=self.alpha_user,
            organization_id=self.alpha.id,
            request_id=uuid.uuid4(),
            encounter_id=revision.encounter_id,
            expected_projection_id=projection.id,
        )
        successor_projection = ArchiveProjection.objects.get(id=successor.projection_id)
        successor_payload = json.loads(bytes(successor_projection.projection_bytes))
        outcomes = successor_payload["outcomes"]
        self.assertEqual(len(outcomes["events"]), 1)
        self.assertEqual(len(outcomes["entries"]), 2)
        self.assertEqual(len(outcomes["accounts"]), 1)
        self.assertEqual(outcomes["accounts"][0]["original_charge"], "10.00")
        self.assertEqual(outcomes["accounts"][0]["payer_reported_credits"], "4.00")
        self.assertEqual(outcomes["accounts"][0]["contractual_adjustments"], "1.00")
        self.assertEqual(outcomes["accounts"][0]["residual"], "5.00")
        self.assertEqual(archive_current_lag(
            actor=self.alpha_user,
            organization_id=self.alpha.id,
            encounter_id=revision.encounter_id,
        ).state, "current")

    def test_concurrent_initial_capture_has_one_projection_and_no_partial_receipt(self):
        revision, _intent, _observation, _result = self.delivered_claim()
        barrier = threading.Barrier(2)

        def capture_once():
            close_old_connections()
            try:
                barrier.wait(timeout=10)
                try:
                    result = capture_archive_projection(
                        actor=self.alpha_user, organization_id=self.alpha.id,
                        request_id=uuid.uuid4(), encounter_id=revision.encounter_id,
                        expected_projection_id=None,
                    )
                    return result.reason_code
                except CommandError as exc:
                    return exc.reason_code
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = [future.result(timeout=15) for future in (
                pool.submit(capture_once), pool.submit(capture_once),
            )]

        self.assertEqual(results.count("archive_projection_captured"), 1)
        self.assertEqual(results.count("archive_projection_head_conflict"), 1)
        self.assertEqual(ArchiveProjection.objects.filter(
            encounter_id=revision.encounter_id,
        ).count(), 1)
        self.assertEqual(ArchiveCommandReceipt.objects.filter(
            command_kind="capture_archive_projection",
        ).count(), 1)

    def test_concurrent_successor_capture_advances_head_once(self):
        revision, intent, observation, _result = self.delivered_claim()
        initial = capture_archive_projection(
            actor=self.alpha_user,
            organization_id=self.alpha.id,
            request_id=uuid.uuid4(),
            encounter_id=revision.encounter_id,
            expected_projection_id=None,
        )
        _delivery, lifecycle = self.admit_inbound(
            kind="lifecycle", intent=intent, observation=observation,
        )
        accept_lifecycle(
            actor=self.alpha_user,
            organization_id=self.alpha.id,
            request_id=uuid.uuid4(),
            candidate_id=lifecycle.candidate_id,
            artifact_store=self.store,
        )
        barrier = threading.Barrier(2)

        def capture_successor():
            close_old_connections()
            try:
                barrier.wait(timeout=10)
                try:
                    return capture_archive_projection(
                        actor=self.alpha_user,
                        organization_id=self.alpha.id,
                        request_id=uuid.uuid4(),
                        encounter_id=revision.encounter_id,
                        expected_projection_id=initial.projection_id,
                    ).reason_code
                except CommandError as exc:
                    return exc.reason_code
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = [future.result(timeout=15) for future in (
                pool.submit(capture_successor),
                pool.submit(capture_successor),
            )]

        self.assertEqual(results.count("archive_projection_captured"), 1)
        self.assertEqual(results.count("archive_projection_head_conflict"), 1)
        projections = ArchiveProjection.objects.filter(
            encounter_id=revision.encounter_id,
        ).order_by("version")
        self.assertEqual(list(projections.values_list("version", flat=True)), [1, 2])
        self.assertEqual(ArchiveCommandReceipt.objects.filter(
            command_kind="capture_archive_projection",
        ).count(), 2)
