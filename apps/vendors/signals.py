"""
Vendor App Signals
Automatically handle subscription creation, store creation, stats updates, notifications, etc.
"""

from django.db.models.signals import post_save, pre_save, post_delete
from django.dispatch import receiver
from django.contrib.auth import get_user_model
from django.utils import timezone
from django.db.models import Sum, Avg, F
import logging

logger = logging.getLogger(__name__)

from .models import (
    VendorProfile, Store, Product,
    Notification, CategoryChangeRequest,
    Subscription
)
from .services.notification_dispatch import create_notification

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
            logger.info("VendorProfile created for vendor: %s", instance.email)
    except Exception as e:
        logger.error(f"Error creating VendorProfile for {instance.email}: {str(e)}", exc_info=True)


# ==========================================
# VENDOR PROFILE SIGNALS
# ==========================================

@receiver(post_save, sender=VendorProfile)
def create_vendor_subscription(sender, instance, created, **kwargs):
    """
    Automatically create a Subscription when VendorProfile is created.

    Phase 5: free-plan vendors start in status 'qualifying'.  Signup and store
    setup start NOTHING - the 7-day countdown only begins when the vendor
    creates their first product (see sync_vendor_qualification below).
    """
    try:
        if created:
            Subscription.objects.get_or_create(
                vendor=instance,
                defaults={
                    'status': 'qualifying',
                    'plan': 'free',
                    'qualification_status': 'not_started',
                    'trial_ends_at': None,
                },
            )
            logger.info("Qualifying subscription created for vendor: %s", instance.user.email)
    except Exception as e:
        logger.error(f"Error creating Subscription for vendor {instance.user.email}: {str(e)}", exc_info=True)


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
        if not hasattr(instance, '_pre_save_verification_status'):
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
    Uses the unified create_notification() which sends both in-app and email.
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
            confidence = getattr(instance, 'selfie_confidence', None)
            if confidence is not None and confidence >= 90:
                title = 'Verification Approved! 🎉'
                message = (
                    'Congratulations! Your vendor account has been automatically approved. '
                    'You can now start listing products and selling on KasuMarketplace.'
                )
            elif confidence is not None and confidence >= 75:
                title = 'Verification Approved — Manual Review ✅'
                message = (
                    'Congratulations! Your vendor account has been approved after a manual '
                    'review by our team. You can now start listing products and selling '
                    'on KasuMarketplace.'
                )
            else:
                title = 'Verification Approved! 🎉'
                message = (
                    'Congratulations! Your vendor account has been approved. '
                    'You can now start listing products and selling on KasuMarketplace.'
                )
            create_notification(
                user=instance.user,
                notification_type='verification',
                title=title,
                message=message,
                link='/vendors/dashboard/',
                vendor=instance,
            )
            logger.info("Approval notification sent to: %s", instance.user.email)

        elif new_status == 'rejected':
            create_notification(
                user=instance.user,
                notification_type='verification',
                title='Verification Rejected',
                message=(
                    f'Your verification was rejected. '
                    f'Reason: {instance.admin_comment or "Please contact support for details."}'
                ),
                link='/vendors/verification/',
                vendor=instance,
            )
            logger.info("Rejection notification sent to: %s", instance.user.email)

    except Exception as e:
        logger.error(
            f"Error in send_verification_notifications for {instance.user.email}: {str(e)}",
            exc_info=True
        )


# ==========================================
# V-BATCH SIGNAL (Phase 8)
# ==========================================

