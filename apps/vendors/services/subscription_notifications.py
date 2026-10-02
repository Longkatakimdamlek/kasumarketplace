"""
Subscription / qualification notifications (Phase 7).

Reuses the unified Notification model and ``create_notification()`` from
``notification_dispatch`` (in-app row + mirrored email).  Nothing in here
builds a parallel notification or email system.

Six kinds, each fired at most once per (subscription, kind, cycle):

  trial_unlocked        synchronous at the qualifying -> trial transition
  qualification_grace   daily command, day-7 deadline inside the lookback
  qualification_failed  daily command, day-14 deadline inside the lookback
  trial_ending_soon     daily command, 0 < days_left <= 7 (no lookback)
  trial_ended           daily command, trial deadline inside the lookback
  subscription_expired  daily command, paid expiry inside the lookback

Copy is verbatim from the Phase 7 spec.  RESTRICTED_MESSAGE and
DATE_FORMAT are imported from ``subscription_state`` so the dashboard
banner and the email can never drift apart; done / needed / days come
from the existing qualification helpers (``qualified_products_count``,
``qualification_days_left``) and ``describe_subscription_state``.

Every notification links to ``vendors:subscription_plans`` as a relative
path; ``notification_dispatch`` prefixes SITE_URL for the email.
"""

import logging
from datetime import timedelta

from django.db import IntegrityError
from django.urls import reverse

from apps.vendors.models import Subscription, SubscriptionNotificationLog, VendorProfile
from apps.vendors.qualification import QUALIFICATION_REQUIRED_PRODUCTS
from apps.vendors.subscription_state import (
    DATE_FORMAT,
    RESTRICTED_MESSAGE,
    describe_subscription_state,
)

logger = logging.getLogger(__name__)

PLANS_URL_NAME = 'vendors:subscription_plans'
NOTIFICATION_TYPE = 'subscription'

TRIAL_UNLOCKED = 'trial_unlocked'
QUALIFICATION_GRACE = 'qualification_grace'
QUALIFICATION_FAILED = 'qualification_failed'
TRIAL_ENDING_SOON = 'trial_ending_soon'
TRIAL_ENDED = 'trial_ended'
SUBSCRIPTION_EXPIRED = 'subscription_expired'

KINDS = (
    TRIAL_UNLOCKED,
    QUALIFICATION_GRACE,
    QUALIFICATION_FAILED,
    TRIAL_ENDING_SOON,
    TRIAL_ENDED,
    SUBSCRIPTION_EXPIRED,
)

TRIAL_ENDING_SOON_WINDOW_DAYS = 7
LOOKBACK_DEFAULT_DAYS = 3

PAID_PLANS = ('basic', 'premium')


# --------------------------------------------------------------------------
# Small helpers
# --------------------------------------------------------------------------
def _fmt(value) -> str:
    """'Oct 07, 2026' - same DATE_FORMAT the subscription banner uses."""
    if value is None:
        return ''
    if hasattr(value, 'date') and not isinstance(value, str):
        value = value.date()
    return value.strftime(DATE_FORMAT)


def _iso_date(value) -> str:
    """Cycle key: the ISO date of a deadline, '' when there is no deadline."""
    if value is None:
        return ''
    if hasattr(value, 'date') and not isinstance(value, str):
        value = value.date()
    return value.isoformat()


def plans_link() -> str:
    """Relative link to the plans page (absolute URL added for the email)."""
    return reverse(PLANS_URL_NAME)


def is_admin_suspended(vendor) -> bool:
    return getattr(vendor, 'verification_status', '') == 'suspended'


def is_active_paid(sub) -> bool:
    return sub.plan in PAID_PLANS and sub.status == 'active'


def _within_lookback(deadline, now, lookback_days) -> bool:
    """True when `deadline` has passed no more than `lookback_days` ago."""
    if deadline is None:
        return False
    if deadline > now:
        return False
    return deadline >= now - timedelta(days=max(lookback_days, 0))


