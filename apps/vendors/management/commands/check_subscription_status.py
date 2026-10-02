"""
Periodic command to expire subscriptions whose grace period has ended.

Also syncs free-plan qualification labels for status='qualifying' rows
(Phase 5): in_progress / grace inside the window, failed + expired past
day 14.  Idempotent.

Phase 7 adds the daily notification pass (kinds 2-6) on top of the same
sync.  Nothing was removed: without the new flags this command behaves
exactly as before, plus the notification summary line.

    python manage.py check_subscription_status
    python manage.py check_subscription_status --dry-run
    python manage.py check_subscription_status --no-notify
    python manage.py check_subscription_status --lookback-days 3

Run via cron or a task scheduler.  Typical schedule: daily.

  --dry-run        print who WOULD be notified; writes nothing, sends nothing
                   (the grace expiry and qualification sync are skipped too)
  --no-notify      old behaviour only (expiry + qualification sync)
  --lookback-days  only notify kinds 2/3/5/6 whose deadline passed within
                   the last N days (default 3), so the first production run
                   does not email every long-expired vendor
"""
from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.vendors.models import Subscription
from apps.vendors.qualification import sync_qualification
from apps.vendors.services.subscription_notifications import (
    LOOKBACK_DEFAULT_DAYS,
    format_dry_run_summary,
    format_summary,
    run_subscription_notifications,
)
from apps.vendors.services.subscription_service import subscription_service


class Command(BaseCommand):
    help = 'Expire subscriptions whose grace period has ended (run daily via cron).'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            default=False,
            help='Report what would be notified; write and send nothing.',
        )
        parser.add_argument(
            '--no-notify',
            action='store_true',
            default=False,
            help='Skip the notification pass (previous behaviour only).',
        )
        parser.add_argument(
            '--lookback-days',
            type=int,
            default=LOOKBACK_DEFAULT_DAYS,
            help=(
                'Only notify kinds whose deadline passed within the last N '
                f'days (default {LOOKBACK_DEFAULT_DAYS}).'
            ),
        )

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        no_notify = options['no_notify']
        lookback_days = options['lookback_days']
        now = timezone.now()

        # ---- 1. grace expiry (writes) ---------------------------------
        if dry_run:
            self.stdout.write(
                '[dry-run] grace expiry and qualification sync skipped (no writes).'
            )
        else:
            count = subscription_service.expire_grace_periods()
            if count:
                self.stdout.write(self.style.SUCCESS(
                    f'Expired {count} subscription(s).'
                ))
            else:
                self.stdout.write('No subscriptions to expire.')

        # ---- 2. qualification label sync (writes) ----------------------
        synced = 0
        failed = 0
        if not dry_run:
            for sub in Subscription.objects.filter(status='qualifying'):
                if sync_qualification(sub):
                    synced += 1
                    if sub.qualification_status == 'failed':
                        failed += 1
            self.stdout.write(f'qualification synced: {synced}, failed: {failed}')

        # ---- 3. notification pass (Phase 7) ----------------------------
        if no_notify:
            self.stdout.write('notifications: skipped (--no-notify)')
            return

        summary = run_subscription_notifications(
            now=now,
            lookback_days=lookback_days,
            dry_run=dry_run,
            stdout=self.stdout,
        )
        if dry_run:
            self.stdout.write(format_dry_run_summary(summary))
        else:
            self.stdout.write(format_summary(summary))
