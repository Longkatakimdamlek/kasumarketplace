from django.http import JsonResponse
from decimal import Decimal, InvalidOperation

"""
Vendor App Views
All views for vendor dashboard, verification, products, store, notifications, etc.
"""

from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
from django.http import HttpResponse
from django.http import Http404
from django.db.models import Sum, Count, Q, Avg
from apps.marketplace.models import Review, Wishlist
from apps.marketplace.services.distance_service import get_distance_to_store
from django.utils import timezone
from django.db.models import F
from django.core.paginator import Paginator
from django.urls import reverse
from django.conf import settings
from decimal import Decimal
from datetime import datetime, date, timedelta
import logging

from .models import (
    VendorProfile, Store, Product, ProductImage,
    MainCategory, SubCategory, SubCategoryAttribute, CategoryChangeRequest,
    Notification, VerificationAttempt, Subscription
)

from .decorators import (
    vendor_required, vendor_verified_required,
    vendor_owns_product,
    rate_limit_verification
)

from .services import dojah_service, notification_service, email_name
from .services.utils import generate_reference, calculate_commission
from .forms import (
    BVNEntryForm,
    BVNSelfieForm,
    CategoryChangeRequestForm,
    StoreSettingsForm,
    StoreSetupForm,
    ProductForm,
    ProductImageFormSet,
)

logger = logging.getLogger(__name__)


def _parse_dojah_date(date_str):
    """
    Dojah's date format is inconsistent across responses observed so far:
      - "1993-05-06"      (ISO format)
      - "01-January-1907" (DD-Month-YYYY)
    Try multiple formats, return None if none match rather than raising -
    a failed date parse should never block the verification outcome itself.
    """
    if not date_str or not date_str.strip():
        return None

    formats_to_try = ['%Y-%m-%d', '%d-%B-%Y', '%d-%b-%Y', '%d-%m-%Y', '%Y/%m/%d']
    for fmt in formats_to_try:
        try:
            return datetime.strptime(date_str.strip(), fmt).date()
        except ValueError:
            continue

    logger.warning(f"Could not parse Dojah date format: {date_str}")
    return None


BVN_SESSION_KEY = 'bvn_pending_verification'
BVN_SESSION_MAX_AGE_SECONDS = 900  # 15 minutes


def _bvn_verification_guard(request, vendor):
    """Shared pre-checks for both BVN verification pages. Returns a response or None."""
    if vendor.bank_status == 'verified':
        messages.info(request, 'Identity already verified')
        return redirect('vendors:verification_center')
    if vendor.bank_status == 'pending_review':
        messages.info(request, 'Your verification is pending review.')
        return redirect('vendors:verification_center')
    failed_attempts_count = VerificationAttempt.objects.filter(
        vendor=vendor, attempt_type='bvn', status='failed'
    ).count()
    if failed_attempts_count >= 3:
        messages.error(
            request,
            "You've reached the maximum number of verification attempts. "
            "Please contact support to continue."
        )
        return render(request, 'vendors/verification/bvn_verification_locked.html', {
            'vendor': vendor, 'hide_verification_badge': True,
        })
    return None


def _store_bvn_session(request, bvn_number):
    request.session[BVN_SESSION_KEY] = {
        'bvn_number': bvn_number,
        'started_at': timezone.now().isoformat(),
    }
    request.session.modified = True


def _get_bvn_session(request):
    data = request.session.get(BVN_SESSION_KEY)
    if not data:
        return None
    started = data.get('started_at')
    if started:
        try:
            started_at = datetime.fromisoformat(started)
            if timezone.is_naive(started_at):
                started_at = timezone.make_aware(started_at)
            if (timezone.now() - started_at).total_seconds() > BVN_SESSION_MAX_AGE_SECONDS:
                del request.session[BVN_SESSION_KEY]
                request.session.modified = True
                return None
        except (ValueError, TypeError):
            pass
    return data


def _clear_bvn_session(request):
    if BVN_SESSION_KEY in request.session:
        del request.session[BVN_SESSION_KEY]
        request.session.modified = True


def _process_bvn_with_selfie(request, vendor, bvn_number, selfie_data_uri):
    """
    Run Dojah BVN+selfie verification and persist vendor identity state.
    Returns a redirect response.
    """
    selfie_base64 = (
        selfie_data_uri.split(',', 1)[-1]
        if ',' in selfie_data_uri else selfie_data_uri
    )

    duplicate_vendor = VendorProfile.objects.filter(
        bvn_number=bvn_number
    ).exclude(id=vendor.id).first()

    if duplicate_vendor:
        vendor.has_duplicate_bvn = True
        vendor.duplicate_bvn_vendor_id = str(duplicate_vendor.vendor_id)
        vendor.save()
        logger.warning(f"Duplicate BVN detected: {bvn_number[-4:]}")
        messages.error(
            request,
            "This BVN is already registered. If this is your BVN, please contact support."
        )
        _clear_bvn_session(request)
        return redirect('vendors:bvn_verification')

    success, data = dojah_service.verify_bvn_with_selfie(bvn_number, selfie_base64)

    if not success:
        VerificationAttempt.objects.create(
            vendor=vendor, attempt_type='bvn', status='failed',
            request_data={'bvn_masked': f'***{bvn_number[-4:]}'},
            response_data={}, error_message=data.get('error', ''),
            ip_address=request.META.get('REMOTE_ADDR'),
            user_agent=request.META.get('HTTP_USER_AGENT', ''),
        )
        messages.error(request, f"Verification failed: {data.get('error', 'Please try again.')}")
        return redirect('vendors:bvn_selfie_capture')

    confidence = data['selfie_confidence']
    auto_threshold = settings.DOJAH_SELFIE_AUTO_VERIFY_THRESHOLD
    review_threshold = settings.DOJAH_SELFIE_REVIEW_THRESHOLD

    if confidence >= auto_threshold:
        attempt_status = 'success'
    elif confidence >= review_threshold:
        attempt_status = 'success'
    else:
        attempt_status = 'failed'

    redacted_data = {k: v for k, v in data.items() if k != 'bvn_number'}
    if 'raw_response' in redacted_data and isinstance(redacted_data['raw_response'], dict):
        redacted_data['raw_response'] = {
            k: v for k, v in redacted_data['raw_response'].items()
            if k != 'bvn'
        }
    VerificationAttempt.objects.create(
        vendor=vendor, attempt_type='bvn', status=attempt_status,
        request_data={'bvn_masked': f'***{bvn_number[-4:]}'},
        response_data=redacted_data,
        ip_address=request.META.get('REMOTE_ADDR'),
        user_agent=request.META.get('HTTP_USER_AGENT', ''),
    )

    vendor.bvn_number = ''  # clear immediately — never retain raw BVN
    vendor.full_name = data['full_name']
    vendor.gender = (data.get('gender') or '').lower()
    vendor.phone = data.get('phone', '')
    vendor.selfie_match = data['selfie_match']
    vendor.selfie_confidence = confidence
    vendor.selfie_image_url = data.get('selfie_image_url', '')
    vendor.bvn_verification_ip = request.META.get('REMOTE_ADDR')

    dob_raw = data.get('dateofbirth', '')
    parsed_dob = _parse_dojah_date(dob_raw)
    if parsed_dob:
        vendor.dob = parsed_dob
        today = date.today()
        age = today.year - parsed_dob.year - (
            (today.month, today.day) < (parsed_dob.month, parsed_dob.day)
        )
        vendor.calculated_age = age
        if age < 18:
            vendor.is_underage = True
            logger.warning(f"Underage vendor detected: {age} years old")

    if confidence >= auto_threshold:
        vendor.bank_status = 'verified'
        vendor.bvn_verified_at = timezone.now()
        outcome_message = 'Identity verified successfully!'
        redirect_target = 'vendors:verification_success'

    else:
        vendor.bank_status = 'failed'
        outcome_message = (
            "We couldn't verify your identity. Please ensure good lighting "
            "and a clear view of your face, then try again."
        )
        redirect_target = 'vendors:bvn_verification'

    vendor.calculate_risk_score()
    vendor.save()
    _clear_bvn_session(request)

    if vendor.bank_status == 'verified':
        try:
            notification_service.send_bvn_verified(vendor)
        except Exception:
            logger.warning('Failed to send BVN verified notification')

    if vendor.bank_status == 'failed':
        messages.error(request, outcome_message)
    else:
        messages.success(request, outcome_message)

    return redirect(redirect_target)


