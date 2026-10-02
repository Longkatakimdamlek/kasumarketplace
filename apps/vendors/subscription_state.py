"""
Subscription state descriptor (Phase 6).

One shared, read-only place that turns a vendor's Subscription (plus the
vendor's availability) into display-ready copy for the dashboard, the
Product Management page, the verification center and the product-creation
prompt.

Ten states, verbatim copy from the Phase 6 spec:

  1  qualifying_not_started       (info)          "Start your free trial"
  2  qualifying_in_progress       (info)          "{done} of 3" countdown
  3  qualifying_grace             (warning)       grace countdown
  4  trial_active                 (success/warn)  "{days} day(s) left"
  5  paid_active                  (success/warn)  "{plan} active"
  6  payment_grace                (warning)       "Payment problem"
  7  restricted_qualification_failed  (danger)    "Free trial not unlocked"
  8  restricted_trial_expired         (danger)    "Free trial ended"
  9  restricted_subscription_expired  (danger)    "Subscription expired"
  10 no_subscription               (neutral)       "No subscription found"

Rules:
  - Read-only.  Never writes, and runs AT MOST ONE published-product COUNT
    query - and only for the states that actually show a product count
    (7, 8, 9, 10 run zero count queries).
  - Safe when the vendor has no Subscription row at all.
  - `is_restricted` always equals `not vendor.is_available`.
  - Templates never branch on the state themselves: they pick colours from
    `tone` and the CTA block from `primary_cta_*` / `secondary_cta_*`.
"""

from dataclasses import dataclass
from datetime import date, datetime
from typing import Optional

from django.core.exceptions import ObjectDoesNotExist
from django.utils import timezone

from .qualification import QUALIFICATION_REQUIRED_PRODUCTS

# --------------------------------------------------------------------------
# Display labels
# --------------------------------------------------------------------------
PLAN_NAMES = {
    'free': 'Free Plan',
    'basic': 'Basic Plan',
    'premium': 'Premium Plan',
}

STATUS_LABELS = {
    'qualifying': 'Qualifying',
    'trial': 'Trial',
    'active': 'Active',
    'past_due': 'Past Due',
    'cancelled': 'Cancelled',
    'expired': 'Expired',
}

DATE_FORMAT = '%b %d, %Y'

RESTRICTED_MESSAGE = (
    'Your store and products stay public, but buyers see Vendor Unavailable '
    'instead of Call/WhatsApp and you cannot add new products. Subscribe to '
    'restore everything immediately.'
)

ADD_FIRST_PRODUCT = ('Add your first product', 'vendors:product_create')
ADD_PRODUCT = ('Add product', 'vendors:product_create')
VIEW_PLANS = ('View plans', 'vendors:subscription_plans')
MANAGE_SUBSCRIPTION = ('Manage subscription', 'vendors:subscription_plans')
SUBSCRIBE = ('Subscribe', 'vendors:subscription_plans')


@dataclass(frozen=True)
class SubscriptionState:
    """Display-ready snapshot of one subscription state (never None-safe)."""

    key: str
    tone: str
    title: str
    message: str
    primary_cta_label: str
    primary_cta_url_name: str
    secondary_cta_label: Optional[str] = None
    secondary_cta_url_name: Optional[str] = None
    is_restricted: bool = False
    plan_name: str = ''
    status_label: str = ''
    days_left: Optional[int] = None
    end_date: Optional[date] = None
    qualification: Optional[dict] = None


