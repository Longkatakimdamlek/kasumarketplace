"""
Marketplace Signals
- BuyerProfile auto-create on registration
- Wishlist merge on login
- Product report admin notification
- Review rating recalculation
"""

from django.db import transaction
from django.db.models.signals import post_save, post_delete, pre_save
from django.contrib.auth.signals import user_logged_in
from django.dispatch import receiver
from django.contrib.auth import get_user_model
from decimal import Decimal
import logging

from apps.marketplace.models import Wishlist, ProductView

logger = logging.getLogger(__name__)

User = get_user_model()


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
def merge_wishlist_on_login(sender, request, user, **kwargs):
    """Move anonymous session wishlist into the logged-in user's wishlist.

    Django's ``login()`` call rotates the session key (flushes the
    session) before emitting ``user_logged_in``.  That means by the time
    the signal is handled ``request.session.session_key`` is new and the
    previous anonymous session key cannot be found.

    To work around this we preserve the pre-login key via middleware
    (``PreserveSessionKeyMiddleware``) and fall back to it when available.
    This covers both the custom login view and social / allauth logins.
    """
    try:
        # prefer the original key stored by middleware
        session_key = getattr(request, '_pre_login_session_key', None) or request.session.session_key
        if not session_key:
            return

        anon_items = Wishlist.objects.filter(session_key=session_key, user__isnull=True)
        if not anon_items.exists():
            return

        for anon_item in anon_items:
            existing = Wishlist.objects.filter(user=user, product=anon_item.product).first()
            if existing:
                # Same product already wishlisted on the account — keep the higher quantity
                if anon_item.quantity > existing.quantity:
                    existing.quantity = anon_item.quantity
                    existing.save(update_fields=['quantity'])
                anon_item.delete()
            else:
                # Transfer the anonymous item to the user
                anon_item.user = user
                anon_item.session_key = ''
                anon_item.save(update_fields=['user', 'session_key'])

        logger.info(f"Wishlist merged for user {user.email}")
    except Exception as e:
        logger.error(f"Error merging wishlist for {user.email}: {str(e)}", exc_info=True)
        # Don't re-raise to prevent breaking login


@receiver(post_save, sender='marketplace.ProductReport')
def handle_product_report_created(sender, instance, created, **kwargs):
    """Notify admin when a new product report is submitted."""
    if not created:
        return
    try:
        from apps.marketplace.services.email_service import _send, ADMIN_EMAIL
        if ADMIN_EMAIL:
            reporter_email = instance.reporter.email if instance.reporter else 'Anonymous'
            reporter_ip = instance.reporter_ip or 'Unknown'
            _send(
                subject=f'[Product Report] {instance.product.title[:40]} — Action Required',
                message=(
                    f'New product report received.\n\n'
                    f'Product: {instance.product.title}\n'
                    f'Store: {instance.product.store.store_name}\n'
                    f'Reason: {instance.get_reason_display()}\n'
                    f'Reporter: {reporter_email}\n'
                    f'Reporter IP: {reporter_ip}\n'
                    f'Details: {instance.details or "None provided"}\n\n'
                    f'Review in admin: /admin/marketplace/productreport/'
                ),
                recipient_list=[ADMIN_EMAIL],
            )
    except Exception as e:
        logger.error(f"Error sending product report notification: {e}", exc_info=True)


@receiver(post_save, sender='marketplace.Review')
@receiver(post_delete, sender='marketplace.Review')
def recalc_ratings_on_review_change(sender, instance, **kwargs):
    """Recalculate product and store ratings after a review changes."""
    product_id = instance.product_id

    def recalculate():
        from django.db.models import Avg, Count
        from apps.vendors.models import Product
        from apps.marketplace.models import Review

        # During a cascading delete the product may already be gone by the
        # time the transaction commits; in that case there is nothing to rate.
        product = Product.objects.filter(pk=product_id).first()
        if not product:
            return

        agg = product.reviews.aggregate(avg=Avg('rating'), count=Count('id'))
        product.average_rating = round(agg['avg'] or 0, 2)
        product.review_count = agg['count'] or 0
        product.save(update_fields=['average_rating', 'review_count'])

        store_agg = Review.objects.filter(product__store=product.store).aggregate(avg=Avg('rating'))
        product.store.average_rating = round(store_agg['avg'] or 0, 2)
        product.store.save(update_fields=['average_rating'])

    transaction.on_commit(recalculate)


