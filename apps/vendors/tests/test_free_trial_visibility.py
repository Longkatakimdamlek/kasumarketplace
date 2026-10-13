"""
Free-trial qualification visibility - plans Free card + create-page banner
===========================================================================

The qualification flow becomes visible to the vendor with NO new gate and
NO migration:

  * Subscription plans page - the Free card renders by subscription state:
      qualifying, 0 products  -> "0 of 3 products published" +
                                 "Your 14 days start when you add your first product"
      qualifying, 1-2 products -> "N of 3 products published" + progress bar +
                                 "Add X more product(s) to activate your 3-month free trial" +
                                 "X day(s) left in your window"
      trial_active            -> "Free trial active until <M d, Y>"
      both qualifying branches replace the button row with the primary CTA
                                 "Add products to activate your free trial"
                                 -> vendors:product_create
  * Product-create page - a banner above the form card, qualifying only:
      "Free trial: publish 3 products within 14 days of your first product.
       You've published N of 3."
       (the apostrophe is literal template text, so it is NOT entity-escaped
       by autoescape - only {{ var }} output is; suspended vendors are
       excluded by the view before the descriptor even runs)

Drafts never count (published only).  The restricted / failed / paid states
keep their existing copy - no activation button is offered there.

Query budget (measured before and after the change, this fixture):
  plans page         flat in every state (template-only change; the page
                     already runs the descriptor)
  product-create     flat for trial / paid / expired / suspended (+0) and
                     +1 exactly for qualifying form paths - the one COUNT
                     the banner's own "N of 3" must display
This file is append-only: no existing test was modified.
"""

from datetime import timedelta

from django.contrib.auth import get_user_model
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from apps.users.models import CustomUser
from apps.vendors.models import (
    MainCategory, Product, Store, SubCategory, Subscription, VendorProfile,
)

DAY = timedelta(days=1)

PROMPT_HEADING = 'Subscription needed to add products'
FORM_MARKER = 'id="id_subcategory"'
ACTIVATE_CTA = 'Add products to activate your free trial'
START_COPY = 'Your 14 days start when you add your first product'

QUALIFYING_FIELDS = {'status': 'qualifying', 'plan': 'free'}
TRIAL_FIELDS = {
    'status': 'trial', 'plan': 'free',
    'trial_ends_at': timezone.now() + timedelta(days=30),
}
PAID_FIELDS = {
    'status': 'active', 'plan': 'basic',
    'period_end': timezone.now() + timedelta(days=20),
}
EXPIRED_TRIAL_FIELDS = {
    'status': 'expired', 'plan': 'free',
    'trial_ends_at': timezone.now() - DAY,
}
FAILED_FIELDS = {
    'status': 'expired', 'plan': 'free',
    'qualification_status': 'failed',
}


def banner_copy(done):
    """Exact banner sentence as it appears in the rendered HTML source.

    Django only escapes ``{{ var }}`` output, never literal template text,
    so the apostrophe in "You've" reaches the page verbatim.
    """
    return (
        'Free trial: publish 3 products within 14 days of your first product. '
        "You've published %d of 3." % done
    )


