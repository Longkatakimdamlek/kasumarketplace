"""
Payment Service
Handles all Paystack integration:
- Reference generation
- Server-side transaction verification
- Webhook processing
All amounts stored in Naira internally.
Converted to kobo only when calling Paystack API.
"""

import hmac
import hashlib
import requests
import uuid
from django.conf import settings
from django.utils import timezone
from apps.marketplace.models import PaymentTransaction


PAYSTACK_SECRET_KEY = settings.PAYSTACK_SECRET_KEY
PAYSTACK_BASE_URL = "https://api.paystack.co"


# ==========================================
# REFERENCE GENERATION
# ==========================================

def generate_payment_reference() -> str:
    """
    Generate a unique Paystack payment reference.
    Format: KSM-<UUID4-short>
    Example: KSM-a3f2b1c4d5e6
    """
    unique = uuid.uuid4().hex[:12].upper()
    return f"KSM-{unique}"


# ==========================================
# PAYMENT VERIFICATION
# ==========================================

def verify_payment(reference: str, expected_amount_naira) -> dict:
    """
    Verify a Paystack transaction server-side.
    NEVER trust frontend success callback alone.

    Idempotency:
    - If reference already exists with SUCCESS + orders: return existing
    - If reference exists with PENDING: re-verify
    - If reference does not exist: create + verify

    Args:
        reference: Paystack transaction reference
        expected_amount_naira: Amount buyer should have paid (Decimal/float)

    Returns dict with keys:
        - success (bool)
        - message (str)
        - transaction (PaymentTransaction instance or None)
        - already_processed (bool) — True if duplicate call
    """
    # ---- IDEMPOTENCY CHECK ----
    existing = PaymentTransaction.objects.filter(reference=reference).first()

    if existing:
        if existing.status == 'SUCCESS':
            # Already verified and orders created — return early
            return {
                'success': True,
                'message': 'Payment already verified.',
                'transaction': existing,
                'already_processed': True,
            }
        elif existing.status == 'FAILED':
            # Previously failed — allow re-check with Paystack
            transaction = existing
        else:
            # PENDING — proceed to verify
            transaction = existing
    else:
        # First time seeing this reference
        transaction = PaymentTransaction.objects.create(
            reference=reference,
            amount=expected_amount_naira,
            status='PENDING',
        )

    # ---- CALL PAYSTACK API ----
    try:
        response = requests.get(
            f"{PAYSTACK_BASE_URL}/transaction/verify/{reference}",
            headers={
                "Authorization": f"Bearer {PAYSTACK_SECRET_KEY}",
                "Content-Type": "application/json",
            },
            timeout=30,
        )
        data = response.json()
    except requests.RequestException as e:
        return {
            'success': False,
            'message': f'Could not reach Paystack: {str(e)}',
            'transaction': transaction,
            'already_processed': False,
        }

    # ---- VALIDATE RESPONSE ----
    if not data.get('status'):
        transaction.status = 'FAILED'
        transaction.paystack_response = data
        transaction.save(update_fields=['status', 'paystack_response'])
        return {
            'success': False,
            'message': data.get('message', 'Paystack verification failed.'),
            'transaction': transaction,
            'already_processed': False,
        }

    ps_data = data.get('data', {})
    ps_status = ps_data.get('status')
    ps_amount_kobo = ps_data.get('amount', 0)
    ps_amount_naira = ps_amount_kobo / 100
    ps_currency = ps_data.get('currency', '')

    # Status must be 'success'
    if ps_status != 'success':
        transaction.status = 'FAILED'
        transaction.paystack_response = data
        transaction.save(update_fields=['status', 'paystack_response'])
        return {
            'success': False,
            'message': f'Payment status is {ps_status}.',
            'transaction': transaction,
            'already_processed': False,
        }

    # Currency must be NGN
    if ps_currency != 'NGN':
        transaction.status = 'FAILED'
        transaction.paystack_response = data
        transaction.save(update_fields=['status', 'paystack_response'])
        return {
            'success': False,
            'message': 'Invalid currency. Only NGN accepted.',
            'transaction': transaction,
            'already_processed': False,
        }

    # Amount must match (within 1 kobo tolerance for float safety)
    expected_kobo = int(float(expected_amount_naira) * 100)
    if abs(ps_amount_kobo - expected_kobo) > 1:
        transaction.status = 'FAILED'
        transaction.paystack_response = data
        transaction.save(update_fields=['status', 'paystack_response'])
        return {
            'success': False,
            'message': (
                f'Amount mismatch. Expected ₦{expected_amount_naira}, '
                f'got ₦{ps_amount_naira}.'
            ),
            'transaction': transaction,
            'already_processed': False,
        }

    # ---- ALL CHECKS PASSED ----
    transaction.status = 'SUCCESS'
    transaction.paystack_response = data
    transaction.verified_at = timezone.now()
    transaction.save(update_fields=['status', 'paystack_response', 'verified_at'])

    return {
        'success': True,
        'message': 'Payment verified successfully.',
        'transaction': transaction,
        'already_processed': False,
    }


