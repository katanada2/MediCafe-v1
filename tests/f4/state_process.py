from __future__ import annotations

import json
import sys

import django


def main():
    django.setup()
    from medicafe_v1.access.models import User
    from medicafe_v1.outcomes.models import AcceptedEvent, PostingEntry
    from medicafe_v1.outcomes.queries import ledger_detail

    organization_id, user_id, claim_revision_id = sys.argv[1:4]
    actor = User.objects.get(id=user_id)
    ledger = ledger_detail(
        actor=actor, organization_id=organization_id,
        claim_revision_id=claim_revision_id,
    )
    print(json.dumps({
        "events": AcceptedEvent.objects.filter(
            organization_id=organization_id,
            claim_revision_id=claim_revision_id,
        ).count(),
        "entries": PostingEntry.objects.filter(
            organization_id=organization_id,
            account__claim_revision_id=claim_revision_id,
        ).count(),
        "original_charge": str(ledger.original_charge),
        "payer_reported_credits": str(ledger.payer_reported_credits),
        "contractual_adjustments": str(ledger.contractual_adjustments),
        "residual": str(ledger.residual),
    }, sort_keys=True))


if __name__ == "__main__":
    main()
