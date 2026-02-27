from __future__ import annotations

from typing import Iterable

from django.conf import settings
from django.core.mail import send_mail


def send_kasu_email(subject: str, message: str, recipient_list: Iterable[str]) -> int:
    """
    Send a plain-text email using Django's configured email backend.

    - Uses `settings.DEFAULT_FROM_EMAIL` as the sender
    - Raises exceptions if sending fails (`fail_silently=False`)
    - Returns the number of messages sent (per Django's `send_mail`)
    """
    if not subject or not isinstance(subject, str):
        raise ValueError("subject must be a non-empty string")

    if message is None or not isinstance(message, str):
        raise ValueError("message must be a string")

    if recipient_list is None:
        raise ValueError("recipient_list must be provided")

    recipients = [r.strip() for r in recipient_list if str(r).strip()]
    if not recipients:
        raise ValueError("recipient_list must contain at least one email address")

    sent_count = send_mail(
        subject=subject,
        message=message,
        from_email=settings.DEFAULT_FROM_EMAIL,
        recipient_list=recipients,
        fail_silently=False,
    )

    if sent_count < 1:
        raise RuntimeError("Email was not sent (send_mail returned 0).")

    return sent_count

