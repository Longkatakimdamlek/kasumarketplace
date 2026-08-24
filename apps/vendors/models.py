"""
Vendor App Models
Complete database schema for vendor verification, store management, products, orders, wallet, etc.
"""

from django.db import models
from django.contrib.auth import get_user_model
from django.conf import settings
from cloudinary.models import CloudinaryField
from django.core.validators import MinValueValidator, MaxValueValidator, RegexValidator
from django.utils.text import slugify
from django.urls import reverse
from django.utils import timezone
from decimal import Decimal
from difflib import SequenceMatcher
import logging
import uuid

logger = logging.getLogger(__name__)

User = get_user_model()


# ==========================================
# VENDOR PROFILE & VERIFICATION
# ==========================================

"""
VendorProfile — complete replacement class.

Paste this in place of the ENTIRE existing `class VendorProfile(models.Model):`
block in apps/vendors/models.py — from "class VendorProfile(models.Model):"
down to (but not including) the next class definition ("class VerificationAttempt...").

Requires at the top of models.py (add if not already present):
    import logging
    logger = logging.getLogger(__name__)
"""

class VendorProfile(models.Model):
    """
    Main vendor profile - linked to User model
    Tracks verification status and personal information

    Identity verification: BVN + live selfie only (no OTP).
    Dojah's /api/v1/kyc/bvn/verify returns identity fields + a
    selfie_verification.confidence_value in one call. We use the confidence
    score (not Dojah's own coarse match boolean) to drive a 3-tier outcome:
    auto-verify, pending admin review, or fail. See views.bvn_verification.
    """

    # Verification Status Choices (overall vendor approval, unchanged)
    VERIFICATION_STATUS_CHOICES = [
        ('pending', 'Pending Verification'),
        ('bvn_verified', 'BVN Verified'),
        ('student_verified', 'Student Verified'),
        ('approved', 'Approved'),
        ('rejected', 'Rejected'),
        ('suspended', 'Suspended'),
    ]

    # Bank/identity verification status — single source of truth now.
    # 'verified'        = auto-verified, confidence >= DOJAH_SELFIE_AUTO_VERIFY_THRESHOLD
    # 'pending_review'  = borderline confidence, awaiting admin approve/reject
    # 'failed'          = confidence too low, or admin rejected after review
    BANK_STATUS_CHOICES = [
        ('not_started', 'Not Started'),
        ('verified', 'Verified'),
        ('pending_review', 'Pending Admin Review'),
        ('failed', 'Failed'),
    ]

    STUDENT_STATUS_CHOICES = [
        ('not_applicable', 'Not a Student'),
        ('not_started', 'Not Started'),
        ('pending', 'Pending Review'),
        ('verified', 'Verified'),
        ('rejected', 'Rejected'),
    ]

    GENDER_CHOICES = [
        ('male', 'Male'),
        ('female', 'Female'),
        ('other', 'Other'),
    ]

    # ==========================================
    # Basic Info
    # ==========================================
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='vendorprofile')
    vendor_id = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)

    # ==========================================
    # Personal Information (auto-filled from BVN response, immutable once verified)
    # ==========================================
    full_name = models.CharField(max_length=200, blank=True)
    phone = models.CharField(
        max_length=20,
        blank=True,
        help_text="From BVN phone_number1. Admin-only — masked to vendor via get_masked_phone()."
    )
    gender = models.CharField(max_length=10, choices=GENDER_CHOICES, blank=True)
    dob = models.DateField(null=True, blank=True, verbose_name="Date of Birth")
    calculated_age = models.PositiveIntegerField(
        null=True, blank=True,
        help_text="Vendor's age calculated from DOB at time of verification"
    )
    is_underage = models.BooleanField(
        default=False,
        help_text="True if vendor is under 18 years old"
    )

    # NOTE: address / state / lga intentionally NOT here.
    # BVN does not return these fields. They are collected on the Store model
    # during store setup instead.

    # ==========================================
    # BVN Data — sole identity verification method
    # ==========================================
    bvn_number = models.CharField(
        max_length=11,
        blank=True,
        validators=[RegexValidator(r'^\d{11}$', 'BVN must be 11 digits')],
        verbose_name="BVN",
        help_text="Cleared after successful verification — never retained long-term."
    )

    # ==========================================
    # BVN Consent
    # ==========================================
    bvn_consent_given = models.BooleanField(
        default=False,
        help_text="Vendor consented to BVN collection and submission to Dojah for identity verification."
    )
    bvn_consent_timestamp = models.DateTimeField(
        null=True, blank=True,
        help_text="Timestamp when BVN collection consent was given."
    )

    # ==========================================
    # Selfie verification results (immutable once bank_status == 'verified')
    # ==========================================
    identity_selfie = CloudinaryField(
        'identity_selfie',
        blank=True,
        null=True,
        help_text="Live selfie captured during BVN identity verification. "
                   "Separate from `selfie` (student verification photo) — never overwrite that field."
    )
    selfie_match = models.BooleanField(
        null=True,
        blank=True,
        help_text="Dojah's own match result (true/false, hardcoded 90% cutoff). "
                   "Business logic uses selfie_confidence directly, not this field."
    )
    selfie_confidence = models.DecimalField(
        max_digits=6,
        decimal_places=3,
        null=True,
        blank=True,
        help_text="Dojah confidence_value, 0-100. Drives the 3-tier verification outcome."
    )
    selfie_image_url = models.URLField(
        blank=True,
        help_text="Dojah-hosted reference copy of the selfie (selfie_image_url from API response)"
    )

    # ==========================================
    # Student Information (Optional) — UNCHANGED, separate from identity verification
    # ==========================================
    matric_number = models.CharField(max_length=50, blank=True)
    department = models.CharField(max_length=100, blank=True)
    level = models.CharField(max_length=20, blank=True)
    student_id_image = CloudinaryField('student_id_image', blank=True, null=True)
    selfie = CloudinaryField(
        'selfie', blank=True, null=True,
        help_text="Student verification selfie. NOT the same field as identity_selfie."
    )

    # ==========================================
    # Verification Status
    # ==========================================
    verification_status = models.CharField(
        max_length=20,
        choices=VERIFICATION_STATUS_CHOICES,
        default='pending'
    )
    bank_status = models.CharField(
        max_length=20,
        choices=BANK_STATUS_CHOICES,
        default='not_started'
    )
    student_status = models.CharField(
        max_length=20,
        choices=STUDENT_STATUS_CHOICES,
        default='not_applicable'
    )

    # ==========================================
    # Store Setup Progress
    # ==========================================
    store_setup_completed = models.BooleanField(default=False)
    store_setup_skipped = models.BooleanField(default=False)

    # ==========================================
    # Admin Review
    # ==========================================
    admin_comment = models.TextField(blank=True, help_text="Admin notes on verification")
    reviewed_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='reviewed_vendors'
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)

    # ==========================================
    # Verification Timestamps
    # ==========================================
    bvn_verified_at = models.DateTimeField(null=True, blank=True)
    student_verified_at = models.DateTimeField(null=True, blank=True)
    approved_at = models.DateTimeField(null=True, blank=True)

    # ==========================================
    # Progress Tracking
    # ==========================================
    verification_progress = models.JSONField(
        default=dict,
        blank=True,
        help_text="Tracks current step, timestamps, attempts"
    )

    # ==========================================
    # IP Tracking
    # ==========================================
    registration_ip = models.GenericIPAddressField(
        null=True, blank=True,
        help_text="IP address used during registration"
    )
    bvn_verification_ip = models.GenericIPAddressField(
        null=True, blank=True,
        help_text="IP address used during BVN verification"
    )

    # ==========================================
    # Alert Flags (for admin monitoring)
    # ==========================================
    has_duplicate_bvn = models.BooleanField(
        default=False,
        help_text="True if BVN exists on another account"
    )
    duplicate_bvn_vendor_id = models.CharField(
        max_length=100,
        blank=True,
        help_text="Vendor ID of account with same BVN"
    )

    admin_internal_notes = models.TextField(
        blank=True,
        help_text="Private notes visible only to admins (not shown to vendor)"
    )

    risk_score = models.IntegerField(
        default=0,
        validators=[MinValueValidator(0), MaxValueValidator(100)],
        help_text="Automated risk assessment score (0-100, higher = riskier)"
    )

    # ==========================================
    # Timestamps
    # ==========================================
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Vendor Profile"
        verbose_name_plural = "Vendor Profiles"
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.full_name or self.user.email} - {self.verification_status}"

    # ==========================================
    # Properties
    # ==========================================

    @property
    def is_verified(self):
        """Check if vendor is fully verified and approved"""
        return self.verification_status == 'approved'

    @property
    def can_sell(self):
        """Check if vendor can list products (BVN+selfie verified)"""
        return self.bank_status == 'verified'

    @property
    def current_step(self):
        """Calculate which verification step user should see next"""
        if self.bank_status == 'pending_review':
            return 'pending_review'

        if self.bank_status != 'verified':
            return 'bvn_verification'

        if not self.store_setup_completed and not self.store_setup_skipped:
            return 'store_setup'

        if self.student_status == 'not_started':
            return 'student_verification'

        return 'admin_review'

    @property
    def completion_percentage(self):
        """Calculate verification progress (0-100). 4 total steps."""
        total_steps = 4
        completed = 0

        if self.bank_status == 'verified':
            completed += 1
        elif self.bank_status == 'pending_review':
            completed += 0.5

        if self.store_setup_completed or self.store_setup_skipped:
            completed += 1

        if self.student_status == 'verified':
            completed += 1

        if self.verification_status == 'approved':
            completed += 1

        return int((completed / total_steps) * 100)

    @property
    def age(self):
        """Calculate current age from DOB"""
        if not self.dob:
            return None

        from datetime import date
        today = date.today()
        age = today.year - self.dob.year - (
            (today.month, today.day) < (self.dob.month, self.dob.day)
        )
        return age

    def get_absolute_url(self):
        return reverse('vendors:dashboard')

    # ==========================================
    # Risk assessment
    # ==========================================

    def calculate_risk_score(self):
        """Calculate automated risk score based on flags"""
        score = 0

        if self.has_duplicate_bvn:
            score += 50
        if self.is_underage:
            score += 100  # Critical - should not allow selling
        if self.bank_status == 'pending_review':
            score += 20  # borderline selfie matches get a small bump for admin visibility

        self.risk_score = min(score, 100)
        return self.risk_score

    # ==========================================
    # Masking helpers (admin-only data hidden from vendor view)
    # ==========================================

    def get_masked_bvn(self):
        """Return masked BVN for vendor view"""
        if not self.bvn_number or len(self.bvn_number) < 11:
            return "***-****-****"
        return f"***-****-{self.bvn_number[-4:]}"

    def get_masked_phone(self):
        """Return masked phone for vendor view — admin-only field, full BVN-sourced number hidden"""
        if not self.phone or len(self.phone) < 4:
            return "***-***-****"
        return f"***-***-{self.phone[-4:]}"

    # ==========================================
    # Immutability enforcement
    # ==========================================

    def save(self, *args, **kwargs):
        """
        Once bank_status == 'verified', the identity fields below become
        permanently locked. Any attempt to change them through this model
        (including via admin) is silently reverted and logged as a warning.
        This is enforced here, not just hidden from forms, so it can't be
        bypassed by editing the DB through any other code path that still
        calls .save().
        """
        if self.pk:
            original = VendorProfile.objects.filter(pk=self.pk).values(
                'bank_status', 'full_name', 'gender', 'dob',
                'selfie_match', 'selfie_confidence'
            ).first()

            if original and original['bank_status'] == 'verified':
                locked_fields = [
                    'full_name', 'gender', 'dob',
                    'selfie_match', 'selfie_confidence'
                ]
                for field in locked_fields:
                    if getattr(self, field) != original[field]:
                        logger.warning(
                            f"🚫 BLOCKED: Attempted to modify locked field '{field}' "
                            f"on verified VendorProfile {self.pk}"
                        )
                        setattr(self, field, original[field])

        super().save(*args, **kwargs)
        