# ==========================================
# PROFILE
# ==========================================

@vendor_required
def profile_view(request):
    """
    View vendor profile (read-only display)
    Shows auto-filled BVN data with masked sensitive info
    """
    vendor = request.user.vendorprofile

    context = {
        'vendor': vendor,
        'hide_verification_badge': True,
    }

    return render(request, 'vendors/profile/view.html', context)


# ==========================================
# DASHBOARD
# ==========================================

def _get_greeting():
    """Return a time-appropriate greeting string."""
    hour = timezone.now().hour
    if hour < 12:
        return 'Good morning'
    elif hour < 17:
        return 'Good afternoon'
    else:
        return 'Good evening'


def _get_display_name(vendor) -> str:
    """Display name = the email name (part before @). Never pulls from the profile."""
    return email_name(vendor)


@vendor_required
def dashboard(request):
    """
    Main vendor dashboard with stats and overview
    """
    vendor = request.user.vendorprofile

    # Safely get the vendor's store if it exists
    try:
        store = vendor.store
    except Store.DoesNotExist:
        store = None

    # Published products queryset (reused below)
    published_products = vendor.products.filter(status='published')

    # Subscription status
    subscription = None
    try:
        subscription = vendor.subscription
    except Subscription.DoesNotExist:
        pass

    # Aggregate stats
    total_products = published_products.count()
    total_views = published_products.aggregate(s=Sum('views_count'))['s'] or 0
    total_wishlists = Wishlist.objects.filter(
        product__vendor=vendor,
        product__status='published',
    ).count()
    if store:
        avg_rating = store.average_rating
    else:
        avg_rating = published_products.aggregate(
            avg=Avg('average_rating')
        )['avg'] or 0

    context = {
        'vendor': vendor,
        'store': store,
        'total_products': total_products,
        'total_views': total_views,
        'total_wishlists': total_wishlists,
        'avg_rating': round(float(avg_rating), 1),
        'subscription': subscription,
        'greeting': _get_greeting(),
        'display_name': _get_display_name(vendor),
        'today': timezone.localdate(),
        'storefront_url': store.get_absolute_url() if store else reverse('vendors:products_list'),

        # Low stock products
        'low_stock_products': published_products.filter(
            track_inventory=True,
            stock_quantity__lte=5
        )[:5],
    }

    # Show verification banner if not verified
    if not vendor.can_sell:
        messages.info(
            request,
            f'Complete verification to start selling. Progress: {vendor.completion_percentage}%'
        )

    context['hide_verification_badge'] = True
    return render(request, 'vendors/dashboard.html', context)


@vendor_required
def vendor_wishlist(request):
    """
    Dedicated wishlist page showing vendor's products that have been wishlisted.
    Displays aggregate counts only — no buyer-identifying information.
    """
    vendor = request.user.vendorprofile

    products_with_wishlists = (
        Product.objects
        .filter(vendor=vendor, status='published')
        .annotate(wishlist_count=Count('wishlisted_by'))
        .filter(wishlist_count__gt=0)
        .order_by('-wishlist_count')
    )

    context = {
        'vendor': vendor,
        'products': products_with_wishlists,
        'total_wishlists': Wishlist.objects.filter(
            product__vendor=vendor,
            product__status='published',
        ).count(),
        'hide_verification_badge': True,
    }

    return render(request, 'vendors/wishlist.html', context)


@vendor_required
def vendor_reviews(request):
    """
    Dedicated reviews page showing all reviews for the vendor's published products.
    Displays reviewer display name, initial-based avatar, rating, comment, date, and product.
    """
    vendor = request.user.vendorprofile

    reviews = (
        Review.objects
        .filter(product__vendor=vendor, product__status='published')
        .select_related('user', 'product', 'product__store')
        .order_by('-created_at')
    )

    total_reviews = reviews.count()
    avg_rating = reviews.aggregate(avg=Avg('rating'))['avg'] or 0

    context = {
        'vendor': vendor,
        'reviews': reviews,
        'total_reviews': total_reviews,
        'avg_rating': round(float(avg_rating), 1),
        'hide_verification_badge': True,
    }

    return render(request, 'vendors/reviews.html', context)


# ==========================================
# VERIFICATION VIEWS
# ==========================================

