"""
Marketplace Views
All buyer-facing views for KasuMarketplace.

Views:
- Product listing (with search, category filter, distance)
- Product detail
- Cart (view, add, update, remove)
- Checkout
- Payment verify + Webhook
- Order list
- Order detail
- Confirm receipt
- Report issue (dispute)
- Update buyer location (AJAX)
"""

import json
import logging

from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_POST, require_GET
from django.views.decorators.csrf import csrf_exempt
from django.http import JsonResponse, HttpResponse
from django.contrib import messages
from django.conf import settings
from django.utils import timezone
from django.db.models import Q

from apps.vendors.models import Product, Store, MainCategory, SubCategory
from apps.marketplace.models import (
    Cart, CartItem,
    MainOrder, SubOrder,
    PaymentTransaction,
)
from apps.marketplace.services.cart_service import (
    get_or_create_cart,
    add_to_cart,
    update_cart_item,
    remove_from_cart,
    get_cart_summary,
)
from apps.marketplace.services.payment_service import (
    generate_payment_reference,
    verify_payment,
    verify_webhook_signature,
    process_webhook,
)
from apps.marketplace.services.order_service import (
    create_orders_from_cart,
    confirm_suborder,
    open_dispute,
)
from apps.marketplace.services.distance_service import (
    get_distance_to_store,
    annotate_products_with_distance,
)

logger = logging.getLogger(__name__)


# ==========================================
# HELPERS
# ==========================================

def get_buyer_location(request):
    """
    Get buyer lat/lon from:
    1. Session (set via AJAX after browser geolocation)
    2. BuyerProfile (saved location)
    Returns (lat, lon) or (None, None)
    """
    # Check session first (most recent)
    lat = request.session.get('buyer_lat')
    lon = request.session.get('buyer_lon')
    if lat and lon:
        return lat, lon

    # Fall back to profile
    if request.user.is_authenticated:
        try:
            profile = request.user.buyer_profile
            if profile.has_location:
                return float(profile.latitude), float(profile.longitude)
        except Exception:
            pass

    return None, None


def buyer_required(view_func):
    """
    Decorator: requires user to be logged in AND have role='buyer'.
    Redirects to login if not authenticated.
    Redirects to product list with error if wrong role.
    """
    @login_required
    def wrapped(request, *args, **kwargs):
        if request.user.role != 'buyer':
            messages.error(request, 'This area is for buyers only.')
            return redirect('marketplace:product_list')
        return view_func(request, *args, **kwargs)
    wrapped.__name__ = view_func.__name__
    return wrapped


def vendor_forbidden(view_func):
    """
    Decorator: prevents logged-in vendors from accessing marketplace pages.
    Vendors must log out or use a separate buyer account to shop.
    """
    def wrapped(request, *args, **kwargs):
        if request.user.is_authenticated and getattr(request.user, 'role', None) == 'vendor':
            messages.warning(request, 'Please log out of your vendor account to browse the marketplace.')
            return redirect('vendors:dashboard')
        return view_func(request, *args, **kwargs)
    wrapped.__name__ = view_func.__name__
    return wrapped


# ==========================================
# PRODUCT LIST
# ==========================================

@vendor_forbidden
def product_list(request):
    """
    Main marketplace listing page.
    Supports:
    - Search by product title / description
    - Filter by main category
    - Filter by subcategory
    - Distance badge per product (if location available)

    """
    

    products = Product.objects.filter(
        status='published',
        store__is_published=True,
    ).select_related('store', 'subcategory__main_category').prefetch_related('images')

    # Search
    query = request.GET.get('q', '').strip()
    if query:
        products = products.filter(
            Q(title__icontains=query) |
            Q(description__icontains=query)
        )

    # Category filter
    main_category_slug = request.GET.get('category', '')
    if main_category_slug:
        products = products.filter(
            subcategory__main_category__slug=main_category_slug
        )

    # Subcategory filter
    subcategory_slug = request.GET.get('subcategory', '')
    if subcategory_slug:
        products = products.filter(
            subcategory__slug=subcategory_slug
        )

    # Get buyer location for distance
    buyer_lat, buyer_lon = get_buyer_location(request)

    # Convert to list and add distance inline to avoid circular references
    annotated = []
    for product in products:
        distance = get_distance_to_store(buyer_lat, buyer_lon, product.store)
        # Store distance in a way templates can access (no underscore prefix)
        product.distance = distance
        annotated.append(product)

    # Categories for filter sidebar
    categories = MainCategory.objects.filter(is_active=True).prefetch_related('subcategories')

    # Featured products for Flash Deals section
    featured_qs = Product.objects.filter(
        status='published',
        store__is_published=True,
        is_featured=True
    ).select_related('store').prefetch_related('images')[:10]

    # Annotate featured products with distance
    featured = []
    for product in featured_qs:
        distance = get_distance_to_store(buyer_lat, buyer_lon, product.store)
        product.distance = distance
        featured.append(product)

    context = {
        'annotated_products': annotated,
        'featured_products': featured,
        'categories': categories,
        'query': query,
        'selected_category': main_category_slug,
        'selected_subcategory': subcategory_slug,
        'buyer_lat': buyer_lat,
        'buyer_lon': buyer_lon,
        'paystack_public_key': settings.PAYSTACK_PUBLIC_KEY,
    }

    return render(request, 'marketplace/product_list.html', context)