class PendingReviewVendor(VendorProfile):
    """
    Proxy model — same DB table as VendorProfile, filtered to
    bank_status='pending_review' in the admin queryset.
    Gives the review queue its own Django admin menu entry and
    its own ModelAdmin class (PendingReviewAdmin in admin.py)
    without touching VendorProfile's admin at all.
    """
    class Meta:
        proxy = True
        verbose_name        = 'Pending Verification Review'
        verbose_name_plural = 'Pending Verification Reviews'


class VerificationAttempt(models.Model):
    """
    Audit log for verification attempts (BVN, Student, OTP)
    Tracks all API calls and responses for compliance
    """
    
    ATTEMPT_TYPE_CHOICES = [
        ('bvn', 'BVN Verification'),
        ('student', 'Student Verification'),
        ('otp', 'OTP Verification'),
    ]
    
    STATUS_CHOICES = [
        ('started', 'Started'),
        ('success', 'Success'),
        ('failed', 'Failed'),
        ('expired', 'Expired'),
    ]
    
    vendor = models.ForeignKey(VendorProfile, on_delete=models.CASCADE, related_name='verification_attempts')
    attempt_type = models.CharField(max_length=20, choices=ATTEMPT_TYPE_CHOICES)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES)
    
    # Response Data (sanitized - no full BVN stored)
    request_data = models.JSONField(default=dict, blank=True)
    response_data = models.JSONField(default=dict, blank=True)
    error_message = models.TextField(blank=True)
    
    # Metadata
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        verbose_name = "Verification Attempt"
        verbose_name_plural = "Verification Attempts"
        ordering = ['-created_at']
    
    def __str__(self):
        return f"{self.vendor.full_name} - {self.attempt_type} - {self.status}"


