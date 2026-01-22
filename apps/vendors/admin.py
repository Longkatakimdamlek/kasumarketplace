"""
Vendor App Django Admin
Provides admin interface for managing vendors, verification, stores, products, etc.
"""

from django.contrib import admin
from django.utils.html import format_html
from django.urls import reverse
from django.utils import timezone
from django.db.models import Count, Sum, Q
from django.contrib import messages
from .models import (
    VendorProfile, VerificationAttempt, MainCategory, SubCategory,
    Store, CategoryChangeRequest, Product, ProductImage,
    Wallet, Transaction, Order, OrderItem, RefundRequest, Notification,
    SubCategoryAttribute
)
import logging

logger = logging.getLogger(__name__)

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
# VENDOR PROFILE ADMIN
# ==========================================

@admin.register(VendorProfile)
class VendorProfileAdmin(admin.ModelAdmin):
    list_display = [
        'vendor_id_short', 'full_name', 'user_email',
        'verification_badge', 'identity_badge', 'bank_badge',
        'student_badge', 'risk_flags_badge',
        'can_sell_badge', 'created_at'
    ]
    
    list_filter = [
        'verification_status', 'identity_status', 'bank_status',
        'student_status', 'created_at',
        'has_name_mismatch',
        'has_duplicate_nin',
        'has_duplicate_bvn',
        'is_underage',
    ]
    
    search_fields = [
        'full_name', 'user__email', 'phone', 'matric_number',
        'vendor_id', 'nin_number', 'bvn_number'
    ]
    
    readonly_fields = [
        'vendor_id', 'user', 'created_at', 'updated_at',
        'nin_verified_at', 'bvn_verified_at', 'student_verified_at',
        'approved_at', 'completion_percentage', 'current_step',
        'photo_preview', 'student_id_preview', 'selfie_preview',
        'registration_ip', 'nin_verification_ip', 'bvn_verification_ip',
        'risk_score', 'risk_flags_summary', 'calculated_age',
        'duplicate_nin_vendor_id', 'duplicate_bvn_vendor_id',
        'name_mismatch_details', 'bvn_full_name',
    ]
    
    fieldsets = (
        ('👤 Basic Information', {
            'fields': (
                'vendor_id', 'user', 'full_name', 'phone',
                'gender', 'dob', 'calculated_age'
            )
        }),
        
        ('📍 Address', {
            'fields': ('address', 'state', 'lga')
        }),
        
        ('🆔 Identity Verification (NIN)', {
            'fields': (
                'identity_status', 'nin_number', 'photo_from_nin',
                'photo_preview', 'nin_verified_at', 'nin_verification_ip'
            ),
            'description': '🔒 Auto-filled from Dojah NIN API - Read-Only for Vendor'
        }),
        
        ('🏦 Banking Verification (BVN)', {
            'fields': (
                'bank_status', 'bvn_number', 'bvn_full_name',
                'bvn_verified_at', 'bvn_verification_ip'
            ),
            'description': '🔒 Auto-filled from Dojah BVN API - Read-Only for Vendor'
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
            'fields': (
                'risk_flags_summary',
                'name_mismatch_details',
                'duplicate_nin_vendor_id',
                'duplicate_bvn_vendor_id'
            ),
            'classes': ('collapse',),
            'description': '⚠️ Automated security alerts - Review these before approving vendor'
        }),
        
        ('🔒 Security & Tracking', {
            'fields': (
                'registration_ip',
            ),
            'classes': ('collapse',),
            'description': 'IP addresses used during verification process'
        }),
        
        ('📝 Admin Internal Notes', {
            'fields': ('admin_internal_notes',),
            'description': '⚠️ PRIVATE NOTES - NOT visible to vendor. Use for internal tracking.'
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
        'recalculate_risk_scores',
        'flag_for_review'
    ]
    
    # Display Methods
    def vendor_id_short(self, obj):
        return str(obj.vendor_id)[:8]
    vendor_id_short.short_description = 'Vendor ID'
    
    def user_email(self, obj):
        return obj.user.email
    user_email.short_description = 'Email'
    
    def verification_badge(self, obj):
        colors = {
            'approved': '#10b981',
            'rejected': '#ef4444',
            'pending': '#f59e0b',
            'nin_verified': '#3b82f6',
            'bvn_verified': '#3b82f6',
            'student_verified': '#3b82f6',
            'suspended': '#6b7280',
        }
        color = colors.get(obj.verification_status, '#6b7280')
        return format_html(
            '<span style="background-color: {}; color: white; padding: 4px 12px; border-radius: 6px; font-weight: 600; font-size: 11px;">{}</span>',
            color, obj.get_verification_status_display()
        )
    verification_badge.short_description = 'Status'
    
    def identity_badge(self, obj):
        if obj.identity_status == 'nin_verified':
            return format_html('<span style="color: #10b981; font-weight: 600;">✓ NIN</span>')
        return format_html('<span style="color: #f59e0b;">⏳ NIN</span>')
    identity_badge.short_description = 'Identity'
    
    def bank_badge(self, obj):
        if obj.bank_status == 'bvn_verified':
            return format_html('<span style="color: #10b981; font-weight: 600;">✓ BVN</span>')
        return format_html('<span style="color: #f59e0b;">⏳ BVN</span>')
    bank_badge.short_description = 'Banking'
    
    def student_badge(self, obj):
        if obj.student_status == 'verified':
            return format_html('<span style="color: #10b981; font-weight: 600;">✓ Student</span>')
        elif obj.student_status == 'not_applicable':
            return format_html('<span style="color: #6b7280;">N/A</span>')
        return format_html('<span style="color: #f59e0b;">⏳ Student</span>')
    student_badge.short_description = 'Student'
    
    def can_sell_badge(self, obj):
        if obj.can_sell:
            return format_html('<span style="color: #10b981; font-weight: 700;">✓ Can Sell</span>')
        return format_html('<span style="color: #ef4444; font-weight: 600;">✗ Cannot Sell</span>')
    can_sell_badge.short_description = 'Can Sell?'
    
    def photo_preview(self, obj):
        if obj.photo_from_nin:
            return format_html(
                '<img src="{}" width="100" height="100" style="object-fit: cover; border-radius: 8px; border: 2px solid #e5e7eb;" />',
                obj.photo_from_nin.url
            )
        return '—'
    photo_preview.short_description = 'NIN Photo'
    
    def student_id_preview(self, obj):
        if obj.student_id_image:
            return format_html(
                '<img src="{}" width="150" style="max-height: 100px; object-fit: contain; border-radius: 8px; border: 2px solid #e5e7eb;" />',
                obj.student_id_image.url
            )
        return '—'
    student_id_preview.short_description = 'Student ID'
    
    def selfie_preview(self, obj):
        if obj.selfie:
            return format_html(
                '<img src="{}" width="100" height="100" style="object-fit: cover; border-radius: 8px; border: 2px solid #e5e7eb;" />',
                obj.selfie.url
            )
        return '—'
    selfie_preview.short_description = 'Selfie'
    
    def risk_flags_badge(self, obj):
        """Risk flags badge for list view"""
        flags = []
        if obj.has_name_mismatch:
            flags.append('⚠️ Name')
        if obj.has_duplicate_nin:
            flags.append('⚠️ NIN')
        if obj.has_duplicate_bvn:
            flags.append('⚠️ BVN')
        if obj.is_underage:
            flags.append('🚫 Age')
        
        if flags:
            flag_text = ' '.join(flags)
            color = '#ef4444' if obj.risk_score > 50 else '#f59e0b'
            return format_html(
                '<span style="color: {}; font-weight: 700; font-size: 12px;">{}</span>',
                color, flag_text
            )
        return format_html('<span style="color: #10b981; font-weight: 600;">✓ Clean</span>')
    
    risk_flags_badge.short_description = 'Risk Flags'
    
    def risk_flags_summary(self, obj):
        """Detailed risk assessment for detail view"""
        flags = []
        
        if obj.has_name_mismatch:
            flags.append(f'''
                <div style="background: #fee2e2; border-left: 4px solid #dc2626; padding: 12px; margin: 8px 0; border-radius: 6px;">
                    <strong style="color: #991b1b;">❌ NAME MISMATCH</strong><br>
                    <span style="color: #7f1d1d; font-size: 13px;">
                        {obj.name_mismatch_details or 'NIN name does not match BVN name'}
                    </span>
                </div>
            ''')
        
        if obj.has_duplicate_nin:
            flags.append(f'''
                <div style="background: #fee2e2; border-left: 4px solid #dc2626; padding: 12px; margin: 8px 0; border-radius: 6px;">
                    <strong style="color: #991b1b;">❌ DUPLICATE NIN</strong><br>
                    <span style="color: #7f1d1d; font-size: 13px;">
                        This NIN is already registered on another account.<br>
                        <strong>Other Vendor ID:</strong> {obj.duplicate_nin_vendor_id or 'Unknown'}
                    </span>
                </div>
            ''')
        
        if obj.has_duplicate_bvn:
            flags.append(f'''
                <div style="background: #fee2e2; border-left: 4px solid #dc2626; padding: 12px; margin: 8px 0; border-radius: 6px;">
                    <strong style="color: #991b1b;">❌ DUPLICATE BVN</strong><br>
                    <span style="color: #7f1d1d; font-size: 13px;">
                        This BVN is already registered on another account.<br>
                        <strong>Other Vendor ID:</strong> {obj.duplicate_bvn_vendor_id or 'Unknown'}
                    </span>
                </div>
            ''')
        
        if obj.is_underage:
            age = obj.calculated_age or 0
            flags.append(f'''
                <div style="background: #fee2e2; border-left: 4px solid #dc2626; padding: 12px; margin: 8px 0; border-radius: 6px;">
                    <strong style="color: #991b1b;">🚫 UNDERAGE VENDOR</strong><br>
                    <span style="color: #7f1d1d; font-size: 13px;">
                        Vendor is <strong>{age} years old</strong> (must be 18+)<br>
                        <strong>DOB:</strong> {obj.dob.strftime('%B %d, %Y') if obj.dob else 'Unknown'}
                    </span>
                </div>
            ''')
        
        if not flags:
            return format_html('''
                <div style="background: #d1fae5; border-left: 4px solid #10b981; padding: 12px; border-radius: 6px;">
                    <strong style="color: #065f46;">✅ NO RISK FLAGS DETECTED</strong><br>
                    <span style="color: #047857; font-size: 13px;">All automated security checks passed successfully.</span>
                </div>
            ''')
        
        risk_html = ''.join(flags)
        
        # Risk Score Bar
        risk_color = '#dc2626' if obj.risk_score > 50 else '#f59e0b' if obj.risk_score > 20 else '#10b981'
        risk_html += f'''
            <div style="background: #fef3c7; border-left: 4px solid #f59e0b; padding: 12px; margin-top: 12px; border-radius: 6px;">
                <strong style="color: #78350f;">RISK SCORE: {obj.risk_score}/100</strong>
                <div style="width: 100%; background: #e5e7eb; height: 24px; border-radius: 6px; margin-top: 8px; overflow: hidden;">
                    <div style="width: {obj.risk_score}%; background: {risk_color}; height: 100%; display: flex; align-items: center; justify-content: center; color: white; font-weight: 600; font-size: 12px;">
                        {obj.risk_score}%
                    </div>
                </div>
            </div>
        '''
        
        return format_html(risk_html)
    
    risk_flags_summary.short_description = '⚠️ Risk Assessment'
    
    # Admin Actions
    def approve_vendors(self, request, queryset):
        """Approve selected vendors with safety checks"""
        count = 0
        warnings = []
        
        for vendor in queryset:
            # Check prerequisites
            if vendor.identity_status != 'nin_verified':
                warnings.append(f'{vendor.full_name}: NIN not verified')
                continue
            
            if vendor.bank_status != 'bvn_verified':
                warnings.append(f'{vendor.full_name}: BVN not verified')
                continue
            
            # Warn about high-risk vendors
            if vendor.risk_score > 50:
                warnings.append(
                    f'⚠️ {vendor.full_name}: HIGH RISK ({vendor.risk_score}/100) - '
                    f'Review flags before approving'
                )
                continue
            
            # Check for critical flags
            if vendor.is_underage:
                warnings.append(f'🚫 {vendor.full_name}: UNDERAGE ({vendor.calculated_age} years) - Cannot approve')
                continue
            
            # Approve
            vendor.verification_status = 'approved'
            vendor.approved_at = timezone.now()
            vendor.reviewed_by = request.user
            vendor.reviewed_at = timezone.now()
            vendor.save()
            count += 1
            
            logger.info(
                f"✅ VENDOR APPROVED: {vendor.full_name} (ID: {vendor.vendor_id}) "
                f"by {request.user.email}"
            )
        
        if warnings:
            self.message_user(request, ' | '.join(warnings), messages.WARNING)
        
        if count > 0:
            self.message_user(
                request,
                f'✅ Approved {count} vendor(s)',
                messages.SUCCESS
            )
    
    approve_vendors.short_description = '✅ Approve selected vendors'
    
    def reject_vendors(self, request, queryset):
        """Reject selected vendors"""
        count = queryset.update(
            verification_status='rejected',
            reviewed_by=request.user,
            reviewed_at=timezone.now()
        )
        
        for vendor in queryset:
            logger.warning(
                f"❌ VENDOR REJECTED: {vendor.full_name} (ID: {vendor.vendor_id}) "
                f"by {request.user.email}"
            )
        
        self.message_user(request, f'❌ Rejected {count} vendor(s)', messages.WARNING)
    
    reject_vendors.short_description = '❌ Reject selected vendors'
    
    def suspend_vendors(self, request, queryset):
        """Suspend selected vendors"""
        count = queryset.update(verification_status='suspended')
        
        for vendor in queryset:
            logger.warning(
                f"⏸ VENDOR SUSPENDED: {vendor.full_name} (ID: {vendor.vendor_id}) "
                f"by {request.user.email}"
            )
        
        self.message_user(request, f'⏸ Suspended {count} vendor(s)', messages.WARNING)
    
    suspend_vendors.short_description = '⏸ Suspend selected vendors'
    
    def recalculate_risk_scores(self, request, queryset):
        """Recalculate risk scores for selected vendors"""
        count = 0
        for vendor in queryset:
            vendor.calculate_risk_score()
            vendor.save()
            count += 1
        
        self.message_user(
            request,
            f'🔄 Recalculated risk scores for {count} vendor(s)',
            messages.SUCCESS
        )
    
    recalculate_risk_scores.short_description = '🔄 Recalculate risk scores'
    
    def flag_for_review(self, request, queryset):
        """Flag vendors for manual review"""
        count = 0
        for vendor in queryset:
            if not vendor.admin_internal_notes:
                vendor.admin_internal_notes = f"[FLAGGED FOR REVIEW by {request.user.email} on {timezone.now().strftime('%Y-%m-%d %H:%M')}]\n\n"
            else:
                vendor.admin_internal_notes += f"\n[FLAGGED FOR REVIEW by {request.user.email} on {timezone.now().strftime('%Y-%m-%d %H:%M')}]\n"
            vendor.save()
            count += 1
        
        self.message_user(
            request,
            f'🚩 Flagged {count} vendor(s) for manual review',
            messages.INFO
        )
    
    flag_for_review.short_description = '🚩 Flag for manual review'


@admin.register(VerificationAttempt)
class VerificationAttemptAdmin(admin.ModelAdmin):
    list_display = ['vendor', 'attempt_type', 'status', 'created_at']
    list_filter = ['attempt_type', 'status', 'created_at']
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
    """Manage subcategories inside MainCategory admin"""
    model = SubCategory
    extra = 1
    fields = ['name', 'slug', 'icon', 'is_active', 'sort_order']
    prepopulated_fields = {'slug': ('name',)}


@admin.register(MainCategory)
class MainCategoryAdmin(admin.ModelAdmin):
    list_display = ['name', 'slug', 'subcategory_count', 'store_count', 'is_active', 'sort_order']
    list_editable = ['is_active', 'sort_order']
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
    list_display = ['name', 'main_category', 'product_count', 'is_active', 'sort_order']
    list_filter = ['main_category', 'is_active']
    list_editable = ['is_active', 'sort_order']
    search_fields = ['name', 'main_category__name']
    prepopulated_fields = {'slug': ('name',)}
    
    def product_count(self, obj):
        return obj.products.count()
    product_count.short_description = 'Products'


# Admin for SubCategoryAttribute
@admin.register(SubCategoryAttribute)
class SubCategoryAttributeAdmin(admin.ModelAdmin):
    list_display = (
        'name',
        'subcategory',
        'field_type',
        'is_required',
        'is_active',
        'sort_order',
    )
    list_filter = ('subcategory', 'field_type', 'is_active')
    search_fields = ('name',)
    ordering = ('subcategory', 'sort_order')


# ==========================================
# STORE ADMIN
# ==========================================

@admin.register(Store)
class StoreAdmin(admin.ModelAdmin):
    list_display = [
        'store_name', 'vendor_name', 'main_category', 
        'category_locked_badge', 'is_published', 
        'total_products', 'total_orders', 'total_sales', 'average_rating'
    ]
    list_filter = ['main_category', 'is_published', 'main_category_locked', 'created_at']
    search_fields = ['store_name', 'vendor__full_name', 'vendor__user__email']
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
            'fields': (
                'main_category', 'main_category_locked', 'main_category_locked_at'
            )
        }),
        ('Branding', {
            'fields': ('logo', 'logo_preview', 'banner', 'banner_preview', 'primary_color')
        }),
        ('Contact Information', {
            'fields': ('business_email', 'phone', 'whatsapp', 'address')
        }),
        ('Social Links', {
            'fields': ('instagram', 'facebook', 'twitter')
        }),
        ('Policies', {
            'fields': ('shipping_policy', 'return_policy')
        }),
        ('Settings', {
            'fields': ('is_published', 'allow_reviews')
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
            return format_html('<span style="color: red; font-weight: bold;">🔒 Locked</span>')
        return format_html('<span style="color: green;">🔓 Unlocked</span>')
    category_locked_badge.short_description = 'Category Status'
    
    def logo_preview(self, obj):
        if obj.logo:
            return format_html('<img src="{}" width="100" height="100" style="object-fit: cover;" />', obj.logo.url)
        return '-'
    logo_preview.short_description = 'Logo Preview'
    
    def banner_preview(self, obj):
        if obj.banner:
            return format_html('<img src="{}" style="max-width: 300px; max-height: 100px; object-fit: contain;" />', obj.banner.url)
        return '-'
    banner_preview.short_description = 'Banner Preview'


@admin.register(CategoryChangeRequest)
class CategoryChangeRequestAdmin(admin.ModelAdmin):
    list_display = [
        'request_id_short',
        'store_name',
        'vendor_name',
        'current_category',
        'requested_category',
        'status_badge',
        'created_at',
        'days_since_last_change'
    ]
    
    list_filter = ['status', 'created_at', 'reviewed_at']
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
                '<div style="background: #dbeafe; padding: 12px; border-radius: 6px; border-left: 4px solid #3b82f6;">'
                '<strong>Review vendor history and store performance before approving</strong>'
                '</div>'
            )
        }),
        ('✅ Admin Response', {
            'fields': ('status', 'admin_comment', 'reviewed_by', 'reviewed_at')
        }),
        ('🕐 Timestamps', {
            'fields': ('created_at', 'updated_at')
        }),
    )
    
    actions = ['approve_requests', 'reject_requests', 'require_more_info']
    
    # Display Methods
    def request_id_short(self, obj):
        return f"CR-{obj.id}"
    request_id_short.short_description = 'Request ID'
    
    def store_name(self, obj):
        return obj.store.store_name
    store_name.short_description = 'Store'
    
    def vendor_name(self, obj):
        return obj.store.vendor.full_name
    vendor_name.short_description = 'Vendor'
    
    def status_badge(self, obj):
        colors = {
            'pending': '#f59e0b',
            'approved': '#10b981',
            'rejected': '#ef4444',
        }
        color = colors.get(obj.status, '#6b7280')
        return format_html(
            '<span style="background-color: {}; color: white; padding: 4px 12px; border-radius: 6px; font-weight: 600; font-size: 11px;">{}</span>',
            color, obj.get_status_display()
        )
    status_badge.short_description = 'Status'
    
    def days_since_last_change(self, obj):
        """Show how long since last category change"""
        if obj.store.main_category_last_changed_at:
            days = (timezone.now() - obj.store.main_category_last_changed_at).days
            return format_html(
                '<span style="color: {};">{} days ago</span>',
                '#10b981' if days >= 365 else '#ef4444',
                days
            )
        return format_html('<span style="color: #6b7280;">Never changed</span>')
    days_since_last_change.short_description = 'Last Change'
    
    # Admin Actions
    def approve_requests(self, request, queryset):
        """Approve category change requests"""
        from .views import approve_category_change
        
        count = 0
        errors = []
        
        for change_request in queryset.filter(status='pending'):
            success, message = approve_category_change(change_request.id, request.user)
            
            if success:
                count += 1
                logger.info(
                    f"✅ CATEGORY CHANGE APPROVED: {change_request.store.store_name} "
                    f"({change_request.current_category.name} → {change_request.requested_category.name}) "
                    f"by {request.user.email}"
                )
            else:
                errors.append(f"{change_request.store.store_name}: {message}")
        
        if errors:
            self.message_user(request, ' | '.join(errors), messages.ERROR)
        
        if count > 0:
            self.message_user(
                request,
                f'✅ Approved {count} category change request(s)',
                messages.SUCCESS
            )
    
    approve_requests.short_description = '✅ Approve selected requests'
    
    def reject_requests(self, request, queryset):
        """Reject category change requests"""
        from .views import reject_category_change
        
        count = 0
        
        for change_request in queryset.filter(status='pending'):
            success, message = reject_category_change(
                change_request.id,
                request.user,
                reason='Request rejected by admin'
            )
            
            if success:
                count += 1
                logger.info(
                    f"❌ CATEGORY CHANGE REJECTED: {change_request.store.store_name} "
                    f"by {request.user.email}"
                )
        
        if count > 0:
            self.message_user(
                request,
                f'❌ Rejected {count} category change request(s)',
                messages.WARNING
            )
    
    reject_requests.short_description = '❌ Reject selected requests'
    
    def require_more_info(self, request, queryset):
        """Request more information from vendor"""
        count = 0
        
        for change_request in queryset.filter(status='pending'):
            change_request.admin_comment = (
                f"[{timezone.now().strftime('%Y-%m-%d')}] Admin {request.user.email}: "
                f"More information required. Please provide additional details."
            )
            change_request.save()
            count += 1
        
        self.message_user(
            request,
            f'📧 Requested more info for {count} request(s)',
            messages.INFO
        )
    
    require_more_info.short_description = '📧 Request more information'

