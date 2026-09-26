"""
Quick Sell Models

Temporary marketplace listings created by registered users.
Separate from the vendor Product system — no VendorProfile, Store, or Subscription required.
"""

from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models
from django.utils import timezone
from django.utils.text import slugify
from decimal import Decimal
from cloudinary.models import CloudinaryField


# ==========================================
# QUICK SELL
# ==========================================

class QuickSellQuerySet(models.QuerySet):
    """Custom QuerySet for Quick Sell listings."""

    def active(self):
        """Non-expired listings visible to the public."""
        return self.filter(expires_at__gt=timezone.now())

    def expired(self):
        """Listings whose 10-day window has passed."""
        return self.filter(expires_at__lte=timezone.now())


class QuickSell(models.Model):
    """
    A temporary listing created by any registered user.
    No vendor profile, store, or subscription required.
    Expires exactly 10 days after creation.
    """

    QUICK_SELL_DURATION_DAYS = 10

    objects = QuickSellQuerySet.as_manager()

    # ── Ownership ──
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='quicksell_listings',
        help_text="Seller who created this listing"
    )

    # ── Category ──
    subcategory = models.ForeignKey(
        'vendors.SubCategory',
        on_delete=models.PROTECT,
        related_name='quicksell_listings'
    )

    # ── Basic Info ──
    title = models.CharField(max_length=200)
    slug = models.SlugField(unique=True, max_length=250)
    description = models.TextField()

    # ── Pricing ──
    price = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        validators=[MinValueValidator(Decimal('0.01'))]
    )
    compare_at_price = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Original price (for showing discounts)"
    )

    # ── Dynamic Specifications ──
    attributes = models.JSONField(
        default=dict,
        blank=True,
        help_text="Category-specific attributes (key = SubCategoryAttribute ID, value = attribute value)"
    )

    # ── Contact ──
    whatsapp = models.CharField(max_length=20, blank=True)
    phone = models.CharField(max_length=20, blank=True)

    # ── Video (optional, one per listing) ──
    video = CloudinaryField(
        'video',
        resource_type='video',
        null=True,
        blank=True,
        help_text="Optional product video (max ~60s recommended)"
    )

    # ── Stats ──
    views_count = models.PositiveIntegerField(default=0)

    # ── Timestamps ──
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    expires_at = models.DateTimeField(
        help_text="Listing expires exactly 10 days after creation"
    )

    class Meta:
        verbose_name = "Quick Sell Listing"
        verbose_name_plural = "Quick Sell Listings"
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['user', 'created_at']),
            models.Index(fields=['subcategory', 'created_at']),
            models.Index(fields=['expires_at']),
            models.Index(fields=['slug']),
        ]

    def __str__(self):
        return self.title

    def save(self, *args, **kwargs):
        # Generate slug if not exists
        if not self.slug:
            base_slug = slugify(self.title)
            slug = base_slug
            counter = 1
            while QuickSell.objects.filter(slug=slug).exists():
                slug = f"{base_slug}-{counter}"
                counter += 1
            self.slug = slug

        # Set expiration on first save (new listings only)
        if not self.pk and not self.expires_at:
            self.expires_at = timezone.now() + timezone.timedelta(days=self.QUICK_SELL_DURATION_DAYS)

        super().save(*args, **kwargs)

    @property
    def is_active(self):
        """Whether this listing is still publicly visible."""
        return self.expires_at > timezone.now()

    @property
    def days_remaining(self):
        """Days until expiration (0 if already expired)."""
        delta = self.expires_at - timezone.now()
        return max(0, delta.days)

    @property
    def main_category(self):
        """Derive the main category from the subcategory."""
        return self.subcategory.main_category

    def resolved_attributes(self):
        """
        Returns attributes with human-readable names instead of IDs.
        Single query — no N+1.
        Output format: [{"name": "Brand", "value": "Apple"}, ...]
        """
        if not self.attributes:
            return []

        from apps.vendors.models import SubCategoryAttribute

        attribute_ids = self.attributes.keys()

        attributes_qs = SubCategoryAttribute.objects.filter(
            id__in=attribute_ids,
            is_active=True
        )

        attributes_map = {
            str(attr.id): attr.name
            for attr in attributes_qs
        }

        resolved = []
        for attr_id, value in self.attributes.items():
            name = attributes_map.get(str(attr_id))
            if name:
                resolved.append({
                    "name": name,
                    "value": value,
                })

        return resolved


# ==========================================
# QUICK SELL IMAGE
# ==========================================

class QuickSellImage(models.Model):
    """
    Multiple images per Quick Sell listing.
    Follows the existing ProductImage conventions.
    """

    quicksell = models.ForeignKey(
        QuickSell,
        on_delete=models.CASCADE,
        related_name='images'
    )
    image = CloudinaryField('image')
    alt_text = models.CharField(max_length=200, blank=True)
    is_primary = models.BooleanField(default=False)
    sort_order = models.PositiveIntegerField(default=0)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Quick Sell Image"
        verbose_name_plural = "Quick Sell Images"
        ordering = ['sort_order', 'created_at']

    def __str__(self):
        return f"{self.quicksell.title} - Image {self.sort_order}"


# ==========================================
# QUICK SELL REPORT
# ==========================================

class QuickSellReport(models.Model):
    """
    Buyer-initiated report against a Quick Sell listing.
    Follows the existing ProductReport conventions.
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
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='quicksell_reports',
        help_text="Blank if report was submitted anonymously"
    )
    reporter_ip = models.GenericIPAddressField(
        null=True,
        blank=True,
        help_text="IP address of the reporter, used for rate-limiting anonymous reports"
    )
    quicksell = models.ForeignKey(
        QuickSell,
        on_delete=models.CASCADE,
        related_name='reports'
    )
    reason = models.CharField(max_length=20, choices=REASON_CHOICES)
    details = models.TextField(
        blank=True,
        help_text="Optional additional context from the reporter"
    )
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default='pending'
    )
    created_at = models.DateTimeField(auto_now_add=True)
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='reviewed_quicksell_reports'
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "Quick Sell Report"
        verbose_name_plural = "Quick Sell Reports"
        ordering = ['-created_at']

    def __str__(self):
        reporter_email = self.reporter.email if self.reporter else 'Anonymous'
        return f"Report #{self.pk} — {self.quicksell.title[:30]} by {reporter_email}"
