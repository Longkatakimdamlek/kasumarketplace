from django.contrib.auth.models import AbstractBaseUser, PermissionsMixin, BaseUserManager
from django.contrib.auth.hashers import make_password, check_password
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _


class CustomUserManager(BaseUserManager):
    """
    Custom user manager where email is the unique identifier
    for authentication instead of username.
    """
    
    def create_user(self, email, password=None, **extra_fields):
        """
        Create and save a regular user with the given email and password.
        """
        if not email:
            raise ValueError(_('The Email field must be set'))
        
        email = self.normalize_email(email)
        user = self.model(email=email, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user
    
    def create_superuser(self, email, password=None, **extra_fields):
        """
        Create and save a superuser with the given email and password.
        """
        extra_fields.setdefault('is_staff', True)
        extra_fields.setdefault('is_superuser', True)
        extra_fields.setdefault('is_active', True)
        extra_fields.setdefault('is_verified', True)
        extra_fields.setdefault('role', 'admin')
        
        if extra_fields.get('is_staff') is not True:
            raise ValueError(_('Superuser must have is_staff=True.'))
        if extra_fields.get('is_superuser') is not True:
            raise ValueError(_('Superuser must have is_superuser=True.'))
        
        return self.create_user(email, password, **extra_fields)


class CustomUser(AbstractBaseUser, PermissionsMixin):
    """
    Custom user model for KasuMarketplace that uses email as the
    unique identifier instead of username.
    """
    
    ROLE_CHOICES = (
        ('buyer', 'Buyer'),
        ('vendor', 'Vendor'),
        ('admin', 'Admin'),
    )
    
    email = models.EmailField(
        _('email address'),
        unique=True,
        error_messages={
            'unique': _('A user with that email already exists.'),
        },
    )
    username = models.CharField(
        _('username'),
        max_length=150,
        blank=True,
        help_text=_('Optional. 150 characters or fewer.')
    )
    role = models.CharField(
        _('role'),
        max_length=10,
        choices=ROLE_CHOICES,
        default='buyer',
        help_text=_('User role in the marketplace')
    )
    is_verified = models.BooleanField(
        _('verified'),
        default=False,
        help_text=_('Designates whether this user has verified their email address.')
    )
    otp_code = models.CharField(
        _('OTP code'),
        max_length=6,
        blank=True,
        null=True,
        help_text=_('Temporary OTP code for verification')
    )
    date_joined = models.DateTimeField(
        _('date joined'),
        default=timezone.now
    )
    is_staff = models.BooleanField(
        _('staff status'),
        default=False,
        help_text=_('Designates whether the user can log into the admin site.')
    )
    is_active = models.BooleanField(
        _('active'),
        default=True,
        help_text=_(
            'Designates whether this user should be treated as active. '
            'Unselect this instead of deleting accounts.'
        )
    )
    
    objects = CustomUserManager()
    
    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS = []
    
    class Meta:
        verbose_name = _('user')
        verbose_name_plural = _('users')
        ordering = ['-date_joined']
        db_table = 'users_customuser'
    
    def __str__(self):
        return self.email
    
    def get_full_name(self):
        """
        Return the email or username as the full name.
        """
        return self.username if self.username else self.email
    
    def get_short_name(self):
        """
        Return the username or first part of email.
        """
        return self.username if self.username else self.email.split('@')[0]

    @property
    def full_name(self):
        """A property alias for the user's display name.

        This mirrors older code that referenced a `full_name` attribute
        from the admin configuration.
        """
        return self.get_full_name()
    
    @property
    def is_buyer(self):
        """Check if user is a buyer."""
        return self.role == 'buyer'
    
    @property
    def is_vendor(self):
        """Check if user is a vendor."""
        return self.role == 'vendor'
    
    @property
    def is_admin_role(self):
        """Check if user has admin role."""
        return self.role == 'admin'
    
# ==========================================
# BUYER PROFILE
# ==========================================

class BuyerProfile(models.Model):
    """
    Extended profile for buyers.
    Stores delivery address and location for distance calculation.
    Created automatically when a user with role='buyer' is created.
    """
    user = models.OneToOneField(
        'CustomUser',
        on_delete=models.CASCADE,
        related_name='buyer_profile'
    )

    # Full name (can differ from account email name)
    full_name = models.CharField(max_length=200, blank=True)

    # Primary phone number
    phone = models.CharField(max_length=20, blank=True)

    # Default delivery address (pre-filled at checkout, editable)
    default_address = models.TextField(
        blank=True,
        help_text="Default delivery address for orders"
    )
    city = models.CharField(max_length=100, blank=True)
    state = models.CharField(max_length=100, blank=True)

    # Location coordinates (set via browser geolocation)
    # Used for Haversine distance calculation to stores
    latitude = models.DecimalField(
        max_digits=9,
        decimal_places=6,
        null=True,
        blank=True,
        help_text="Buyer's latitude (from browser geolocation)"
    )
    longitude = models.DecimalField(
        max_digits=9,
        decimal_places=6,
        null=True,
        blank=True,
        help_text="Buyer's longitude (from browser geolocation)"
    )

    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Buyer Profile"
        verbose_name_plural = "Buyer Profiles"

    def __str__(self):
        return f"{self.user.email} - Buyer Profile"

    @property
    def has_location(self):
        """Check if buyer has shared their location"""
        return self.latitude is not None and self.longitude is not None

    @property
    def display_name(self):
        """Return best available display name"""
        return self.full_name or self.user.username or self.user.email.split('@')[0]


# ==========================================
# OTP VERIFICATION MODEL
# ==========================================

class OTPVerification(models.Model):
    """
    Production-ready OTP model for email verification.
    
    Features:
    - Hashed OTP storage using Django's make_password
    - Configurable expiration time (5 minutes)
    - Single-use OTP (is_used flag)
    - Attempt counter with max 5 tries
    - Timezone-aware datetime
    - Automatic cleanup of expired OTPs
    """
    
    user = models.OneToOneField(
        CustomUser,
        on_delete=models.CASCADE,
        related_name='otp_verification',
        help_text="User requesting OTP verification"
    )
    
    otp_hash = models.CharField(
        max_length=255,
        help_text="Hashed OTP code"
    )
    
    created_at = models.DateTimeField(
        auto_now_add=True,
        help_text="When OTP was created (timezone-aware)"
    )
    
    expires_at = models.DateTimeField(
        help_text="When OTP expires (timezone-aware)"
    )
    
    is_used = models.BooleanField(
        default=False,
        help_text="Marks OTP as used (prevents reuse)"
    )
    
    used_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When OTP was successfully used"
    )
    
    attempts = models.PositiveIntegerField(
        default=0,
        help_text="Number of verification attempts"
    )
    
    is_locked = models.BooleanField(
        default=False,
        help_text="Locked after max verification attempts exceeded"
    )
    
    locked_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When OTP was locked due to max attempts"
    )
    
    MAX_ATTEMPTS = 5
    OTP_EXPIRY_MINUTES = 5
    MAX_GENERATION_ATTEMPTS = 3
    GENERATION_WINDOW_MINUTES = 10
    
    class Meta:
        verbose_name = "OTP Verification"
        verbose_name_plural = "OTP Verifications"
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['user', 'is_used']),
            models.Index(fields=['expires_at']),
            models.Index(fields=['user', 'created_at']),
            models.Index(fields=['is_locked']),
        ]
    
    def __str__(self):
        return f"OTP for {self.user.email} (Created: {self.created_at})"
    
    @classmethod
    def create_otp(cls, user, otp_code):
        """
        Create a new OTP for the user.
        Deletes any existing OTP for the user.
        
        Args:
            user (CustomUser): User requesting OTP
            otp_code (str): Plain text OTP code
        
        Returns:
            OTPVerification: Newly created OTP instance
        """
        # Delete existing OTP
        cls.objects.filter(user=user).delete()
        
        # Create new OTP with expiration
        expiry_time = timezone.now() + timezone.timedelta(
            minutes=cls.OTP_EXPIRY_MINUTES
        )
        
        otp = cls.objects.create(
            user=user,
            otp_hash=make_password(otp_code),
            expires_at=expiry_time
        )
        return otp
    
    def verify_otp(self, otp_code):
        """
        Verify the OTP code.
        
        Args:
            otp_code (str): Plain text OTP code to verify
        
        Returns:
            dict: {'success': bool, 'error': str or None}
        """
        # Check if OTP is locked
        if self.is_locked:
            return {'success': False, 'error': 'This OTP is locked due to too many failed attempts.'}
        
        # Check if OTP has been used
        if self.is_used:
            return {'success': False, 'error': 'This OTP has already been used.'}
        
        # Check if OTP has expired
        if timezone.now() > self.expires_at:
            return {'success': False, 'error': 'This OTP has expired.'}
        
        # Increment attempt counter
        self.attempts += 1
        
        # Check if max attempts exceeded
        if self.attempts >= self.MAX_ATTEMPTS:
            self.is_locked = True
            self.locked_at = timezone.now()
            self.save(update_fields=['attempts', 'is_locked', 'locked_at'])
            return {'success': False, 'error': 'Maximum verification attempts exceeded. OTP is now locked.'}
        
        # Verify OTP hash
        if not check_password(otp_code, self.otp_hash):
            self.save(update_fields=['attempts'])
            remaining = self.MAX_ATTEMPTS - self.attempts
            return {
                'success': False,
                'error': f'Invalid OTP. {remaining} attempt(s) remaining.'
            }
        
        # OTP is valid - mark as used
        self.is_used = True
        self.used_at = timezone.now()
        self.save(update_fields=['is_used', 'used_at'])
        
        return {'success': True, 'error': None}
    
    @classmethod
    def check_generation_rate_limit(cls, user):
        """
        Check if user has exceeded OTP generation rate limit.
        
        Args:
            user (CustomUser): User requesting OTP
        
        Returns:
            tuple: (is_rate_limited: bool, error_message: str or None, time_until_retry: int or None)
        """
        # Look back GENERATION_WINDOW_MINUTES to count recent OTP creations
        window_start = timezone.now() - timezone.timedelta(
            minutes=cls.GENERATION_WINDOW_MINUTES
        )
        
        recent_count = cls.objects.filter(
            user=user,
            created_at__gte=window_start
        ).count()
        
        if recent_count >= cls.MAX_GENERATION_ATTEMPTS:
            # Calculate time until oldest OTP in window expires from tracking perspective
            oldest_otp = cls.objects.filter(
                user=user,
                created_at__gte=window_start
            ).order_by('created_at').first()
            
            if oldest_otp:
                window_expires = oldest_otp.created_at + timezone.timedelta(
                    minutes=cls.GENERATION_WINDOW_MINUTES
                )
                time_until_retry = int((window_expires - timezone.now()).total_seconds())
                time_until_retry = max(0, time_until_retry)
                
                error_msg = f'Too many OTP requests. Please try again in {time_until_retry} seconds.'
                return True, error_msg, time_until_retry
        
        return False, None, None
    
    def is_valid(self):
        """
        Check if OTP is still valid (not expired and not used).
        
        Returns:
            bool: True if OTP is valid, False otherwise
        """
        return (
            not self.is_used and
            timezone.now() <= self.expires_at
        )
    
    def is_expired(self):
        """
        Check if OTP has expired.
        
        Returns:
            bool: True if OTP has expired, False otherwise
        """
        return timezone.now() > self.expires_at
    
    @property
    def remaining_attempts(self):
        """Get remaining verification attempts."""
        return max(0, self.MAX_ATTEMPTS - self.attempts)
    
    @property
    def time_remaining(self):
        """Get remaining time in seconds before expiration."""
        if self.is_expired():
            return 0
        delta = self.expires_at - timezone.now()
        return max(0, int(delta.total_seconds()))