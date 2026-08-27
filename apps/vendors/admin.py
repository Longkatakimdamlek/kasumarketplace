"""
Vendor App Django Admin
Provides admin interface for managing vendors, verification, stores, products, etc.
"""

import logging
import cloudinary.uploader

from django.contrib import admin
from django.utils.html import format_html
from django.urls import reverse
from django.utils import timezone
from django.db.models import Count, Sum, Q
from django.contrib import messages
from django.db import transaction

from .models import (
    VendorProfile, PendingReviewVendor, VerificationAttempt,
    MainCategory, SubCategory,
    Store, CategoryChangeRequest, Product, ProductImage,
    Wallet, Transaction, Order, OrderItem, RefundRequest, Notification,
    SubCategoryAttribute
)

logger = logging.getLogger(__name__)


# ==========================================
# SHARED HELPERS
# ==========================================

def _confidence_badge(confidence):
    """Colour-coded confidence badge — used in both VendorProfileAdmin and PendingReviewAdmin."""
    if confidence is None:
        return format_html('<span style="color:#9ca3af;">—</span>')
    try:
        score = float(confidence)
    except (TypeError, ValueError):
        return format_html('<span style="color:#9ca3af;">—</span>')
    if score >= 90:
        color, bg, label = '#15803d', '#dcfce7', 'AUTO-VERIFIED'
    elif score >= 75:
        color, bg, label = '#92400e', '#fef3c7', 'PENDING REVIEW'
    else:
        color, bg, label = '#b91c1c', '#fee2e2', 'LOW'
    score_display = f'{score:.1f}'
    return format_html(
        '<span style="display:inline-flex;align-items:center;gap:6px;padding:3px 10px;'
        'border-radius:999px;font-size:11px;font-weight:600;color:{};background:{};">'
        '{}% &nbsp;·&nbsp; {}</span>',
        color, bg, score_display, label,
    )


def _purge_live_selfie(vendor, reason, admin_user):
    """
    Delete the live selfie from Cloudinary and clear identity_selfie.
    Called after any terminal admin decision (approve or reject) so the
    image is never retained beyond the review window.
    Writes an audit note to the most recent VerificationAttempt.
    """
    if not vendor.identity_selfie:
        return

    public_id = None
    try:
        public_id = str(vendor.identity_selfie)
        cloudinary.uploader.destroy(public_id)
        logger.info(
            f"🗑️  Deleted review selfie '{public_id}' for vendor "
            f"{vendor.pk} — reason: {reason}"
        )
    except Exception as exc:
        logger.error(
            f"❌ Cloudinary delete failed for '{public_id}' "
            f"(vendor {vendor.pk}): {exc}"
        )

    # Clear the field regardless — we never want to re-display this image.
    vendor.identity_selfie = None
    vendor.save(update_fields=['identity_selfie'])

    # Audit trail on the most recent bvn VerificationAttempt
    attempt = (
        VerificationAttempt.objects
        .filter(vendor=vendor, attempt_type='bvn')
        .order_by('-created_at')
        .first()
    )
    if attempt:
        attempt.response_data = {
            **attempt.response_data,
            'admin_selfie_purge': {
                'reason': reason,
                'purged_by': admin_user.email if admin_user else 'system',
                'purged_at': timezone.now().isoformat(),
                'cloudinary_public_id': public_id,
            }
        }
        attempt.save(update_fields=['response_data'])


# ==========================================
# INLINE ADMIN CLASSES
# ==========================================

class VerificationAttemptInline(admin.TabularInline):
    """Show verification attempts inside VendorProfile admin"""
    model = VerificationAttempt
    extra = 0
    readonly_fields = ['attempt_type', 'status', 'error_message', 'created_at']
    can_delete = False

    def has_add_permission(self, request, obj=None):
        return False


class ProductImageInline(admin.TabularInline):
    """Manage product images inside Product admin"""
    model = ProductImage
    extra = 1
    fields = ['image', 'alt_text', 'is_primary', 'sort_order']


class OrderItemInline(admin.TabularInline):
    """Show order items inside Order admin"""
    model = OrderItem
    extra = 0
    readonly_fields = ['product', 'quantity', 'price', 'total']
    can_delete = False


# ==========================================
# PENDING VERIFICATION REVIEW QUEUE
# ==========================================

