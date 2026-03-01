from django.contrib import admin
from django.utils.html import format_html
from django.utils import timezone
from .models import (
    Cart, CartItem,
    PaymentTransaction,
    MainOrder, SubOrder, SubOrderItem,
    WalletTransaction,
    RefundRecord,
    Dispute,
)


# ==========================================
# CART
# ==========================================

class CartItemInline(admin.TabularInline):
    model = CartItem
    extra = 0
    readonly_fields = ['product', 'quantity', 'unit_price', 'subtotal', 'added_at']
    fields = ['product', 'quantity', 'unit_price', 'subtotal', 'added_at']

    def unit_price(self, obj):
        return f"₦{obj.unit_price:,.2f}"
    unit_price.short_description = "Unit Price"

    def subtotal(self, obj):
        return f"₦{obj.subtotal:,.2f}"
    subtotal.short_description = "Subtotal"


@admin.register(Cart)
class CartAdmin(admin.ModelAdmin):
    list_display = ['id', 'owner', 'total_items', 'grand_total_display', 'created_at']
    list_filter = ['created_at']
    search_fields = ['user__email', 'session_key']
    readonly_fields = ['session_key', 'created_at', 'updated_at']
    inlines = [CartItemInline]

    def owner(self, obj):
        if obj.user:
            return obj.user.email
        return f"Anonymous ({obj.session_key[:8]}...)"
    owner.short_description = "Owner"

    def grand_total_display(self, obj):
        return f"₦{obj.grand_total:,.2f}"
    grand_total_display.short_description = "Grand Total"


# ==========================================
# PAYMENT TRANSACTION
# ==========================================

@admin.register(PaymentTransaction)
class PaymentTransactionAdmin(admin.ModelAdmin):
    list_display = [
        'reference', 'user_email', 'amount_display',
        'status', 'webhook_processed', 'created_at'
    ]
    list_filter = ['status', 'webhook_processed', 'created_at']
    search_fields = ['reference', 'user__email']
    readonly_fields = [
        'reference', 'user', 'amount', 'status',
        'paystack_response', 'webhook_processed',
        'created_at', 'verified_at'
    ]

    def user_email(self, obj):
        return obj.user.email if obj.user else '—'
    user_email.short_description = "Buyer"

    def amount_display(self, obj):
        return f"₦{obj.amount:,.2f}"
    amount_display.short_description = "Amount"

    # Prevent any edits — payment records are immutable
    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


# ==========================================
# MAIN ORDER
# ==========================================

class SubOrderInline(admin.TabularInline):
    model = SubOrder
    extra = 0
    readonly_fields = ['store', 'subtotal', 'status', 'payment_status', 'vendor_deadline']
    fields = ['store', 'subtotal', 'status', 'payment_status', 'vendor_deadline']
    show_change_link = True


@admin.register(MainOrder)
class MainOrderAdmin(admin.ModelAdmin):
    list_display = [
        'order_number', 'buyer_email', 'total_display',
        'payment_status', 'suborder_count', 'created_at'
    ]
    list_filter = ['payment_status', 'created_at']
    search_fields = ['order_number', 'reference', 'buyer__email']
    readonly_fields = [
        'order_number', 'reference', 'buyer',
        'total', 'payment_status',
        'delivery_address', 'delivery_city',
        'delivery_state', 'delivery_phone',
        'created_at', 'updated_at'
    ]
    inlines = [SubOrderInline]

    def buyer_email(self, obj):
        return obj.buyer.email if obj.buyer else '—'
    buyer_email.short_description = "Buyer"

    def total_display(self, obj):
        return f"₦{obj.total:,.2f}"
    total_display.short_description = "Total"

    def has_add_permission(self, request):
        return False


# ==========================================
# SUB ORDER
# ==========================================

class SubOrderItemInline(admin.TabularInline):
    model = SubOrderItem
    extra = 0
    readonly_fields = ['product', 'product_title', 'unit_price', 'quantity', 'subtotal']
    fields = ['product_title', 'unit_price', 'quantity', 'subtotal']


class WalletTransactionInline(admin.TabularInline):
    model = WalletTransaction
    extra = 0
    readonly_fields = ['transaction_type', 'amount', 'status', 'reference', 'created_at']
    fields = ['transaction_type', 'amount', 'status', 'reference', 'created_at']


