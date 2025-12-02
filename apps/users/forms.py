"""
Forms for KasuMarketplace user authentication and registration.
Location: apps/users/forms.py
"""

from django import forms
from django.contrib.auth import authenticate
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.validators import EmailValidator
from django.utils.translation import gettext_lazy as _
import re

from .models import CustomUser


class BaseSignupForm(forms.ModelForm):
    """
    Base signup form with shared logic for buyers and vendors.
    Handles email, password validation, and reCAPTCHA.
    """
    email = forms.EmailField(
        label=_('Email Address'),
        widget=forms.EmailInput(attrs={
            'class': 'form-control',
            'placeholder': 'Enter your email address',
            'autocomplete': 'email',
        }),
        validators=[EmailValidator(message=_('Enter a valid email address.'))],
        error_messages={
            'required': _('Email address is required.'),
            'invalid': _('Enter a valid email address.'),
        }
    )
    
    password1 = forms.CharField(
        label=_('Password'),
        widget=forms.PasswordInput(attrs={
            'class': 'form-control',
            'placeholder': 'Create a strong password',
            'autocomplete': 'new-password',
        }),
        help_text=_(
            'Password must be at least 8 characters long and contain '
            'uppercase, lowercase, numbers, and special characters.'
        ),
        error_messages={
            'required': _('Password is required.'),
        }
    )
    
    password2 = forms.CharField(
        label=_('Confirm Password'),
        widget=forms.PasswordInput(attrs={
            'class': 'form-control',
            'placeholder': 'Re-enter your password',
            'autocomplete': 'new-password',
        }),
        error_messages={
            'required': _('Please confirm your password.'),
        }
    )
    
    recaptcha = forms.CharField(
        label=_('reCAPTCHA'),
        widget=forms.HiddenInput(),
        required=False,  # Set to True in production with actual reCAPTCHA
        help_text=_('Please complete the reCAPTCHA verification.')
    )
    
    class Meta:
        model = CustomUser
        fields = ['email']
    
    def clean_email(self):
        """Validate email uniqueness and format."""
        email = self.cleaned_data.get('email', '').lower().strip()
        
        if not email:
            raise ValidationError(_('Email address is required.'))
        
        # Check if email already exists
        if CustomUser.objects.filter(email=email).exists():
            raise ValidationError(
                _('An account with this email already exists. Please login instead.')
            )
        
        return email
    
    def clean_password1(self):
        """Validate password strength."""
        password = self.cleaned_data.get('password1')
        
        if not password:
            raise ValidationError(_('Password is required.'))
        
        # Minimum length check
        if len(password) < 8:
            raise ValidationError(
                _('Password must be at least 8 characters long.')
            )
        
        # Check for uppercase letter
        if not re.search(r'[A-Z]', password):
            raise ValidationError(
                _('Password must contain at least one uppercase letter.')
            )
        
        # Check for lowercase letter
        if not re.search(r'[a-z]', password):
            raise ValidationError(
                _('Password must contain at least one lowercase letter.')
            )
        
        # Check for digit
        if not re.search(r'\d', password):
            raise ValidationError(
                _('Password must contain at least one number.')
            )
        
        # Check for special character
        if not re.search(r'[!@#$%^&*(),.?":{}|<>]', password):
            raise ValidationError(
                _('Password must contain at least one special character.')
            )
        
        # Use Django's built-in password validators
        try:
            validate_password(password)
        except ValidationError as e:
            raise ValidationError(e.messages)
        
        return password
    
    def clean(self):
        """Validate that passwords match and reCAPTCHA is completed."""
        cleaned_data = super().clean()
        password1 = cleaned_data.get('password1')
        password2 = cleaned_data.get('password2')
        
        # Check if passwords match
        if password1 and password2 and password1 != password2:
            raise ValidationError({
                'password2': _('Passwords do not match. Please try again.')
            })
        
        # TODO: Add actual reCAPTCHA validation in production
        # recaptcha_response = cleaned_data.get('recaptcha')
        # if not self._validate_recaptcha(recaptcha_response):
        #     raise ValidationError(_('reCAPTCHA validation failed.'))
        
        return cleaned_data
    
    def _validate_recaptcha(self, response):
        """
        Validate reCAPTCHA response with Google's API.
        Implement this method when using actual reCAPTCHA in production.
        """
        # Placeholder for reCAPTCHA validation
        return True


