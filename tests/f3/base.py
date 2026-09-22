"""PostgreSQL-only fixtures for F3 delivery tests."""

from __future__ import annotations

import uuid

from medicafe_v1.claims.commands import approve_claim_revision, prepare_claim_revision
from medicafe_v1.claims.models import ClaimApproval, ClaimRevision

from tests.f2.base import F2TestCase, F2TransactionTestCase


class F3FixtureMixin:
    def approved_claim(self, *, route_version="v1"):
        _, observation, resolved = self.resolved_observation()
        service = self.accepted_service(resolved, observation)
        prepared = prepare_claim_revision(
            actor=self.alpha_user, organization_id=self.alpha.id,
            request_id=uuid.uuid4(), encounter_id=resolved.encounter_id,
            expected_claim_revision_id=None,
            selected_service_revision_ids=[service.revision_id],
            route_id="synthetic-receiver", route_version=route_version,
            reason="Synthetic F3 claim preparation",
        )
        revision = ClaimRevision.objects.get(id=prepared.revision_id)
        approved = approve_claim_revision(
            actor=self.alpha_user, organization_id=self.alpha.id,
            request_id=uuid.uuid4(), claim_revision_id=revision.id,
            expected_envelope_digest=revision.envelope_digest,
        )
        return revision.claim, revision, ClaimApproval.objects.get(id=approved.approval_id)


class F3TestCase(F3FixtureMixin, F2TestCase):
    pass


class F3TransactionTestCase(F3FixtureMixin, F2TransactionTestCase):
    pass
