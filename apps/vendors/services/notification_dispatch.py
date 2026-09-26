"""
Unified notification dispatch — single entry point for creating
in-app notifications and optionally sending email.

All future trigger code should call ``create_notification()`` instead
of ``Notification.objects.create()`` directly.  This ensures every
notification can optionally produce an email without each caller
needing to know the email infrastructure.
"""

import logging
from datetime import timezone as tz

from django.conf import settings
from django.utils import timezone

logger = logging.getLogger(__name__)

NOTIFICATION_EMAIL_TEMPLATE = 'vendors/emails/generic_notification.html'


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
    True, dispatch an email to the user via the existing EmailService.

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

    # ── 3. Dispatch email (best-effort, never blocks in-app) ───────
    if not is_in_app_only and user and user.email:
        try:
            _send_notification_email(user, title, message, link)
            notif.email_sent_at = timezone.now()
            notif.save(update_fields=['email_sent_at'])
        except Exception as exc:
            # Email failure must never roll back the in-app notification.
            logger.error(
                'Notification email dispatch failed for user %s: %s',
                user.pk,
                exc,
                exc_info=True,
            )

    return notif


def _send_notification_email(user, title, message, link=''):
    """
    Render and send the generic notification email via the existing
    EmailService / ZeptoMail infrastructure.
    """
    from django.core.mail import EmailMultiAlternatives
    from django.template.loader import render_to_string
    from django.utils.html import strip_tags

    base_url = getattr(settings, 'SITE_URL', 'https://kasumarketplace.com.ng')
    full_url = f'{base_url}{link}' if link else base_url

    context = {
        'user': user,
        'title': title,
        'message': message,
        'link': full_url,
        'base_url': base_url,
    }

    html_body = render_to_string(NOTIFICATION_EMAIL_TEMPLATE, context)
    text_body = strip_tags(html_body)

    email = EmailMultiAlternatives(
        subject=title,
        body=text_body,
        from_email=getattr(settings, 'DEFAULT_FROM_EMAIL', 'no-reply@kasumarketplace.com.ng'),
        to=[user.email],
    )
    email.attach_alternative(html_body, 'text/html')
    email.send(fail_silently=False)
