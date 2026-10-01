"""
Marketplace Views
All buyer-facing views for KasuMarketplace.

Views:
- Product listing (with search, category filter, distance)
- Product detail
- Update buyer location (AJAX)
"""

import json
import logging
import random
from datetime import timedelta
from types import SimpleNamespace

from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_POST, require_GET
from django.views.decorators.csrf import csrf_exempt
from django.http import JsonResponse, HttpResponse
from django.contrib import messages
from django.conf import settings
from django.utils import timezone
from django.db.models import Q
from django.db.models import Sum, Count
from django.core.paginator import Paginator

from apps.vendors.models import Product, Store, MainCategory, SubCategory
from apps.marketplace.models import (
    Promotion,
    Wishlist,
)
from apps.marketplace.services.distance_service import (
    get_distance_to_store,
    annotate_products_with_distance,
)
from apps.quicksell.models import QuickSell
from apps.quicksell.adapter import adapt_quicksell_queryset

logger = logging.getLogger(__name__)


def get_wishlisted_ids(request):
    """Return set of product IDs wishlisted by the current user (auth or guest)."""
    if request.user.is_authenticated:
        return set(
            Wishlist.objects.filter(user=request.user).values_list('product_id', flat=True)
        )
    session_key = request.session.session_key
    if session_key:
        return set(
            Wishlist.objects.filter(session_key=session_key).values_list('product_id', flat=True)
        )
    return set()


# ==========================================
# HERO DEFAULTS (static fallback per slot)
# ==========================================

HERO_DEFAULTS = [
    {
        'hero_slot': 'campus_essentials',
        'title': 'Campus Essentials',
        'subtitle': 'Everything you need for campus life',
        'link_url': '/',
        'static_image': 'marketplace/img/hero-defaults/campus-essentials.jpg',
    },
    {
        'hero_slot': 'tech_electronics',
        'title': 'Tech & Electronics',
        'subtitle': 'Phones, laptops, and gadgets',
        'link_url': '/category/tech-electronics/',
        'static_image': 'marketplace/img/hero-defaults/tech-electronics.jpg',
    },
    {
        'hero_slot': 'fashion_accessories',
        'title': 'Fashion & Accessories',
        'subtitle': 'Style that fits your vibe',
        'link_url': '/category/fashion-accessories/',
        'static_image': 'marketplace/img/hero-defaults/fashion-accessories.jpg',
    },
    {
        'hero_slot': 'food_beverages',
        'title': 'Food & Beverages',
        'subtitle': 'Quick bites and campus favourites',
        'link_url': '/category/food-beverages/',
        'static_image': 'marketplace/img/hero-defaults/food-beverages.jpg',
    },
    {
        'hero_slot': 'deals_marketplace',
        'title': 'Deals & Marketplace',
        'subtitle': "Discounts you don't want to miss",
        'link_url': '/deals/',
        'static_image': 'marketplace/img/hero-defaults/deals-marketplace.jpg',
    },
    {
        'hero_slot': 'top_seller',
        'title': 'Top Seller This Week',
        'subtitle': 'Discover the most popular store on campus',
        'link_url': '/stores/',
        'static_image': 'marketplace/img/hero-defaults/top-seller.jpg',
    },
]


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