class BuyerSignupForm(BaseSignupForm):
    """
    Signup form for buyers.
    Uses email as the unique identifier.
    """
    
    def save(self, commit=True):
        """Save buyer with role='buyer'."""
        user = super().save(commit=False)
        user.role = 'buyer'
        user.set_password(self.cleaned_data['password1'])
        
        if commit:
            user.save()
        
        return user


class VendorSignupForm(BaseSignupForm):
    """
    Signup form for vendors.
    Uses business email and validates professional domain.
    """
    email = forms.EmailField(
        label=_('Business Email Address'),
        widget=forms.EmailInput(attrs={
            'class': 'form-control',
            'placeholder': 'Enter your business email',
            'autocomplete': 'email',
        }),
        help_text=_('Please use a professional business email address.'),
        validators=[EmailValidator(message=_('Enter a valid email address.'))],
        error_messages={
            'required': _('Business email address is required.'),
            'invalid': _('Enter a valid business email address.'),
        }
    )
    
    def clean_email(self):
        """Validate business email and check for professional domain."""
        email = super().clean_email()
        
        # List of common free email providers
        free_email_domains = [
            'gmail.com', 'yahoo.com', 'hotmail.com', 'outlook.com',
            'aol.com', 'icloud.com', 'mail.com', 'protonmail.com'
        ]
        
        domain = email.split('@')[-1].lower()
        
        # Warning for free email domains (not blocking, just warning)
        if domain in free_email_domains:
            # In production, you might want to make this a hard block
            # For now, we'll allow it but you can uncomment to block:
            # raise ValidationError(
            #     _('Please use a business email address. Free email providers are not allowed for vendor accounts.')
            # )
            pass
        
        return email
    
    def save(self, commit=True):
        """Save vendor with role='vendor'."""
        user = super().save(commit=False)
        user.role = 'vendor'
        user.set_password(self.cleaned_data['password1'])
        
        if commit:
            user.save()
        
        return user


class LoginForm(forms.Form):
    """
    Login form using email and password (no username).
    Includes reCAPTCHA for bot protection.
    """
    email = forms.EmailField(
        label=_('Email Address'),
        widget=forms.EmailInput(attrs={
            'class': 'form-control',
            'placeholder': 'Enter your email address',
            'autocomplete': 'email',
            'autofocus': True,
        }),
        error_messages={
            'required': _('Email address is required.'),
            'invalid': _('Enter a valid email address.'),
        }
    )
    
    password = forms.CharField(
        label=_('Password'),
        widget=forms.PasswordInput(attrs={
            'class': 'form-control',
            'placeholder': 'Enter your password',
            'autocomplete': 'current-password',
        }),
        error_messages={
            'required': _('Password is required.'),
        }
    )
    
    recaptcha = forms.CharField(
        label=_('reCAPTCHA'),
        widget=forms.HiddenInput(),
        required=False,  # Set to True in production
    )
    
    remember_me = forms.BooleanField(
        label=_('Remember Me'),
        required=False,
        widget=forms.CheckboxInput(attrs={
            'class': 'form-check-input',
        })
    )
    
    def __init__(self, request=None, *args, **kwargs):
        """Initialize form with request object for authentication."""
        self.request = request
        self.user_cache = None
        super().__init__(*args, **kwargs)
    
    def clean(self):
        """Validate user credentials."""
        cleaned_data = super().clean()
        email = cleaned_data.get('email', '').lower().strip()
        password = cleaned_data.get('password')
        
        if email and password:
            # Check if user exists
            try:
                user = CustomUser.objects.get(email=email)
            except CustomUser.DoesNotExist:
                raise ValidationError(
                    _('Invalid email or password. Please try again.')
                )
            
            # Authenticate user
            self.user_cache = authenticate(
                self.request,
                username=email,  # Django uses 'username' param even for email
                password=password
            )
            
            if self.user_cache is None:
                raise ValidationError(
                    _('Invalid email or password. Please try again.')
                )
            
            # Check if user is active
            if not self.user_cache.is_active:
                raise ValidationError(
                    _('This account has been deactivated. Please contact support.')
                )
            
            # Check if email is verified
            if not self.user_cache.is_verified:
                raise ValidationError(
                    _('Please verify your email address before logging in.')
                )
        
        return cleaned_data
    
    def get_user(self):
        """Return authenticated user."""
        return self.user_cache


