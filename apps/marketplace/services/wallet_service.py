"""
Wallet Service
Manages vendor wallet credits from marketplace orders.

Flow:
1. Payment verified → credit_pending() → wallet.pending_balance += subtotal
2. Buyer confirms → schedule_wallet_release() → after 24h hold → release_to_available()
3. Refund triggered → reverse_pending_credit() → wallet.pending_balance -= subtotal
"""

from django.db import transaction
from django.utils import timezone
from datetime import timedelta

from apps.marketplace.models import WalletTransaction


def credit_pending(sub_order, main_order) -> dict:
    """
    Credit vendor wallet with PENDING amount after payment verification.

    IDEMPOTENCY: Checks WalletTransaction unique_together (reference + sub_order)
    before creating. Safe to call multiple times — only credits once.

    Args:
        sub_order: SubOrder instance
        main_order: MainOrder instance

    Returns dict:
        - success (bool)
        - message (str)
    """
    try:
        vendor_profile = sub_order.store.vendor
        wallet = vendor_profile.wallet
    except Exception as e:
        return {
            'success': False,
            'message': f'Could not find vendor wallet: {str(e)}'
        }

    # ---- IDEMPOTENCY CHECK ----
    already_credited = WalletTransaction.objects.filter(
        sub_order=sub_order,
        reference=main_order.reference,
        transaction_type='PENDING_CREDIT',
    ).exists()

    if already_credited:
        return {
            'success': True,
            'message': 'Already credited (idempotent skip).'
        }

    try:
        with transaction.atomic():
            # Create wallet transaction record
            WalletTransaction.objects.create(
                wallet=wallet,
                sub_order=sub_order,
                transaction_type='PENDING_CREDIT',
                amount=sub_order.subtotal,
                status='PENDING',
                reference=main_order.reference,
                note=f"Pending credit for order {main_order.order_number}",
            )

            # Update wallet pending balance
            wallet.pending_balance += sub_order.subtotal
            wallet.save(update_fields=['pending_balance', 'updated_at'])

        return {
            'success': True,
            'message': f'₦{sub_order.subtotal:,.2f} credited as PENDING to {vendor_profile.user.email}.'
        }

    except Exception as e:
        return {
            'success': False,
            'message': f'Wallet credit failed: {str(e)}'
        }


def schedule_wallet_release(sub_order) -> None:
    """
    Called by signal when SubOrder is CONFIRMED.
    Records the confirmation time — actual release happens
    when release_to_available() is called after 24h.

    Since we have no Celery, this is called lazily:
    - Admin or a management command checks confirmed_at + 24h
    - Or vendor dashboard triggers it when they view their wallet

    For MVP: release_to_available() is called from vendor wallet view.
    """
    # Just log — actual release is lazy (no Celery)
    pass


def release_to_available(sub_order) -> dict:
    """
    Move vendor wallet funds from PENDING to AVAILABLE.
    Called 24 hours after buyer confirmation.

    Can be called from:
    - Vendor wallet view (lazy check)
    - Management command (batch release)

    Args:
        sub_order: SubOrder instance (must be CONFIRMED)

    Returns dict:
        - success (bool)
        - message (str)
        - released (bool) — False if 24h not yet elapsed
    """
    if sub_order.status != 'CONFIRMED':
        return {
            'success': False,
            'message': 'SubOrder is not CONFIRMED.',
            'released': False,
        }

    if not sub_order.confirmed_at:
        return {
            'success': False,
            'message': 'No confirmation timestamp found.',
            'released': False,
        }

    # Enforce 24-hour hold
    release_time = sub_order.confirmed_at + timedelta(hours=24)
    if timezone.now() < release_time:
        remaining = release_time - timezone.now()
        hours = int(remaining.total_seconds() // 3600)
        return {
            'success': True,
            'message': f'Funds available in {hours}h.',
            'released': False,
        }

    # Check if already released
    already_released = WalletTransaction.objects.filter(
        sub_order=sub_order,
        transaction_type='AVAILABLE_CREDIT',
        status='AVAILABLE',
    ).exists()

    if already_released:
        return {
            'success': True,
            'message': 'Already released (idempotent skip).',
            'released': True,
        }

    try:
        vendor_profile = sub_order.store.vendor
        wallet = vendor_profile.wallet
    except Exception as e:
        return {
            'success': False,
            'message': f'Could not find vendor wallet: {str(e)}',
            'released': False,
        }

    try:
        with transaction.atomic():
            # Create AVAILABLE_CREDIT transaction record
            WalletTransaction.objects.create(
                wallet=wallet,
                sub_order=sub_order,
                transaction_type='AVAILABLE_CREDIT',
                amount=sub_order.subtotal,
                status='AVAILABLE',
                reference=sub_order.main_order.reference,
                note=f"Released to available for order {sub_order.main_order.order_number}",
            )

            # Move from pending_balance to available balance
            wallet.pending_balance -= sub_order.subtotal
            wallet.balance += sub_order.subtotal
            wallet.total_earned += sub_order.subtotal
            wallet.save(update_fields=[
                'pending_balance', 'balance',
                'total_earned', 'updated_at'
            ])

        return {
            'success': True,
            'message': f'₦{sub_order.subtotal:,.2f} released to available balance.',
            'released': True,
        }

    except Exception as e:
        return {
            'success': False,
            'message': f'Release failed: {str(e)}',
            'released': False,
        }


def reverse_pending_credit(sub_order) -> dict:
    """
    Reverse a PENDING wallet credit when a SubOrder is refunded.
    Called by refund_service after successful Paystack refund.

    Args:
        sub_order: SubOrder instance

    Returns dict:
        - success (bool)
        - message (str)
    """
    # Check if there's a pending credit to reverse
    pending_tx = WalletTransaction.objects.filter(
        sub_order=sub_order,
        transaction_type='PENDING_CREDIT',
        status='PENDING',
    ).first()

    if not pending_tx:
        # Nothing to reverse
        return {
            'success': True,
            'message': 'No pending credit to reverse.'
        }

    try:
        vendor_profile = sub_order.store.vendor
        wallet = vendor_profile.wallet
    except Exception as e:
        return {
            'success': False,
            'message': f'Could not find vendor wallet: {str(e)}'
        }

    try:
        with transaction.atomic():
            # Create REVERSAL transaction record
            WalletTransaction.objects.create(
                wallet=wallet,
                sub_order=sub_order,
                transaction_type='REVERSAL',
                amount=sub_order.subtotal,
                status='REVERSED',
                reference=sub_order.main_order.reference,
                note=f"Reversal for refunded order {sub_order.main_order.order_number}",
            )

            # Mark original pending credit as reversed
            pending_tx.status = 'REVERSED'
            pending_tx.save(update_fields=['status', 'updated_at'])

            # Deduct from pending balance
            wallet.pending_balance -= sub_order.subtotal
            wallet.save(update_fields=['pending_balance', 'updated_at'])

        return {
            'success': True,
            'message': f'₦{sub_order.subtotal:,.2f} pending credit reversed.'
        }

    except Exception as e:
        return {
            'success': False,
            'message': f'Reversal failed: {str(e)}'
        }