@vendor_required
def verification_center(request):
    """
    Verification center - shows progress and next steps.
    2 steps: BVN+selfie -> Store setup.
    """
    vendor = request.user.vendorprofile

    # If already approved, redirect to dashboard
    if vendor.is_verified:
        messages.success(request, "You're already verified!")
        return redirect('vendors:dashboard')

    def _bvn_badge(s):
        if s == 'verified':
            return 'completed', 'Verified'
        if s == 'pending_review':
            return 'in_progress', 'Pending Review'
        if s == 'failed':
            return 'failed', 'Failed'
        return 'not_started', 'Not Started'

    bvn_badge_status, bvn_status_label = _bvn_badge(vendor.bank_status)

    # Lock logic: each step after BVN is locked until the prior step is done.
    bvn_done = vendor.bank_status == 'verified'
    store_done = vendor.store_setup_completed or vendor.store_setup_skipped

    step1_status = bvn_badge_status
    step2_status = 'completed' if store_done else 'not_started'

    steps = [
        {
            'number': 1,
            'name': 'Verify Your Identity',
            'title': 'Verify Your Identity',
            'description': 'Enter your BVN, then take a live selfie to verify your identity.',
            'status': step1_status,
            'status_label': bvn_status_label,
            'completed': bvn_done,
            'completed_at': vendor.bvn_verified_at,
            'note': (
                "Your verification is awaiting manual review."
                if vendor.bank_status == 'pending_review' else None
            ),
            'url': 'vendors:bvn_verification',
            'skip_url': 'vendors:store_setup',
            'verification_type': 'bvn',
            'icon': '''<svg class="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                         <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M3 10h18M7 15h1m4 0h1m-7 4h12a3 3 0 003-3V8a3 3 0 00-3-3H6a3 3 0 00-3 3v8a3 3 0 003 3z"/>
                       </svg>'''
        },
        {
            'number': 2,
            'name': 'Set Up Your Store',
            'title': 'Set Up Your Store',
            'description': 'Add your store name, branding, contact details, and pick a category for your products.',
            'status': step2_status,
            'status_label': 'Completed' if store_done else 'Not Started',
            'completed': store_done,
            'completed_at': None,
            'note': None,
            'url': 'vendors:store_setup',
            'icon': '''<svg class="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                         <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 21V5a2 2 0 00-2-2H7a2 2 0 00-2 2v16m14 0h2m-2 0h-5m-9 0H3m2 0h5M9 7h1m-1 4h1m4-4h1m-1 4h1m-5 10v-5a1 1 0 011-1h2a1 1 0 011 1v5m-4 0h4"/>
                       </svg>'''
        }
    ]

    context = {
        'vendor': vendor,
        'steps': steps,
        'completion_percentage': vendor.completion_percentage,
        'current_step': vendor.current_step,
        'can_sell': vendor.can_sell,
        'hide_verification_badge': True,
    }

    return render(request, 'vendors/verification/center.html', context)


@vendor_required
@rate_limit_verification
def bvn_verification(request):
    """
    Page 1 of 2: BVN number and consent.
    Stores details in session and sends vendor to the selfie capture page.
    """
    vendor = request.user.vendorprofile

    guard = _bvn_verification_guard(request, vendor)
    if guard:
        return guard

    if request.method == 'POST':
        form = BVNEntryForm(request.POST)
        if form.is_valid():
            vendor.bvn_consent_given = True
            vendor.bvn_consent_timestamp = timezone.now()
            vendor.save(update_fields=['bvn_consent_given', 'bvn_consent_timestamp'])
            _store_bvn_session(
                request,
                form.cleaned_data['bvn_number'],
            )
            return redirect('vendors:bvn_selfie_capture')
        messages.error(request, 'Please correct the errors below.')
    else:
        form = BVNEntryForm()

    return render(request, 'vendors/verification/bvn_verification.html', {
        'form': form,
        'vendor': vendor,
        'hide_verification_badge': True,
    })


@vendor_required
@rate_limit_verification
def bvn_selfie_capture(request):
    """
    Page 2 of 2: MediaPipe live selfie capture with auto-submit to Dojah.
    BVN is read from session (set on page 1).
    """
    vendor = request.user.vendorprofile

    guard = _bvn_verification_guard(request, vendor)
    if guard:
        return guard

    session_data = _get_bvn_session(request)
    if not session_data:
        messages.warning(request, 'Please enter your BVN first.')
        return redirect('vendors:bvn_verification')

    if request.method == 'POST':
        form = BVNSelfieForm(request.POST)
        if form.is_valid():
            return _process_bvn_with_selfie(
                request,
                vendor,
                session_data['bvn_number'],
                form.cleaned_data['selfie_image'],
            )
        messages.error(request, 'Selfie capture failed. Please try again.')
    else:
        form = BVNSelfieForm()

    bvn_number = session_data['bvn_number']
    return render(request, 'vendors/verification/bvn_selfie_capture.html', {
        'form': form,
        'vendor': vendor,
        'bvn_masked': f'***{bvn_number[-4:]}',
        'hide_verification_badge': True,
    })


@vendor_required
def store_setup(request):
    """
    Store creation — minimal setup page.
    """
    vendor = request.user.vendorprofile

    try:
        store = vendor.store
        return redirect('vendors:store_settings')
    except Store.DoesNotExist:
        store = None

    if request.method == 'POST':
        form = StoreSetupForm(request.POST, instance=store, vendor=vendor)

        if form.is_valid():
            store = form.save()
            vendor.store_setup_completed = True
            vendor.save()

            messages.success(request, 'Store created successfully.')
            return redirect('vendors:store_settings')
    else:
        form = StoreSetupForm(instance=store, vendor=vendor)
        if vendor.phone:
            form.initial['phone'] = vendor.phone

    context = {
        'form': form,
        'vendor': vendor,
        'hide_verification_badge': True,
    }

    return render(request, 'vendors/verification/store_setup.html', context)


@vendor_required
def verification_success(request):
    """
    Dedicated success screen shown after auto-verify (confidence ≥ 90%).
    Redirects away if vendor isn't actually verified — prevents direct URL access
    before verification is complete.
    """
    vendor = request.user.vendorprofile
 
    if vendor.bank_status != 'verified':
        return redirect('vendors:verification_center')
 
    return render(request, 'vendors/verification/verification_success.html', {
        'vendor': vendor,
        'hide_verification_badge': True,
    })

# ==========================================
# PRODUCT VIEWS
# ==========================================

@vendor_verified_required
def products_list(request):
    """List all vendor products with filters and stock status"""
    vendor = request.user.vendorprofile

    # Filters
    status = request.GET.get('status', '')
    stock_filter = request.GET.get('stock', '')
    search = request.GET.get('search', '')

    products = vendor.products.all()

    # Apply filters
    if status:
        products = products.filter(status=status)

    if stock_filter == 'low_stock':
        products = products.filter(
            track_inventory=True,
            stock_quantity__gt=0,
            stock_quantity__lte=F('low_stock_threshold')
        )
    elif stock_filter == 'out_of_stock':
        products = products.filter(track_inventory=True, stock_quantity=0)

    if search:
        products = products.filter(
            Q(title__icontains=search) |
            Q(description__icontains=search) |
            Q(sku__icontains=search)
        )

    products = products.order_by('-created_at')

    # Pagination
    paginator = Paginator(products, 20)
    page_obj = paginator.get_page(request.GET.get('page'))

    context = {
        'products': page_obj,
        'total_products': vendor.products.count(),
        'published_count': vendor.products.filter(status='published').count(),
        'draft_count': vendor.products.filter(status='draft').count(),
        'low_stock_count': vendor.products.filter(
            track_inventory=True,
            stock_quantity__gt=0,
            stock_quantity__lte=F('low_stock_threshold')
        ).count(),
        'out_of_stock_count': vendor.products.filter(
            track_inventory=True,
            stock_quantity=0
        ).count(),
        'current_status': status,
        'stock_filter': stock_filter,
        'search_query': search,
        'hide_verification_badge': True,
    }

    return render(request, 'vendors/products/list.html', context)


