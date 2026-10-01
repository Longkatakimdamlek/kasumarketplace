"""
Subscription Billing Service
Handles Paystack recurring billing, webhook processing, and grace-period logic.

Env vars required:
  PAYSTACK_SECRET_KEY
  PAYSTACK_BASIC_PLAN_CODE
  PAYSTACK_PREMIUM_PLAN_CODE

This service is intentionally kept separate from the existing paystack.py
(legacy payment service) so it can be developed and tested independently.
Legacy paystack.py will be removed in Phase 3.
"""
import os
import hmac
import hashlib
import logging
from datetime import timedelta
from typing import Dict, Optional, Tuple

import requests
from django.conf import settings
from django.core.exceptions import ValidationError
from django.urls import reverse
from django.utils import timezone

from apps.vendors.models import Subscription, VendorProfile
from apps.vendors.plans import (
    get_plan,
    get_paystack_plan_code,
    get_plan_price_kobo,
    plan_for_paystack_code,
    paid_plans,
)
from apps.vendors.services.notification_dispatch import create_notification

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
GRACE_PERIOD_DAYS = 7
MAX_RETRY_ATTEMPTS = 3


def build_callback_url() -> str:
    """
    Absolute URL of the Paystack callback endpoint (vendors:subscription_callback).

    Built from the existing SITE_URL setting (KasuMarketplace/settings.py),
    so the value is stable across hosts and does not depend on the inbound
    request.  No new setting is introduced.
    """
    base = str(getattr(settings, 'SITE_URL', '') or '').rstrip('/')
    return f'{base}{reverse("vendors:subscription_callback")}'


class SubscriptionServiceError(Exception):
    """Raised when a Paystack subscription API call fails."""


