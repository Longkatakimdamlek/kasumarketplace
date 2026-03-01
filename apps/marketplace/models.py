"""
Marketplace App Models
Handles all buyer-side transactions:
Cart, Orders, Payments, Wallet Credits, Refunds, Disputes
"""

from django.db import models
from django.contrib.auth import get_user_model
from django.core.validators import MinValueValidator
from django.utils import timezone
from decimal import Decimal
import uuid
import random

User = get_user_model()


# ==========================================
# CART
# ==========================================

class Cart(models.Model):
    """
    Session-based cart — no login required to add items.
    One cart per session key. Merged with user cart on login.
    Multi-vendor: items grouped by store at checkout.
    """
    session_key = models.CharField(
        max_length=40,
        unique=True,
        help_text="Django session key"
    )
    user = models.OneToOneField(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='cart',
        help_text="Linked when user logs in"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Cart"
        verbose_name_plural = "Carts"

    def __str__(self):
        owner = self.user.email if self.user else f"Session {self.session_key[:8]}"
        return f"Cart — {owner}"

    @property
    def total_items(self):
        return sum(item.quantity for item in self.items.all())

    @property
    def grand_total(self):
        return sum(item.subtotal for item in self.items.all())

    @property
    def is_empty(self):
        return not self.items.exists()

    def get_items_by_store(self):
        """
        Returns cart items grouped by store.
        Used at checkout to split into SubOrders.
        Returns: {store_instance: [CartItem, ...]}
        """
        grouped = {}
        for item in self.items.select_related('product__store'):
            store = item.product.store
            if store not in grouped:
                grouped[store] = []
            grouped[store].append(item)
        return grouped


class CartItem(models.Model):
    """
    One product line in a cart.
    Price is read live from Product.
    Price snapshot happens at order creation — not here.
    """
    cart = models.ForeignKey(
        Cart,
        on_delete=models.CASCADE,
        related_name='items'
    )
    product = models.ForeignKey(
        'vendors.Product',
        on_delete=models.CASCADE,
        related_name='cart_items'
    )
    quantity = models.PositiveIntegerField(
        default=1,
        validators=[MinValueValidator(1)]
    )
    added_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Cart Item"
        verbose_name_plural = "Cart Items"
        unique_together = [['cart', 'product']]

    def __str__(self):
        return f"{self.product.title} x{self.quantity}"

    @property
    def unit_price(self):
        return self.product.price

    @property
    def subtotal(self):
        return self.unit_price * Decimal(self.quantity)


# ==========================================
# PAYMENT TRANSACTION
# ==========================================

class PaymentTransaction(models.Model):
    """
    Records every Paystack payment attempt.
    IDEMPOTENCY: reference field is UNIQUE.
    Duplicate verify calls return existing record — no duplicate orders.
    """
    STATUS_CHOICES = [
        ('PENDING', 'Pending'),
        ('SUCCESS', 'Success'),
        ('FAILED', 'Failed'),
        ('REFUNDED', 'Refunded'),
    ]

    reference = models.CharField(
        max_length=100,
        unique=True,
        help_text="Paystack transaction reference"
    )
    user = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        related_name='payment_transactions'
    )
    # Stored in Naira — converted to kobo only when calling Paystack API
    amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        help_text="Amount in Naira"
    )
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default='PENDING'
    )
    # Full Paystack API response stored for audit/dispute evidence
    paystack_response = models.JSONField(
        default=dict,
        blank=True
    )
    # Prevents duplicate webhook processing
    webhook_processed = models.BooleanField(default=False)

    created_at = models.DateTimeField(auto_now_add=True)
    verified_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "Payment Transaction"
        verbose_name_plural = "Payment Transactions"
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.reference} — ₦{self.amount} — {self.status}"


# ==========================================
# MAIN ORDER
# ==========================================

class MainOrder(models.Model):
    """
    One per buyer checkout session.
    Groups all SubOrders from one payment.
    Created ONLY after Paystack server-side verification succeeds.
    """
    PAYMENT_STATUS_CHOICES = [
        ('PENDING', 'Pending'),
        ('SUCCESS', 'Success'),
        ('FAILED', 'Failed'),
        ('REFUNDED', 'Refunded'),
    ]

    order_number = models.CharField(
        max_length=25,
        unique=True,
        editable=False,
        help_text="Human-readable: KSM-20240101-4823"
    )
    reference = models.CharField(
        max_length=100,
        unique=True,
        help_text="Paystack reference — matches PaymentTransaction"
    )
    buyer = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        related_name='main_orders'
    )
    # Grand total in Naira — must equal sum of all SubOrder subtotals
    total = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        help_text="Grand total in Naira"
    )
    payment_status = models.CharField(
        max_length=20,
        choices=PAYMENT_STATUS_CHOICES,
        default='PENDING'
    )
    # Address snapshot at checkout — buyer profile changes won't affect this
    delivery_address = models.TextField()
    delivery_city = models.CharField(max_length=100, blank=True)
    delivery_state = models.CharField(max_length=100, blank=True)
    delivery_phone = models.CharField(max_length=20, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Main Order"
        verbose_name_plural = "Main Orders"
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.order_number} — ₦{self.total} — {self.payment_status}"

    def save(self, *args, **kwargs):
        if not self.order_number:
            self.order_number = self._generate_order_number()
        super().save(*args, **kwargs)

    def _generate_order_number(self):
        date_str = timezone.now().strftime('%Y%m%d')
        suffix = str(random.randint(1000, 9999))
        return f"KSM-{date_str}-{suffix}"

    def verify_total(self):
        """
        Sanity check: MainOrder.total must equal sum of SubOrder subtotals.
        Called after atomic order creation.
        """
        calculated = sum(sub.subtotal for sub in self.suborders.all())
        return calculated == self.total

    @property
    def suborder_count(self):
        return self.suborders.count()


