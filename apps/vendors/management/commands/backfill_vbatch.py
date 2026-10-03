"""
Backfill / grandfather the V-Batch badge (Phase 8).

Default: dry-run (reports what would be done).  Use --apply to write.

Rules (a vendor matching rule 1 is awarded 'premium' first, so rule 2 never
overwrites it - award_vbatch() is one-way anyway):
  rule 1: currently on an active Premium plan   -> source 'premium'
  rule 2: successful BVN verification on record -> source 'legacy'

Rule 2 deliberately keys on ``bank_status == 'verified'`` (always written
together with ``bvn_verified_at`` by the BVN flow) and NOT on
``verification_status``: the BVN flow never touches verification_status
(that one is admin-managed), and a VerificationAttempt can be 'success'
while bank_status is still 'failed' for the 75-90 confidence band.  So
bank_status is the one field that means "the BVN check passed".

Vendors that qualify for neither are never touched.  Awarding is silent:
this command passes notify=False, so no in-app notification and no email is
produced for grandfathered vendors.  Re-running is a no-op because
award_vbatch() only ever awards a vendor that does not have the badge yet.

This is a separate command rather than an extension of
backfill_subscriptions so that the Phase 5 command keeps its exact output
and its "sends no notifications" contract untouched.
"""
from django.core.management.base import BaseCommand

from apps.vendors.models import Subscription, VendorProfile
from apps.vendors.vbatch import award_vbatch


class Command(BaseCommand):
    help = (
        'Grandfather the V-Batch badge for legacy vendors. '
        'Default is dry-run; pass --apply to write. Sends no notifications.'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--apply',
            action='store_true',
            default=False,
            help='Actually write changes (default is dry-run).',
        )

    def handle(self, *args, **options):
        apply = options['apply']

        premium = list(
            Subscription.objects.filter(plan='premium', status='active')
            .select_related('vendor__user')
            .order_by('vendor_id')
        )
        premium_pks = [sub.vendor_id for sub in premium]

        bvn = list(
            VendorProfile.objects.filter(bank_status='verified')
            .exclude(pk__in=premium_pks)
            .select_related('user')
            .order_by('pk')
        )

        rules = [
            ('rule 1', "active Premium plan -> source 'premium'",
             [sub.vendor for sub in premium], 'premium'),
            ('rule 2', "BVN verified on record -> source 'legacy'",
             bvn, 'legacy'),
        ]

        self.stdout.write(
            'V-Batch backfill' + (' (DRY RUN)' if not apply else ' (APPLY)')
        )

        to_award = 0
        already = 0
        for name, description, vendors, source in rules:
            pending = [v for v in vendors if not v.has_vbatch]
            done = len(vendors) - len(pending)
            to_award += len(pending)
            already += done
            self.stdout.write(
                f'  {name}: {description}: {len(vendors)} candidate(s), '
                f'{done} already earned, {len(pending)} to award'
            )

        self.write_comparison(premium_pks, bvn)

        if not apply:
            self.stdout.write(
                'DRY RUN - no changes written. Re-run with --apply to write.'
            )
            for name, _description, vendors, source in rules:
                for vendor in vendors:
                    if vendor.has_vbatch:
                        self.stdout.write(
                            f'  {name} skip pk={vendor.pk} '
                            f'vendor={vendor.user.email} [already earned]'
                        )
                    else:
                        self.stdout.write(
                            f'  {name} would award pk={vendor.pk} '
                            f'vendor={vendor.user.email} [source={source}]'
                        )
            self.stdout.write(
                f'Done - would award {to_award}, already earned {already}.'
            )
            return

        awarded = 0
        for name, _description, vendors, source in rules:
            for vendor in vendors:
                if award_vbatch(vendor, source, notify=False):
                    awarded += 1
                    self.stdout.write(
                        f'  {name} awarded pk={vendor.pk} '
                        f'vendor={vendor.user.email} [source={source}]'
                    )

        self.stdout.write(
            f'Done - awarded {awarded}, already earned {already}.'
        )

    def write_comparison(self, premium_pks, bvn):
        """
        Comparison block (Phase 8B): every approved vendor, with a count and
        a per-row pk / email / verification_status line, marking which ones
        this backfill leaves without the badge.  The gap rows are the ones an
        operator should look at: approved, but no active Premium plan and no
        verified BVN on record.
        """
        approved = list(
            VendorProfile.objects.filter(verification_status='approved')
            .select_related('user')
            .order_by('pk')
        )

        earning_pks = set(premium_pks) | {vendor.pk for vendor in bvn}
        for vendor in approved:
            if vendor.has_vbatch:
                earning_pks.add(vendor.pk)

        gap = [v for v in approved if v.pk not in earning_pks]
        self.stdout.write(
            f'  comparison: {len(approved)} approved vendor(s) - '
            f'{len(approved) - len(gap)} receive the V-Batch, '
            f'{len(gap)} do not'
        )
        for vendor in approved:
            marker = (
                'receives' if vendor.pk in earning_pks else 'skips'
            )
            self.stdout.write(
                f'    {marker:<9} pk={vendor.pk} '
                f'vendor={vendor.user.email} '
                f'[verification_status={vendor.verification_status}]'
            )