# ==========================================
# PRODUCT DETAIL
# ==========================================

def product_detail(request, slug):
    """
    Legacy marketplace product detail URL.

    Buyers should be served the vendor app's public product page.
    We keep the original route for backwards compatibility, but simply
    look up the product and redirect to the new URL pattern.
    """
    product = get_object_or_404(
        Product.objects.select_related('store'),
        slug=slug,
        status='published',
        store__is_published=True,
    )
    return redirect('product_detail_public', store_slug=product.store.slug, product_slug=product.slug)


# ==========================================
# CART VIEWS
# ==========================================

@vendor_forbidden
def cart_view(request):
    """
    Display the cart page.
    Shows items grouped by store with subtotals and grand total.
    """
    summary = get_cart_summary(request)
    context = {
        **summary,
        'paystack_public_key': settings.PAYSTACK_PUBLIC_KEY,
    }
    return render(request, 'marketplace/cart.html', context)


@vendor_forbidden
@require_POST
def cart_add(request):
    """
    AJAX: Add a product to the cart.
    Expects POST: product_id, quantity (optional, default 1)
    Returns JSON.
    """
    try:
        data = json.loads(request.body)
        product_id = int(data.get('product_id'))
        quantity = int(data.get('quantity', 1))
    except (ValueError, TypeError, json.JSONDecodeError):
        return JsonResponse({'success': False, 'message': 'Invalid request.'}, status=400)

    result = add_to_cart(request, product_id, quantity)
    return JsonResponse(result)


@vendor_forbidden
@require_POST
def cart_update(request):
    """
    AJAX: Update quantity of a cart item.
    Expects POST: product_id, quantity
    If quantity is 0 — removes item.
    Returns JSON.
    """
    try:
        data = json.loads(request.body)
        product_id = int(data.get('product_id'))
        quantity = int(data.get('quantity', 1))
    except (ValueError, TypeError, json.JSONDecodeError):
        return JsonResponse({'success': False, 'message': 'Invalid request.'}, status=400)

    result = update_cart_item(request, product_id, quantity)
    return JsonResponse(result)


@vendor_forbidden
@require_POST
def cart_remove(request):
    """
    AJAX: Remove a product from the cart entirely.
    Expects POST: product_id
    Returns JSON.
    """
    try:
        data = json.loads(request.body)
        product_id = int(data.get('product_id'))
    except (ValueError, TypeError, json.JSONDecodeError):
        return JsonResponse({'success': False, 'message': 'Invalid request.'}, status=400)

    result = remove_from_cart(request, product_id)
    return JsonResponse(result)


# ==========================================
# CHECKOUT
# ==========================================

@buyer_required
def checkout(request):
    """
    Checkout page.
    - Pre-fills delivery address from BuyerProfile
    - Buyer can edit before paying
    - Generates Paystack reference server-side
    - Displays Paystack inline payment button
    """
    summary = get_cart_summary(request)

    if summary['is_empty']:
        messages.warning(request, 'Your cart is empty.')
        return redirect('marketplace:cart')

    # Pre-fill from buyer profile
    try:
        profile = request.user.buyer_profile
    except Exception:
        profile = None

    # Generate fresh Paystack reference for this session
    reference = generate_payment_reference()
    request.session['payment_reference'] = reference
    request.session['checkout_total'] = str(summary['grand_total'])

    context = {
        **summary,
        'reference': reference,
        'paystack_public_key': settings.PAYSTACK_PUBLIC_KEY,
        'profile': profile,
        # Pre-fill values for template
        'prefill_address': profile.default_address if profile else '',
        'prefill_city': profile.city if profile else '',
        'prefill_state': profile.state if profile else '',
        'prefill_phone': profile.phone if profile else '',
        'prefill_name': profile.display_name if profile else '',
    }
    return render(request, 'marketplace/checkout.html', context)


# ==========================================
# PAYMENT VERIFY
# ==========================================

