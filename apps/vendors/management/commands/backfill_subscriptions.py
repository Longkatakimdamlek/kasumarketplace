"""
Backfill Subscription records for existing VendorProfile records
that were created before the Subscription model existed.

Default: dry-run (reports what would be done).
Use --apply to write changes.
"""
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.vendors.models import VendorProfile, Subscription


class Command(BaseCommand):
    help = (
        'Create Subscription records for existing VendorProfile rows '
        'that do not yet have one. Default is dry-run; pass --apply to write.'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--apply',
            action='store_true',
            default=False,
            help='Actually create Subscription records (default is dry-run).',
        )
        parser.add_argument(
            '--trial-days',
            type=int,
            default=90,
            help='Free trial duration in days (default: 90).',
        )

    def handle(self, *args, **options):
        apply = options['apply']
        trial_days = options['trial_days']

        vendors_without = VendorProfile.objects.filter(subscription__isnull=True)
        count = vendors_without.count()

        if count == 0:
            self.stdout.write(self.style.SUCCESS('All VendorProfile rows already have a Subscription.'))
            return

        self.stdout.write(f'Found {count} VendorProfile(s) without a Subscription.')

        if not apply:
            self.stdout.write(self.style.WARNING('DRY RUN — no changes written. Re-run with --apply to create records.'))
            for vp in vendors_without.select_related('user').iterator():
                self.stdout.write(f'  would create Subscription for: {vp.full_name or vp.user.email} (pk={vp.pk}) [status=active]')
            return

        now = timezone.now()
        period_end = now + timedelta(days=trial_days)
        created = 0

        for vp in vendors_without.select_related('user').iterator():
            Subscription.objects.create(
                vendor=vp,
                status='active',
                period_end=period_end,
                trial_ends_at=None,
            )
            created += 1
            self.stdout.write(f'  [OK] Subscription created for: {vp.full_name or vp.user.email} (pk={vp.pk}) [status=active]')

        self.stdout.write(self.style.SUCCESS(f'\nDone — created {created} Subscription record(s).'))
