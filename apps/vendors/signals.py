"""
Vendor App Signals
Automatically handle wallet creation, store creation, stats updates, notifications, etc.
"""

from django.db.models.signals import post_save, pre_save, post_delete
from django.dispatch import receiver
from django.contrib.auth import get_user_model
from django.utils import timezone
from django.db.models import Sum, Avg, F
import logging

logger = logging.getLogger(__name__)

from .models import (
    VendorProfile, Wallet, Store, Product, Order, OrderItem,
    Transaction, Notification, RefundRequest, CategoryChangeRequest
)

User = get_user_model()


# ==========================================
# USER SIGNALS (CREATE VENDORPROFILE)
# ==========================================

@receiver(post_save, sender=User)
def create_vendor_profile_for_vendor_users(sender, instance, created, **kwargs):
    """
    Automatically create VendorProfile when a vendor User is created
    """
    try:
        if created and hasattr(instance, 'role') and instance.role == 'vendor':
            vendor_profile = VendorProfile.objects.create(user=instance)
            print(f"✅ VendorProfile created for vendor: {instance.email}")
            logger.info(f"VendorProfile created for vendor: {instance.email}")
    except Exception as e:
        logger.error(f"Error creating VendorProfile for {instance.email}: {str(e)}", exc_info=True)


# ==========================================
# VENDOR PROFILE SIGNALS
# ==========================================

@receiver(post_save, sender=VendorProfile)
def create_vendor_wallet(sender, instance, created, **kwargs):
    """
    Automatically create a Wallet when VendorProfile is created
    """
    try:
        if created:
            Wallet.objects.create(
                vendor=instance,
                commission_rate=10.00
            )
            print(f"✓ Wallet created for vendor: {instance.full_name or instance.user.email}")
            logger.info(f"Wallet created for vendor: {instance.user.email}")
    except Exception as e:
        logger.error(f"Error creating Wallet for vendor {instance.user.email}: {str(e)}", exc_info=True)


# ── pre_save: cache old verification_status so post_save can detect real changes ──
@receiver(pre_save, sender=VendorProfile)
def cache_vendor_verification_status(sender, instance, **kwargs):
    """
    Cache the verification_status value from the DB before this save
    so send_verification_notifications can detect genuine state transitions.
    Without this, post_save only sees the new value and fires on every save
    where the status happens to be 'approved' or 'rejected' — even if it
    didn't just change.
    """
    if instance.pk:
        try:
            instance._pre_save_verification_status = (
                VendorProfile.objects.get(pk=instance.pk).verification_status
            )
        except VendorProfile.DoesNotExist:
            instance._pre_save_verification_status = None
    else:
        instance._pre_save_verification_status = None


@receiver(post_save, sender=VendorProfile)
def send_verification_notifications(sender, instance, created, **kwargs):
    """
    Send notifications ONLY when verification_status genuinely transitions.

    BUG FIXED (was firing on every save):
    The original code had two problems:
      1. The print() and logger.info() for the 'rejected' case were OUTSIDE
         the elif block due to wrong indentation — they ran after every save
         where `not created` was True, regardless of status.
      2. There was no state-transition check — the signal checked the current
         status value but not whether it just changed, so re-saving a rejected
         vendor (e.g. admin adding a note) would re-trigger the notification
         path on every save.

    Fix: pre_save caches the old status; post_save compares old vs new and
    returns early if nothing changed. print/logger are now inside their
    respective if/elif blocks.
    """
    try:
        if created:
            return  # New profile — no status change to notify about

        old_status = getattr(instance, '_pre_save_verification_status', None)
        new_status = instance.verification_status

        # Nothing changed — do nothing
        if old_status == new_status:
            return

        if new_status == 'approved' and instance.approved_at:
            Notification.objects.get_or_create(
                vendor=instance,
                notification_type='verification',
                title='Verification Approved! 🎉',
                defaults={
                    'message': (
                        'Congratulations! Your vendor account has been approved. '
                        'You can now start listing products and selling on KasuMarketplace.'
                    ),
                    'link': '/vendors/dashboard/'
                }
            )
            print(f"✓ Approval notification sent to: {instance.full_name}")
            logger.info(f"Approval notification sent to: {instance.user.email}")

            # TODO: Send email notification
            # from .services.notifications import send_verification_approved_email
            # send_verification_approved_email(instance)

        elif new_status == 'rejected':
            Notification.objects.get_or_create(
                vendor=instance,
                notification_type='verification',
                title='Verification Rejected',
                defaults={
                    'message': (
                        f'Your verification was rejected. '
                        f'Reason: {instance.admin_comment or "Please contact support for details."}'
                    ),
                    'link': '/vendors/verification/'
                }
            )
            # ← These two lines were OUTSIDE the elif in the original — fixed:
            print(f"✓ Rejection notification sent to: {instance.full_name}")
            logger.info(f"Rejection notification sent to: {instance.user.email}")

    except Exception as e:
        logger.error(
            f"Error in send_verification_notifications for {instance.user.email}: {str(e)}",
            exc_info=True
        )


