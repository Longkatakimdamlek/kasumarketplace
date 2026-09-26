"""
Subscription Billing Service
Handles Paystack recurring billing, webhook processing, and grace-period logic.

Env vars required:
  PAYSTACK_SECRET_KEY
  PAYSTACK_SUBSCRIPTION_PLAN_CODE  (set by Remedy)

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
from django.utils import timezone

from apps.vendors.models import Subscription
from apps.vendors.services.notification_dispatch import create_notification

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
GRACE_PERIOD_DAYS = 7
MONTHLY_PRICE_KOBO = 300000  # ₦3,000 in kobo
MAX_RETRY_ATTEMPTS = 3


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
        self.plan_code = getattr(settings, 'PAYSTACK_SUBSCRIPTION_PLAN_CODE', '')

        if not self.secret_key:
            logger.warning('PAYSTACK_SECRET_KEY not set — billing calls will fail.')
        if not self.plan_code:
            logger.warning('PAYSTACK_SUBSCRIPTION_PLAN_CODE not set — billing calls will fail.')

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

    def initialize_subscription(self, email: str, metadata: Optional[Dict] = None) -> Tuple[bool, Dict]:
        """
        Initialize a Paystack subscription payment.
        Returns (success, {authorization_url, reference, ...}).
        """
        payload = {
            'email': email,
            'plan': self.plan_code,
            'amount': MONTHLY_PRICE_KOBO,
            'currency': 'NGN',
        }
        if metadata:
            payload['metadata'] = metadata

        result = self._request('POST', '/transaction/initialize', payload)

        return True, {
            'authorization_url': result.get('authorization_url', ''),
            'access_code': result.get('access_code', ''),
            'reference': result.get('reference', ''),
        }

    # ------------------------------------------------------------------
    # Subscription status helpers
    # ------------------------------------------------------------------

    def activate_subscription(self, sub: Subscription, paystack_data: Dict) -> None:
        """
        Mark subscription as active after successful first payment.
        paystack_data should contain: paystack_customer_code, paystack_subscription_code, etc.
        """
        now = timezone.now()
        sub.status = 'active'
        sub.period_end = now + timedelta(days=30)
        sub.grace_ends_at = None
        sub.paystack_customer_code = paystack_data.get('customer_code', sub.paystack_customer_code)
        sub.paystack_subscription_code = paystack_data.get('subscription_code', sub.paystack_subscription_code)
        sub.paystack_plan_code = paystack_data.get('plan_code', sub.paystack_plan_code)
        sub.retry_count = 0
        sub.last_payment_attempt_at = now
        sub.save(update_fields=[
            'status', 'period_end', 'grace_ends_at',
            'paystack_customer_code', 'paystack_subscription_code',
            'paystack_plan_code', 'retry_count', 'last_payment_attempt_at',
            'updated_at',
        ])
        logger.info('Subscription %s activated for vendor %s', sub.pk, sub.vendor_id)

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
        Called when Paystack sends subscription.disable webhook.
        Cancels the subscription; grace period still applies.
        """
        now = timezone.now()
        sub.status = 'cancelled'
        sub.grace_ends_at = now + timedelta(days=GRACE_PERIOD_DAYS)
        sub.save(update_fields=['status', 'grace_ends_at', 'updated_at'])
        logger.info('Subscription %s disabled via webhook', sub.pk)

    # ------------------------------------------------------------------
    # Grace-period checker (called by management command / cron)
    # ------------------------------------------------------------------

    def expire_grace_periods(self) -> int:
        """
        Find subscriptions in past_due/cancelled status whose grace_ends_at
        has passed, and set them to 'expired'.  Returns the count of
        subscriptions expired.
        """
        now = timezone.now()
        qs = Subscription.objects.filter(
            status__in=['past_due', 'cancelled'],
            grace_ends_at__isnull=False,
            grace_ends_at__lte=now,
        )
        count = qs.update(status='expired')
        if count:
            logger.info('Expired %d subscription(s) past grace period', count)
        return count


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


def process_subscription_webhook(event_type: str, data: dict, event_id: str = '') -> dict:
    """
    Handle vendor subscription billing events from Paystack.

    Dispatches to:
    - charge.success (initial: metadata.subscription_code; recurring: data.subscription.subscription_code)
      → activate_subscription (initial) or handle_successful_payment (recurring)
    - invoice.payment_failed → handle_failed_payment
    - subscription.disable → disable_subscription

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
    sub_code = ''
    sub_data = data.get('subscription') or {}
    if isinstance(sub_data, dict):
        sub_code = sub_data.get('subscription_code', '')

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

    # ---- subscription.disable ----
    if event_type == 'subscription.disable' and sub_code:
        try:
            sub = Subscription.objects.get(paystack_subscription_code=sub_code)
        except Subscription.DoesNotExist:
            return {'success': False, 'message': f'No subscription for code {sub_code}.'}
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
                return {'success': False, 'message': f'No subscription for code {meta_sub_code}.'}
            subscription_service.activate_subscription(sub, {
                'customer_code': data.get('customer', {}).get('customer_code', ''),
                'subscription_code': meta_sub_code,
                'plan_code': data.get('plan', {}).get('plan_code', ''),
            })
            if event_id:
                WebhookEvent.objects.create(event_id=event_id, event_type=event_type, reference=meta_sub_code, payload=data)
            return {'success': True, 'message': f'charge.success (initial) processed for sub {meta_sub_code}.'}

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
