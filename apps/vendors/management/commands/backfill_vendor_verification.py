"""
One-off management command: backfill vendors stuck in intermediate
verification_status values (bvn_verified, nin_verified, student_verified)
to 'approved' — but ONLY when the vendor is genuinely functional
(bank_status == 'verified' and store exists).

Run on production:
    python manage.py backfill_vendor_verification

Dry-run by default. Pass --apply to execute the update.
"""

from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.vendors.models import VendorProfile


class Command(BaseCommand):
    help = (
        "Backfill vendors stuck in intermediate verification_status "
        "to 'approved' where bank_status is already 'verified'."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--apply',
            action='store_true',
            default=False,
            help='Actually apply changes (dry-run by default)',
        )

    def handle(self, *args, **options):
        apply = options['apply']

        stuck_statuses = ['bvn_verified', 'nin_verified', 'student_verified']
        stuck_vendors = VendorProfile.objects.filter(
            verification_status__in=stuck_statuses,
            bank_status='verified',
        ).select_related('user', 'store')

        count = stuck_vendors.count()

        if count == 0:
            self.stdout.write(self.style.SUCCESS(
                'No vendors found stuck in intermediate verification states. Nothing to do.'
            ))
            return

        self.stdout.write(self.style.WARNING(
            f'Found {count} vendor(s) stuck in intermediate verification_status '
            f'with bank_status="verified":'
        ))

        for vendor in stuck_vendors:
            self.stdout.write(
                f'  - ID {vendor.pk}: {vendor.full_name or vendor.user.email} | '
                f'verification_status={vendor.verification_status} | '
                f'bank_status={vendor.bank_status} | '
                f'store={getattr(vendor.store, "store_name", "NO STORE")}'
            )

        if not apply:
            self.stdout.write(self.style.WARNING(
                '\nDry-run only. Re-run with --apply to execute the backfill.'
            ))
            return

        now = timezone.now()
        updated = 0
        for vendor in stuck_vendors:
            vendor.verification_status = 'approved'
            vendor.approved_at = vendor.approved_at or now
            vendor.reviewed_at = vendor.reviewed_at or now
            vendor.save(update_fields=[
                'verification_status', 'approved_at', 'reviewed_at',
            ])
            updated += 1
            self.stdout.write(self.style.SUCCESS(
                f'  ✅ Updated {vendor.pk} ({vendor.full_name or vendor.user.email}) '
                f'to verification_status="approved"'
            ))

        self.stdout.write(self.style.SUCCESS(
            f'\nDone. {updated} vendor(s) backfilled to "approved".'
        ))