def product_list(request):
    """
    Main marketplace listing page.
    Supports:
    - Search by product title / description
    - Filter by main category
    - Filter by subcategory
    - Distance badge per product (if location available)

    """
    

    products = Product.objects.publicly_visible()

    wishlisted_ids = get_wishlisted_ids(request)

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

    # Shuffle products on each page load for fresh browsing experience
    random.shuffle(annotated)

    # Categories for filter sidebar
    categories = MainCategory.objects.filter(is_active=True).prefetch_related('subcategories')

    # Featured products for Flash Deals section — only products with actual discounts
    from django.db.models import F, ExpressionWrapper, DecimalField
    featured_qs = Product.objects.publicly_visible().filter(
        compare_at_price__isnull=False,
        compare_at_price__gt=F('price'),
    )

    featured_qs = featured_qs.annotate(
        discount_amount=ExpressionWrapper(
            F('compare_at_price') - F('price'),
            output_field=DecimalField(max_digits=12, decimal_places=2)
        )
    ).order_by('-discount_amount')[:10]

    # Annotate featured products with distance
    featured = []
    for product in featured_qs:
        distance = get_distance_to_store(buyer_lat, buyer_lon, product.store)
        product.distance = distance
        featured.append(product)

    # Shuffle featured products for freshness
    random.shuffle(featured)

    # ── Quick Sell listings — active only ──
    quicksell_qs = QuickSell.objects.active().select_related('subcategory__main_category')
    if query:
        quicksell_qs = quicksell_qs.filter(
            Q(title__icontains=query) | Q(description__icontains=query)
        )
    if main_category_slug:
        quicksell_qs = quicksell_qs.filter(
            subcategory__main_category__slug=main_category_slug
        )
    if subcategory_slug:
        quicksell_qs = quicksell_qs.filter(
            subcategory__slug=subcategory_slug
        )
    quicksell_items = adapt_quicksell_queryset(quicksell_qs[:60])
    
    # ---- Weekly top seller (single store) — used by mobile hero's dedicated slide ----
    # Phase 8: rank by store_score (wishlist_count + views_count + rating*20)
    # across all published products, picking the highest-scoring store.
    from django.db.models import Sum as DjSum, Count as DjCount
    top_seller_candidates = Store.objects.publicly_visible().annotate(
        score=DjSum('products__wishlisted_by__id', filter=Q(products__status='published'), distinct=True)
             + DjSum('products__views_count', filter=Q(products__status='published'))
    ).order_by('-score')

    top_seller_store = top_seller_candidates.first() if top_seller_candidates.exists() else None
    # If the top-scoring store has score 0 (no activity), don't show it
    if top_seller_store and not hasattr(top_seller_store, 'score'):
        top_seller_store = None

    # Sponsored stores first, fallback to top stores by store_score
    sponsored_stores = list(
        Store.objects.publicly_visible().filter(
            is_sponsored=True
        ).exclude(sponsored_until__lt=timezone.now())[:6]
    )

    if len(sponsored_stores) < 6:
        # Fill remaining slots with top stores by score (excluding already-sponsored)
        sponsored_ids = [s.pk for s in sponsored_stores]
        fallback_needed = 6 - len(sponsored_stores)
        top_by_score = Store.objects.publicly_visible().exclude(
            pk__in=sponsored_ids
        ).annotate(
            score=DjSum('products__wishlisted_by__id', filter=Q(products__status='published'), distinct=True)
                 + DjSum('products__views_count', filter=Q(products__status='published'))
        ).order_by('-score')[:fallback_needed]
        spotlight_stores = sponsored_stores + list(top_by_score)
    else:
        spotlight_stores = sponsored_stores

    vendor_promotions = Promotion.objects.filter(is_active=True, slide_type='vendor_promo')[:5]

    # --- Hero brand slides: 5 fixed slots with optional DB overrides ---
    now = timezone.now()
    hero_overrides = Promotion.objects.filter(
        is_active=True,
        slide_type='hero_brand',
    ).filter(
        Q(start_date__isnull=True) | Q(start_date__lte=now),
        Q(end_date__isnull=True) | Q(end_date__gte=now),
    ).order_by('sort_order')
    override_map = {o.hero_slot: o for o in hero_overrides if o.hero_slot}

    hero_brand_slides = []
    for default in HERO_DEFAULTS:
        slot = default['hero_slot']
        if slot in override_map:
            promo = override_map[slot]
            hero_brand_slides.append(SimpleNamespace(
                title=promo.title,
                subtitle=promo.subtitle,
                link_url=promo.link_url,
                background_image=promo.background_image,
                static_image_path=default['static_image'] if not promo.background_image else None,
            ))
        else:
            hero_brand_slides.append(SimpleNamespace(
                title=default['title'],
                subtitle=default['subtitle'],
                link_url=default['link_url'],
                background_image=None,
                static_image_path=default['static_image'],
            ))

    # --- Top Seller slide: override/default background, store content overlays on top ---
    top_seller_default = next((d for d in HERO_DEFAULTS if d['hero_slot'] == 'top_seller'), None)
    if top_seller_default and 'top_seller' in override_map:
        promo = override_map['top_seller']
        top_seller_slide = SimpleNamespace(
            background_image=promo.background_image,
            static_image_path=top_seller_default['static_image'] if not promo.background_image else None,
        )
    elif top_seller_default:
        top_seller_slide = SimpleNamespace(
            background_image=None,
            static_image_path=top_seller_default['static_image'],
        )
    else:
        top_seller_slide = None

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
        'hero_brand_slides': hero_brand_slides,
        'spotlight_stores': spotlight_stores,
        'top_seller_store': top_seller_store,
        'top_seller_slide': top_seller_slide,
        'wishlisted_ids': wishlisted_ids,
        'store_promotion_contact_email': 'support@kasumarketplace.com.ng',
        'paystack_public_key': settings.PAYSTACK_PUBLIC_KEY,
        'quicksell_items': quicksell_items,
    }

    return render(request, 'marketplace/product_list.html', context)