class SubscriptionService:
    """
    Stateless service — every public method accepts explicit arguments and
    returns clear success/failure tuples.  No singletons or global state.
    """

    def __init__(self):
        self.secret_key = os.getenv('PAYSTACK_SECRET_KEY', '')
        self.base_url = 'https://api.paystack.co'

        if not self.secret_key:
            logger.warning('PAYSTACK_SECRET_KEY not set — billing calls will fail.')

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _headers(self) -> Dict[str, str]:
        return {
            'Authorization': f'Bearer {self.secret_key}',
            'Content-Type': 'application/json',
        }

    def _request(self, method: str, endpoint: str, data: Optional[Dict] = None) -> Dict:
        url = f'{self.base_url}{endpoint}'
        try:
            if method.upper() == 'GET':
                resp = requests.get(url, headers=self._headers(), params=data, timeout=30)
            else:
                resp = requests.post(url, headers=self._headers(), json=data, timeout=30)

            resp.raise_for_status()
            body = resp.json()

            if not body.get('status'):
                raise SubscriptionServiceError(body.get('message', 'Paystack API error'))

            return body.get('data', {})

        except requests.exceptions.RequestException as exc:
            logger.error('Paystack request failed: %s %s — %s', method, endpoint, exc)
            raise SubscriptionServiceError(str(exc))

    # ------------------------------------------------------------------
    # Customer management
    # ------------------------------------------------------------------

    def get_or_create_customer(self, email: str, first_name: str = '', last_name: str = '') -> str:
        """Return the Paystack customer_code for the given email, creating if needed."""
        # Try fetching existing
        data = self._request('GET', '/customer', {'email': email})
        customers = data.get('data', []) if isinstance(data, dict) else data
        if customers:
            return customers[0].get('customer_code', '')

        # Create new
        payload = {'email': email}
        if first_name:
            payload['first_name'] = first_name
        if last_name:
            payload['last_name'] = last_name
        result = self._request('POST', '/customer', payload)
        return result.get('customer_code', '')

    # ------------------------------------------------------------------
    # Subscription initialization (first payment / redirect flow)
    # ------------------------------------------------------------------

    def initialize_subscription(
        self,
        email: str,
        plan: str,
        metadata: Optional[Dict] = None
    ) -> Tuple[bool, Dict]:
        """
        Initialize a Paystack subscription payment for a given plan.
        plan must be 'basic' or 'premium'.
        Returns (success, {authorization_url, reference, ...}).
        """
        # Validate plan
        if plan not in ('basic', 'premium'):
            raise SubscriptionServiceError(f"Invalid plan '{plan}'. Must be 'basic' or 'premium'.")

        plan_config = get_plan(plan)
        plan_code = get_paystack_plan_code(plan)
        if not plan_code:
            raise SubscriptionServiceError(
                f"Paystack plan code for '{plan}' is not configured. "
                f"Set {plan_config['paystack_plan_code_setting']} in environment."
            )

        price_kobo = get_plan_price_kobo(plan)

        payload = {
            'email': email,
            'plan': plan_code,
            'amount': price_kobo,
            'currency': 'NGN',
            'callback_url': build_callback_url(),
        }
        if metadata:
            payload['metadata'] = metadata

        result = self._request('POST', '/transaction/initialize', payload)

        return True, {
            'authorization_url': result.get('authorization_url', ''),
            'access_code': result.get('access_code', ''),
            'reference': result.get('reference', ''),
            'callback_url': payload['callback_url'],
        }

    # ------------------------------------------------------------------
    # Transaction verification (used by the browser callback)
    # ------------------------------------------------------------------

    def verify_transaction(self, reference: str) -> Dict:
        """
        Verify a transaction reference with Paystack's verify endpoint and
        return the transaction dict.  Raises SubscriptionServiceError if the
        reference is unknown or the API call fails.
        """
        if not reference:
            raise SubscriptionServiceError('Missing transaction reference')
        # _request already raises on a non-`status: true` Paystack envelope and
        # returns the `data` object, which is the transaction dict itself.
        return self._request('GET', f'/transaction/verify/{reference}')

    # ------------------------------------------------------------------
    # Subscription status helpers
    # ------------------------------------------------------------------

    def _is_replay(self, sub: Subscription, new_sub_code: str, plan: str) -> bool:
        """
        True when this exact charge has already been applied to `sub`.

        A duplicate webhook or a callback arriving after the webhook carries
        the same Paystack subscription code and the same target plan.  If the
        stored row already reflects that, the event is a replay and must not
        extend period_end, flip the plan again, or disable anything twice.
        """
        return bool(
            new_sub_code
            and sub.status == 'active'
            and sub.plan == plan
            and sub.paystack_subscription_code == new_sub_code
        )

    def _disable_paystack_subscription(
        self, subscription_code: str, sub_pk=None, failure_level: int = logging.ERROR
    ) -> bool:
        """
        Disable a Paystack subscription through the shared disable endpoint.

        Returns True on success.  On failure it logs at failure_level
        (ERROR by default, including the local subscription pk and the
        Paystack subscription code) and returns False so the caller can keep
        the new plan active.  Callers that disable an already-disabled code
        pass a lower level so the failure is not read as a billing alarm.
        """
        if not subscription_code:
            return False
        try:
            self._request('POST', f'/subscription/{subscription_code}/disable', {})
            logger.info(
                'Disabled Paystack subscription %s (local subscription pk %s)',
                subscription_code, sub_pk,
            )
            return True
        except SubscriptionServiceError as exc:
            logger.log(
                failure_level,
                'Failed to disable Paystack subscription %s for subscription pk %s: %s',
                subscription_code, sub_pk, exc,
            )
            return False

    def activate_subscription(self, sub: Subscription, paystack_data: Dict, plan: str) -> bool:
        """
        Mark subscription as active after a successful first payment.

        paystack_data should contain: customer_code, subscription_code, plan_code.

        Idempotent: returns True when the row was changed, False when this
        charge was already applied (replayed webhook / callback).

        When the incoming charge belongs to a DIFFERENT Paystack subscription
        than the one currently stored (the basic -> premium upgrade), the old
        subscription code is captured BEFORE the row is overwritten and the
        old subscription is disabled after the new plan is saved.  A failure to
        disable leaves the new plan active and is logged at ERROR.
        """
        new_sub_code = paystack_data.get('subscription_code') or sub.paystack_subscription_code

        if self._is_replay(sub, new_sub_code, plan):
            logger.info(
                'Subscription %s already active on plan %s (paystack code %s) '
                '- replay ignored', sub.pk, plan, new_sub_code,
            )
            return False

        # Capture the OLD Paystack subscription code before activate overwrites
        # it.  No email/token needs capturing: Paystack's
        # POST /subscription/{code}/disable authenticates with the secret-key
        # bearer token only.
        old_sub_code = sub.paystack_subscription_code or ''
        # Captured before the save below clears it.  A vendor who cancelled or
        # downgraded already had the old subscription disabled at Paystack, so
        # failing to disable it again is expected and must not be reported as
        # a double-billing ERROR.
        was_cancelling = bool(sub.cancel_at_period_end)

        now = timezone.now()
        # Phase 5: a row that was still qualifying when it started paying skips qualification.
        sub.qualification_status = 'skipped' if sub.status == 'qualifying' else sub.qualification_status
        sub.status = 'active'
        sub.plan = plan
        sub.period_end = now + timedelta(days=30)
        sub.grace_ends_at = None
        sub.paystack_customer_code = paystack_data.get('customer_code') or sub.paystack_customer_code
        sub.paystack_subscription_code = new_sub_code
        sub.paystack_plan_code = paystack_data.get('plan_code') or sub.paystack_plan_code
        sub.cancel_at_period_end = False
        sub.pending_plan = ''
        sub.retry_count = 0
        sub.last_payment_attempt_at = now
        sub.save(update_fields=[
            'status', 'plan', 'period_end', 'grace_ends_at',
            'qualification_status',
            'paystack_customer_code', 'paystack_subscription_code',
            'paystack_plan_code', 'cancel_at_period_end', 'pending_plan',
            'retry_count', 'last_payment_attempt_at',
            'updated_at',
        ])
        logger.info('Subscription %s activated for vendor %s with plan %s', sub.pk, sub.vendor_id, plan)

        # First-time subscribe has no old code -> nothing to disable.
        if old_sub_code and old_sub_code != new_sub_code:
            logger.info(
                'Subscription %s upgraded from Paystack subscription %s to %s '
                '- disabling the old subscription',
                sub.pk, old_sub_code, new_sub_code,
            )
            self._disable_paystack_subscription(
                old_sub_code,
                sub_pk=sub.pk,
                failure_level=logging.INFO if was_cancelling else logging.ERROR,
            )

        return True

    def handle_successful_payment(self, sub: Subscription) -> None:
        """
        Called when a recurring payment succeeds (webhook: charge.success).
        Extends period_end by 30 days.
        """
        now = timezone.now()
        sub.status = 'active'
        sub.period_end = (sub.period_end or now) + timedelta(days=30)
        sub.grace_ends_at = None
        sub.retry_count = 0
        sub.last_payment_attempt_at = now
        sub.save(update_fields=[
            'status', 'period_end', 'grace_ends_at',
            'retry_count', 'last_payment_attempt_at', 'updated_at',
        ])
        try:
            create_notification(
                user=sub.vendor.user,
                notification_type='subscription',
                title='Subscription Renewed! 🎉',
                message=(
                    f'Your subscription has been renewed successfully. '
                    f'Your store will remain active until {sub.period_end.strftime("%B %d, %Y")}.'
                ),
                link='/vendors/dashboard/',
                vendor=sub.vendor,
            )
        except Exception:
            logger.exception("Failed to send subscription renewal notification")
        logger.info('Subscription %s payment succeeded — new period_end %s', sub.pk, sub.period_end)

    def handle_failed_payment(self, sub: Subscription) -> None:
        """
        Called when a recurring payment fails (webhook: invoice.payment_failed).
        Moves to past_due and starts the 7-day grace period.
        """
        now = timezone.now()
        sub.retry_count += 1
        sub.last_payment_attempt_at = now

        if sub.retry_count >= MAX_RETRY_ATTEMPTS:
            sub.status = 'expired'
            sub.grace_ends_at = now + timedelta(days=GRACE_PERIOD_DAYS)
        else:
            sub.status = 'past_due'
            sub.grace_ends_at = now + timedelta(days=GRACE_PERIOD_DAYS)

        sub.save(update_fields=[
            'status', 'retry_count', 'last_payment_attempt_at',
            'grace_ends_at', 'updated_at',
        ])
        try:
            grace_date = sub.grace_ends_at.strftime('%B %d, %Y') if sub.grace_ends_at else 'soon'
            if sub.status == 'expired':
                title = 'Subscription Expired! ❌'
                msg = (
                    f'Your subscription payment has failed after {MAX_RETRY_ATTEMPTS} attempts. '
                    f'Your store will remain visible until {grace_date}. '
                    f'Please update your payment method to avoid losing access.'
                )
            else:
                title = 'Payment Failed ⚠️'
                msg = (
                    f'Your subscription payment failed. '
                    f'A 7-day grace period has started and ends on {grace_date}. '
                    f'Please update your payment method to avoid interruption.'
                )
            create_notification(
                user=sub.vendor.user,
                notification_type='subscription',
                title=title,
                message=msg,
                link='/vendors/dashboard/',
                vendor=sub.vendor,
            )
        except Exception:
            logger.exception("Failed to send subscription payment failure notification")
        logger.warning(
            'Subscription %s payment failed (attempt %d/%d) — status=%s',
            sub.pk, sub.retry_count, MAX_RETRY_ATTEMPTS, sub.status,
        )

    def disable_subscription(self, sub: Subscription) -> None:
        """
        Called when Paystack sends subscription.disable webhook for a
        subscription that is NOT scheduled to end (cancel_at_period_end False),
        i.e. it was disabled from the Paystack dashboard or outside our UI.
        Cancels the subscription; grace period still applies.
        """
        now = timezone.now()
        sub.status = 'cancelled'
        sub.grace_ends_at = now + timedelta(days=GRACE_PERIOD_DAYS)
        sub.save(update_fields=['status', 'grace_ends_at', 'updated_at'])
        logger.info('Subscription %s disabled via webhook', sub.pk)

    def cancel_subscription(self, sub: Subscription) -> None:
        """
        Vendor requests cancellation — disable auto-renewal on Paystack
        and mark for expiry at period_end.
        """
        # Disable auto-renewal on Paystack if we have a subscription code.
        # Failure is logged, not raised: we still want to mark locally.
        self._disable_paystack_subscription(sub.paystack_subscription_code, sub_pk=sub.pk)

        sub.cancel_at_period_end = True
        sub.pending_plan = ''
        sub.save(update_fields=['cancel_at_period_end', 'pending_plan', 'updated_at'])
        logger.info('Subscription %s marked for cancellation at period_end', sub.pk)

    def downgrade_subscription(self, sub: Subscription, new_plan: str = 'basic') -> None:
        """
        Vendor requests downgrade — disable auto-renewal on Paystack,
        set cancel_at_period_end=True and pending_plan to new_plan.
        """
        # pending_plan is only ever '' or 'basic' - no flow schedules a move
        # to premium, so anything else is rejected here.
        if new_plan != 'basic':
            raise SubscriptionServiceError(f"Invalid plan '{new_plan}' for downgrade")

        # Disable auto-renewal on Paystack
        self._disable_paystack_subscription(sub.paystack_subscription_code, sub_pk=sub.pk)

        sub.cancel_at_period_end = True
        sub.pending_plan = new_plan
        sub.save(update_fields=['cancel_at_period_end', 'pending_plan', 'updated_at'])
        logger.info('Subscription %s marked for downgrade to %s at period_end', sub.pk, new_plan)

    def upgrade_subscription(self, sub: Subscription, paystack_data: Dict) -> bool:
        """
        Basic -> premium upgrade, driven by the Premium charge that just
        succeeded (webhook charge.success or the browser callback).

        Delegates to activate_subscription, which captures the old Paystack
        subscription code before overwriting it and then disables the old
        Basic subscription.  Returns True when the plan changed, False when
        the charge was a replay.

        A Premium charge always activates, even when the row is cancelling
        (cancel_at_period_end): the money was taken, so the plan must follow.
        activate_subscription clears cancel_at_period_end and pending_plan.

        Raises SubscriptionServiceError only when sub.plan is not 'basic'.
        That case is unreachable from process_subscription_webhook, which
        routes to this method only when plan == 'premium' and sub.plan ==
        'basic'; it stays as a guard for direct callers.
        """
        new_sub_code = paystack_data.get('subscription_code') or sub.paystack_subscription_code

        # Replay of an upgrade that already landed: nothing to do.
        if self._is_replay(sub, new_sub_code, 'premium'):
            logger.info(
                'Subscription %s already upgraded to premium (paystack code %s) '
                '- replay ignored', sub.pk, new_sub_code,
            )
            return False

        if sub.plan != 'basic':
            raise SubscriptionServiceError(
                f"Can only upgrade from basic plan (subscription {sub.pk} is on '{sub.plan}')"
            )

        if sub.cancel_at_period_end:
            logger.info(
                'Subscription %s was cancelling plan %s; activating premium anyway '
                '(charge already succeeded)',
                sub.pk, sub.plan,
            )

        return self.activate_subscription(sub, paystack_data, plan='premium')

    # ------------------------------------------------------------------
    # Grace-period checker (called by management command / cron)
    # ------------------------------------------------------------------

    def expire_grace_periods(self) -> int:
        """
        Find subscriptions in past_due/cancelled status whose grace_ends_at
        has passed, and set them to 'expired'.  Returns the count of
        subscriptions expired.

        For subscriptions with cancel_at_period_end=True and period_end < now,
        they expire directly without payment-retry grace (no renewal charge coming).
        """
        now = timezone.now()

        # 1. Expire past_due/cancelled past grace period (existing behavior)
        qs1 = Subscription.objects.filter(
            status__in=['past_due', 'cancelled'],
            grace_ends_at__isnull=False,
            grace_ends_at__lte=now,
        )
        count1 = qs1.update(status='expired')

        # 2. Expire cancel_at_period_end subscriptions whose period_end has passed
        # These expire directly without grace period because no renewal charge is coming
        qs2 = Subscription.objects.filter(
            cancel_at_period_end=True,
            period_end__isnull=False,
            period_end__lte=now,
        ).exclude(status='expired')
        count2 = qs2.update(status='expired', cancel_at_period_end=False, pending_plan='')

        total = count1 + count2
        if total:
            logger.info('Expired %d subscription(s) past grace period / period_end', total)
        return total


