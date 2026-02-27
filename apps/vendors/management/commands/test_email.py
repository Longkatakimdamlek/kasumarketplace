from __future__ import annotations

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from core.utils.email_service import send_kasu_email


class Command(BaseCommand):
    help = "Send a test email using the configured SMTP backend (ZeptoMail)."

    def add_arguments(self, parser):
        parser.add_argument("to", help="Recipient email address")
        parser.add_argument(
            "--subject",
            default="KasuMarketplace test email",
            help="Email subject",
        )
        parser.add_argument(
            "--message",
            default="This is a test email sent from KasuMarketplace using ZeptoMail SMTP.",
            help="Plain-text email message body",
        )

    def handle(self, *args, **options):
        if not settings.EMAIL_HOST_PASSWORD:
            raise CommandError(
                "EMAIL_HOST_PASSWORD is not set. "
                "Set it in your environment (recommended) or in your .env file."
            )

        to_email = options["to"]
        subject = options["subject"]
        message = options["message"]

        try:
            send_kasu_email(subject=subject, message=message, recipient_list=[to_email])
        except Exception as exc:
            raise CommandError(f"Email send failed: {exc}") from exc

        self.stdout.write(self.style.SUCCESS(f"Test email sent to {to_email}"))

