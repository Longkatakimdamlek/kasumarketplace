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
    Wallet, Transaction, Order, OrderItem, RefundRequest, Notification
)


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
        'student_badge', 'can_sell_badge', 'created_at'
    ]
    list_filter = [
        'verification_status', 'identity_status', 'bank_status', 
        'student_status', 'created_at'
    ]
    search_fields = ['full_name', 'user__email', 'phone', 'matric_number', 'vendor_id']
    readonly_fields = [
        'vendor_id', 'user', 'created_at', 'updated_at', 
        'nin_verified_at', 'bvn_verified_at', 'student_verified_at', 
        'approved_at', 'completion_percentage', 'current_step',
        'photo_preview', 'student_id_preview', 'selfie_preview'
    ]
    
    fieldsets = (
        ('Basic Information', {
            'fields': ('vendor_id', 'user', 'full_name', 'phone', 'gender', 'dob')
        }),
        ('Address', {
            'fields': ('address', 'state', 'lga')
        }),
        ('Identity Verification (NIN)', {
            'fields': (
                'identity_status', 'nin_number', 'photo_from_nin', 'photo_preview',
                'nin_verified_at'
            )
        }),
        ('Banking Verification (BVN)', {
            'fields': ('bank_status', 'bvn_number', 'bvn_verified_at')
        }),
        ('Student Verification (Optional)', {
            'fields': (
                'student_status', 'matric_number', 'department', 'level',
                'student_id_image', 'student_id_preview', 
                'selfie', 'selfie_preview', 'student_verified_at'
            )
        }),
        ('Store Setup', {
            'fields': ('store_setup_completed', 'store_setup_skipped')
        }),
        ('Verification Status', {
            'fields': (
                'verification_status', 'completion_percentage', 'current_step',
                'admin_comment', 'reviewed_by', 'reviewed_at', 'approved_at'
            )
        }),
        ('Progress Tracking', {
            'fields': ('verification_progress',),
            'classes': ('collapse',)
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )
    
    inlines = [VerificationAttemptInline]
    
    actions = ['approve_vendors', 'reject_vendors', 'suspend_vendors']
    
    def vendor_id_short(self, obj):
        return str(obj.vendor_id)[:8]
    vendor_id_short.short_description = 'Vendor ID'
    
    def user_email(self, obj):
        return obj.user.email
    user_email.short_description = 'Email'
    
    def verification_badge(self, obj):
        colors = {
            'approved': 'green',
            'rejected': 'red',
            'pending': 'orange',
            'nin_verified': 'blue',
            'bvn_verified': 'blue',
            'student_verified': 'blue',
            'suspended': 'gray',
        }
        color = colors.get(obj.verification_status, 'gray')
        return format_html(
            '<span style="background-color: {}; color: white; padding: 3px 10px; border-radius: 3px;">{}</span>',
            color, obj.get_verification_status_display()
        )
    verification_badge.short_description = 'Status'
    
    def identity_badge(self, obj):
        if obj.identity_status == 'nin_verified':
            return format_html('<span style="color: green;">✓ NIN</span>')
        return format_html('<span style="color: orange;">⏳ NIN</span>')
    identity_badge.short_description = 'Identity'
    
    def bank_badge(self, obj):
        if obj.bank_status == 'bvn_verified':
            return format_html('<span style="color: green;">✓ BVN</span>')
        return format_html('<span style="color: orange;">⏳ BVN</span>')
    bank_badge.short_description = 'Banking'
    
    def student_badge(self, obj):
        if obj.student_status == 'verified':
            return format_html('<span style="color: green;">✓ Student</span>')
        elif obj.student_status == 'not_applicable':
            return format_html('<span style="color: gray;">N/A</span>')
        return format_html('<span style="color: orange;">⏳ Student</span>')
    student_badge.short_description = 'Student'
    
    def can_sell_badge(self, obj):
        if obj.can_sell:
            return format_html('<span style="color: green; font-weight: bold;">✓ Can Sell</span>')
        return format_html('<span style="color: red;">✗ Cannot Sell</span>')
    can_sell_badge.short_description = 'Can Sell?'
    
    def photo_preview(self, obj):
        if obj.photo_from_nin:
            return format_html('<img src="{}" width="100" height="100" style="object-fit: cover;" />', obj.photo_from_nin.url)
        return '-'
    photo_preview.short_description = 'NIN Photo'
    
    def student_id_preview(self, obj):
        if obj.student_id_image:
            return format_html('<img src="{}" width="150" style="max-height: 100px; object-fit: contain;" />', obj.student_id_image.url)
        return '-'
    student_id_preview.short_description = 'Student ID'
    
    def selfie_preview(self, obj):
        if obj.selfie:
            return format_html('<img src="{}" width="100" height="100" style="object-fit: cover;" />', obj.selfie.url)
        return '-'
    selfie_preview.short_description = 'Selfie'
    
    # Admin Actions
    def approve_vendors(self, request, queryset):
        """Approve selected vendors"""
        count = 0
        for vendor in queryset:
            if vendor.identity_status == 'nin_verified' and vendor.bank_status == 'bvn_verified':
                vendor.verification_status = 'approved'
                vendor.approved_at = timezone.now()
                vendor.reviewed_by = request.user
                vendor.reviewed_at = timezone.now()
                vendor.save()
                count += 1
                
                # TODO: Send approval email
                
        self.message_user(request, f'✓ Approved {count} vendor(s)', messages.SUCCESS)
    approve_vendors.short_description = 'Approve selected vendors'
    
    def reject_vendors(self, request, queryset):
        """Reject selected vendors"""
        count = queryset.update(
            verification_status='rejected',
            reviewed_by=request.user,
            reviewed_at=timezone.now()
        )
        self.message_user(request, f'✗ Rejected {count} vendor(s)', messages.WARNING)
    reject_vendors.short_description = 'Reject selected vendors'
    
    def suspend_vendors(self, request, queryset):
        """Suspend selected vendors"""
        count = queryset.update(verification_status='suspended')
        self.message_user(request, f'⏸ Suspended {count} vendor(s)', messages.WARNING)
    suspend_vendors.short_description = 'Suspend selected vendors'


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
    list_display = ['store', 'current_category', 'requested_category', 'status', 'created_at']
    list_filter = ['status', 'created_at']
    search_fields = ['store__store_name', 'reason']
    readonly_fields = ['store', 'current_category', 'requested_category', 'created_at', 'updated_at']
    
    fieldsets = (
        ('Request Details', {
            'fields': ('store', 'current_category', 'requested_category', 'reason')
        }),
        ('Admin Response', {
            'fields': ('status', 'admin_comment', 'reviewed_by', 'reviewed_at')
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at')
        }),
    )
    
    actions = ['approve_requests', 'reject_requests']
    
    def approve_requests(self, request, queryset):
        """Approve category change requests"""
        count = 0
        for change_request in queryset.filter(status='pending'):
            # Update store's main category
            store = change_request.store
            store.main_category = change_request.requested_category
            store.save()
            
            # Update request
            change_request.status = 'approved'
            change_request.reviewed_by = request.user
            change_request.reviewed_at = timezone.now()
            change_request.save()
            
            count += 1
            
            # TODO: Send notification to vendor
        
        self.message_user(request, f'✓ Approved {count} category change request(s)', messages.SUCCESS)
    approve_requests.short_description = 'Approve selected requests'
    
    def reject_requests(self, request, queryset):
        """Reject category change requests"""
        count = queryset.filter(status='pending').update(
            status='rejected',
            reviewed_by=request.user,
            reviewed_at=timezone.now()
        )
        self.message_user(request, f'✗ Rejected {count} category change request(s)', messages.WARNING)
    reject_requests.short_description = 'Reject selected requests'


# ==========================================
# PRODUCT ADMIN
# ==========================================

@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = [
        'title', 'vendor_name', 'subcategory', 'price', 
        'quantity', 'status', 'sales_count', 'created_at'
    ]
    list_filter = ['status', 'subcategory__main_category', 'subcategory', 'created_at']
    search_fields = ['title', 'vendor__full_name', 'sku']
    readonly_fields = [
        'slug', 'vendor', 'store', 'views_count', 'sales_count', 
        'created_at', 'updated_at', 'published_at', 'main_category'
    ]
    prepopulated_fields = {'slug': ('title',)}
    
    fieldsets = (
        ('Basic Info', {
            'fields': ('vendor', 'store', 'title', 'slug', 'description')
        }),
        ('Category', {
            'fields': ('subcategory', 'main_category')
        }),
        ('Pricing & Inventory', {
            'fields': ('price', 'compare_at_price', 'quantity', 'sku')
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


@admin.register(ProductImage)
class ProductImageAdmin(admin.ModelAdmin):
    list_display = ['product', 'image_preview', 'is_primary', 'sort_order', 'created_at']
    list_filter = ['is_primary', 'created_at']
    search_fields = ['product__title']
    
    def image_preview(self, obj):
        if obj.image:
            return format_html('<img src="{}" width="80" height="80" style="object-fit: cover;" />', obj.image.url)
        return '-'
    image_preview.short_description = 'Preview'


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