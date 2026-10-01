"""
Phase 3 - Visibility Inversion
==============================
A restricted vendor (qualification failed, trial expired, subscription
expired, past due) stays PUBLIC: store, products and prices remain listed and
indexed.  Only admin suspension and is_published hide a store/product.

Covered here:
  - Store/Product.objects.publicly_visible() across every subscription state
  - the exclusions (unpublished store, suspended vendor, unpublished product)
  - public store page / product detail pages (200 vs 404, owner preview)
  - sitemaps
  - VendorProfile.is_available / Store.is_vendor_available (Phase 4 helpers)
  - marketplace product list and search

No mocks: these tests use real model rows only.
"""

from datetime import timedelta

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.users.models import CustomUser
from apps.vendors.models import (
    MainCategory, SubCategory, Store, Product, Subscription, VendorProfile,
)
from KasuMarketplace.sitemaps import ProductSitemap, VendorSitemap


class VisibilityFixture(TestCase):
    """Shared vendor / store / product factory."""

    def setUp(self):
        self.category = MainCategory.objects.create(name='Electronics', slug='electronics')
        self.subcategory = SubCategory.objects.create(
            main_category=self.category, name='Phones', slug='phones',
        )

    def make_vendor(
        self,
        key,
        sub_fields=None,
        store_published=True,
        verification_status='pending',
        product_status='published',
        delete_subscription=False,
    ):
        user = CustomUser.objects.create_user(
            email=f'{key}@example.com',
            password='password123',
            username=key.replace('-', '_'),
            role='vendor',
        )
        vendor = user.vendorprofile
        if verification_status != 'pending':
            vendor.verification_status = verification_status
            vendor.save(update_fields=['verification_status'])

        store = Store.objects.create(
            vendor=vendor,
            store_name=f'{key} store',
            slug=key,
            main_category=self.category,
            is_published=store_published,
        )
        product = Product.objects.create(
            vendor=vendor,
            store=store,
            subcategory=self.subcategory,
            title=f'{key} product',
            slug=f'{key}-product',
            description='A product for visibility tests',
            price='2500.00',
            status=product_status,
        )

        # Product.save() republishes the store whenever a product is published
        # (models.py:1285-1300), so the requested store state is enforced after
        # the product row exists.
        if not store_published:
            Store.objects.filter(pk=store.pk).update(is_published=False)
            store.is_published = False

        subscription = Subscription.objects.get(vendor=vendor)
        if delete_subscription:
            subscription.delete()
        elif sub_fields:
            for field, value in sub_fields.items():
                setattr(subscription, field, value)
            subscription.save()

        # Re-fetch: the factory steps above can cache the profile -> subscription
        # relation before the mutation, and is_available would then read the
        # stale row.  A freshly loaded instance starts with an empty cache.
        vendor = VendorProfile.objects.get(pk=vendor.pk)
        store.vendor = vendor
        product.vendor = vendor
        product.store = store
        return vendor, store, product

    @staticmethod
    def assert_visible(case, store, product):
        stores = list(Store.objects.publicly_visible())
        products = list(Product.objects.publicly_visible())
        case.assertIn(store, stores, f'{case._testMethodName}: store missing')
        case.assertIn(product, products, f'{case._testMethodName}: product missing')

    @staticmethod
    def assert_hidden(case, store, product):
        stores = list(Store.objects.publicly_visible())
        products = list(Product.objects.publicly_visible())
        case.assertNotIn(store, stores, f'{case._testMethodName}: store still listed')
        case.assertNotIn(product, products, f'{case._testMethodName}: product still listed')