# ==========================================
# SUB ORDER
# ==========================================

class SubOrder(models.Model):
    """
    One per store within a MainOrder.
    Has its own status lifecycle.
    Credits its vendor's wallet independently.
    Can be refunded independently.
    """
    STATUS_CHOICES = [
        ('PENDING_VENDOR', 'Pending Vendor'),
        ('ACCEPTED', 'Accepted'),
        ('REJECTED', 'Rejected'),
        ('CANCELLED', 'Cancelled'),
        ('CONFIRMED', 'Confirmed'),
        ('DISPUTED', 'Disputed'),
        ('REFUNDED', 'Refunded'),
    ]
    PAYMENT_STATUS_CHOICES = [
        ('PENDING', 'Pending'),
        ('SUCCESS', 'Success'),
        ('REFUNDED', 'Refunded'),
    ]

    main_order = models.ForeignKey(
        MainOrder,
        on_delete=models.CASCADE,
        related_name='suborders'
    )
    store = models.ForeignKey(
        'vendors.Store',
        on_delete=models.PROTECT,
        related_name='suborders'
    )
    subtotal = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        help_text="Sum of all items for this store (Naira)"
    )
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default='PENDING_VENDOR'
    )
    payment_status = models.CharField(
        max_length=20,
        choices=PAYMENT_STATUS_CHOICES,
        default='PENDING'
    )
    # 48-hour vendor action window — checked lazily (no Celery needed)
    vendor_deadline = models.DateTimeField(
        help_text="Auto-cancel if vendor doesn't act before this"
    )
    # Set when buyer clicks YES — Release Payment
    confirmed_at = models.DateTimeField(null=True, blank=True)
    rejection_reason = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Sub Order"
        verbose_name_plural = "Sub Orders"
        ordering = ['-created_at']

    def __str__(self):
        return f"SubOrder #{self.pk} — {self.store.store_name} — {self.status}"

    def save(self, *args, **kwargs):
        if not self.pk and not self.vendor_deadline:
            from datetime import timedelta
            self.vendor_deadline = timezone.now() + timedelta(hours=48)
        super().save(*args, **kwargs)

    @property
    def is_vendor_deadline_passed(self):
        return timezone.now() > self.vendor_deadline

    @property
    def buyer_can_see_vendor_contact(self):
        """
        Buyer sees store contact (phone, WhatsApp, address)
        as soon as payment_status is SUCCESS.
        """
        return self.payment_status == 'SUCCESS'

    @property
    def vendor_can_see_buyer_contact(self):
        """
        Vendor sees buyer contact only after explicitly accepting.
        """
        return self.status == 'ACCEPTED'

    def check_and_apply_timeout(self):
        """
        Called when SubOrder is accessed.
        If deadline passed and still PENDING_VENDOR — auto cancel.
        No Celery needed — lazy evaluation.
        """
        if (
            self.status == 'PENDING_VENDOR'
            and self.is_vendor_deadline_passed
        ):
            self.status = 'CANCELLED'
            self.save(update_fields=['status', 'updated_at'])
            return True
        return False


# ==========================================
# SUB ORDER ITEM
# ==========================================

class SubOrderItem(models.Model):
    """
    Price snapshot of each product at time of order.
    Product price may change later — this preserves what buyer paid.
    """
    sub_order = models.ForeignKey(
        SubOrder,
        on_delete=models.CASCADE,
        related_name='items'
    )
    product = models.ForeignKey(
        'vendors.Product',
        on_delete=models.PROTECT,
        related_name='order_items'
    )
    # Snapshot fields — frozen at order creation
    product_title = models.CharField(
        max_length=200,
        help_text="Product title at time of order"
    )
    unit_price = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        help_text="Price per unit at time of order (Naira)"
    )
    quantity = models.PositiveIntegerField(default=1)
    subtotal = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        help_text="unit_price × quantity"
    )

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Sub Order Item"
        verbose_name_plural = "Sub Order Items"

    def __str__(self):
        return f"{self.product_title} x{self.quantity} — ₦{self.subtotal}"

    def save(self, *args, **kwargs):
        # Auto-calculate subtotal
        self.subtotal = self.unit_price * Decimal(self.quantity)
        super().save(*args, **kwargs)