@receiver(post_save, sender='marketplace.Review')
def notify_vendor_on_new_review(sender, instance, created, **kwargs):
    """Notify vendor when a new review is created on their product."""
    if not created:
        return
    try:
        from apps.vendors.services.notification_dispatch import create_notification

        product = instance.product
        vendor_user = product.store.vendor.user
        stars = '⭐' * instance.rating
        comment_excerpt = ''
        if instance.comment:
            excerpt = instance.comment[:120]
            if len(instance.comment) > 120:
                excerpt += '...'
            comment_excerpt = f'\n"{excerpt}"'

        create_notification(
            user=vendor_user,
            notification_type='wishlist',
            title=f'New Review — {stars}',
            message=(
                f'{instance.user.email} reviewed "{product.title}" '
                f'with {instance.rating}/5 stars.{comment_excerpt}'
            ),
            link=f'/vendors/products/{product.slug}/',
            vendor=product.store.vendor,
        )
    except Exception:
        logger.exception("Failed to send new review notification")


# ==========================================
# HELPER: get_buyer_top_categories
# ==========================================

def get_buyer_top_categories(user, limit=5):
    """
    Return a QuerySet of SubCategory IDs representing a buyer's most-viewed
    and most-wishlisted subcategories combined.
    Used by sponsored-featured and similar-product triggers.
    """
    from django.db.models import Count
    from apps.vendors.models import Product
    from apps.marketplace.models import ProductView, Wishlist

    view_cats = (
        ProductView.objects.filter(user=user)
        .values_list('product__subcategory_id', flat=True)
    )
    wish_cats = (
        Wishlist.objects.filter(user=user)
        .values_list('product__subcategory_id', flat=True)
    )

    all_cat_ids = list(view_cats) + list(wish_cats)
    if not all_cat_ids:
        return []

    from collections import Counter
    counts = Counter(all_cat_ids)
    return [cat_id for cat_id, _ in counts.most_common(limit)]


# ==========================================
# B3: PRICE DROP TRACKING
# ==========================================

@receiver(pre_save, sender='vendors.Product')
def cache_product_price(sender, instance, **kwargs):
    """Cache old price so post_save can detect price drops."""
    if instance.pk and not hasattr(instance, '_pre_save_price'):
        try:
            old = Product.objects.filter(pk=instance.pk).values_list('price', flat=True).first()
            instance._pre_save_price = old if old is not None else instance.price
        except Exception:
            instance._pre_save_price = instance.price
    elif not hasattr(instance, '_pre_save_price'):
        instance._pre_save_price = instance.price


@receiver(post_save, sender='vendors.Product')
def notify_buyers_on_price_drop(sender, instance, created, **kwargs):
    """Notify wishlisted buyers when price drops meaningfully (>5% or >₦500)."""
    if created:
        return
    if not instance.track_inventory or instance.status != 'published':
        pass  # Still check price even if not inventory-tracked

    old_price = getattr(instance, '_pre_save_price', None)
    if old_price is None or old_price <= 0:
        return

    new_price = instance.price
    if new_price >= old_price:
        return

    pct_drop = ((old_price - new_price) / old_price) * 100
    abs_drop = old_price - new_price
    MEANINGFUL_THRESHOLD_PCT = 5
    MEANINGFUL_THRESHOLD_ABS = Decimal('500')

    if pct_drop < MEANINGFUL_THRESHOLD_PCT and abs_drop < MEANINGFUL_THRESHOLD_ABS:
        return

    try:
        from apps.vendors.services.notification_dispatch import create_notification

        wishlisted_buyers = Wishlist.objects.filter(
            product=instance, user__isnull=False
        ).values_list('user', flat=True).distinct()

        savings_pct = round(pct_drop, 1)
        for buyer_id in wishlisted_buyers:
            from apps.users.models import CustomUser as User
            buyer = User.objects.filter(id=buyer_id).first()
            if buyer:
                create_notification(
                    user=buyer,
                    notification_type='wishlist',
                    title=f'Price Drop! {savings_pct}% Off',
                    message=(
                        f'"{instance.title}" dropped from ₦{old_price:,.0f} to ₦{new_price:,.0f} '
                        f'({savings_pct}% off). Grab it before it goes back up!'
                    ),
                    link=f'/shop/{instance.store.slug}/products/{instance.slug}/',
                    in_app_only=False,
                )
    except Exception:
        logger.exception("Failed to send price drop notifications")


