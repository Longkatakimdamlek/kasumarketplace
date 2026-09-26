"""
Marketplace App Models
Handles buyer-side wishlist, reviews, product reports, and promotions.
"""

from django.db import models
from django.contrib.auth import get_user_model
from django.core.validators import MinValueValidator
from django.utils import timezone
from decimal import Decimal
import uuid
import random
from cloudinary.models import CloudinaryField

User = get_user_model()


# ==========================================
# PROMOTION
# ==========================================

class Promotion(models.Model):
    """Admin-managed promotional banner slides (e.g. 'Become a Vendor' call-outs)."""
    SLIDE_TYPE_CHOICES = [
        ('vendor_promo', 'Vendor Promo (Desktop Side Banner)'),
        ('hero_brand', 'Hero Brand Slide (Mobile)'),
        ('event_popup', 'Event/Campaign Popup'),
    ]

    title = models.CharField(max_length=200)
    subtitle = models.CharField(max_length=300, blank=True)
    image = CloudinaryField('image', blank=True, null=True)
    background_image = CloudinaryField(
        'background_image', blank=True, null=True,
        help_text="Full-width background image for hero_brand slides. "
                   "If set, displayed behind the text instead of the gradient."
    )
    slide_type = models.CharField(
        max_length=20,
        choices=SLIDE_TYPE_CHOICES,
        default='vendor_promo',
        help_text="Determines where this slide is rendered."
    )
    HERO_SLOT_CHOICES = [
        ('campus_essentials', 'Campus Essentials'),
        ('tech_electronics', 'Tech & Electronics'),
        ('fashion_accessories', 'Fashion & Accessories'),
        ('food_beverages', 'Food & Beverages'),
        ('deals_marketplace', 'Deals & Marketplace'),
        ('top_seller', 'Top Seller This Week'),
    ]
    hero_slot = models.CharField(
        max_length=30,
        choices=HERO_SLOT_CHOICES,
        blank=True,
        null=True,
        help_text="Which fixed hero slot this record overrides. Only used when slide_type=hero_brand."
    )
    link_url = models.CharField(max_length=300, help_text="Where this slide links to, e.g. /vendor-signup/")
    is_active = models.BooleanField(default=True)
    sort_order = models.PositiveIntegerField(default=0)
    start_date = models.DateTimeField(
        blank=True, null=True,
        help_text="Leave blank to start immediately"
    )
    end_date = models.DateTimeField(
        blank=True, null=True,
        help_text="Leave blank for no expiry"
    )
    frequency_minutes = models.PositiveIntegerField(
        default=1440,
        help_text="Minutes before this popup shows again after being dismissed. "
                  "E.g. 10 for 10 minutes, 1440 for 24 hours."
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['sort_order', '-created_at']

    def __str__(self):
        return self.title


# ==========================================
# WISHLIST
# ==========================================

class Wishlist(models.Model):
    """
    One row per buyer-saved product. Toggled on/off from product card or detail page.
    Supports both authenticated users (linked via user FK) and anonymous guests
    (linked via session_key). Quantity tracks how many of this product the buyer wants.
    """
    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='wishlist_items',
        null=True,
        blank=True,
        help_text="Set when user is authenticated"
    )
    session_key = models.CharField(
        max_length=40,
        blank=True,
        default='',
        help_text="Set for anonymous (guest) wishlists"
    )
    product = models.ForeignKey(
        'vendors.Product',
        on_delete=models.CASCADE,
        related_name='wishlisted_by'
    )
    quantity = models.PositiveIntegerField(
        default=1,
        validators=[MinValueValidator(1)]
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Wishlist Item"
        verbose_name_plural = "Wishlist Items"
        unique_together = [['user', 'product'], ['session_key', 'product']]
        ordering = ['-created_at']

    def __str__(self):
        owner = self.user.email if self.user else f"Session {self.session_key[:8]}"
        return f"{owner} - {self.product.title}"


# ==========================================
# REVIEW
# ==========================================

class Review(models.Model):
    """
    One review per buyer per product. Star-only submission still counts
    as a full review record - comment is optional.
    """
    RATING_CHOICES = [(i, str(i)) for i in range(1, 6)]

    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='reviews'
    )
    product = models.ForeignKey(
        'vendors.Product',
        on_delete=models.CASCADE,
        related_name='reviews'
    )
    rating = models.PositiveSmallIntegerField(choices=RATING_CHOICES)
    comment = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Review"
        verbose_name_plural = "Reviews"
        unique_together = [['user', 'product']]
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.product.title} - {self.rating} by {self.user.email}"


