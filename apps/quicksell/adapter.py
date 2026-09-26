"""
Quick Sell Marketplace Adapter

Provides a lightweight adapter that makes QuickSell objects compatible
with the existing marketplace product card template.

This is the SAFEST integration approach — it does NOT:
- Modify the Product model
- Modify the existing product card template
- Create fake VendorProfile/Store objects
- Change existing marketplace queries

It ONLY provides attribute compatibility for template rendering.
"""

from django.utils import timezone


class QuickSellStoreAdapter:
    """
    Minimal adapter that provides store-like attributes for QuickSell.
    Used by the product card template which expects item.store.*
    """

    def __init__(self, listing):
        self._listing = listing
        self.slug = f"quicksell-{listing.slug}"
        self.store_name = "Quick Sell"
        self.whatsapp = listing.whatsapp or ''
        self.phone = listing.phone or ''

    @property
    def vendor(self):
        return QuickSellVendorAdapter(self._listing)


class QuickSellVendorAdapter:
    """
    Minimal adapter that provides vendor-like attributes for QuickSell.
    Used by the product card template which expects item.store.vendor.*
    """

    def __init__(self, listing):
        self._listing = listing
        self.is_verified = False


class QuickSellImageAdapter:
    """
    Minimal adapter that provides image-like attributes for QuickSell.
    Used by the product card template which expects item.images.all|first
    """

    def __init__(self, image):
        self.image = image.image


class QuickSellQuerySetAdapter:
    """
    Makes a QuickSell QuerySet behave like a Product QuerySet
    for template compatibility.
    """

    def __init__(self, queryset):
        self._queryset = queryset

    def __iter__(self):
        for listing in self._queryset:
            yield QuickSellAdapter(listing)

    def __len__(self):
        return self._queryset.count()

    def __bool__(self):
        return self._queryset.exists()


class QuickSellAdapter:
    """
    Lightweight adapter that makes a QuickSell object compatible
    with the existing marketplace product card template.

    The product card expects:
    - item.store.slug → f"quicksell-{slug}"
    - item.store.store_name → "Quick Sell"
    - item.store.vendor.is_verified → False
    - item.store.whatsapp → listing.whatsapp
    - item.store.phone → listing.phone
    - item.images.all|first → adapted image
    - item.title → listing.title
    - item.slug → listing.slug
    - item.price → listing.price
    - item.compare_at_price → listing.compare_at_price
    - item.description → listing.description
    - item.distance → attached later
    - item.discount_percentage → 0 (QuickSell doesn't track this)
    - item.review_count → 0 (QuickSell doesn't have reviews)
    - item.average_rating → 0 (QuickSell doesn't have ratings)
    - item.track_inventory → False
    - item.stock_quantity → 0
    - item.low_stock_threshold → 0
    - item.is_sponsored → False
    - item.sponsored_until → None
    - item.sponsored_priority → 0
    - item.is_featured → False
    - item.pk → listing.pk
    - item.is_quicksell → True (new attribute for template differentiation)
    """

    def __init__(self, listing):
        self._listing = listing
        self.is_quicksell = True

    @property
    def pk(self):
        return self._listing.pk

    @property
    def title(self):
        return self._listing.title

    @property
    def slug(self):
        return self._listing.slug

    @property
    def description(self):
        return self._listing.description

    @property
    def price(self):
        return self._listing.price

    @property
    def compare_at_price(self):
        return self._listing.compare_at_price

    @property
    def created_at(self):
        return self._listing.created_at

    @property
    def store(self):
        return QuickSellStoreAdapter(self._listing)

    @property
    def images(self):
        return QuickSellImagesProxy(self._listing)

    @property
    def distance(self):
        return getattr(self, '_distance', None)

    @distance.setter
    def distance(self, value):
        self._distance = value

    @property
    def discount_percentage(self):
        return 0

    @property
    def review_count(self):
        return 0

    @property
    def average_rating(self):
        return 0

    @property
    def track_inventory(self):
        return False

    @property
    def stock_quantity(self):
        return 0

    @property
    def low_stock_threshold(self):
        return 0

    @property
    def is_sponsored(self):
        return False

    @property
    def sponsored_until(self):
        return None

    @property
    def sponsored_priority(self):
        return 0

    @property
    def is_featured(self):
        return False

    @property
    def subcategory(self):
        return self._listing.subcategory

    @property
    def main_category(self):
        return self._listing.main_category

    def get_absolute_url(self):
        """Return the QuickSell detail URL."""
        from django.urls import reverse
        return reverse('quicksell:detail', kwargs={'slug': self.slug})


class QuickSellImagesProxy:
    """
    Proxy that makes QuickSell images behave like Product images.
    The product card uses: item.images.all|first
    """

    def __init__(self, listing):
        self._listing = listing

    def all(self):
        """Return adapted images."""
        return [
            QuickSellImageAdapter(img)
            for img in self._listing.images.all()
        ]


def adapt_quicksell_queryset(queryset):
    """
    Wrap a QuickSell queryset to return adapters.
    Used in views that combine Product and QuickSell results.
    """
    return [QuickSellAdapter(listing) for listing in queryset]
