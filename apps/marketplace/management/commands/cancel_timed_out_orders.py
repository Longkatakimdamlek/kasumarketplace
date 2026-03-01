"""
Management Command: cancel_timed_out_orders

Auto-cancels SubOrders where:
- status = PENDING_VENDOR
- vendor_deadline has passed

Run manually:
    python manage.py cancel_timed_out_orders

Schedule via cron (every 30 minutes):
    */30 * * * * cd /path/to/project && python manage.py cancel_timed_out_orders

Or Windows Task Scheduler for development.
"""

from django.core.management.base import BaseCommand
from django.utils import timezone
from apps.marketplace.models import SubOrder


class Command(BaseCommand):
    help = 'Auto-cancel SubOrders where vendor did not respond within 48 hours'

    def handle(self, *args, **options):
        # Find all expired pending orders
        expired = SubOrder.objects.filter(
            status='PENDING_VENDOR',
            vendor_deadline__lt=timezone.now(),
        ).select_related('main_order', 'store')

        count = expired.count()

        if count == 0:
            self.stdout.write(self.style.SUCCESS('No timed-out orders found.'))
            return

        self.stdout.write(f'Found {count} timed-out order(s). Processing...')

        success = 0
        failed = 0

        for sub in expired:
            try:
                # check_and_apply_timeout handles status + refund trigger
                sub.check_and_apply_timeout()
                self.stdout.write(
                    f'  ✓ SubOrder #{sub.pk} ({sub.store.store_name}) — cancelled'
                )
                success += 1
            except Exception as e:
                self.stdout.write(
                    self.style.ERROR(f'  ✗ SubOrder #{sub.pk} failed: {str(e)}')
                )
                failed += 1

        self.stdout.write(
            self.style.SUCCESS(
                f'\nDone. {success} cancelled, {failed} failed.'
            )
        )