def _expiry_deadline(sub):
    """
    When a paid subscription actually became unavailable: the later of
    period_end and grace_ends_at (grace is the moment the store went dark
    after a failed payment), whichever exist.
    """
    candidates = [d for d in (sub.period_end, sub.grace_ends_at) if d is not None]
    if not candidates:
        return None
    return max(candidates)


def prime_subscription_cache(vendor, sub) -> None:
    """
    Seed vendor._state.fields_cache so ``vendor.subscription`` (used by
    describe_subscription_state and vendor.is_available) does not issue a
    second query per vendor inside the cron loop.
    """
    try:
        rel = VendorProfile._meta.get_field('subscription')
    except Exception:  # pragma: no cover - defensive
        return
    try:
        if not rel.is_cached(vendor):
            rel.set_cached_value(vendor, sub)
    except Exception:  # pragma: no cover - defensive
        logger.debug('Could not prime subscription cache for vendor %s', vendor.pk)


# --------------------------------------------------------------------------
# Copy (verbatim from the Phase 7 spec)
# --------------------------------------------------------------------------
def build_copy(kind, sub, state=None, days=None):
    """Return (title, message) for `kind` using the existing helpers."""
    if kind == TRIAL_UNLOCKED:
        return (
            'Free trial unlocked',
            'You published 3 products. Your 3-month free trial is active '
            f'until {_fmt(sub.trial_ends_at)}.',
        )

    if kind == QUALIFICATION_GRACE:
        done = sub.qualified_products_count
        needed = max(QUALIFICATION_REQUIRED_PRODUCTS - done, 0)
        days_left = sub.qualification_days_left
        return (
            'Grace period started',
            f'You have published {done} of 3 products. You have {days_left} '
            f'more day(s) to publish {needed} more product(s). After that, '
            'buyers will see Vendor Unavailable and you will not be able to '
            'add products until you subscribe.',
        )

    if kind == QUALIFICATION_FAILED:
        return (
            'Free trial not unlocked',
            'You did not publish 3 products within 14 days of your first '
            f'product. {RESTRICTED_MESSAGE}',
        )

    if kind == TRIAL_ENDING_SOON:
        return (
            f'Your free trial ends in {days} day(s)',
            f'Your free trial ends on {_fmt(sub.trial_ends_at)}. '
            'Choose a plan to keep your store available to buyers.',
        )

    if kind == TRIAL_ENDED:
        return 'Free trial ended', RESTRICTED_MESSAGE

    if kind == SUBSCRIPTION_EXPIRED:
        return 'Subscription expired', RESTRICTED_MESSAGE

    raise ValueError(f'Unknown subscription notification kind: {kind}')


