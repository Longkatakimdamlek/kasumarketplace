"""
Phase 4 - Contact removal and the "Vendor Unavailable" label
=============================================================
A restricted vendor (trial/subscription expired, past due, no Subscription
row) stays PUBLIC, but the contact controls disappear from every public
page and the label "Vendor Unavailable" is rendered instead.

Covered here:
  - available vendor: product list, product detail and store page still
    show the WhatsApp/Call controls (wa.me + tel: + both numbers)
  - unavailable vendor in every state: product list, search, product
    detail, store page and wishlist page show the label and leak neither
    wa.me, tel:, the phone digits nor the WhatsApp digits
  - the owner sees exactly the same public rendering
  - wishlist "You Might Also Like" (Phase 3 leak fix): a suspended
    vendor's product never appears, an expired vendor's product can
  - contact_intent is refused server-side for an unavailable vendor
  - plan (Basic/Premium) does not change anything, only availability
  - no N+1: the unavailable product list page issues no more queries than
    the same page for the same products while the vendors were available

No mocks: real model rows and real page requests only.
"""

from datetime import timedelta

from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from apps.marketplace.models import Wishlist, ContactIntent
from apps.users.models import CustomUser
from apps.vendors.models import (
    MainCategory, SubCategory, Store, Product, Subscription, VendorProfile,
    Notification,
)

# Deliberately distinctive numbers so assertNotIn on the digits is meaningful.
PHONE = '08099887766'
WHATSAPP = '2348099887766'

NOW = timezone.now()

VALID_TRIAL = {'status': 'trial', 'trial_ends_at': NOW + timedelta(days=10)}
IN_GRACE = {'status': 'past_due', 'grace_ends_at': NOW + timedelta(days=2)}

UNAVAILABLE_STATES = [
    ('trial-expired', {'status': 'trial', 'trial_ends_at': NOW - timedelta(days=1)}),
    ('active-expired', {'status': 'active', 'period_end': NOW - timedelta(days=1)}),
    ('expired-status', {'status': 'expired'}),
    ('past-due-after-grace', {'status': 'past_due', 'grace_ends_at': NOW - timedelta(days=1)}),
    ('no-subscription', None),  # None -> Subscription row is deleted
]

LEAKS = ('wa.me', 'tel:', PHONE, WHATSAPP)


class ContactFixture(TestCase):
    """Shared vendor / store / product factory with phone + WhatsApp set."""

    def setUp(self):
        self.category = MainCategory.objects.create(name='Electronics', slug='ca-electronics')
        self.subcategory = SubCategory.objects.create(
            main_category=self.category, name='Phones', slug='ca-phones',
        )

    def make_vendor(self, key, sub_fields=None, delete_subscription=False,
                    verification_status='pending'):
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
            is_published=True,
            phone=PHONE,
            whatsapp=WHATSAPP,
        )
        product = self.make_product(vendor, store, key)

        subscription = Subscription.objects.get(vendor=vendor)
        if delete_subscription:
            subscription.delete()
        elif sub_fields:
            for field, value in sub_fields.items():
                setattr(subscription, field, value)
            subscription.save()

        # Re-fetch so no stale profile -> subscription cache is read.
        vendor = VendorProfile.objects.get(pk=vendor.pk)
        store.vendor = vendor
        product.store = store
        return vendor, store, product

    def make_product(self, vendor, store, key):
        product = Product.objects.create(
            vendor=vendor,
            store=store,
            subcategory=self.subcategory,
            title=f'{key} product',
            slug=f'{key}-product',
            description='A product for contact availability tests',
            price='2500.00',
            status='published',
        )
        product.store = store
        return product

    # ---- assertions -------------------------------------------------

    @staticmethod
    def content_of(response):
        return response.content.decode('utf-8')

    def assert_contact_shown(self, response, label):
        content = self.content_of(response)
        self.assertEqual(response.status_code, 200, label)
        self.assertIn('wa.me', content, f'{label}: WhatsApp control missing')
        self.assertIn('tel:', content, f'{label}: call control missing')
        self.assertIn(PHONE, content, f'{label}: phone digits missing')
        self.assertIn(WHATSAPP, content, f'{label}: WhatsApp digits missing')
        self.assertNotIn('Vendor Unavailable', content, label)

    def assert_contact_hidden(self, response, label):
        content = self.content_of(response)
        self.assertEqual(response.status_code, 200, label)
        self.assertIn('Vendor Unavailable', content, f'{label}: label missing')
        for needle in LEAKS:
            self.assertNotIn(needle, content, f'{label}: {needle} leaked')

    # ---- page URLs --------------------------------------------------

    def product_detail_url(self, store, product):
        return reverse('product_detail_public', kwargs={
            'store_slug': store.slug, 'product_slug': product.slug,
        })

    def store_url(self, store):
        return reverse('store_public', kwargs={'slug': store.slug})


