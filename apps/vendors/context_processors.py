from .models import Notification
from .services import email_name

def vendor_context(request):
    """
    Injects vendor notification counts into every vendor template.
    """
    if not request.user.is_authenticated:
        return {}

    try:
        # Verify the user is a vendor (has a vendorprofile)
        vendor = request.user.vendorprofile
    except Exception:
        return {}

    unread_notifications = Notification.objects.filter(
        user=request.user, is_read=False
    ).count()
    recent_notifications = Notification.objects.filter(
        user=request.user
    ).order_by('-created_at')[:5]

    return {
        'unread_notifications': unread_notifications,
        'recent_notifications': recent_notifications,
        'vendor_display_name': email_name(vendor),
    }