class PubliclyVisibleSubscriptionStateTests(VisibilityFixture):
    """Every subscription state keeps an is_published store/product public."""

    def test_trial_valid_is_visible(self):
        vendor, store, product = self.make_vendor(
            'trial-valid',
            sub_fields={'status': 'trial', 'trial_ends_at': timezone.now() + timedelta(days=10)},
        )
        self.assert_visible(self, store, product)

    def test_trial_expired_is_visible(self):
        vendor, store, product = self.make_vendor(
            'trial-expired',
            sub_fields={'status': 'trial', 'trial_ends_at': timezone.now() - timedelta(days=1)},
        )
        self.assert_visible(self, store, product)

    def test_active_valid_is_visible(self):
        vendor, store, product = self.make_vendor(
            'active-valid',
            sub_fields={'status': 'active', 'period_end': timezone.now() + timedelta(days=20)},
        )
        self.assert_visible(self, store, product)

    def test_active_expired_is_visible(self):
        vendor, store, product = self.make_vendor(
            'active-expired',
            sub_fields={'status': 'active', 'period_end': timezone.now() - timedelta(days=1)},
        )
        self.assert_visible(self, store, product)

    def test_past_due_in_grace_is_visible(self):
        vendor, store, product = self.make_vendor(
            'past-due-grace',
            sub_fields={'status': 'past_due', 'grace_ends_at': timezone.now() + timedelta(days=2)},
        )
        self.assert_visible(self, store, product)

    def test_past_due_after_grace_is_visible(self):
        vendor, store, product = self.make_vendor(
            'past-due-old',
            sub_fields={'status': 'past_due', 'grace_ends_at': timezone.now() - timedelta(days=2)},
        )
        self.assert_visible(self, store, product)

    def test_cancelled_in_grace_is_visible(self):
        vendor, store, product = self.make_vendor(
            'cancelled-grace',
            sub_fields={'status': 'cancelled', 'grace_ends_at': timezone.now() + timedelta(days=2)},
        )
        self.assert_visible(self, store, product)

    def test_expired_status_is_visible(self):
        vendor, store, product = self.make_vendor(
            'expired-status',
            sub_fields={'status': 'expired'},
        )
        self.assert_visible(self, store, product)

    def test_cancel_at_period_end_and_expired_is_visible(self):
        vendor, store, product = self.make_vendor(
            'cancel-past-end',
            sub_fields={
                'status': 'expired',
                'cancel_at_period_end': True,
                'period_end': timezone.now() - timedelta(days=1),
            },
        )
        self.assert_visible(self, store, product)

    def test_vendor_without_subscription_row_is_visible(self):
        vendor, store, product = self.make_vendor('no-subscription', delete_subscription=True)
        self.assertFalse(Subscription.objects.filter(vendor=vendor).exists())
        self.assert_visible(self, store, product)


class PubliclyVisibleExclusionTests(VisibilityFixture):
    """The only things that hide a store/product: unpublished + suspended."""

    def test_unpublished_store_is_hidden(self):
        vendor, store, product = self.make_vendor(
            'unpublished-store',
            sub_fields={'status': 'active', 'period_end': timezone.now() + timedelta(days=20)},
            store_published=False,
        )
        self.assert_hidden(self, store, product)

    def test_suspended_vendor_is_hidden_even_when_published(self):
        vendor, store, product = self.make_vendor(
            'suspended-vendor',
            sub_fields={'status': 'active', 'period_end': timezone.now() + timedelta(days=20)},
            store_published=True,
            verification_status='suspended',
        )
        self.assert_hidden(self, store, product)

    def test_unpublished_product_is_hidden_even_when_store_visible(self):
        vendor, store, product = self.make_vendor(
            'draft-product',
            sub_fields={'status': 'active', 'period_end': timezone.now() + timedelta(days=20)},
            store_published=True,
            product_status='draft',
        )
        self.assertIn(store, list(Store.objects.publicly_visible()))
        self.assertNotIn(product, list(Product.objects.publicly_visible()))


class PublicPageTests(VisibilityFixture):
    """Store / product pages: 200 for restricted, 404 for suspended/unpublished."""

    def test_store_page_200_for_expired_vendor(self):
        vendor, store, product = self.make_vendor(
            'page-expired',
            sub_fields={'status': 'expired'},
        )
        response = self.client.get(reverse('store_public', kwargs={'slug': store.slug}))
        self.assertEqual(response.status_code, 200)

    def test_product_detail_200_for_expired_vendor(self):
        vendor, store, product = self.make_vendor(
            'page-expired-product',
            sub_fields={'status': 'expired'},
        )
        response = self.client.get(
            reverse('product_detail_public', kwargs={
                'store_slug': store.slug, 'product_slug': product.slug,
            })
        )
        self.assertEqual(response.status_code, 200)

    def test_store_page_404_for_suspended_vendor(self):
        vendor, store, product = self.make_vendor(
            'page-suspended',
            sub_fields={'status': 'active', 'period_end': timezone.now() + timedelta(days=20)},
            verification_status='suspended',
        )
        response = self.client.get(reverse('store_public', kwargs={'slug': store.slug}))
        self.assertEqual(response.status_code, 404)

    def test_product_detail_404_for_suspended_vendor(self):
        vendor, store, product = self.make_vendor(
            'page-suspended-product',
            sub_fields={'status': 'active', 'period_end': timezone.now() + timedelta(days=20)},
            verification_status='suspended',
        )
        response = self.client.get(
            reverse('product_detail_public', kwargs={
                'store_slug': store.slug, 'product_slug': product.slug,
            })
        )
        self.assertEqual(response.status_code, 404)

    def test_store_page_404_for_unpublished_store(self):
        vendor, store, product = self.make_vendor(
            'page-unpublished',
            sub_fields={'status': 'active', 'period_end': timezone.now() + timedelta(days=20)},
            store_published=False,
        )
        response = self.client.get(reverse('store_public', kwargs={'slug': store.slug}))
        self.assertEqual(response.status_code, 404)

    def test_owner_preview_still_works_for_unpublished_store(self):
        vendor, store, product = self.make_vendor(
            'page-owner-preview',
            sub_fields={'status': 'expired'},
            store_published=False,
        )
        self.client.force_login(vendor.user)
        store_response = self.client.get(
            reverse('store_public', kwargs={'slug': store.slug})
        )
        product_response = self.client.get(
            reverse('product_detail_public', kwargs={
                'store_slug': store.slug, 'product_slug': product.slug,
            })
        )
        self.assertEqual(store_response.status_code, 200)
        self.assertEqual(product_response.status_code, 200)


