from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
import uuid
from decimal import Decimal

from django.db import connection

from medicafe_v1.claims.commands import prepare_claim_revision
from medicafe_v1.claims.models import ClaimRevision

from tests.f2.base import F2TransactionTestCase


class F2DurabilityTests(F2TransactionTestCase):
    def test_envelope_and_exact_line_ids_survive_a_fresh_process(self):
        _delivery, _observation, resolved = self.resolved_observation(
            note="SYNTHETIC_F2_FRESH_PROCESS"
        )
        service = self.accepted_service(
            resolved,
            _observation,
            code="SYN-A",
            units=2,
            unit_amount=Decimal("6.25"),
            reason="Synthetic durable claim service",
        )
        prepared = prepare_claim_revision(
            actor=self.alpha_user,
            organization_id=self.alpha.id,
            request_id=uuid.uuid4(),
            encounter_id=resolved.encounter_id,
            expected_claim_revision_id=None,
            selected_service_revision_ids=[service.revision_id],
            route_id="synthetic-receiver",
            route_version="v1",
            reason="Synthetic fresh-process envelope",
        )
        revision = ClaimRevision.objects.get(pk=prepared.revision_id)
        envelope_hex = bytes(revision.envelope_bytes).hex()
        database = connection.settings_dict
        environment = os.environ.copy()
        environment.update({
            "PYTHONPATH": str(Path(__file__).resolve().parents[2] / "src"),
            "DJANGO_SETTINGS_MODULE": "medicafe_v1.settings",
            "POSTGRES_DB": database["NAME"],
            "POSTGRES_USER": database["USER"],
            "POSTGRES_PASSWORD": database["PASSWORD"],
            "POSTGRES_HOST": database["HOST"],
            "POSTGRES_PORT": str(database["PORT"]),
        })
        script = (
            "import django; django.setup(); "
            "from medicafe_v1.claims.models import ClaimRevision; "
            f"r=ClaimRevision.objects.get(pk='{revision.id}'); "
            "lines=list(r.lines.order_by('ordinal')); "
            "print(r.claim_id, r.id, r.envelope_digest, bytes(r.envelope_bytes).hex(), "
            "','.join(str(line.service_revision_id) for line in lines))"
        )
        completed = subprocess.run(
            [sys.executable, "-c", script],
            check=True,
            capture_output=True,
            text=True,
            env=environment,
            timeout=20,
        )
        self.assertIn(str(prepared.claim_id), completed.stdout)
        self.assertIn(str(revision.id), completed.stdout)
        self.assertIn(revision.envelope_digest, completed.stdout)
        self.assertIn(envelope_hex, completed.stdout)
        self.assertIn(str(service.revision_id), completed.stdout)

