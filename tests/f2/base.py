"""Shared PostgreSQL-only setup for the synthetic F2 command tests."""

from __future__ import annotations

import uuid

from medicafe_v1.claims.commands import initialize_synthetic_policy
from medicafe_v1.records.commands import ResolutionIntent, accept_service, resolve_identity

from tests.f1.base import F1TestCase, F1TransactionTestCase
from tests.fixtures.synthetic_inputs import csv_bytes, synthetic_rows


class F2FixtureMixin:
    def setUp(self):
        super().setUp()
        self.policy = initialize_synthetic_policy(
            actor=self.alpha_user, organization_id=self.alpha.id
        )

    def resolved_observation(self, *, actor=None, organization=None, note="SYNTHETIC_F2_OBSERVATION"):
        actor = actor or self.alpha_user
        organization = organization or self.alpha
        admitted = self.admit(
            actor=actor,
            organization=organization,
            content=csv_bytes(synthetic_rows(note=note)),
        )
        self.parse(admitted.delivery_id, actor=actor, organization=organization)
        observation = self.first_observation(admitted.delivery_id)
        resolved = resolve_identity(
            actor=actor,
            organization_id=organization.id,
            observation_id=observation.id,
            request_uuid=uuid.uuid4(),
            intent=ResolutionIntent(
                mode="create",
                reason="Synthetic F2 identity review",
                display_name=f"Synthetic F2 Patient {uuid.uuid4().hex[:8]}",
                service_date="2026-01-15",
            ),
            artifact_store=self.store,
        )
        return self.delivery(admitted.delivery_id), observation, resolved

    def accepted_service(self, resolved, observation, *, actor=None, organization=None,
                         request_id=None, code="SYN-A", units=1,
                         unit_amount="10.00", currency="USD",
                         reason="Synthetic accepted service"):
        actor = actor or self.alpha_user
        organization = organization or self.alpha
        return accept_service(
            actor=actor,
            organization_id=organization.id,
            request_id=request_id or uuid.uuid4(),
            identity_decision_id=resolved.decision_id,
            evidence_observation_id=observation.id,
            code=code,
            units=units,
            unit_amount=unit_amount,
            currency=currency,
            reason=reason,
            artifact_store=self.store,
        )


class F2TestCase(F2FixtureMixin, F1TestCase):
    """Create isolated synthetic organizations and provision alpha's policy."""


class F2TransactionTestCase(F2FixtureMixin, F1TransactionTestCase):
    """F2 fixture setup without TestCase's outer transaction for race tests."""