# ==========================================
# CATEGORIES & STORE
# ==========================================

class MainCategory(models.Model):
    """
    Main category groups (admin-managed)
    Examples: Fashion & Accessories, Tech & Electronics, Food & Beverages
    Vendors select ONE main category (locked after confirmation)
    """
    name = models.CharField(max_length=100, unique=True)
    slug = models.SlugField(unique=True)
    description = models.TextField(blank=True, help_text="What this category includes")
    icon = models.CharField(
        max_length=50,
        blank=True,
        default='package',
        help_text="Lucide icon name (for example: 'laptop', 'shirt', or 'package')",
    )
    is_active = models.BooleanField(default=True)
    sort_order = models.PositiveIntegerField(default=0)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        verbose_name = "Main Category"
        verbose_name_plural = "Main Categories"
        ordering = ['sort_order', 'name']
    
    def __str__(self):
        return self.name
    
    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)
        super().save(*args, **kwargs)


class SubCategory(models.Model):
    """
    Subcategories under each main category (admin-managed)
    Examples: Clothes, Shoes (under Fashion), Phones, Laptops (under Tech)
    Vendors automatically get access to ALL subcategories under their main category
    """
    main_category = models.ForeignKey(
        MainCategory, 
        on_delete=models.CASCADE, 
        related_name='subcategories'
    )
    name = models.CharField(max_length=100)
    slug = models.SlugField()
    description = models.TextField(blank=True)
    icon = models.CharField(max_length=50, blank=True)
    is_active = models.BooleanField(default=True)
    sort_order = models.PositiveIntegerField(default=0)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        verbose_name = "Sub Category"
        verbose_name_plural = "Sub Categories"
        ordering = ['main_category', 'sort_order', 'name']
        unique_together = [['main_category', 'name']]  # Unique within main category
    
    def __str__(self):
        return f"{self.main_category.name} → {self.name}"
    
    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)
        super().save(*args, **kwargs)


