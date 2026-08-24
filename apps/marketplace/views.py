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
from datetime import timedelta

from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_POST, require_GET
from django.views.decorators.csrf import csrf_exempt
from django.http import JsonResponse, HttpResponse
from django.contrib import messages
from django.conf import settings
from django.utils import timezone
from django.db.models import Q
from django.db.models import Sum

from apps.vendors.models import Product, Store, MainCategory, SubCategory
from apps.marketplace.models import (
    Cart, CartItem,
    MainOrder, SubOrder,
    PaymentTransaction,
    Promotion,
    Wishlist,
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

    wishlisted_ids = set()
    if request.user.is_authenticated:
        wishlisted_ids = set(
            Wishlist.objects.filter(user=request.user).values_list('product_id', flat=True)
        )

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
    
    # ---- Weekly top seller (single store) — used by mobile hero's dedicated slide ----
    week_ago = timezone.now() - timedelta(days=7)

    top_seller_store = Store.objects.filter(
        is_published=True,
        suborders__payment_status='SUCCESS',
        suborders__created_at__gte=week_ago,
    ).annotate(
        weekly_units_sold=Sum('suborders__items__quantity')
    ).order_by('-weekly_units_sold').first()

    # Sponsored stores first, fallback to top sellers by WEEKLY units sold
    # (previously ranked by all-time cumulative sales_count — see audit notes)
    sponsored_stores = list(
        Store.objects.filter(
            is_published=True, is_sponsored=True
        ).exclude(sponsored_until__lt=timezone.now())[:6]
    )

    if len(sponsored_stores) < 6:
        top_stores = Store.objects.filter(
            is_published=True,
            suborders__payment_status='SUCCESS',
            suborders__created_at__gte=week_ago,
        ).annotate(
            weekly_units_sold=Sum('suborders__items__quantity')
        ).order_by('-weekly_units_sold').exclude(
            id__in=[s.id for s in sponsored_stores]
        )[:6 - len(sponsored_stores)]
        spotlight_stores = sponsored_stores + list(top_stores)
    else:
        spotlight_stores = sponsored_stores

    vendor_promotions = Promotion.objects.filter(is_active=True)[:5]
    context = {
        'annotated_products': annotated,
        'featured_products': featured,
        'categories': categories,
        'query': query,
        'selected_category': main_category_slug,
        'selected_subcategory': subcategory_slug,
        'buyer_lat': buyer_lat,
        'buyer_lon': buyer_lon,
        'vendor_promotions': vendor_promotions,
        'spotlight_stores': spotlight_stores,
        'top_seller_store': top_seller_store,
        'wishlisted_ids': wishlisted_ids,
        'store_promotion_contact_email': 'support@kasumarketplace.com.ng',
        'paystack_public_key': settings.PAYSTACK_PUBLIC_KEY,
    }

    return render(request, 'marketplace/product_list.html', context)


@vendor_forbidden
def new_arrivals(request):
    """Show the newest published products first."""
    products = Product.objects.filter(
        status='published',
        store__is_published=True,
    ).select_related(
        'store', 'subcategory__main_category'
    ).prefetch_related('images').order_by('-created_at')[:60]

    buyer_lat, buyer_lon = get_buyer_location(request)

    wishlisted_ids = set()
    if request.user.is_authenticated:
        wishlisted_ids = set(
            Wishlist.objects.filter(user=request.user).values_list(
                'product_id', flat=True
            )
        )

    annotated = []
    for product in products:
        product.distance = get_distance_to_store(
            buyer_lat, buyer_lon, product.store
        )
        annotated.append(product)

    context = {
        'annotated_products': annotated,
        'wishlisted_ids': wishlisted_ids,
        'page_title': 'New Arrivals',
        'page_subtitle': f'{len(annotated)} newly listed products',
    }
    return render(request, 'marketplace/new_arrivals.html', context)


@vendor_forbidden
def deals(request):
    """
    Products currently discounted — compare_at_price set and greater than price.
    Sorted by discount percentage, biggest savings first.
    """
    from django.db.models import F, ExpressionWrapper, DecimalField

    products = Product.objects.filter(
        status='published',
        store__is_published=True,
        compare_at_price__isnull=False,
        compare_at_price__gt=F('price'),
    ).select_related('store', 'subcategory__main_category').prefetch_related('images')

    products = products.annotate(
        discount_amount=ExpressionWrapper(
            F('compare_at_price') - F('price'),
            output_field=DecimalField(max_digits=12, decimal_places=2)
        )
    ).order_by('-discount_amount')[:60]

    buyer_lat, buyer_lon = get_buyer_location(request)

    wishlisted_ids = set()
    if request.user.is_authenticated:
        from apps.marketplace.models import Wishlist
        wishlisted_ids = set(
            Wishlist.objects.filter(user=request.user).values_list('product_id', flat=True)
        )

    annotated = []
    for product in products:
        product.distance = get_distance_to_store(buyer_lat, buyer_lon, product.store)
        annotated.append(product)

    context = {
        'annotated_products': annotated,
        'wishlisted_ids': wishlisted_ids,
        'page_title': 'Flash Deals',
        'page_subtitle': f'{len(annotated)} products discounted right now',
    }
    return render(request, 'marketplace/deals.html', context)


@vendor_forbidden
def store_directory(request):
    """Browse all published stores, optionally filtered by category."""
    stores = Store.objects.filter(
        is_published=True,
    ).select_related('main_category').order_by('-average_rating')

    category_slug = request.GET.get('category', '')
    if category_slug:
        stores = stores.filter(main_category__slug=category_slug)

    context = {
        'stores': stores,
        'selected_category': category_slug,
    }
    return render(request, 'marketplace/store_directory.html', context)


@vendor_forbidden
def category_landing(request, slug):
    """
    Dedicated landing page for a product category.
    Shows subcategory filters, top store, and all products in the category.
    """
    from django.shortcuts import get_object_or_404

    category = get_object_or_404(
        MainCategory,
        slug=slug,
        is_active=True,
    )

    subcategories = category.subcategories.filter(is_active=True)

    products = Product.objects.filter(
        status='published',
        store__is_published=True,
        subcategory__main_category=category,
    ).select_related('store', 'subcategory__main_category').prefetch_related('images')

    subcategory_slug = request.GET.get('subcategory', '')
    if subcategory_slug:
        products = products.filter(subcategory__slug=subcategory_slug)

    buyer_lat, buyer_lon = get_buyer_location(request)

    wishlisted_ids = set()
    if request.user.is_authenticated:
        wishlisted_ids = set(
            Wishlist.objects.filter(user=request.user).values_list('product_id', flat=True)
        )

    annotated = []
    for product in products:
        product.distance = get_distance_to_store(buyer_lat, buyer_lon, product.store)
        annotated.append(product)

    top_store = Store.objects.filter(
        main_category=category,
        is_published=True,
    ).order_by('-average_rating').first()

    context = {
        'category': category,
        'subcategories': subcategories,
        'selected_subcategory': subcategory_slug,
        'annotated_products': annotated,
        'wishlisted_ids': wishlisted_ids,
        'top_store': top_store,
    }
    return render(request, 'marketplace/category_landing.html', context)


@vendor_forbidden
def trending(request):
    """Weekly best-selling products ranked by cached trending_score."""
    products = Product.objects.filter(
        status='published',
        store__is_published=True,
        trending_score__gt=0,
    ).select_related('store', 'subcategory__main_category').prefetch_related('images').order_by('-trending_score')[:60]

    buyer_lat, buyer_lon = get_buyer_location(request)

    wishlisted_ids = set()
    if request.user.is_authenticated:
        wishlisted_ids = set(
            Wishlist.objects.filter(user=request.user).values_list('product_id', flat=True)
        )

    annotated = []
    for product in products:
        product.distance = get_distance_to_store(buyer_lat, buyer_lon, product.store)
        annotated.append(product)

    context = {
        'annotated_products': annotated,
        'wishlisted_ids': wishlisted_ids,
        'page_title': 'Trending This Week at KASU',
        'page_subtitle': f'{len(annotated)} product{{% if annotated|length != 1 %}}s{{% endif %}} flying off the shelves',
    }
    return render(request, 'marketplace/trending.html', context)


@vendor_forbidden
def contact_us(request):
    """Contact form with subject-based email routing."""
    from apps.marketplace.forms import ContactForm
    from apps.marketplace.services.email_service import _send, ADMIN_EMAIL

    if request.method == 'POST':
        form = ContactForm(request.POST)
        if form.is_valid():
            data = form.cleaned_data
            subject_label = dict(ContactForm.SUBJECT_CHOICES)[data['subject']]
            body = (
                f"Role: {data['role']}\n"
                f"Name: {data['name']}\n"
                f"Email: {data['email']}\n"
                f"Subject: {subject_label}\n\n"
                f"Message:\n{data['message']}"
            )

            recipient_map = {
                'order_issue': 'support@kasumarketplace.com.ng',
                'vendor_application': ADMIN_EMAIL or 'support@kasumarketplace.com.ng',
                'report_problem': ADMIN_EMAIL or 'support@kasumarketplace.com.ng',
                'general': 'info@kasumarketplace.com.ng',
            }
            to_email = recipient_map[data['subject']]

            _send(
                subject=f"[Contact] {subject_label} — {data['name']}",
                message=body,
                recipient_list=[to_email],
            )

            messages.success(request, 'Your message has been sent. We\'ll get back to you shortly.')
            return redirect('marketplace:contact')
    else:
        form = ContactForm()

    context = {'form': form}
    return render(request, 'marketplace/contact.html', context)


@buyer_required
def wishlist_view(request):
    """Buyer's saved products, using the same card partial as listing pages."""
    from apps.marketplace.services.distance_service import get_distance_to_store

    buyer_lat, buyer_lon = get_buyer_location(request)

    wishlist_items = Wishlist.objects.filter(
        user=request.user
    ).select_related('product__store').prefetch_related(
        'product__images'
    ).order_by('-created_at')

    products = []
    for wishlist_item in wishlist_items:
        product = wishlist_item.product
        product.distance = get_distance_to_store(
            buyer_lat, buyer_lon, product.store
        )
        products.append(product)

    wishlisted_pks = {w.product_id for w in wishlist_items}

    # "You Might Also Like" — trending products not already wishlisted
    from apps.vendors.models import Product
    recommended = Product.objects.filter(
        status='published',
        store__is_published=True,
    ).exclude(
        pk__in=wishlisted_pks
    ).select_related('store').prefetch_related('images').order_by(
        '-trending_score', '-created_at'
    )[:8]

    for p in recommended:
        p.distance = get_distance_to_store(buyer_lat, buyer_lon, p.store)

    context = {
        'wishlist_products': products,
        'wishlisted_ids': wishlisted_pks,
        'recommended_products': list(recommended),
    }
    return render(request, 'marketplace/wishlist.html', context)


def search_results(request):
    """Unified search results for matching stores and published products."""
    query = request.GET.get('q', '').strip()

    products = Product.objects.none()
    stores = Store.objects.none()

    if query:
        products = Product.objects.filter(
            Q(title__icontains=query) | Q(description__icontains=query),
            status='published',
            store__is_published=True,
        ).select_related('store').prefetch_related('images')

        stores = Store.objects.filter(
            Q(store_name__icontains=query) | Q(tagline__icontains=query),
            is_published=True,
        ).select_related('main_category')

    buyer_lat, buyer_lon = get_buyer_location(request)
    annotated_products = []
    for product in products:
        product.distance = get_distance_to_store(
            buyer_lat, buyer_lon, product.store
        )
        annotated_products.append(product)

    wishlisted_ids = set()
    if request.user.is_authenticated:
        wishlisted_ids = set(
            Wishlist.objects.filter(user=request.user).values_list(
                'product_id', flat=True
            )
        )

    context = {
        'query': query,
        'products': annotated_products,
        'stores': stores,
        'product_count': len(annotated_products),
        'store_count': stores.count(),
        'wishlisted_ids': wishlisted_ids,
    }
    return render(request, 'marketplace/search_results.html', context)

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

    # "You Might Also Like" — trending products not already in cart
    from apps.vendors.models import Product
    from apps.marketplace.services.distance_service import get_distance_to_store
    cart_product_ids = set()
    for items in summary.get('items_by_store', {}).values():
        for ci in items:
            cart_product_ids.add(ci.product_id)

    buyer_lat, buyer_lon = get_buyer_location(request)
    recommended = Product.objects.filter(
        status='published',
        store__is_published=True,
    ).exclude(
        pk__in=cart_product_ids
    ).select_related('store').prefetch_related('images').order_by(
        '-trending_score', '-created_at'
    )[:8]

    for p in recommended:
        p.distance = get_distance_to_store(buyer_lat, buyer_lon, p.store)

    context = {
        **summary,
        'paystack_public_key': settings.PAYSTACK_PUBLIC_KEY,
        'recommended_products': list(recommended),
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
    logger = logging.getLogger('marketplace.cart')
    user_label = (
        f"user={request.user.pk}"
        if request.user.is_authenticated
        else f"anon session={request.session.session_key}"
    )

    try:
        data = json.loads(request.body)
        product_id = int(data.get('product_id'))
        quantity = int(data.get('quantity', 1))
    except (ValueError, TypeError, json.JSONDecodeError) as exc:
        logger.warning(
            "cart_add bad_request %s product_id=%s error=%s",
            user_label, data.get('product_id') if isinstance(data, dict) else '?', exc,
        )
        return JsonResponse({'success': False, 'message': 'Invalid request.'}, status=400)

    try:
        result = add_to_cart(request, product_id, quantity)
    except Exception as exc:
        import traceback
        logger.error(
            "cart_add exception %s product_id=%s error_type=%s error=%s\n%s",
            user_label, product_id, type(exc).__name__, exc, traceback.format_exc(),
        )
        return JsonResponse({
            'success': False,
            'message': 'Something went wrong. Please try again.',
            '_debug_error': f"{type(exc).__name__}: {exc}",
        }, status=500)

    if not result.get('success'):
        logger.info("cart_add declined %s product_id=%s message=%s", user_label, product_id, result.get('message'))

    logger.info("cart_add ok %s product_id=%s qty=%s cart_items=%s", user_label, product_id, quantity, result.get('cart_total_items'))
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
            'suborders__dispute',
        ),
        order_number=order_number,
        buyer=request.user,
    )

    # Lazy timeout check for each suborder
    for sub in main_order.suborders.all():
        sub.check_and_apply_timeout()

    context = {
        'main_order': main_order,
        'order': main_order,  # ← add this line
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


def about_page(request):
    """About KasuMarketplace page."""
    return render(request, 'marketplace/about.html')


def cookies_page(request):
    """Cookie policy page."""
    return render(request, 'marketplace/cookies.html')


def privacy_policy(request):
    """Privacy policy page."""
    return render(request, 'marketplace/privacy.html')


def terms_of_service(request):
    """Terms of service page."""
    return render(request, 'marketplace/terms.html')


# ==========================================
# ACCOUNT DELETION REQUEST
# ==========================================

@login_required
@require_POST
def request_account_deletion(request):
    """
    Send an account deletion request email to platform admin.
    No automatic deletion — this is a manual review queue.
    """
    user = request.user

    from apps.marketplace.services.email_service import _send, ADMIN_EMAIL

    if ADMIN_EMAIL:
        subject = f'[Account Deletion Request] Buyer: {user.email}'
        body = (
            f"Account Deletion Request\n"
            f"========================\n\n"
            f"User ID: {user.pk}\n"
            f"Email: {user.email}\n"
            f"Account Type: Buyer\n"
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
    return redirect('marketplace:profile')