@admin.register(PendingReviewVendor)
class PendingReviewAdmin(admin.ModelAdmin):
    """
    Dedicated identity-review queue.
    Only vendors whose selfie confidence landed in 75–89% appear here.
    Admin compares live selfie vs Dojah BVN reference photo side-by-side,
    then approves or rejects with a single action.

    On either decision:
      - Vendor status updates atomically inside a transaction
      - Live selfie is purged from Cloudinary immediately
      - Audit trail is written to VerificationAttempt.response_data
      - In-app notification is sent to the vendor
    """

    list_display_links = ['vendor_full_name']
    ordering           = ['created_at']   # oldest first — FIFO
    actions            = ['approve_verification', 'reject_verification']

    list_display = [
        'vendor_full_name',
        'user_email',
        'confidence_col',
        'submitted_col',
        'risk_col',
        'review_link',
    ]

    readonly_fields = [
        'vendor_full_name', 'user_email', 'confidence_col',
        'risk_col', 'submitted_col',
        'side_by_side_images',
        'identity_data_panel',
        'audit_trail_panel',
        'admin_comment',
    ]

    fieldsets = [
        ('📋 Vendor', {
            'fields': ['vendor_full_name', 'user_email', 'submitted_col'],
        }),
        ('🖼️ Image Comparison', {
            'description': (
                'Compare the live selfie (left) captured during verification '
                'against the reference photo Dojah retrieved for this BVN (right). '
                'Confidence score is shown below.'
            ),
            'fields': ['side_by_side_images', 'confidence_col'],
        }),
        ('👤 Identity Data (from Dojah)', {
            'fields': ['identity_data_panel'],
        }),
        ('⚠️ Risk', {
            'fields': ['risk_col'],
        }),
        ('📝 Admin Notes', {
            'fields': ['admin_comment'],
        }),
        ('🕵️ Audit Trail', {
            'classes': ['collapse'],
            'fields': ['audit_trail_panel'],
        }),
    ]

    def get_queryset(self, request):
        return (
            super().get_queryset(request)
            .filter(bank_status='pending_review')
            .select_related('user')
        )

    # ── List columns ──────────────────────────────────────────────────────

    @admin.display(description='Vendor')
    def vendor_full_name(self, obj):
        return obj.full_name or '—'

    @admin.display(description='Email')
    def user_email(self, obj):
        return obj.user.email

    @admin.display(description='Confidence')
    def confidence_col(self, obj):
        return _confidence_badge(obj.selfie_confidence)

    @admin.display(description='Submitted')
    def submitted_col(self, obj):
        ts = obj.updated_at
        return ts.strftime('%d %b %Y, %H:%M') if ts else '—'

    @admin.display(description='Risk')
    def risk_col(self, obj):
        score = obj.risk_score or 0
        if score == 0:
            color, bg, label = '#15803d', '#dcfce7', 'LOW'
        elif score <= 30:
            color, bg, label = '#92400e', '#fef3c7', 'MEDIUM'
        else:
            color, bg, label = '#b91c1c', '#fee2e2', 'HIGH'
        flags = []
        if obj.has_duplicate_bvn:
            flags.append('duplicate BVN')
        if obj.is_underage:
            flags.append('underage')
        flag_html = (
            format_html(' &nbsp;·&nbsp; <em style="font-weight:400">{}</em>', ', '.join(flags))
            if flags else format_html('')
        )
        return format_html(
            '<span style="display:inline-flex;align-items:center;padding:3px 10px;'
            'border-radius:999px;font-size:11px;font-weight:600;color:{};background:{};">'
            '{} {}{}</span>',
            color, bg, score, label, flag_html,
        )

    @admin.display(description='')
    def review_link(self, obj):
        url = reverse('admin:vendors_pendingreviewvendor_change', args=[obj.pk])
        return format_html(
            '<a href="{}" style="padding:4px 12px;border-radius:6px;font-size:12px;'
            'font-weight:600;color:#fff;background:#6a3df5;text-decoration:none;">'
            'Review →</a>',
            url,
        )

    # ── Detail panels ─────────────────────────────────────────────────────

    @admin.display(description='Image Comparison')
    def side_by_side_images(self, obj):
        if obj.identity_selfie:
            live_html = format_html(
                '<img src="{}" style="width:100%;max-width:260px;height:auto;'
                'border-radius:12px;border:2px solid #e5e7eb;display:block;" />',
                obj.identity_selfie.url,
            )
        else:
            live_html = format_html(
                '<div style="width:260px;height:300px;background:#f5f5f7;border-radius:12px;'
                'border:2px dashed #d1d5db;display:flex;align-items:center;justify-content:center;'
                'color:#9ca3af;font-size:13px;text-align:center;padding:16px;">'
                'Live selfie not available<br>'
                '<small>(storage may have failed at capture time)</small></div>'
            )

        if obj.selfie_image_url:
            dojah_html = format_html(
                '<img src="{}" style="width:100%;max-width:260px;height:auto;'
                'border-radius:12px;border:2px solid #e5e7eb;display:block;" />',
                obj.selfie_image_url,
            )
        else:
            dojah_html = format_html(
                '<div style="width:260px;height:300px;background:#f5f5f7;border-radius:12px;'
                'border:2px dashed #d1d5db;display:flex;align-items:center;justify-content:center;'
                'color:#9ca3af;font-size:13px;text-align:center;padding:16px;">'
                'Dojah reference photo not available</div>'
            )

        return format_html(
            '<div style="display:flex;gap:32px;flex-wrap:wrap;margin:8px 0;">'
            '<div style="flex:1;min-width:220px;">'
            '<p style="font-size:11px;font-weight:600;color:#6b7280;text-transform:uppercase;'
            'letter-spacing:.05em;margin:0 0 8px;">Live Selfie (captured)</p>{}</div>'
            '<div style="flex:1;min-width:220px;">'
            '<p style="font-size:11px;font-weight:600;color:#6b7280;text-transform:uppercase;'
            'letter-spacing:.05em;margin:0 0 8px;">Dojah BVN Reference Photo</p>{}</div>'
            '</div>',
            live_html, dojah_html,
        )

    @admin.display(description='Identity Data')
    def identity_data_panel(self, obj):
        rows = [
            ('Full Name', obj.full_name or '—'),
            ('BVN',       obj.get_masked_bvn()),
            ('DOB',       obj.dob.strftime('%d %b %Y') if obj.dob else '—'),
            ('Age',       f'{obj.calculated_age} yrs' if obj.calculated_age else '—'),
            ('Gender',    obj.get_gender_display() if obj.gender else '—'),
            ('Phone',     obj.get_masked_phone()),
        ]
        rows_html = ''.join(
            format_html(
                '<tr>'
                '<td style="padding:8px 12px;font-size:12px;color:#6b7280;font-weight:600;'
                'white-space:nowrap;border-bottom:1px solid #f3f4f6;">{}</td>'
                '<td style="padding:8px 12px;font-size:13px;color:#111;'
                'border-bottom:1px solid #f3f4f6;">{}</td></tr>',
                label, value,
            )
            for label, value in rows
        )
        return format_html(
            '<table style="border-collapse:collapse;width:100%;max-width:480px;'
            'background:#fafafa;border-radius:10px;overflow:hidden;'
            'border:1px solid #e5e7eb;">{}</table>',
            rows_html,
        )

    @admin.display(description='Audit Trail')
    def audit_trail_panel(self, obj):
        attempts = (
            VerificationAttempt.objects
            .filter(vendor=obj, attempt_type='bvn')
            .order_by('-created_at')[:5]
        )
        if not attempts:
            return '—'
        rows_html = ''.join(
            format_html(
                '<tr>'
                '<td style="padding:6px 10px;font-size:12px;color:#6b7280;white-space:nowrap;">{}</td>'
                '<td style="padding:6px 10px;font-size:12px;color:#111;">{}</td>'
                '<td style="padding:6px 10px;font-size:12px;color:#6b7280;">{}</td>'
                '</tr>',
                a.created_at.strftime('%d %b %Y %H:%M'),
                a.get_status_display(),
                a.error_message[:80] if a.error_message else '—',
            )
            for a in attempts
        )
        return format_html(
            '<table style="border-collapse:collapse;width:100%;max-width:600px;'
            'background:#fafafa;border-radius:10px;border:1px solid #e5e7eb;">'
            '<thead><tr>'
            '<th style="padding:6px 10px;font-size:11px;color:#9ca3af;text-align:left;'
            'border-bottom:1px solid #e5e7eb;">Date</th>'
            '<th style="padding:6px 10px;font-size:11px;color:#9ca3af;text-align:left;'
            'border-bottom:1px solid #e5e7eb;">Status</th>'
            '<th style="padding:6px 10px;font-size:11px;color:#9ca3af;text-align:left;'
            'border-bottom:1px solid #e5e7eb;">Note</th>'
            '</tr></thead><tbody>{}</tbody></table>',
            rows_html,
        )

    # ── Actions ───────────────────────────────────────────────────────────

    @admin.action(description='✅  Approve — mark as Verified')
    def approve_verification(self, request, queryset):
        approved = skipped = 0
        for vendor in queryset:
            if vendor.bank_status != 'pending_review':
                skipped += 1
                continue
            try:
                with transaction.atomic():
                    vendor.bank_status         = 'verified'
                    vendor.verification_status = 'bvn_verified'
                    vendor.bvn_verified_at     = timezone.now()
                    vendor.reviewed_by         = request.user
                    vendor.reviewed_at         = timezone.now()
                    vendor.calculate_risk_score()
                    vendor.save(update_fields=[
                        'bank_status', 'verification_status', 'bvn_verified_at',
                        'reviewed_by', 'reviewed_at', 'risk_score',
                    ])

                    # Sync wallet
                    try:
                        wallet = vendor.wallet
                        wallet.account_holder_name = vendor.full_name
                        wallet.is_verified = True
                        wallet.verified_at = timezone.now()
                        wallet.save()
                    except Exception as w_err:
                        logger.warning(f'Wallet update failed for {vendor.pk}: {w_err}')

                    # Purge live selfie — not needed after decision
                    _purge_live_selfie(vendor, reason='approved', admin_user=request.user)

                    try:
                        Notification.objects.create(
                            vendor=vendor,
                            notification_type='verification',
                            title='Identity Verified ✅',
                            message=(
                                'Your identity has been verified successfully. '
                                'You can now continue setting up your store.'
                            ),
                            link='/vendors/verification/',
                        )
                    except Exception as n_err:
                        logger.warning(f'Notification failed for {vendor.pk}: {n_err}')

                    logger.info(
                        f'✅ APPROVED: vendor {vendor.pk} ({vendor.full_name}) '
                        f'by {request.user.email}'
                    )
                    approved += 1
            except Exception as exc:
                logger.error(f'Approve failed for vendor {vendor.pk}: {exc}')
                messages.error(request, f'Failed to approve {vendor.full_name}: {exc}')

        if approved:
            messages.success(request, f'✅ {approved} vendor(s) approved.')
        if skipped:
            messages.warning(request, f'{skipped} skipped — not in pending_review status.')

    @admin.action(description='❌  Reject — mark as Failed')
    def reject_verification(self, request, queryset):
        rejected = skipped = 0
        for vendor in queryset:
            if vendor.bank_status != 'pending_review':
                skipped += 1
                continue
            try:
                with transaction.atomic():
                    vendor.bank_status  = 'failed'
                    vendor.reviewed_by  = request.user
                    vendor.reviewed_at  = timezone.now()
                    vendor.calculate_risk_score()

                    # Admin rejection counts as a failed attempt
                    progress = vendor.verification_progress or {}
                    progress['bvn_attempts'] = progress.get('bvn_attempts', 0) + 1
                    vendor.verification_progress = progress

                    vendor.save(update_fields=[
                        'bank_status', 'reviewed_by', 'reviewed_at',
                        'risk_score', 'verification_progress',
                    ])

                    VerificationAttempt.objects.create(
                        vendor=vendor, attempt_type='bvn', status='failed',
                        request_data={}, response_data={},
                        error_message=(
                            f'Rejected by admin ({request.user.email}) after manual review.'
                        ),
                    )

                    _purge_live_selfie(vendor, reason='rejected', admin_user=request.user)

                    try:
                        Notification.objects.create(
                            vendor=vendor,
                            notification_type='verification',
                            title='Verification Not Approved',
                            message=(
                                'Your identity verification could not be approved '
                                'after review. You may try again or contact support.'
                            ),
                            link='/vendors/verification/',
                        )
                    except Exception as n_err:
                        logger.warning(f'Notification failed for {vendor.pk}: {n_err}')

                    logger.warning(
                        f'❌ REJECTED: vendor {vendor.pk} ({vendor.full_name}) '
                        f'by {request.user.email}'
                    )
                    rejected += 1
            except Exception as exc:
                logger.error(f'Reject failed for vendor {vendor.pk}: {exc}')
                messages.error(request, f'Failed to reject {vendor.full_name}: {exc}')

        if rejected:
            messages.success(request, f'❌ {rejected} vendor(s) rejected.')
        if skipped:
            messages.warning(request, f'{skipped} skipped — not in pending_review status.')

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


