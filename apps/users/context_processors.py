"""
Context processors for KasuMarketplace users app.
Makes variables available to all templates.
Location: apps/users/context_processors.py
"""

from django.conf import settings


def recaptcha_keys(request):
    """
    Add reCAPTCHA keys to template context.
    Makes RECAPTCHA_PUBLIC_KEY and RECAPTCHA_PRIVATE_KEY available in all templates.
    
    Usage in templates:
        <div class="g-recaptcha" data-sitekey="{{ RECAPTCHA_PUBLIC_KEY }}"></div>
    """
    return {
        'RECAPTCHA_PUBLIC_KEY': getattr(settings, 'RECAPTCHA_PUBLIC_KEY', ''),
        'RECAPTCHA_PRIVATE_KEY': getattr(settings, 'RECAPTCHA_PRIVATE_KEY', ''),
    }


def user_role_context(request):
    """
    Add user role information to template context.
    Makes it easy to check user roles in templates.
    
    Usage in templates:
        {% if is_buyer %}
            <!-- Buyer-specific content -->
        {% endif %}
        
        {% if is_vendor %}
            <!-- Vendor-specific content -->
        {% endif %}
    """
    if request.user.is_authenticated:
        return {
            'is_buyer': request.user.is_buyer,
            'is_vendor': request.user.is_vendor,
            'is_admin': request.user.is_admin_role,
            'user_role': request.user.role,
        }
    return {
        'is_buyer': False,
        'is_vendor': False,
        'is_admin': False,
        'user_role': None,
    }


def site_settings(request):
    """
    Add common site settings to template context.
    
    Usage in templates:
        {{ SITE_NAME }}
        {{ SITE_URL }}
        {{ SUPPORT_EMAIL }}
    """
    return {
        'SITE_NAME': getattr(settings, 'SITE_NAME', 'KasuMarketplace'),
        'SITE_URL': getattr(settings, 'SITE_URL', 'https://kasumarketplace.com'),
        'SUPPORT_EMAIL': getattr(settings, 'SUPPORT_EMAIL', 'support@kasumarketplace.com'),
        'CONTACT_EMAIL': getattr(settings, 'CONTACT_EMAIL', 'contact@kasumarketplace.com'),
    }


def otp_settings(request):
    """
    Add OTP configuration to template context.
    
    Usage in templates:
        Code expires in {{ OTP_EXPIRY_TIME }} minutes
    """
    return {
        'OTP_EXPIRY_TIME': getattr(settings, 'OTP_EXPIRY_TIME', 10),
        'OTP_LENGTH': getattr(settings, 'OTP_LENGTH', 6),
    }
