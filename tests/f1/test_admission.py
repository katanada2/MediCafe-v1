from __future__ import annotations

import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from django.db import close_old_connections

from medicafe_v1.access.services import AuthorizationError
from medicafe_v1.sources.artifacts import LocalArtifactStore
from medicafe_v1.sources.domain import CommandError
from medicafe_v1.sources.models import Artifact, Delivery, ParseAttempt

from tests.fixtures.synthetic_inputs import CSV_MEDIA_TYPE, csv_bytes, synthetic_rows
from tests.f1.base import F1TestCase, F1TransactionTestCase


class AdmissionAndArtifactTests(F1TestCase):
    def test_replay_conflict_artifact_reuse_and_corrected_source_lineage(self):
        source_key = str(uuid.uuid4())
        original = csv_bytes(synthetic_rows(note="SYNTHETIC_ORIGINAL"))

        admitted = self.admit(content=original, source_key=source_key)
        replay = self.admit(content=original, source_key=source_key)
        self.assertEqual(admitted.reason_code, "delivery_admitted")
        self.assertEqual(replay.reason_code, "delivery_replayed")
        self.assertEqual(replay.delivery_id, admitted.delivery_id)

        with self.assertRaises(CommandError) as changed:
            self.admit(content=csv_bytes(synthetic_rows(note="SYNTHETIC_CHANGED")), source_key=source_key)
        self.assertEqual(changed.exception.reason_code, "delivery_source_conflict")

        same_digest = self.admit(content=original, source_key=str(uuid.uuid4()))
        self.assertNotEqual(same_digest.delivery_id, admitted.delivery_id)
        self.assertEqual(Artifact.objects.filter(organization=self.alpha).count(), 1)
        self.assertEqual(
            Delivery.objects.filter(organization=self.alpha, artifact_id=self.delivery(admitted.delivery_id).artifact_id).count(),
            2,
        )

        corrected = self.admit(
            content=csv_bytes(synthetic_rows(note="SYNTHETIC_CORRECTED")),
            source_key=str(uuid.uuid4()),
            supersedes_id=admitted.delivery_id,
        )
        corrected_delivery = self.delivery(corrected.delivery_id)
        self.assertEqual(corrected.reason_code, "delivery_admitted")
        self.assertEqual(corrected_delivery.supersedes_id, admitted.delivery_id)
        self.assertEqual(Artifact.objects.filter(organization=self.alpha).count(), 2)
        self.assertEqual(Delivery.objects.filter(organization=self.alpha).count(), 3)

    def test_upload_envelope_membership_and_artifact_storage_fail_closed(self):
        with self.assertRaises(CommandError) as empty:
            self.admit(content=b"")
        self.assertEqual(empty.exception.reason_code, "upload_empty")

        with self.assertRaises(CommandError) as oversized:
            self.admit(content=b"x" * (5 * 1024 * 1024 + 1))
        self.assertEqual(oversized.exception.reason_code, "upload_too_large")

        with self.assertRaises(CommandError) as unsupported:
            self.admit(content=b"synthetic", media_type="application/octet-stream")
        self.assertEqual(unsupported.exception.reason_code, "media_type_unsupported")

        with self.assertRaises(CommandError) as blank_identity:
            self.admit(source_namespace=" ")
        self.assertEqual(blank_identity.exception.reason_code, "source_identity_required")

        self.deactivate_membership = self.alpha.membership_set.get(user=self.alpha_user)
        self.deactivate_membership.is_active = False
        self.deactivate_membership.save(update_fields=["is_active"])
        with self.assertRaises(AuthorizationError) as inactive:
            self.admit()
        self.assertEqual(inactive.exception.reason_code, "active_membership_required")

    def test_artifact_is_content_addressed_and_corruption_is_retryable(self):
        content = csv_bytes(synthetic_rows(note="SYNTHETIC_ARTIFACT_SENTINEL"))
        admitted = self.admit(content=content)
        delivery = self.delivery(admitted.delivery_id)
        path = Path(self._artifact_tmp.name) / delivery.artifact.storage_key

        self.assertTrue(path.is_file())
        self.assertNotIn("synthetic.csv", delivery.artifact.storage_key)
        self.assertEqual(path.read_bytes(), content)

        path.write_bytes(b"SYNTHETIC_CORRUPTED_BYTES")
        with self.assertRaises(CommandError) as unavailable:
            self.parse(delivery.id)
        self.assertEqual(unavailable.exception.reason_code, "artifact_unavailable")
        self.assertEqual(ParseAttempt.objects.filter(delivery=delivery).count(), 1)
        self.assertFalse(ParseAttempt.objects.filter(delivery=delivery).first().succeeded)

        path.write_bytes(content)
        parsed = self.parse(delivery.id)
        self.assertEqual(parsed.reason_code, "parse_succeeded")


class ConcurrentAdmissionTests(F1TransactionTestCase):
    def test_same_digest_admitted_concurrently_reuses_one_artifact(self):
        content = csv_bytes(synthetic_rows(note="SYNTHETIC_CONCURRENT_ADMISSION"))
        gate = threading.Barrier(2)

        class SynchronizedStore(LocalArtifactStore):
            def put(self, organization_id, payload):
                value = super().put(organization_id, payload)
                gate.wait(timeout=15)
                return value

        store = SynchronizedStore(self._artifact_tmp.name)
        errors = []
        results = []

        def worker(source_key):
            close_old_connections()
            try:
                from medicafe_v1.sources.commands import admit_delivery
                from medicafe_v1.access.models import User

                result = admit_delivery(
                    actor=User.objects.get(pk=self.alpha_user.pk),
                    organization_id=self.alpha.id,
                    source_namespace="synthetic-concurrent",
                    source_key=source_key,
                    content=content,
                    media_type=CSV_MEDIA_TYPE,
                    artifact_store=store,
                )
                results.append(result)
            except Exception as exc:  # surfaced below with both thread outcomes
                errors.append(exc)
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [executor.submit(worker, str(uuid.uuid4())) for _ in range(2)]
            for future in futures:
                future.result(timeout=30)

        self.assertEqual(errors, [])
        self.assertEqual(len(results), 2)
        self.assertTrue(all(result.reason_code == "delivery_admitted" for result in results))
        self.assertEqual(Artifact.objects.filter(organization=self.alpha).count(), 1)
        self.assertEqual(
            Delivery.objects.filter(organization=self.alpha, source_namespace="synthetic-concurrent").count(),
            2,
        )
