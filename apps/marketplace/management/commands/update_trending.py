"""
Management command: update_trending
Recalculates the trailing-7-day trending_score for every published Product.
Run manually or via a weekly cron job / scheduled task.

Usage:
    python manage.py update_trending
"""

from datetime import timedelta

from django.core.management.base import BaseCommand
from django.db.models import Sum
from django.utils import timezone

from apps.vendors.models import Product
from apps.marketplace.models import SubOrderItem


class Command(BaseCommand):
    help = "Refresh trending_score (units sold in the last 7 days) for all published products."

    def handle(self, *args, **options):
        week_ago = timezone.now() - timedelta(days=7)

        # Products with confirmed sales in the trailing 7 days
        trending = (
            SubOrderItem.objects.filter(
                sub_order__status='CONFIRMED',
                sub_order__created_at__gte=week_ago,
                product__status='published',
                product__store__is_published=True,
            )
            .values('product_id')
            .annotate(total=Sum('quantity'))
            .order_by()
        )

        score_map = {row['product_id']: row['total'] for row in trending}

        # Bulk-update all published products
        published_ids = list(
            Product.objects.filter(
                status='published',
                store__is_published=True,
            ).values_list('id', flat=True)
        )

        updated = 0
        for product_id in published_ids:
            new_score = score_map.get(product_id, 0)
            Product.objects.filter(id=product_id).update(trending_score=new_score)
            updated += 1

        self.stdout.write(
            self.style.SUCCESS(
                f"Updated trending_score for {updated} products "
                f"({len(score_map)} with sales this week)."
            )
        )
