"""
Vendor App Models
Complete database schema for vendor verification, store management, products, orders, wallet, etc.
"""

from django.db import models
from django.contrib.auth import get_user_model
from django.core.validators import MinValueValidator, MaxValueValidator, RegexValidator
from django.utils.text import slugify
from django.urls import reverse
from django.utils import timezone
from decimal import Decimal
import uuid

User = get_user_model()


# ==========================================
# VENDOR PROFILE & VERIFICATION
# ==========================================

class VendorProfile(models.Model):
    """
    Main vendor profile - linked to User model
    Tracks verification status and personal information
    """
    
    # Verification Status Choices
    VERIFICATION_STATUS_CHOICES = [
        ('pending', 'Pending Verification'),
        ('nin_verified', 'NIN Verified'),
        ('bvn_verified', 'BVN Verified'),
        ('student_verified', 'Student Verified'),
        ('approved', 'Approved'),
        ('rejected', 'Rejected'),
        ('suspended', 'Suspended'),
    ]
    
    IDENTITY_STATUS_CHOICES = [
        ('not_started', 'Not Started'),
        ('nin_entered', 'NIN Entered'),
        ('nin_otp_sent', 'OTP Sent'),
        ('nin_verified', 'Verified'),
        ('failed', 'Failed'),
    ]
    
    BANK_STATUS_CHOICES = [
        ('not_started', 'Not Started'),
        ('bvn_entered', 'BVN Entered'),
        ('bvn_otp_sent', 'OTP Sent'),
        ('bvn_verified', 'Verified'),
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
    
    # Basic Info
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='vendorprofile')
    vendor_id = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)
    
    # Personal Information (Auto-filled from NIN)
    full_name = models.CharField(max_length=200, blank=True)
    phone = models.CharField(max_length=20, blank=True)
    gender = models.CharField(max_length=10, choices=GENDER_CHOICES, blank=True)
    dob = models.DateField(null=True, blank=True, verbose_name="Date of Birth")
    address = models.TextField(blank=True)
    state = models.CharField(max_length=50, blank=True)
    lga = models.CharField(max_length=100, blank=True, verbose_name="LGA")
    
    # NIN/BVN Data (Encrypted in production)
    nin_number = models.CharField(
        max_length=11, 
        blank=True, 
        validators=[RegexValidator(r'^\d{11}$', 'NIN must be 11 digits')],
        verbose_name="NIN"
    )
    bvn_number = models.CharField(
        max_length=11, 
        blank=True,
        validators=[RegexValidator(r'^\d{11}$', 'BVN must be 11 digits')],
        verbose_name="BVN"
    )
    photo_from_nin = models.ImageField(upload_to='vendors/nin_photos/', blank=True, null=True)
    
    # Student Information (Optional)
    matric_number = models.CharField(max_length=50, blank=True)
    department = models.CharField(max_length=100, blank=True)
    level = models.CharField(max_length=20, blank=True)
    student_id_image = models.ImageField(upload_to='vendors/student_ids/', blank=True, null=True)
    selfie = models.ImageField(upload_to='vendors/selfies/', blank=True, null=True)
    
    # Verification Status
    verification_status = models.CharField(
        max_length=20, 
        choices=VERIFICATION_STATUS_CHOICES, 
        default='pending'
    )
    identity_status = models.CharField(
        max_length=20, 
        choices=IDENTITY_STATUS_CHOICES, 
        default='not_started'
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
    
    # Store Setup Progress
    store_setup_completed = models.BooleanField(default=False)
    store_setup_skipped = models.BooleanField(default=False)
    
    # Admin Review
    admin_comment = models.TextField(blank=True, help_text="Admin notes on verification")
    reviewed_by = models.ForeignKey(
        User, 
        on_delete=models.SET_NULL, 
        null=True, 
        blank=True, 
        related_name='reviewed_vendors'
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    
    # Verification Timestamps
    nin_verified_at = models.DateTimeField(null=True, blank=True)
    bvn_verified_at = models.DateTimeField(null=True, blank=True)
    student_verified_at = models.DateTimeField(null=True, blank=True)
    approved_at = models.DateTimeField(null=True, blank=True)
    
    # Progress Tracking (JSON field for flexibility)
    verification_progress = models.JSONField(
        default=dict, 
        blank=True,
        help_text="Tracks current step, timestamps, attempts"
    )
    
    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        verbose_name = "Vendor Profile"
        verbose_name_plural = "Vendor Profiles"
        ordering = ['-created_at']
    
    def __str__(self):
        return f"{self.full_name or self.user.email} - {self.verification_status}"
    
    @property
    def is_verified(self):
        """Check if vendor is fully verified and approved"""
        return self.verification_status == 'approved'
    
    @property
    def can_sell(self):
        """Check if vendor can list products (NIN + BVN verified)"""
        return self.identity_status == 'nin_verified' and self.bank_status == 'bvn_verified'
    
    @property
    def current_step(self):
        """Calculate which verification step user should see next"""
        if self.identity_status != 'nin_verified':
            if self.identity_status == 'nin_otp_sent':
                return 'nin_otp'
            return 'nin_entry'
        
        if self.bank_status != 'bvn_verified':
            if self.bank_status == 'bvn_otp_sent':
                return 'bvn_otp'
            return 'bvn_entry'
        
        if not self.store_setup_completed and not self.store_setup_skipped:
            return 'store_setup'
        
        if self.student_status == 'not_started':
            return 'student_verification'
        
        return 'admin_review'
    
    @property
    def completion_percentage(self):
        """Calculate verification progress (0-100)"""
        total_steps = 6
        completed = 0
        
        if self.identity_status == 'nin_verified':
            completed += 2  # NIN entry + verification
        elif self.identity_status in ['nin_entered', 'nin_otp_sent']:
            completed += 1
        
        if self.bank_status == 'bvn_verified':
            completed += 2
        elif self.bank_status in ['bvn_entered', 'bvn_otp_sent']:
            completed += 1
        
        if self.store_setup_completed or self.store_setup_skipped:
            completed += 1
        
        if self.student_status == 'verified':
            completed += 1
        
        return int((completed / total_steps) * 100)
    
    def get_absolute_url(self):
        return reverse('vendors:dashboard')


class VerificationAttempt(models.Model):
    """
    Audit log for verification attempts (NIN, BVN, Student)
    Tracks all API calls and responses for compliance
    """
    
    ATTEMPT_TYPE_CHOICES = [
        ('nin', 'NIN Verification'),
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
    
    # Response Data (sanitized - no full BVN/NIN stored)
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
    icon = models.CharField(max_length=50, blank=True, help_text="Icon name (e.g., 'shopping-bag', 'laptop')")
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
    logo = models.ImageField(upload_to='stores/logos/', blank=True, null=True, help_text="Recommended: 400x400px, max 5MB")
    banner = models.ImageField(upload_to='stores/banners/', blank=True, null=True, help_text="Recommended: 1200x350px, max 8MB")
    primary_color = models.CharField(max_length=7, blank=True, help_text="Hex color code (e.g., #FF5733)")
    
    # Contact Info (Public)
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
        super().save(*args, **kwargs)
    
    def get_absolute_url(self):
        return reverse('vendors:store_public', kwargs={'slug': self.slug})
    
    def lock_main_category(self):
        """Lock main category (call this after vendor confirms)"""
        if not self.main_category_locked:
            self.main_category_locked = True
            self.main_category_locked_at = timezone.now()
            self.save(update_fields=['main_category_locked', 'main_category_locked_at'])


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
    
    STATUS_CHOICES = [
        ('draft', 'Draft'),
        ('published', 'Published'),
        ('out_of_stock', 'Out of Stock'),
        ('discontinued', 'Discontinued'),
    ]
    
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
    quantity = models.PositiveIntegerField(default=0)
    sku = models.CharField(max_length=100, blank=True, verbose_name="SKU")
    
    # Dynamic Attributes (category-specific product details)
    attributes = models.JSONField(
        default=dict,
        blank=True,
        help_text="Category-specific attributes (brand, size, specs, etc.)"
    )
    # Example stored data:
    # For Laptop: {"brand": "HP", "processor": "Intel i5", "ram": "8GB", "storage": "512GB SSD"}
    # For Shoes: {"size": "42", "color": "Black", "material": "Leather", "brand": "Nike"}
    # For Barbing: {"duration": "30 mins", "availability": "Mon-Sat 9AM-6PM"}
    
    # Status
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='draft')
    is_featured = models.BooleanField(default=False)
    
    # Stats
    views_count = models.PositiveIntegerField(default=0)
    sales_count = models.PositiveIntegerField(default=0)
    
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
        
        if self.subcategory and self.store:
            if self.subcategory.main_category != self.store.main_category:
                raise ValidationError({
                    'subcategory': f"You can only add products in {self.store.main_category.name} category. "
                                  f"'{self.subcategory.name}' belongs to {self.subcategory.main_category.name}."
                })
    
    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.title)
        
        # Set published_at when status changes to published
        if self.status == 'published' and not self.published_at:
            self.published_at = timezone.now()
        
        # Run validation
        self.full_clean()
        
        super().save(*args, **kwargs)
    
    def get_absolute_url(self):
        return reverse('vendors:product_detail', kwargs={'slug': self.slug})
    
    def get_attribute(self, attribute_name, default=None):
        """Helper method to get a specific attribute value"""
        return self.attributes.get(attribute_name, default)
    
    @property
    def is_in_stock(self):
        return self.quantity > 0
    
    @property
    def discount_percentage(self):
        """Calculate discount percentage if compare_at_price exists"""
        if self.compare_at_price and self.compare_at_price > self.price:
            return int(((self.compare_at_price - self.price) / self.compare_at_price) * 100)
        return 0
    
    @property
    def main_category(self):
        """Get main category through subcategory"""
        return self.subcategory.main_category


class ProductImage(models.Model):
    """
    Multiple images per product
    """
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name='images')
    image = models.ImageField(upload_to='products/')
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