# ---------------------------------------------------------------------------
# Subscription webhook processing (decoupled from payment_service.py)
# ---------------------------------------------------------------------------

def verify_subscription_webhook_signature(payload: bytes, signature: str) -> bool:
    """
    Verify Paystack webhook signature using HMAC SHA512.
    Self-contained — no dependency on payment_service.py.
    """
    secret_key = os.getenv('PAYSTACK_SECRET_KEY', '')
    if not secret_key:
        logger.warning('PAYSTACK_SECRET_KEY not set — cannot verify webhook signature.')
        return False
    expected = hmac.new(
        secret_key.encode('utf-8'),
        payload,
        hashlib.sha512,
    ).hexdigest()
    return hmac.compare_digest(expected, signature)


def _subscription_for_vendor_id(vendor_id: str):
    """
    Resolve the Subscription row of a vendor from the `vendor_id` metadata we
    attach to every checkout.  Returns None when the vendor or the row is
    missing or the id is not a valid UUID.
    """
    if not vendor_id:
        return None
    try:
        vendor = VendorProfile.objects.get(vendor_id=vendor_id)
    except (VendorProfile.DoesNotExist, VendorProfile.MultipleObjectsReturned,
            ValidationError, ValueError, TypeError):
        return None
    try:
        return vendor.subscription
    except Subscription.DoesNotExist:
        return None