# ==========================================
# STORE SIGNALS
# ==========================================

@receiver(post_save, sender=Store)
def update_store_stats(sender, instance, created, **kwargs):
    try:
        if created:
            print(f"✓ Store created: {instance.store_name}")
            Notification.objects.create(
                vendor=instance.vendor,
                notification_type='system',
                title='Store Created! 🏪',
                message=f'Your store "{instance.store_name}" has been created successfully. You can now add products.',
                link='/vendors/store/settings/'
            )
            logger.info(f"Store created: {instance.store_name}")
    except Exception as e:
        logger.error(f"Error in update_store_stats for store {instance.store_name}: {str(e)}", exc_info=True)


@receiver(post_save, sender=Store)
def notify_category_lock(sender, instance, created, **kwargs):
    try:
        if not created and instance.main_category_locked:
            old_instance = Store.objects.filter(pk=instance.pk).first()
            if old_instance and not old_instance.main_category_locked:
                Notification.objects.create(
                    vendor=instance.vendor,
                    notification_type='system',
                    title='Category Locked 🔒',
                    message=f'Your main category "{instance.main_category.name}" has been locked. To change it, submit a category change request.',
                    link='/vendors/store/settings/'
                )
                logger.info(f"Category lock notification sent for store {instance.store_name}")
    except Exception as e:
        logger.error(f"Error in notify_category_lock for store {instance.store_name}: {str(e)}", exc_info=True)


# ==========================================
# PRODUCT SIGNALS
# ==========================================

@receiver(post_save, sender=Product)
def update_store_product_count(sender, instance, created, **kwargs):
    store = instance.store
    store.total_products = store.products.filter(status='published').count()
    store.save(update_fields=['total_products'])
    if created:
        print(f"✓ Product created: {instance.title} in store: {store.store_name}")
        Notification.objects.create(
            vendor=instance.vendor,
            notification_type='system',
            title='Product Created 📦',
            message=f'Your product "{instance.title}" has been created. Publish it to make it visible to customers.',
            link=f'/vendors/products/{instance.slug}/'
        )


@receiver(post_delete, sender=Product)
def update_store_product_count_on_delete(sender, instance, **kwargs):
    store = instance.store
    store.total_products = store.products.filter(status='published').count()
    store.save(update_fields=['total_products'])
    print(f"✓ Product deleted: {instance.title}")


@receiver(post_save, sender=Product)
def handle_product_publish(sender, instance, created, **kwargs):
    if not created and instance.status == 'published' and not instance.published_at:
        instance.published_at = timezone.now()
        instance.save(update_fields=['published_at'])
        Notification.objects.create(
            vendor=instance.vendor,
            notification_type='system',
            title='Product Published! ✅',
            message=f'Your product "{instance.title}" is now live and visible to customers.',
            link=f'/vendors/products/{instance.slug}/'
        )


@receiver(post_save, sender=Product)
def notify_vendor_stock_status(sender, instance, created, **kwargs):
    if not instance.track_inventory or instance.status != 'published':
        return
    if instance.stock_quantity == 0:
        Notification.objects.get_or_create(
            vendor=instance.vendor,
            link=f'/vendors/products/{instance.slug}/',
            notification_type='inventory',
            title='Out of Stock! ⚠️',
            defaults={
                'message': f'Your product "{instance.title}" is now out of stock. Restock it to continue selling.',
                'is_read': False,
            }
        )
        print(f"⚠️ Out of stock notification: {instance.title}")
    elif instance.stock_quantity <= instance.low_stock_threshold and instance.stock_quantity > 0:
        Notification.objects.get_or_create(
            vendor=instance.vendor,
            link=f'/vendors/products/{instance.slug}/',
            notification_type='inventory',
            title='Low Stock Alert 📉',
            defaults={
                'message': f'Your product "{instance.title}" has low stock ({instance.stock_quantity} units left). Consider restocking.',
                'is_read': False,
            }
        )
        print(f"📉 Low stock notification: {instance.title}")


# ==========================================
# ORDER SIGNALS
# ==========================================

@receiver(post_save, sender=Order)
def notify_vendor_new_order(sender, instance, created, **kwargs):
    if created:
        Notification.objects.create(
            vendor=instance.vendor,
            notification_type='order',
            title='New Order Received! 🛒',
            message=f'You have a new order (#{str(instance.order_id)[:8]}) worth ₦{instance.total_amount}. Please process it promptly.',
            link=f'/vendors/orders/{instance.order_id}/'
        )
        print(f"✓ New order notification sent to: {instance.vendor.full_name}")