def new_arrivals(request):
    """Show the newest published products and active Quick Sell listings first (14-day rolling window)."""
    two_weeks_ago = timezone.now() - timedelta(days=14)
    products = Product.objects.publicly_visible().filter(
        created_at__gte=two_weeks_ago,
    ).order_by('-created_at')[:60]

    buyer_lat, buyer_lon = get_buyer_location(request)

    wishlisted_ids = get_wishlisted_ids(request)

    annotated = []
    for product in products:
        product.distance = get_distance_to_store(
            buyer_lat, buyer_lon, product.store
        )
        annotated.append(product)

    # Shuffle for fresh browsing experience on each visit
    random.shuffle(annotated)

    # Quick Sell new arrivals — active only, created in last 14 days
    quicksell_qs = QuickSell.objects.active().filter(
        created_at__gte=two_weeks_ago,
    ).select_related('subcategory__main_category').order_by('-created_at')[:60]
    quicksell_items = adapt_quicksell_queryset(quicksell_qs)

    context = {
        'annotated_products': annotated,
        'quicksell_items': quicksell_items,
        'wishlisted_ids': wishlisted_ids,
        'page_title': 'New Arrivals',
        'page_subtitle': f'{len(annotated)} newly listed products + {len(quicksell_items)} quick sell listings',
    }
    return render(request, 'marketplace/new_arrivals.html', context)


def deals(request):
    """
    Products currently discounted — compare_at_price set and greater than price.
    Sorted by discount percentage, biggest savings first.
    """
    from django.db.models import F, ExpressionWrapper, DecimalField

    products = Product.objects.publicly_visible().filter(
        compare_at_price__isnull=False,
        compare_at_price__gt=F('price'),
    )

    products = products.annotate(
        discount_amount=ExpressionWrapper(
            F('compare_at_price') - F('price'),
            output_field=DecimalField(max_digits=12, decimal_places=2)
        )
    ).order_by('-discount_amount')[:60]

    buyer_lat, buyer_lon = get_buyer_location(request)

    wishlisted_ids = get_wishlisted_ids(request)

    annotated = []
    for product in products:
        product.distance = get_distance_to_store(buyer_lat, buyer_lon, product.store)
        annotated.append(product)

    # Shuffle for fresh browsing experience on each visit
    random.shuffle(annotated)

    context = {
        'annotated_products': annotated,
        'wishlisted_ids': wishlisted_ids,
        'page_title': 'Flash Deals',
        'page_subtitle': f'{len(annotated)} products discounted right now',
    }
    return render(request, 'marketplace/deals.html', context)


