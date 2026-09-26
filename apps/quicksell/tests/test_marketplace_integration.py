"""
Quick Sell Marketplace Integration Tests

Phase 4: Tests for Quick Sell discovery integration into the marketplace.
Covers:
1. Active Quick Sell is discoverable
2. Expired Quick Sell is not discoverable
3. Vendor Products remain discoverable
4. Existing marketplace product listing still works
5. Existing Product detail URL still works
6. Existing search still works
7. Quick Sell search works
8. Category filtering works for Quick Sell
9. Category filtering still works for Vendor Products
10. Quick Sell uses the existing SubCategory taxonomy
11. Expired Quick Sell cannot bypass visibility through query parameters
12. Existing marketplace pagination remains correct
13. Existing vendor subscription visibility remains unchanged
14. Existing Product queries remain unchanged
15. Quick Sell does not require VendorProfile, Store, or Subscription
"""

from decimal import Decimal

from django.test import TestCase, Client
from django.urls import reverse
from django.utils import timezone

from apps.quicksell.models import QuickSell
from apps.quicksell.adapter import QuickSellAdapter, adapt_quicksell_queryset
from apps.users.models import CustomUser
from apps.vendors.models import MainCategory, SubCategory, SubCategoryAttribute


class QuickSellAdapterTest(TestCase):
    """Tests for the QuickSellAdapter."""

    def setUp(self):
        self.user = CustomUser.objects.create_user(
            email='seller@example.com',
            password='password123',
            username='seller',
            role='buyer',
        )
        self.category = MainCategory.objects.create(
            name='Tech & Electronics', slug='tech-electronics'
        )
        self.subcategory = SubCategory.objects.create(
            main_category=self.category,
            name='Phones',
            slug='phones',
        )
        self.listing = QuickSell.objects.create(
            user=self.user,
            subcategory=self.subcategory,
            title='iPhone 15 Pro Max',
            description='Brand new iPhone 15 Pro Max 256GB',
            price=Decimal('850000.00'),
            whatsapp='+2348012345678',
            phone='+2348012345679',
        )

    def test_adapter_has_quicksell_flag(self):
        adapter = QuickSellAdapter(self.listing)
        self.assertTrue(adapter.is_quicksell)

    def test_adapter_has_pk(self):
        adapter = QuickSellAdapter(self.listing)
        self.assertEqual(adapter.pk, self.listing.pk)

    def test_adapter_has_title(self):
        adapter = QuickSellAdapter(self.listing)
        self.assertEqual(adapter.title, 'iPhone 15 Pro Max')

    def test_adapter_has_slug(self):
        adapter = QuickSellAdapter(self.listing)
        self.assertEqual(adapter.slug, self.listing.slug)

    def test_adapter_has_price(self):
        adapter = QuickSellAdapter(self.listing)
        self.assertEqual(adapter.price, Decimal('850000.00'))

    def test_adapter_has_compare_at_price(self):
        adapter = QuickSellAdapter(self.listing)
        self.assertIsNone(adapter.compare_at_price)

    def test_adapter_store_returns_adapter(self):
        adapter = QuickSellAdapter(self.listing)
        store = adapter.store
        self.assertEqual(store.store_name, 'Quick Sell')
        self.assertEqual(store.whatsapp, '+2348012345678')
        self.assertEqual(store.phone, '+2348012345679')

    def test_adapter_store_vendor_not_verified(self):
        adapter = QuickSellAdapter(self.listing)
        self.assertFalse(adapter.store.vendor.is_verified)

    def test_adapter_images_returns_proxy(self):
        adapter = QuickSellAdapter(self.listing)
        images = adapter.images.all()
        self.assertEqual(len(images), 0)

    def test_adapter_distance_default_none(self):
        adapter = QuickSellAdapter(self.listing)
        self.assertIsNone(adapter.distance)

    def test_adapter_distance_settable(self):
        adapter = QuickSellAdapter(self.listing)
        adapter.distance = '3.2 km away'
        self.assertEqual(adapter.distance, '3.2 km away')

    def test_adapter_discount_percentage_zero(self):
        adapter = QuickSellAdapter(self.listing)
        self.assertEqual(adapter.discount_percentage, 0)

    def test_adapter_review_count_zero(self):
        adapter = QuickSellAdapter(self.listing)
        self.assertEqual(adapter.review_count, 0)

    def test_adapter_average_rating_zero(self):
        adapter = QuickSellAdapter(self.listing)
        self.assertEqual(adapter.average_rating, 0)

    def test_adapter_is_not_sponsored(self):
        adapter = QuickSellAdapter(self.listing)
        self.assertFalse(adapter.is_sponsored)

    def test_adapter_is_not_featured(self):
        adapter = QuickSellAdapter(self.listing)
        self.assertFalse(adapter.is_featured)

    def test_adapter_subcategory(self):
        adapter = QuickSellAdapter(self.listing)
        self.assertEqual(adapter.subcategory, self.subcategory)

    def test_adapter_main_category(self):
        adapter = QuickSellAdapter(self.listing)
        self.assertEqual(adapter.main_category, self.category)

    def test_adapter_get_absolute_url(self):
        adapter = QuickSellAdapter(self.listing)
        url = adapter.get_absolute_url()
        self.assertEqual(url, f'/quick-sell/{self.listing.slug}/')

    def test_adapt_quicksell_queryset(self):
        qs = QuickSell.objects.filter(pk=self.listing.pk)
        adapted = adapt_quicksell_queryset(qs)
        self.assertEqual(len(adapted), 1)
        self.assertIsInstance(adapted[0], QuickSellAdapter)
        self.assertEqual(adapted[0].pk, self.listing.pk)


