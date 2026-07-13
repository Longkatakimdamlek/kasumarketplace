from .models import Notification

def vendor_context(request):
    """
    Injects vendor notification and order counts into every vendor template.
    """
    if not request.user.is_authenticated:
        return {}

    try:
        vendor = request.user.vendorprofile
    except Exception:
        return {}

    try:
        from apps.marketplace.models import SubOrder
        pending_orders = SubOrder.objects.filter(
            store=vendor.store,
            status='PENDING_VENDOR'
        ).count()
    except Exception:
        pending_orders = 0

    unread_notifications = vendor.notifications.filter(is_read=False).count()
    recent_notifications = vendor.notifications.order_by('-created_at')[:5]

    return {
        'pending_orders': pending_orders,
        'unread_notifications': unread_notifications,
        'recent_notifications': recent_notifications,
    }