def quicksell_listing(request):
    """Dedicated Quick Sell listings page — active Quick Sell items only."""
    quicksell_qs = QuickSell.objects.active().select_related('subcategory__main_category').order_by('-created_at')[:120]
    quicksell_items = adapt_quicksell_queryset(quicksell_qs)

    # Shuffle for fresh browsing experience on each visit
    random.shuffle(quicksell_items)

    context = {
        'quicksell_items': quicksell_items,
        'page_title': 'Quick Sell',
        'page_subtitle': f'{len(quicksell_items)} active listings from campus sellers',
    }
    return render(request, 'marketplace/quicksell_listing.html', context)


def store_directory(request):
    """Browse all published stores, optionally filtered by category."""
    stores = Store.objects.publicly_visible().select_related('main_category').order_by('-average_rating')

    category_slug = request.GET.get('category', '')
    if category_slug:
        stores = stores.filter(main_category__slug=category_slug)

    context = {
        'stores': stores,
        'selected_category': category_slug,
    }
    return render(request, 'marketplace/store_directory.html', context)


def category_landing(request, slug):
    """
    Dedicated landing page for a product category.
    Shows subcategory filters, top store, products, and active Quick Sell listings in the category.
    """
    from django.shortcuts import get_object_or_404

    category = get_object_or_404(
        MainCategory,
        slug=slug,
        is_active=True,
    )

    subcategories = category.subcategories.filter(is_active=True)

    products = Product.objects.publicly_visible().filter(
        subcategory__main_category=category,
    )

    subcategory_slug = request.GET.get('subcategory', '')
    if subcategory_slug:
        products = products.filter(subcategory__slug=subcategory_slug)

    buyer_lat, buyer_lon = get_buyer_location(request)

    organic_products = []
    for product in products:
        product.distance = get_distance_to_store(buyer_lat, buyer_lon, product.store)
        organic_products.append(product)

    # ── Sponsored products ──
    organic_ids = {p.pk for p in organic_products}

    organic_sponsored = []
    organic_regular = []
    for p in organic_products:
        if p.is_sponsored and (not p.sponsored_until or p.sponsored_until >= timezone.now()):
            organic_sponsored.append(p)
        else:
            organic_regular.append(p)

    organic_count = len(organic_products)
    max_sponsored = min(4, organic_count)
    extra_sponsored = []

    if max_sponsored > 0:
        extra_sponsored = list(
            Product.objects.publicly_visible().filter(
                subcategory__main_category=category,
                is_sponsored=True,
            ).exclude(
                pk__in=organic_ids
            ).exclude(
                sponsored_until__lt=timezone.now()
            ).order_by(
                '-sponsored_priority'
            ).select_related('store').prefetch_related('images')[:max_sponsored]
        )
        if subcategory_slug:
            extra_sponsored = [p for p in extra_sponsored if p.subcategory.slug == subcategory_slug]

    all_sponsored = organic_sponsored + extra_sponsored
    all_sponsored.sort(key=lambda p: p.sponsored_priority or 0, reverse=True)
    top_sponsored = all_sponsored[:max_sponsored]

    sponsored_ids = {p.pk for p in top_sponsored}

    for p in top_sponsored:
        if not hasattr(p, 'distance'):
            p.distance = get_distance_to_store(buyer_lat, buyer_lon, p.store)

    # Shuffle regular products for fresh browsing experience on each visit
    random.shuffle(organic_regular)

    merged_products = top_sponsored + organic_regular

    # ── Quick Sell listings in this category ──
    quicksell_qs = QuickSell.objects.active().filter(
        subcategory__main_category=category,
    ).select_related('subcategory__main_category')
    if subcategory_slug:
        quicksell_qs = quicksell_qs.filter(subcategory__slug=subcategory_slug)
    quicksell_items = adapt_quicksell_queryset(quicksell_qs)

    # Shuffle for fresh browsing experience on each visit
    random.shuffle(quicksell_items)

    wishlisted_ids = get_wishlisted_ids(request)

    top_store = Store.objects.publicly_visible().filter(
        main_category=category,
    ).order_by('-average_rating').first()

    context = {
        'category': category,
        'subcategories': subcategories,
        'selected_subcategory': subcategory_slug,
        'annotated_products': merged_products,
        'quicksell_items': quicksell_items,
        'wishlisted_ids': wishlisted_ids,
        'top_store': top_store,
        'sponsored_ids': sponsored_ids,
    }
    return render(request, 'marketplace/category_landing.html', context)