@receiver(post_save, sender=Subscription)
def award_vbatch_on_premium_active(sender, instance, **kwargs):
    """
    Phase 8: a Premium subscription becoming active earns the persistent
    V-Batch badge.

    This is the single Premium trigger: every path that can write
    plan='premium' + status='active' goes through Subscription.save()
    (activate_subscription, upgrade_subscription, the Paystack webhook and
    callback, and a manual admin edit).  Paths that bypass save()
    (QuerySet.update in the backfill / expire / restart actions) are
    structurally unable to produce premium + active.

    award_vbatch() is a no-op when the badge is already earned, so repeated
    saves of an already-earned premium row cost one conditional UPDATE.
    """
    if instance.plan != 'premium' or instance.status != 'active':
        return

    try:
        from .vbatch import award_vbatch

        vendor = VendorProfile.objects.filter(
            pk=instance.vendor_id
        ).select_related('user').first()
        if vendor is None:
            return

        if award_vbatch(vendor, 'premium'):
            logger.info(
                "V-Batch awarded on premium activation for vendor %s "
                "(subscription %s)",
                instance.vendor_id, instance.pk,
            )
    except Exception as e:
        logger.error(
            f"V-Batch award failed for subscription {instance.pk}: {str(e)}",
            exc_info=True,
        )


# ==========================================
# STORE SIGNALS
# ==========================================