@vendor_verified_required
def product_create(request):
    """Create new product with dynamic attributes and images"""
    vendor = request.user.vendorprofile

    if not hasattr(vendor, 'store'):
        messages.warning(request, 'Please complete store setup first')
        return redirect('vendors:store_setup')

    if request.method == 'POST':
        subcategory_id = request.POST.get('subcategory')
        form = ProductForm(
            request.POST,
            request.FILES,
            vendor=vendor,
            subcategory_id=subcategory_id,
            is_editing=False
        )
        temp_product = Product()
        formset = ProductImageFormSet(request.POST, request.FILES, instance=temp_product)

        if 'status' in request.POST and request.POST['status'] == 'discontinued':
            messages.error(request, '❌ You cannot set a new product as discontinued.')
            form.add_error('status', 'Products can only be discontinued after creation.')

        if form.is_valid() and formset.is_valid():
            try:
                product = form.save()

                formset.instance = product
                formset.save()

                if not product.images.filter(is_primary=True).exists():
                    first_image = product.images.first()
                    if first_image:
                        first_image.is_primary = True
                        first_image.save()

                messages.success(request, f'✅ Product "{product.title}" created successfully!')
                return redirect('vendors:product_detail', slug=product.slug)

            except Exception as e:
                messages.error(request, f'❌ Error: {str(e)}')
                import traceback
                print(traceback.format_exc())
        else:
            messages.error(request, '❌ Please correct the errors below.')
    else:
        form = ProductForm(vendor=vendor, is_editing=False)
        formset = ProductImageFormSet(instance=Product())

    subcategories = SubCategory.objects.filter(
        main_category=vendor.store.main_category,
        is_active=True
    ).order_by('name')

    context = {
        'form': form,
        'formset': formset,
        'vendor': vendor,
        'subcategories': subcategories,
        'hide_verification_badge': True,
    }

    return render(request, 'vendors/products/create.html', context)


@vendor_verified_required
@vendor_owns_product
def product_edit(request, slug):
    """Edit existing product"""
    product = request.product
    vendor = request.user.vendorprofile


    if request.method == 'POST':
        form = ProductForm(
            request.POST,
            request.FILES,
            instance=product,
            vendor=vendor,
            is_editing=True
        )
        formset = ProductImageFormSet(request.POST, request.FILES, instance=product)

        if form.is_valid() and formset.is_valid():
            product = form.save()
            formset.save()

            messages.success(request, '✅ Product updated successfully!')
            return redirect('vendors:product_detail', slug=product.slug)
        else:
            messages.error(request, '❌ Please correct the errors below.')
    else:
        form = ProductForm(
            instance=product,
            vendor=vendor,
            is_editing=True
        )
        formset = ProductImageFormSet(instance=product)

    import json
    subcategories = SubCategory.objects.filter(
        main_category=vendor.store.main_category,
        is_active=True
    ).values('id', 'name').order_by('name')

    current_attributes = SubCategoryAttribute.objects.filter(
        subcategory=product.subcategory,
        is_active=True
    ).order_by('sort_order')

    attributes_json = json.dumps([
        {
            "id": attr.id,
            "name": attr.name,
            "field_type": attr.field_type,
            "options": attr.options if isinstance(attr.options, list) else [],
            "is_required": attr.is_required,
            "placeholder": attr.placeholder,
            "help_text": attr.help_text,
            "current_value": product.attributes.get(str(attr.id)) if product.attributes else ""
        }
        for attr in current_attributes
    ])

    context = {
        'form': form,
        'formset': formset,
        'product': product,
        'vendor': vendor,
        'is_editing': True,
        'subcategories': list(subcategories),
        'subcategories_json': json.dumps(list(subcategories)),
        'attributes_json': attributes_json,
        'hide_verification_badge': True,
    }

    return render(request, 'vendors/products/edit.html', context)


@vendor_verified_required
@vendor_owns_product
def product_delete(request, slug):
    """Delete product"""
    product = request.product

    if request.method == 'POST':
        title = product.title
        product.delete()

        messages.success(request, f'🗑️ Product "{title}" deleted successfully')
        return redirect('vendors:products_list')

    context = {
        'product': product,
        'hide_verification_badge': True,
    }

    return render(request, 'vendors/products/delete_confirm.html', context)


@vendor_verified_required
@vendor_owns_product
def product_detail(request, slug):
    """View product details"""
    product = request.product
    vendor = request.user.vendorprofile

    context = {
        'product': product,
        'vendor': vendor,
        'hide_verification_badge': True,
    }

    return render(request, 'vendors/products/detail.html', context)

# ==========================================
# PUBLIC BUYER PRODUCT DETAIL
# ==========================================

def product_detail_public(request, store_slug, product_slug):
    """
    Public-facing product detail page for buyers

    URL: /shop/<store_slug>/products/<product_slug>/
    """
    try:
        store = Store.objects.get(slug=store_slug)
    except Store.DoesNotExist:
        raise Http404("No Store matches the given query.")

    is_owner = (
        request.user.is_authenticated and
        hasattr(request.user, 'vendorprofile') and
        request.user.vendorprofile == store.vendor
    )

    if not store.is_publicly_visible and not is_owner:
        raise Http404("No Store matches the given query.")

    product_qs = Product.objects.filter(slug=product_slug, store=store)
    if not is_owner:
        product_qs = product_qs.filter(status='published')
    product = get_object_or_404(product_qs)

    product.views_count = F('views_count') + 1
    product.save(update_fields=['views_count'])
    product.refresh_from_db()

    try:
        from apps.marketplace.models import ProductView
        user = request.user if request.user.is_authenticated else None
        session_key = ''
        if not user:
            if not request.session.session_key:
                request.session.create()
            session_key = request.session.session_key
        if not is_owner:
            ProductView.objects.create(
                user=user,
                session_key=session_key,
                product=product,
                store=store,
            )
    except Exception:
        logger.exception("Failed to create ProductView")

    VIEW_MILESTONES = {100, 500, 1000, 5000, 10000}
    if product.views_count in VIEW_MILESTONES:
        try:
            from apps.vendors.services.notification_dispatch import create_notification
            create_notification(
                user=store.vendor.user,
                notification_type='system',
                title=f'Product View Milestone — {product.views_count:,} Views! 📊',
                message=(
                    f'Your product "{product.title}" has reached '
                    f'{product.views_count:,} views. Great job!'
                ),
                link=f'/vendors/products/{product.slug}/',
                in_app_only=True,
                vendor=store.vendor,
            )
        except Exception:
            logger.exception("Failed to send view milestone notification")

    attributes = SubCategoryAttribute.objects.filter(
        subcategory=product.subcategory,
        is_active=True
    ).order_by('sort_order')

    specifications = []
    for attr in attributes:
        value = product.attributes.get(str(attr.id))
        if value:
            specifications.append({
                'label': attr.name.replace('_', ' ').title(),
                'value': value,
                'field_type': attr.field_type
            })
    buyer_lat = request.session.get('buyer_lat')
    buyer_lon = request.session.get('buyer_lon')

    reviews = Review.objects.filter(
        product=product
    ).select_related('user').order_by('-created_at')
    user_review = None
    can_review = False
    if request.user.is_authenticated and not is_owner:
        user_review = reviews.filter(user=request.user).first()
        if not user_review:
            can_review = True

    is_wishlisted = False
    if not is_owner:
        if request.user.is_authenticated:
            is_wishlisted = Wishlist.objects.filter(
                user=request.user, product=product
            ).exists()
        else:
            # Check session-based guest wishlist
            session_key = request.session.session_key
            if session_key:
                is_wishlisted = Wishlist.objects.filter(
                    session_key=session_key, product=product
                ).exists()

    related_products = Product.objects.publicly_visible().filter(
        subcategory=product.subcategory,
    ).exclude(pk=product.pk)[:4]

    if related_products.count() < 4:
        extra_needed = 4 - related_products.count()
        extra = Product.objects.publicly_visible().filter(
            store=store,
        ).exclude(pk=product.pk).exclude(
            pk__in=[related.pk for related in related_products]
        )[:extra_needed]
        related_products = list(related_products) + list(extra)

    context = {
        'product': product,
        'store': store,
        'vendor': store.vendor,
        'specifications': specifications,
        'is_owner': is_owner,
        'is_preview': not store.is_published and is_owner,
        'in_stock': product.is_in_stock,
        'distance': get_distance_to_store(buyer_lat, buyer_lon, store),
        'reviews': reviews,
        'user_review': user_review,
        'can_review': can_review,
        'is_wishlisted': is_wishlisted,
        'related_products': related_products,
    }

    return render(request, 'products/product_detail.html', context)


