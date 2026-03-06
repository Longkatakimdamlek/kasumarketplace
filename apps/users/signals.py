from django.dispatch import receiver
from allauth.account.signals import user_signed_up
from allauth.socialaccount.signals import social_account_added
from .models import CustomUser
import logging

logger = logging.getLogger(__name__)


def _assign_role_from_request(request, user):
    """Helper that inspects the request and assigns user.role.

    **Idempotent:** if the user already has a non‑buyer role the helper does
    nothing.  This prevents later signals from undoing a vendor assignment made
    earlier by the adapter or the signup form.
    """
    # if user already has a role other than the default 'buyer', leave it
    current = getattr(user, 'role', '') or ''
    if current and current != 'buyer':
        logger.info(
            "_assign_role_from_request: skipping role assignment for %s (already '%s')",
            getattr(user, 'email', repr(user)), current
        )
        return

    # first priority: explicit session value (set by signup view)
    role_from_session = request.session.pop('signup_role', None)
    if role_from_session:
        user.role = role_from_session
        user.save()
        print(f"Assigned role '{user.role}' from session to {getattr(user, 'email', repr(user))}")
        return

    path = getattr(request, 'path', '') or ''
    path = path.lower()

    try:
        next_url = (request.GET.get('next', '') or '').lower()
    except Exception:
        next_url = ''

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
    try:
        if request is None:
            user.role = getattr(user, 'role', 'buyer') or 'buyer'
            user.save()
            print(f"No request available; left role as '{user.role}' for {getattr(user, 'email', repr(user))}")
            logger.info(f"No request in user_signed_up signal, assigned role: {user.role}")
            return

        _assign_role_from_request(request, user)
        logger.info(f"Assigned role '{user.role}' on signup for {user.email}")
    except Exception as e:
        logger.error(f"Error in assign_role_on_account_signup signal: {str(e)}", exc_info=True)
        # Don't re-raise to prevent breaking the signup process


@receiver(social_account_added)
def assign_role_on_social_signup(request, sociallogin, **kwargs):
    """Handle role assignment when a user is created/connected via social auth."""
    try:
        user = getattr(sociallogin, 'user', None)
        if user is None:
            logger.warning("No user object in sociallogin")
            return

        if request is None:
            user.role = getattr(user, 'role', 'buyer') or 'buyer'
            user.save()
            print(f"No request available for social signup; left role as '{user.role}' for {getattr(user, 'email', repr(user))}")
            logger.info(f"No request in social_account_added signal, assigned role: {user.role}")
            return

        _assign_role_from_request(request, user)
        logger.info(f"Assigned role '{user.role}' on social signup for {user.email}")
    except Exception as e:
        logger.error(f"Error in assign_role_on_social_signup signal: {str(e)}", exc_info=True)
        # Don't re-raise to prevent breaking the signup process
    