class AvailableVendorContactTests(ContactFixture):
    """A vendor with a valid trial keeps every contact control."""

    def test_product_list_shows_contact_controls(self):
        self.make_vendor('avail-list', sub_fields=VALID_TRIAL)
        self.assert_contact_shown(
            self.client.get(reverse('marketplace:product_list')), 'product list',
        )

    def test_product_detail_shows_contact_controls(self):
        vendor, store, product = self.make_vendor('avail-detail', sub_fields=VALID_TRIAL)
        self.assert_contact_shown(
            self.client.get(self.product_detail_url(store, product)), 'product detail',
        )

    def test_store_page_shows_contact_controls(self):
        vendor, store, product = self.make_vendor('avail-store', sub_fields=VALID_TRIAL)
        self.assert_contact_shown(
            self.client.get(self.store_url(store)), 'store page',
        )

    def test_search_results_show_contact_controls(self):
        vendor, store, product = self.make_vendor('avail-search', sub_fields=VALID_TRIAL)
        self.assert_contact_shown(
            self.client.get(reverse('marketplace:search'), {'q': product.title}),
            'search results',
        )

    def test_vendor_in_grace_still_shows_contact(self):
        vendor, store, product = self.make_vendor('avail-grace', sub_fields=IN_GRACE)
        self.assert_contact_shown(
            self.client.get(self.product_detail_url(store, product)), 'in-grace detail',
        )

    def test_premium_available_vendor_shows_contact(self):
        vendor, store, product = self.make_vendor('avail-premium', sub_fields={
            'status': 'active',
            'period_end': NOW + timedelta(days=20),
            'plan': 'premium',
        })
        self.assert_contact_shown(
            self.client.get(self.product_detail_url(store, product)), 'premium detail',
        )

    def test_premium_expired_vendor_hides_contact(self):
        vendor, store, product = self.make_vendor('expired-premium', sub_fields={
            'status': 'active',
            'period_end': NOW - timedelta(days=1),
            'plan': 'premium',
        })
        self.assert_contact_hidden(
            self.client.get(self.product_detail_url(store, product)), 'premium expired',
        )


class UnavailableVendorContactTests(ContactFixture):
    """Every unavailable state: contact gone, label present, on all pages."""

    def assert_hidden_everywhere(self, key, sub_fields, delete_subscription=False):
        vendor, store, product = self.make_vendor(
            key, sub_fields=sub_fields, delete_subscription=delete_subscription,
        )
        self.make_product(vendor, store, f'{key}-extra')

        self.assert_contact_hidden(
            self.client.get(reverse('marketplace:product_list')), 'product list',
        )
        self.assert_contact_hidden(
            self.client.get(reverse('marketplace:search'), {'q': product.title}),
            'search results',
        )
        self.assert_contact_hidden(
            self.client.get(self.product_detail_url(store, product)), 'product detail',
        )
        self.assert_contact_hidden(
            self.client.get(self.store_url(store)), 'store page',
        )

        buyer = CustomUser.objects.create_user(
            email=f'{key}-buyer@example.com',
            password='password123',
            username=f'{key}_buyer'.replace('-', '_'),
            role='buyer',
        )
        Wishlist.objects.create(user=buyer, product=product)
        self.client.force_login(buyer)
        self.assert_contact_hidden(
            self.client.get(reverse('marketplace:wishlist')), 'wishlist page',
        )

    def test_trial_expired(self):
        self.assert_hidden_everywhere('un-trial', UNAVAILABLE_STATES[0][1])

    def test_active_expired(self):
        self.assert_hidden_everywhere('un-active', UNAVAILABLE_STATES[1][1])

    def test_expired_status(self):
        self.assert_hidden_everywhere('un-expired', UNAVAILABLE_STATES[2][1])

    def test_past_due_after_grace(self):
        self.assert_hidden_everywhere('un-past-due', UNAVAILABLE_STATES[3][1])

    def test_no_subscription_row(self):
        self.assert_hidden_everywhere('un-no-sub', None, delete_subscription=True)

    def test_owner_sees_the_same_public_rendering(self):
        vendor, store, product = self.make_vendor(
            'un-owner', sub_fields={'status': 'expired'},
        )
        self.client.force_login(vendor.user)
        self.assert_contact_hidden(
            self.client.get(self.product_detail_url(store, product)),
            'owner product detail',
        )
        self.assert_contact_hidden(
            self.client.get(self.store_url(store)), 'owner store page',
        )

    def test_no_phone_in_structured_data(self):
        vendor, store, product = self.make_vendor(
            'un-schema', sub_fields={'status': 'expired'},
        )
        content = self.content_of(self.client.get(self.product_detail_url(store, product)))
        self.assertNotIn('telephone', content)
        self.assertNotIn('schema.org/telephone', content)