@login_required
@require_http_methods(["POST"])
def submit_review(request, store_slug, product_slug):
    """AJAX: buyer submits a star rating and optional comment."""
    product = get_object_or_404(
        Product,
        slug=product_slug,
        store__slug=store_slug,
        status='published',
    )

    if Review.objects.filter(user=request.user, product=product).exists():
        return JsonResponse(
            {'success': False, 'message': 'You already reviewed this product.'},
            status=400,
        )

    try:
        rating = int(request.POST.get('rating', 0))
    except (ValueError, TypeError):
        rating = 0

    if rating < 1 or rating > 5:
        return JsonResponse(
            {'success': False, 'message': 'Please select a star rating.'},
            status=400,
        )

    Review.objects.create(
        user=request.user,
        product=product,
        rating=rating,
        comment=request.POST.get('comment', '').strip(),
    )
    return JsonResponse({'success': True, 'message': 'Review submitted. Thank you!'})


@require_http_methods(["POST"])
def toggle_wishlist(request, store_slug, product_slug):
    """AJAX: toggle a product in or out of the buyer's wishlist.

    Supports both authenticated users and anonymous guests via session key.
    """
    product = get_object_or_404(
        Product,
        slug=product_slug,
        store__slug=store_slug,
        status='published',
    )

    if request.user.is_authenticated:
        existing = Wishlist.objects.filter(user=request.user, product=product).first()
        if existing:
            existing.delete()
            count = Wishlist.objects.filter(user=request.user).count()
            return JsonResponse({
                'success': True,
                'wishlisted': False,
                'wishlist_count': count,
                'message': f'"{product.title}" removed from wishlist.',
            })
        Wishlist.objects.create(user=request.user, product=product)
        count = Wishlist.objects.filter(user=request.user).count()
        try:
            from apps.vendors.services.notification_dispatch import create_notification
            create_notification(
                user=product.store.vendor.user,
                notification_type='wishlist',
                title='Product Wishlisted! ❤️',
                message=(
                    f'{request.user.email} added "{product.title}" to their wishlist. '
                    f'Your product is getting attention!'
                ),
                link=f'/vendors/products/{product.slug}/',
                vendor=product.store.vendor,
            )
        except Exception:
            logger.exception("Failed to send wishlist vendor notification")
        return JsonResponse({
            'success': True,
            'wishlisted': True,
            'wishlist_count': count,
            'message': f'"{product.title}" added to wishlist.',
        })
    else:
        # Anonymous guest — use session key
        if not request.session.session_key:
            request.session.create()
        session_key = request.session.session_key
        existing = Wishlist.objects.filter(session_key=session_key, product=product).first()
        if existing:
            existing.delete()
            count = Wishlist.objects.filter(session_key=session_key).count()
            return JsonResponse({
                'success': True,
                'wishlisted': False,
                'wishlist_count': count,
                'message': f'"{product.title}" removed from wishlist.',
            })
        Wishlist.objects.create(session_key=session_key, product=product)
        count = Wishlist.objects.filter(session_key=session_key).count()
        return JsonResponse({
            'success': True,
            'wishlisted': True,
            'wishlist_count': count,
            'message': f'"{product.title}" added to wishlist.',
        })


# ==========================================
# AJAX ENDPOINTS FOR DYNAMIC FORMS
# ==========================================

@vendor_required
def ajax_get_subcategories(request):
    """Get subcategories for vendor's main category"""
    vendor = request.user.vendorprofile

    if not hasattr(vendor, 'store'):
        return JsonResponse({'subcategories': []})

    subcategories = SubCategory.objects.filter(
        main_category=vendor.store.main_category,
        is_active=True
    ).values('id', 'name').order_by('name')

    return JsonResponse({
        'subcategories': list(subcategories)
    })


@vendor_required
def ajax_get_attributes(request):
    """Get attributes for a specific subcategory"""
    subcategory_id = request.GET.get('subcategory_id')

    if not subcategory_id:
        return JsonResponse({'attributes': []})

    attributes = SubCategoryAttribute.objects.filter(
        subcategory_id=subcategory_id,
        is_active=True
    ).order_by('sort_order')

    attrs_data = []
    for attr in attributes:
        attrs_data.append({
            'id': attr.id,
            'name': attr.name,
            'field_type': attr.field_type,
            'is_required': attr.is_required,
            'placeholder': attr.placeholder,
            'help_text': attr.help_text,
            'options': attr.options if attr.field_type == 'dropdown' else []
        })

    return JsonResponse({'attributes': attrs_data})


# ==========================================
# STORE SETTINGS VIEWS
# ==========================================