class FreeTrialVisibilityFixture(TestCase):
    """Vendor + store + subscription state + products, both target pages."""

    def setUp(self):
        self.category = MainCategory.objects.create(name='Vis', slug='vis-fv')
        self.subcategory = SubCategory.objects.create(
            main_category=self.category, name='VisSub', slug='vis-sub-fv',
        )

    def make_vendor(self, key, suspended=False):
        user = CustomUser.objects.create_user(
            email=f'{key}@example.com',
            password='password123',
            username=key.replace('-', '_'),
            role='vendor',
        )
        vendor = user.vendorprofile
        vendor.store_setup_completed = True
        vendor.save(update_fields=['store_setup_completed'])
        store = Store.objects.create(
            vendor=vendor,
            store_name=f'{key} store',
            slug=key,
            main_category=self.category,
            is_published=True,
        )
        if suspended:
            VendorProfile.objects.filter(pk=vendor.pk).update(
                verification_status='suspended',
            )
        # Re-fetch: the profile -> subscription cache may be stale.
        return VendorProfile.objects.get(pk=vendor.pk), store

    @staticmethod
    def set_sub(vendor, **fields):
        Subscription.objects.filter(vendor=vendor).update(**fields)
        return Subscription.objects.get(vendor=vendor)

    def make_products(self, vendor, store, published=0, drafts=0):
        for i in range(published):
            Product.objects.create(
                vendor=vendor,
                store=store,
                subcategory=self.subcategory,
                title=f'{vendor.pk} visibility published {i}',
                slug=f'fv-{vendor.pk}-pub-{i}',
                description='A product for the free-trial visibility tests',
                price='1750.00',
                status='published',
            )
        for i in range(drafts):
            Product.objects.create(
                vendor=vendor,
                store=store,
                subcategory=self.subcategory,
                title=f'{vendor.pk} visibility draft {i}',
                slug=f'fv-{vendor.pk}-draft-{i}',
                description='A draft for the free-trial visibility tests',
                price='1750.00',
                status='draft',
            )

    @staticmethod
    def content_of(response):
        return response.content.decode('utf-8')

    def plans_body(self, vendor):
        self.client.force_login(vendor.user)
        response = self.client.get(reverse('vendors:subscription_plans'))
        self.assertEqual(response.status_code, 200)
        return self.content_of(response)

    def create_body(self, vendor):
        self.client.force_login(vendor.user)
        response = self.client.get(reverse('vendors:product_create'))
        self.assertEqual(response.status_code, 200)
        return self.content_of(response)


class FreeCardOnPlansPageTests(FreeTrialVisibilityFixture):
    """Free card copy and CTA per subscription state (exact strings)."""

    def test_zero_products_shows_count_start_copy_and_activation_button(self):
        vendor, store = self.make_vendor('fv-card-zero')
        self.set_sub(vendor, **QUALIFYING_FIELDS)

        body = self.plans_body(vendor)

        self.assertIn('0 of 3 products published', body)
        self.assertIn(START_COPY, body)
        self.assertIn(ACTIVATE_CTA, body)
        self.assertIn(
            'href="%s"' % reverse('vendors:product_create'), body,
        )
        # not_started has no window yet - no countdown line
        self.assertNotIn('day(s) left in your window', body)
        self.assertNotIn('Add 2 more products', body)

    def test_one_published_product_shows_progress_add_more_and_days(self):
        vendor, store = self.make_vendor('fv-card-one')
        self.set_sub(vendor, **QUALIFYING_FIELDS)
        self.make_products(vendor, store, published=1)

        body = self.plans_body(vendor)

        self.assertIn('1 of 3 products published', body)
        self.assertIn('width: 33%', body)
        self.assertIn(
            'Add 2 more products to activate your 3-month free trial', body,
        )
        self.assertIn('7 day(s) left in your window', body)
        self.assertIn(ACTIVATE_CTA, body)

    def test_two_published_products_uses_singular_add_more(self):
        vendor, store = self.make_vendor('fv-card-two')
        self.set_sub(vendor, **QUALIFYING_FIELDS)
        self.make_products(vendor, store, published=2)

        body = self.plans_body(vendor)

        self.assertIn('2 of 3 products published', body)
        self.assertIn('width: 67%', body)
        self.assertIn(
            'Add 1 more product to activate your 3-month free trial', body,
        )
        self.assertIn('7 day(s) left in your window', body)
        self.assertIn(ACTIVATE_CTA, body)

    def test_drafts_do_not_count_toward_the_free_card(self):
        vendor, store = self.make_vendor('fv-card-drafts')
        self.set_sub(vendor, **QUALIFYING_FIELDS)
        self.make_products(vendor, store, published=1, drafts=2)

        body = self.plans_body(vendor)

        self.assertIn('1 of 3 products published', body)
        self.assertNotIn('3 of 3 products published', body)
        self.assertIn(
            'Add 2 more products to activate your 3-month free trial', body,
        )

    def test_draft_only_vendor_has_already_started_the_window(self):
        vendor, store = self.make_vendor('fv-card-draft-only')
        self.set_sub(vendor, **QUALIFYING_FIELDS)
        self.make_products(vendor, store, published=0, drafts=1)

        body = self.plans_body(vendor)

        self.assertIn('0 of 3 products published', body)
        # A first product of ANY status starts the window
        self.assertNotIn(START_COPY, body)
        self.assertIn('7 day(s) left in your window', body)
        self.assertIn(
            'Add 3 more products to activate your 3-month free trial', body,
        )

    def test_trial_state_shows_free_trial_active_until_without_activation(self):
        vendor, store = self.make_vendor('fv-card-trial')
        sub = self.set_sub(vendor, **TRIAL_FIELDS)

        body = self.plans_body(vendor)

        expected = 'Free trial active until %s' % sub.trial_ends_at.strftime(
            '%b %d, %Y',
        )
        self.assertIn(expected, body)
        self.assertNotIn(ACTIVATE_CTA, body)

    def test_failed_qualification_state_offers_no_activation_button(self):
        vendor, store = self.make_vendor('fv-card-failed')
        self.set_sub(vendor, **FAILED_FIELDS)

        body = self.plans_body(vendor)

        self.assertNotIn(ACTIVATE_CTA, body)
        self.assertNotIn(START_COPY, body)
        self.assertIn('Free Plan', body)

    def test_paid_active_state_offers_no_activation_button(self):
        vendor, store = self.make_vendor('fv-card-paid')
        self.set_sub(vendor, **PAID_FIELDS)

        body = self.plans_body(vendor)

        self.assertNotIn(ACTIVATE_CTA, body)
        self.assertNotIn('products published', body)