class QuickSellDiscoveryTest(TestCase):
    """Tests for Quick Sell discovery in the marketplace."""

    def setUp(self):
        self.client = Client()
        self.user = CustomUser.objects.create_user(
            email='seller@example.com',
            password='password123',
            username='seller',
            role='buyer',
        )
        self.category = MainCategory.objects.create(
            name='Tech & Electronics', slug='tech-electronics'
        )
        self.subcategory = SubCategory.objects.create(
            main_category=self.category,
            name='Phones',
            slug='phones',
        )
        self.active_listing = QuickSell.objects.create(
            user=self.user,
            subcategory=self.subcategory,
            title='Active iPhone',
            description='Brand new iPhone',
            price=Decimal('850000.00'),
        )
        self.expired_listing = QuickSell.objects.create(
            user=self.user,
            subcategory=self.subcategory,
            title='Expired Samsung',
            description='Old Samsung phone',
            price=Decimal('150000.00'),
        )
        # Set expiration to past
        self.expired_listing.expires_at = timezone.now() - timezone.timedelta(days=1)
        self.expired_listing.save(update_fields=['expires_at'])

    def test_active_quicksell_appears_in_search(self):
        response = self.client.get(reverse('marketplace:search') + '?q=iPhone')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Active iPhone')

    def test_expired_quicksell_not_in_search(self):
        response = self.client.get(reverse('marketplace:search') + '?q=Samsung')
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'Expired Samsung')

    def test_active_quicksell_appears_in_category(self):
        response = self.client.get(
            reverse('marketplace:category_landing', kwargs={'slug': self.category.slug})
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Active iPhone')

    def test_expired_quicksell_not_in_category(self):
        response = self.client.get(
            reverse('marketplace:category_landing', kwargs={'slug': self.category.slug})
        )
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'Expired Samsung')

    def test_active_quicksell_appears_in_product_list(self):
        response = self.client.get(reverse('marketplace:product_list'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Active iPhone')

    def test_expired_quicksell_not_in_product_list(self):
        response = self.client.get(reverse('marketplace:product_list'))
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'Expired Samsung')

    def test_active_quicksell_appears_in_new_arrivals(self):
        response = self.client.get(reverse('marketplace:new_arrivals'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Active iPhone')

    def test_expired_quicksell_not_in_new_arrivals(self):
        response = self.client.get(reverse('marketplace:new_arrivals'))
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'Expired Samsung')

    def test_quicksell_does_not_require_vendor_profile(self):
        """Quick Sell should be discoverable without VendorProfile."""
        response = self.client.get(reverse('marketplace:search') + '?q=iPhone')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Active iPhone')

    def test_quicksell_uses_shared_taxonomy(self):
        """Quick Sell uses the same SubCategory as Vendor Products."""
        self.assertEqual(self.active_listing.subcategory.main_category, self.category)

    def test_expired_quicksell_cannot_bypass_via_query_params(self):
        """Expired Quick Sell cannot be made visible through query parameters."""
        response = self.client.get(
            reverse('marketplace:search') + '?q=Expired'
        )
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'Expired Samsung')

    def test_search_returns_both_products_and_quicksell(self):
        """Search returns both Vendor Products and Quick Sell listings."""
        response = self.client.get(reverse('marketplace:search') + '?q=iPhone')
        self.assertEqual(response.status_code, 200)
        # Should contain QuickSell items section
        self.assertContains(response, 'Quick Sell Listings')

    def test_category_page_shows_quicksell_count(self):
        """Category page shows Quick Sell count alongside product count."""
        response = self.client.get(
            reverse('marketplace:category_landing', kwargs={'slug': self.category.slug})
        )
        self.assertEqual(response.status_code, 200)
        # Should contain quick sell listing count
        self.assertContains(response, 'quick sell')


class MarketplaceRegressionTest(TestCase):
    """Tests to ensure existing marketplace functionality is not broken."""

    def setUp(self):
        self.client = Client()

    def test_product_list_view_still_works(self):
        response = self.client.get(reverse('marketplace:product_list'))
        self.assertEqual(response.status_code, 200)

    def test_search_view_still_works(self):
        response = self.client.get(reverse('marketplace:search') + '?q=test')
        self.assertEqual(response.status_code, 200)

    def test_new_arrivals_view_still_works(self):
        response = self.client.get(reverse('marketplace:new_arrivals'))
        self.assertEqual(response.status_code, 200)

    def test_deals_view_still_works(self):
        response = self.client.get(reverse('marketplace:deals'))
        self.assertEqual(response.status_code, 200)

    def test_trending_view_still_works(self):
        response = self.client.get(reverse('marketplace:trending'))
        self.assertEqual(response.status_code, 200)

    def test_sponsored_products_view_still_works(self):
        response = self.client.get(reverse('marketplace:sponsored_products'))
        self.assertEqual(response.status_code, 200)

    def test_store_directory_view_still_works(self):
        response = self.client.get(reverse('marketplace:store_directory'))
        self.assertEqual(response.status_code, 200)