@vendor_required
def store_settings(request):
    """
    Store settings — clean, single-page form for all store fields.
    Enforces 1-year limit on store name and category changes.
    """
    vendor = request.user.vendorprofile

    try:
        store = vendor.store
    except Store.DoesNotExist:
        messages.warning(request, 'Please complete store setup first')
        return redirect('vendors:store_setup')

    if request.method == 'POST':
        form = StoreSettingsForm(request.POST, request.FILES, instance=store)

        if form.is_valid():
            old_store_name = store.store_name
            new_store_name = form.cleaned_data.get('store_name')

            store = form.save()

            if old_store_name != new_store_name:
                logger.warning(
                    f"STORE NAME CHANGED: '{old_store_name}' -> '{new_store_name}' "
                    f"(Vendor: {vendor.full_name}, Change #{store.store_name_change_count})"
                )
                messages.success(
                    request,
                    f'Store name changed to "{new_store_name}". '
                    f'You can change it again after {(store.store_name_last_changed_at + timezone.timedelta(days=365)).strftime("%B %d, %Y")}.'
                )
            else:
                messages.success(request, 'Store settings updated.')

            return redirect('vendors:store_public', slug=store.slug)
        else:
            messages.error(request, 'Please correct the errors below.')
    else:
        form = StoreSettingsForm(instance=store)

    active_products_count = vendor.products.filter(status='published').count()

    context = {
        'store': store,
        'form': form,
        'vendor': vendor,
        'active_products_count': active_products_count,
        'hide_verification_badge': True,
    }

    return render(request, 'vendors/store/settings.html', context)


# ==========================================
# STORE PUBLIC PREVIEW VIEW FOR VENDORS
# ==========================================
@vendor_required
def store_public_preview(request):
    """
    Preview public storefront
    """
    vendor = request.user.vendorprofile

    try:
        store = vendor.store
    except Store.DoesNotExist:
        messages.warning(request, 'Store not set up yet')
        return redirect('vendors:store_setup')

    products = vendor.products.filter(status='published')[:12]

    context = {
        'store': store,
        'products': products,
        'is_preview': True,
        'hide_verification_badge': True,
    }

    return render(request, 'vendors/store/preview.html', context)


# ==========================================
# CATEGORY CHANGE REQUEST VIEWS
# ==========================================

@vendor_required
def category_change_request(request):
    """
    Request to change locked main category
    Enforces 1-YEAR LIMIT on category change requests
    """
    vendor = request.user.vendorprofile

    try:
        store = vendor.store
    except Store.DoesNotExist:
        messages.warning(request, 'Store not set up yet')
        return redirect('vendors:store_setup')

    if not store.main_category_locked:
        messages.info(request, 'Your category is not locked yet. You can change it in store settings.')
        return redirect('vendors:store_settings')

    if not store.can_request_category_change():
        days_left = store.days_until_next_category_change()
        next_change_date = (
            store.main_category_last_changed_at + timezone.timedelta(days=365)
        ).strftime('%B %d, %Y')

        messages.warning(
            request,
            f'🔒 Category change requests are limited to once per year. '
            f'You can submit a new request on {next_change_date} ({days_left} days remaining).'
        )
        return redirect('vendors:store_settings')

    pending_request = CategoryChangeRequest.objects.filter(
        store=store,
        status='pending'
    ).first()

    if pending_request:
        messages.info(
            request,
            f'You already have a pending category change request '
            f'(from {pending_request.current_category.name} to {pending_request.requested_category.name}). '
            f'Please wait for admin review.'
        )
        return redirect('vendors:store_settings')

    if request.method == 'POST':
        form = CategoryChangeRequestForm(request.POST, store=store)

        if form.is_valid():
            change_request = form.save()

            logger.info(
                f"📋 Category change request submitted: {store.store_name} "
                f"({change_request.current_category.name} → {change_request.requested_category.name})"
            )

            messages.success(
                request,
                f'✅ Category change request submitted successfully! '
                f'We will review your request to change from "{change_request.current_category.name}" '
                f'to "{change_request.requested_category.name}" and notify you via email.'
            )
            return redirect('vendors:store_settings')
        else:
            messages.error(request, '❌ Please correct the errors below.')
    else:
        form = CategoryChangeRequestForm(store=store)

    previous_requests = CategoryChangeRequest.objects.filter(
        store=store
    ).exclude(status='pending').order_by('-created_at')[:5]

    context = {
        'form': form,
        'store': store,
        'vendor': vendor,
        'previous_requests': previous_requests,
        'can_request_change': store.can_request_category_change(),
        'days_until_next_change': store.days_until_next_category_change(),
        'hide_verification_badge': True,
    }

    return render(request, 'vendors/store/category_change_request.html', context)


@vendor_required
def category_change_status(request):
    """
    View status of category change requests
    """
    vendor = request.user.vendorprofile

    try:
        store = vendor.store
    except Store.DoesNotExist:
        messages.warning(request, 'Store not set up yet')
        return redirect('vendors:store_setup')

    all_requests = CategoryChangeRequest.objects.filter(
        store=store
    ).order_by('-created_at')

    pending_requests = all_requests.filter(status='pending')
    approved_requests = all_requests.filter(status='approved')
    rejected_requests = all_requests.filter(status='rejected')

    context = {
        'store': store,
        'vendor': vendor,
        'pending_requests': pending_requests,
        'approved_requests': approved_requests,
        'rejected_requests': rejected_requests,
        'can_request_change': store.can_request_category_change(),
        'days_until_next_change': store.days_until_next_category_change(),
        'hide_verification_badge': True,
    }

    return render(request, 'vendors/store/category_change_status.html', context)


def approve_category_change(category_request_id, admin_user):
    """
    Helper function to approve category change request
    Called from admin panel action
    """
    try:
        change_request = CategoryChangeRequest.objects.get(id=category_request_id)

        if change_request.status != 'pending':
            return False, f'Request is already {change_request.status}'

        store = change_request.store
        old_category = store.main_category
        new_category = change_request.requested_category

        store.main_category = new_category
        store.main_category_last_changed_at = timezone.now()
        store.main_category_change_count = (store.main_category_change_count or 0) + 1
        store.save()

        change_request.status = 'approved'
        change_request.reviewed_by = admin_user
        change_request.reviewed_at = timezone.now()
        change_request.save()

        logger.info(
            f"✅ Category change APPROVED: {store.store_name} "
            f"({old_category.name} → {new_category.name}) by {admin_user.email}"
        )

        return True, f'Category changed from {old_category.name} to {new_category.name}'

    except CategoryChangeRequest.DoesNotExist:
        return False, 'Category change request not found'
    except Exception as e:
        logger.error(f'Error approving category change: {str(e)}')
        return False, f'Error: {str(e)}'


def reject_category_change(category_request_id, admin_user, reason=''):
    """
    Helper function to reject category change request
    Called from admin panel action
    """
    try:
        change_request = CategoryChangeRequest.objects.get(id=category_request_id)

        if change_request.status != 'pending':
            return False, f'Request is already {change_request.status}'

        change_request.status = 'rejected'
        change_request.reviewed_by = admin_user
        change_request.reviewed_at = timezone.now()
        if reason:
            change_request.admin_comment = reason
        change_request.save()

        logger.info(
            f"❌ Category change REJECTED: {change_request.store.store_name} "
            f"({change_request.current_category.name} → {change_request.requested_category.name}) "
            f"by {admin_user.email}"
        )

        return True, 'Category change request rejected'

    except CategoryChangeRequest.DoesNotExist:
        return False, 'Category change request not found'
    except Exception as e:
        logger.error(f'Error rejecting category change: {str(e)}')
        return False, f'Error: {str(e)}'

