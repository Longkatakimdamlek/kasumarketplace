"""
Management command: update_trending
Recalculates a weighted trending_score for every published Product.

Signals used (all within a 28-day rolling window):
  - Purchases (confirmed SubOrderItems): 60% weight
  - Wishlists: 40% weight

Each signal uses exponential time decay with a 14-day half-life,
so recent activity counts more than older activity.

Usage:
    python manage.py update_trending
"""

import math
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.db.models import Sum
from django.utils import timezone

from apps.vendors.models import Product
from apps.marketplace.models import SubOrderItem, Wishlist

# Signal weights (must sum to 1.0)
WEIGHT_PURCHASES = 0.60
WEIGHT_WISHLISTS = 0.40

# Exponential decay half-life in days
# A signal from 14 days ago counts as 50% of its original weight.
HALF_LIFE_DAYS = 14
DECAY_LAMBDA = math.log(2) / HALF_LIFE_DAYS

# Rolling window — ignore activity older than this
WINDOW_DAYS = 28


def _decay_weight(days_ago):
    """Exponential decay: returns a multiplier between 0.0 and 1.0."""
    return math.exp(-DECAY_LAMBDA * days_ago)


class Command(BaseCommand):
    help = "Refresh trending_score (weighted, time-decayed) for all published products."

    def handle(self, *args, **options):
        now = timezone.now()
        window_start = now - timedelta(days=WINDOW_DAYS)

        # -------------------------------------------------------
        # 1. Purchase signal — confirmed SubOrderItems, time-decayed
        # -------------------------------------------------------
        purchase_items = SubOrderItem.objects.filter(
            sub_order__status='CONFIRMED',
            sub_order__created_at__gte=window_start,
            product__status='published',
            product__store__is_published=True,
        ).values('product_id', 'sub_order__created_at')

        purchase_scores = {}
        for row in purchase_items:
            pid = row['product_id']
            created = row['sub_order__created_at']
            days_ago = (now - created).total_seconds() / 86400
            purchase_scores[pid] = purchase_scores.get(pid, 0) + _decay_weight(days_ago)

        # -------------------------------------------------------
        # 2. Wishlist signal — wishlists within window, time-decayed
        # -------------------------------------------------------
        wishlist_items = Wishlist.objects.filter(
            created_at__gte=window_start,
            product__status='published',
            product__store__is_published=True,
        ).values('product_id', 'created_at')

        wishlist_scores = {}
        for row in wishlist_items:
            pid = row['product_id']
            created = row['created_at']
            days_ago = (now - created).total_seconds() / 86400
            wishlist_scores[pid] = wishlist_scores.get(pid, 0) + _decay_weight(days_ago)

        # -------------------------------------------------------
        # 3. Combine weighted scores
        # -------------------------------------------------------
        all_product_ids = set(purchase_scores) | set(wishlist_scores)

        # Also include all published products (score 0 if no activity)
        published_ids = list(
            Product.objects.filter(
                status='published',
                store__is_published=True,
            ).values_list('id', flat=True)
        )
        all_product_ids.update(published_ids)

        score_map = {}
        for pid in all_product_ids:
            raw = (
                WEIGHT_PURCHASES * purchase_scores.get(pid, 0) +
                WEIGHT_WISHLISTS * wishlist_scores.get(pid, 0)
            )
            # Scale to integer (multiply by 100 for two decimal places of precision)
            score_map[pid] = int(round(raw * 100))

        # -------------------------------------------------------
        # 4. Bulk-update all published products
        # -------------------------------------------------------
        updated = 0
        for product_id in published_ids:
            new_score = score_map.get(product_id, 0)
            Product.objects.filter(id=product_id).update(trending_score=new_score)
            updated += 1

        self.stdout.write(
            self.style.SUCCESS(
                f"Updated trending_score for {updated} products "
                f"({len(purchase_scores)} with purchases, "
                f"{len(wishlist_scores)} with wishlists in last {WINDOW_DAYS} days)."
            )
        )
