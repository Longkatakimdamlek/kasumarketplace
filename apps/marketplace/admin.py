from django.utils.html import format_html
from django.utils import timezone
from django.contrib import admin, messages
from apps.vendors.models import Product, ProductImage, Store
from .models import Promotion
from .models import (
    Wishlist, Review,
    ProductReport,
)


@admin.register(Promotion)
class PromotionAdmin(admin.ModelAdmin):
    list_display = ['title', 'slide_type', 'is_active', 'sort_order', 'start_date', 'end_date']
    list_filter = ['slide_type', 'is_active', 'start_date', 'end_date']
    list_editable = ['is_active', 'sort_order']

    def get_fieldsets(self, request, obj=None):
        if obj is None:
            return (
                ('Content', {
                    'fields': ('title', 'subtitle', 'image', 'background_image', 'link_url')
                }),
                ('Display Settings', {
                    'fields': ('slide_type', 'hero_slot', 'is_active', 'sort_order')
                }),
                ('Campaign Window', {
                    'fields': ('start_date', 'end_date', 'frequency_minutes'),
                    'classes': ('collapse',),
                }),
            )

        if obj.slide_type == 'vendor_promo':
            return (
                ('Content', {
                    'fields': ('title', 'subtitle', 'image', 'link_url')
                }),
                ('Display Settings', {
                    'fields': ('slide_type', 'is_active', 'sort_order')
                }),
            )

        if obj.slide_type == 'hero_brand':
            return (
                ('Content', {
                    'fields': ('title', 'subtitle', 'background_image', 'link_url')
                }),
                ('Hero Slot', {
                    'fields': ('hero_slot',)
                }),
                ('Display Settings', {
                    'fields': ('slide_type', 'is_active', 'sort_order')
                }),
                ('Campaign Window', {
                    'fields': ('start_date', 'end_date'),
                }),
            )

        if obj.slide_type == 'event_popup':
            return (
                ('Content', {
                    'fields': ('title', 'subtitle', 'image', 'background_image', 'link_url')
                }),
                ('Display Settings', {
                    'fields': ('slide_type', 'is_active', 'sort_order')
                }),
                ('Event Popup Settings', {
                    'fields': ('start_date', 'end_date', 'frequency_minutes'),
                    'classes': ('collapse',),
                }),
            )

        return (
            ('Content', {
                'fields': ('title', 'subtitle', 'image', 'background_image', 'link_url')
            }),
            ('Display Settings', {
                'fields': ('slide_type', 'hero_slot', 'is_active', 'sort_order')
            }),
            ('Campaign Window', {
                'fields': ('start_date', 'end_date', 'frequency_minutes'),
                'classes': ('collapse',),
            }),
        )


@admin.register(Wishlist)
class WishlistAdmin(admin.ModelAdmin):
    list_display = ['user', 'session_key_display', 'product', 'quantity', 'created_at']
    search_fields = ['user__email', 'session_key', 'product__title']
    readonly_fields = ['user', 'session_key', 'product', 'quantity', 'created_at']

    def session_key_display(self, obj):
        if obj.user:
            return '-'
        return f"{obj.session_key[:8]}..." if obj.session_key else '-'
    session_key_display.short_description = "Guest Session"


@admin.register(Review)
class ReviewAdmin(admin.ModelAdmin):
    list_display = ['product', 'user', 'rating', 'created_at']
    list_filter = ['rating', 'created_at']
    search_fields = ['product__title', 'user__email', 'comment']
    readonly_fields = ['user', 'product', 'rating', 'comment', 'created_at']


# ==========================================
# PRODUCT REPORTS
# ==========================================