def process_subscription_webhook(event_type: str, data: dict, event_id: str = '') -> dict:
    """
    Handle vendor subscription billing events from Paystack.

    Dispatches to:
    - charge.success (initial: metadata.subscription_code; recurring: data.subscription.subscription_code)
      → activate_subscription (initial) or handle_successful_payment (recurring)
    - invoice.payment_failed → handle_failed_payment
    - subscription.disable → disable_subscription (only when the code is the
      row's current code and cancel_at_period_end is False; otherwise the
      event is acknowledged and ignored)
    - subscription.not_renew → acknowledged and ignored (recorded only)

    Idempotency: if event_id is provided and already exists in WebhookEvent,
    the event is acknowledged but not re-processed.

    Returns a result dict with 'success' and 'message' keys.
    """
    from apps.vendors.models import WebhookEvent

    # ---- Idempotency guard ----
    if event_id:
        if WebhookEvent.objects.filter(event_id=event_id).exists():
            logger.info('Duplicate webhook event %s — skipping', event_id)
            return {'success': True, 'message': f'Event {event_id} already processed (idempotent skip).'}

    # ---- Extract subscription code from multiple possible locations ----
    # Real Paystack subscription.* events may carry the code at the top level
    # (data.subscription_code) or nested (data.subscription.subscription_code).
    sub_code = data.get('subscription_code', '')
    if not sub_code:
        sub_data = data.get('subscription') or {}
        if isinstance(sub_data, dict):
            sub_code = sub_data.get('subscription_code', '')

    # ---- Map Paystack plan code to our plan identifier ----
    paystack_plan_code = ''
    plan_data = data.get('plan') or {}
    if isinstance(plan_data, dict):
        paystack_plan_code = plan_data.get('plan_code', '')
    # Also check top-level plan_code for charge.success initial payment
    if not paystack_plan_code:
        paystack_plan_code = data.get('plan', {}).get('plan_code', '')

    plan_identifier = plan_for_paystack_code(paystack_plan_code) if paystack_plan_code else None

    # ---- invoice.payment_failed ----
    if event_type == 'invoice.payment_failed' and sub_code:
        try:
            sub = Subscription.objects.get(paystack_subscription_code=sub_code)
        except Subscription.DoesNotExist:
            return {'success': False, 'message': f'No subscription for code {sub_code}.'}
        subscription_service.handle_failed_payment(sub)
        if event_id:
            WebhookEvent.objects.create(event_id=event_id, event_type=event_type, reference=sub_code, payload=data)
        return {'success': True, 'message': f'invoice.payment_failed processed for sub {sub_code}.'}

    # ---- subscription.disable / subscription.not_renew ----
    # Both arrive as a consequence of our own disable calls (cancel, downgrade,
    # upgrade) and of a disable done outside our UI (Paystack dashboard), so
    # they are gated twice:
    #   1. the code must be the row's CURRENT paystack_subscription_code - an
    #      event for the old Basic code that an upgrade replaced is ignored;
    #   2. a row already scheduled to end (cancel_at_period_end) is left alone:
    #      it keeps paid benefits until period_end, and expire_grace_periods()
    #      expires it then.
    if event_type in ('subscription.disable', 'subscription.not_renew') and sub_code:
        try:
            sub = Subscription.objects.get(paystack_subscription_code=sub_code)
        except Subscription.DoesNotExist:
            # No row currently holds this code (the Basic code that an upgrade
            # replaced, or a code we never knew). Acknowledge, record, ignore.
            if event_id:
                WebhookEvent.objects.create(event_id=event_id, event_type=event_type, reference=sub_code, payload=data)
            logger.info(
                '%s ignored: event for non-current subscription code %s',
                event_type, sub_code,
            )
            return {'success': True, 'message': f'{event_type} ignored: event for non-current subscription code {sub_code}.'}

        if sub.cancel_at_period_end:
            # Our own disable call. Status stays active until period_end and
            # the schedule flags stay as the vendor left them.
            if event_id:
                WebhookEvent.objects.create(event_id=event_id, event_type=event_type, reference=sub_code, payload=data)
            logger.info(
                '%s acknowledged for subscription %s: already scheduled to end at '
                'period_end, no change (code %s)',
                event_type, sub.pk, sub_code,
            )
            return {
                'success': True,
                'message': f'{event_type} acknowledged; subscription {sub.pk} is scheduled to end at period_end.',
            }

        if event_type == 'subscription.not_renew':
            # Not scheduled to end and not one of ours: record it and log it,
            # but change nothing - no local rule depends on this event.
            if event_id:
                WebhookEvent.objects.create(event_id=event_id, event_type=event_type, reference=sub_code, payload=data)
            logger.info(
                'subscription.not_renew acknowledged for subscription %s: '
                'no local change (code %s)',
                sub.pk, sub_code,
            )
            return {'success': True, 'message': f'subscription.not_renew acknowledged for sub {sub_code}.'}

        # cancel_at_period_end is False: disabled from outside our UI.
        subscription_service.disable_subscription(sub)
        if event_id:
            WebhookEvent.objects.create(event_id=event_id, event_type=event_type, reference=sub_code, payload=data)
        return {'success': True, 'message': f'subscription.disable processed for sub {sub_code}.'}

    # ---- charge.success ----
    if event_type == 'charge.success':
        # Check for initial payment first (metadata.subscription_code)
        metadata = data.get('metadata', {}) or {}
        meta_sub_code = metadata.get('subscription_code', '')

        if meta_sub_code:
            # Initial subscription payment
            try:
                sub = Subscription.objects.get(paystack_subscription_code=meta_sub_code)
            except Subscription.DoesNotExist:
                sub = None
            except Subscription.MultipleObjectsReturned:
                sub = Subscription.objects.filter(paystack_subscription_code=meta_sub_code).first()

            if sub is None:
                # The Paystack code is not the one on file.  For a first-time
                # subscribe or a basic -> premium upgrade that is expected:
                # Paystack created a NEW subscription for this vendor.  Resolve
                # the vendor from the vendor_id metadata we send at checkout.
                sub = _subscription_for_vendor_id(metadata.get('vendor_id', ''))
                if sub is None:
                    return {'success': False, 'message': f'No subscription for code {meta_sub_code}.'}

            # Determine plan from Paystack plan code in payload
            plan = plan_identifier
            if not plan:
                # Fallback: infer from amount
                amount = data.get('amount', 0)
                plan = 'premium' if amount >= 300000 else 'basic'

            customer_data = data.get('customer') or {}
            paystack_args = {
                'customer_code': customer_data.get('customer_code', ''),
                'subscription_code': meta_sub_code,
                'plan_code': paystack_plan_code,
            }

            if plan == 'premium' and sub.plan == 'basic':
                # Basic -> premium upgrade: the old Basic Paystack subscription
                # is captured and disabled inside the service.
                changed = subscription_service.upgrade_subscription(sub, paystack_args)
            else:
                changed = subscription_service.activate_subscription(sub, paystack_args, plan=plan)

            if event_id:
                WebhookEvent.objects.create(event_id=event_id, event_type=event_type, reference=meta_sub_code, payload=data)
            kind = 'upgrade' if changed else 'replay'
            return {'success': True, 'message': f'charge.success (initial) {kind} processed for sub {meta_sub_code}.'}

        # Recurring subscription payment (data.subscription.subscription_code)
        if sub_code:
            try:
                sub = Subscription.objects.get(paystack_subscription_code=sub_code)
            except Subscription.DoesNotExist:
                return {'success': False, 'message': f'No subscription for code {sub_code}.'}
            subscription_service.handle_successful_payment(sub)
            if event_id:
                WebhookEvent.objects.create(event_id=event_id, event_type=event_type, reference=sub_code, payload=data)
            return {'success': True, 'message': f'charge.success (recurring) processed for sub {sub_code}.'}

    # ---- subscription.deactivate (Paystack may send this for expired subs) ----
    if event_type == 'subscription.deactivate' and sub_code:
        try:
            sub = Subscription.objects.get(paystack_subscription_code=sub_code)
        except Subscription.DoesNotExist:
            return {'success': False, 'message': f'No subscription for code {sub_code}.'}
        subscription_service.disable_subscription(sub)
        if event_id:
            WebhookEvent.objects.create(event_id=event_id, event_type=event_type, reference=sub_code, payload=data)
        return {'success': True, 'message': f'subscription.deactivate processed for sub {sub_code}.'}

    # ---- Unknown / non-subscription event ----
    if event_id:
        WebhookEvent.objects.create(event_id=event_id, event_type=event_type, payload=data)
    return {'success': True, 'message': f'Event {event_type} acknowledged (not a subscription event).'}


# Module-level singleton (stateless — safe to reuse)
subscription_service = SubscriptionService()