class WishlistRecommendationTests(ContactFixture):
    """Phase 3 leak fix: recommendations use Product.objects.publicly_visible()."""

    def test_suspended_vendor_is_expired_vendor_is_split(self):
        buyer = CustomUser.objects.create_user(
            email='rec-buyer@example.com',
            password='password123',
            username='rec_buyer',
            role='buyer',
        )

        # Expired vendor: still public, so recommendations may include it.
        _, _, expired_product = self.make_vendor(
            'rec-expired', sub_fields={'status': 'expired'},
        )
        # Suspended vendor: hidden by the store rule, must never appear.
        _, _, suspended_product = self.make_vendor(
            'rec-suspended',
            sub_fields={'status': 'active', 'period_end': NOW + timedelta(days=20)},
            verification_status='suspended',
        )
        # A third vendor owns the wishlisted product that seeds the page.
        _, _, wishlisted_product = self.make_vendor(
            'rec-seed', sub_fields={'status': 'expired'},
        )
        Wishlist.objects.create(user=buyer, product=wishlisted_product)

        self.client.force_login(buyer)
        response = self.client.get(reverse('marketplace:wishlist'))
        self.assertEqual(response.status_code, 200)
        content = self.content_of(response)

        self.assertIn(expired_product.title, content)
        self.assertNotIn(suspended_product.title, content)


class ContactIntentAvailabilityTests(ContactFixture):
    """The endpoint refuses an unavailable vendor: no row, no notification."""

    def test_refused_for_unavailable_vendor(self):
        _, _, product = self.make_vendor('ci-unavailable', sub_fields={'status': 'expired'})
        intents_before = ContactIntent.objects.count()
        notifications_before = Notification.objects.count()

        for channel in ('whatsapp', 'call'):
            response = self.client.post(
                reverse('vendors:contact_intent', kwargs={'product_id': product.id}),
                data={'channel': channel},
            )
            self.assertEqual(response.status_code, 403, channel)
            self.assertEqual(response.json()['success'], False)

        self.assertEqual(ContactIntent.objects.count(), intents_before)
        self.assertEqual(Notification.objects.count(), notifications_before)

    def test_still_works_for_available_vendor(self):
        _, _, product = self.make_vendor('ci-available', sub_fields=VALID_TRIAL)
        intents_before = ContactIntent.objects.count()
        notifications_before = Notification.objects.count()

        response = self.client.post(
            reverse('vendors:contact_intent', kwargs={'product_id': product.id}),
            data={'channel': 'whatsapp'},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(ContactIntent.objects.count(), intents_before + 1)
        self.assertEqual(Notification.objects.count(), notifications_before + 1)


class ProductListQueryCountTests(ContactFixture):
    """is_available must not add per-product queries (no N+1)."""

    def test_unavailable_page_issues_no_more_queries(self):
        vendors = []
        for i in range(5):
            vendor, store, product = self.make_vendor(f'qc-avail-{i}', sub_fields=VALID_TRIAL)
            vendors.append(vendor)

        with CaptureQueriesContext(connection) as available_queries:
            response = self.client.get(reverse('marketplace:product_list'))
        self.assertEqual(response.status_code, 200)
        self.assertNotIn('Vendor Unavailable', self.content_of(response))

        # Flip the very same vendors/products to an unavailable state.
        for vendor in vendors:
            subscription = Subscription.objects.get(vendor=vendor)
            subscription.status = 'expired'
            subscription.save()

        with CaptureQueriesContext(connection) as unavailable_queries:
            response = self.client.get(reverse('marketplace:product_list'))
        self.assertEqual(response.status_code, 200)
        self.assertIn('Vendor Unavailable', self.content_of(response))

        self.assertLessEqual(
            len(unavailable_queries), len(available_queries),
            'unavailable rendering issued more queries per product than available',
        )
