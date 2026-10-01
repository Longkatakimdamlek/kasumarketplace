"""
Periodic command to expire subscriptions whose grace period has ended.

Also syncs free-plan qualification labels for status='qualifying' rows
(Phase 5): in_progress / grace inside the window, failed + expired past
day 14.  Idempotent.

Run via cron or a task scheduler.  Typical schedule: daily.

    python manage.py check_subscription_status
"""
from django.core.management.base import BaseCommand

from apps.vendors.models import Subscription
from apps.vendors.qualification import sync_qualification
from apps.vendors.services.subscription_service import subscription_service


class Command(BaseCommand):
    help = 'Expire subscriptions whose grace period has ended (run daily via cron).'

    def handle(self, *args, **options):
        count = subscription_service.expire_grace_periods()
        if count:
            self.stdout.write(self.style.SUCCESS(f'✅ Expired {count} subscription(s).'))
        else:
            self.stdout.write('No subscriptions to expire.')

        synced = 0
        failed = 0
        for sub in Subscription.objects.filter(status='qualifying'):
            if sync_qualification(sub):
                synced += 1
                if sub.qualification_status == 'failed':
                    failed += 1
        self.stdout.write(f'qualification synced: {synced}, failed: {failed}')
