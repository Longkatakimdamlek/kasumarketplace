"""
Refund Service
Handles all refund processing for SubOrders.

Trigger conditions:
- Vendor rejects order
- Vendor no response after 48h (auto-cancel)
- Admin resolves dispute in buyer's favour

IDEMPOTENCY: One RefundRecord per SubOrder (OneToOneField).
Prevents duplicate Paystack refund API calls.
"""

from django.db import transaction
from django.utils import timezone

from apps.marketplace.models import RefundRecord, SubOrder
from apps.marketplace.services.payment_service import call_paystack_refund
from apps.marketplace.services.wallet_service import reverse_pending_credit


def trigger_refund_if_needed(sub_order: SubOrder) -> dict:
    """
    Called by signal when SubOrder status becomes CANCELLED or REJECTED.
    Checks if a refund is needed and triggers it.

    Args:
        sub_order: SubOrder instance

    Returns dict:
        - success (bool)
        - message (str)
    """
    # Only refund if payment was successful
    if sub_order.payment_status != 'SUCCESS':
        return {
            'success': True,
            'message': 'No payment to refund.'
        }

    # Map status to refund reason
    reason_map = {
        'CANCELLED': 'VENDOR_TIMEOUT',
        'REJECTED': 'VENDOR_REJECTED',
    }
    reason = reason_map.get(sub_order.status)

    if not reason:
        return {
            'success': False,
            'message': f'No refund reason for status {sub_order.status}.'
        }

    return process_refund(sub_order=sub_order, reason=reason)


def process_refund(sub_order: SubOrder, reason: str, note: str = '') -> dict:
    """
    Process a full refund for a SubOrder.

    IDEMPOTENCY:
    - Checks for existing RefundRecord with PROCESSING or COMPLETED status
    - If exists: returns existing status, no duplicate API call

    Steps:
    1. Check idempotency
    2. Create RefundRecord (PROCESSING)
    3. Reverse pending wallet credit
    4. Call Paystack refund API
    5. Update RefundRecord + SubOrder status

    Args:
        sub_order: SubOrder instance
        reason: One of REASON_CHOICES from RefundRecord
        note: Optional admin note

    Returns dict:
        - success (bool)
        - message (str)
        - refund_record (RefundRecord or None)
    """
    # ---- IDEMPOTENCY CHECK ----
    existing_refund = RefundRecord.objects.filter(
        sub_order=sub_order,
        status__in=['PROCESSING', 'COMPLETED']
    ).first()

    if existing_refund:
        return {
            'success': True,
            'message': f'Refund already {existing_refund.status.lower()}.',
            'refund_record': existing_refund,
        }

    # ---- CREATE REFUND RECORD ----
    try:
        with transaction.atomic():
            refund_record = RefundRecord.objects.create(
                sub_order=sub_order,
                reason=reason,
                status='PROCESSING',
                amount=sub_order.subtotal,
                note=note,
            )
    except Exception as e:
        return {
            'success': False,
            'message': f'Could not create refund record: {str(e)}',
            'refund_record': None,
        }

    # ---- REVERSE WALLET CREDIT ----
    wallet_result = reverse_pending_credit(sub_order)
    if not wallet_result['success']:
        refund_record.status = 'FAILED'
        refund_record.note = f"Wallet reversal failed: {wallet_result['message']}"
        refund_record.save(update_fields=['status', 'note', 'updated_at'])
        return {
            'success': False,
            'message': wallet_result['message'],
            'refund_record': refund_record,
        }

    # ---- CALL PAYSTACK REFUND API ----
    reference = sub_order.main_order.reference
    paystack_result = call_paystack_refund(
        reference=reference,
        amount_naira=sub_order.subtotal,
    )

    # ---- UPDATE RECORDS ----
    with transaction.atomic():
        refund_record.paystack_response = paystack_result.get('response', {})

        if paystack_result['success']:
            refund_record.status = 'COMPLETED'
            refund_record.completed_at = timezone.now()
            refund_record.save(update_fields=[
                'status', 'paystack_response',
                'completed_at', 'updated_at'
            ])

            # Mark SubOrder as REFUNDED
            sub_order.payment_status = 'REFUNDED'
            sub_order.status = 'REFUNDED'
            sub_order.save(update_fields=[
                'status', 'payment_status', 'updated_at'
            ])

            return {
                'success': True,
                'message': f'₦{sub_order.subtotal:,.2f} refund processed successfully.',
                'refund_record': refund_record,
            }
        else:
            refund_record.status = 'FAILED'
            refund_record.note = paystack_result['message']
            refund_record.save(update_fields=[
                'status', 'paystack_response',
                'note', 'updated_at'
            ])

            return {
                'success': False,
                'message': f"Refund failed: {paystack_result['message']}",
                'refund_record': refund_record,
            }


def get_refund_status(sub_order: SubOrder) -> dict:
    """
    Get the current refund status for a SubOrder.
    Safe to call any time — returns status without side effects.

    Returns dict:
        - has_refund (bool)
        - status (str or None)
        - amount (Decimal or None)
        - completed_at (datetime or None)
    """
    try:
        refund = sub_order.refund_record
        return {
            'has_refund': True,
            'status': refund.status,
            'amount': refund.amount,
            'completed_at': refund.completed_at,
        }
    except RefundRecord.DoesNotExist:
        return {
            'has_refund': False,
            'status': None,
            'amount': None,
            'completed_at': None,
        }