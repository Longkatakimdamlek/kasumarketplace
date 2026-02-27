from django.contrib.auth.models import AbstractBaseUser, PermissionsMixin, BaseUserManager
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
    
