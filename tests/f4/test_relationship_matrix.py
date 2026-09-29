from __future__ import annotations

import hashlib
import uuid
from datetime import timedelta

from django.db import DatabaseError, connection, transaction
from django.utils import timezone

from medicafe_v1.archival.commands import capture_archive_projection, queue_archive_batch
from medicafe_v1.archival.models import (
    ArchiveAttempt, ArchiveAttemptOutcome, ArchiveAuthorization, ArchiveBatch,
    ArchiveBatchItem, ArchiveCommandReceipt, ArchiveHead, ArchiveProjection,
    ArchiveReadbackObservation, ArchiveWork,
)
from medicafe_v1.archival.worker import _admit_attempt, _claim_work
from medicafe_v1.outcomes.commands import accept_lifecycle, post_remittance
from medicafe_v1.outcomes.models import (
    AcceptedEvent, AcceptedEventEvidence, ChargeBasis, FinancialAccount,
    InboundAttempt, InboundCandidate, InboundConflict, OutcomesCommandReceipt,
    PostingBatch, PostingEntry,
)

from .base import F4TransactionTestCase


class OutcomesRelationshipMatrixTests(F4TransactionTestCase):
    def test_inbound_attempt_and_accepted_event_owner_links_fail_closed(self):
        revision, intent, observation, _result = self.delivered_claim()
        delivery, interpreted = self.admit_inbound(
            kind="lifecycle", intent=intent, observation=observation,
        )
        candidate = InboundCandidate.objects.get(id=interpreted.candidate_id)
        with self.assertRaisesMessage(
            DatabaseError, "inbound attempt delivery or terminal time mismatch",
        ), transaction.atomic():
            InboundAttempt.objects.create(
                organization=self.beta,
                delivery_id=delivery.delivery_id,
                interpreter_version="wrong-owner",
                started_at=timezone.now(),
                ended_at=timezone.now(),
                succeeded=False,
                reason_code="synthetic",
            )

        other_revision, _other_intent, other_observation, _other_result = (
            self.delivered_claim()
        )
        with self.assertRaisesMessage(
            DatabaseError, "accepted event candidate or delivery evidence mismatch",
        ), transaction.atomic():
            AcceptedEvent.objects.create(
                organization=self.alpha,
                primary_candidate=candidate,
                kind=candidate.kind,
                sender_id=candidate.sender_id,
                event_id=candidate.event_id,
                semantic_digest=candidate.semantic_digest,
                intent=intent,
                claim_revision=other_revision,
                receiver_observation=other_observation,
                receiver_evidence_fingerprint=other_observation.evidence_fingerprint,
                receiver_receipt_id=other_observation.receipt_id,
                lifecycle_sequence=candidate.lifecycle_sequence,
                predecessor_event_id=candidate.predecessor_event_id,
                lifecycle_status=candidate.lifecycle_status,
                accepted_by=self.alpha_user,
            )
        self.assertFalse(AcceptedEvent.objects.filter(
            primary_candidate=candidate,
        ).exists())

    def test_candidate_and_conflict_relationships_fail_closed(self):
        _revision, intent, observation, _result = self.delivered_claim()
        _delivery, interpreted = self.admit_inbound(
            kind="lifecycle", intent=intent, observation=observation,
        )
        candidate = InboundCandidate.objects.get(id=interpreted.candidate_id)
        with self.assertRaisesMessage(
            DatabaseError, "inbound candidate delivery mismatch",
        ), transaction.atomic():
            InboundCandidate.objects.create(
                organization=self.beta, delivery=candidate.delivery,
                interpreter_version="wrong-organization",
                schema_version=candidate.schema_version, kind=candidate.kind,
                sender_id=candidate.sender_id, event_id=uuid.uuid4(),
                delivery_key=candidate.delivery_key, intent_id=candidate.intent_id,
                claim_revision_id=candidate.claim_revision_id,
                receiver_receipt_id=candidate.receiver_receipt_id,
                currency="", lifecycle_sequence=1,
                predecessor_event_id=None,
                lifecycle_status=candidate.lifecycle_status,
                normalized_content=candidate.normalized_content,
                semantic_bytes=candidate.semantic_bytes,
                semantic_digest=candidate.semantic_digest,
            )
        with self.assertRaisesMessage(
            DatabaseError, "inbound conflict evidence mismatch",
        ), transaction.atomic():
            InboundConflict.objects.create(
                organization=self.alpha, existing_candidate=candidate,
                conflicting_candidate=candidate,
                reason_code="conflicting_identity_or_content",
            )

    def test_evidence_link_and_lifecycle_predecessor_must_match(self):
        _revision, intent, observation, _result = self.delivered_claim()
        _delivery, first = self.admit_inbound(
            kind="lifecycle", intent=intent, observation=observation,
        )
        accepted = accept_lifecycle(
            actor=self.alpha_user, organization_id=self.alpha.id,
            request_id=uuid.uuid4(), candidate_id=first.candidate_id,
            artifact_store=self.store,
        )
        event = AcceptedEvent.objects.get(id=accepted.event_id)
        _remit_delivery, remit = self.admit_inbound(
            kind="remittance", intent=intent, observation=observation,
        )
        remit_candidate = InboundCandidate.objects.get(id=remit.candidate_id)
        with self.assertRaisesMessage(
            DatabaseError, "accepted event evidence mismatch",
        ), transaction.atomic():
            AcceptedEventEvidence.objects.create(
                organization=self.alpha, event=event, candidate=remit_candidate,
            )

        _other_revision, other_intent, other_observation, _other_result = (
            self.delivered_claim()
        )
        _other_delivery, other_candidate = self.admit_inbound(
            kind="lifecycle", intent=other_intent, observation=other_observation,
        )
        other_event = accept_lifecycle(
            actor=self.alpha_user, organization_id=self.alpha.id,
            request_id=uuid.uuid4(), candidate_id=other_candidate.candidate_id,
            artifact_store=self.store,
        )
        wrong_stream_event_id = AcceptedEvent.objects.get(
            id=other_event.event_id,
        ).event_id
        _second_delivery, second = self.admit_inbound(
            kind="lifecycle", intent=intent, observation=observation,
            sequence=2, predecessor_event_id=wrong_stream_event_id,
        )
        candidate = InboundCandidate.objects.get(id=second.candidate_id)
        with self.assertRaisesMessage(
            DatabaseError, "lifecycle predecessor missing or mismatched",
        ), transaction.atomic():
            AcceptedEvent.objects.create(
                organization=self.alpha, primary_candidate=candidate,
                kind=candidate.kind, sender_id=candidate.sender_id,
                event_id=candidate.event_id, semantic_digest=candidate.semantic_digest,
                intent=intent, claim_revision_id=intent.claim_revision_id,
                receiver_observation=observation,
                receiver_evidence_fingerprint=observation.evidence_fingerprint,
                receiver_receipt_id=observation.receipt_id,
                lifecycle_sequence=2,
                predecessor_event_id=candidate.predecessor_event_id,
                lifecycle_status=candidate.lifecycle_status,
                accepted_by=self.alpha_user,
            )

    def test_financial_basis_batch_entry_and_completeness_relationships(self):
        revision, intent, observation, _result = self.delivered_claim()
        with self.assertRaisesMessage(
            DatabaseError, "financial account charge or revision mismatch",
        ), transaction.atomic():
            FinancialAccount.objects.create(
                organization=self.alpha, claim_revision=revision,
                currency=revision.currency,
                original_charge=revision.total_amount + 1,
            )
        account = FinancialAccount.objects.create(
            organization=self.alpha, claim_revision=revision,
            currency=revision.currency, original_charge=revision.total_amount,
        )
        line = revision.lines.get(ordinal=1)
        with self.assertRaisesMessage(
            DatabaseError, "charge basis line or account mismatch",
        ), transaction.atomic():
            ChargeBasis.objects.create(
                organization=self.alpha, account=account, claim_line=line,
                line_ordinal=line.ordinal, original_charge=line.line_amount + 1,
                currency=line.currency,
            )
        other_revision, _other_intent, _other_observation, _other_result = (
            self.delivered_claim()
        )
        other_line = other_revision.lines.get(ordinal=1)
        with self.assertRaisesMessage(
            DatabaseError, "charge basis line or account mismatch",
        ), transaction.atomic():
            ChargeBasis.objects.create(
                organization=self.alpha,
                account=account,
                claim_line=other_line,
                line_ordinal=other_line.ordinal,
                original_charge=other_line.line_amount,
                currency=other_line.currency,
            )
        basis = ChargeBasis.objects.create(
            organization=self.alpha, account=account, claim_line=line,
            line_ordinal=line.ordinal, original_charge=line.line_amount,
            currency=line.currency,
        )
        _life_delivery, lifecycle = self.admit_inbound(
            kind="lifecycle", intent=intent, observation=observation,
        )
        lifecycle_result = accept_lifecycle(
            actor=self.alpha_user, organization_id=self.alpha.id,
            request_id=uuid.uuid4(), candidate_id=lifecycle.candidate_id,
            artifact_store=self.store,
        )
        with self.assertRaisesMessage(
            DatabaseError, "posting batch event or account mismatch",
        ), transaction.atomic():
            PostingBatch.objects.create(
                organization=self.alpha,
                event_id=lifecycle_result.event_id, account=account,
            )

        _remit_delivery, remittance = self.admit_inbound(
            kind="remittance", intent=intent, observation=observation,
            lines=[{
                "line_ordinal": 1, "paid_amount": "2.00",
                "contractual_adjustment": "0.00",
            }],
        )
        candidate = InboundCandidate.objects.get(id=remittance.candidate_id)
        with self.assertRaisesMessage(
            DatabaseError, "posting batch is incomplete or contains extra entries",
        ), transaction.atomic():
            event = AcceptedEvent.objects.create(
                organization=self.alpha, primary_candidate=candidate,
                kind=candidate.kind, sender_id=candidate.sender_id,
                event_id=candidate.event_id, semantic_digest=candidate.semantic_digest,
                intent=intent, claim_revision=revision,
                receiver_observation=observation,
                receiver_evidence_fingerprint=observation.evidence_fingerprint,
                receiver_receipt_id=observation.receipt_id,
                lifecycle_sequence=None, predecessor_event_id=None,
                lifecycle_status="", accepted_by=self.alpha_user,
            )
            AcceptedEventEvidence.objects.create(
                organization=self.alpha, event=event, candidate=candidate,
            )
            PostingBatch.objects.create(
                organization=self.alpha, event=event, account=account,
            )

        _posted_delivery, posted_candidate = self.admit_inbound(
            kind="remittance", intent=intent, observation=observation,
        )
        posted = post_remittance(
            actor=self.alpha_user, organization_id=self.alpha.id,
            request_id=uuid.uuid4(), candidate_id=posted_candidate.candidate_id,
            artifact_store=self.store,
        )
        entry = PostingEntry.objects.filter(batch_id=posted.batch_id).first()
        with self.assertRaisesMessage(
            DatabaseError, "posting entry relationship mismatch",
        ), transaction.atomic():
            PostingEntry.objects.create(
                organization=self.alpha, batch_id=posted.batch_id,
                event_id=posted.event_id, account=account, charge_basis=basis,
                claim_line=line, kind=PostingEntry.KIND_PAYMENT,
                amount="1.00", currency="EUR",
            )
        with self.assertRaisesMessage(
            DatabaseError, "posting entry relationship mismatch",
        ), transaction.atomic():
            PostingEntry.objects.create(
                organization=self.alpha,
                batch_id=posted.batch_id,
                event_id=posted.event_id,
                account=account,
                charge_basis=basis,
                claim_line=other_line,
                kind=PostingEntry.KIND_PAYMENT,
                amount="4.00",
                currency=account.currency,
            )
        with self.assertRaisesMessage(
            DatabaseError, "posting entry kind unsupported",
        ), transaction.atomic():
            PostingEntry.objects.create(
                organization=self.alpha, batch_id=posted.batch_id,
                event_id=posted.event_id, account=account, charge_basis=basis,
                claim_line=line, kind="wrong_component",
                amount="1.00", currency=account.currency,
            )
        with self.assertRaisesMessage(
            DatabaseError, "F4 accepted history is immutable",
        ), transaction.atomic():
            PostingEntry.objects.filter(id=entry.id).update(amount="0.01")
        with self.assertRaisesMessage(
            DatabaseError, "F4 accepted history is immutable",
        ), transaction.atomic(), connection.cursor() as cursor:
            cursor.execute(
                "DELETE FROM outcomes_inboundcandidate WHERE id=%s",
                [candidate.id],
            )

    def test_outcomes_receipt_cannot_point_to_unrelated_result(self):
        _revision, intent, observation, _result = self.delivered_claim()
        _life_delivery, lifecycle = self.admit_inbound(
            kind="lifecycle", intent=intent, observation=observation,
        )
        accepted = accept_lifecycle(
            actor=self.alpha_user, organization_id=self.alpha.id,
            request_id=uuid.uuid4(), candidate_id=lifecycle.candidate_id,
            artifact_store=self.store,
        )
        _remit_delivery, remittance = self.admit_inbound(
            kind="remittance", intent=intent, observation=observation,
        )
        with self.assertRaisesMessage(
            DatabaseError, "outcomes command receipt result mismatch",
        ), transaction.atomic():
            OutcomesCommandReceipt.objects.create(
                organization=self.alpha, request_uuid=uuid.uuid4(),
                command_kind="post_remittance",
                target_candidate_id=remittance.candidate_id,
                target_intent_id=intent.id, intent_digest="d" * 64,
                accepted_by=self.alpha_user, result_event_id=accepted.event_id,
                result_batch=None,
            )


