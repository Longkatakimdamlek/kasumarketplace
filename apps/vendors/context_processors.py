from .models import Notification, PlatformSettings
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

    # Phase 9 Task 7: platform BVN toggle for the vendor nav chips.
    # Read at most ONCE per request (memoised on the request object) so no
    # template can query it in a loop; non-vendor requests never reach this.
    bvn_on = getattr(request, '_bvn_verification_enabled', None)
    if bvn_on is None:
        bvn_on = PlatformSettings.get_solo().bvn_verification_enabled
        request._bvn_verification_enabled = bvn_on

    return {
        'unread_notifications': unread_notifications,
        'recent_notifications': recent_notifications,
        'vendor_display_name': email_name(vendor),
        'bvn_verification_enabled': bvn_on,
    }