@receiver(post_save, sender=Order)
def update_wallet_on_order_payment(sender, instance, created, **kwargs):
    if not created and instance.payment_status == 'paid' and instance.paid_at:
        wallet = instance.vendor.wallet
        existing_transaction = Transaction.objects.filter(
            wallet=wallet, order=instance, transaction_type='credit', status='pending'
        ).first()
        if not existing_transaction:
            vendor_amount = instance.vendor_amount
            balance_before = wallet.balance
            wallet.pending_balance += vendor_amount
            wallet.save(update_fields=['pending_balance'])
            Transaction.objects.create(
                wallet=wallet, transaction_type='credit', amount=vendor_amount,
                status='pending', reference=f"ORDER-{instance.order_id}",
                description=f"Payment for order #{str(instance.order_id)[:8]}",
                order=instance, balance_before=balance_before, balance_after=balance_before
            )
            print(f"✓ Added ₦{vendor_amount} to pending balance for: {instance.vendor.full_name}")
            Notification.objects.create(
                vendor=instance.vendor, notification_type='payment',
                title='Payment Received 💰',
                message=f'Payment of ₦{vendor_amount} received for order #{str(instance.order_id)[:8]}. Amount will be available after delivery.',
                link='/vendors/wallet/'
            )


@receiver(post_save, sender=Order)
def update_wallet_on_order_delivery(sender, instance, created, **kwargs):
    if not created and instance.status == 'delivered' and instance.delivered_at:
        wallet = instance.vendor.wallet
        existing_transaction = Transaction.objects.filter(
            wallet=wallet, order=instance, transaction_type='credit', status='completed'
        ).first()
        if not existing_transaction:
            vendor_amount = instance.vendor_amount
            balance_before = wallet.balance
            wallet.pending_balance -= vendor_amount
            wallet.balance += vendor_amount
            wallet.total_earned += vendor_amount
            wallet.save(update_fields=['pending_balance', 'balance', 'total_earned'])
            transaction = Transaction.objects.filter(
                wallet=wallet, order=instance, transaction_type='credit', status='pending'
            ).first()
            if transaction:
                transaction.status = 'completed'
                transaction.balance_after = wallet.balance
                transaction.completed_at = timezone.now()
                transaction.save()
            print(f"✓ Moved ₦{vendor_amount} to available balance for: {instance.vendor.full_name}")
            Notification.objects.create(
                vendor=instance.vendor, notification_type='payment',
                title='Funds Available! 💵',
                message=f'₦{vendor_amount} from order #{str(instance.order_id)[:8]} is now available for withdrawal.',
                link='/vendors/wallet/'
            )


@receiver(post_save, sender=Order)
def update_store_order_stats(sender, instance, created, **kwargs):
    store = instance.vendor.store
    store.total_orders = store.vendor.orders.filter(
        status__in=['delivered', 'completed']
    ).count()
    store.total_sales = store.vendor.orders.filter(
        status__in=['delivered', 'completed']
    ).aggregate(total=Sum('vendor_amount'))['total'] or 0
    store.save(update_fields=['total_orders', 'total_sales'])


@receiver(post_save, sender=OrderItem)
def update_product_sales_count(sender, instance, created, **kwargs):
    if instance.order.status in ['delivered', 'completed']:
        product = instance.product
        product.sales_count = OrderItem.objects.filter(
            product=product, order__status__in=['delivered', 'completed']
        ).aggregate(total_quantity=Sum('quantity'))['total_quantity'] or 0
        product.save(update_fields=['sales_count'])


@receiver(post_save, sender=OrderItem)
def reduce_product_quantity(sender, instance, created, **kwargs):
    if created:
        product = instance.product
        if product.track_inventory:
            if product.stock_quantity >= instance.quantity:
                product.stock_quantity -= instance.quantity
                product.save(update_fields=['stock_quantity'])
                if product.is_low_stock:
                    Notification.objects.create(
                        vendor=product.vendor, notification_type='system',
                        title=f'Low Stock Alert: {product.title}',
                        message=f'Only {product.stock_quantity} units left! Restock soon.',
                        link=f'/vendors/products/{product.slug}/edit/'
                    )
                if product.stock_quantity == 0:
                    product.status = 'out_of_stock'
                    product.save(update_fields=['status'])
                    Notification.objects.create(
                        vendor=product.vendor, notification_type='system',
                        title=f'Out of Stock: {product.title}',
                        message='Your product is now out of stock. Update inventory to continue selling.',
                        link=f'/vendors/products/{product.slug}/edit/'
                    )
            else:
                print(f"⚠️ WARNING: Insufficient stock for {product.title}")


# ==========================================
# REFUND SIGNALS
# ==========================================