@admin.register(SubOrder)
class SubOrderAdmin(admin.ModelAdmin):
    list_display = [
        'id', 'main_order_number', 'store_name',
        'subtotal_display', 'status', 'payment_status',
        'deadline_status', 'created_at'
    ]
    list_filter = ['status', 'payment_status', 'created_at']
    search_fields = [
        'main_order__order_number',
        'store__store_name',
        'main_order__buyer__email'
    ]
    readonly_fields = [
        'main_order', 'store', 'subtotal',
        'payment_status', 'vendor_deadline',
        'confirmed_at', 'created_at', 'updated_at'
    ]
    fields = [
        'main_order', 'store', 'subtotal',
        'status', 'payment_status',
        'vendor_deadline', 'confirmed_at',
        'rejection_reason', 'created_at', 'updated_at'
    ]
    inlines = [SubOrderItemInline, WalletTransactionInline]

    def main_order_number(self, obj):
        return obj.main_order.order_number
    main_order_number.short_description = "Order"

    def store_name(self, obj):
        return obj.store.store_name
    store_name.short_description = "Store"

    def subtotal_display(self, obj):
        return f"₦{obj.subtotal:,.2f}"
    subtotal_display.short_description = "Subtotal"

    def deadline_status(self, obj):
        if obj.status != 'PENDING_VENDOR':
            return '—'
        if obj.is_vendor_deadline_passed:
            return format_html('<span style="color:red;">⚠ EXPIRED</span>')
        remaining = obj.vendor_deadline - timezone.now()
        hours = int(remaining.total_seconds() // 3600)
        return format_html(
            '<span style="color:orange;">{}h left</span>', hours
        )
    deadline_status.short_description = "Deadline"


# ==========================================
# WALLET TRANSACTION
# ==========================================

@admin.register(WalletTransaction)
class WalletTransactionAdmin(admin.ModelAdmin):
    list_display = [
        'id', 'wallet_vendor', 'transaction_type',
        'amount_display', 'status', 'reference', 'created_at'
    ]
    list_filter = ['transaction_type', 'status', 'created_at']
    search_fields = ['reference', 'wallet__vendor__user__email']
    readonly_fields = [
        'wallet', 'sub_order', 'transaction_type',
        'amount', 'status', 'reference',
        'created_at', 'updated_at'
    ]

    def wallet_vendor(self, obj):
        return obj.wallet.vendor.user.email
    wallet_vendor.short_description = "Vendor"

    def amount_display(self, obj):
        return f"₦{obj.amount:,.2f}"
    amount_display.short_description = "Amount"

    def has_add_permission(self, request):
        return False


# ==========================================
# REFUND RECORD
# ==========================================

@admin.register(RefundRecord)
class RefundRecordAdmin(admin.ModelAdmin):
    list_display = [
        'id', 'suborder_ref', 'reason',
        'amount_display', 'status', 'created_at'
    ]
    list_filter = ['status', 'reason', 'created_at']
    search_fields = ['sub_order__main_order__order_number']
    readonly_fields = [
        'sub_order', 'reason', 'amount',
        'paystack_response', 'created_at', 'updated_at'
    ]
    fields = [
        'sub_order', 'reason', 'amount',
        'status', 'note',
        'paystack_response',
        'created_at', 'updated_at', 'completed_at'
    ]

    def suborder_ref(self, obj):
        return f"SubOrder #{obj.sub_order.pk}"
    suborder_ref.short_description = "SubOrder"

    def amount_display(self, obj):
        return f"₦{obj.amount:,.2f}"
    amount_display.short_description = "Amount"


# ==========================================
# DISPUTE
# ==========================================

@admin.register(Dispute)
class DisputeAdmin(admin.ModelAdmin):
    list_display = [
        'id', 'suborder_ref', 'opened_by_email',
        'status', 'created_at', 'resolved_at'
    ]
    list_filter = ['status', 'created_at']
    search_fields = [
        'sub_order__main_order__order_number',
        'opened_by__email'
    ]
    readonly_fields = [
        'sub_order', 'opened_by', 'reason',
        'created_at', 'updated_at'
    ]
    fields = [
        'sub_order', 'opened_by', 'reason',
        'status', 'admin_note',
        'resolved_by', 'resolved_at',
        'created_at', 'updated_at'
    ]

    def suborder_ref(self, obj):
        return f"SubOrder #{obj.sub_order.pk} — {obj.sub_order.store.store_name}"
    suborder_ref.short_description = "SubOrder"

    def opened_by_email(self, obj):
        return obj.opened_by.email if obj.opened_by else '—'
    opened_by_email.short_description = "Opened By"

    def save_model(self, request, obj, form, change):
        """Auto-set resolved_by and resolved_at when admin resolves dispute"""
        if obj.status in ['RESOLVED_RELEASE', 'RESOLVED_REFUND', 'CLOSED']:
            if not obj.resolved_at:
                obj.resolved_at = timezone.now()
            if not obj.resolved_by:
                obj.resolved_by = request.user
        super().save_model(request, obj, form, change)