# ==========================================
# PRODUCT ADMIN (FIXED)
# ==========================================

@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = [
        'title', 'vendor_name', 'subcategory', 'price',
        'stock_badge',
        'display_attributes',
        'status', 'sales_count', 'created_at'
    ]
    list_filter = [
        'status', 'track_inventory',
        'subcategory__main_category', 'subcategory', 'created_at'
    ]
    search_fields = ['title', 'vendor__full_name', 'sku']
    readonly_fields = [
        'slug', 'vendor', 'store', 'views_count', 'sales_count', 
        'created_at', 'updated_at', 'published_at', 'main_category', 'formatted_attributes', 'attributes_preview'
    ]
    # ❌ REMOVE THIS LINE - It conflicts with readonly_fields
    # prepopulated_fields = {'slug': ('title',)}
    
    fieldsets = (
        ('Basic Info', {
            'fields': ('vendor', 'store', 'title', 'slug', 'description')
        }),
        ('Category', {
            'fields': ('subcategory', 'main_category')
        }),
        ('Pricing & Inventory', {
            'fields': ('price', 'compare_at_price', 'stock_quantity', 'low_stock_threshold', 'track_inventory', 'sku')
        }),
        ('Status', {
            'fields': ('status', 'is_featured')
        }),
        ('Stats', {
            'fields': ('views_count', 'sales_count')
        }),
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
        """Show main category for reference"""
        return obj.subcategory.main_category.name if obj.subcategory else '-'
    main_category.short_description = 'Main Category'

    def stock_badge(self, obj):
        """Display stock status with color"""
        if not obj.track_inventory:
            return format_html('<span style="color: gray;">∞ Not Tracked</span>')
        
        if obj.stock_quantity == 0:
            return format_html('<span style="color: red; font-weight: bold;">❌ OUT</span>')
        elif obj.is_low_stock:
            return format_html(
                '<span style="color: orange; font-weight: bold;">⚠️ LOW ({})</span>',
                obj.stock_quantity
            )
        else:
            return format_html(
                '<span style="color: green;">✓ {} units</span>', 
                obj.stock_quantity
            )
    stock_badge.short_description = 'Stock'
    
    def formatted_attributes(self, obj):
        if not obj.attributes:
            return "— No attributes —"

        return "\n".join(
            f"{key}: {value}" for key, value in obj.attributes.items()
        )

    formatted_attributes.short_description = "Product Specifications"

    def attributes_preview(self, obj):
        if not obj.attributes:
            return "-"

        rows = []
        for attr_id, value in obj.attributes.items():
            attr = SubCategoryAttribute.objects.filter(id=attr_id).first()
            if attr:
                rows.append(f"{attr.name}: {value}")

        return format_html("<br>".join(rows))

    attributes_preview.short_description = "Product Specifications"

    @admin.display(description="Specifications")
    def display_attributes(self, obj):
        if not obj.attributes:
            return "-"

        lines = []
        for attr_id, value in obj.attributes.items():
            try:
                # attr_id may be string; coerce to int when possible
                lookup_id = int(attr_id) if isinstance(attr_id, str) and attr_id.isdigit() else attr_id
                attr = SubCategoryAttribute.objects.get(id=lookup_id)
                lines.append(f"{attr.name}: {value}")
            except SubCategoryAttribute.DoesNotExist:
                continue

        return ", ".join(lines)
    

# ==========================================
# WALLET & TRANSACTIONS ADMIN
# ==========================================

@admin.register(Wallet)
class WalletAdmin(admin.ModelAdmin):
    list_display = [
        'vendor_name', 'balance', 'pending_balance', 
        'total_earned', 'total_withdrawn', 'commission_rate', 
        'is_verified'
    ]
    list_filter = ['is_verified', 'auto_payout']
    search_fields = ['vendor__full_name', 'account_number', 'bank_name']
    readonly_fields = [
        'vendor', 'balance', 'pending_balance', 'total_earned', 
        'total_withdrawn', 'created_at', 'updated_at', 'verified_at'
    ]
    
    fieldsets = (
        ('Vendor', {
            'fields': ('vendor',)
        }),
        ('Bank Account (Auto-filled from BVN)', {
            'fields': ('account_number', 'bank_name', 'bank_code', 'account_holder_name')
        }),
        ('Balances (Read-only)', {
            'fields': ('balance', 'pending_balance', 'total_earned', 'total_withdrawn')
        }),
        ('Settings', {
            'fields': ('commission_rate', 'auto_payout', 'payout_threshold')
        }),
        ('Verification', {
            'fields': ('is_verified', 'verified_at')
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at')
        }),
    )
    
    def vendor_name(self, obj):
        return obj.vendor.full_name
    vendor_name.short_description = 'Vendor'


@admin.register(Transaction)
class TransactionAdmin(admin.ModelAdmin):
    list_display = [
        'transaction_id_short', 'wallet_vendor', 'transaction_type', 
        'amount', 'status', 'created_at'
    ]
    list_filter = ['transaction_type', 'status', 'created_at']
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
    list_display = [
        'order_id_short', 'vendor_name', 'customer_name', 
        'status', 'total_amount', 'vendor_amount', 'created_at'
    ]
    list_filter = ['status', 'payment_status', 'created_at']
    search_fields = ['order_id', 'vendor__full_name', 'customer__email', 'payment_reference']
    readonly_fields = [
        'order_id', 'vendor', 'customer', 'total_amount', 
        'commission_amount', 'vendor_amount', 'created_at', 
        'updated_at', 'paid_at', 'delivered_at'
    ]
    
    fieldsets = (
        ('Order Details', {
            'fields': ('order_id', 'vendor', 'customer', 'status')
        }),
        ('Payment', {
            'fields': (
                'total_amount', 'commission_amount', 'vendor_amount',
                'payment_reference', 'payment_status', 'paid_at'
            )
        }),
        ('Shipping', {
            'fields': ('shipping_address', 'shipping_phone', 'tracking_number')
        }),
        ('Notes', {
            'fields': ('customer_note', 'vendor_note')
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at', 'delivered_at')
        }),
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
    list_display = [
        'refund_id_short', 'order', 'vendor_name', 
        'reason', 'amount', 'status', 'created_at'
    ]
    list_filter = ['status', 'reason', 'created_at']
    search_fields = ['refund_id', 'order__order_id', 'vendor__full_name']
    readonly_fields = [
        'refund_id', 'order', 'order_item', 'vendor', 
        'amount', 'created_at', 'updated_at', 'processed_at'
    ]
    
    fieldsets = (
        ('Refund Details', {
            'fields': ('refund_id', 'order', 'order_item', 'vendor', 'amount')
        }),
        ('Request', {
            'fields': ('reason', 'description', 'status')
        }),
        ('Admin Response', {
            'fields': ('admin_comment', 'processed_by', 'processed_at')
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at')
        }),
    )
    
    actions = ['approve_refunds', 'reject_refunds']
    
    def refund_id_short(self, obj):
        return str(obj.refund_id)[:8]
    refund_id_short.short_description = 'Refund ID'
    
    def vendor_name(self, obj):
        return obj.vendor.full_name
    vendor_name.short_description = 'Vendor'
    
    def approve_refunds(self, request, queryset):
        """Approve refund requests"""
        count = queryset.filter(status='pending').update(
            status='approved',
            processed_by=request.user,
            processed_at=timezone.now()
        )
        self.message_user(request, f'✓ Approved {count} refund request(s)', messages.SUCCESS)
    approve_refunds.short_description = 'Approve selected refunds'
    
    def reject_refunds(self, request, queryset):
        """Reject refund requests"""
        count = queryset.filter(status='pending').update(
            status='rejected',
            processed_by=request.user,
            processed_at=timezone.now()
        )
        self.message_user(request, f'✗ Rejected {count} refund request(s)', messages.WARNING)
    reject_refunds.short_description = 'Reject selected refunds'


# ==========================================
# NOTIFICATIONS ADMIN
# ==========================================

@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ['title', 'vendor_name', 'notification_type', 'is_read', 'created_at']
    list_filter = ['notification_type', 'is_read', 'created_at']
    search_fields = ['title', 'message', 'vendor__full_name']
    readonly_fields = ['vendor', 'created_at', 'read_at']
    
    def vendor_name(self, obj):
        return obj.vendor.full_name
    vendor_name.short_description = 'Vendor'