class ArchiveRelationshipMatrixTests(F4TransactionTestCase):
    def _projection(self):
        _revision, intent, _observation, _result = self.delivered_claim()
        return capture_archive_projection(
            actor=self.alpha_user, organization_id=self.alpha.id,
            request_id=uuid.uuid4(), encounter_id=intent.claim_revision.encounter_id,
            expected_projection_id=None,
        )

    def test_head_rewind_and_cross_projection_batch_item_fail_closed(self):
        first = self._projection()
        second = self._projection()
        queued = queue_archive_batch(
            actor=self.alpha_user, organization_id=self.alpha.id,
            request_id=uuid.uuid4(), projection_ids=[first.projection_id],
        )
        item = ArchiveBatchItem.objects.get(batch_id=queued.batch_id)
        foreign_batch = ArchiveBatch.objects.create(
            organization=self.alpha, created_by=self.alpha_user,
        )
        with self.assertRaisesMessage(
            DatabaseError, "archive batch item relationship mismatch",
        ), transaction.atomic():
            ArchiveBatchItem.objects.create(
                organization=self.alpha, batch=foreign_batch, ordinal=1,
                projection_id=second.projection_id, work=item.work,
                authorization=item.authorization,
            )

        first_projection = ArchiveProjection.objects.get(id=first.projection_id)
        # Create a valid successor for the first encounter by changing outcomes.
        intent = first_projection.encounter.claim.current_revision.delivery_intents.first()
        observation = intent.observations.filter(binding_valid=True).first()
        _delivery, lifecycle = self.admit_inbound(
            kind="lifecycle", intent=intent, observation=observation,
        )
        accept_lifecycle(
            actor=self.alpha_user, organization_id=self.alpha.id,
            request_id=uuid.uuid4(), candidate_id=lifecycle.candidate_id,
            artifact_store=self.store,
        )
        successor = capture_archive_projection(
            actor=self.alpha_user, organization_id=self.alpha.id,
            request_id=uuid.uuid4(), encounter_id=first_projection.encounter_id,
            expected_projection_id=first.projection_id,
        )
        self.assertNotEqual(successor.projection_id, first.projection_id)
        head = ArchiveHead.objects.get(encounter_id=first_projection.encounter_id)
        with self.assertRaisesMessage(
            DatabaseError, "archive head cannot rewind or skip predecessor",
        ), transaction.atomic():
            ArchiveHead.objects.filter(id=head.id).update(
                projection_id=first.projection_id,
            )

    def test_projection_work_and_capture_receipt_owner_links_fail_closed(self):
        first = self._projection()
        second = self._projection()
        first_projection = ArchiveProjection.objects.get(id=first.projection_id)
        second_projection = ArchiveProjection.objects.get(id=second.projection_id)
        payload = b"{}"
        with self.assertRaisesMessage(
            DatabaseError, "archive projection predecessor mismatch",
        ), transaction.atomic():
            ArchiveProjection.objects.create(
                organization=self.alpha,
                encounter=second_projection.encounter,
                version=2,
                predecessor=first_projection,
                source_fingerprint="a" * 64,
                schema_version="synthetic-archive-v1",
                projection_bytes=payload,
                projection_digest=hashlib.sha256(payload).hexdigest(),
                byte_length=len(payload),
                captured_by=self.alpha_user,
            )

        queued = queue_archive_batch(
            actor=self.alpha_user,
            organization_id=self.alpha.id,
            request_id=uuid.uuid4(),
            projection_ids=[first.projection_id],
        )
        item = ArchiveBatchItem.objects.get(batch_id=queued.batch_id)
        with self.assertRaisesMessage(
            DatabaseError, "archive work projection or authorization mismatch",
        ), transaction.atomic():
            ArchiveWork.objects.create(
                organization=self.alpha,
                projection=second_projection,
                scheduled_authorization=item.authorization,
                state=ArchiveWork.STATE_PENDING,
                due_at=timezone.now(),
            )

        with self.assertRaisesMessage(
            DatabaseError, "archive capture receipt result mismatch",
        ), transaction.atomic():
            ArchiveCommandReceipt.objects.create(
                organization=self.alpha,
                request_uuid=uuid.uuid4(),
                command_kind="capture_archive_projection",
                target_key=str(second_projection.encounter_id),
                intent_digest="d" * 64,
                accepted_by=self.alpha_user,
                result_projection=first_projection,
                result_code="archive_projection_captured",
            )
        with self.assertRaisesMessage(
            DatabaseError, "F4 archive history is immutable",
        ), transaction.atomic():
            ArchiveProjection.objects.filter(id=first_projection.id).update(
                projection_bytes=b"changed",
            )

    def test_authorization_attempt_outcome_and_receipt_relationships_fail_closed(self):
        first = self._projection()
        second = self._projection()
        queued = queue_archive_batch(
            actor=self.alpha_user, organization_id=self.alpha.id,
            request_id=uuid.uuid4(), projection_ids=[first.projection_id],
        )
        second_queued = queue_archive_batch(
            actor=self.alpha_user, organization_id=self.alpha.id,
            request_id=uuid.uuid4(), projection_ids=[second.projection_id],
        )
        second_authorization = ArchiveBatchItem.objects.get(
            batch_id=second_queued.batch_id,
        ).authorization
        ArchiveWork.objects.filter(
            projection_id=second.projection_id,
        ).update(due_at=timezone.now() + timedelta(days=1))
        work = ArchiveWork.objects.get(projection_id=first.projection_id)
        claim, recovered = _claim_work(worker_id="relationship-worker", lease_seconds=5)
        self.assertIsNone(recovered)
        self.assertEqual(claim[0], work.id)
        work.refresh_from_db()
        for relationship in ("authorization", "fence"):
            with self.subTest(relationship=relationship):
                with self.assertRaisesMessage(
                    DatabaseError,
                    "archive attempt lease, grant, projection, or budget mismatch",
                ), transaction.atomic():
                    ArchiveAttempt.objects.create(
                        organization=self.alpha,
                        projection_id=first.projection_id,
                        authorization=(
                            second_authorization
                            if relationship == "authorization"
                            else work.scheduled_authorization
                        ),
                        work=work,
                        ordinal=1,
                        receiver_id="synthetic-archive",
                        receiver_version="v1",
                        projection_digest=work.projection.projection_digest,
                        byte_length=work.projection.byte_length,
                        lease_owner=work.lease_owner,
                        fencing_generation=(
                            work.fencing_generation + 1
                            if relationship == "fence"
                            else work.fencing_generation
                        ),
                        started_at=timezone.now(),
                        possible_write=True,
                    )
        with self.assertRaisesMessage(
            DatabaseError, "archive attempt lease, grant, projection, or budget mismatch",
        ), transaction.atomic():
            ArchiveAttempt.objects.create(
                organization=self.alpha, projection_id=first.projection_id,
                authorization=work.scheduled_authorization, work=work, ordinal=1,
                receiver_id="wrong-receiver", receiver_version="v1",
                projection_digest=work.projection.projection_digest,
                byte_length=work.projection.byte_length,
                lease_owner=work.lease_owner,
                fencing_generation=work.fencing_generation,
                started_at=timezone.now(), possible_write=True,
            )
        frozen = _admit_attempt(
            work_id=work.id, worker_id=work.lease_owner,
            generation=work.fencing_generation,
        )
        attempt = ArchiveAttempt.objects.get(id=frozen.attempt_id)
        with self.assertRaisesMessage(
            DatabaseError, "archive outcome attempt mismatch",
        ), transaction.atomic():
            ArchiveAttemptOutcome.objects.create(
                organization=self.beta,
                attempt=attempt,
                kind=ArchiveAttemptOutcome.UNKNOWN,
                reason="wrong-owner",
                ended_at=timezone.now(),
            )
        with self.assertRaisesMessage(
            DatabaseError, "archive confirmation requires exact verified readback",
        ), transaction.atomic():
            ArchiveAttemptOutcome.objects.create(
                organization=self.alpha, attempt=attempt,
                kind=ArchiveAttemptOutcome.TARGET_CONFIRMED,
                reason="forged-confirmation", ended_at=timezone.now(),
                readback_observation=None,
            )

        ArchiveAttemptOutcome.objects.create(
            organization=self.alpha,
            attempt=attempt,
            kind=ArchiveAttemptOutcome.UNKNOWN,
            reason="synthetic-budget-use",
            ended_at=timezone.now(),
        )
        for ordinal in (2, 3):
            ArchiveWork.objects.filter(id=work.id).update(
                state=ArchiveWork.STATE_PENDING,
                due_at=timezone.now(),
                lease_owner="",
                lease_expires_at=None,
            )
            claim, recovered = _claim_work(
                worker_id=f"budget-worker-{ordinal}",
                lease_seconds=5,
            )
            self.assertIsNone(recovered)
            self.assertEqual(claim[0], work.id)
            work.refresh_from_db()
            used = ArchiveAttempt.objects.create(
                organization=self.alpha,
                projection=work.projection,
                authorization=work.scheduled_authorization,
                work=work,
                ordinal=ordinal,
                receiver_id="synthetic-archive",
                receiver_version="v1",
                projection_digest=work.projection.projection_digest,
                byte_length=work.projection.byte_length,
                lease_owner=work.lease_owner,
                fencing_generation=work.fencing_generation,
                started_at=timezone.now(),
                possible_write=True,
            )
            ArchiveAttemptOutcome.objects.create(
                organization=self.alpha,
                attempt=used,
                kind=ArchiveAttemptOutcome.UNKNOWN,
                reason="synthetic-budget-use",
                ended_at=timezone.now(),
            )
        ArchiveWork.objects.filter(id=work.id).update(
            state=ArchiveWork.STATE_PENDING,
            due_at=timezone.now(),
            lease_owner="",
            lease_expires_at=None,
        )
        claim, recovered = _claim_work(
            worker_id="budget-worker-4",
            lease_seconds=5,
        )
        self.assertIsNone(recovered)
        self.assertEqual(claim[0], work.id)
        work.refresh_from_db()
        with self.assertRaisesMessage(
            DatabaseError,
            "archive attempt lease, grant, projection, or budget mismatch",
        ), transaction.atomic():
            ArchiveAttempt.objects.create(
                organization=self.alpha,
                projection=work.projection,
                authorization=work.scheduled_authorization,
                work=work,
                ordinal=4,
                receiver_id="synthetic-archive",
                receiver_version="v1",
                projection_digest=work.projection.projection_digest,
                byte_length=work.projection.byte_length,
                lease_owner=work.lease_owner,
                fencing_generation=work.fencing_generation,
                started_at=timezone.now(),
                possible_write=True,
            )

        authorization_id = uuid.uuid4()
        with self.assertRaisesMessage(
            DatabaseError, "manual archive authorization predecessor mismatch",
        ), transaction.atomic():
            receipt = ArchiveCommandReceipt.objects.create(
                organization=self.alpha, request_uuid=uuid.uuid4(),
                command_kind="retry_archive_item",
                target_key=str(second.projection_id), intent_digest="a" * 64,
                accepted_by=self.alpha_user,
                result_projection_id=second.projection_id,
                result_authorization_id=authorization_id,
                result_code="archive_retry_scheduled",
            )
            ArchiveAuthorization.objects.create(
                id=authorization_id, organization=self.alpha,
                projection_id=second.projection_id,
                receiver_id="synthetic-archive", receiver_version="v1",
                kind=ArchiveAuthorization.KIND_MANUAL,
                command_receipt=receipt,
                expected_predecessor_attempt=attempt,
                allowed_attempts=1, authorized_by=self.alpha_user,
            )

        empty_batch = ArchiveBatch.objects.create(
            organization=self.alpha, created_by=self.alpha_user,
        )
        with self.assertRaisesMessage(
            DatabaseError, "archive queue receipt result mismatch",
        ), transaction.atomic():
            ArchiveCommandReceipt.objects.create(
                organization=self.alpha, request_uuid=uuid.uuid4(),
                command_kind="queue_archive_batch",
                target_key=str(empty_batch.id), intent_digest="b" * 64,
                accepted_by=self.alpha_user, result_batch=empty_batch,
                result_code="archive_batch_queued",
            )

    def test_wrong_item_readback_is_retained_conflict_and_cannot_confirm(self):
        first = self._projection()
        second = self._projection()
        queue_archive_batch(
            actor=self.alpha_user, organization_id=self.alpha.id,
            request_id=uuid.uuid4(), projection_ids=[first.projection_id],
        )
        work = ArchiveWork.objects.get(projection_id=first.projection_id)
        claim, _recovered = _claim_work(worker_id="observation-worker", lease_seconds=5)
        frozen = _admit_attempt(
            work_id=claim[0], worker_id="observation-worker", generation=claim[1],
        )
        attempt = ArchiveAttempt.objects.get(id=frozen.attempt_id)
        first_projection = ArchiveProjection.objects.get(id=first.projection_id)
        second_projection = ArchiveProjection.objects.get(id=second.projection_id)
        observation = ArchiveReadbackObservation.objects.create(
            organization=self.alpha, source_attempt=attempt,
            lookup_projection=second_projection,
            reported_attempt_id=attempt.id,
            receiver_id="synthetic-archive", receiver_version="v1",
            target_receipt_id=f"wrong-item-{uuid.uuid4()}",
            reported_organization_id=self.alpha.id,
            reported_encounter_id=first_projection.encounter_id,
            reported_projection_id=first_projection.id,
            reported_projection_version=first_projection.version,
            reported_digest=first_projection.projection_digest,
            reported_byte_length=first_projection.byte_length,
            received_bytes=first_projection.projection_bytes,
            evidence_fingerprint="c" * 64,
            observed_state=ArchiveReadbackObservation.STATE_VERIFIED,
            conflict_reason="", observed_at=timezone.now(),
        )
        observation.refresh_from_db()
        self.assertEqual(
            observation.observed_state,
            ArchiveReadbackObservation.STATE_CONFLICT,
        )
        with self.assertRaisesMessage(
            DatabaseError, "archive outcome readback does not match attempt projection",
        ), transaction.atomic():
            ArchiveAttemptOutcome.objects.create(
                organization=self.alpha, attempt=attempt,
                kind=ArchiveAttemptOutcome.TARGET_CONFIRMED,
                reason="wrong-item", ended_at=timezone.now(),
                readback_observation=observation,
            )
