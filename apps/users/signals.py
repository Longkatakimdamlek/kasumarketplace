from django.dispatch import receiver
from allauth.account.signals import user_signed_up
from allauth.socialaccount.signals import social_account_added
from .models import CustomUser


def _assign_role_from_request(request, user):
    """Helper that inspects the request and assigns user.role.

    Uses simple substring checks (case-insensitive) on the request path
    and the `next` GET parameter. Uses print() for lightweight debugging
    as requested.
    """
    # Defensive access to request attributes (social providers sometimes
    # call signals without a full request object available).
    path = getattr(request, 'path', '') or ''
    path = path.lower()

    try:
        next_url = (request.GET.get('next', '') or '').lower()
    except Exception:
        # If request doesn't have GET (rare), fall back to empty string
        next_url = ''

    # Debug prints for development; remove or replace with logging in prod
    print(f"Signup - Request Path: {path}")
    print(f"Signup - Next URL: {next_url}")

    if 'vendor' in path or 'vendor' in next_url:
        user.role = 'vendor'
    else:
        user.role = 'buyer'

    print(f"Assigned role '{user.role}' to user {getattr(user, 'email', repr(user))}")
    user.save()


@receiver(user_signed_up)
def assign_role_on_account_signup(request, user, **kwargs):
    """Handle role assignment for regular (email/password) signups."""
    if request is None:
        # Nothing we can inspect — default to buyer to be safe
        user.role = getattr(user, 'role', 'buyer') or 'buyer'
        user.save()
        print(f"No request available; left role as '{user.role}' for {getattr(user,'email',repr(user))}")
        return

    _assign_role_from_request(request, user)


@receiver(social_account_added)
def assign_role_on_social_signup(request, sociallogin, **kwargs):
    """Handle role assignment when a user is created/connected via social auth.

    The `social_account_added` signal is fired when a social account is added
    to a user (including the initial creation). `sociallogin.user` is the
    Django user instance.
    """
    user = getattr(sociallogin, 'user', None)
    if user is None:
        return

    # Some social flows may not provide a request object; handle defensively
    if request is None:
        # Nothing we can inspect — default to buyer to be safe
        user.role = getattr(user, 'role', 'buyer') or 'buyer'
        user.save()
        print(f"No request available for social signup; left role as '{user.role}' for {getattr(user,'email',repr(user))}")
        return

    _assign_role_from_request(request, user)

