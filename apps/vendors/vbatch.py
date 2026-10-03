"""
V-Batch - the persistent buyer-facing store badge (Phase 8).

V-Batch is a one-way flag on VendorProfile: it is earned either by BVN
verification (while the platform BVN verification toggle is ON) or by a
Premium subscription becoming active, and once earned no code path ever
removes it.  Only a manual admin edit of ``has_vbatch`` clears it.

Awarding is a single conditional UPDATE::

    UPDATE vendorprofile SET has_vbatch = 1, ...
    WHERE id = <pk> AND has_vbatch = 0

so two callers racing on the same vendor cannot both win, and a caller that
loses the race simply reports False.  Nothing in this module ever clears
the flag back to off.

Notification: the FIRST award only sends one notification (in-app + email)
through the existing ``create_notification()`` helper.
"""
import logging

from django.utils import timezone

logger = logging.getLogger(__name__)

VBATCH_TITLE = 'V-Batch earned'
VBATCH_MESSAGE = (
    'Your store now has the V-Batch. It stays on your store permanently.'
)
VBATCH_LINK = '/vendors/dashboard/'
VBATCH_NOTIFICATION_TYPE = 'verification'


def award_vbatch(vendor, source, *, notify=True):
    """
    Grant the V-Batch to ``vendor`` if it does not have it yet.

    Args:
        vendor: VendorProfile instance (saved row).
        source: One of VendorProfile.VBATCH_SOURCE_CHOICES keys - recorded
            only when this call is the one that actually awarded.
        notify: Send the one-shot notification on first award.  Backfill
            passes False for silent grandfathering.

    Returns:
        True only on the first award; False when the vendor already has the
        V-Batch (including a second award attempt with a different source,
        or a BVN award attempted while the platform BVN toggle is OFF).
    """
    from apps.vendors.models import VendorProfile

    if not vendor or not vendor.pk or vendor.has_vbatch:
        return False

    # Rule 1 - the BVN award is gated by the platform-wide BVN verification
    # toggle, enforced here so no caller can bypass it.  Flipping the toggle
    # never runs this UPDATE in reverse, so a later change cannot take a
    # badge away either.
    if source == 'bvn' and not _bvn_toggle_is_on():
        logger.info(
            'V-Batch BVN award skipped for vendor %s (BVN toggle OFF)',
            vendor.pk,
        )
        return False

    now = timezone.now()
    # Conditional UPDATE: the WHERE clause makes this atomic, so exactly one
    # caller can flip 0 -> 1.  It never touches an already-earned row, which
    # is what keeps the original source and timestamp intact.
    updated = VendorProfile.objects.filter(pk=vendor.pk).exclude(
        has_vbatch=True
    ).update(
        has_vbatch=True,
        vbatch_earned_at=now,
        vbatch_source=source,
    )
    if updated != 1:
        return False

    # Keep the in-memory instance consistent for the rest of the request.
    vendor.has_vbatch = True
    vendor.vbatch_earned_at = now
    vendor.vbatch_source = source

    logger.info(
        'V-Batch awarded to vendor %s (source=%s)', vendor.pk, source,
    )

    if notify:
        try:
            _notify_vbatch_earned(vendor)
        except Exception:
            # A failed notification must never undo an award.
            logger.exception(
                'V-Batch notification failed for vendor %s', vendor.pk,
            )

    return True


def _notify_vbatch_earned(vendor):
    """One in-app + email notification, first award only."""
    from apps.vendors.services.notification_dispatch import create_notification

    user = getattr(vendor, 'user', None)
    if user is None:
        return

    create_notification(
        user=user,
        notification_type=VBATCH_NOTIFICATION_TYPE,
        title=VBATCH_TITLE,
        message=VBATCH_MESSAGE,
        link=VBATCH_LINK,
        vendor=vendor,
    )


def _bvn_toggle_is_on():
    """
    The platform-wide "BVN verification enabled" toggle (Phase 8B).

    Read from the single PlatformSettings row, which ships OFF (default) and
    is edited by a superuser in the admin.

    ON  = BVN verification is enabled -> a BVN success may award.
    OFF = BVN verification is disabled -> no BVN award, and the BVN flow
          itself is rejected before any Dojah call.

    The toggle is platform-wide, so it never looks at the vendor: suspending
    a vendor has no effect on awarding either way.  Flipping it after an
    award changes nothing - this helper is only ever consulted at award time,
    and no code path ever clears an earned badge.

    Cost: at most one cheap primary-key query per call, so never call it in
    a loop.
    """
    from apps.vendors.models import PlatformSettings

    return PlatformSettings.get_solo().bvn_verification_enabled
