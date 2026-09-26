"""
Periodic command to expire subscriptions whose grace period has ended.

Run via cron or a task scheduler.  Typical schedule: daily.

    python manage.py check_subscription_status
"""
from django.core.management.base import BaseCommand

from apps.vendors.services.subscription_service import subscription_service


class Command(BaseCommand):
    help = 'Expire subscriptions whose grace period has ended (run daily via cron).'

    def handle(self, *args, **options):
        count = subscription_service.expire_grace_periods()
        if count:
            self.stdout.write(self.style.SUCCESS(f'✅ Expired {count} subscription(s).'))
        else:
            self.stdout.write('No subscriptions to expire.')