@admin.register(ProductReport)
class ProductReportAdmin(admin.ModelAdmin):
    list_display = ['id', 'product_title', 'reporter_display', 'reason_badge', 'status_badge', 'created_at']
    list_filter = ['status', 'reason', 'created_at']
    search_fields = ['product__title', 'reporter__email', 'details']
    readonly_fields = ['reporter', 'reporter_ip', 'product', 'reason', 'details', 'created_at', 'reviewed_by', 'reviewed_at']
    actions = ['dismiss_reports', 'actioned_remove_product', 'warn_vendor', 'suspend_vendor_from_report']

    fieldsets = (
        ('Report Details', {
            'fields': ('product', 'reporter', 'reporter_ip', 'reason', 'details', 'created_at')
        }),
        ('Moderation', {
            'fields': ('status', 'reviewed_by', 'reviewed_at'),
        }),
    )

    def product_title(self, obj):
        return obj.product.title[:50]
    product_title.short_description = 'Product'

    def reporter_display(self, obj):
        if obj.reporter:
            return obj.reporter.email
        return format_html('<span style="color:#9ca3af;">Anonymous</span>')
    reporter_display.short_description = 'Reporter'

    def reason_badge(self, obj):
        colors = {
            'counterfeit': '#dc2626',
            'prohibited': '#ea580c',
            'misleading': '#d97706',
            'other': '#6b7280',
        }
        color = colors.get(obj.reason, '#6b7280')
        return format_html(
            '<span style="color:{};font-weight:600;font-size:12px;">{}</span>',
            color, obj.get_reason_display()
        )
    reason_badge.short_description = 'Reason'

    def status_badge(self, obj):
        styles = {
            'pending': ('#f59e0b', '#fef3c7', '⏳ Pending'),
            'reviewed': ('#3b82f6', '#dbeafe', '🔍 Under Review'),
            'actioned': ('#10b981', '#d1fae5', '✓ Actioned'),
            'dismissed': ('#6b7280', '#f3f4f6', '— Dismissed'),
        }
        color, bg, label = styles.get(obj.status, ('#6b7280', '#f3f4f6', obj.status))
        return format_html(
            '<span style="background:{};color:{};padding:3px 10px;border-radius:12px;font-size:11px;font-weight:600;">{}</span>',
            bg, color, label
        )
    status_badge.short_description = 'Status'

    def dismiss_reports(self, request, queryset):
        from django.utils import timezone as tz
        count = 0
        for report in queryset.filter(status='pending'):
            report.status = 'dismissed'
            report.reviewed_by = request.user
            report.reviewed_at = tz.now()
            report.save(update_fields=['status', 'reviewed_by', 'reviewed_at'])
            count += 1
        self.message_user(request, f'Dismissed {count} report(s).', messages.INFO)
    dismiss_reports.short_description = 'Dismiss selected reports'

    def actioned_remove_product(self, request, queryset):
        from django.utils import timezone as tz
        count = 0
        for report in queryset.filter(status='pending'):
            product = report.product
            product.status = 'removed'
            product.save(update_fields=['status'])
            report.status = 'actioned'
            report.reviewed_by = request.user
            report.reviewed_at = tz.now()
            report.save(update_fields=['status', 'reviewed_by', 'reviewed_at'])
            count += 1
        self.message_user(request, f'Actioned {count} report(s) — product(s) removed.', messages.WARNING)
    actioned_remove_product.short_description = 'Remove product & action report'

    def warn_vendor(self, request, queryset):
        from django.utils import timezone as tz
        from apps.marketplace.services.email_service import _send
        warned_vendors = set()
        count = 0
        for report in queryset.filter(status='pending'):
            vendor = report.product.store.vendor
            if vendor.pk in warned_vendors:
                report.status = 'actioned'
                report.reviewed_by = request.user
                report.reviewed_at = tz.now()
                report.save(update_fields=['status', 'reviewed_by', 'reviewed_at'])
                count += 1
                continue
            warned_vendors.add(vendor.pk)
            _send(
                subject='Listing Warning — KasuMarketplace',
                message=(
                    f'Hi {vendor.full_name},\n\n'
                    f'Your product "{report.product.title}" has been reported for: {report.get_reason_display()}.\n'
                    f'Please review and update your listing to ensure it complies with our Community Guidelines.\n'
                    f'Failure to address repeated reports may result in product removal or account suspension.\n\n'
                    f'KasuMarketplace Support'
                ),
                recipient_list=[vendor.user.email],
            )
            report.status = 'actioned'
            report.reviewed_by = request.user
            report.reviewed_at = tz.now()
            report.save(update_fields=['status', 'reviewed_by', 'reviewed_at'])
            count += 1
        self.message_user(request, f'Warned {len(warned_vendors)} vendor(s) across {count} report(s).', messages.WARNING)
    warn_vendor.short_description = 'Warn vendor & action report'

    def suspend_vendor_from_report(self, request, queryset):
        from django.utils import timezone as tz
        suspended_vendors = set()
        count = 0
        for report in queryset.filter(status='pending'):
            vendor = report.product.store.vendor
            if vendor.pk in suspended_vendors:
                report.status = 'actioned'
                report.reviewed_by = request.user
                report.reviewed_at = tz.now()
                report.save(update_fields=['status', 'reviewed_by', 'reviewed_at'])
                count += 1
                continue
            suspended_vendors.add(vendor.pk)
            vendor.verification_status = 'suspended'
            vendor.save(update_fields=['verification_status'])
            report.status = 'actioned'
            report.reviewed_by = request.user
            report.reviewed_at = tz.now()
            report.save(update_fields=['status', 'reviewed_by', 'reviewed_at'])
            count += 1
        self.message_user(request, f'⏸ Suspended {len(suspended_vendors)} vendor(s) across {count} report(s).', messages.WARNING)
    suspend_vendor_from_report.short_description = 'Suspend vendor & action report'