class SubCategoryAttribute(models.Model):
    """
    Defines dynamic attributes/fields for each subcategory
    Admin creates these once, product forms use them dynamically
    
    Examples:
    - Subcategory: Laptops → Attributes: Brand, Processor, RAM, Storage, Screen Size
    - Subcategory: Shoes → Attributes: Size, Color, Material, Brand
    - Subcategory: Barbing (Service) → Attributes: Duration, Availability, Service Area
    """
    
    FIELD_TYPE_CHOICES = [
        ('text', 'Text Input'),
        ('number', 'Number Input'),
        ('dropdown', 'Dropdown Select'),
        ('checkbox', 'Checkbox'),
        ('textarea', 'Text Area'),
        ('radio', 'Radio Buttons'),
    ]
    
    subcategory = models.ForeignKey(
        SubCategory, 
        on_delete=models.CASCADE, 
        related_name='attributes'
    )
    
    # Attribute Definition
    name = models.CharField(
        max_length=100,
        help_text="Attribute name (e.g., 'Brand', 'Size', 'RAM')"
    )
    field_type = models.CharField(
        max_length=20,
        choices=FIELD_TYPE_CHOICES,
        default='text'
    )
    
    # For dropdown/radio options (stored as JSON list)
    options = models.JSONField(
        default=list, 
        blank=True,
        help_text="Dropdown/radio options as list (e.g., ['New', 'Used', 'Refurbished'])"
    )
    
    # Validation
    is_required = models.BooleanField(default=False)
    min_value = models.IntegerField(null=True, blank=True, help_text="Min value for number fields")
    max_value = models.IntegerField(null=True, blank=True, help_text="Max value for number fields")
    
    # UI Helpers
    placeholder = models.CharField(max_length=200, blank=True, help_text="Placeholder text")
    help_text = models.CharField(max_length=300, blank=True, help_text="Help text shown to vendor")
    
    # Ordering
    sort_order = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        verbose_name = "SubCategory Attribute"
        verbose_name_plural = "SubCategory Attributes"
        ordering = ['subcategory', 'sort_order', 'name']
        unique_together = [['subcategory', 'name']]  # Unique attribute name per subcategory
    
    def __str__(self):
        return f"{self.subcategory.name} → {self.name} ({self.field_type})"



