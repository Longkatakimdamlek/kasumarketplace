"""
apps/vendors/services/wallet_service.py

Vendor wallet operations:
1. release_to_available(sub_order)  — move PENDING → AVAILABLE after 24h hold
2. get_wallet_summary(vendor)       — returns wallet stats for dashboard
3. release_all_due(vendor)          — batch release all eligible pending credits
"""

from django.utils import timezone
from django.db import transaction as db_transaction

from apps.marketplace.models import WalletTransaction, SubOrder


def release_to_available(sub_order) -> dict:
    """
    Move vendor wallet funds from PENDING to AVAILABLE.
    Called lazily from the vendor wallet view after 24h hold.
    """
    if sub_order.status != 'CONFIRMED':
        return {'success': False, 'message': f'SubOrder is {sub_order.status}, not CONFIRMED.', 'released': False}

    if not sub_order.confirmed_at:
        return {'success': False, 'message': 'No confirmed_at timestamp.', 'released': False}

    hold_until = sub_order.confirmed_at + timezone.timedelta(hours=24)
    if timezone.now() < hold_until:
        remaining = hold_until - timezone.now()
        hours = int(remaining.total_seconds() // 3600)
        mins = int((remaining.total_seconds() % 3600) // 60)
        return {'success': True, 'message': f'Funds available in {hours}h {mins}m.', 'released': False}

    # Idempotency check
    already_released = WalletTransaction.objects.filter(
        sub_order=sub_order,
        transaction_type='AVAILABLE_CREDIT',
        status='AVAILABLE',
    ).exists()

    if already_released:
        return {'success': True, 'message': 'Already released.', 'released': True}

    try:
        vendor_profile = sub_order.store.vendor
        wallet = vendor_profile.wallet
    except Exception as e:
        return {'success': False, 'message': f'Could not find vendor wallet: {str(e)}', 'released': False}

    try:
        with db_transaction.atomic():
            WalletTransaction.objects.create(
                wallet=wallet,
                sub_order=sub_order,
                transaction_type='AVAILABLE_CREDIT',
                amount=sub_order.subtotal,
                status='AVAILABLE',
                reference=sub_order.main_order.reference + '-RELEASE',
                note=f"Released to available for order {sub_order.main_order.order_number}",
            )
            wallet.pending_balance -= sub_order.subtotal
            wallet.balance += sub_order.subtotal
            wallet.total_earned += sub_order.subtotal
            wallet.save(update_fields=['pending_balance', 'balance', 'total_earned', 'updated_at'])

        return {'success': True, 'message': f'₦{sub_order.subtotal:,.2f} released to available balance.', 'released': True}

    except Exception as e:
        return {'success': False, 'message': f'Release failed: {str(e)}', 'released': False}


def release_all_due(vendor) -> dict:
    """
    Release all CONFIRMED SubOrders past the 24h hold.
    Called lazily when vendor views their wallet.
    """
    try:
        store = vendor.store
    except Exception:
        return {'released_count': 0, 'total_released': 0, 'pending_count': 0}

    confirmed_subs = SubOrder.objects.filter(
        store=store, status='CONFIRMED', confirmed_at__isnull=False,
    )

    released_count = 0
    total_released = 0
    pending_count = 0

    for sub in confirmed_subs:
        result = release_to_available(sub)
        if result.get('released'):
            released_count += 1
            total_released += sub.subtotal
        elif result.get('success') and not result.get('released'):
            pending_count += 1

    return {'released_count': released_count, 'total_released': total_released, 'pending_count': pending_count}


def get_wallet_summary(vendor) -> dict:
    """
    Returns wallet stats for vendor wallet dashboard.
    Triggers lazy release of due funds automatically.
    """
    release_all_due(vendor)

    try:
        wallet = vendor.wallet
    except Exception:
        return {
            'balance': 0, 'pending_balance': 0,
            'total_earned': 0, 'total_withdrawn': 0,
            'recent_transactions': [],
        }

    recent_transactions = WalletTransaction.objects.filter(
        wallet=wallet
    ).order_by('-created_at')[:20]

    return {
        'balance': wallet.balance,
        'pending_balance': wallet.pending_balance,
        'total_earned': wallet.total_earned,
        'total_withdrawn': getattr(wallet, 'total_withdrawn', 0),
        'recent_transactions': recent_transactions,
    }