class ProductCreateBannerTests(FreeTrialVisibilityFixture):
    """Qualifying-only banner above the create form; no gate changes."""

    def test_qualifying_zero_products_shows_exact_banner_and_form(self):
        vendor, store = self.make_vendor('fv-banner-zero')
        self.set_sub(vendor, **QUALIFYING_FIELDS)

        body = self.create_body(vendor)

        self.assertIn(banner_copy(0), body)
        self.assertIn(FORM_MARKER, body)
        self.assertNotIn(PROMPT_HEADING, body)

    def test_banner_counts_only_published_products(self):
        vendor, store = self.make_vendor('fv-banner-published')
        self.set_sub(vendor, **QUALIFYING_FIELDS)
        self.make_products(vendor, store, published=2, drafts=1)

        body = self.create_body(vendor)

        self.assertIn(banner_copy(2), body)
        self.assertNotIn(banner_copy(3), body)

    def test_banner_hidden_for_trial_state(self):
        vendor, store = self.make_vendor('fv-banner-trial')
        self.set_sub(vendor, **TRIAL_FIELDS)

        body = self.create_body(vendor)

        self.assertNotIn(banner_copy(0), body)
        self.assertIn(FORM_MARKER, body)

    def test_banner_hidden_for_paid_state(self):
        vendor, store = self.make_vendor('fv-banner-paid')
        self.set_sub(vendor, **PAID_FIELDS)

        body = self.create_body(vendor)

        self.assertNotIn(banner_copy(0), body)
        self.assertIn(FORM_MARKER, body)

    def test_banner_hidden_for_restricted_trial_expired(self):
        vendor, store = self.make_vendor('fv-banner-expired')
        self.set_sub(vendor, **EXPIRED_TRIAL_FIELDS)

        body = self.create_body(vendor)

        self.assertNotIn(banner_copy(0), body)
        self.assertIn(PROMPT_HEADING, body)

    def test_banner_hidden_for_suspended_vendor_but_form_still_renders(self):
        vendor, store = self.make_vendor('fv-banner-susp', suspended=True)
        self.set_sub(vendor, **QUALIFYING_FIELDS)

        body = self.create_body(vendor)

        self.assertNotIn(banner_copy(0), body)
        self.assertIn(FORM_MARKER, body)
        self.assertNotIn(PROMPT_HEADING, body)

    def test_no_new_gate_for_qualifying_and_trial_vendors(self):
        fields = (
            ('fv-gate-qual', QUALIFYING_FIELDS, 1),
            ('fv-gate-trial', TRIAL_FIELDS, 0),
        )
        for key, sub_fields, published in fields:
            vendor, store = self.make_vendor(key)
            self.set_sub(vendor, **sub_fields)
            self.make_products(vendor, store, published=published)

            self.client.force_login(vendor.user)
            response = self.client.get(reverse('vendors:product_create'))

            self.assertEqual(response.status_code, 200, key)
            body = self.content_of(response)
            self.assertIn(FORM_MARKER, body, key)
            self.assertNotIn(PROMPT_HEADING, body, key)