class Store(models.Model):
    """
    Vendor storefront - one per vendor
    Public-facing store with branding
    """
    vendor = models.OneToOneField(VendorProfile, on_delete=models.CASCADE, related_name='store')
    
    # Store Info
    store_name = models.CharField(max_length=100, help_text="Store name (locked after confirmation)")
    slug = models.SlugField(unique=True)
    tagline = models.CharField(max_length=150, blank=True, help_text="Short description (e.g., 'Trendy fashion for students')")
    description = models.TextField(max_length=1000, blank=True)
    
    # Main Category (vendor picks ONE - LOCKED after confirmation)
    main_category = models.ForeignKey(
        MainCategory, 
        on_delete=models.PROTECT, 
        related_name='stores',
        help_text="Main category (LOCKED after confirmation - change requires admin approval)"
    )
    main_category_locked = models.BooleanField(
        default=False, 
        help_text="Once locked, vendor cannot change without admin approval"
    )
    main_category_locked_at = models.DateTimeField(null=True, blank=True)
    
    # Branding
    logo = CloudinaryField('logo', blank=True, null=True, help_text="Recommended: 400x400px, max 5MB")
    banner = CloudinaryField('banner', blank=True, null=True, help_text="Recommended: 1200x350px, max 8MB")
    primary_color = models.CharField(max_length=7, blank=True, help_text="Hex color code (e.g., #FF5733)")
    
    # Contact Info (Public)
    # Location Coordinates (for buyer distance calculation)
    latitude = models.DecimalField(
        max_digits=9,
        decimal_places=6,
        null=True,
        blank=True,
        help_text="Store latitude (set by vendor in store settings)"
    )
    longitude = models.DecimalField(
        max_digits=9,
        decimal_places=6,
        null=True,
        blank=True,
        help_text="Store longitude (set by vendor in store settings)"
    )
    
    business_email = models.EmailField(blank=True)
    phone = models.CharField(max_length=20, blank=True)
    whatsapp = models.CharField(max_length=20, blank=True, help_text="WhatsApp number for quick contact")
    address = models.TextField(blank=True, help_text="Pickup location or delivery address")
    
    # Social Links (Public)
    instagram = models.URLField(blank=True)
    facebook = models.URLField(blank=True)
    twitter = models.URLField(blank=True)
    
    # Policies
    shipping_policy = models.TextField(blank=True, help_text="Shipping/delivery policy")
    return_policy = models.TextField(blank=True, help_text="Return/refund policy")
    
    # Settings
    is_published = models.BooleanField(default=False, help_text="Make store visible to public")
    allow_reviews = models.BooleanField(default=True)
    
    is_sponsored = models.BooleanField(
        default=False,
        help_text="Manually promoted store — takes priority over auto-ranked top sellers"
    )
    sponsored_until = models.DateTimeField(
        null=True, blank=True,
        help_text="Optional expiry — sponsorship auto-drops after this date if set"
    )

    # Stats (updated via signals)
    total_products = models.PositiveIntegerField(default=0)
    total_orders = models.PositiveIntegerField(default=0)
    total_sales = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    average_rating = models.DecimalField(max_digits=3, decimal_places=2, default=0)
    
    # SEO
    meta_title = models.CharField(max_length=70, blank=True)
    meta_description = models.CharField(max_length=160, blank=True)
    
    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        verbose_name = "Store"
        verbose_name_plural = "Stores"
        ordering = ['-created_at']
    
    def __str__(self):
        return self.store_name
    
    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.store_name)
        
        # Track original values on first save
        if not self.pk:
            self.original_store_name = self.store_name
            self.original_main_category = self.main_category
        
        super().save(*args, **kwargs)
    
    def get_absolute_url(self):
        return reverse('vendors:store_public', kwargs={'slug': self.slug})
    
    def lock_main_category(self):
        """Lock main category (call this after vendor confirms)"""
        if not self.main_category_locked:
            self.main_category_locked = True
            self.main_category_locked_at = timezone.now()
            self.save(update_fields=['main_category_locked', 'main_category_locked_at'])

    # Store Name Change Tracking
    store_name_last_changed_at = models.DateTimeField(
        null=True, blank=True,
        help_text="Last time store name was changed"
    )
    store_name_change_count = models.PositiveIntegerField(
        default=0,
        help_text="Number of times store name has been changed"
    )
    original_store_name = models.CharField(
        max_length=100,
        blank=True,
        help_text="Original store name for tracking"
    )
    
    # Main Category Change Tracking (already have lock, but add last change)
    main_category_last_changed_at = models.DateTimeField(
        null=True, blank=True,
        help_text="Last time main category was changed (via admin approval)"
    )
    main_category_change_count = models.PositiveIntegerField(
        default=0,
        help_text="Number of times main category has been changed"
    )
    original_main_category = models.ForeignKey(
        MainCategory,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='original_stores',
        help_text="Original main category for tracking"
    )
    
    # ✅ ADD METHOD to check if changes are allowed
    def can_change_store_name(self) -> bool:
        """Check if vendor can change store name (once per year)"""
        if not self.store_name_last_changed_at:
            return True  # Never changed before
        
        from datetime import timedelta
        one_year_ago = timezone.now() - timedelta(days=365)
        # Can change if last change was MORE than 365 days ago
        return self.store_name_last_changed_at <= one_year_ago
    
    def can_request_category_change(self) -> bool:
        """Check if vendor can request category change (once per year)"""
        if not self.main_category_last_changed_at:
            return True  # Never changed before
        
        from datetime import timedelta
        one_year_ago = timezone.now() - timedelta(days=365)
        # Can change if last change was MORE than 365 days ago
        return self.main_category_last_changed_at <= one_year_ago
    
    def days_until_next_name_change(self) -> int:
        """Calculate days remaining until store name can be changed again"""
        if self.can_change_store_name():
            return 0
        
        from datetime import timedelta
        one_year_later = self.store_name_last_changed_at + timedelta(days=365)
        days_left = (one_year_later - timezone.now()).days
        return max(0, days_left)
    
    def days_until_next_category_change(self) -> int:
        """Calculate days remaining until category can be changed again"""
        if self.can_request_category_change():
            return 0
        
        from datetime import timedelta
        one_year_later = self.main_category_last_changed_at + timedelta(days=365)
        days_left = (one_year_later - timezone.now()).days
        return max(0, days_left)

class CategoryChangeRequest(models.Model):
    """
    Vendor requests to change locked main category
    Admin reviews and approves/rejects
    """
    STATUS_CHOICES = [
        ('pending', 'Pending Review'),
        ('approved', 'Approved'),
        ('rejected', 'Rejected'),
    ]
    
    store = models.ForeignKey(Store, on_delete=models.CASCADE, related_name='category_change_requests')
    
    # Current & Requested
    current_category = models.ForeignKey(
        MainCategory, 
        on_delete=models.PROTECT, 
        related_name='current_change_requests'
    )
    requested_category = models.ForeignKey(
        MainCategory, 
        on_delete=models.PROTECT, 
        related_name='requested_change_requests'
    )
    
    # Request Details
    reason = models.TextField(help_text="Why vendor wants to change category")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    
    # Admin Response
    admin_comment = models.TextField(blank=True)
    reviewed_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)
    
    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        verbose_name = "Category Change Request"
        verbose_name_plural = "Category Change Requests"
        ordering = ['-created_at']
    
    def __str__(self):
        return f"{self.store.store_name}: {self.current_category} → {self.requested_category} ({self.status})"


# ==========================================
# PRODUCTS
# ==========================================