@buyer_required
def payment_verify(request):
    """
    Server-side payment verification after Paystack callback.
    Called with GET: ?reference=KSM-XXXXXXXX

    Flow:
    1. Get reference from query params
    2. Get expected amount from session
    3. Verify with Paystack API
    4. If success: create orders, clear cart, redirect to order detail
    5. If fail: redirect to checkout with error
    """
    reference = request.GET.get('reference', '').strip()

    if not reference:
        messages.error(request, 'No payment reference found.')
        return redirect('marketplace:checkout')

    # Get expected amount from session
    expected_amount = request.session.get('checkout_total')
    if not expected_amount:
        messages.error(request, 'Session expired. Please try again.')
        return redirect('marketplace:checkout')

    # Get delivery data from POST (submitted with payment form)
    delivery_data = {
        'delivery_address': request.session.get('delivery_address', ''),
        'delivery_city': request.session.get('delivery_city', ''),
        'delivery_state': request.session.get('delivery_state', ''),
        'delivery_phone': request.session.get('delivery_phone', ''),
    }

    # Verify with Paystack
    verify_result = verify_payment(
        reference=reference,
        expected_amount_naira=expected_amount,
    )

    if not verify_result['success']:
        messages.error(request, f"Payment failed: {verify_result['message']}")
        return redirect('marketplace:checkout')

    transaction = verify_result['transaction']

    # Link transaction to logged-in user
    if not transaction.user:
        transaction.user = request.user
        transaction.save(update_fields=['user'])

    # If already processed — redirect to existing order
    if verify_result['already_processed']:
        try:
            existing_order = MainOrder.objects.get(reference=reference)
            messages.info(request, 'This payment was already processed.')
            return redirect('marketplace:order_detail', order_number=existing_order.order_number)
        except MainOrder.DoesNotExist:
            pass

    # Create orders
    cart = get_or_create_cart(request)
    order_result = create_orders_from_cart(
        cart=cart,
        payment_transaction=transaction,
        delivery_data=delivery_data,
    )

    if not order_result['success']:
        logger.error(f"Order creation failed for ref {reference}: {order_result['message']}")
        messages.error(request, 'Order creation failed. Please contact support.')
        return redirect('marketplace:checkout')

    # Clear session checkout data
    for key in ['payment_reference', 'checkout_total', 'delivery_address',
                'delivery_city', 'delivery_state', 'delivery_phone']:
        request.session.pop(key, None)

    main_order = order_result['main_order']
    messages.success(request, f'Order {main_order.order_number} placed successfully!')
    return redirect('marketplace:order_detail', order_number=main_order.order_number)


@require_POST
def checkout_save_delivery(request):
    """
    AJAX: Save delivery details to session before Paystack popup opens.
    Called when buyer clicks Pay — saves their delivery form data
    so it's available after Paystack redirects back.
    Expects POST JSON: address, city, state, phone
    """
    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({'success': False, 'message': 'Invalid data.'}, status=400)

    request.session['delivery_address'] = data.get('address', '')
    request.session['delivery_city'] = data.get('city', '')
    request.session['delivery_state'] = data.get('state', '')
    request.session['delivery_phone'] = data.get('phone', '')

    return JsonResponse({'success': True})


# ==========================================
# PAYSTACK WEBHOOK
# ==========================================

@csrf_exempt
@require_POST
def paystack_webhook(request):
    """
    Paystack webhook endpoint.
    Receives payment events from Paystack servers.

    Security: Validates X-Paystack-Signature header.
    Idempotency: Skips already-processed events.
    Always returns 200 OK to Paystack (even on errors)
    to prevent Paystack from retrying.
    """
    signature = request.headers.get('X-Paystack-Signature', '')

    # Verify signature
    if not verify_webhook_signature(request.body, signature):
        logger.warning('Invalid Paystack webhook signature received.')
        return HttpResponse(status=400)

    try:
        event = json.loads(request.body)
    except json.JSONDecodeError:
        return HttpResponse(status=400)

    # Process event
    result = process_webhook(event)
    logger.info(f"Webhook processed: {result['message']}")

    # Always return 200 to Paystack
    return HttpResponse(status=200)


# ==========================================
# ORDER LIST
# ==========================================

@buyer_required
def order_list(request):
    """
    Buyer's order history — flat list of SubOrders.
    """
    from apps.marketplace.models import SubOrder
    status_filter = request.GET.get('status', '')

    suborders = SubOrder.objects.filter(
        main_order__buyer=request.user
    ).select_related(
        'main_order', 'store'
    ).prefetch_related(
        'items__product'
    ).order_by('-created_at')

    if status_filter:
        suborders = suborders.filter(status=status_filter)

    # Lazy timeout check
    for sub in suborders:
        sub.check_and_apply_timeout()

    context = {
        'suborders': suborders,
        'status_filter': status_filter,
    }
    return render(request, 'marketplace/order_list.html', context)

# ==========================================
# ORDER DETAIL
# ==========================================

