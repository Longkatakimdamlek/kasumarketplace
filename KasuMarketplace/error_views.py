"""Branded, standalone error handlers for KasuMarketplace.

These handlers must never crash.  They therefore:

* render templates with ``render_to_string`` and **no request argument**, so
  no context processors run and no database access happens while rendering;
* wrap every access to ``request.user`` / ``reverse()`` / ``settings`` in
  ``try/except`` with safe fallbacks;
* fall back to a tiny hardcoded HTML string if rendering itself raises;
* answer JSON instead of HTML for AJAX/JSON clients, without leaking
  exception text or the CSRF failure reason.
"""

import logging

from django.http import Http404, HttpResponse, JsonResponse
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils.safestring import mark_safe

logger = logging.getLogger(__name__)

# --------------------------------------------------------------------------
# Copy
# --------------------------------------------------------------------------

COPY = {
    "400": {
        "status": 400,
        "title": "That request didn't look right",
        "message": "Please go back and try again.",
    },
    "403": {
        "status": 403,
        "title": "You don't have access to this page",
        "message": "This page isn't available for your account.",
    },
    "404": {
        "status": 404,
        "title": "We can't find that page",
        "message": "The link may be broken, or the product or store may have been removed.",
    },
    "500": {
        "status": 500,
        "title": "Something went wrong on our side",
        "message": "It's not you. Please try again in a moment.",
    },
    "csrf": {
        "status": 403,
        "title": "Your session expired",
        "message": "For your security this page timed out. Go back, refresh the page and try again.",
    },
}

TEMPLATES = {
    "400": "400.html",
    "403": "403.html",
    "404": "404.html",
    "500": "500.html",
    "csrf": "csrf_failure.html",
}

# Short, plain-language JSON messages.  Never exception text, never the
# CSRF reason, never a traceback.
JSON_MESSAGES = {
    400: "Bad request.",
    403: "Access denied.",
    404: "Not found.",
    500: "Something went wrong. Please try again.",
}


def _wants_json(request):
    """True when the client asked for JSON rather than HTML."""
    try:
        if request.headers.get("x-requested-with") == "XMLHttpRequest":
            return True
        accept = request.headers.get("accept", "")
        return accept.startswith("application/json")
    except Exception:
        return False


def _json_response(status):
    return JsonResponse(
        {"success": False, "error": JSON_MESSAGES.get(status, "Something went wrong.")},
        status=status,
    )


def _fallback_html(status, title, message):
    """Last-resort page: hardcoded, no template, no reverse, no context."""
    return HttpResponse(
        "<!DOCTYPE html><html lang=\"en\"><head><meta charset=\"utf-8\">"
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">"
        "<meta name=\"robots\" content=\"noindex\">"
        "<title>{title} - KasuMarketplace</title>"
        "<style>body{{margin:0;min-height:100vh;display:flex;align-items:center;"
        "justify-content:center;font-family:'Manrope','DM Sans',system-ui,"
        "-apple-system,'Segoe UI',sans-serif;background:#F5F7FA;color:#111827;}}"
        "main{{text-align:center;padding:2rem;max-width:28rem;}}"
        ".num{{font-size:4rem;font-weight:800;color:#0b3f26;}}"
        "h1{{font-size:1.5rem;margin:.5rem 0;}}"
        "p{{color:#6B7280;line-height:1.6;margin:0 0 1.5rem;}}"
        "a{{display:inline-block;min-height:48px;line-height:48px;padding:0 1.5rem;"
        "background:#0b3f26;color:#fff;text-decoration:none;border-radius:.875rem;"
        "font-weight:600;}}</style></head><body><main>"
        "<div class=\"num\">{status}</div><h1>{title}</h1><p>{message}</p>"
        "<a href=\"/\">Go to Marketplace</a></main></body></html>".format(
            status=status, title=title, message=message
        ),
        status=status,
        content_type="text/html",
    )


def _primary_target(request):
    """Role-aware primary button.  Returns (url, label)."""
    try:
        if (
            request.user.is_authenticated
            and getattr(request.user, "is_vendor", False)
        ):
            return reverse("vendors:dashboard"), "Go to your dashboard"
    except Exception:
        pass
    try:
        return reverse("marketplace:product_list"), "Go to Marketplace"
    except Exception:
        return "/", "Go to Marketplace"


def _respond(request, template, status, title, message, *, show_login=False):
    """Build the JSON or HTML error response for one page."""
    if _wants_json(request):
        return _json_response(status)

    # Role-aware primary button.
    primary_url, primary_label = _primary_target(request)

    # Login link.
    login_url = "/accounts/login/"
    try:
        login_url = reverse("users:login")
    except Exception:
        pass

    # Home URL for no-JS fallbacks.
    home_url = "/"
    try:
        home_url = reverse("marketplace:product_list")
    except Exception:
        pass

    support_email = "support@kasumarketplace.com.ng"
    try:
        from django.conf import settings as django_settings

        support_email = getattr(
            django_settings, "SUPPORT_EMAIL", "support@kasumarketplace.com.ng"
        )
    except Exception:
        pass

    # show_login only applies to anonymous users on 403 / csrf pages.
    is_anonymous = True
    try:
        is_anonymous = not request.user.is_authenticated
    except Exception:
        is_anonymous = True
    show_login = bool(show_login) and is_anonymous

    context = {
        "status": status,
        # Title/message are module-level hardcoded constants (never user
        # input), so marking them safe keeps the copy verbatim in the HTML.
        "title": mark_safe(title),
        "message": mark_safe(message),
        "primary_url": primary_url,
        "primary_label": primary_label,
        "show_login": show_login,
        "login_url": login_url,
        "support_email": support_email,
        "home_url": home_url,
    }

    try:
        html = render_to_string(template, context)
        return HttpResponse(html, status=status, content_type="text/html")
    except Exception:
        logger.exception("error page %s failed to render", template)
        return _fallback_html(status, title, message)


# --------------------------------------------------------------------------
# Handler entry points
# --------------------------------------------------------------------------


def bad_request(request, exception=None):
    spec = COPY["400"]
    return _respond(request, TEMPLATES["400"], spec["status"], spec["title"], spec["message"])


def permission_denied(request, exception=None):
    spec = COPY["403"]
    return _respond(
        request,
        TEMPLATES["403"],
        spec["status"],
        spec["title"],
        spec["message"],
        show_login=True,
    )


def page_not_found(request, exception=None):
    spec = COPY["404"]
    return _respond(request, TEMPLATES["404"], spec["status"], spec["title"], spec["message"])


def server_error(request):
    spec = COPY["500"]
    return _respond(request, TEMPLATES["500"], spec["status"], spec["title"], spec["message"])


def csrf_failure(request, reason=""):
    spec = COPY["csrf"]
    # Never pass `reason` to the template or the JSON body.
    return _respond(
        request,
        TEMPLATES["csrf"],
        spec["status"],
        spec["title"],
        spec["message"],
        show_login=True,
    )


def preview(request, kind):
    """DEBUG-only visual preview route for the error pages."""
    kind = str(kind).lower()
    if kind not in COPY:
        raise Http404("No preview for that kind.")
    spec = COPY[kind]
    template = TEMPLATES[kind]
    status = spec["status"]
    if kind in ("403", "csrf"):
        return _respond(
            request, template, status, spec["title"], spec["message"], show_login=True
        )
    return _respond(request, template, status, spec["title"], spec["message"])