@receiver(post_save, sender=Store)
def update_store_stats(sender, instance, created, **kwargs):
    try:
        if created:
            logger.info("Store created: %s", instance.store_name)
            create_notification(
                user=instance.vendor.user,
                notification_type='system',
                title='Store Created! 🏪',
                message=f'Your store "{instance.store_name}" has been created successfully. You can now add products.',
                link='/vendors/store/settings/',
                vendor=instance.vendor,
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
                create_notification(
                    user=instance.vendor.user,
                    notification_type='system',
                    title='Category Locked 🔒',
                    message=f'Your main category "{instance.main_category.name}" has been locked. To change it, submit a category change request.',
                    link='/vendors/store/settings/',
                    vendor=instance.vendor,
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
        logger.info("Product created: %s in store: %s", instance.title, store.store_name)
        create_notification(
            user=instance.vendor.user,
            notification_type='system',
            title='Product Created 📦',
            message=f'Your product "{instance.title}" has been created. Publish it to make it visible to customers.',
            link=f'/vendors/products/{instance.slug}/',
            vendor=instance.vendor,
        )


@receiver(post_delete, sender=Product)
def update_store_product_count_on_delete(sender, instance, **kwargs):
    store = instance.store
    store.total_products = store.products.filter(status='published').count()
    store.save(update_fields=['total_products'])
    logger.info("Product deleted: %s", instance.title)


@receiver(pre_save, sender=Product)
def cache_product_status_for_publish(sender, instance, **kwargs):
    if instance.pk and not hasattr(instance, '_pre_save_status'):
        try:
            instance._pre_save_status = Product.objects.filter(
                pk=instance.pk
            ).values_list('status', flat=True).first()
        except Exception:
            instance._pre_save_status = None
    elif not instance.pk:
        instance._pre_save_status = None


@receiver(post_save, sender=Product)
def handle_product_publish(sender, instance, created, **kwargs):
    old_status = getattr(instance, '_pre_save_status', None)
    is_newly_published = instance.status == 'published' and old_status != 'published'
    if is_newly_published:
        create_notification(
            user=instance.vendor.user,
            notification_type='system',
            title='Product Published! ✅',
            message=f'Your product "{instance.title}" is now live and visible to customers.',
            link=f'/vendors/products/{instance.slug}/',
            vendor=instance.vendor,
        )

        try:
            from apps.marketplace.models import Wishlist
            buyer_ids = Wishlist.objects.filter(
                product__store=instance.store,
                user__isnull=False,
            ).exclude(
                product=instance,
            ).values_list('user', flat=True).distinct()

            from apps.users.models import CustomUser as User
            for buyer_id in buyer_ids:
                buyer = User.objects.filter(id=buyer_id).first()
                if buyer:
                    create_notification(
                        user=buyer,
                        notification_type='wishlist',
                    title=f'New Product from {instance.store.store_name}!',
                    message=(
                        f'{instance.store.store_name} just listed "{instance.title}". '
                        f'Check it out!'
                    ),
                        link=f'/shop/{instance.store.slug}/products/{instance.slug}/',
                        in_app_only=False,
                    )
        except Exception:
            logger.exception("Failed to send new-from-wishlisted-store buyer notifications")


# ── pre_save: cache old stock_quantity so post_save can detect back-in-stock ──

@receiver(pre_save, sender=Product)
def cache_product_stock_quantity(sender, instance, **kwargs):
    if instance.pk and not hasattr(instance, '_pre_save_stock_quantity'):
        try:
            old = Product.objects.filter(pk=instance.pk).values_list('stock_quantity', flat=True).first()
            instance._pre_save_stock_quantity = old if old is not None else instance.stock_quantity
        except Exception:
            instance._pre_save_stock_quantity = instance.stock_quantity
    elif not hasattr(instance, '_pre_save_stock_quantity'):
        instance._pre_save_stock_quantity = instance.stock_quantity


@receiver(post_save, sender=Product)
def notify_vendor_stock_status(sender, instance, created, **kwargs):
    if not instance.track_inventory or instance.status != 'published':
        return
    if instance.stock_quantity == 0:
        create_notification(
            user=instance.vendor.user,
            notification_type='inventory',
            title='Out of Stock! ⚠️',
            message=f'Your product "{instance.title}" is now out of stock. Restock it to continue selling.',
            link=f'/vendors/products/{instance.slug}/',
            vendor=instance.vendor,
        )
        logger.info("Out of stock notification: %s", instance.title)
    elif instance.stock_quantity <= instance.low_stock_threshold and instance.stock_quantity > 0:
        create_notification(
            user=instance.vendor.user,
            notification_type='inventory',
            title='Low Stock Alert 📉',
            message=f'Your product "{instance.title}" has low stock ({instance.stock_quantity} units left). Consider restocking.',
            link=f'/vendors/products/{instance.slug}/',
            vendor=instance.vendor,
        )
        logger.info("Low stock notification: %s", instance.title)

    old_stock = getattr(instance, '_pre_save_stock_quantity', None)
    if old_stock == 0 and instance.stock_quantity > 0:
        try:
            from apps.marketplace.models import Wishlist
            wishlisted_users = Wishlist.objects.filter(
                product=instance, user__isnull=False
            ).values_list('user', flat=True).distinct()
            for user_id in wishlisted_users:
                from apps.users.models import CustomUser as User
                buyer = User.objects.filter(id=user_id).first()
                if buyer:
                    create_notification(
                        user=buyer,
                        notification_type='wishlist',
                        title=f'Back in Stock! 🎉',
                        message=f'"{instance.title}" is back in stock. Grab it before it sells out!',
                        link=f'/shop/{instance.store.slug}/products/{instance.slug}/',
                        in_app_only=False,
                    )
        except Exception:
            logger.exception("Failed to send back-in-stock buyer notifications")


# ==========================================
# FREE-PLAN QUALIFICATION SIGNAL (Phase 5)
# ==========================================

@receiver(post_save, sender=Product)
def sync_vendor_qualification(sender, instance, created, **kwargs):
    """
    A product being created or updated may advance the vendor's free-plan
    first-product qualification: the FIRST product (any status) starts the
    7-day countdown, the 3rd published product passes it immediately, and a
    row that is still 'qualifying' after 14 days is marked failed.
    """
    try:
        from .qualification import on_product_saved
        on_product_saved(instance)
    except Exception as e:
        logger.error(
            f"Error syncing qualification for vendor {instance.vendor_id}: {str(e)}",
            exc_info=True,
        )


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
            create_notification(
                user=instance.store.vendor.user,
                notification_type='admin_message',
                title=f'📧 Admin Update - Category Change Request #{instance.id}',
                message=instance.admin_comment,
                link=f'/vendors/store/category-change-request/{instance.id}/',
                vendor=instance.store.vendor,
            )
            logger.info("Admin message notification sent to: %s", instance.store.vendor.user.email)