# ==========================================
# B4: SUBSCRIPTION TRANSITION DETECTION
# ==========================================

@receiver(pre_save, sender='vendors.Subscription')
def cache_subscription_status(sender, instance, **kwargs):
    """Cache old subscription status for transition detection."""
    if instance.pk and not hasattr(instance, '_pre_save_status'):
        try:
            from apps.vendors.models import Subscription
            old = Subscription.objects.filter(pk=instance.pk).values_list('status', flat=True).first()
            instance._pre_save_status = old if old is not None else instance.status
        except Exception:
            instance._pre_save_status = instance.status
    elif not hasattr(instance, '_pre_save_status'):
        instance._pre_save_status = instance.status


@receiver(post_save, sender='vendors.Subscription')
def notify_buyers_on_vendor_reactivation(sender, instance, **kwargs):
    """Notify buyers when a vendor's subscription transitions back to active."""
    old_status = getattr(instance, '_pre_save_status', None)
    new_status = instance.status

    if old_status == new_status:
        return

    was_inactive = old_status in ('expired', 'past_due', 'cancelled')
    is_active = new_status in ('active', 'trial')

    if not (was_inactive and is_active):
        return

    try:
        from apps.vendors.services.notification_dispatch import create_notification
        from apps.vendors.models import Store

        store = Store.objects.filter(vendor=instance.vendor).first()
        if not store:
            return

        wishlisted_buyers = Wishlist.objects.filter(
            product__store=store,
            user__isnull=False,
        ).values_list('user', flat=True).distinct()

        from apps.users.models import CustomUser as User
        for buyer_id in wishlisted_buyers:
            buyer = User.objects.filter(id=buyer_id).first()
            if buyer:
                create_notification(
                    user=buyer,
                    notification_type='wishlist',
                    title=f'{store.store_name} is Back! 🎉',
                    message=(
                        f'{store.store_name} is active again. '
                        f'Check out what\'s new!'
                    ),
                    link=f'/shop/{store.slug}/',
                    in_app_only=False,
                )
    except Exception:
        logger.exception("Failed to send vendor reactivation notifications")


# ==========================================
# B6: SPONSORED/FEATURED PRODUCT (buyer notification)
# ==========================================

@receiver(pre_save, sender='vendors.Product')
def cache_product_sponsored_featured(sender, instance, **kwargs):
    """Cache old is_sponsored/is_featured for transition detection."""
    if instance.pk and not hasattr(instance, '_pre_save_is_sponsored'):
        try:
            from apps.vendors.models import Product
            old_s, old_f = Product.objects.filter(
                pk=instance.pk
            ).values_list('is_sponsored', 'is_featured').first() or (False, False)
            instance._pre_save_is_sponsored = old_s
            instance._pre_save_is_featured = old_f
        except Exception:
            instance._pre_save_is_sponsored = instance.is_sponsored
            instance._pre_save_is_featured = instance.is_featured
    elif not hasattr(instance, '_pre_save_is_sponsored'):
        instance._pre_save_is_sponsored = instance.is_sponsored
        instance._pre_save_is_featured = instance.is_featured


