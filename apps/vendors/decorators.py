"""
Vendor App Decorators
Access control decorators for vendor views
"""

from functools import wraps
from django.shortcuts import redirect
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import HttpResponseForbidden
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
            return redirect('home')  # Or wherever you want to redirect
        
        # User is authenticated and has vendor profile
        return view_func(request, *args, **kwargs)
    
    return wrapper


def vendor_verified_required(view_func):
    """
    Decorator to ensure vendor is fully verified (NIN + BVN verified)
    Redirects to verification center if not verified
    
    Usage:
        @vendor_verified_required
        def add_product(request):
            ...
    """
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        # First check if user is a vendor
        if not request.user.is_authenticated:
            messages.warning(request, 'Please login to access this page.')
            return redirect(f'{reverse("users:login")}?next={request.path}')
        
        if not hasattr(request.user, 'vendorprofile'):
            messages.error(request, 'You need to be a registered vendor.')
            return redirect('home')
        
        vendor = request.user.vendorprofile
        
        # Check if vendor can sell (NIN + BVN verified)
        if not vendor.can_sell:
            messages.warning(
                request, 
                'Please complete identity (NIN) and banking (BVN) verification to access this feature.'
            )
            return redirect('vendors:verification_center')
        
        # Vendor is verified
        return view_func(request, *args, **kwargs)
    
    return wrapper


def vendor_approved_required(view_func):
    """
    Decorator to ensure vendor is fully approved by admin
    More strict than vendor_verified_required
    
    Usage:
        @vendor_approved_required
        def publish_product(request, slug):
            ...
    """
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        # First check if user is a vendor
        if not request.user.is_authenticated:
            messages.warning(request, 'Please login to access this page.')
            return redirect(f'{reverse("users:login")}?next={request.path}')
        
        if not hasattr(request.user, 'vendorprofile'):
            messages.error(request, 'You need to be a registered vendor.')
            return redirect('home')
        
        vendor = request.user.vendorprofile
        
        # Check if vendor is approved
        if not vendor.is_verified:
            messages.warning(
                request,
                'Your vendor account is pending admin approval. You will be notified once approved.'
            )
            return redirect('vendors:verification_center')
        
        # Check if suspended
        if vendor.verification_status == 'suspended':
            messages.error(
                request,
                'Your vendor account has been suspended. Please contact support.'
            )
            return redirect('vendors:dashboard')
        
        # Vendor is approved
        return view_func(request, *args, **kwargs)
    
    return wrapper


def store_setup_required(view_func):
    """
    Decorator to ensure vendor has completed store setup
    Redirects to store setup if not completed
    
    Usage:
        @store_setup_required
        def products_list(request):
            ...
    """
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        # First check if user is a vendor
        if not request.user.is_authenticated:
            messages.warning(request, 'Please login to access this page.')
            return redirect(f'{reverse("users:login")}?next={request.path}')
        
        if not hasattr(request.user, 'vendorprofile'):
            messages.error(request, 'You need to be a registered vendor.')
            return redirect('home')
        
        vendor = request.user.vendorprofile
        
        # Check if store setup is completed
        if not vendor.store_setup_completed:
            messages.info(
                request,
                'Please complete your store setup before accessing this feature.'
            )
            return redirect('vendors:store_setup')
        
        # Store setup is complete
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


def vendor_owns_order(view_func):
    """
    Decorator to ensure vendor owns the order they're trying to access
    Expects 'order_id' in URL kwargs
    
    Usage:
        @vendor_owns_order
        def order_detail(request, order_id):
            ...
    """
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        from .models import Order
        
        # Get order by order_id (UUID)
        order_id = kwargs.get('order_id')
        try:
            order = Order.objects.get(order_id=order_id)
        except Order.DoesNotExist:
            messages.error(request, 'Order not found.')
            return redirect('vendors:orders_list')
        
        # Check ownership
        if order.vendor != request.user.vendorprofile:
            messages.error(request, 'You do not have permission to access this order.')
            return redirect('vendors:orders_list')
        
        # Add order to request
        request.order = order
        
        return view_func(request, *args, **kwargs)
    
    return wrapper


# ==========================================
# COMBINED DECORATORS
# ==========================================

def vendor_verified_and_owns_product(view_func):
    """
    Combined decorator: vendor must be verified AND own the product
    
    Usage:
        @vendor_verified_and_owns_product
        def publish_product(request, slug):
            ...
    """
    @wraps(view_func)
    @vendor_verified_required
    @vendor_owns_product
    def wrapper(request, *args, **kwargs):
        return view_func(request, *args, **kwargs)
    
    return wrapper


# ==========================================
# AJAX/API DECORATORS
# ==========================================