class SitemapVisibilityTests(VisibilityFixture):
    """Sitemaps follow the managers: restricted in, suspended/unpublished out."""

    def test_sitemap_includes_expired_vendor_store_and_product(self):
        vendor, store, product = self.make_vendor('sitemap-expired', sub_fields={'status': 'expired'})
        self.assertIn(store, list(VendorSitemap().items()))
        self.assertIn(product, list(ProductSitemap().items()))

    def test_sitemap_excludes_suspended_vendor(self):
        vendor, store, product = self.make_vendor(
            'sitemap-suspended',
            sub_fields={'status': 'active', 'period_end': timezone.now() + timedelta(days=20)},
            verification_status='suspended',
        )
        self.assertNotIn(store, list(VendorSitemap().items()))
        self.assertNotIn(product, list(ProductSitemap().items()))

    def test_sitemap_excludes_unpublished_store(self):
        vendor, store, product = self.make_vendor(
            'sitemap-unpublished',
            sub_fields={'status': 'active', 'period_end': timezone.now() + timedelta(days=20)},
            store_published=False,
        )
        self.assertNotIn(store, list(VendorSitemap().items()))
        self.assertNotIn(product, list(ProductSitemap().items()))


class VendorAvailabilityTests(VisibilityFixture):
    """is_available is the availability semantics, not a visibility one."""

    def test_available_states(self):
        cases = [
            ('avail-trial', {'status': 'trial', 'trial_ends_at': timezone.now() + timedelta(days=5)}),
            ('avail-active', {'status': 'active', 'period_end': timezone.now() + timedelta(days=5)}),
            ('avail-past-due', {'status': 'past_due', 'grace_ends_at': timezone.now() + timedelta(days=2)}),
            ('avail-cancelled', {'status': 'cancelled', 'grace_ends_at': timezone.now() + timedelta(days=2)}),
        ]
        for key, fields in cases:
            vendor, store, product = self.make_vendor(key, sub_fields=fields)
            self.assertTrue(vendor.is_available, key)
            self.assertTrue(store.is_vendor_available, key)

    def test_unavailable_states(self):
        cases = [
            ('unavail-trial', {'status': 'trial', 'trial_ends_at': timezone.now() - timedelta(days=1)}),
            ('unavail-active', {'status': 'active', 'period_end': timezone.now() - timedelta(days=1)}),
            ('unavail-expired', {'status': 'expired'}),
            ('unavail-past-due-old', {'status': 'past_due', 'grace_ends_at': timezone.now() - timedelta(days=1)}),
        ]
        for key, fields in cases:
            vendor, store, product = self.make_vendor(key, sub_fields=fields)
            self.assertFalse(vendor.is_available, key)
            self.assertFalse(store.is_vendor_available, key)

    def test_unavailable_when_subscription_row_missing(self):
        vendor, store, product = self.make_vendor('unavail-no-sub', delete_subscription=True)
        self.assertFalse(vendor.is_available)
        self.assertFalse(store.is_vendor_available)


class MarketplaceListingTests(VisibilityFixture):
    """An expired vendor's product is still listed and searchable."""

    def test_expired_vendor_product_appears_in_product_list(self):
        vendor, store, product = self.make_vendor(
            'listing-expired',
            sub_fields={'status': 'expired'},
        )
        response = self.client.get(reverse('marketplace:product_list'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, product.title)

    def test_expired_vendor_product_appears_in_search_results(self):
        vendor, store, product = self.make_vendor(
            'search-expired',
            sub_fields={'status': 'expired'},
        )
        response = self.client.get(reverse('marketplace:search'), {'q': product.title})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, product.title)

    def test_expired_vendor_store_appears_in_store_directory(self):
        vendor, store, product = self.make_vendor(
            'directory-expired',
            sub_fields={'status': 'expired'},
        )
        response = self.client.get(reverse('marketplace:store_directory'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, store.store_name)
