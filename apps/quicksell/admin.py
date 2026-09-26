"""
Quick Sell Admin

Registers QuickSell, QuickSellImage, and QuickSellReport for admin management.
"""

from django.contrib import admin
from django.utils import timezone
from django.utils.html import format_html
from .models import QuickSell, QuickSellImage, QuickSellReport


class QuickSellImageInline(admin.TabularInline):
    model = QuickSellImage
    extra = 0
    readonly_fields = ['created_at']


@admin.register(QuickSell)
class QuickSellAdmin(admin.ModelAdmin):
    list_display = [
        'title', 'seller_email', 'subcategory', 'price',
        'status_badge', 'days_remaining_display', 'views_count', 'created_at'
    ]
    list_filter = ['subcategory__main_category', 'subcategory', 'created_at', 'expires_at']
    search_fields = ['title', 'description', 'user__email']
    readonly_fields = [
        'user', 'slug', 'views_count', 'created_at', 'updated_at', 'expires_at'
    ]
    inlines = [QuickSellImageInline]

    fieldsets = (
        ('Seller', {
            'fields': ('user',)
        }),
        ('Basic Info', {
            'fields': ('title', 'slug', 'subcategory', 'description')
        }),
        ('Media', {
            'fields': ('video',)
        }),
        ('Pricing', {
            'fields': ('price', 'compare_at_price')
        }),
        ('Specifications', {
            'fields': ('attributes',)
        }),
        ('Contact', {
            'fields': ('whatsapp', 'phone')
        }),
        ('Stats', {
            'fields': ('views_count',)
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at', 'expires_at')
        }),
    )

    def seller_email(self, obj):
        if obj.user:
            return obj.user.email
        return format_html('<span style="color:#9ca3af;">Deleted user</span>')
    seller_email.short_description = 'Seller'

    def status_badge(self, obj):
        if obj.expires_at > timezone.now():
            return format_html(
                '<span style="background:#d1fae5;color:#065f46;'
                'padding:3px 10px;border-radius:12px;font-size:11px;'
                'font-weight:600;">Active</span>'
            )
        return format_html(
            '<span style="background:#f3f4f6;color:#6b7280;'
            'padding:3px 10px;border-radius:12px;font-size:11px;'
            'font-weight:600;">Expired</span>'
        )
    status_badge.short_description = 'Status'

    def days_remaining_display(self, obj):
        if obj.expires_at > timezone.now():
            days = (obj.expires_at - timezone.now()).days
            return f"{days}d"
        return "—"
    days_remaining_display.short_description = 'Days Left'


class QuickSellReportStatusFilter(admin.SimpleListFilter):
    title = 'report status'
    parameter_name = 'report_status'

    def lookups(self, request, model_admin):
        return QuickSellReport.STATUS_CHOICES

    def queryset(self, request, queryset):
        if self.value():
            return queryset.filter(status=self.value())
        return queryset


@admin.register(QuickSellReport)
class QuickSellReportAdmin(admin.ModelAdmin):
    list_display = [
        'id', 'listing_title', 'reporter_display', 'reason_badge',
        'status_badge', 'created_at'
    ]
    list_filter = [QuickSellReportStatusFilter, 'reason', 'created_at']
    search_fields = ['quicksell__title', 'reporter__email', 'details']
    readonly_fields = [
        'reporter', 'reporter_ip', 'quicksell', 'reason', 'details',
        'created_at', 'reviewed_by', 'reviewed_at'
    ]
    actions = ['dismiss_reports', 'actioned_remove_listing']

    fieldsets = (
        ('Report Details', {
            'fields': ('quicksell', 'reporter', 'reporter_ip', 'reason', 'details', 'created_at')
        }),
        ('Moderation', {
            'fields': ('status', 'reviewed_by', 'reviewed_at'),
        }),
    )

    def listing_title(self, obj):
        return obj.quicksell.title[:50]
    listing_title.short_description = 'Listing'

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
            'pending': ('#f59e0b', '#fef3c7', 'Pending'),
            'reviewed': ('#3b82f6', '#dbeafe', 'Under Review'),
            'actioned': ('#10b981', '#d1fae5', 'Actioned'),
            'dismissed': ('#6b7280', '#f3f4f6', 'Dismissed'),
        }
        color, bg, label = styles.get(obj.status, ('#6b7280', '#f3f4f6', obj.status))
        return format_html(
            '<span style="background:{};color:{};padding:3px 10px;'
            'border-radius:12px;font-size:11px;font-weight:600;">{}</span>',
            bg, color, label
        )
    status_badge.short_description = 'Status'

    def dismiss_reports(self, request, queryset):
        count = queryset.filter(status='pending').update(
            status='dismissed',
            reviewed_by=request.user,
            reviewed_at=timezone.now()
        )
        self.message_user(request, f'Dismissed {count} report(s).')
    dismiss_reports.short_description = 'Dismiss selected reports'

    def actioned_remove_listing(self, request, queryset):
        count = 0
        for report in queryset.filter(status='pending'):
            listing = report.quicksell
            listing.delete()
            report.status = 'actioned'
            report.reviewed_by = request.user
            report.reviewed_at = timezone.now()
            report.save()
            count += 1
        self.message_user(request, f'Removed {count} listing(s) and actioned report(s).')
    actioned_remove_listing.short_description = 'Action: remove listing & action report'
