"""
Unified notification dispatch — single entry point for creating
in-app notifications and optionally sending email.

All future trigger code should call ``create_notification()`` instead
of ``Notification.objects.create()`` directly.  This ensures every
notification can optionally produce an email without each caller
needing to know the email infrastructure.
"""

import logging
import threading

import requests
from django.conf import settings
from django.utils import timezone

logger = logging.getLogger(__name__)

NOTIFICATION_EMAIL_TEMPLATE = 'vendors/emails/generic_notification.html'
ZEPTO_API_URL = 'https://api.zeptomail.com/v1.1/email'

def create_notification(
    user,
    notification_type,
    title,
    message,
    link='',
    in_app_only=False,
    vendor=None,
):
    """
    Create an in-app Notification record and, unless ``in_app_only`` is
    True, dispatch an email to the user via ZeptoMail in the background.

    Args:
        user:               The recipient (User instance).  Required.
        notification_type:  One of the Notification.TYPE_CHOICES values.
        title:              Short notification headline.
        message:            Body text (plain-text, shown in-app and in email).
        link:               Optional relative URL for the notification.
        in_app_only:        If True, skip the email dispatch.
        vendor:             Optional VendorProfile — set on legacy FK for
                            backward-compat with vendor-scoped queries.

    Returns:
        The created Notification instance.
    """
    from apps.vendors.models import Notification

    # ── 1. Resolve channel ──────────────────────────────────────────
    is_in_app_only = in_app_only
    channel = 'in_app' if is_in_app_only else 'both'

    # ── 2. Create the in-app record ────────────────────────────────
    notif = Notification.objects.create(
        user=user,
        vendor=vendor,
        notification_type=notification_type,
        title=title,
        message=message,
        link=link,
        channel=channel,
        is_in_app_only=is_in_app_only,
    )

    # ── 3. Dispatch email (background in production, inline in tests) ─
    if not is_in_app_only and user and user.email:
        if getattr(settings, 'NOTIFICATION_EMAIL_ASYNC', True):
            threading.Thread(
                target=_dispatch_email,
                args=(notif.pk, user, title, message, link, True),
                daemon=True,
            ).start()
        else:
            _dispatch_email(notif.pk, user, title, message, link)

    return notif


def _dispatch_email(notif_id, user, title, message, link='', in_thread=False):
    """Failures are logged, never raised."""
    from django.db import close_old_connections
    from apps.vendors.models import Notification

    try:
        _send_notification_email(user, title, message, link)
        Notification.objects.filter(pk=notif_id).update(email_sent_at=timezone.now())
    except Exception as exc:
        logger.error(
            'Notification email dispatch failed for user %s: %s',
            user.pk, exc, exc_info=True,
        )
    finally:
        if in_thread:
            close_old_connections()


def _send_notification_email(user, title, message, link=''):
    """ZeptoMail HTTPS API in production; Django mail backend otherwise (tests)."""
    from django.template.loader import render_to_string
    from django.utils.html import strip_tags

    base_url = getattr(settings, 'SITE_URL', 'https://kasumarketplace.com.ng')
    full_url = f'{base_url}{link}' if link else base_url
    from_email = getattr(settings, 'DEFAULT_FROM_EMAIL', 'no-reply@kasumarketplace.com.ng')

    html_body = render_to_string(NOTIFICATION_EMAIL_TEMPLATE, {
        'user': user,
        'title': title,
        'message': message,
        'link': full_url,
        'base_url': base_url,
    })
    text_body = strip_tags(html_body)

    # Non-SMTP backend (locmem in tests, console in dev): use Django mail.
    if settings.EMAIL_BACKEND != 'django.core.mail.backends.smtp.EmailBackend':
        from django.core.mail import EmailMultiAlternatives
        msg = EmailMultiAlternatives(
            subject=title, body=text_body, from_email=from_email, to=[user.email],
        )
        msg.attach_alternative(html_body, 'text/html')
        msg.send(fail_silently=False)
        return

    token = getattr(settings, 'ZEPTO_API_TOKEN', '')
    if not token:
        raise RuntimeError('ZEPTO_API_TOKEN is not configured')

    payload = {
        'from': {'address': from_email, 'name': 'KasuMarketplace'},
        'to': [{'email_address': {
            'address': user.email,
            'name': user.get_full_name() or user.email,
        }}],
        'subject': title,
        'htmlbody': html_body,
        'textbody': text_body,
    }

    resp = requests.post(
        ZEPTO_API_URL,
        json=payload,
        headers={
            'Authorization': token,
            'Accept': 'application/json',
            'Content-Type': 'application/json',
        },
        timeout=10,
    )
    resp.raise_for_status()