def trending(request):
    """Weekly best-selling products ranked by cached trending_score."""
    products = Product.objects.publicly_visible().filter(
        trending_score__gt=0,
    ).order_by('-trending_score')[:60]

    buyer_lat, buyer_lon = get_buyer_location(request)

    wishlisted_ids = get_wishlisted_ids(request)

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


def sponsored_products(request):
    """Dedicated page showing all currently active sponsored products, ordered by priority."""
    products = Product.objects.publicly_visible().filter(
        is_sponsored=True,
    ).exclude(
        sponsored_until__lt=timezone.now()
    ).order_by(
        '-sponsored_priority'
    )

    buyer_lat, buyer_lon = get_buyer_location(request)

    wishlisted_ids = get_wishlisted_ids(request)

    annotated = []
    sponsored_ids = set()
    for product in products:
        product.distance = get_distance_to_store(buyer_lat, buyer_lon, product.store)
        annotated.append(product)
        sponsored_ids.add(product.pk)

    # Shuffle for fresh browsing experience on each visit
    random.shuffle(annotated)

    context = {
        'annotated_products': annotated,
        'wishlisted_ids': wishlisted_ids,
        'sponsored_ids': sponsored_ids,
        'page_title': 'Promoted for You',
        'page_subtitle': f'{len(annotated)} sponsored product{{% if annotated|length != 1 %}}s{{% endif %}} from our partners',
    }
    return render(request, 'marketplace/sponsored_products.html', context)


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


