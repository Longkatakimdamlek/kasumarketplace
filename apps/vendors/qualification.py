"""
Free-plan first-product qualification (Phase 5).

Rules (spec):
  - Signup / store creation never starts a countdown.
  - The countdown starts only when the vendor creates their FIRST product
    (any status: a draft starts it too, drafts just never count).
  - 7 days from that first product to have 3 PUBLISHED products.  The third
    qualifying product starts the free trial immediately - day 7 is only the
    deadline, not the trigger.
  - Fewer than 3 after day 7 -> a second 7-day grace window (days 8-14).
    A third published product during grace still qualifies immediately.
  - Still fewer than 3 after 14 days -> qualification FAILED: the row becomes
    status 'expired' with qualification_status 'failed'.  Store and products
    stay public, contact stays hidden, product creation is blocked.
  - Paid plans (basic/premium) skip qualification entirely.

This module is import-safe next to apps.vendors.models: it only pulls the
model layer in lazily, inside the functions that need it.
"""

from datetime import timedelta

from django.db import transaction
from django.utils import timezone

# --------------------------------------------------------------------------
# Constants - single source of truth (Phase 6 reads these for its countdown)
# --------------------------------------------------------------------------
QUALIFICATION_REQUIRED_PRODUCTS = 3
QUALIFICATION_DAYS = 7
QUALIFICATION_GRACE_DAYS = 7
FREE_TRIAL_DAYS = 90


def _window_end(first_product_at, days):
    return first_product_at + timedelta(days=days)


def effective_state(sub, now):
    """
    Pure (no writes, no queries) classification of a subscription's
    qualification state at `now`.

      not_started -> no first product yet
      in_progress -> inside the first 7 days
      grace       -> inside days 8-14
      failed      -> past day 14

    Rows that are not status 'qualifying' simply report the stored label.
    """
    if sub.status != 'qualifying':
        return sub.qualification_status
    if sub.first_product_at is None:
        return 'not_started'
    if now <= _window_end(sub.first_product_at, QUALIFICATION_DAYS):
        return 'in_progress'
    if now <= _window_end(
        sub.first_product_at, QUALIFICATION_DAYS + QUALIFICATION_GRACE_DAYS
    ):
        return 'grace'
    return 'failed'


def sync_qualification(sub, now=None):
    """
    Bring a status='qualifying' row in line with the clock.

      - inside 7 days  -> stored label 'in_progress'
      - inside 14 days -> stored label 'grace'
      - past 14 days   -> stored label 'failed' AND status 'expired'

    Idempotent: returns True only when a write actually happened, and does
    nothing at all for rows whose status is not 'qualifying'.
    """
    if sub.status != 'qualifying':
        return False

    now = now or timezone.now()
    state = effective_state(sub, now)

    if state == 'failed':
        sub.status = 'expired'
        sub.qualification_status = 'failed'
        sub.save(update_fields=['status', 'qualification_status', 'updated_at'])
        return True

    if sub.qualification_status != state:
        sub.qualification_status = state
        sub.save(update_fields=['qualification_status', 'updated_at'])
        return True

    return False


def on_product_saved(product):
    """
    post_save hook for Product (Phase 5).  Recomputes the free-plan
    qualification for the product's vendor.

    Never touches a row whose status is not 'qualifying': paid, trial,
    expired and grandfathered legacy rows are left alone and their products
    are not counted.  Deleting products never resets first_product_at.
    """
    from .models import Subscription

    vendor = getattr(product, 'vendor', None)
    if vendor is None:
        return False

    now = timezone.now()

    with transaction.atomic():
        try:
            sub = Subscription.objects.select_for_update().get(vendor=vendor)
        except Subscription.DoesNotExist:
            return False

        if sub.status != 'qualifying':
            return False

        changed = False

        # 1st product starts the countdown, whatever its status is.
        if sub.first_product_at is None:
            sub.first_product_at = getattr(product, 'created_at', None) or now
            sub.qualification_status = 'in_progress'
            sub.save(
                update_fields=['first_product_at', 'qualification_status', 'updated_at']
            )
            changed = True

        # Past the 14-day window: fail, never qualify.
        if now > _window_end(
            sub.first_product_at, QUALIFICATION_DAYS + QUALIFICATION_GRACE_DAYS
        ):
            return sync_qualification(sub, now=now) or changed

        published = vendor.products.filter(status='published').count()
        if published >= QUALIFICATION_REQUIRED_PRODUCTS:
            sub.status = 'trial'
            sub.trial_ends_at = now + timedelta(days=FREE_TRIAL_DAYS)
            sub.qualification_status = 'qualified'
            sub.qualified_at = now
            # plan stays 'free'; grace_ends_at / period_end are left alone.
            sub.save(update_fields=[
                'status', 'trial_ends_at', 'qualification_status',
                'qualified_at', 'updated_at',
            ])
            return True

        return sync_qualification(sub, now=now) or changed
