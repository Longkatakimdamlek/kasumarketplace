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

User = get_user_model()


@receiver(post_save, sender=User)
def create_buyer_profile(sender, instance, created, **kwargs):
    if created and instance.role == 'buyer':
        from apps.users.models import BuyerProfile
        BuyerProfile.objects.get_or_create(user=instance)


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