def wishlist_view(request):
    """Buyer's saved products, using the same card partial as listing pages.
    Supports both authenticated users and anonymous guests via session key."""
    from apps.marketplace.services.distance_service import get_distance_to_store

    buyer_lat, buyer_lon = get_buyer_location(request)

    if request.user.is_authenticated:
        wishlist_items = Wishlist.objects.filter(
            user=request.user
        ).select_related('product__store').prefetch_related(
            'product__images'
        ).order_by('-created_at')
    else:
        session_key = request.session.session_key
        if not session_key:
            wishlist_items = Wishlist.objects.none()
        else:
            wishlist_items = Wishlist.objects.filter(
                session_key=session_key
            ).select_related('product__store').prefetch_related(
                'product__images'
            ).order_by('-created_at')

    products = []
    for wishlist_item in wishlist_items:
        product = wishlist_item.product
        product.distance = get_distance_to_store(
            buyer_lat, buyer_lon, product.store
        )
        product.wishlist_quantity = wishlist_item.quantity
        product.total_price = product.price * wishlist_item.quantity
        products.append(product)

    wishlisted_pks = {w.product_id for w in wishlist_items}

    # "You Might Also Like" — trending products not already wishlisted
    from apps.vendors.models import Product
    recommended = Product.objects.publicly_visible().exclude(
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


@require_POST
def wishlist_update_qty(request):
    """AJAX: Update quantity of a wishlist item. Works for both auth and guest."""
    try:
        data = json.loads(request.body)
        product_id = int(data.get('product_id'))
        quantity = int(data.get('quantity', 1))
    except (ValueError, TypeError, json.JSONDecodeError):
        return JsonResponse({'success': False, 'message': 'Invalid request.'}, status=400)

    if quantity < 1:
        quantity = 1

    if request.user.is_authenticated:
        item = Wishlist.objects.filter(user=request.user, product_id=product_id).first()
    else:
        session_key = request.session.session_key
        if not session_key:
            return JsonResponse({'success': False, 'message': 'No session.'}, status=400)
        item = Wishlist.objects.filter(session_key=session_key, product_id=product_id).first()

    if not item:
        return JsonResponse({'success': False, 'message': 'Item not found in wishlist.'}, status=404)

    item.quantity = quantity
    item.save(update_fields=['quantity'])
    return JsonResponse({'success': True, 'message': 'Quantity updated.'})


@require_POST
def wishlist_remove(request):
    """AJAX: Remove a product from the wishlist entirely. Works for both auth and guest."""
    try:
        data = json.loads(request.body)
        product_id = int(data.get('product_id'))
    except (ValueError, TypeError, json.JSONDecodeError):
        return JsonResponse({'success': False, 'message': 'Invalid request.'}, status=400)

    if request.user.is_authenticated:
        deleted, _ = Wishlist.objects.filter(user=request.user, product_id=product_id).delete()
        count = Wishlist.objects.filter(user=request.user).count()
    else:
        session_key = request.session.session_key
        if not session_key:
            return JsonResponse({'success': False, 'message': 'No session.'}, status=400)
        deleted, _ = Wishlist.objects.filter(session_key=session_key, product_id=product_id).delete()
        count = Wishlist.objects.filter(session_key=session_key).count()

    if deleted:
        return JsonResponse({'success': True, 'message': 'Item removed.', 'wishlist_count': count})
    return JsonResponse({'success': False, 'message': 'Item not found.'}, status=404)


def search_results(request):
    """Unified search results for matching stores, published products, and active Quick Sell listings."""
    query = request.GET.get('q', '').strip()

    products = Product.objects.none()
    stores = Store.objects.none()
    quicksell_listings = QuickSell.objects.none()

    if query:
        products = Product.objects.publicly_visible().filter(
            Q(title__icontains=query) | Q(description__icontains=query),
        )

        stores = Store.objects.publicly_visible().filter(
            Q(store_name__icontains=query) | Q(tagline__icontains=query),
        ).select_related('main_category')

        # Quick Sell search — only active (non-expired) listings
        quicksell_listings = QuickSell.objects.active().filter(
            Q(title__icontains=query) | Q(description__icontains=query),
        ).select_related('subcategory__main_category')

    buyer_lat, buyer_lon = get_buyer_location(request)
    organic_products = []
    for product in products:
        product.distance = get_distance_to_store(
            buyer_lat, buyer_lon, product.store
        )
        organic_products.append(product)

    # ── Sponsored products ──
    organic_ids = {p.pk for p in organic_products}

    # Split organic into sponsored and regular
    organic_sponsored = []
    organic_regular = []
    for p in organic_products:
        if p.is_sponsored and (not p.sponsored_until or p.sponsored_until >= timezone.now()):
            organic_sponsored.append(p)
        else:
            organic_regular.append(p)

    # Query extra sponsored products not already in organic results
    organic_count = len(organic_products)
    max_sponsored = min(4, organic_count)
    extra_sponsored = []

    if max_sponsored > 0 and query:
        extra_sponsored = list(
            Product.objects.publicly_visible().filter(
                Q(title__icontains=query) | Q(description__icontains=query),
                is_sponsored=True,
            ).exclude(
                pk__in=organic_ids
            ).exclude(
                sponsored_until__lt=timezone.now()
            ).order_by(
                '-sponsored_priority'
            ).select_related('store').prefetch_related('images')[:max_sponsored]
        )

    # Combine all sponsored, sort by priority, cap
    all_sponsored = organic_sponsored + extra_sponsored
    all_sponsored.sort(key=lambda p: p.sponsored_priority or 0, reverse=True)
    top_sponsored = all_sponsored[:max_sponsored]

    # Badges: all sponsored products (capped list) get the badge
    sponsored_ids = {p.pk for p in top_sponsored}

    # Annotate distance on sponsored products
    for p in top_sponsored:
        if not hasattr(p, 'distance'):
            p.distance = get_distance_to_store(buyer_lat, buyer_lon, p.store)

    merged_products = top_sponsored + organic_regular

    # Adapt Quick Sell listings for template compatibility
    quicksell_items = adapt_quicksell_queryset(quicksell_listings)

    wishlisted_ids = get_wishlisted_ids(request)

    context = {
        'query': query,
        'products': merged_products,
        'stores': stores,
        'quicksell_items': quicksell_items,
        'product_count': len(merged_products),
        'quicksell_count': len(quicksell_items),
        'organic_count': organic_count,
        'store_count': stores.count(),
        'wishlisted_ids': wishlisted_ids,
        'sponsored_ids': sponsored_ids,
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
        Product.objects.publicly_visible(),
        slug=slug,
    )
    return redirect('product_detail_public', store_slug=product.store.slug, product_slug=product.slug)


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

    # QuickSell counts for current user
    from apps.quicksell.models import QuickSell
    user_qs = QuickSell.objects.filter(user=request.user)
    active_count = user_qs.active().count()
    expired_count = user_qs.expired().count()

    context = {
        'profile': profile,
        'active_listings_count': active_count,
        'expired_listings_count': expired_count,
    }
    return render(request, 'marketplace/profile.html', context)


def _validate_nigerian_phone(phone):
    """
    Validate a Nigerian phone number.
    Accepts: 0XXXXXXXXXX (11 digits) or +234XXXXXXXXXX (13 digits)
    Returns cleaned phone or raises ValueError.
    """
    import re
    if not phone:
        return phone
    phone = re.sub(r'[\s\-\(\)]', '', phone.strip())
    if not re.match(r'^(0|\+234)[7-9][0-1]\d{8}$', phone):
        raise ValueError('Enter a valid Nigerian phone number (e.g. 080XXXXXXXX or +234XXXXXXXXXX)')
    return phone


@buyer_required
def personal_information(request):
    """Personal Information page — dedicated profile editing."""
    try:
        profile = request.user.buyer_profile
    except Exception:
        profile = None

    if request.method == 'POST':
        from apps.users.models import BuyerProfile
        profile, _ = BuyerProfile.objects.get_or_create(user=request.user)
        profile.full_name = request.POST.get('full_name', '')
        phone = request.POST.get('phone', '')
        try:
            phone = _validate_nigerian_phone(phone)
        except ValueError as e:
            messages.error(request, str(e))
            return redirect('marketplace:personal_information')
        profile.phone = phone
        profile.save()
        messages.success(request, 'Profile updated.')
        return redirect('marketplace:personal_information')

    return render(request, 'marketplace/personal_information.html', {'profile': profile})


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


def help_center(request):
    """Help Center / FAQ page."""
    return render(request, 'marketplace/help.html')


def buyer_protection(request):
    """Buyer Protection page."""
    return render(request, 'marketplace/buyer_protection.html')


# ==========================================
# PRODUCT REPORT
# ==========================================

@require_POST
def report_product(request, product_id):
    """
    AJAX endpoint: anyone (logged-in or anonymous) can report a product.
    Creates a ProductReport record and notifies admin.
    Rate-limited: one report per IP per product per 24 hours.
    """
    from apps.vendors.models import Product
    from apps.marketplace.models import ProductReport
    from apps.marketplace.forms import ProductReportForm

    product = get_object_or_404(Product.objects.publicly_visible(), id=product_id)

    # Prevent vendor from reporting their own product (only check if logged in)
    if request.user.is_authenticated and hasattr(request.user, 'vendorprofile') and request.user.vendorprofile == product.store.vendor:
        return JsonResponse({'success': False, 'message': 'You cannot report your own product.'}, status=400)

    # Rate limit: one report per IP per product per 24 hours
    ip = request.META.get('HTTP_X_FORWARDED_FOR', request.META.get('REMOTE_ADDR', '')).split(',')[0].strip()
    cutoff = timezone.now() - timedelta(hours=24)
    recent = ProductReport.objects.filter(
        product=product,
        created_at__gte=cutoff,
    )
    if ip:
        recent = recent.filter(reporter_ip=ip)
    if recent.exists():
        return JsonResponse({'success': False, 'message': 'You have already reported this product recently. Please try again later.'}, status=429)

    form = ProductReportForm(request.POST)
    if form.is_valid():
        ProductReport.objects.create(
            reporter=request.user if request.user.is_authenticated else None,
            product=product,
            reason=form.cleaned_data['reason'],
            details=form.cleaned_data['details'],
            reporter_ip=ip or None,
        )
        return JsonResponse({'success': True, 'message': 'Report submitted. Our team will review it shortly.'})

    return JsonResponse({'success': False, 'message': 'Invalid submission. Please try again.'}, status=400)


def community_guidelines(request):
    """Community Guidelines page."""
    return render(request, 'marketplace/community_guidelines.html')


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


# ==========================================
# BUYER NOTIFICATIONS
# ==========================================

@login_required
def buyer_notifications_list(request):
    """List all notifications for the logged-in buyer."""
    from apps.vendors.models import Notification

    notifications = Notification.objects.filter(
        user=request.user
    ).order_by('-created_at')

    filter_value = request.GET.get('filter', '')
    if filter_value == 'unread':
        notifications = notifications.filter(is_read=False)
    elif filter_value in ['system', 'verification', 'admin_message', 'inventory', 'wishlist']:
        notifications = notifications.filter(notification_type=filter_value)

    paginator = Paginator(notifications, 20)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    unread_count = Notification.objects.filter(
        user=request.user, is_read=False
    ).count()

    return render(request, 'marketplace/notifications/list.html', {
        'page_obj': page_obj,
        'notifications': page_obj,
        'unread_count': unread_count,
    })


@login_required
def buyer_notification_detail(request, notification_id):
    """View a single notification for the logged-in buyer."""
    from apps.vendors.models import Notification
    from django.utils import timezone as tz

    notification = get_object_or_404(
        Notification, id=notification_id, user=request.user
    )

    if not notification.is_read:
        notification.is_read = True
        notification.read_at = tz.now()
        notification.save()

    return render(request, 'marketplace/notifications/detail.html', {
        'notification': notification,
    })


@login_required
@require_POST
def buyer_notification_mark_read(request, notification_id):
    """Mark a single notification as read."""
    from apps.vendors.models import Notification
    from django.utils import timezone as tz

    notification = get_object_or_404(
        Notification, id=notification_id, user=request.user
    )
    if not notification.is_read:
        notification.is_read = True
        notification.read_at = tz.now()
        notification.save()
    return redirect('marketplace:buyer_notification_detail', notification_id=notification.id)


@login_required
@require_POST
def buyer_notification_delete(request, notification_id):
    """Delete a single notification."""
    from apps.vendors.models import Notification

    notification = get_object_or_404(
        Notification, id=notification_id, user=request.user
    )
    notification.delete()
    return redirect('marketplace:buyer_notifications_list')


@login_required
@require_POST
def buyer_notifications_mark_all_read(request):
    """Mark all unread notifications as read."""
    from apps.vendors.models import Notification
    from django.utils import timezone as tz

    qs = Notification.objects.filter(user=request.user, is_read=False)
    qs.update(is_read=True, read_at=tz.now())
    return redirect('marketplace:buyer_notifications_list')