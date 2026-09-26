"""
Email Service
Sends transactional emails for KasuMarketplace.

Uses Django's built-in send_mail.
Configure in settings.py:
    EMAIL_BACKEND = 'django.core.mail.backends.smtp.EmailBackend'
    EMAIL_HOST = 'smtp.gmail.com'
    EMAIL_PORT = 587
    EMAIL_USE_TLS = True
    EMAIL_HOST_USER = 'your@email.com'
    EMAIL_HOST_PASSWORD = 'your_app_password'
    DEFAULT_FROM_EMAIL = 'KasuMarketplace <noreply@kasumarketplace.com.ng>'
"""

import logging
from django.core.mail import send_mail
from django.conf import settings

logger = logging.getLogger(__name__)

FROM_EMAIL = getattr(settings, 'DEFAULT_FROM_EMAIL', 'KasuMarketplace <noreply@kasumarketplace.com.ng>')
ADMIN_EMAIL = getattr(settings, 'ADMIN_EMAIL', settings.ADMINS[0][1] if settings.ADMINS else None)


def _send(subject, message, recipient_list, html_message=None):
    """
    Safe wrapper around send_mail.
    Logs errors but never raises — email failure must not break the app.
    """
    try:
        send_mail(
            subject=subject,
            message=message,
            from_email=FROM_EMAIL,
            recipient_list=recipient_list,
            html_message=html_message,
            fail_silently=False,
        )
        logger.info(f'Email sent: "{subject}" → {recipient_list}')
    except Exception as e:
        logger.error(f'Email failed: "{subject}" → {recipient_list}: {str(e)}')