# --------------------------------------------------------------------------
# Small helpers (no queries)
# --------------------------------------------------------------------------
def _as_date(value) -> Optional[date]:
    """Datetimes render as plain dates; dates are passed through."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    return value


def _fmt(value) -> str:
    """'Oct 07, 2026' or '' when there is no date."""
    parsed = _as_date(value)
    if parsed is None:
        return ''
    return parsed.strftime(DATE_FORMAT)


def _days_left(target, now) -> Optional[int]:
    """Whole days remaining until `target` (rounded up), None when target is None."""
    if target is None:
        return None
    seconds = (target - now).total_seconds()
    if seconds <= 0:
        return 0
    days = int(seconds // 86400)
    if seconds % 86400:
        days += 1
    return days


def _plan_name(sub) -> str:
    return PLAN_NAMES.get(sub.plan, sub.plan.title() if sub.plan else 'No plan')


def _status_label(sub) -> str:
    return STATUS_LABELS.get(sub.status, sub.status.replace('_', ' ').title())


def _qualification(done, days, window) -> dict:
    """Progress block for the qualification states (one count query upstream)."""
    return {
        'products_done': done,
        'products_needed': max(QUALIFICATION_REQUIRED_PRODUCTS - done, 0),
        'required': QUALIFICATION_REQUIRED_PRODUCTS,
        'days_left': days,
        'window': window,
    }


def _state(key, tone, title, message, cta, *, secondary=None, is_restricted=False,
           plan_name='', status_label='', days_left=None, end_date=None,
           qualification=None) -> SubscriptionState:
    return SubscriptionState(
        key=key,
        tone=tone,
        title=title,
        message=message,
        primary_cta_label=cta[0],
        primary_cta_url_name=cta[1],
        secondary_cta_label=secondary[0] if secondary else None,
        secondary_cta_url_name=secondary[1] if secondary else None,
        is_restricted=is_restricted,
        plan_name=plan_name,
        status_label=status_label,
        days_left=days_left,
        end_date=_as_date(end_date),
        qualification=qualification,
    )


# --------------------------------------------------------------------------
# The descriptor
# --------------------------------------------------------------------------
def describe_subscription_state(vendor) -> SubscriptionState:
    """
    Classify `vendor`'s subscription into exactly one of the ten states.

    Takes no arguments beyond the vendor, never writes, and is safe to call
    from any vendor view (the banner partial only reads the result).
    """
    now = timezone.now()

    try:
        sub = vendor.subscription
    except ObjectDoesNotExist:
        sub = None

    # --- state 10: no Subscription row at all ---------------------------
    if sub is None:
        return _state(
            'no_subscription',
            'neutral',
            'No subscription found',
            'Open the plans page to choose a plan.',
            VIEW_PLANS,
            is_restricted=not vendor.is_available,
            plan_name='No plan',
            status_label='None',
        )

    plan_name = _plan_name(sub)
    status_label = _status_label(sub)
    is_restricted = not vendor.is_available

    # --- states 1-3 / 7: free-plan qualification ------------------------
    if sub.status == 'qualifying':
        window = sub.effective_qualification_status  # pure, no queries
        if window == 'failed':
            # state 7 - restricted, failed qualification
            done = sub.qualified_products_count  # the one count query
            return _state(
                'restricted_qualification_failed',
                'danger',
                'Free trial not unlocked',
                (
                    'You did not publish 3 products within 14 days of your '
                    'first product. '
                ) + RESTRICTED_MESSAGE,
                SUBSCRIBE,
                is_restricted=is_restricted,
                plan_name=plan_name,
                status_label=status_label,
                days_left=0,
                end_date=sub.qualification_grace_deadline,
                qualification=_qualification(done, 0, 'failed'),
            )

        done = sub.qualified_products_count  # the one count query
        needed = max(QUALIFICATION_REQUIRED_PRODUCTS - done, 0)
        days = sub.qualification_days_left

        if window == 'grace':
            # state 3 - grace countdown, still allowed to sell
            return _state(
                'qualifying_grace',
                'warning',
                f'Grace period: {done} of {QUALIFICATION_REQUIRED_PRODUCTS} published products',
                (
                    f'Your first 7 days are over. You have {days} more day(s) '
                    f'to publish {needed} more product(s). After that, buyers '
                    'will see Vendor Unavailable and you will not be able to '
                    'add products until you subscribe.'
                ),
                ADD_PRODUCT,
                secondary=VIEW_PLANS,
                is_restricted=is_restricted,
                plan_name=plan_name,
                status_label=status_label,
                days_left=days,
                end_date=sub.qualification_grace_deadline,
                qualification=_qualification(done, days, 'grace'),
            )

        if window == 'in_progress':
            # state 2 - first 7-day window
            return _state(
                'qualifying_in_progress',
                'info',
                f'Free trial qualification: {done} of {QUALIFICATION_REQUIRED_PRODUCTS} published products',
                (
                    f'Publish {needed} more product(s) within {days} day(s) '
                    'to unlock your 3-month free trial. Drafts do not count.'
                ),
                ADD_PRODUCT,
                is_restricted=is_restricted,
                plan_name=plan_name,
                status_label=status_label,
                days_left=days,
                end_date=sub.qualification_deadline,
                qualification=_qualification(done, days, 'in_progress'),
            )

        # state 1 - no first product yet (window == 'not_started')
        return _state(
            'qualifying_not_started',
            'info',
            'Start your free trial',
            (
                'Create your first product to begin your 7-day qualification. '
                'Publish 3 products within 7 days to unlock your 3-month free '
                'trial.'
            ),
            ADD_FIRST_PRODUCT,
            is_restricted=is_restricted,
            plan_name=plan_name,
            status_label=status_label,
            days_left=None,
            end_date=None,
            qualification=_qualification(done, None, 'in_progress'),
        )

    # --- state 4 / 8: free trial -----------------------------------------
    if sub.status == 'trial':
        if sub.trial_ends_at is not None and sub.trial_ends_at > now:
            days = _days_left(sub.trial_ends_at, now)
            message = f'{days} day(s) left (ends {_fmt(sub.trial_ends_at)}).'
            if days is not None and days <= 7:
                message += ' Choose a plan to keep your store available to buyers.'
            return _state(
                'trial_active',
                'warning' if days is not None and days <= 7 else 'success',
                'Free trial active',
                message,
                VIEW_PLANS,
                is_restricted=is_restricted,
                plan_name=plan_name,
                status_label=status_label,
                days_left=days,
                end_date=sub.trial_ends_at,
            )
        # state 8 - trial over
        return _state(
            'restricted_trial_expired',
            'danger',
            'Free trial ended',
            RESTRICTED_MESSAGE,
            SUBSCRIBE,
            is_restricted=is_restricted,
            plan_name=plan_name,
            status_label=status_label,
            days_left=0,
            end_date=sub.trial_ends_at,
        )

    # --- state 5: paid subscription running ------------------------------
    if sub.status == 'active':
        paid = sub.plan in ('basic', 'premium')
        if paid and sub.period_end is not None and sub.period_end > now:
            days = _days_left(sub.period_end, now)
            if sub.cancel_at_period_end:
                message = (
                    f'Your plan ends on {_fmt(sub.period_end)}. '
                    'No automatic charge will occur.'
                )
                tone = 'warning'
            else:
                message = f'Renews on {_fmt(sub.period_end)}.'
                tone = 'success'
            return _state(
                'paid_active',
                tone,
                f'{plan_name} active',
                message,
                MANAGE_SUBSCRIPTION,
                is_restricted=is_restricted,
                plan_name=plan_name,
                status_label=status_label,
                days_left=days,
                end_date=sub.period_end,
            )
        return _state(
            'restricted_subscription_expired',
            'danger',
            'Subscription expired',
            RESTRICTED_MESSAGE,
            SUBSCRIBE,
            is_restricted=is_restricted,
            plan_name=plan_name,
            status_label=status_label,
            days_left=0,
            end_date=sub.period_end or sub.grace_ends_at,
        )

    # --- state 6 / 9: payment problem / expired ---------------------------
    if sub.status in ('past_due', 'cancelled'):
        if sub.grace_ends_at is not None and sub.grace_ends_at > now:
            # state 6 - store still up during grace
            return _state(
                'payment_grace',
                'warning',
                'Payment problem',
                (
                    f'Your store stays available until {_fmt(sub.grace_ends_at)}. '
                    'Subscribe again to keep contact buttons and product creation.'
                ),
                SUBSCRIBE,
                is_restricted=is_restricted,
                plan_name=plan_name,
                status_label=status_label,
                days_left=_days_left(sub.grace_ends_at, now),
                end_date=sub.grace_ends_at,
            )
        return _state(
            'restricted_subscription_expired',
            'danger',
            'Subscription expired',
            RESTRICTED_MESSAGE,
            SUBSCRIBE,
            is_restricted=is_restricted,
            plan_name=plan_name,
            status_label=status_label,
            days_left=0,
            end_date=sub.grace_ends_at,
        )

    # --- expired rows: qualification failure vs a lapsed plan -------------
    if sub.status == 'expired':
        if sub.qualification_status == 'failed':
            done = sub.qualified_products_count  # the one count query
            return _state(
                'restricted_qualification_failed',
                'danger',
                'Free trial not unlocked',
                (
                    'You did not publish 3 products within 14 days of your '
                    'first product. '
                ) + RESTRICTED_MESSAGE,
                SUBSCRIBE,
                is_restricted=is_restricted,
                plan_name=plan_name,
                status_label=status_label,
                days_left=0,
                end_date=sub.qualification_grace_deadline,
                qualification=_qualification(done, 0, 'failed'),
            )
        if sub.trial_ends_at is not None:
            return _state(
                'restricted_trial_expired',
                'danger',
                'Free trial ended',
                RESTRICTED_MESSAGE,
                SUBSCRIBE,
                is_restricted=is_restricted,
                plan_name=plan_name,
                status_label=status_label,
                days_left=0,
                end_date=sub.trial_ends_at,
            )
        return _state(
            'restricted_subscription_expired',
            'danger',
            'Subscription expired',
            RESTRICTED_MESSAGE,
            SUBSCRIBE,
            is_restricted=is_restricted,
            plan_name=plan_name,
            status_label=status_label,
            days_left=0,
            end_date=sub.period_end or sub.grace_ends_at,
        )

    # --- anything else (impossible per STATUS_CHOICES): stay restricted ----
    return _state(
        'restricted_subscription_expired',
        'danger',
        'Subscription expired',
        RESTRICTED_MESSAGE,
        SUBSCRIBE,
        is_restricted=is_restricted,
        plan_name=plan_name,
        status_label=status_label,
        days_left=0,
        end_date=sub.period_end,
    )
