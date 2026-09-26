from django.db import models
from apps.vendors.models import MainCategory
import logging

logger = logging.getLogger(__name__)


def categories_processor(request):
    """Make active categories and their subcategories available globally."""
    try:
        return {
            'categories': MainCategory.objects.filter(
                is_active=True
            ).prefetch_related('subcategories').order_by('sort_order'),
        }
    except Exception as e:
        logger.error(f"Error in categories_processor: {str(e)}", exc_info=True)
        return {'categories': []}


def wishlist_count_processor(request):
    """Inject wishlist item count for authenticated buyers and session-based guests."""
    try:
        from apps.marketplace.models import Wishlist
        if request.user.is_authenticated:
            return {'wishlist_count': Wishlist.objects.filter(user=request.user).count()}
        # For anonymous users, count session-based wishlist items
        session_key = request.session.session_key
        if session_key:
            return {'wishlist_count': Wishlist.objects.filter(session_key=session_key).count()}
        return {'wishlist_count': 0}
    except Exception:
        return {'wishlist_count': 0}


def event_popup_processor(request):
    """Fetch active event_popup Promotions for the popup overlay on every page."""
    try:
        from django.utils import timezone
        from apps.marketplace.models import Promotion

        now = timezone.now()
        popups = Promotion.objects.filter(
            slide_type='event_popup',
            is_active=True,
        ).filter(
            models.Q(start_date__isnull=True) | models.Q(start_date__lte=now),
            models.Q(end_date__isnull=True) | models.Q(end_date__gte=now),
        ).order_by('sort_order', '-created_at').values(
            'id', 'title', 'subtitle', 'image', 'background_image',
            'link_url', 'frequency_minutes', 'sort_order',
        )
        return {'active_event_popups': list(popups)}
    except Exception as e:
        logger.error(f"Error in event_popup_processor: {str(e)}", exc_info=True)
        return {'active_event_popups': []}


def buyer_notification_processor(request):
    """
    Inject buyer notification counts into every marketplace template.
    Only fires for authenticated users with the 'buyer' role.
    """
    if not request.user.is_authenticated:
        return {}
    try:
        if not request.user.is_buyer:
            return {}
    except Exception:
        return {}

    from apps.vendors.models import Notification
    unread = Notification.objects.filter(
        user=request.user, is_read=False
    ).count()
    recent = Notification.objects.filter(
        user=request.user
    ).order_by('-created_at')[:5]
    return {
        'buyer_unread_count': unread,
        'buyer_recent_notifications': recent,
    }