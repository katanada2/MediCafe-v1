from .models import Membership


class AuthorizationError(Exception):
    def __init__(self, reason_code="active_membership_required"):
        self.reason_code = reason_code
        super().__init__(reason_code)


def require_active_membership(*, actor, organization_id, for_update=False):
    if not actor or not actor.is_authenticated:
        raise AuthorizationError("authentication_required")
    try:
        query = Membership.objects.select_related("organization")
        if for_update:
            # Same-organization commands still serialize, while FK KEY SHARE at a
            # claims commit remains compatible and cannot invert the lock order.
            query = query.select_for_update(no_key=True)
        return query.get(
            user=actor, organization_id=organization_id, is_active=True
        )
    except Membership.DoesNotExist as exc:
        raise AuthorizationError() from exc