# --------------------------------------------------------------------------
# Which kind (if any) is due for a subscription right now
# --------------------------------------------------------------------------
def evaluate_due(sub, state, now, lookback_days=LOOKBACK_DEFAULT_DAYS):
    """
    Decide what `sub` is due for at `now`.

    Returns ``(outcome, kind, cycle_key, deadline)`` with outcome in
      'due'       - send it (after the dedupe claim)
      'not_due'   - the state does not call for this kind
      'suppressed'- admin-suspended vendor / active paid trial warning
      'lookback'  - the deadline fell outside the lookback window
    """
    vendor = sub.vendor
    suspended = is_admin_suspended(vendor)
    key = state.key
    kind = cycle = deadline = None

    if key == 'qualifying_grace':
        kind = QUALIFICATION_GRACE
        deadline = sub.qualification_deadline
        cycle = _iso_date(sub.first_product_at)
        if suspended:
            return 'suppressed', kind, cycle, deadline
        if not _within_lookback(deadline, now, lookback_days):
            return 'lookback', kind, cycle, deadline
        return 'due', kind, cycle, deadline

    if key == 'restricted_qualification_failed':
        kind = QUALIFICATION_FAILED
        deadline = sub.qualification_grace_deadline
        cycle = _iso_date(sub.first_product_at)
        if suspended:
            return 'suppressed', kind, cycle, deadline
        if not _within_lookback(deadline, now, lookback_days):
            return 'lookback', kind, cycle, deadline
        return 'due', kind, cycle, deadline

    if key == 'trial_active':
        days = state.days_left
        if days is None or days <= 0 or days > TRIAL_ENDING_SOON_WINDOW_DAYS:
            return 'not_due', '', '', None
        kind = TRIAL_ENDING_SOON
        cycle = _iso_date(sub.trial_ends_at)
        # Never warn a vendor who is already paying (or was suspended).
        if suspended or is_active_paid(sub):
            return 'suppressed', kind, cycle, None
        return 'due', kind, cycle, None

    if key == 'restricted_trial_expired':
        kind = TRIAL_ENDED
        deadline = sub.trial_ends_at
        cycle = _iso_date(sub.trial_ends_at)
        # A paid vendor whose old free trial date passed is not "trial ended".
        if sub.plan != 'free' or not cycle:
            return 'not_due', kind, cycle, deadline
        if suspended:
            return 'suppressed', kind, cycle, deadline
        if not _within_lookback(deadline, now, lookback_days):
            return 'lookback', kind, cycle, deadline
        return 'due', kind, cycle, deadline

    if key == 'restricted_subscription_expired':
        kind = SUBSCRIPTION_EXPIRED
        deadline = _expiry_deadline(sub)
        cycle = _iso_date(deadline)
        if not cycle:
            # No billing deadline on this row: nothing to key the cycle on.
            return 'not_due', kind, cycle, deadline
        if suspended:
            return 'suppressed', kind, cycle, deadline
        if not _within_lookback(deadline, now, lookback_days):
            return 'lookback', kind, cycle, deadline
        return 'due', kind, cycle, deadline

    return 'not_due', '', '', None


# --------------------------------------------------------------------------
# Dedupe claim + dispatch
# --------------------------------------------------------------------------
def claim_cycle(sub, kind, cycle_key, dry_run=False) -> bool:
    """
    Claim (subscription, kind, cycle_key) for this run.

    Returns True when the caller owns the cycle and may send.  The write is
    a get_or_create against a UNIQUE(subscription, kind, cycle_key)
    constraint, so two overlapping cron runs cannot both win; a lost race
    raises nothing and reports False.
    """
    if dry_run:
        return not SubscriptionNotificationLog.objects.filter(
            subscription=sub, kind=kind, cycle_key=cycle_key,
        ).exists()

    try:
        _, created = SubscriptionNotificationLog.objects.get_or_create(
            subscription=sub, kind=kind, cycle_key=cycle_key,
        )
    except IntegrityError:
        return False
    return created


def _deliver(sub, kind, state, cycle, days=None, dry_run=False):
    """Claim the cycle, then dispatch through create_notification()."""
    if not cycle:
        return 'not_due', '', ''

    user = getattr(sub.vendor, 'user', None)
    if user is None:
        return 'suppressed', '', ''

    title, message = build_copy(kind, sub, state, days=days)

    if not claim_cycle(sub, kind, cycle, dry_run=dry_run):
        return 'dedupe', title, message

    if dry_run:
        return 'would_send', title, message

    from apps.vendors.services.notification_dispatch import create_notification

    create_notification(
        user=user,
        notification_type=NOTIFICATION_TYPE,
        title=title,
        message=message,
        link=plans_link(),
        vendor=sub.vendor,
    )
    return 'sent', title, message


def notify_trial_unlocked(sub, dry_run=False) -> str:
    """
    Kind 1: fired synchronously from the qualifying -> trial transition
    (qualification.evaluate_qualification).  Never raises: qualification
    must keep working even if the notification infrastructure fails.
    """
    try:
        cycle = _iso_date(sub.trial_ends_at)
        state = describe_subscription_state(sub.vendor)
        outcome, _, _ = _deliver(
            sub, TRIAL_UNLOCKED, state, cycle, dry_run=dry_run,
        )
        if outcome == 'sent':
            logger.info(
                'trial_unlocked notified vendor %s (subscription %s, cycle %s)',
                sub.vendor_id, sub.pk, cycle,
            )
        return outcome
    except Exception:
        logger.exception(
            'trial_unlocked notification failed for subscription %s', sub.pk,
        )
        return 'error'