@buyer_required
def order_detail(request, order_number):
    """
    Detailed view of a single order.
    Shows:
    - All SubOrders with items
    - Vendor contact (phone, WhatsApp) if payment_status == SUCCESS
    - Confirm / Report Issue buttons if SubOrder is ACCEPTED
    - Checks + applies 48h timeout lazily
    """
    main_order = get_object_or_404(
        MainOrder.objects.prefetch_related(
            'suborders__store__vendor__user',
            'suborders__items__product',
            'suborders__wallet_transactions',
        ),
        order_number=order_number,
        buyer=request.user,
    )

    # Lazy timeout check for each suborder
    for sub in main_order.suborders.all():
        sub.check_and_apply_timeout()

    context = {
        'main_order': main_order,
        'suborders': main_order.suborders.all(),
    }
    return render(request, 'marketplace/order_detail.html', context)


# ==========================================
# CONFIRM RECEIPT
# ==========================================

@buyer_required
@require_POST
def confirm_receipt(request, suborder_id):
    """
    Buyer clicks YES — Release Payment.
    Marks SubOrder as CONFIRMED.
    Triggers 24h hold before vendor can withdraw.
    """
    sub_order = get_object_or_404(
        SubOrder.objects.select_related('main_order', 'store'),
        pk=suborder_id,
        main_order__buyer=request.user,
    )

    result = confirm_suborder(sub_order=sub_order, buyer=request.user)

    if result['success']:
        messages.success(request, result['message'])
    else:
        messages.error(request, result['message'])

    return redirect(
        'marketplace:order_detail',
        order_number=sub_order.main_order.order_number
    )


# ==========================================
# REPORT ISSUE (DISPUTE)
# ==========================================

@buyer_required
@require_POST
def report_issue(request, suborder_id):
    """
    Buyer clicks REPORT ISSUE.
    Creates a Dispute record and locks vendor funds.
    Requires POST field: reason (text)
    """
    sub_order = get_object_or_404(
        SubOrder.objects.select_related('main_order', 'store'),
        pk=suborder_id,
        main_order__buyer=request.user,
    )

    reason = request.POST.get('reason', '').strip()
    if not reason:
        messages.error(request, 'Please describe the issue.')
        return redirect(
            'marketplace:order_detail',
            order_number=sub_order.main_order.order_number
        )

    result = open_dispute(
        sub_order=sub_order,
        buyer=request.user,
        reason=reason,
    )

    if result['success']:
        messages.success(request, result['message'])
    else:
        messages.error(request, result['message'])

    return redirect(
        'marketplace:order_detail',
        order_number=sub_order.main_order.order_number
    )


# ==========================================
# BUYER LOCATION UPDATE (AJAX)
# ==========================================

@require_POST
def update_buyer_location(request):
    """
    AJAX: Save buyer's geolocation to session (and profile if logged in).
    Called from frontend after browser grants location permission.
    Expects POST JSON: lat, lon
    """
    try:
        data = json.loads(request.body)
        lat = float(data.get('lat'))
        lon = float(data.get('lon'))
    except (ValueError, TypeError, json.JSONDecodeError):
        return JsonResponse({'success': False, 'message': 'Invalid coordinates.'}, status=400)

    # Validate coordinate ranges
    if not (-90 <= lat <= 90) or not (-180 <= lon <= 180):
        return JsonResponse({'success': False, 'message': 'Coordinates out of range.'}, status=400)

    # Save to session
    request.session['buyer_lat'] = lat
    request.session['buyer_lon'] = lon

    # Save to profile if logged in
    if request.user.is_authenticated and request.user.role == 'buyer':
        try:
            profile = request.user.buyer_profile
            profile.latitude = lat
            profile.longitude = lon
            profile.save(update_fields=['latitude', 'longitude'])
        except Exception:
            pass  # Session save is enough for current request

    return JsonResponse({'success': True, 'message': 'Location updated.'})


# ==========================================
# STORE PUBLIC PAGE
# ==========================================

def store_detail(request, slug):
    """
    Legacy marketplace store detail view.

    Redirect users to the canonical vendors app public storefront route.
    The marketplace-specific template has been removed.
    """
    # preserve any query params if needed
    return redirect('vendors:store_public', slug=slug)

@buyer_required
def profile(request):
    try:
        profile = request.user.buyer_profile
    except Exception:
        profile = None

    if request.method == 'POST':
        from apps.users.models import BuyerProfile
        profile, _ = BuyerProfile.objects.get_or_create(user=request.user)
        profile.full_name = request.POST.get('full_name', '')
        profile.phone = request.POST.get('phone', '')
        profile.default_address = request.POST.get('default_address', '')
        profile.city = request.POST.get('city', '')
        profile.state = request.POST.get('state', '')
        profile.save()
        messages.success(request, 'Profile updated.')
        return redirect('marketplace:profile')

    return render(request, 'marketplace/profile.html', {'profile': profile})