@receiver(post_save, sender=RefundRequest)
def notify_vendor_refund_request(sender, instance, created, **kwargs):
    if created:
        Notification.objects.create(
            vendor=instance.vendor, notification_type='refund',
            title='Refund Request Received',
            message=f'Customer requested refund for order #{str(instance.order.order_id)[:8]}. Reason: {instance.get_reason_display()}',
            link=f'/vendors/refunds/{instance.refund_id}/'
        )
        print(f"✓ Refund request notification sent to: {instance.vendor.full_name}")


@receiver(post_save, sender=RefundRequest)
def process_approved_refund(sender, instance, created, **kwargs):
    if not created and instance.status == 'approved':
        existing_transaction = Transaction.objects.filter(
            wallet=instance.vendor.wallet, transaction_type='refund',
            reference=f"REFUND-{instance.refund_id}"
        ).exists()
        if not existing_transaction:
            wallet = instance.vendor.wallet
            refund_amount = instance.amount
            balance_before = wallet.balance
            wallet.balance -= refund_amount
            wallet.save(update_fields=['balance'])
            Transaction.objects.create(
                wallet=wallet, transaction_type='refund', amount=refund_amount,
                status='completed', reference=f"REFUND-{instance.refund_id}",
                description=f"Refund for order #{str(instance.order.order_id)[:8]}",
                order=instance.order, balance_before=balance_before,
                balance_after=wallet.balance, completed_at=timezone.now()
            )
            print(f"✓ Refund processed: ₦{refund_amount} deducted from {instance.vendor.full_name}")
            Notification.objects.create(
                vendor=instance.vendor, notification_type='refund',
                title='Refund Processed',
                message=f'Refund of ₦{refund_amount} has been processed for order #{str(instance.order.order_id)[:8]}.',
                link='/vendors/wallet/transactions/'
            )


# ==========================================
# TRANSACTION SIGNALS
# ==========================================

@receiver(post_save, sender=Transaction)
def notify_vendor_payout(sender, instance, created, **kwargs):
    if instance.transaction_type == 'payout' and instance.status == 'completed':
        Notification.objects.create(
            vendor=instance.wallet.vendor, notification_type='payment',
            title='Payout Successful 💸',
            message=f'Your payout of ₦{instance.amount} has been sent to your bank account ({instance.wallet.bank_name}).',
            link='/vendors/wallet/payout-history/'
        )
        print(f"✓ Payout notification sent: ₦{instance.amount} to {instance.wallet.vendor.full_name}")


# ==========================================
# HELPER FUNCTIONS
# ==========================================

def recalculate_store_stats(store):
    store.total_products = store.products.filter(status='published').count()
    store.total_orders = store.vendor.orders.filter(
        status__in=['delivered', 'completed']
    ).count()
    store.total_sales = store.vendor.orders.filter(
        status__in=['delivered', 'completed']
    ).aggregate(total=Sum('vendor_amount'))['total'] or 0
    store.save()
    print(f"✓ Store stats recalculated for: {store.store_name}")


def recalculate_wallet_balances(wallet):
    total_credits = Transaction.objects.filter(
        wallet=wallet, transaction_type='credit', status='completed'
    ).aggregate(total=Sum('amount'))['total'] or 0
    total_debits = Transaction.objects.filter(
        wallet=wallet, transaction_type__in=['payout', 'refund'], status='completed'
    ).aggregate(total=Sum('amount'))['total'] or 0
    pending = Transaction.objects.filter(
        wallet=wallet, transaction_type='credit', status='pending'
    ).aggregate(total=Sum('amount'))['total'] or 0
    wallet.balance = total_credits - total_debits
    wallet.pending_balance = pending
    wallet.total_earned = total_credits
    wallet.total_withdrawn = Transaction.objects.filter(
        wallet=wallet, transaction_type='payout', status='completed'
    ).aggregate(total=Sum('amount'))['total'] or 0
    wallet.save()
    print(f"✓ Wallet balances recalculated for: {wallet.vendor.full_name}")


# ==========================================
# ADMIN MESSAGE SIGNALS
# ==========================================

@receiver(post_save, sender=CategoryChangeRequest)
def notify_vendor_of_admin_message(sender, instance, created, **kwargs):
    if not created and instance.admin_comment:
        last_notification = Notification.objects.filter(
            vendor=instance.store.vendor,
            notification_type='admin_message',
            title__icontains='Category Change Request'
        ).order_by('-created_at').first()
        if not last_notification or last_notification.message != instance.admin_comment:
            Notification.objects.create(
                vendor=instance.store.vendor,
                notification_type='admin_message',
                title=f'📧 Admin Update - Category Change Request #{instance.id}',
                message=instance.admin_comment,
                link=f'/vendors/store/category-change-request/{instance.id}/'
            )
            print(f"✓ Admin message notification sent to: {instance.store.vendor.full_name}")