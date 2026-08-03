from django.utils.html import format_html
from django.utils import timezone
from django.contrib import admin, messages
from apps.vendors.models import Product, ProductImage, Store
from .models import Promotion
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
# ==========================================#

@admin.register(Dispute)
class DisputeAdmin(admin.ModelAdmin):
    list_display = [
        'id', 'order_number', 'buyer_email', 'vendor_store',
        'status_badge', 'amount_at_stake', 'created_at', 'action_buttons'
    ]
    list_filter = ['status', 'created_at']
    search_fields = [
        'opened_by__email',
        'sub_order__main_order__order_number',
        'reason',
    ]
    readonly_fields = [
        'sub_order', 'opened_by', 'created_at', 'resolved_at', 'resolved_by',
        'dispute_details', 'buyer_info', 'vendor_info', 'order_info',
    ]
    fieldsets = (
        ('📋 Dispute Summary', {
            'fields': ('dispute_details',)
        }),
        ('👤 Buyer Information', {
            'fields': ('buyer_info',)
        }),
        ('🏪 Vendor Information', {
            'fields': ('vendor_info',)
        }),
        ('📦 Order Information', {
            'fields': ('order_info',)
        }),
        ('⚙️ Resolution', {
            'fields': ('status', 'admin_note', 'resolved_at', 'resolved_by'),
        }),
    )
    actions = [
        'mark_under_review',
        'resolve_release_to_vendor',
        'resolve_refund_buyer',
        'close_dispute',
    ]
    save_on_top = True

    # ---- LIST DISPLAY METHODS ----

    def order_number(self, obj):
        return obj.sub_order.main_order.order_number
    order_number.short_description = 'Order'

    def buyer_email(self, obj):
        return obj.opened_by.email if obj.opened_by else 'N/A'
    buyer_email.short_description = 'Buyer'

    def vendor_store(self, obj):
        return obj.sub_order.store.store_name
    vendor_store.short_description = 'Store'

    def status_badge(self, obj):
        colors = {
            'OPEN': '#dc2626',
            'UNDER_REVIEW': '#d97706',
            'RESOLVED_RELEASE': '#059669',
            'RESOLVED_REFUND': '#7c3aed',
            'CLOSED': '#6b7280',
        }
        color = colors.get(obj.status, '#6b7280')
        return format_html(
            '<span style="background:{};color:white;padding:3px 8px;border-radius:12px;font-size:11px;font-weight:bold;">{}</span>',
            color, obj.get_status_display()
        )
    status_badge.short_description = 'Status'

    def amount_at_stake(self, obj):
        amount = '₦{:,.2f}'.format(obj.sub_order.subtotal)
        return format_html('<strong style="color:#059669;">{}</strong>', amount)
    amount_at_stake.short_description = 'Amount'

    def action_buttons(self, obj):
        # Always show a Review link back to the dispute
        return format_html(
            '<a href="{}" style="background:#3b82f6;color:white;padding:4px 10px;border-radius:4px;font-size:11px;text-decoration:none;font-weight:bold;">View / Resolve</a>',
            f'/admin/marketplace/dispute/{obj.pk}/change/'
        )
    action_buttons.short_description = 'Actions'

    # ---- READONLY FIELD RENDERERS ----

    def dispute_details(self, obj):
        return format_html(
            '''
            <div style="background:#fef3c7;border:1px solid #fbbf24;border-radius:8px;padding:16px;margin:8px 0;">
                <p style="margin:0 0 6px;font-weight:bold;color:#92400e;font-size:15px;">🚨 Dispute #{} — {}</p>
                <p style="margin:0 0 4px;color:#6b7280;font-size:12px;">Opened: {}</p>
                <p style="margin:0 0 12px;color:#6b7280;font-size:12px;">Status: <strong>{}</strong></p>
                <p style="margin:0 0 6px;font-weight:bold;color:#374151;">Buyer's Reason:</p>
                <div style="background:white;border:1px solid #e5e7eb;border-radius:6px;padding:12px;color:#374151;line-height:1.6;font-size:14px;">
                    {}
                </div>
            </div>
            ''',
            obj.pk,
            obj.sub_order.main_order.order_number,
            obj.created_at.strftime('%B %d, %Y at %I:%M %p'),
            obj.get_status_display(),
            obj.reason,
        )
    dispute_details.short_description = 'Dispute Details'

    def buyer_info(self, obj):
        buyer = obj.opened_by
        order = obj.sub_order.main_order
        return format_html(
            '''
            <div style="background:#eff6ff;border:1px solid #bfdbfe;border-radius:8px;padding:16px;">
                <p style="margin:0 0 6px;font-size:14px;"><strong>📧 Email:</strong> <a href="mailto:{}">{}</a></p>
                <p style="margin:0 0 6px;font-size:14px;"><strong>📞 Phone:</strong> <a href="tel:{}">{}</a></p>
                <p style="margin:0 0 6px;font-size:14px;"><strong>📍 Delivery Address:</strong> {}, {}, {}</p>
                <p style="margin:0 0 0px;font-size:14px;"><strong>📦 Order Placed:</strong> {}</p>
            </div>
            ''',
            buyer.email if buyer else '',
            buyer.email if buyer else 'N/A',
            order.delivery_phone or '',
            order.delivery_phone or 'N/A',
            order.delivery_address or 'N/A',
            order.delivery_city or '',
            order.delivery_state or '',
            order.created_at.strftime('%B %d, %Y'),
        )
    buyer_info.short_description = 'Buyer Info'

    def vendor_info(self, obj):
        store = obj.sub_order.store
        vendor = store.vendor
        return format_html(
            '''
            <div style="background:#f0fdf4;border:1px solid #bbf7d0;border-radius:8px;padding:16px;">
                <p style="margin:0 0 6px;font-size:14px;"><strong>🏪 Store:</strong> {}</p>
                <p style="margin:0 0 6px;font-size:14px;"><strong>📧 Vendor Email:</strong> <a href="mailto:{}">{}</a></p>
                <p style="margin:0 0 6px;font-size:14px;"><strong>📞 Store Phone:</strong> <a href="tel:{}">{}</a></p>
                <p style="margin:0 0 0px;font-size:14px;"><strong>💬 WhatsApp:</strong> {}</p>
            </div>
            ''',
            store.store_name,
            vendor.user.email,
            vendor.user.email,
            store.phone or '',
            store.phone or 'N/A',
            store.whatsapp or 'N/A',
        )
    vendor_info.short_description = 'Vendor Info'

    def order_info(self, obj):
        sub = obj.sub_order
        items = sub.items.select_related('product').all()
        items_rows = ''.join([
            f'<tr><td style="padding:6px 8px;border-bottom:1px solid #e5e7eb;">{item.product.title}</td>'
            f'<td style="padding:6px 8px;border-bottom:1px solid #e5e7eb;text-align:center;">{item.quantity}</td>'
            f'<td style="padding:6px 8px;border-bottom:1px solid #e5e7eb;text-align:right;">₦{item.unit_price:,.2f}</td>'
            f'<td style="padding:6px 8px;border-bottom:1px solid #e5e7eb;text-align:right;font-weight:bold;">₦{item.subtotal:,.2f}</td></tr>'
            for item in items
        ])
        total_formatted = '₦{:,.2f}'.format(sub.subtotal)
        return format_html(
            '''
            <div style="background:#f9fafb;border:1px solid #e5e7eb;border-radius:8px;padding:16px;">
                <p style="margin:0 0 10px;font-size:14px;"><strong>Order:</strong> {} | <strong>SubOrder #{}:</strong> {} items | <strong>Total: {}</strong></p>
                <table style="width:100%;border-collapse:collapse;font-size:13px;">
                    <thead>
                        <tr style="background:#e5e7eb;">
                            <th style="padding:6px 8px;text-align:left;">Product</th>
                            <th style="padding:6px 8px;text-align:center;">Qty</th>
                            <th style="padding:6px 8px;text-align:right;">Unit Price</th>
                            <th style="padding:6px 8px;text-align:right;">Total</th>
                        </tr>
                    </thead>
                    <tbody>{}</tbody>
                </table>
            </div>
            ''',
            sub.main_order.order_number,
            sub.pk,
            items.count(),
            total_formatted,
            format_html(items_rows),
        )
    order_info.short_description = 'Order Info'

    # ---- ADMIN ACTIONS ----

    @admin.action(description='👀 Mark as Under Review')
    def mark_under_review(self, request, queryset):
        updated = queryset.filter(status='OPEN').update(status='UNDER_REVIEW')
        self.message_user(request, f'{updated} dispute(s) marked as Under Review.', messages.SUCCESS)

    @admin.action(description='✅ Resolve — Release funds to vendor')
    def resolve_release_to_vendor(self, request, queryset):
        from apps.marketplace.models import WalletTransaction
        resolved = 0
        for dispute in queryset.filter(status__in=['OPEN', 'UNDER_REVIEW']):
            sub = dispute.sub_order
            already = WalletTransaction.objects.filter(
                sub_order=sub, transaction_type='AVAILABLE_CREDIT'
            ).exists()
            if not already:
                try:
                    wallet = sub.store.vendor.wallet
                    WalletTransaction.objects.create(
                        wallet=wallet,
                        sub_order=sub,
                        transaction_type='AVAILABLE_CREDIT',
                        amount=sub.subtotal,
                        status='AVAILABLE',
                        reference=sub.main_order.reference + '-DISPUTE-RELEASE',
                        note=f'Admin resolved dispute #{dispute.pk} — funds released to vendor',
                    )
                    wallet.pending_balance -= sub.subtotal
                    wallet.balance += sub.subtotal
                    wallet.total_earned += sub.subtotal
                    wallet.save(update_fields=['pending_balance', 'balance', 'total_earned', 'updated_at'])
                except Exception as e:
                    self.message_user(request, f'Wallet release failed for dispute #{dispute.pk}: {e}', messages.ERROR)
                    continue

            dispute.status = 'RESOLVED_RELEASE'
            dispute.resolved_at = timezone.now()
            dispute.resolved_by = request.user
            dispute.admin_note = dispute.admin_note or f'Resolved by {request.user.email} on {timezone.now().strftime("%B %d, %Y")}'
            dispute.save(update_fields=['status', 'resolved_at', 'resolved_by', 'admin_note'])

            sub.status = 'CONFIRMED'
            if not sub.confirmed_at:
                sub.confirmed_at = timezone.now()
            sub.save(update_fields=['status', 'confirmed_at'])

            # Notify buyer
            try:
                from apps.marketplace.services.email_service import _send
                _send(
                    subject=f'Dispute #{dispute.pk} Resolved — Order {sub.main_order.order_number}',
                    message=f'Your dispute has been reviewed. The funds have been released to the vendor. If you have further concerns, contact support.',
                    recipient_list=[dispute.opened_by.email],
                )
            except Exception:
                pass

            resolved += 1
        self.message_user(request, f'{resolved} dispute(s) resolved — funds released to vendor.', messages.SUCCESS)

    @admin.action(description='💸 Resolve — Refund buyer')
    def resolve_refund_buyer(self, request, queryset):
        from apps.marketplace.services.refund_service import trigger_refund_if_needed
        resolved = 0
        for dispute in queryset.filter(status__in=['OPEN', 'UNDER_REVIEW']):
            sub = dispute.sub_order
            result = trigger_refund_if_needed(sub)
            if result['success']:
                dispute.status = 'RESOLVED_REFUND'
                dispute.resolved_at = timezone.now()
                dispute.resolved_by = request.user
                dispute.admin_note = dispute.admin_note or f'Refund issued by {request.user.email} on {timezone.now().strftime("%B %d, %Y")}'
                dispute.save(update_fields=['status', 'resolved_at', 'resolved_by', 'admin_note'])

                sub.status = 'REFUNDED'
                sub.save(update_fields=['status'])

                # Notify buyer
                try:
                    from apps.marketplace.services.email_service import _send
                    _send(
                        subject=f'Dispute #{dispute.pk} Resolved — Refund Issued',
                        message=f'Your dispute for order {sub.main_order.order_number} has been reviewed and a refund of ₦{sub.subtotal:,.2f} has been processed to your original payment method.',
                        recipient_list=[dispute.opened_by.email],
                    )
                except Exception:
                    pass

                # Notify vendor
                try:
                    from apps.marketplace.services.email_service import _send
                    _send(
                        subject=f'Dispute #{dispute.pk} Resolved — Buyer Refunded',
                        message=f'The dispute for order {sub.main_order.order_number} has been reviewed. The buyer has been refunded ₦{sub.subtotal:,.2f}. The funds will not be released to your wallet for this order.',
                        recipient_list=[sub.store.vendor.user.email],
                    )
                except Exception:
                    pass

                resolved += 1
            else:
                self.message_user(
                    request,
                    f'Refund failed for dispute #{dispute.pk}: {result["message"]}',
                    messages.ERROR
                )

        self.message_user(request, f'{resolved} dispute(s) resolved — buyers refunded.', messages.SUCCESS)

    @admin.action(description='🔒 Close dispute (no action)')
    def close_dispute(self, request, queryset):
        updated = queryset.exclude(
            status__in=['RESOLVED_RELEASE', 'RESOLVED_REFUND']
        ).update(status='CLOSED', resolved_at=timezone.now())
        self.message_user(request, f'{updated} dispute(s) closed.', messages.WARNING)

    def save_model(self, request, obj, form, change):
        print('DisputeAdmin.save_model called', 'change=', change, 'pk=', getattr(obj, 'pk', None))
        if change:
            if obj.status in ['RESOLVED_RELEASE', 'RESOLVED_REFUND', 'CLOSED']:
                if not obj.resolved_by:
                    obj.resolved_by = request.user
                if not obj.resolved_at:
                    obj.resolved_at = timezone.now()

            # Get the note from POST data directly — bypasses changed_data issue
            submitted_note = request.POST.get('admin_note', '').strip()

            super().save_model(request, obj, form, change)

            if submitted_note:
                try:
                    from apps.marketplace.services.email_service import _send
                    
                    order_number = obj.sub_order.main_order.order_number
                    status_display = obj.get_status_display()
                    subject = f'Dispute Update — Order {order_number}'
                    
                    # Plain text fallback
                    plain = (
                        f'Dispute Update — Order {order_number}\n\n'
                        f'Status: {status_display}\n\n'
                        f'Admin Note:\n{submitted_note}\n\n'
                        f'For further assistance contact support@kasumarketplace.com.ng'
                    )
                    
                    # HTML email
                    html = f"""
                    <div style="font-family:'Segoe UI',Arial,sans-serif;max-width:580px;margin:0 auto;background:#ffffff;border-radius:12px;overflow:hidden;border:1px solid #e5e7eb;">
                      
                      <!-- Header -->
                      <div style="background:#1e293b;padding:28px 32px;">
                        <h1 style="margin:0;color:#ffffff;font-size:20px;font-weight:700;letter-spacing:-0.3px;">KasuMarketplace</h1>
                        <p style="margin:6px 0 0;color:#94a3b8;font-size:13px;">Dispute Resolution Centre</p>
                      </div>
                      
                      <!-- Body -->
                      <div style="padding:32px;">
                        <h2 style="margin:0 0 8px;color:#0f172a;font-size:18px;font-weight:700;">Dispute Update</h2>
                        <p style="margin:0 0 20px;color:#64748b;font-size:14px;">Order <strong style="color:#0f172a;">{order_number}</strong></p>
                        
                        <!-- Status badge -->
                        <div style="display:inline-block;background:#f1f5f9;border-radius:20px;padding:6px 14px;margin-bottom:24px;">
                          <span style="color:#475569;font-size:13px;font-weight:600;">Status: {status_display}</span>
                        </div>
                        
                        <!-- Admin note box -->
                        <div style="background:#f8fafc;border-left:4px solid #3b82f6;border-radius:0 8px 8px 0;padding:16px 20px;margin-bottom:24px;">
                          <p style="margin:0 0 6px;color:#3b82f6;font-size:12px;font-weight:700;text-transform:uppercase;letter-spacing:0.5px;">Message from Admin</p>
                          <p style="margin:0;color:#334155;font-size:14px;line-height:1.7;">{submitted_note}</p>
                        </div>
                        
                        <p style="margin:0 0 24px;color:#64748b;font-size:13px;line-height:1.6;">
                          If you have any questions or need further assistance, please contact our support team.
                        </p>
                        
                        <!-- CTA button -->
                        <a href="https://kasumarketplace.com.ng/orders/" 
                           style="display:inline-block;background:#0f172a;color:#ffffff;text-decoration:none;padding:12px 24px;border-radius:8px;font-size:14px;font-weight:600;">
                          View Your Orders →
                        </a>
                      </div>
                      
                      <!-- Footer -->
                      <div style="background:#f8fafc;padding:20px 32px;border-top:1px solid #e5e7eb;">
                        <p style="margin:0;color:#94a3b8;font-size:12px;">
                          © 2026 KasuMarketplace · 
                          <a href="mailto:support@kasumarketplace.com.ng" style="color:#64748b;text-decoration:none;">support@kasumarketplace.com.ng</a>
                        </p>
                      </div>
                      
                    </div>
                    """
                    
                    _send(subject=subject, message=plain, recipient_list=[obj.opened_by.email], html_message=html)
                    _send(subject=subject, message=plain, recipient_list=[obj.sub_order.store.vendor.user.email], html_message=html)
                    self.message_user(request, 'Note sent to buyer and vendor via email.', messages.INFO)
                except Exception as e:
                    self.message_user(request, f'Email failed: {e}', messages.WARNING)
        else:
            super().save_model(request, obj, form, change)

@admin.register(Promotion)
class PromotionAdmin(admin.ModelAdmin):
    list_display = ['title', 'is_active', 'sort_order']
    list_editable = ['is_active', 'sort_order']