def get_store_change_summary(store):
    """
    Get summary of store changes for display
    """
    return {
        'can_change_name': store.can_change_store_name(),
        'days_until_name_change': store.days_until_next_name_change(),
        'name_change_count': store.store_name_change_count or 0,
        'name_last_changed': store.store_name_last_changed_at,
        'original_name': store.original_store_name,

        'can_change_category': store.can_request_category_change(),
        'days_until_category_change': store.days_until_next_category_change(),
        'category_change_count': store.main_category_change_count or 0,
        'category_last_changed': store.main_category_last_changed_at,
        'original_category': store.original_main_category,
        'category_locked': store.main_category_locked,
    }


def check_vendor_can_edit_profile(vendor):
    """
    Check what profile fields vendor can edit
    """
    return {
        'cannot_edit': {
            'full_name': 'Verified from BVN',
            'email': 'Account email',
            'bvn_number': 'Verified identity',
            'dob': 'From BVN',
            'gender': 'From BVN',
            'primary_phone': 'From BVN',
        },

        'can_edit': {
            'alternative_phone': 'Backup contact',
            'whatsapp': 'WhatsApp contact',
        },

        'special': {
            'store_name': {
                'can_edit': vendor.store.can_change_store_name() if hasattr(vendor, 'store') else False,
                'reason': 'Once per year limit',
            },
            'main_category': {
                'can_edit': False,
                'reason': 'Requires admin approval',
            }
        }
    }

# ==========================================
# PUBLIC STOREFRONT VIEW
# ==========================================================================

def store_public(request, slug):
    """
    Public-facing store (accessible to customers)
    No login required
    """
    try:
        store = Store.objects.get(slug=slug)
    except Store.DoesNotExist:
        raise Http404("No Store matches the given query.")

    is_owner = (request.user.is_authenticated and
                hasattr(request.user, 'vendorprofile') and
                request.user.vendorprofile == store.vendor)

    if not store.is_publicly_visible and not is_owner:
        raise Http404("No Store matches the given query.")

    all_products = store.vendor.products.filter(status='published').order_by('-created_at')
    total_products_count = all_products.count()  # computed BEFORE any filter is applied

    # ---- Sidebar data: subcategories under this store's locked main category ----
    subcategories = SubCategory.objects.filter(
        main_category=store.main_category,
        is_active=True
    ).order_by('name')

    products = all_products

    # ---- Filter: subcategory ----
    selected_subcategory_id = request.GET.get('subcategory')
    if selected_subcategory_id:
        products = products.filter(subcategory_id=selected_subcategory_id)

    # ---- Filter: price range ----
    min_price_raw = request.GET.get('min_price', '').strip()
    max_price_raw = request.GET.get('max_price', '').strip()
    min_price = None
    max_price = None
    try:
        if min_price_raw:
            min_price = Decimal(min_price_raw)
            products = products.filter(price__gte=min_price)
        if max_price_raw:
            max_price = Decimal(max_price_raw)
            products = products.filter(price__lte=max_price)
    except InvalidOperation:
        pass  # ignore malformed price input rather than 500ing

    # ---- Filter: availability ----
    in_stock_only = request.GET.get('in_stock') == '1'
    if in_stock_only:
        products = products.filter(
            Q(track_inventory=False) | Q(stock_quantity__gt=0)
        )

    from django.core.paginator import Paginator
    paginator = Paginator(products, 12)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    from apps.marketplace.services.distance_service import get_distance_to_store
    from apps.marketplace.views import get_wishlisted_ids
    buyer_lat = request.session.get('buyer_lat')
    buyer_lon = request.session.get('buyer_lon')

    # Sponsored product IDs (products that are sponsored)
    sponsored_ids = set(
        all_products.filter(is_sponsored=True).values_list('pk', flat=True)
    )

    # Wishlisted product IDs for the current user/session
    wishlisted_ids = get_wishlisted_ids(request)

    # Annotate each product on the current page with distance
    for product in page_obj:
        product._distance = get_distance_to_store(buyer_lat, buyer_lon, store)

    context = {
        'store': store,
        'vendor': store.vendor,
        'products': page_obj,
        'total_products': total_products_count,
        'subcategories': subcategories,
        'selected_subcategory_id': int(selected_subcategory_id) if selected_subcategory_id else None,
        'min_price': min_price_raw,
        'max_price': max_price_raw,
        'in_stock_only': in_stock_only,
        'is_owner': is_owner,
        'is_preview': not store.is_published and is_owner,
        'distance': get_distance_to_store(buyer_lat, buyer_lon, store),
        'sponsored_ids': sponsored_ids,
        'wishlisted_ids': wishlisted_ids,
    }

    return render(request, 'vendors/store/public_storefront.html', context)

# ==========================================
# NOTIFICATIONS
# ==========================================

@vendor_required
def notifications_list(request):
    """
    List all notifications for the logged-in vendor.
    """
    notifications = Notification.objects.filter(
        user=request.user
    ).order_by('-created_at')

    filter_value = request.GET.get('filter', '')
    if filter_value == 'unread':
        notifications = notifications.filter(is_read=False)
    elif filter_value in ['system', 'verification', 'admin_message', 'inventory']:
        notifications = notifications.filter(notification_type=filter_value)

    paginator = Paginator(notifications, 20)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    unread_count = Notification.objects.filter(user=request.user, is_read=False).count()

    return render(request, 'vendors/notifications/list.html', {
        'page_obj': page_obj,
        'notifications': page_obj,
        'unread_count': unread_count,
        'hide_verification_badge': True,
    })

@vendor_required
def notification_detail(request, notification_id):
    """
    View single notification
    """
    notification = get_object_or_404(Notification, id=notification_id, user=request.user)

    if not notification.is_read:
        notification.is_read = True
        notification.read_at = timezone.now()
        notification.save()

    return render(request, 'vendors/notifications/detail.html', {'notification': notification, 'hide_verification_badge': True})


@vendor_required
@require_http_methods(["POST"])
def notification_mark_read(request, notification_id):
    notification = get_object_or_404(Notification, id=notification_id, user=request.user)
    if not notification.is_read:
        notification.is_read = True
        notification.read_at = timezone.now()
        notification.save()
    return redirect('vendors:notification_detail', notification_id=notification.id)


@vendor_required
@require_http_methods(["POST"])
def notification_delete(request, notification_id):
    notification = get_object_or_404(Notification, id=notification_id, user=request.user)
    notification.delete()
    return redirect('vendors:notifications_list')


@vendor_required
@require_http_methods(["POST"])
def notifications_mark_all_read(request):
    qs = Notification.objects.filter(user=request.user, is_read=False)
    qs.update(is_read=True, read_at=timezone.now())
    return redirect('vendors:notifications_list')


