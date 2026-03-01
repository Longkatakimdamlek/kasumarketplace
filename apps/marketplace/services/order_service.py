"""
Order Service
Atomic order creation after payment verification.
Splits cart into MainOrder + SubOrders (one per store).
Credits vendor wallets as PENDING.
Full rollback on any failure — no partial orders.
"""

from django.db import transaction
from django.utils import timezone
from datetime import timedelta
from decimal import Decimal

from apps.marketplace.models import (
    MainOrder,
    SubOrder,
    SubOrderItem,
    PaymentTransaction,
)
from apps.marketplace.services.cart_service import clear_cart
from apps.marketplace.services.wallet_service import credit_pending


def create_orders_from_cart(cart, payment_transaction, delivery_data: dict) -> dict:
    """
    Atomically create MainOrder + SubOrders from a verified cart.

    Called only after Paystack server-side verification succeeds.
    If any step fails, the entire transaction rolls back.

    Args:
        cart: Cart instance (with items)
        payment_transaction: PaymentTransaction instance (status=SUCCESS)
        delivery_data: dict with keys:
            - delivery_address (str)
            - delivery_city (str)
            - delivery_state (str)
            - delivery_phone (str)

    Returns dict with keys:
        - success (bool)
        - message (str)
        - main_order (MainOrder instance or None)
    """
    if cart.is_empty:
        return {
            'success': False,
            'message': 'Cart is empty.',
            'main_order': None,
        }

    items_by_store = cart.get_items_by_store()
    grand_total = cart.grand_total

    try:
        with transaction.atomic():
            # ---- CREATE MAIN ORDER ----
            main_order = MainOrder.objects.create(
                reference=payment_transaction.reference,
                buyer=payment_transaction.user,
                total=grand_total,
                payment_status='SUCCESS',
                delivery_address=delivery_data.get('delivery_address', ''),
                delivery_city=delivery_data.get('delivery_city', ''),
                delivery_state=delivery_data.get('delivery_state', ''),
                delivery_phone=delivery_data.get('delivery_phone', ''),
            )

            # Link buyer to payment transaction if not already set
            if not payment_transaction.user and cart.user:
                payment_transaction.user = cart.user
                payment_transaction.save(update_fields=['user'])

            # ---- CREATE ONE SUBORDER PER STORE ----
            for store, items in items_by_store.items():
                store_subtotal = sum(
                    item.unit_price * Decimal(item.quantity) for item in items
                )

                sub_order = SubOrder.objects.create(
                    main_order=main_order,
                    store=store,
                    subtotal=store_subtotal,
                    status='PENDING_VENDOR',
                    payment_status='SUCCESS',
                    vendor_deadline=timezone.now() + timedelta(hours=48),
                )

                # ---- CREATE SUBORDER ITEMS (price snapshot) ----
                for item in items:
                    SubOrderItem.objects.create(
                        sub_order=sub_order,
                        product=item.product,
                        product_title=item.product.title,
                        unit_price=item.unit_price,
                        quantity=item.quantity,
                        subtotal=item.unit_price * Decimal(item.quantity),
                    )
                    
                    # ---- REDUCE PRODUCT INVENTORY ----
                    product = item.product
                    if product.track_inventory:
                        # Reduce stock by quantity purchased
                        product.stock_quantity = max(0, product.stock_quantity - item.quantity)
                        product.save(update_fields=['stock_quantity'])

                # ---- CREDIT VENDOR WALLET AS PENDING ----
                wallet_result = credit_pending(
                    sub_order=sub_order,
                    main_order=main_order,
                )
                if not wallet_result['success']:
                    # Wallet credit failed — rollback everything
                    raise Exception(
                        f"Wallet credit failed for store {store.store_name}: "
                        f"{wallet_result['message']}"
                    )

            # ---- VERIFY TOTAL INTEGRITY ----
            if not main_order.verify_total():
                raise Exception(
                    f"Order total mismatch. "
                    f"MainOrder.total={main_order.total}, "
                    f"SubOrder sum={sum(s.subtotal for s in main_order.suborders.all())}"
                )

            # ---- CLEAR CART ----
            clear_cart(cart)

            return {
                'success': True,
                'message': 'Order created successfully.',
                'main_order': main_order,
            }

    except Exception as e:
        return {
            'success': False,
            'message': str(e),
            'main_order': None,
        }


def get_order_for_buyer(order_number: str, buyer) -> MainOrder | None:
    """
    Safely retrieve a MainOrder for a specific buyer.
    Returns None if order doesn't belong to buyer.
    """
    try:
        return MainOrder.objects.get(
            order_number=order_number,
            buyer=buyer
        )
    except MainOrder.DoesNotExist:
        return None


def get_suborder_for_vendor(suborder_id: int, vendor_profile):
    """
    Safely retrieve a SubOrder for a specific vendor.
    Returns None if SubOrder doesn't belong to vendor's store.
    """
    try:
        return SubOrder.objects.select_related(
            'main_order', 'store', 'store__vendor'
        ).get(
            pk=suborder_id,
            store__vendor=vendor_profile
        )
    except SubOrder.DoesNotExist:
        return None


def confirm_suborder(sub_order: SubOrder, buyer) -> dict:
    """
    Buyer clicks YES — Release Payment.
    Marks SubOrder as CONFIRMED and records confirmation timestamp.
    Wallet release to AVAILABLE is handled by wallet_service (24h hold).

    Args:
        sub_order: SubOrder instance
        buyer: User instance (must be the buyer of this order)

    Returns dict with keys:
        - success (bool)
        - message (str)
    """
    # Verify buyer owns this order
    if sub_order.main_order.buyer != buyer:
        return {'success': False, 'message': 'Unauthorised.'}

    # Can only confirm ACCEPTED orders
    if sub_order.status != 'ACCEPTED':
        return {
            'success': False,
            'message': f'Cannot confirm order with status {sub_order.status}.'
        }

    sub_order.status = 'CONFIRMED'
    sub_order.confirmed_at = timezone.now()
    sub_order.save(update_fields=['status', 'confirmed_at', 'updated_at'])

    return {
        'success': True,
        'message': 'Payment released. Thank you for confirming your order.'
    }


def open_dispute(sub_order: SubOrder, buyer, reason: str) -> dict:
    """
    Buyer clicks REPORT ISSUE.
    Creates a Dispute record and locks wallet funds.
    Buttons are disabled after this — no further buyer action.

    Args:
        sub_order: SubOrder instance
        buyer: User instance
        reason: Buyer's description of the issue

    Returns dict with keys:
        - success (bool)
        - message (str)
    """
    from apps.marketplace.models import Dispute

    # Verify buyer owns this order
    if sub_order.main_order.buyer != buyer:
        return {'success': False, 'message': 'Unauthorised.'}

    # Can only dispute ACCEPTED orders
    if sub_order.status != 'ACCEPTED':
        return {
            'success': False,
            'message': f'Cannot dispute order with status {sub_order.status}.'
        }

    # Check dispute doesn't already exist
    if Dispute.objects.filter(sub_order=sub_order).exists():
        return {'success': False, 'message': 'Dispute already opened.'}

    with transaction.atomic():
        Dispute.objects.create(
            sub_order=sub_order,
            opened_by=buyer,
            reason=reason,
            status='OPEN',
        )
        sub_order.status = 'DISPUTED'
        sub_order.save(update_fields=['status', 'updated_at'])

    return {
        'success': True,
        'message': 'Dispute opened. Our team will review and contact you.'
    }