@receiver(post_save, sender='vendors.Product')
def notify_buyers_on_sponsored_featured(sender, instance, **kwargs):
    """Notify buyers in the product's subcategory when it becomes sponsored or featured."""
    old_sponsored = getattr(instance, '_pre_save_is_sponsored', False)
    old_featured = getattr(instance, '_pre_save_is_featured', False)

    became_sponsored = instance.is_sponsored and not old_sponsored
    became_featured = instance.is_featured and not old_featured

    if not (became_sponsored or became_featured):
        return

    try:
        from apps.vendors.services.notification_dispatch import create_notification
        from apps.vendors.models import Product
        from django.db.models import Count
        from collections import Counter

        CATEGORY_BUYER_CAP = 100

        # Find buyers who viewed/wishlisted products in this subcategory
        view_cats = ProductView.objects.filter(
            product__subcategory=instance.subcategory
        ).values_list('user_id', flat=True)

        wish_cats = Wishlist.objects.filter(
            product__subcategory=instance.subcategory,
            user__isnull=False,
        ).values_list('user', flat=True)

        all_buyer_ids = list(view_cats) + list(wish_cats)
        buyer_id_counts = Counter(all_buyer_ids)
        top_buyer_ids = [bid for bid, _ in buyer_id_counts.most_common(CATEGORY_BUYER_CAP)]

        from apps.users.models import CustomUser as User
        for buyer_id in top_buyer_ids:
            buyer = User.objects.filter(id=buyer_id).first()
            if buyer:
                label = 'Sponsored' if became_sponsored else 'Featured'
                create_notification(
                    user=buyer,
                    notification_type='wishlist',
                    title=f'{label} Product for You!',
                    message=(
                        f'"{instance.title}" is now {label.lower()} in '
                        f'{instance.subcategory.name}. Check it out!'
                    ),
                    link=f'/shop/{instance.store.slug}/products/{instance.slug}/',
                    in_app_only=False,
                )
    except Exception:
        logger.exception("Failed to send sponsored/featured buyer notifications")


# ==========================================
# B7: SIMILAR PRODUCT TO WISHLISTED ITEM
# ==========================================

@receiver(post_save, sender='vendors.Product')
def notify_buyers_on_similar_to_wishlist(sender, instance, created, **kwargs):
    """
    On product publish, notify buyers who wishlisted a product in the same
    subcategory. If a buyer also qualifies for the same-store trigger (Phase B #8),
    prefer that one — this trigger sends only if same-store didn't fire.
    """
    if not created or instance.status != 'published':
        return

    try:
        from apps.vendors.services.notification_dispatch import create_notification
        from apps.vendors.models import Product

        # Find buyers with same-subcategory wishlisted products (excluding this product)
        same_subcat_buyers = Wishlist.objects.filter(
            product__subcategory=instance.subcategory,
            user__isnull=False,
        ).exclude(
            product=instance,
        ).values_list('user', flat=True).distinct()

        # Find buyers who already got the same-store notification (Phase B #8)
        same_store_buyers = set(
            Wishlist.objects.filter(
                product__store=instance.store,
                user__isnull=False,
            ).exclude(
                product=instance,
            ).values_list('user', flat=True).distinct()
        )

        from apps.users.models import CustomUser as User
        for buyer_id in same_subcat_buyers:
            # Skip if same-store notification already covers this buyer
            if buyer_id in same_store_buyers:
                continue

            buyer = User.objects.filter(id=buyer_id).first()
            if buyer:
                create_notification(
                    user=buyer,
                    notification_type='wishlist',
                    title='Similar to Your Wishlist!',
                    message=(
                        f'"{instance.title}" is similar to something in your wishlist. '
                        f'Take a look!'
                    ),
                    link=f'/shop/{instance.store.slug}/products/{instance.slug}/',
                    in_app_only=False,
                )
    except Exception:
        logger.exception("Failed to send similar-to-wishlist notifications")


# ==========================================
# B5: REVIEW REPLY → BUYER NOTIFICATION
# ==========================================

@receiver(post_save, sender='marketplace.ReviewReply')
def notify_buyer_on_review_reply(sender, instance, created, **kwargs):
    """Notify the review author when a vendor replies to their review."""
    if not created:
        return
    try:
        from apps.vendors.services.notification_dispatch import create_notification

        review = instance.review
        buyer = review.user
        store_name = review.product.store.store_name

        create_notification(
            user=buyer,
            notification_type='wishlist',
            title=f'Reply from {store_name}',
            message=(
                f'{store_name} replied to your review of "{review.product.title}". '
                f'"{instance.reply_text[:100]}{"..." if len(instance.reply_text) > 100 else ""}"'
            ),
            link=f'/shop/{review.product.store.slug}/products/{review.product.slug}/',
            in_app_only=False,
        )
    except Exception:
        logger.exception("Failed to send review reply notification")