# ==========================================
# VENDOR PROFILE ADMIN
# ==========================================

@admin.register(VendorProfile)
class VendorProfileAdmin(admin.ModelAdmin):
    list_display = [
        'vendor_id_short', 'full_name', 'user_email',
        'verification_badge', 'bank_badge', 'selfie_confidence_badge',
        'student_badge', 'risk_flags_badge',
        'can_sell_badge', 'created_at'
    ]
    list_filter = [
        'verification_status', 'bank_status',
        'student_status', 'created_at',
        'has_duplicate_bvn', 'is_underage',
    ]
    search_fields = [
        'full_name', 'user__email', 'phone', 'matric_number',
        'vendor_id', 'bvn_number'
    ]
    readonly_fields = [
        'vendor_id', 'user', 'created_at', 'updated_at',
        'bvn_verified_at', 'student_verified_at',
        'approved_at', 'completion_percentage', 'current_step',
        'identity_selfie_preview', 'student_id_preview', 'selfie_preview',
        'registration_ip', 'bvn_verification_ip',
        'risk_score', 'risk_flags_summary', 'calculated_age',
        'duplicate_bvn_vendor_id',
        'bvn_number', 'selfie_match', 'selfie_confidence', 'selfie_image_url',
    ]
    fieldsets = (
        ('👤 Basic Information', {
            'fields': (
                'vendor_id', 'user', 'full_name', 'phone',
                'gender', 'dob', 'calculated_age'
            )
        }),
        ('🏦 Identity Verification (BVN + Selfie)', {
            'fields': (
                'bank_status', 'bvn_number',
                'identity_selfie', 'identity_selfie_preview',
                'selfie_match', 'selfie_confidence', 'selfie_image_url',
                'bvn_verified_at', 'bvn_verification_ip'
            ),
            'description': (
                '🔒 Auto-filled from Dojah BVN+Selfie API — read-only once '
                'bank_status is Verified. confidence ≥ 90% auto-verifies, '
                '75–90% goes to Pending Review queue, <75% fails.'
            )
        }),
        ('🎓 Student Verification (Optional)', {
            'fields': (
                'student_status', 'matric_number', 'department', 'level',
                'student_id_image', 'student_id_preview',
                'selfie', 'selfie_preview', 'student_verified_at'
            )
        }),
        ('🏪 Store Setup', {
            'fields': ('store_setup_completed', 'store_setup_skipped')
        }),
        ('✅ Verification Status', {
            'fields': (
                'verification_status', 'completion_percentage', 'current_step',
                'admin_comment', 'reviewed_by', 'reviewed_at', 'approved_at'
            )
        }),
        ('🚩 Risk & Compliance Alerts', {
            'fields': ('risk_flags_summary', 'duplicate_bvn_vendor_id'),
            'classes': ('collapse',),
            'description': '⚠️ Automated security alerts — review before approving vendor.'
        }),
        ('🔒 Security & Tracking', {
            'fields': ('registration_ip',),
            'classes': ('collapse',),
        }),
        ('📝 Admin Internal Notes', {
            'fields': ('admin_internal_notes',),
            'description': '⚠️ PRIVATE NOTES — NOT visible to vendor.'
        }),
        ('📊 Progress Tracking', {
            'fields': ('verification_progress',),
            'classes': ('collapse',)
        }),
        ('🕐 Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )
    inlines = [VerificationAttemptInline]
    actions = [
        'approve_vendors',
        'reject_vendors',
        'suspend_vendors',
        'approve_pending_review',
        'reject_pending_review',
        'recalculate_risk_scores',
        'flag_for_review',
    ]

    # ── Display methods ──────────────────────────────────────────────────

    def vendor_id_short(self, obj):
        return str(obj.vendor_id)[:8]
    vendor_id_short.short_description = 'Vendor ID'

    def user_email(self, obj):
        return obj.user.email
    user_email.short_description = 'Email'

    def verification_badge(self, obj):
        colors = {
            'approved': '#10b981', 'rejected': '#ef4444',
            'pending': '#f59e0b', 'bvn_verified': '#3b82f6',
            'student_verified': '#3b82f6', 'suspended': '#6b7280',
        }
        color = colors.get(obj.verification_status, '#6b7280')
        return format_html(
            '<span style="background-color:{};color:white;padding:4px 12px;'
            'border-radius:6px;font-weight:600;font-size:11px;">{}</span>',
            color, obj.get_verification_status_display()
        )
    verification_badge.short_description = 'Status'

    def bank_badge(self, obj):
        if obj.bank_status == 'verified':
            return format_html('<span style="color:#10b981;font-weight:600;">✓ BVN Verified</span>')
        if obj.bank_status == 'pending_review':
            return format_html('<span style="color:#f59e0b;font-weight:600;">⏳ Pending Review</span>')
        if obj.bank_status == 'failed':
            return format_html('<span style="color:#ef4444;font-weight:600;">✗ Failed</span>')
        return format_html('<span style="color:#6b7280;">— Not Started</span>')
    bank_badge.short_description = 'Banking'

    def selfie_confidence_badge(self, obj):
        return _confidence_badge(obj.selfie_confidence)
    selfie_confidence_badge.short_description = 'Confidence'

    def student_badge(self, obj):
        if obj.student_status == 'verified':
            return format_html('<span style="color:#10b981;font-weight:600;">✓ Student</span>')
        elif obj.student_status == 'not_applicable':
            return format_html('<span style="color:#6b7280;">N/A</span>')
        return format_html('<span style="color:#f59e0b;">⏳ Student</span>')
    student_badge.short_description = 'Student'

    def can_sell_badge(self, obj):
        if obj.can_sell:
            return format_html('<span style="color:#10b981;font-weight:700;">✓ Can Sell</span>')
        return format_html('<span style="color:#ef4444;font-weight:600;">✗ Cannot Sell</span>')
    can_sell_badge.short_description = 'Can Sell?'

    def identity_selfie_preview(self, obj):
        if obj.identity_selfie:
            return format_html(
                '<img src="{}" width="100" height="100" '
                'style="object-fit:cover;border-radius:8px;border:2px solid #e5e7eb;" />',
                obj.identity_selfie.url
            )
        return '—'
    identity_selfie_preview.short_description = 'BVN Selfie'

    def student_id_preview(self, obj):
        if obj.student_id_image:
            return format_html(
                '<img src="{}" width="150" '
                'style="max-height:100px;object-fit:contain;border-radius:8px;'
                'border:2px solid #e5e7eb;" />',
                obj.student_id_image.url
            )
        return '—'
    student_id_preview.short_description = 'Student ID'

    def selfie_preview(self, obj):
        if obj.selfie:
            return format_html(
                '<img src="{}" width="100" height="100" '
                'style="object-fit:cover;border-radius:8px;border:2px solid #e5e7eb;" />',
                obj.selfie.url
            )
        return '—'
    selfie_preview.short_description = 'Student Selfie'

    def risk_flags_badge(self, obj):
        flags = []
        if obj.has_duplicate_bvn:
            flags.append('⚠️ BVN')
        if obj.is_underage:
            flags.append('🚫 Age')
        if obj.bank_status == 'pending_review':
            flags.append('🔍 Review')
        if flags:
            color = '#ef4444' if obj.risk_score > 50 else '#f59e0b'
            return format_html(
                '<span style="color:{};font-weight:700;font-size:12px;">{}</span>',
                color, ' '.join(flags)
            )
        return format_html('<span style="color:#10b981;font-weight:600;">✓ Clean</span>')
    risk_flags_badge.short_description = 'Risk Flags'

    def risk_flags_summary(self, obj):
        flags = []
        if obj.has_duplicate_bvn:
            flags.append(f'''
                <div style="background:#fee2e2;border-left:4px solid #dc2626;
                            padding:12px;margin:8px 0;border-radius:6px;">
                    <strong style="color:#991b1b;">❌ DUPLICATE BVN</strong><br>
                    <span style="color:#7f1d1d;font-size:13px;">
                        This BVN is already registered on another account.<br>
                        <strong>Other Vendor ID:</strong> {obj.duplicate_bvn_vendor_id or 'Unknown'}
                    </span>
                </div>
            ''')
        if obj.is_underage:
            age = obj.calculated_age or 0
            flags.append(f'''
                <div style="background:#fee2e2;border-left:4px solid #dc2626;
                            padding:12px;margin:8px 0;border-radius:6px;">
                    <strong style="color:#991b1b;">🚫 UNDERAGE VENDOR</strong><br>
                    <span style="color:#7f1d1d;font-size:13px;">
                        Vendor is <strong>{age} years old</strong> (must be 18+)<br>
                        <strong>DOB:</strong> {obj.dob.strftime('%B %d, %Y') if obj.dob else 'Unknown'}
                    </span>
                </div>
            ''')
        if obj.bank_status == 'pending_review':
            flags.append(f'''
                <div style="background:#fef3c7;border-left:4px solid #f59e0b;
                            padding:12px;margin:8px 0;border-radius:6px;">
                    <strong style="color:#78350f;">🔍 BORDERLINE SELFIE MATCH — NEEDS MANUAL REVIEW</strong><br>
                    <span style="color:#78350f;font-size:13px;">
                        Confidence: <strong>{obj.selfie_confidence}%</strong> (75–90% review band)<br>
                        Use the <strong>Pending Verification Reviews</strong> queue in the sidebar
                        to compare images and approve or reject.
                    </span>
                </div>
            ''')
        if not flags:
            return format_html(
                '<div style="background:#d1fae5;border-left:4px solid #10b981;'
                'padding:12px;border-radius:6px;">'
                '<strong style="color:#065f46;">✅ NO RISK FLAGS DETECTED</strong><br>'
                '<span style="color:#047857;font-size:13px;">'
                'All automated security checks passed successfully.</span></div>'
            )
        risk_color = '#dc2626' if obj.risk_score > 50 else '#f59e0b' if obj.risk_score > 20 else '#10b981'
        risk_bar = (
            f'<div style="background:#fef3c7;border-left:4px solid #f59e0b;'
            f'padding:12px;margin-top:12px;border-radius:6px;">'
            f'<strong style="color:#78350f;">RISK SCORE: {obj.risk_score}/100</strong>'
            f'<div style="width:100%;background:#e5e7eb;height:24px;border-radius:6px;'
            f'margin-top:8px;overflow:hidden;">'
            f'<div style="width:{obj.risk_score}%;background:{risk_color};height:100%;'
            f'display:flex;align-items:center;justify-content:center;'
            f'color:white;font-weight:600;font-size:12px;">{obj.risk_score}%</div>'
            f'</div></div>'
        )
        return format_html(''.join(flags) + risk_bar)
    risk_flags_summary.short_description = '⚠️ Risk Assessment'

    # ── Actions ──────────────────────────────────────────────────────────

    def approve_vendors(self, request, queryset):
        """Final overall approval — distinct from BVN-specific approval."""
        count = 0
        warnings = []
        for vendor in queryset:
            if vendor.bank_status != 'verified':
                warnings.append(f'{vendor.full_name}: BVN+selfie not verified')
                continue
            if vendor.risk_score > 50:
                warnings.append(f'⚠️ {vendor.full_name}: HIGH RISK ({vendor.risk_score}/100)')
                continue
            if vendor.is_underage:
                warnings.append(f'🚫 {vendor.full_name}: UNDERAGE ({vendor.calculated_age} years)')
                continue
            vendor.verification_status = 'approved'
            vendor.approved_at  = timezone.now()
            vendor.reviewed_by  = request.user
            vendor.reviewed_at  = timezone.now()
            vendor.save()
            count += 1
            logger.info(f"✅ VENDOR APPROVED: {vendor.full_name} by {request.user.email}")
        if warnings:
            self.message_user(request, ' | '.join(warnings), messages.WARNING)
        if count:
            self.message_user(request, f'✅ Approved {count} vendor(s)', messages.SUCCESS)
    approve_vendors.short_description = '✅ Approve selected vendors'

    def reject_vendors(self, request, queryset):
        count = queryset.update(
            verification_status='rejected',
            reviewed_by=request.user,
            reviewed_at=timezone.now()
        )
        self.message_user(request, f'❌ Rejected {count} vendor(s)', messages.WARNING)
    reject_vendors.short_description = '❌ Reject selected vendors'

    def suspend_vendors(self, request, queryset):
        count = queryset.update(verification_status='suspended')
        self.message_user(request, f'⏸ Suspended {count} vendor(s)', messages.WARNING)
    suspend_vendors.short_description = '⏸ Suspend selected vendors'

    def approve_pending_review(self, request, queryset):
        """
        Approve vendors in the BVN selfie 75–90% review band from the
        main VendorProfile list. Mirrors PendingReviewAdmin.approve_verification
        but available from the general vendor list for convenience.
        """
        pending_qs = queryset.filter(bank_status='pending_review')
        count = 0
        for vendor in pending_qs:
            try:
                with transaction.atomic():
                    vendor.bank_status         = 'verified'
                    vendor.verification_status = 'bvn_verified'
                    vendor.bvn_verified_at     = timezone.now()
                    vendor.reviewed_by         = request.user
                    vendor.reviewed_at         = timezone.now()
                    vendor.save()
                    try:
                        wallet = vendor.wallet
                        wallet.account_holder_name = vendor.full_name
                        wallet.is_verified = True
                        wallet.verified_at = timezone.now()
                        wallet.save()
                    except Exception:
                        logger.warning(f'Wallet update failed for {vendor.pk}')
                    _purge_live_selfie(vendor, reason='approved', admin_user=request.user)
                    Notification.objects.create(
                        vendor=vendor,
                        notification_type='verification',
                        title='Verification Approved ✅',
                        message='Your identity verification has been manually reviewed and approved.',
                        link='/vendors/verification/'
                    )
                    logger.info(
                        f"✅ BVN PENDING-REVIEW APPROVED: {vendor.full_name} "
                        f"(confidence: {vendor.selfie_confidence}%) by {request.user.email}"
                    )
                    count += 1
            except Exception as exc:
                logger.error(f'approve_pending_review failed for {vendor.pk}: {exc}')
                messages.error(request, f'Failed to approve {vendor.full_name}: {exc}')
        self.message_user(request, f'✅ Approved {count} pending-review verification(s)', messages.SUCCESS)
    approve_pending_review.short_description = '✅ Approve pending-review verifications'

    def reject_pending_review(self, request, queryset):
        """
        Reject vendors in the BVN selfie 75–90% review band.
        Counts toward the 3-failed-attempt cap.
        """
        pending_qs = queryset.filter(bank_status='pending_review')
        count = 0
        for vendor in pending_qs:
            try:
                with transaction.atomic():
                    vendor.bank_status = 'failed'
                    vendor.reviewed_by = request.user
                    vendor.reviewed_at = timezone.now()
                    progress = vendor.verification_progress or {}
                    progress['bvn_attempts'] = progress.get('bvn_attempts', 0) + 1
                    vendor.verification_progress = progress
                    vendor.save()
                    VerificationAttempt.objects.create(
                        vendor=vendor, attempt_type='bvn', status='failed',
                        request_data={}, response_data={},
                        error_message=f'Rejected by admin ({request.user.email}) after manual review.',
                    )
                    _purge_live_selfie(vendor, reason='rejected', admin_user=request.user)
                    Notification.objects.create(
                        vendor=vendor,
                        notification_type='verification',
                        title='Verification Not Approved',
                        message='Your identity verification could not be approved after review. You may try again or contact support.',
                        link='/vendors/verification/'
                    )
                    logger.warning(
                        f"❌ BVN PENDING-REVIEW REJECTED: {vendor.full_name} "
                        f"(confidence: {vendor.selfie_confidence}%) by {request.user.email}"
                    )
                    count += 1
            except Exception as exc:
                logger.error(f'reject_pending_review failed for {vendor.pk}: {exc}')
                messages.error(request, f'Failed to reject {vendor.full_name}: {exc}')
        self.message_user(request, f'❌ Rejected {count} pending-review verification(s)', messages.WARNING)
    reject_pending_review.short_description = '❌ Reject pending-review verifications'

    def recalculate_risk_scores(self, request, queryset):
        count = 0
        for vendor in queryset:
            vendor.calculate_risk_score()
            vendor.save()
            count += 1
        self.message_user(request, f'🔄 Recalculated risk scores for {count} vendor(s)', messages.SUCCESS)
    recalculate_risk_scores.short_description = '🔄 Recalculate risk scores'

    def flag_for_review(self, request, queryset):
        count = 0
        for vendor in queryset:
            note = (
                f"\n[FLAGGED FOR REVIEW by {request.user.email} "
                f"on {timezone.now().strftime('%Y-%m-%d %H:%M')}]\n"
            )
            vendor.admin_internal_notes = (vendor.admin_internal_notes or '') + note
            vendor.save()
            count += 1
        self.message_user(request, f'🚩 Flagged {count} vendor(s) for manual review', messages.INFO)
    flag_for_review.short_description = '🚩 Flag for manual review'


# ==========================================
# VERIFICATION ATTEMPT (audit log — read-only)
# ==========================================

@admin.register(VerificationAttempt)
class VerificationAttemptAdmin(admin.ModelAdmin):
    list_display  = ['vendor', 'attempt_type', 'status', 'created_at']
    list_filter   = ['attempt_type', 'status', 'created_at']
    search_fields = ['vendor__full_name', 'vendor__user__email']
    readonly_fields = ['vendor', 'attempt_type', 'status', 'request_data', 'response_data', 'created_at']

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return request.user.is_superuser


# ==========================================
# CATEGORIES ADMIN
# ==========================================

class SubCategoryInline(admin.TabularInline):
    model = SubCategory
    extra = 1
    fields = ['name', 'slug', 'icon', 'is_active', 'sort_order']
    prepopulated_fields = {'slug': ('name',)}


@admin.register(MainCategory)
class MainCategoryAdmin(admin.ModelAdmin):
    list_display  = ['name', 'icon', 'slug', 'subcategory_count', 'store_count', 'is_active', 'sort_order']
    list_editable = ['icon', 'is_active', 'sort_order']
    search_fields = ['name']
    prepopulated_fields = {'slug': ('name',)}
    inlines = [SubCategoryInline]

    def subcategory_count(self, obj):
        return obj.subcategories.count()
    subcategory_count.short_description = 'Subcategories'

    def store_count(self, obj):
        return obj.stores.count()
    store_count.short_description = 'Stores'


@admin.register(SubCategory)
class SubCategoryAdmin(admin.ModelAdmin):
    list_display  = ['name', 'main_category', 'product_count', 'is_active', 'sort_order']
    list_filter   = ['main_category', 'is_active']
    list_editable = ['is_active', 'sort_order']
    search_fields = ['name', 'main_category__name']
    prepopulated_fields = {'slug': ('name',)}

    def product_count(self, obj):
        return obj.products.count()
    product_count.short_description = 'Products'


@admin.register(SubCategoryAttribute)
class SubCategoryAttributeAdmin(admin.ModelAdmin):
    list_display  = ('name', 'subcategory', 'field_type', 'is_required', 'is_active', 'sort_order')
    list_filter   = ('subcategory', 'field_type', 'is_active')
    search_fields = ('name',)
    ordering      = ('subcategory', 'sort_order')


# ==========================================
# STORE ADMIN
# ==========================================

@admin.register(Store)
class StoreAdmin(admin.ModelAdmin):
    list_display = [
        'store_name', 'vendor_name', 'main_category',
        'category_locked_badge', 'is_published', 'sponsorship_status',
        'total_products', 'total_orders', 'total_sales', 'average_rating'
    ]
    list_filter   = [
        'main_category', 'is_published', 'is_sponsored',
        'main_category_locked', 'created_at', 'sponsored_until'
    ]
    search_fields = ['store_name', 'vendor__full_name', 'vendor__user__email']
    actions = ['activate_sponsorship', 'deactivate_sponsorship']
    readonly_fields = [
        'slug', 'vendor', 'main_category_locked', 'main_category_locked_at',
        'total_products', 'total_orders', 'total_sales', 'average_rating',
        'created_at', 'updated_at', 'logo_preview', 'banner_preview'
    ]
    fieldsets = (
        ('Basic Info', {
            'fields': ('vendor', 'store_name', 'slug', 'tagline', 'description')
        }),
        ('Category (LOCKED after confirmation)', {
            'fields': ('main_category', 'main_category_locked', 'main_category_locked_at')
        }),
        ('Branding', {
            'fields': ('logo', 'logo_preview', 'banner', 'banner_preview', 'primary_color')
        }),
        ('Contact Information', {
            'fields': ('business_email', 'phone', 'whatsapp', 'address')
        }),
        ('Social Links', {'fields': ('instagram', 'facebook', 'twitter')}),
        ('Policies',     {'fields': ('shipping_policy', 'return_policy')}),
        ('Settings',     {'fields': ('is_published', 'allow_reviews')}),
        ('Sponsorship', {
            'fields': ('is_sponsored', 'sponsored_until'),
            'description': (
                'Sponsored stores are prioritised in the marketplace spotlight. '
                'Leave the expiry blank for an ongoing sponsorship.'
            ),
        }),
        ('Stats (Auto-calculated)', {
            'fields': ('total_products', 'total_orders', 'total_sales', 'average_rating')
        }),
        ('SEO', {
            'fields': ('meta_title', 'meta_description'),
            'classes': ('collapse',)
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )

    def vendor_name(self, obj):
        return obj.vendor.full_name
    vendor_name.short_description = 'Vendor'

    def category_locked_badge(self, obj):
        if obj.main_category_locked:
            return format_html('<span style="color:red;font-weight:bold;">🔒 Locked</span>')
        return format_html('<span style="color:green;">🔓 Unlocked</span>')
    category_locked_badge.short_description = 'Category Status'

    def sponsorship_status(self, obj):
        if not obj.is_sponsored:
            return format_html('<span style="color:#6b7280;">Not sponsored</span>')
        if obj.sponsored_until and obj.sponsored_until < timezone.now():
            return format_html('<strong style="color:#dc2626;">Expired</strong>')
        if obj.sponsored_until:
            return format_html(
                '<strong style="color:#15803d;">Sponsored</strong><br><small>Until {}</small>',
                timezone.localtime(obj.sponsored_until).strftime('%d %b %Y, %H:%M')
            )
        return format_html('<strong style="color:#15803d;">Sponsored</strong><br><small>No expiry</small>')
    sponsorship_status.short_description = 'Sponsorship'

    @admin.action(description='Activate sponsorship for selected stores')
    def activate_sponsorship(self, request, queryset):
        count = queryset.count()
        # An expired date would keep a newly activated store hidden from the
        # homepage, so clear it when the sponsorship is activated again.
        queryset.filter(sponsored_until__lt=timezone.now()).update(sponsored_until=None)
        queryset.update(is_sponsored=True)
        self.message_user(
            request,
            f'Sponsorship activated for {count} store(s). Set an expiry date from each store page if needed.',
            messages.SUCCESS,
        )

    @admin.action(description='Deactivate sponsorship for selected stores')
    def deactivate_sponsorship(self, request, queryset):
        count = queryset.update(is_sponsored=False, sponsored_until=None)
        self.message_user(request, f'Sponsorship deactivated for {count} store(s).', messages.SUCCESS)

    def logo_preview(self, obj):
        if obj.logo:
            return format_html('<img src="{}" width="100" height="100" style="object-fit:cover;" />', obj.logo.url)
        return '-'
    logo_preview.short_description = 'Logo Preview'

    def banner_preview(self, obj):
        if obj.banner:
            return format_html('<img src="{}" style="max-width:300px;max-height:100px;object-fit:contain;" />', obj.banner.url)
        return '-'
    banner_preview.short_description = 'Banner Preview'


@admin.register(CategoryChangeRequest)
class CategoryChangeRequestAdmin(admin.ModelAdmin):
    list_display = [
        'request_id_short', 'store_name', 'vendor_name',
        'current_category', 'requested_category',
        'status_badge', 'created_at', 'days_since_last_change'
    ]
    list_filter   = ['status', 'created_at', 'reviewed_at']
    search_fields = ['store__store_name', 'store__vendor__full_name', 'reason']
    readonly_fields = [
        'store', 'current_category', 'requested_category',
        'created_at', 'updated_at', 'reviewed_at'
    ]
    fieldsets = (
        ('📋 Request Details', {
            'fields': ('store', 'current_category', 'requested_category', 'reason')
        }),
        ('👤 Vendor Context', {
            'fields': (),
            'description': format_html(
                '<div style="background:#dbeafe;padding:12px;border-radius:6px;border-left:4px solid #3b82f6;">'
                '<strong>Review vendor history and store performance before approving</strong></div>'
            )
        }),
        ('✅ Admin Response', {
            'fields': ('status', 'admin_comment', 'reviewed_by', 'reviewed_at')
        }),
        ('🕐 Timestamps', {'fields': ('created_at', 'updated_at')}),
    )
    actions = ['approve_requests', 'reject_requests', 'require_more_info']

    def request_id_short(self, obj):
        return f'CR-{obj.id}'
    request_id_short.short_description = 'Request ID'

    def store_name(self, obj):
        return obj.store.store_name
    store_name.short_description = 'Store'

    def vendor_name(self, obj):
        return obj.store.vendor.full_name
    vendor_name.short_description = 'Vendor'

    def status_badge(self, obj):
        colors = {'pending': '#f59e0b', 'approved': '#10b981', 'rejected': '#ef4444'}
        color  = colors.get(obj.status, '#6b7280')
        return format_html(
            '<span style="background-color:{};color:white;padding:4px 12px;'
            'border-radius:6px;font-weight:600;font-size:11px;">{}</span>',
            color, obj.get_status_display()
        )
    status_badge.short_description = 'Status'

    def days_since_last_change(self, obj):
        if obj.store.main_category_last_changed_at:
            days = (timezone.now() - obj.store.main_category_last_changed_at).days
            return format_html(
                '<span style="color:{};">{} days ago</span>',
                '#10b981' if days >= 365 else '#ef4444', days
            )
        return format_html('<span style="color:#6b7280;">Never changed</span>')
    days_since_last_change.short_description = 'Last Change'

    def approve_requests(self, request, queryset):
        from .views import approve_category_change
        count = 0
        errors = []
        for cr in queryset.filter(status='pending'):
            success, message = approve_category_change(cr.id, request.user)
            if success:
                count += 1
                logger.info(
                    f"✅ CATEGORY CHANGE APPROVED: {cr.store.store_name} "
                    f"({cr.current_category.name} → {cr.requested_category.name}) "
                    f"by {request.user.email}"
                )
            else:
                errors.append(f'{cr.store.store_name}: {message}')
        if errors:
            self.message_user(request, ' | '.join(errors), messages.ERROR)
        if count:
            self.message_user(request, f'✅ Approved {count} category change request(s)', messages.SUCCESS)
    approve_requests.short_description = '✅ Approve selected requests'

    def reject_requests(self, request, queryset):
        from .views import reject_category_change
        count = 0
        for cr in queryset.filter(status='pending'):
            success, _ = reject_category_change(cr.id, request.user, reason='Request rejected by admin')
            if success:
                count += 1
                logger.info(f"❌ CATEGORY CHANGE REJECTED: {cr.store.store_name} by {request.user.email}")
        if count:
            self.message_user(request, f'❌ Rejected {count} category change request(s)', messages.WARNING)
    reject_requests.short_description = '❌ Reject selected requests'

    def require_more_info(self, request, queryset):
        count = 0
        for cr in queryset.filter(status='pending'):
            cr.admin_comment = (
                f"[{timezone.now().strftime('%Y-%m-%d')}] Admin {request.user.email}: "
                f"More information required. Please provide additional details."
            )
            cr.save()
            count += 1
        self.message_user(request, f'📧 Requested more info for {count} request(s)', messages.INFO)
    require_more_info.short_description = '📧 Request more information'


# ==========================================
# PRODUCT ADMIN
# ==========================================

@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = [
        'title', 'vendor_name', 'subcategory', 'price',
        'stock_badge', 'display_attributes', 'status', 'sales_count',
        'sponsorship_status', 'created_at'
    ]
    list_filter   = [
        'status', 'track_inventory', 'is_sponsored',
        'subcategory__main_category', 'subcategory', 'created_at', 'sponsored_until'
    ]
    search_fields = ['title', 'vendor__full_name', 'sku']
    actions = ['activate_sponsorship', 'deactivate_sponsorship']
    readonly_fields = [
        'slug', 'vendor', 'store', 'views_count', 'sales_count',
        'created_at', 'updated_at', 'published_at',
        'main_category', 'formatted_attributes', 'attributes_preview'
    ]
    fieldsets = (
        ('Basic Info', {
            'fields': ('vendor', 'store', 'title', 'slug', 'description')
        }),
        ('Category',   {'fields': ('subcategory', 'main_category')}),
        ('Pricing & Inventory', {
            'fields': (
                'price', 'compare_at_price', 'stock_quantity',
                'low_stock_threshold', 'track_inventory', 'sku'
            )
        }),
        ('Status',     {'fields': ('status', 'is_featured')}),
        ('Sponsorship', {
            'fields': ('is_sponsored', 'sponsored_until', 'sponsored_priority'),
            'description': (
                'Sponsored products are prioritised in the marketplace spotlight. '
                'Leave the expiry blank for an ongoing sponsorship. '
                'Higher priority shows first among sponsored products.'
            ),
        }),
        ('Stats',      {'fields': ('views_count', 'sales_count')}),
        ('SEO', {
            'fields': ('meta_title', 'meta_description'),
            'classes': ('collapse',)
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at', 'published_at')
        }),
    )
    inlines = [ProductImageInline]

    def vendor_name(self, obj):
        return obj.vendor.full_name
    vendor_name.short_description = 'Vendor'

    def main_category(self, obj):
        return obj.subcategory.main_category.name if obj.subcategory else '-'
    main_category.short_description = 'Main Category'

    def stock_badge(self, obj):
        if not obj.track_inventory:
            return format_html('<span style="color:gray;">∞ Not Tracked</span>')
        if obj.stock_quantity == 0:
            return format_html('<span style="color:red;font-weight:bold;">❌ OUT</span>')
        elif obj.is_low_stock:
            return format_html('<span style="color:orange;font-weight:bold;">⚠️ LOW ({})</span>', obj.stock_quantity)
        return format_html('<span style="color:green;">✓ {} units</span>', obj.stock_quantity)
    stock_badge.short_description = 'Stock'

    def formatted_attributes(self, obj):
        if not obj.attributes:
            return '— No attributes —'
        return '\n'.join(f'{k}: {v}' for k, v in obj.attributes.items())
    formatted_attributes.short_description = 'Product Specifications'

    def attributes_preview(self, obj):
        if not obj.attributes:
            return '-'
        rows = []
        for attr_id, value in obj.attributes.items():
            attr = SubCategoryAttribute.objects.filter(id=attr_id).first()
            if attr:
                rows.append(f'{attr.name}: {value}')
        return format_html('<br>'.join(rows))
    attributes_preview.short_description = 'Product Specifications'

    @admin.display(description='Specifications')
    def display_attributes(self, obj):
        if not obj.attributes:
            return '-'
        lines = []
        for attr_id, value in obj.attributes.items():
            try:
                lookup_id = int(attr_id) if isinstance(attr_id, str) and attr_id.isdigit() else attr_id
                attr = SubCategoryAttribute.objects.get(id=lookup_id)
                lines.append(f'{attr.name}: {value}')
            except SubCategoryAttribute.DoesNotExist:
                continue
        return ', '.join(lines)

    # ─── SPONSORSHIP STATUS DISPLAY METHOD ───
    def sponsorship_status(self, obj):
        if not obj.is_sponsored:
            return format_html('<span style="color:#6b7280;">Not sponsored</span>')
        if obj.sponsored_until and obj.sponsored_until < timezone.now():
            return format_html('<strong style="color:#dc2626;">Expired</strong>')
        if obj.sponsored_until:
            return format_html(
                '<strong style="color:#15803d;">Sponsored</strong><br><small>Until {}</small>',
                timezone.localtime(obj.sponsored_until).strftime('%d %b %Y, %H:%M')
            )
        return format_html('<strong style="color:#15803d;">Sponsored</strong><br><small>No expiry</small>')
    sponsorship_status.short_description = 'Sponsorship'

    # ─── ACTIVATE SPONSORSHIP ACTION ───
    @admin.action(description='Activate sponsorship for selected products')
    def activate_sponsorship(self, request, queryset):
        count = queryset.count()
        queryset.filter(sponsored_until__lt=timezone.now()).update(sponsored_until=None)
        queryset.update(is_sponsored=True)
        self.message_user(
            request,
            f'Sponsorship activated for {count} product(s). Set an expiry date from each product page if needed.',
            messages.SUCCESS,
        )

    # ─── DEACTIVATE SPONSORSHIP ACTION ───
    @admin.action(description='Deactivate sponsorship for selected products')
    def deactivate_sponsorship(self, request, queryset):
        count = queryset.update(is_sponsored=False, sponsored_until=None)
        self.message_user(request, f'Sponsorship deactivated for {count} product(s).', messages.SUCCESS)


# ==========================================
# WALLET & TRANSACTIONS ADMIN
# ==========================================

@admin.register(Wallet)
class WalletAdmin(admin.ModelAdmin):
    list_display = [
        'vendor_name', 'balance', 'pending_balance',
        'total_earned', 'total_withdrawn', 'commission_rate', 'is_verified'
    ]
    list_filter   = ['is_verified', 'auto_payout']
    search_fields = ['vendor__full_name', 'account_number', 'bank_name']
    readonly_fields = [
        'vendor', 'balance', 'pending_balance', 'total_earned',
        'total_withdrawn', 'created_at', 'updated_at', 'verified_at'
    ]
    fieldsets = (
        ('Vendor', {'fields': ('vendor',)}),
        ('Bank Account (Auto-filled from BVN)', {
            'fields': ('account_number', 'bank_name', 'bank_code', 'account_holder_name')
        }),
        ('Balances (Read-only)', {
            'fields': ('balance', 'pending_balance', 'total_earned', 'total_withdrawn')
        }),
        ('Settings',     {'fields': ('commission_rate', 'auto_payout', 'payout_threshold')}),
        ('Verification', {'fields': ('is_verified', 'verified_at')}),
        ('Timestamps',   {'fields': ('created_at', 'updated_at')}),
    )

    def vendor_name(self, obj):
        return obj.vendor.full_name
    vendor_name.short_description = 'Vendor'


@admin.register(Transaction)
class TransactionAdmin(admin.ModelAdmin):
    list_display  = [
        'transaction_id_short', 'wallet_vendor', 'transaction_type',
        'amount', 'status', 'created_at'
    ]
    list_filter   = ['transaction_type', 'status', 'created_at']
    search_fields = ['transaction_id', 'wallet__vendor__full_name', 'reference']
    readonly_fields = [
        'transaction_id', 'wallet', 'transaction_type', 'amount',
        'balance_before', 'balance_after', 'created_at', 'completed_at'
    ]

    def transaction_id_short(self, obj):
        return str(obj.transaction_id)[:8]
    transaction_id_short.short_description = 'Transaction ID'

    def wallet_vendor(self, obj):
        return obj.wallet.vendor.full_name
    wallet_vendor.short_description = 'Vendor'

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return request.user.is_superuser


# ==========================================
# ORDERS & REFUNDS ADMIN
# ==========================================

@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display  = [
        'order_id_short', 'vendor_name', 'customer_name',
        'status', 'total_amount', 'vendor_amount', 'created_at'
    ]
    list_filter   = ['status', 'payment_status', 'created_at']
    search_fields = ['order_id', 'vendor__full_name', 'customer__email', 'payment_reference']
    readonly_fields = [
        'order_id', 'vendor', 'customer', 'total_amount',
        'commission_amount', 'vendor_amount', 'created_at',
        'updated_at', 'paid_at', 'delivered_at'
    ]
    fieldsets = (
        ('Order Details', {'fields': ('order_id', 'vendor', 'customer', 'status')}),
        ('Payment', {
            'fields': (
                'total_amount', 'commission_amount', 'vendor_amount',
                'payment_reference', 'payment_status', 'paid_at'
            )
        }),
        ('Shipping',   {'fields': ('shipping_address', 'shipping_phone', 'tracking_number')}),
        ('Notes',      {'fields': ('customer_note', 'vendor_note')}),
        ('Timestamps', {'fields': ('created_at', 'updated_at', 'delivered_at')}),
    )
    inlines = [OrderItemInline]

    def order_id_short(self, obj):
        return str(obj.order_id)[:8]
    order_id_short.short_description = 'Order ID'

    def vendor_name(self, obj):
        return obj.vendor.full_name
    vendor_name.short_description = 'Vendor'

    def customer_name(self, obj):
        return obj.customer.get_full_name() or obj.customer.email
    customer_name.short_description = 'Customer'


@admin.register(RefundRequest)
class RefundRequestAdmin(admin.ModelAdmin):
    list_display  = [
        'refund_id_short', 'order', 'vendor_name',
        'reason', 'amount', 'status', 'created_at'
    ]
    list_filter   = ['status', 'reason', 'created_at']
    search_fields = ['refund_id', 'order__order_id', 'vendor__full_name']
    readonly_fields = [
        'refund_id', 'order', 'order_item', 'vendor',
        'amount', 'created_at', 'updated_at', 'processed_at'
    ]
    fieldsets = (
        ('Refund Details', {
            'fields': ('refund_id', 'order', 'order_item', 'vendor', 'amount')
        }),
        ('Request',       {'fields': ('reason', 'description', 'status')}),
        ('Admin Response', {
            'fields': ('admin_comment', 'processed_by', 'processed_at')
        }),
        ('Timestamps', {'fields': ('created_at', 'updated_at')}),
    )
    actions = ['approve_refunds', 'reject_refunds']

    def refund_id_short(self, obj):
        return str(obj.refund_id)[:8]
    refund_id_short.short_description = 'Refund ID'

    def vendor_name(self, obj):
        return obj.vendor.full_name
    vendor_name.short_description = 'Vendor'

    def approve_refunds(self, request, queryset):
        count = queryset.filter(status='pending').update(
            status='approved', processed_by=request.user, processed_at=timezone.now()
        )
        self.message_user(request, f'✓ Approved {count} refund request(s)', messages.SUCCESS)
    approve_refunds.short_description = 'Approve selected refunds'

    def reject_refunds(self, request, queryset):
        count = queryset.filter(status='pending').update(
            status='rejected', processed_by=request.user, processed_at=timezone.now()
        )
        self.message_user(request, f'✗ Rejected {count} refund request(s)', messages.WARNING)
    reject_refunds.short_description = 'Reject selected refunds'


# ==========================================
# NOTIFICATIONS ADMIN
# ==========================================

@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display  = ['title', 'vendor_name', 'notification_type', 'is_read', 'created_at']
    list_filter   = ['notification_type', 'is_read', 'created_at']
    search_fields = ['title', 'message', 'vendor__full_name']
    readonly_fields = ['vendor', 'created_at', 'read_at']

    def vendor_name(self, obj):
        return obj.vendor.full_name
    vendor_name.short_description = 'Vendor'
