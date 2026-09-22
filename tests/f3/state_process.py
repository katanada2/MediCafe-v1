from __future__ import annotations

import json
import sys

import django


def main():
    django.setup()
    from medicafe_v1.claims.models import DeliveryIntent
    from medicafe_v1.claims.queries import delivery_effect_state

    intent = DeliveryIntent.objects.get(id=sys.argv[1])
    print(json.dumps({
        "intent_id": str(intent.id),
        "state": delivery_effect_state(intent),
        "attempts": intent.attempts.count(),
        "outcomes": sum(hasattr(attempt, "outcome") for attempt in intent.attempts.all()),
        "observations": intent.observations.count(),
    }, sort_keys=True))


if __name__ == "__main__":
    main()