# --------------------------------------------------------------------------
# Daily loop (called by the check_subscription_status command)
# --------------------------------------------------------------------------
def run_subscription_notifications(
    now=None,
    lookback_days=LOOKBACK_DEFAULT_DAYS,
    dry_run=False,
    stdout=None,
):
    """
    Evaluate every subscription once and send what is due.

    Query shape: one SELECT with select_related('vendor__user') plus the
    per-vendor queries a due notification actually needs (product COUNT for
    the copy, the dedupe claim, the Notification insert).  A failure for one
    vendor is logged and counted; it never stops the loop.

    Returns a summary dict:
      processed, sent {kind: n}, would_send {kind: n},
      suppressed, dedupe, lookback, not_due, errors
    """
    from django.utils import timezone

    now = now or timezone.now()
    summary = {
        'processed': 0,
        'sent': {kind: 0 for kind in KINDS},
        'would_send': {kind: 0 for kind in KINDS},
        'suppressed': 0,
        'dedupe': 0,
        'lookback': 0,
        'not_due': 0,
        'errors': 0,
    }

    subscriptions = Subscription.objects.select_related('vendor__user').order_by('pk')

    for sub in subscriptions:
        summary['processed'] += 1
        try:
            vendor = sub.vendor
            prime_subscription_cache(vendor, sub)
            state = describe_subscription_state(vendor)

            outcome, kind, cycle, _deadline = evaluate_due(
                sub, state, now, lookback_days=lookback_days,
            )
            if outcome != 'due':
                summary[outcome] += 1
                continue

            days = state.days_left if kind == TRIAL_ENDING_SOON else None
            result, title, _message = _deliver(
                sub, kind, state, cycle, days=days, dry_run=dry_run,
            )

            if result in ('sent', 'would_send'):
                bucket = 'sent' if result == 'sent' else 'would_send'
                summary[bucket][kind] += 1
                if dry_run and stdout is not None:
                    stdout.write(
                        f'[dry-run] would notify {vendor.user.email} '
                        f'[{kind}] {title}'
                    )
                elif result == 'sent':
                    logger.info(
                        '%s notified for vendor %s (subscription %s, cycle %s)',
                        kind, vendor_id_or_pk(vendor), sub.pk, cycle,
                    )
            else:
                summary[result] += 1
        except Exception:
            summary['errors'] += 1
            logger.exception(
                'subscription notification failed for subscription %s', sub.pk,
            )

    return summary


def vendor_id_or_pk(vendor):
    return getattr(vendor, 'vendor_id', None) or vendor.pk


def format_summary(summary) -> str:
    """One ASCII summary line: processed / sent per kind / skipped / errors."""
    sent = ', '.join(f'{kind}={summary["sent"][kind]}' for kind in KINDS)
    return (
        f'summary: processed {summary["processed"]} | '
        f'sent: {sent} | '
        f'skipped: suppressed={summary["suppressed"]}, '
        f'dedupe={summary["dedupe"]}, lookback={summary["lookback"]}, '
        f'not_due={summary["not_due"]} | '
        f'errors: {summary["errors"]}'
    )


def format_dry_run_summary(summary) -> str:
    would = ', '.join(f'{kind}={summary["would_send"][kind]}' for kind in KINDS)
    return (
        f'[dry-run] summary: processed {summary["processed"]} | '
        f'would send: {would} | '
        f'skipped: suppressed={summary["suppressed"]}, '
        f'dedupe={summary["dedupe"]}, lookback={summary["lookback"]}, '
        f'not_due={summary["not_due"]} | '
        f'errors: {summary["errors"]}'
    )