class Product(models.Model):
    """
    Vendor products with images, pricing, inventory
    Products must be in a subcategory that belongs to the vendor's main category
    """
    
    # ✅ VENDOR STATUS CHOICES (What vendors can select)
    VENDOR_STATUS_CHOICES = [
        ('draft', 'Draft'),
        ('published', 'Published'),
    ]
    
    # ✅ DISCONTINUED STATUS (Only for editing existing products)
    DISCONTINUED_STATUS = ('discontinued', 'Discontinued')
    
    vendor = models.ForeignKey(VendorProfile, on_delete=models.CASCADE, related_name='products')
    store = models.ForeignKey(Store, on_delete=models.CASCADE, related_name='products')
    
    # Category (subcategory must be from store's main category)
    subcategory = models.ForeignKey(
        SubCategory, 
        on_delete=models.PROTECT, 
        related_name='products',
        help_text="Must be from your store's main category"
    )
    
    # Basic Info
    title = models.CharField(max_length=200)
    slug = models.SlugField(unique=True, max_length=250)
    description = models.TextField()
    
    # Pricing & Inventory
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
    stock_quantity = models.PositiveIntegerField(
        default=0,
        help_text="Current stock quantity available for sale"
    )
    low_stock_threshold = models.PositiveIntegerField(
        default=5,
        help_text="Alert when stock falls below this number"
    )
    track_inventory = models.BooleanField(
        default=True,
        help_text="Enable automatic stock tracking for this product"
    )
    
    sku = models.CharField(max_length=100, blank=True, verbose_name="SKU")

    # Dynamic Attributes (category-specific product details)
    attributes = models.JSONField(
        default=dict,
        blank=True,
        help_text="Category-specific attributes (brand, size, specs, etc.)"
    )

    # Status (stores vendor choice: draft, published, or discontinued)
    status = models.CharField(
        max_length=20, 
        choices=VENDOR_STATUS_CHOICES + [DISCONTINUED_STATUS],
        default='draft'
    )
    is_featured = models.BooleanField(default=False)
    
    # Video (optional, one per product)
    video = CloudinaryField(
        'video',
        resource_type='video',
        null=True,
        blank=True,
        help_text="Optional product video (max ~60s recommended)"
    )

    # Stats
    views_count = models.PositiveIntegerField(default=0)
    sales_count = models.PositiveIntegerField(default=0)
    trending_score = models.PositiveIntegerField(default=0, db_index=True)
    average_rating = models.DecimalField(max_digits=3, decimal_places=2, default=0)
    review_count = models.PositiveIntegerField(default=0)
    
    # SEO
    meta_title = models.CharField(max_length=200, blank=True)
    meta_description = models.TextField(blank=True)
    
    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    published_at = models.DateTimeField(null=True, blank=True)
    
    class Meta:
        verbose_name = "Product"
        verbose_name_plural = "Products"
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['vendor', 'status']),
            models.Index(fields=['slug']),
            models.Index(fields=['subcategory', 'status']),
        ]
    
    def __str__(self):
        return self.title
    
    def clean(self):
        """Validate that subcategory belongs to store's main category"""
        from django.core.exceptions import ValidationError
        
        # Only validate if store exists (skip during form validation)
        if self.subcategory and hasattr(self, 'store') and self.store:
            if self.subcategory.main_category != self.store.main_category:
                raise ValidationError({
                    'subcategory': f"You can only add products in {self.store.main_category.name} category. "
                                f"'{self.subcategory.name}' belongs to {self.subcategory.main_category.name}."
                })
                
    def save(self, *args, **kwargs):
        # Generate slug if not exists
        if not self.slug:
            self.slug = slugify(self.title)

        # Keep published products visible in the marketplace even when stock is zero.
        # Availability is handled by the stock-based properties and UI, not by
        # mutating the product status away from 'published'.

        # Set published timestamp when status changes to published
        if self.status == 'published' and not self.published_at:
            self.published_at = timezone.now()

        # Run validation but do not block saves on validation exceptions
        try:
            self.full_clean()
        except Exception:
            pass

        # Make the store visible in the marketplace whenever it has a published product.
        # This also covers existing products already in the database that need their
        # store visibility synced after the fix.
        if self.store_id:
            try:
                store = self.store
            except Store.DoesNotExist:
                store = None

            has_published_products = (
                self.status == 'published' or
                Product.objects.filter(store=store, status='published').exclude(pk=self.pk).exists()
            )

            if store and has_published_products and not store.is_published:
                store.is_published = True
                store.save(update_fields=['is_published'])

        super().save(*args, **kwargs)

    def resolved_attributes(self):
        """
        Returns attributes with human-readable names instead of IDs
        Output format:
        [
            {"name": "Brand", "value": "Apple"},
            {"name": "Model", "value": "iPhone X"},
        ]
        """
        if not self.attributes:
            return []

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
                    "value": value
                })

        return resolved
    
    @property
    def is_low_stock(self):
        """Check if product is running low on stock"""
        if not self.track_inventory:
            return False
        return 0 < self.stock_quantity <= self.low_stock_threshold
    
    @property
    def is_in_stock(self):
        """Check if product is available"""
        if not self.track_inventory:
            return True
        return self.stock_quantity > 0
    
    @property
    def is_out_of_stock(self):
        """Check if product is out of stock"""
        if not self.track_inventory:
            return False
        return self.stock_quantity == 0

    @property
    def display_stock_status(self):
        """
        Human-readable stock status for display purposes
        This is NOT the same as the status field
        """
        if not self.track_inventory:
            return "In Stock"
        
        if self.stock_quantity == 0:
            return "Out of Stock"
        elif self.stock_quantity <= self.low_stock_threshold:
            return "Low Stock"
        else:
            return "In Stock"

    def get_absolute_url(self):
        return reverse('vendors:product_detail', kwargs={'slug': self.slug})
    
    def get_attribute(self, attribute_name, default=None):
        """Helper method to get a specific attribute value"""
        return self.attributes.get(attribute_name, default)

    @property
    def discount_percentage(self):
        """Calculate discount percentage if compare_at_price exists"""
        if self.compare_at_price and self.compare_at_price > self.price:
            return int(((self.compare_at_price - self.price) / self.compare_at_price) * 100)
        return 0

    @property
    def savings(self):
        """Naira amount saved — used by the buyer-facing product page price block."""
        if self.compare_at_price and self.compare_at_price > self.price:
            return self.compare_at_price - self.price
        return 0
    
    @property
    def main_category(self):
        """Get main category through subcategory"""
        return self.subcategory.main_category
    
    @property
    def primary_image(self):
        """Return the product's primary image, falling back to the first uploaded image."""
        image = self.images.filter(is_primary=True).first()
        if not image:
            image = self.images.first()
        return image

    @property
    def video_thumbnail_url(self):
        """Cloudinary auto-generated poster frame for the product video."""
        if not self.video:
            return None
        public_id = self.video.public_id
        return f"https://res.cloudinary.com/{settings.CLOUDINARY_STORAGE['CLOUD_NAME']}/video/upload/f_jpg,so_0/{public_id}.jpg"


