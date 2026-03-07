from django.contrib.sitemaps import Sitemap
from django.urls import reverse
from apps.vendors.models import Product, Store

# ----------------------------
# Static pages (like homepage)
# ----------------------------
class StaticViewSitemap(Sitemap):
    priority = 1.0
    changefreq = "weekly"

    def items(self):
        return [
            "marketplace:product_list",
            "marketplace:about",
        ]

    def location(self, item):
        # Only return the path; Django will handle domain/scheme
        return reverse(item)


# ----------------------------
# Product pages
# ----------------------------
class ProductSitemap(Sitemap):
    changefreq = "weekly"
    priority = 0.9

    def items(self):
        return Product.objects.filter(status="published")

    def lastmod(self, obj):
        return obj.updated_at

    def location(self, obj):
        # Use the marketplace namespace for product detail
        return reverse("marketplace:product_detail", args=[obj.slug])


# ----------------------------
# Vendor store pages
# ----------------------------
class VendorSitemap(Sitemap):
    changefreq = "weekly"
    priority = 0.8

    def items(self):
        return Store.objects.filter(vendor__verification_status="approved")

    def location(self, obj):
        # Public store page
        return reverse("vendors:store_public", args=[obj.slug])


# ----------------------------
# Sitemaps dictionary
# ----------------------------
sitemaps = {
    "static": StaticViewSitemap,
    "products": ProductSitemap,
    "vendors": VendorSitemap,
}