# ==========================================
# WALLET TRANSACTION
# ==========================================

class WalletTransaction(models.Model):
    """
    Tracks every credit/debit to a vendor wallet from marketplace orders.
    IDEMPOTENCY: unique_together on (reference, sub_order) prevents
    duplicate credits if payment verify is called twice.
    """
    TRANSACTION_TYPE_CHOICES = [
        ('PENDING_CREDIT', 'Pending Credit'),    # After payment success
        ('AVAILABLE_CREDIT', 'Available Credit'), # After buyer confirms + 24h
        ('REVERSAL', 'Reversal'),                 # After refund
    ]
    STATUS_CHOICES = [
        ('PENDING', 'Pending'),
        ('AVAILABLE', 'Available'),
        ('REVERSED', 'Reversed'),
    ]

    wallet = models.ForeignKey(
        'vendors.Wallet',
        on_delete=models.CASCADE,
        related_name='marketplace_transactions'
    )
    sub_order = models.ForeignKey(
        SubOrder,
        on_delete=models.CASCADE,
        related_name='wallet_transactions'
    )
    transaction_type = models.CharField(
        max_length=20,
        choices=TRANSACTION_TYPE_CHOICES
    )
    amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        help_text="Amount in Naira"
    )
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default='PENDING'
    )
    # reference = MainOrder.reference for idempotency check
    reference = models.CharField(max_length=100)
    note = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Wallet Transaction"
        verbose_name_plural = "Wallet Transactions"
        ordering = ['-created_at']
        # Prevents duplicate wallet credits for same order
        unique_together = [['reference', 'sub_order']]

    def __str__(self):
        return f"{self.transaction_type} — ₦{self.amount} — {self.status}"


# ==========================================
# REFUND RECORD
# ==========================================

class RefundRecord(models.Model):
    """
    Tracks every refund attempt per SubOrder.
    IDEMPOTENCY: one RefundRecord per SubOrder max (unique on sub_order).
    Prevents duplicate Paystack refund API calls.
    """
    STATUS_CHOICES = [
        ('PROCESSING', 'Processing'),
        ('COMPLETED', 'Completed'),
        ('FAILED', 'Failed'),
    ]
    REASON_CHOICES = [
        ('VENDOR_REJECTED', 'Vendor Rejected Order'),
        ('VENDOR_TIMEOUT', 'Vendor Did Not Respond (48h)'),
        ('DISPUTE_RESOLVED', 'Dispute Resolved in Buyer Favour'),
        ('ADMIN_MANUAL', 'Admin Manual Refund'),
    ]

    # One refund per SubOrder maximum
    sub_order = models.OneToOneField(
        SubOrder,
        on_delete=models.CASCADE,
        related_name='refund_record'
    )
    reason = models.CharField(max_length=30, choices=REASON_CHOICES)
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default='PROCESSING'
    )
    amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        help_text="Refund amount in Naira"
    )
    # Paystack refund response
    paystack_response = models.JSONField(default=dict, blank=True)
    note = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "Refund Record"
        verbose_name_plural = "Refund Records"
        ordering = ['-created_at']

    def __str__(self):
        return f"Refund — SubOrder #{self.sub_order.pk} — {self.status}"


# ==========================================
# DISPUTE
# ==========================================

class Dispute(models.Model):
    """
    Created when buyer clicks REPORT ISSUE on a confirmed/accepted order.
    Funds remain PENDING (locked) until admin resolves.
    Admin resolves via Django Admin only (no custom UI for MVP).
    """
    STATUS_CHOICES = [
        ('OPEN', 'Open'),
        ('UNDER_REVIEW', 'Under Review'),
        ('RESOLVED_RELEASE', 'Resolved — Funds Released to Vendor'),
        ('RESOLVED_REFUND', 'Resolved — Buyer Refunded'),
        ('CLOSED', 'Closed'),
    ]

    sub_order = models.OneToOneField(
        SubOrder,
        on_delete=models.CASCADE,
        related_name='dispute'
    )
    opened_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        related_name='disputes_opened'
    )
    reason = models.TextField(
        help_text="Buyer's description of the issue"
    )
    status = models.CharField(
        max_length=30,
        choices=STATUS_CHOICES,
        default='OPEN'
    )
    # Admin resolution
    admin_note = models.TextField(blank=True)
    resolved_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='disputes_resolved'
    )
    resolved_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Dispute"
        verbose_name_plural = "Disputes"
        ordering = ['-created_at']

    def __str__(self):
        return f"Dispute — SubOrder #{self.sub_order.pk} — {self.status}"