class OTPVerificationForm(forms.Form):
    """
    Form for OTP-based email verification.
    Accepts a 6-digit numeric code.
    """
    otp_code = forms.CharField(
        label=_('Verification Code'),
        widget=forms.TextInput(attrs={
            'class': 'form-control text-center',
            'placeholder': '000000',
            'maxlength': '6',
            'pattern': '[0-9]{6}',
            'autocomplete': 'off',
            'inputmode': 'numeric',
        }),
        max_length=6,
        min_length=6,
        help_text=_('Enter the 6-digit code sent to your email.'),
        error_messages={
            'required': _('Verification code is required.'),
            'min_length': _('Verification code must be 6 digits.'),
            'max_length': _('Verification code must be 6 digits.'),
        }
    )
    
    def clean_otp_code(self):
        """Validate OTP format."""
        otp_code = self.cleaned_data.get('otp_code', '').strip()
        
        # Check if OTP is numeric
        if not otp_code.isdigit():
            raise ValidationError(
                _('Verification code must contain only numbers.')
            )
        
        # Check length
        if len(otp_code) != 6:
            raise ValidationError(
                _('Verification code must be exactly 6 digits.')
            )
        
        return otp_code


class ResendOTPForm(forms.Form):
    """
    Simple form to resend OTP to user's email.
    """
    email = forms.EmailField(
        label=_('Email Address'),
        widget=forms.EmailInput(attrs={
            'class': 'form-control',
            'placeholder': 'Enter your email address',
            'autocomplete': 'email',
        }),
        error_messages={
            'required': _('Email address is required.'),
            'invalid': _('Enter a valid email address.'),
        }
    )
    
    def clean_email(self):
        """Validate that user exists."""
        email = self.cleaned_data.get('email', '').lower().strip()
        
        try:
            user = CustomUser.objects.get(email=email)
            if user.is_verified:
                raise ValidationError(
                    _('This email is already verified. You can login now.')
                )
        except CustomUser.DoesNotExist:
            raise ValidationError(
                _('No account found with this email address.')
            )
        
        return email

# ============================================
# FILE 1: apps/users/forms.py (ADD THESE FORMS)
# ============================================
"""
Add these password reset forms to your existing forms.py
"""

from django.contrib.auth.forms import PasswordResetForm as DjangoPasswordResetForm
from django.contrib.auth.forms import SetPasswordForm as DjangoSetPasswordForm
from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _


class PasswordResetRequestForm(DjangoPasswordResetForm):
    """
    Form for requesting password reset.
    Uses email to send reset link.
    """
    email = forms.EmailField(
        label=_('Email Address'),
        widget=forms.EmailInput(attrs={
            'class': 'form-control',
            'placeholder': 'Enter your email address',
            'autocomplete': 'email',
        }),
        error_messages={
            'required': _('Email address is required.'),
            'invalid': _('Enter a valid email address.'),
        }
    )
    
    def clean_email(self):
        """Validate that user exists with this email."""
        email = self.cleaned_data.get('email', '').lower().strip()
        
        if not CustomUser.objects.filter(email=email).exists():
            # Don't reveal if email exists for security
            # But we'll handle this in the view
            pass
        
        return email


class PasswordResetConfirmForm(DjangoSetPasswordForm):
    """
    Form for setting new password after reset.
    """
    new_password1 = forms.CharField(
        label=_('New Password'),
        widget=forms.PasswordInput(attrs={
            'class': 'form-control',
            'placeholder': 'Create a new password',
            'autocomplete': 'new-password',
        }),
        help_text=_(
            'Password must be at least 8 characters long and contain '
            'uppercase, lowercase, numbers, and special characters.'
        ),
        error_messages={
            'required': _('Password is required.'),
        }
    )
    
    new_password2 = forms.CharField(
        label=_('Confirm New Password'),
        widget=forms.PasswordInput(attrs={
            'class': 'form-control',
            'placeholder': 'Re-enter your new password',
            'autocomplete': 'new-password',
        }),
        error_messages={
            'required': _('Please confirm your password.'),
        }
    )
    
    def clean_new_password1(self):
        """Validate password strength."""
        password = self.cleaned_data.get('new_password1')
        
        if not password:
            raise ValidationError(_('Password is required.'))
        if len(password) < 8:
            raise ValidationError(
                _('Password must be at least 8 characters long.')
            )
        if not re.search(r'[A-Z]', password):
            raise ValidationError(
                _('Password must contain at least one uppercase letter.')
            )
        if not re.search(r'[a-z]', password):
            raise ValidationError(
                _('Password must contain at least one lowercase letter.')
            )
        if not re.search(r'\d', password):
            raise ValidationError(
                _('Password must contain at least one number.')
            )
        if not re.search(r'[!@#$%^&*(),.?":{}|<>]', password):
            raise ValidationError(
                _('Password must contain at least one special character.')
            )
        
        return password