class ProductImage(models.Model):
    """
    Multiple images per product
    """
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name='images')
    image = CloudinaryField('image')
    alt_text = models.CharField(max_length=200, blank=True)
    is_primary = models.BooleanField(default=False)
    sort_order = models.PositiveIntegerField(default=0)
    
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        verbose_name = "Product Image"
        verbose_name_plural = "Product Images"
        ordering = ['sort_order', 'created_at']
    
    def __str__(self):
        return f"{self.product.title} - Image {self.sort_order}"


# ==========================================
# WALLET & TRANSACTIONS
# ==========================================

class Wallet(models.Model):
    """
    Vendor wallet for receiving payments and tracking balances
    """
    vendor = models.OneToOneField(VendorProfile, on_delete=models.CASCADE, related_name='wallet')
    
    # Bank Account (Auto-filled from BVN)
    account_number = models.CharField(max_length=20, blank=True)
    bank_name = models.CharField(max_length=100, blank=True)
    bank_code = models.CharField(max_length=10, blank=True)
    paystack_recipient_code = models.CharField(max_length=100, blank=True, help_text="Paystack transfer recipient code")
    account_holder_name = models.CharField(max_length=200, blank=True)
    
    # Balances
    balance = models.DecimalField(
        max_digits=12, 
        decimal_places=2, 
        default=0,
        help_text="Available balance (can be withdrawn)"
    )
    pending_balance = models.DecimalField(
        max_digits=12, 
        decimal_places=2, 
        default=0,
        help_text="Pending balance (from incomplete orders)"
    )
    total_earned = models.DecimalField(
        max_digits=12, 
        decimal_places=2, 
        default=0,
        help_text="Lifetime earnings"
    )
    total_withdrawn = models.DecimalField(
        max_digits=12, 
        decimal_places=2, 
        default=0,
        help_text="Total amount withdrawn"
    )
    
    # Commission Rate (can be customized per vendor)
    commission_rate = models.DecimalField(
        max_digits=5, 
        decimal_places=2, 
        default=10.00,
        validators=[MinValueValidator(0), MaxValueValidator(100)],
        help_text="Platform commission percentage (e.g., 10.00 for 10%)"
    )
    
    # Settings
    auto_payout = models.BooleanField(default=False, help_text="Auto-withdraw when balance reaches threshold")
    payout_threshold = models.DecimalField(max_digits=10, decimal_places=2, default=5000)
    
    # Verification
    is_verified = models.BooleanField(default=False)
    verified_at = models.DateTimeField(null=True, blank=True)
    
    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        verbose_name = "Wallet"
        verbose_name_plural = "Wallets"
    
    def __str__(self):
        return f"{self.vendor.full_name}'s Wallet - ₦{self.balance}"


class Transaction(models.Model):
    """
    All wallet transactions (credits, debits, payouts, refunds)
    """
    
    TRANSACTION_TYPE_CHOICES = [
        ('credit', 'Credit'),
        ('debit', 'Debit'),
        ('payout', 'Payout'),
        ('refund', 'Refund'),
        ('commission', 'Commission'),
    ]
    
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('completed', 'Completed'),
        ('failed', 'Failed'),
        ('reversed', 'Reversed'),
    ]
    
    wallet = models.ForeignKey(Wallet, on_delete=models.CASCADE, related_name='transactions')
    transaction_id = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)
    
    # Transaction Details
    transaction_type = models.CharField(max_length=20, choices=TRANSACTION_TYPE_CHOICES)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    
    # References
    reference = models.CharField(max_length=100, blank=True)
    description = models.TextField(blank=True)
    
    # Related Objects (optional)
    order = models.ForeignKey('Order', on_delete=models.SET_NULL, null=True, blank=True)
    
    # Balances After Transaction
    balance_before = models.DecimalField(max_digits=12, decimal_places=2)
    balance_after = models.DecimalField(max_digits=12, decimal_places=2)
    
    # Metadata
    metadata = models.JSONField(default=dict, blank=True)
    
    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    
    class Meta:
        verbose_name = "Transaction"
        verbose_name_plural = "Transactions"
        ordering = ['-created_at']
    
    def __str__(self):
        return f"{self.transaction_type} - ₦{self.amount} - {self.status}"


