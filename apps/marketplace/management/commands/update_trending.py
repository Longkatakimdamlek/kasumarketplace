"""
Management command: update_trending
Recalculates a weighted trending_score for every published Product.

Signals (Phase 8 — order system removed):
  - Wishlists within 28-day window, time-decayed (14-day half-life)
  - views_count (flat bonus — cumulative, no per-view timestamp)
  - average_rating * RATING_WEIGHT (flat bonus)

The time-decayed wishlist signal rewards recent popularity, while
views and rating provide a stable baseline score.

Usage:
    python manage.py update_trending
"""

import math
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.db.models import Sum, Count, F, Q, Value
from django.db.models.functions import Coalesce
from django.utils import timezone

from apps.vendors.models import Product, RATING_WEIGHT
from apps.marketplace.models import Wishlist

# Exponential decay half-life in days
HALF_LIFE_DAYS = 14
DECAY_LAMBDA = math.log(2) / HALF_LIFE_DAYS

# Rolling window — ignore wishlist activity older than this
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
        # 1. Wishlist signal — wishlists within window, time-decayed
        #    Each wishlist contributes a decay weight to its product.
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
        # 2. Fetch static signals for all published products
        # -------------------------------------------------------
        published_products = Product.objects.filter(
            status='published',
            store__is_published=True,
        ).values_list('id', 'views_count', 'average_rating')

        # -------------------------------------------------------
        # 3. Combine: time_decayed_wishlists + views + rating*weight
        #    Scale to integer (×100 for two decimal places of precision)
        # -------------------------------------------------------
        updates = []
        for pid, views_count, avg_rating in published_products:
            wc = wishlist_scores.get(pid, 0)
            vc = views_count or 0
            rc = float(avg_rating or 0) * RATING_WEIGHT
            raw = wc + vc + rc
            updates.append(Product(id=pid, trending_score=int(round(raw * 100))))

        # -------------------------------------------------------
        # 4. Bulk-update all published products
        # -------------------------------------------------------
        Product.objects.bulk_update(updates, ['trending_score'], batch_size=500)

        self.stdout.write(
            self.style.SUCCESS(
                f"Updated trending_score for {len(updates)} products "
                f"({len(wishlist_scores)} with wishlists in last {WINDOW_DAYS} days)."
            )
        )