# ==========================================
# WEBHOOK PROCESSING
# ==========================================

def verify_webhook_signature(payload: bytes, signature: str) -> bool:
    """
    Verify Paystack webhook signature using HMAC SHA512.
    Paystack sends X-Paystack-Signature header with every webhook.

    Args:
        payload: Raw request body (bytes)
        signature: Value of X-Paystack-Signature header

    Returns:
        True if signature is valid, False otherwise
    """
    expected = hmac.new(
        PAYSTACK_SECRET_KEY.encode('utf-8'),
        payload,
        hashlib.sha512
    ).hexdigest()
    return hmac.compare_digest(expected, signature)


def process_webhook(event: dict) -> dict:
    """
    Process a Paystack webhook event idempotently.

    Supported events:
    - charge.success: Mark transaction as SUCCESS

    Args:
        event: Parsed webhook JSON payload

    Returns dict with keys:
        - success (bool)
        - message (str)
    """
    event_type = event.get('event')
    data = event.get('data', {})
    reference = data.get('reference')

    if not reference:
        return {'success': False, 'message': 'No reference in webhook.'}

    # ---- IDEMPOTENCY CHECK ----
    transaction = PaymentTransaction.objects.filter(reference=reference).first()

    if transaction and transaction.webhook_processed:
        return {
            'success': True,
            'message': 'Webhook already processed.',
        }

    if event_type == 'charge.success':
        if transaction:
            if transaction.status != 'SUCCESS':
                transaction.status = 'SUCCESS'
                transaction.paystack_response = data
                transaction.verified_at = timezone.now()
            transaction.webhook_processed = True
            transaction.save(update_fields=[
                'status', 'paystack_response',
                'verified_at', 'webhook_processed'
            ])
        else:
            # Webhook arrived before verify endpoint — create record
            amount_naira = data.get('amount', 0) / 100
            PaymentTransaction.objects.create(
                reference=reference,
                amount=amount_naira,
                status='SUCCESS',
                paystack_response=data,
                verified_at=timezone.now(),
                webhook_processed=True,
            )

        return {'success': True, 'message': 'charge.success processed.'}

    # Unhandled event type — acknowledge but do nothing
    return {'success': True, 'message': f'Event {event_type} acknowledged.'}


# ==========================================
# REFUND API CALL
# ==========================================

def call_paystack_refund(reference: str, amount_naira=None) -> dict:
    """
    Call Paystack refund API for a transaction.

    Args:
        reference: Paystack transaction reference
        amount_naira: Partial refund amount in Naira (None = full refund)

    Returns dict with keys:
        - success (bool)
        - message (str)
        - response (dict) — raw Paystack response
    """
    payload = {"transaction": reference}

    if amount_naira is not None:
        # Paystack refund API expects amount in kobo
        payload["amount"] = int(float(amount_naira) * 100)

    try:
        response = requests.post(
            f"{PAYSTACK_BASE_URL}/refund",
            json=payload,
            headers={
                "Authorization": f"Bearer {PAYSTACK_SECRET_KEY}",
                "Content-Type": "application/json",
            },
            timeout=30,
        )
        data = response.json()
    except requests.RequestException as e:
        return {
            'success': False,
            'message': f'Could not reach Paystack: {str(e)}',
            'response': {},
        }

    if data.get('status'):
        return {
            'success': True,
            'message': 'Refund initiated successfully.',
            'response': data,
        }

    return {
        'success': False,
        'message': data.get('message', 'Refund failed.'),
        'response': data,
    }