class QueryBudgetTests(FreeTrialVisibilityFixture):
    """
    Query counts, measured with this fixture before the change:

        plans page      qualifying_0=11  qualifying_2=11  trial=10
                        paid=10          expired=10       (template-only
                        change -> unchanged after)
        product-create  qualifying_0=12  qualifying_2=12  trial=12
                        paid=12          expired=10       suspended+qual=12
                        (after: qualifying form path +1 for the banner's own
                        COUNT, every other state +0)
    """

    PLANS_ALLOWED = {
        'qualifying_0': 11,
        'qualifying_2': 11,
        'trial': 10,
        'paid': 10,
        'expired': 10,
    }
    CREATE_ALLOWED = {
        'qualifying_0': 13,
        'qualifying_2': 13,
        'trial': 12,
        'paid': 12,
        'expired': 10,
        'susp_qual': 12,
    }

    def setup_state(self, name):
        suspended = name == 'susp_qual'
        vendor, store = self.make_vendor('fv-q-%s' % name, suspended=suspended)
        fields = {
            'qualifying_0': QUALIFYING_FIELDS,
            'qualifying_2': QUALIFYING_FIELDS,
            'trial': TRIAL_FIELDS,
            'paid': PAID_FIELDS,
            'expired': EXPIRED_TRIAL_FIELDS,
            'susp_qual': QUALIFYING_FIELDS,
        }[name]
        self.set_sub(vendor, **fields)
        if name == 'qualifying_2':
            self.make_products(vendor, store, published=2, drafts=1)
        self.client.force_login(vendor.user)
        return vendor

    def measure(self, url_name):
        with CaptureQueriesContext(connection) as ctx:
            response = self.client.get(reverse(url_name))
        self.assertEqual(response.status_code, 200, url_name)
        return len(ctx.captured_queries)

    def test_plans_page_query_count_is_unchanged(self):
        for name, allowed in self.PLANS_ALLOWED.items():
            self.setup_state(name)
            used = self.measure('vendors:subscription_plans')
            print('FV_PLANS %-15s n=%d (pre-change %d)' % (name, used, allowed))
            self.assertLessEqual(
                used, allowed,
                '%s used %d queries, pre-change was %d' % (name, used, allowed),
            )

    def test_product_create_query_count_is_flat(self):
        for name, allowed in self.CREATE_ALLOWED.items():
            self.setup_state(name)
            used = self.measure('vendors:product_create')
            print('FV_CREATE %-15s n=%d (allowed %d)'
                  % (name, used, allowed))
            self.assertLessEqual(
                used, allowed,
                '%s used %d queries, allowed %d' % (name, used, allowed),
            )