# ==========================================
# AJAX / API ENDPOINTS
# ==========================================

@vendor_required
@require_http_methods(["GET"])
def get_subcategories_ajax(request):
    """
    Get subcategories for a main category (AJAX)
    """
    main_category_id = request.GET.get('main_category_id')

    if not main_category_id:
        return JsonResponse({'error': 'Missing main_category_id'}, status=400)

    subcategories = SubCategory.objects.filter(
        main_category_id=main_category_id,
        is_active=True
    ).values('id', 'name')

    return JsonResponse({'subcategories': list(subcategories)})


@vendor_required
@require_http_methods(["GET"])
def get_category_attributes_ajax(request):
    """
    Get attributes for a subcategory (AJAX)
    Used for dynamic product form
    """
    subcategory_id = request.GET.get('subcategory_id')

    if not subcategory_id:
        return JsonResponse({'error': 'Missing subcategory_id'}, status=400)

    try:
        subcategory = SubCategory.objects.get(id=subcategory_id)
        attributes = subcategory.attributes.filter(is_active=True).values(
            'id', 'name', 'field_type', 'options', 'is_required',
            'placeholder', 'help_text', 'sort_order'
        ).order_by('sort_order')

        return JsonResponse({
            'subcategory': subcategory.name,
            'attributes': list(attributes)
        })

    except SubCategory.DoesNotExist:
        return JsonResponse({'error': 'Subcategory not found'}, status=404)


# ==========================================
# ACCOUNT DELETION REQUEST
# ==========================================

@vendor_required
@require_http_methods(["POST"])
def request_account_deletion(request):
    """
    Send an account deletion request email to platform admin.
    No automatic deletion — this is a manual review queue.
    """
    vendor = request.user.vendorprofile
    user = request.user

    from apps.marketplace.services.email_service import _send, ADMIN_EMAIL

    if ADMIN_EMAIL:
        subject = f'[Account Deletion Request] Vendor: {user.email}'
        body = (
            f"Account Deletion Request\n"
            f"========================\n\n"
            f"User ID: {user.pk}\n"
            f"Email: {user.email}\n"
            f"Account Type: Vendor\n"
            f"Vendor ID: {vendor.vendor_id}\n"
            f"Store Name: {getattr(vendor.store, 'store_name', 'N/A')}\n"
            f"Verification Status: {vendor.verification_status}\n"
            f"Request Date: {timezone.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
            f"Action Required: Review and process this deletion request manually."
        )
        _send(subject, body, [ADMIN_EMAIL])

    messages.success(
        request,
        'Your account deletion request has been received. '
        'Our team will review it and process it manually. '
        'You will be notified via email once the request is handled.'
    )
    return redirect('vendors:store_settings')


# ==========================================
# SUBSCRIPTION WEBHOOK
# ==========================================

@csrf_exempt
@require_http_methods(["POST"])
def subscription_webhook(request):
    """
    Dedicated Paystack webhook endpoint for subscription billing events.
    Fully decoupled from the marketplace payment webhook.
    """
    from apps.vendors.services.subscription_service import (
        verify_subscription_webhook_signature,
        process_subscription_webhook,
    )

    signature = request.headers.get('X-Paystack-Signature', '')

    if not verify_subscription_webhook_signature(request.body, signature):
        logger.warning('Invalid Paystack subscription webhook signature received.')
        return HttpResponse(status=400)

    try:
        import json
        event = json.loads(request.body)
    except (json.JSONDecodeError, ValueError):
        return HttpResponse(status=400)

    event_type = event.get('event', '')
    data = event.get('data', {})
    event_id = event.get('id', '')

    result = process_subscription_webhook(event_type, data, event_id=event_id)
    logger.info('Subscription webhook processed: %s', result.get('message', ''))

    return HttpResponse(status=200)


# ==========================================
# CONTACT INTENT (fire-and-forget)
# ==========================================

@csrf_exempt
@require_http_methods(["POST"])
def contact_intent(request, product_id):
    """
    Lightweight endpoint to track Call/WhatsApp clicks.
    Called via fire-and-forget fetch/sendBeacon BEFORE navigation.
    No auth required — guest tracking via session_key.
    """
    from apps.marketplace.models import ContactIntent
    from apps.vendors.models import Product, VendorProfile

    try:
        product = Product.objects.get(id=product_id, status='published')
    except Product.DoesNotExist:
        return JsonResponse({'success': False}, status=404)

    channel = request.POST.get('channel', '')
    if channel not in ('call', 'whatsapp'):
        return JsonResponse({'success': False}, status=400)

    user = request.user if request.user.is_authenticated else None
    session_key = ''
    if not user:
        if not request.session.session_key:
            request.session.create()
        session_key = request.session.session_key

    try:
        ci = ContactIntent.objects.create(
            user=user,
            session_key=session_key,
            product=product,
            vendor=product.store.vendor,
            channel=channel,
        )
        # V9: Notify vendor of contact intent
        from apps.vendors.services.notification_dispatch import create_notification
        buyer_label = user.email if user else 'a visitor'
        channel_label = 'called' if channel == 'call' else 'messaged on WhatsApp'
        create_notification(
            user=product.store.vendor.user,
            notification_type='system',
            title=f'Buyer Contacted You! 📞',
            message=(
                f'{buyer_label} {channel_label} regarding "{product.title}". '
                f'Follow up to close the sale!'
            ),
            link=f'/vendors/products/{product.slug}/',
            vendor=product.store.vendor,
        )
    except Exception:
        logger.exception("Failed to create contact intent")

    return JsonResponse({'success': True})


# ==========================================
# VENDOR REVIEW REPLY
# ==========================================

@login_required
@require_http_methods(["POST"])
def vendor_reply_to_review(request, review_id):
    """
    AJAX: vendor submits a reply to a buyer's review.
    Only the product's vendor can reply.
    """
    from apps.marketplace.models import Review, ReviewReply

    try:
        review = Review.objects.select_related(
            'product__store__vendor__user'
        ).get(id=review_id)
    except Review.DoesNotExist:
        return JsonResponse({'success': False, 'message': 'Review not found.'}, status=404)

    vendor = request.user.vendorprofile
    if review.product.store.vendor != vendor:
        return JsonResponse({'success': False, 'message': 'Not your product.'}, status=403)

    if hasattr(review, 'reply'):
        return JsonResponse(
            {'success': False, 'message': 'You already replied to this review.'},
            status=400,
        )

    reply_text = request.POST.get('reply_text', '').strip()
    if not reply_text:
        return JsonResponse(
            {'success': False, 'message': 'Reply text is required.'},
            status=400,
        )

    reply = ReviewReply.objects.create(
        review=review,
        reply_text=reply_text,
    )

    # Notification to buyer is handled by the notify_buyer_on_review_reply signal

    return JsonResponse({
        'success': True,
        'message': 'Reply submitted.',
        'reply_text': reply.reply_text,
        'created_at': reply.created_at.isoformat(),
    })