def ajax_vendor_required(view_func):
    """
    Decorator for AJAX views that require vendor authentication
    Returns JSON error instead of redirect
    
    Usage:
        @ajax_vendor_required
        def delete_product_ajax(request):
            ...
    """
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        from django.http import JsonResponse
        
        # Check if user is authenticated
        if not request.user.is_authenticated:
            return JsonResponse({
                'success': False,
                'error': 'Authentication required'
            }, status=401)
        
        # Check if user has vendor profile
        if not hasattr(request.user, 'vendorprofile'):
            return JsonResponse({
                'success': False,
                'error': 'Vendor profile required'
            }, status=403)
        
        return view_func(request, *args, **kwargs)
    
    return wrapper


# ==========================================
# RATE LIMITING DECORATOR
# ==========================================

def rate_limit_verification(view_func):
    """
    Rate limit verification attempts (NIN/BVN)
    Max 3 attempts per hour per vendor
    
    Usage:
        @rate_limit_verification
        def nin_verification_view(request):
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


# ==========================================
# ADMIN ONLY DECORATOR
# ==========================================

def vendor_admin_required(view_func):
    """
    Decorator for views that only admins should access
    Can be used for internal vendor management tools
    
    Usage:
        @vendor_admin_required
        def vendor_analytics(request):
            ...
    """
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        # Check if user is authenticated
        if not request.user.is_authenticated:
            messages.warning(request, 'Please login to access this page.')
            return redirect('users:login')
        
        # Check if user is staff/admin
        if not request.user.is_staff:
            raise PermissionDenied('Admin access required')
        
        return view_func(request, *args, **kwargs)
    
    return wrapper


# ==========================================
# CLASS-BASED VIEW MIXINS (BONUS)
# ==========================================

class VendorRequiredMixin:
    """
    Mixin for class-based views requiring vendor authentication
    
    Usage:
        class DashboardView(VendorRequiredMixin, TemplateView):
            template_name = 'vendors/dashboard.html'
    """
    def dispatch(self, request, *args, **kwargs):
        # Check authentication
        if not request.user.is_authenticated:
            messages.warning(request, 'Please login to access vendor dashboard.')
            return redirect(f'{reverse("users:login")}?next={request.path}')
        
        # Check vendor profile
        if not hasattr(request.user, 'vendorprofile'):
            messages.error(request, 'You need to be a registered vendor.')
            return redirect('home')
        
        return super().dispatch(request, *args, **kwargs)


class VendorVerifiedRequiredMixin:
    """
    Mixin for class-based views requiring verified vendor
    
    Usage:
        class AddProductView(VendorVerifiedRequiredMixin, CreateView):
            model = Product
            ...
    """
    def dispatch(self, request, *args, **kwargs):
        # Check authentication
        if not request.user.is_authenticated:
            messages.warning(request, 'Please login to access this page.')
            return redirect(f'{reverse("users:login")}?next={request.path}')
        
        # Check vendor profile
        if not hasattr(request.user, 'vendorprofile'):
            messages.error(request, 'You need to be a registered vendor.')
            return redirect('home')
        
        # Check verification
        vendor = request.user.vendorprofile
        if not vendor.can_sell:
            messages.warning(
                request,
                'Please complete verification to access this feature.'
            )
            return redirect('vendors:verification_center')
        
        return super().dispatch(request, *args, **kwargs)


class VendorOwnsProductMixin:
    """
    Mixin to ensure vendor owns the product (for UpdateView, DeleteView, etc.)
    
    Usage:
        class ProductUpdateView(VendorOwnsProductMixin, UpdateView):
            model = Product
            ...
    """
    def get_queryset(self):
        """Filter queryset to only vendor's own products"""
        return super().get_queryset().filter(
            vendor=self.request.user.vendorprofile
        )


# ==========================================
# UTILITY FUNCTIONS
# ==========================================

def check_vendor_permissions(user, permission_type='basic'):
    """
    Utility function to check vendor permissions
    Returns (has_permission: bool, redirect_url: str, message: str)
    
    Usage:
        has_perm, redirect_url, msg = check_vendor_permissions(request.user, 'verified')
        if not has_perm:
            messages.warning(request, msg)
            return redirect(redirect_url)
    
    Permission types:
        - 'basic': Just needs vendor profile
        - 'verified': Needs NIN + BVN verified
        - 'approved': Needs admin approval
        - 'store': Needs store setup
    """
    # Check authentication
    if not user.is_authenticated:
        return False, 'users:login', 'Please login to continue.'
    
    # Check vendor profile
    if not hasattr(user, 'vendorprofile'):
        return False, 'users:profile', 'You need to be a registered vendor.'
    
    vendor = user.vendorprofile
    
    # Check permission level
    if permission_type == 'basic':
        return True, None, None
    
    elif permission_type == 'verified':
        if not vendor.can_sell:
            return False, 'vendors:verification_center', 'Please complete verification.'
        return True, None, None
    
    elif permission_type == 'approved':
        if not vendor.is_verified:
            return False, 'vendors:verification_center', 'Waiting for admin approval.'
        return True, None, None
    
    elif permission_type == 'store':
        if not vendor.store_setup_completed:
            return False, 'vendors:store_setup', 'Please complete store setup.'
        return True, None, None
    
    return True, None, None