# ==========================================
# ORDERS & REFUNDS
# ==========================================

class Order(models.Model):
    """
    Customer orders - linked to vendors
    """
    
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('confirmed', 'Confirmed'),
        ('processing', 'Processing'),
        ('shipped', 'Shipped'),
        ('delivered', 'Delivered'),
        ('cancelled', 'Cancelled'),
        ('refunded', 'Refunded'),
    ]
    
    order_id = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)
    vendor = models.ForeignKey(VendorProfile, on_delete=models.CASCADE, related_name='orders')
    customer = models.ForeignKey(User, on_delete=models.CASCADE, related_name='vendor_orders')
    
    # Order Details
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    total_amount = models.DecimalField(max_digits=10, decimal_places=2)
    commission_amount = models.DecimalField(max_digits=10, decimal_places=2)
    vendor_amount = models.DecimalField(max_digits=10, decimal_places=2)
    
    # Payment
    payment_reference = models.CharField(max_length=100, blank=True)
    payment_status = models.CharField(max_length=20, default='pending')
    paid_at = models.DateTimeField(null=True, blank=True)
    
    # Shipping
    shipping_address = models.TextField()
    shipping_phone = models.CharField(max_length=20)
    tracking_number = models.CharField(max_length=100, blank=True)
    
    # Notes
    customer_note = models.TextField(blank=True)
    vendor_note = models.TextField(blank=True)
    
    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    delivered_at = models.DateTimeField(null=True, blank=True)
    
    class Meta:
        verbose_name = "Order"
        verbose_name_plural = "Orders"
        ordering = ['-created_at']
    
    def __str__(self):
        return f"Order #{self.order_id} - {self.status}"


class OrderItem(models.Model):
    """
    Individual items in an order
    """
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name='items')
    product = models.ForeignKey(Product, on_delete=models.PROTECT)
    
    quantity = models.PositiveIntegerField(default=1)
    price = models.DecimalField(max_digits=10, decimal_places=2)
    total = models.DecimalField(max_digits=10, decimal_places=2)
    
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        verbose_name = "Order Item"
        verbose_name_plural = "Order Items"
    
    def __str__(self):
        return f"{self.product.title} x{self.quantity}"


class RefundRequest(models.Model):
    """
    Customer refund requests
    """
    
    STATUS_CHOICES = [
        ('pending', 'Pending Review'),
        ('approved', 'Approved'),
        ('rejected', 'Rejected'),
        ('completed', 'Completed'),
    ]
    
    REASON_CHOICES = [
        ('damaged', 'Damaged Product'),
        ('wrong_item', 'Wrong Item Sent'),
        ('not_as_described', 'Not as Described'),
        ('defective', 'Defective'),
        ('other', 'Other'),
    ]
    
    refund_id = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name='refunds')
    order_item = models.ForeignKey(OrderItem, on_delete=models.CASCADE)
    vendor = models.ForeignKey(VendorProfile, on_delete=models.CASCADE)
    
    # Refund Details
    reason = models.CharField(max_length=50, choices=REASON_CHOICES)
    description = models.TextField()
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    
    # Admin/Vendor Response
    admin_comment = models.TextField(blank=True)
    processed_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    
    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    processed_at = models.DateTimeField(null=True, blank=True)
    
    class Meta:
        verbose_name = "Refund Request"
        verbose_name_plural = "Refund Requests"
        ordering = ['-created_at']
    
    def __str__(self):
        return f"Refund #{self.refund_id} - {self.status}"


# ==========================================
# NOTIFICATIONS
# ==========================================

class Notification(models.Model):
    """
    In-app notifications for vendors
    """
    
    TYPE_CHOICES = [
        ('order', 'New Order'),
        ('payment', 'Payment Received'),
        ('refund', 'Refund Request'),
        ('verification', 'Verification Update'),
        ('admin_message', 'Admin Message'),
        ('system', 'System Message'),
    ]
    
    vendor = models.ForeignKey(VendorProfile, on_delete=models.CASCADE, related_name='notifications')
    
    notification_type = models.CharField(max_length=20, choices=TYPE_CHOICES)
    title = models.CharField(max_length=200)
    message = models.TextField()
    link = models.CharField(max_length=500, blank=True)
    
    is_read = models.BooleanField(default=False)
    read_at = models.DateTimeField(null=True, blank=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        verbose_name = "Notification"
        verbose_name_plural = "Notifications"
        ordering = ['-created_at']
    
    def __str__(self):
        return f"{self.title} - {'Read' if self.is_read else 'Unread'}"
