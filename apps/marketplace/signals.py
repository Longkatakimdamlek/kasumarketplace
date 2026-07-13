"""
Marketplace Signals
- BuyerProfile auto-create on registration
- Cart merge on login
- Refund trigger on cancellation/rejection
- Email notifications on order status changes
"""

from django.db.models.signals import post_save
from django.contrib.auth.signals import user_logged_in
from django.dispatch import receiver
from django.contrib.auth import get_user_model
import logging

logger = logging.getLogger(__name__)

User = get_user_model()
from .models import SubOrderItem


@receiver(post_save, sender=User)
def create_buyer_profile(sender, instance, created, **kwargs):
    try:
        if created and instance.role == 'buyer':
            from apps.users.models import BuyerProfile
            profile, new = BuyerProfile.objects.get_or_create(user=instance)
            if new:
                logger.info(f"BuyerProfile created for {instance.email}")
    except Exception as e:
        logger.error(f"Error creating BuyerProfile for {instance.email}: {str(e)}", exc_info=True)
        # Don't re-raise to prevent breaking user creation


@receiver(user_logged_in)
def merge_cart_on_login(sender, request, user, **kwargs):
    """Move anonymous session cart into the logged-in user's cart.

    Django's ``login()`` call rotates the session key (flushes the
    session) before emitting ``user_logged_in``.  That means by the time
    the signal is handled ``request.session.session_key`` is new and the
    previous anonymous cart cannot be found.

    To work around this we preserve the pre‑login key via middleware
    (``PreserveSessionKeyMiddleware``) and fall back to it when available.
    This covers both the custom login view and social / allauth logins.
    """
    try:
        from apps.marketplace.models import Cart

        # prefer the original key stored by middleware
        session_key = getattr(request, '_pre_login_session_key', None) or request.session.session_key
        if not session_key:
            return

        try:
            anon_cart = Cart.objects.get(session_key=session_key, user__isnull=True)
        except Cart.DoesNotExist:
            return

        try:
            user_cart = Cart.objects.get(user=user)
        except Cart.DoesNotExist:
            anon_cart.user = user
            anon_cart.save(update_fields=['user'])
            return

        for anon_item in anon_cart.items.all():
            existing = user_cart.items.filter(product=anon_item.product).first()
            if existing:
                existing.quantity += anon_item.quantity
                existing.save(update_fields=['quantity'])
            else:
                anon_item.cart = user_cart
                anon_item.save(update_fields=['cart'])

        anon_cart.delete()
        logger.info(f"Cart merged for user {user.email}")
    except Exception as e:
        logger.error(f"Error merging cart for {user.email}: {str(e)}", exc_info=True)
        # Don't re-raise to prevent breaking login


@receiver(post_save, sender='marketplace.SubOrder')
def handle_suborder_status_change(sender, instance, created, **kwargs):
    if created:
        return

    status = instance.status

    if status == 'CONFIRMED' and instance.confirmed_at:
        from apps.marketplace.services.wallet_service import schedule_wallet_release
        schedule_wallet_release(instance)
        try:
            from apps.marketplace.services.email_service import send_order_confirmed
            send_order_confirmed(instance)
        except Exception:
            pass

    elif status in ['CANCELLED', 'REJECTED']:
        from apps.marketplace.services.refund_service import trigger_refund_if_needed
        trigger_refund_if_needed(instance)
        try:
            if status == 'CANCELLED':
                from apps.marketplace.services.email_service import send_order_cancelled_timeout
                send_order_cancelled_timeout(instance)
            elif status == 'REJECTED':
                from apps.marketplace.services.email_service import send_order_rejected
                send_order_rejected(instance)
        except Exception:
            pass


@receiver(post_save, sender='marketplace.Dispute')
def handle_dispute_opened(sender, instance, created, **kwargs):
    if created:
        try:
            from apps.marketplace.services.email_service import send_dispute_opened
            send_dispute_opened(instance)
        except Exception:
            pass


@receiver(post_save, sender='marketplace.SubOrder')
def notify_vendor_new_suborder(sender, instance, created, **kwargs):
    """Create a Notification for the vendor when a new SubOrder arrives."""
    if not created:
        return
    try:
        from apps.vendors.models import Notification
        vendor = instance.store.vendor  # Store → VendorProfile
        Notification.objects.create(
            vendor=vendor,
            notification_type='order',
            title='New Order Received! 🛒',
            message=f'You have a new order worth ₦{instance.subtotal} from {instance.main_order.buyer.get_full_name() or "a customer"}. Please accept or reject it.',
            link=f'/vendors/orders/{instance.id}/',
        )
    except Exception as e:
        logger.error(f"Error creating new order notification: {e}", exc_info=True)


@receiver(post_save, sender='marketplace.SubOrderItem')
def reduce_stock_on_suborder_item(sender, instance, created, **kwargs):
    """Reduce product stock immediately on order placement; update sales_count from confirmed orders only."""
    if not created:
        return
    try:
        product = instance.product
        if not product.track_inventory:
            return

        if product.stock_quantity >= instance.quantity:
            product.stock_quantity -= instance.quantity
            if product.stock_quantity == 0:
                product.status = 'out_of_stock'
            product.save(update_fields=['stock_quantity', 'status'])
        else:
            logger.warning(f"Insufficient stock for {product.title}: have {product.stock_quantity}, need {instance.quantity}")

        from django.db.models import Sum
        product.sales_count = SubOrderItem.objects.filter(
            product=product,
            sub_order__status='CONFIRMED'
        ).aggregate(total=Sum('quantity'))['total'] or 0
        product.save(update_fields=['sales_count'])

    except Exception as e:
        logger.error(f"Error reducing stock for SubOrderItem {instance.id}: {e}", exc_info=True)