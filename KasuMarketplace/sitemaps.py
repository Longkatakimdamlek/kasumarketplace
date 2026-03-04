from django.contrib.sitemaps import Sitemap
from django.urls import reverse
from apps.marketplace.models import Product, Category
from apps.vendors.models import Vendor

# ----------------------------
# Static pages (like homepage)
# ----------------------------
class StaticViewSitemap(Sitemap):
    priority = 1.0
    changefreq = 'weekly'

    def items(self):
        # Replace with all static pages if you have more
        return ['marketplace:product_list']

    def location(self, item):
        # Only return the path; Django will handle domain/scheme
        return reverse(item)


# ----------------------------
# Product pages
# ----------------------------
class ProductSitemap(Sitemap):
    changefreq = 'weekly'
    priority = 0.9

    def items(self):
        return Product.objects.filter(is_active=True)

    def location(self, obj):
        # Use the marketplace namespace for product detail
        return reverse('marketplace:product_detail', args=[obj.slug])


# ----------------------------
# Category pages
# ----------------------------
class CategorySitemap(Sitemap):
    changefreq = 'weekly'
    priority = 0.8

    def items(self):
        return Category.objects.all()

    def location(self, obj):
        # Assuming you have a category detail view
        return reverse('marketplace:category_detail', args=[obj.slug])


# ----------------------------
# Vendor store pages
# ----------------------------
class VendorSitemap(Sitemap):
    changefreq = 'weekly'
    priority = 0.8

    def items(self):
        return Vendor.objects.filter(is_active=True)

    def location(self, obj):
        # Public store page
        return reverse('vendors:store_public', args=[obj.slug])


# ----------------------------
# Sitemaps dictionary
# ----------------------------
sitemaps = {
    'static': StaticViewSitemap,
    'products': ProductSitemap,
    'categories': CategorySitemap,
    'vendors': VendorSitemap,
}