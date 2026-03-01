"""Utility middleware for marketplace app."""

from django.utils.deprecation import MiddlewareMixin


class PreserveSessionKeyMiddleware(MiddlewareMixin):
    """Store the current session key on the request for later use.

    Django may rotate/flush the session during login, which makes the
    previous anonymous session key unavailable to post-login signals.  By
    capturing the value here we can reference it in our `merge_cart_on_login`
    signal handler and therefore correctly migrate the anonymous cart.
    """

    def process_request(self, request):
        request._pre_login_session_key = request.session.session_key
        # nothing to return; middleware chain continues