# ==========================================
# PRODUCT REPORTS
# ==========================================

class ProductReport(models.Model):
    """
    Buyer-initiated report against a product listing.
    Routed to admin moderation queue for review.
    """
    REASON_CHOICES = [
        ('counterfeit', 'Counterfeit / fake item'),
        ('prohibited', 'Prohibited or illegal item'),
        ('misleading', 'Misleading listing or description'),
        ('other', 'Other'),
    ]
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('reviewed', 'Under Review'),
        ('actioned', 'Actioned'),
        ('dismissed', 'Dismissed'),
    ]

    reporter = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='product_reports',
        help_text="Blank if report was submitted anonymously"
    )
    reporter_ip = models.GenericIPAddressField(
        null=True,
        blank=True,
        help_text="IP address of the reporter, used for rate-limiting anonymous reports"
    )
    product = models.ForeignKey(
        'vendors.Product',
        on_delete=models.CASCADE,
        related_name='reports'
    )
    reason = models.CharField(max_length=20, choices=REASON_CHOICES)
    details = models.TextField(blank=True, help_text="Optional additional context from the reporter")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    created_at = models.DateTimeField(auto_now_add=True)
    reviewed_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='reviewed_product_reports'
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "Product Report"
        verbose_name_plural = "Product Reports"
        ordering = ['-created_at']

    def __str__(self):
        reporter_email = self.reporter.email if self.reporter else 'Anonymous'
        return f"Report #{self.pk} — {self.product.title[:30]} by {reporter_email}"


# ==========================================
# PRODUCT VIEW TRACKING
# ==========================================

class ProductView(models.Model):
    """
    Tracks individual product views for buyer interest analytics.
    One row per view — created on each product_detail_public page load.
    """
    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='product_views',
        help_text="Set when user is authenticated"
    )
    session_key = models.CharField(
        max_length=40,
        blank=True,
        default='',
        help_text="Set for anonymous (guest) views"
    )
    product = models.ForeignKey(
        'vendors.Product',
        on_delete=models.CASCADE,
        related_name='product_views'
    )
    store = models.ForeignKey(
        'vendors.Store',
        on_delete=models.CASCADE,
        related_name='product_views'
    )
    viewed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Product View"
        verbose_name_plural = "Product Views"
        ordering = ['-viewed_at']
        indexes = [
            models.Index(fields=['user', 'product']),
            models.Index(fields=['product', 'viewed_at']),
        ]

    def __str__(self):
        owner = self.user.email if self.user else f"Session {self.session_key[:8]}"
        return f"{owner} viewed {self.product.title[:30]}"


# ==========================================
# CONTACT INTENT
# ==========================================

class ContactIntent(models.Model):
    """
    Tracks when a buyer clicks Call/WhatsApp on a product.
    Created via fire-and-forget endpoint before navigation.
    """
    CHANNEL_CHOICES = [
        ('call', 'Phone Call'),
        ('whatsapp', 'WhatsApp'),
    ]

    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='contact_intents',
        help_text="Set when user is authenticated"
    )
    session_key = models.CharField(
        max_length=40,
        blank=True,
        default='',
        help_text="Set for anonymous (guest) clicks"
    )
    product = models.ForeignKey(
        'vendors.Product',
        on_delete=models.CASCADE,
        related_name='contact_intents'
    )
    vendor = models.ForeignKey(
        'vendors.VendorProfile',
        on_delete=models.CASCADE,
        related_name='contact_intents'
    )
    channel = models.CharField(max_length=10, choices=CHANNEL_CHOICES)
    contacted_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Contact Intent"
        verbose_name_plural = "Contact Intents"
        ordering = ['-contacted_at']
        indexes = [
            models.Index(fields=['vendor', 'contacted_at']),
        ]

    def __str__(self):
        buyer = self.user.email if self.user else f"Session {self.session_key[:8]}"
        return f"{buyer} contacted {self.vendor} via {self.channel}"


# ==========================================
# REVIEW REPLY (VENDOR → BUYER)
# ==========================================

class ReviewReply(models.Model):
    """
    One reply per review — vendor's response to a buyer review.
    """
    review = models.OneToOneField(
        Review,
        on_delete=models.CASCADE,
        related_name='reply'
    )
    reply_text = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Review Reply"
        verbose_name_plural = "Review Replies"
        ordering = ['-created_at']

    def __str__(self):
        return f"Reply to review #{self.review.pk} by {self.review.product.store.store_name}"