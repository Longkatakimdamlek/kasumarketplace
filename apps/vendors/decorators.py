"""
Vendor App Decorators
Access control decorators for vendor views

IMPORTANT: the project does not define a URL pattern named "home". earlier
implementations mistakenly redirected there which caused NoReverseMatch errors
(see #issues). All redirects now use '/' or named routes - do **not** revert to
redirect('home').

Phase 9: dead decorators/mixins removed.  Kept (all have real callers in
apps/vendors/views.py): vendor_required, vendor_store_ready_required,
vendor_owns_product, rate_limit_verification.
"""

from functools import wraps
from django.shortcuts import redirect
from django.contrib import messages
from django.urls import reverse


# ==========================================
# VENDOR ACCESS DECORATORS
# ==========================================

def vendor_required(view_func):
    """
    Decorator to ensure user is authenticated and has a vendor profile
    Redirects to login if not authenticated
    Shows error if user is not a vendor
    
    Usage:
        @vendor_required
        def dashboard(request):
            ...
    """
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        # Check if user is authenticated
        if not request.user.is_authenticated:
            messages.warning(request, 'Please login to access vendor dashboard.')
            return redirect(f'{reverse("users:login")}?next={request.path}')
        
        # Check if user has vendor profile
        if not hasattr(request.user, 'vendorprofile'):
            messages.error(request, 'You need to be a registered vendor to access this page.')
            return redirect('/')
        
        # User is authenticated and has vendor profile
        return view_func(request, *args, **kwargs)
    
    return wrapper


def vendor_store_ready_required(view_func):
    """
    Decorator (Phase 6): authenticated + vendor profile + store setup done.

    Product CREATION is gated separately, inside views.product_create, by
    vendor.is_available - that page renders the subscription prompt.

    Usage:
        @vendor_store_ready_required
        def products_list(request):
            ...
    """
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            messages.warning(request, 'Please login to access this page.')
            return redirect(f'{reverse("users:login")}?next={request.path}')

        if not hasattr(request.user, 'vendorprofile'):
            messages.error(request, 'You need to be a registered vendor.')
            return redirect('/')

        if not request.user.vendorprofile.store_setup_completed:
            messages.info(
                request,
                'Please complete your store setup before accessing this feature.'
            )
            return redirect('vendors:store_setup')

        return view_func(request, *args, **kwargs)

    return wrapper


# ==========================================
# OWNERSHIP DECORATORS
# ==========================================

def vendor_owns_product(view_func):
    """
    Decorator to ensure vendor owns the product they're trying to access
    Expects 'slug' or 'pk' in URL kwargs
    
    Usage:
        @vendor_owns_product
        def edit_product(request, slug):
            ...
    """
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        from .models import Product
        
        # Get product by slug or pk
        product = None
        if 'slug' in kwargs:
            try:
                product = Product.objects.get(slug=kwargs['slug'])
            except Product.DoesNotExist:
                messages.error(request, 'Product not found.')
                return redirect('vendors:products_list')
        elif 'pk' in kwargs:
            try:
                product = Product.objects.get(pk=kwargs['pk'])
            except Product.DoesNotExist:
                messages.error(request, 'Product not found.')
                return redirect('vendors:products_list')
        
        # Check ownership
        if product and product.vendor != request.user.vendorprofile:
            messages.error(request, 'You do not have permission to access this product.')
            return redirect('vendors:products_list')
        
        # Add product to request for easy access in view
        request.product = product
        
        return view_func(request, *args, **kwargs)
    
    return wrapper


# ==========================================
# RATE LIMITING DECORATOR
# ==========================================

def rate_limit_verification(view_func):
    """
    Rate limit verification attempts for vendor verification.
    Max 3 attempts per hour per vendor.
    
    Usage:
        @rate_limit_verification
        def some_verification_view(request):
            ...
    """
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        from django.utils import timezone
        from datetime import timedelta
        from .models import VerificationAttempt
        
        vendor = request.user.vendorprofile
        
        # Check attempts in last hour
        one_hour_ago = timezone.now() - timedelta(hours=1)
        recent_attempts = VerificationAttempt.objects.filter(
            vendor=vendor,
            created_at__gte=one_hour_ago
        ).count()
        
        if recent_attempts >= 3:
            messages.error(
                request,
                'Too many verification attempts. Please try again in 1 hour.'
            )
            return redirect('vendors:verification_center')
        
        return view_func(request, *args, **kwargs)
    
    return wrapper
