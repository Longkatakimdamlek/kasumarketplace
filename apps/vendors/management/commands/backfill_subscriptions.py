"""
Backfill / grandfather Subscription records for legacy vendors (Phase 5).

Default: dry-run (reports what would be done).  Use --apply to write.

Categories:
  (1) VendorProfile with NO Subscription row -> grandfathered row:
      status='trial', plan='free', qualification_status='qualified',
      qualified_at=now, trial_ends_at=now+FREE_TRIAL_DAYS,
      first_product_at = MIN(product created_at) or None.
  (2) status='trial' AND qualification_status='not_started' (legacy signup
      trials) -> grandfather: qualification_status='qualified',
      qualified_at=now, trial_ends_at=now+FREE_TRIAL_DAYS (fresh),
      first_product_at = MIN(product created_at) when currently None.
  (3) status='active', plan='free' and an EMPTY paystack_subscription_code
      (legacy "active" rows created by the old backfill) -> convert:
      status='trial', trial_ends_at=now+FREE_TRIAL_DAYS, period_end=None,
      qualification_status='qualified', qualified_at=now.

Never touched: rows with a non-empty paystack_subscription_code, rows with
status 'qualifying' / 'past_due' / 'cancelled' / 'expired', and rows already
qualified / skipped / failed.

Writes use Subscription.objects.create for new rows (category 1) and
QuerySet.update() for existing rows (categories 2 and 3) so no signal - and
therefore no buyer reactivation notification - can fire.
"""
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from apps.vendors.models import VendorProfile, Subscription
from apps.vendors.qualification import FREE_TRIAL_DAYS

NEVER_LABELS = ('qualified', 'skipped', 'failed')


def no_paystack_code():
    return Q(paystack_subscription_code='') | Q(paystack_subscription_code__isnull=True)


class Command(BaseCommand):
    help = (
        'Grandfather legacy subscriptions for Phase 5 qualification. '
        'Default is dry-run; pass --apply to write.'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--apply',
            action='store_true',
            default=False,
            help='Actually write changes (default is dry-run).',
        )
        parser.add_argument(
            '--trial-days',
            type=int,
            default=FREE_TRIAL_DAYS,
            help=f'Free trial duration in days (default: {FREE_TRIAL_DAYS}).',
        )

    def handle(self, *args, **options):
        apply = options['apply']
        trial_days = options['trial_days']
        now = timezone.now()
        trial_ends_at = now + timedelta(days=trial_days)

        cat1 = list(
            VendorProfile.objects.filter(subscription__isnull=True)
            .select_related('user')
            .order_by('pk')
        )
        cat2 = list(
            Subscription.objects.filter(status='trial', qualification_status='not_started')
            .filter(no_paystack_code())
            .select_related('vendor__user')
            .order_by('pk')
        )
        cat3 = list(
            Subscription.objects.filter(status='active', plan='free')
            .filter(no_paystack_code())
            .exclude(qualification_status__in=NEVER_LABELS)
            .select_related('vendor__user')
            .order_by('pk')
        )

        if not cat1 and not cat2 and not cat3:
            self.stdout.write(
                self.style.SUCCESS('Nothing to backfill - all rows already grandfathered.')
            )
            return

        self.stdout.write(
            f'Found {len(cat1)} vendor(s) without a Subscription, '
            f'{len(cat2)} legacy signup trial(s), {len(cat3)} legacy free active row(s).'
        )
        self.stdout.write(
            '  category 1: missing Subscription rows -> create grandfathered trial'
        )
        self.stdout.write(
            '  category 2: legacy signup trials -> fresh grandfathered trial'
        )
        self.stdout.write(
            '  category 3: legacy free "active" rows -> convert to grandfathered trial'
        )

        if not apply:
            self.stdout.write(
                'DRY RUN - no changes written. Re-run with --apply to write.'
            )
            for vp in cat1:
                self.stdout.write(
                    f'  [1] would create pk=NEW vendor={vp.user.email} '
                    f'(vendor_pk={vp.pk}) [status=trial]'
                )
            for sub in cat2:
                self.stdout.write(
                    f'  [2] would grandfather pk={sub.pk} '
                    f'vendor={sub.vendor.user.email} [trial_ends_at={trial_ends_at.isoformat()}]'
                )
            for sub in cat3:
                self.stdout.write(
                    f'  [3] would convert pk={sub.pk} vendor={sub.vendor.user.email} '
                    f'[status=trial, period_end=None]'
                )
            return

        created = 0
        grandfathered = 0
        converted = 0

        with transaction.atomic():
            for vp in cat1:
                Subscription.objects.create(
                    vendor=vp,
                    status='trial',
                    plan='free',
                    qualification_status='qualified',
                    qualified_at=now,
                    trial_ends_at=trial_ends_at,
                    first_product_at=self.first_product_at(vp),
                )
                created += 1
                self.stdout.write(
                    f'  [1 OK] created grandfathered trial for {vp.user.email} (vendor_pk={vp.pk})'
                )

            for sub in cat2:
                fp = sub.first_product_at or self.first_product_at(sub.vendor)
                Subscription.objects.filter(pk=sub.pk).update(
                    qualification_status='qualified',
                    qualified_at=now,
                    trial_ends_at=trial_ends_at,
                    first_product_at=fp,
                )
                grandfathered += 1
                self.stdout.write(
                    f'  [2 OK] grandfathered pk={sub.pk} vendor={sub.vendor.user.email}'
                )

            for sub in cat3:
                Subscription.objects.filter(pk=sub.pk).update(
                    status='trial',
                    trial_ends_at=trial_ends_at,
                    period_end=None,
                    qualification_status='qualified',
                    qualified_at=now,
                )
                converted += 1
                self.stdout.write(
                    f'  [3 OK] converted pk={sub.pk} vendor={sub.vendor.user.email} to trial'
                )

        self.stdout.write(
            self.style.SUCCESS(
                f'Done - created {created}, grandfathered {grandfathered}, '
                f'converted {converted}.'
            )
        )

    def first_product_at(self, vendor):
        """MIN(created_at) over the vendor's products, or None."""
        return (
            vendor.products.order_by('created_at')
            .values_list('created_at', flat=True)
            .first()
        )
