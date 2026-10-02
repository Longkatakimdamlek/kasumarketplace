"""
Phase 6 - Restricted-vendor UX
===============================

A vendor whose free trial or paid subscription lapsed (or whose free-plan
qualification failed) keeps its whole vendor area: dashboard, product list,
product detail, product edit and product delete all stay reachable.  The
only action still blocked is product CREATION, which renders the
subscription prompt (heading "Subscription needed to add products") instead
of redirecting to the verification center.

Also covered here:
  - the shared descriptor (apps.vendors.subscription_state) for all ten
    states: key, tone, verbatim copy, CTAs, plan/status labels, countdown
    and the qualification block
  - descriptor runs at most one published-product COUNT query (0 for the
    states that do not show a count) and never writes
  - dashboard / product list / verification center / chip rendering from
    the descriptor, plus the dashboard flash removal
  - dashboard query count stays bounded with the banner included
  - the admin restart action now qualifies a vendor who already has 3
    published products (Phase 6 Task 0)

Time simulation matches Phase 5: rows are backdated with QuerySet.update()
and the real timezone.now() is used everywhere.  No mocks: real rows, real
requests, real templates.
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
from apps.vendors.subscription_state import (
    RESTRICTED_MESSAGE,
    describe_subscription_state,
)

DAY = timedelta(days=1)

PROMPT_HEADING = 'Subscription needed to add products'
OLD_CREATE_GATE_MESSAGE = (
    'Please complete store setup and activate your subscription to access this feature.'
)
OLD_DASHBOARD_FLASH = 'Complete verification to start selling'
OLD_DASHBOARD_BANNER = 'Verify your store to unlock payouts'


def count_product_queries(sqls):
    """Only COUNT(*) queries against the product table (the count query)."""
    table = Product._meta.db_table
    return [
        sql for sql in sqls
        if 'COUNT(' in sql['sql'].upper() and table in sql['sql']
    ]


class RestrictedUxFixture(TestCase):
    """Vendor / store / product factory shared by the Phase 6 tests."""

    def setUp(self):
        self.category = MainCategory.objects.create(name='Bags', slug='bags-p6')
        self.subcategory = SubCategory.objects.create(
            main_category=self.category, name='Totes', slug='totes-p6',
        )

    def make_vendor(self, key, sub_fields=None, delete_subscription=False,
                    store_setup=True):
        user = CustomUser.objects.create_user(
            email=f'{key}@example.com',
            password='password123',
            username=key.replace('-', '_'),
            role='vendor',
        )
        vendor = user.vendorprofile
        vendor.store_setup_completed = store_setup
        vendor.save(update_fields=['store_setup_completed'])
        store = Store.objects.create(
            vendor=vendor,
            store_name=f'{key} store',
            slug=key,
            main_category=self.category,
            is_published=True,
        )
        subscription = Subscription.objects.get(vendor=vendor)
        if delete_subscription:
            subscription.delete()
        elif sub_fields:
            Subscription.objects.filter(pk=subscription.pk).update(**sub_fields)

        # Re-fetch: the profile -> subscription cache may be stale.
        return VendorProfile.objects.get(pk=vendor.pk), store

    def make_product(self, vendor, store, n, status='draft'):
        return Product.objects.create(
            vendor=vendor,
            store=store,
            subcategory=self.subcategory,
            title=f'{vendor.pk} phase6 product {n}',
            slug=f'p6-{vendor.pk}-{n}',
            description='A product used by the Phase 6 restricted UX tests',
            price='1750.00',
            status=status,
        )

    @staticmethod
    def set_sub(vendor, **fields):
        Subscription.objects.filter(vendor=vendor).update(**fields)
        return Subscription.objects.get(vendor=vendor)

    @staticmethod
    def state_of(vendor):
        """Descriptor run against a freshly fetched profile (no stale cache)."""
        return describe_subscription_state(VendorProfile.objects.get(pk=vendor.pk))

    @staticmethod
    def content_of(response):
        return response.content.decode('utf-8')

    @staticmethod
    def restricted(key, **extra):
        """Subscription fields for a restricted (unavailable) vendor."""
        fields = {
            'status': 'trial',
            'trial_ends_at': timezone.now() - DAY,
        }
        fields.update(extra)
        return fields

    @staticmethod
    def available_paid(key='paid', **extra):
        fields = {
            'status': 'active',
            'plan': 'basic',
            'period_end': timezone.now() + timedelta(days=20),
        }
        fields.update(extra)
        return fields


# =========================================================================
# Task 2 - the descriptor: all ten states
# =========================================================================

class DescriptorStateTests(RestrictedUxFixture):

    def test_state_1_qualifying_not_started(self):
        vendor, store = self.make_vendor('p6-state1')
        state = self.state_of(vendor)

        self.assertEqual(state.key, 'qualifying_not_started')
        self.assertEqual(state.tone, 'info')
        self.assertEqual(state.title, 'Start your free trial')
        self.assertIn(
            'Create your first product to begin your 7-day qualification.',
            state.message,
        )
        self.assertIn('Publish 3 products within 7 days', state.message)
        self.assertEqual(state.primary_cta_label, 'Add your first product')
        self.assertEqual(state.primary_cta_url_name, 'vendors:product_create')
        self.assertIsNone(state.secondary_cta_label)
        self.assertFalse(state.is_restricted)
        self.assertEqual(state.plan_name, 'Free Plan')
        self.assertEqual(state.status_label, 'Qualifying')
        self.assertIsNone(state.days_left)
        self.assertIsNone(state.end_date)
        self.assertEqual(state.qualification['required'], 3)
        self.assertEqual(state.qualification['products_done'], 0)
        self.assertEqual(state.qualification['products_needed'], 3)
        self.assertEqual(state.qualification['window'], 'in_progress')

    def test_state_2_qualifying_in_progress(self):
        vendor, store = self.make_vendor('p6-state2')
        self.make_product(vendor, store, 1, status='published')

        state = self.state_of(vendor)
        self.assertEqual(state.key, 'qualifying_in_progress')
        self.assertEqual(state.tone, 'info')
        self.assertEqual(
            state.title, 'Free trial qualification: 1 of 3 published products'
        )
        self.assertEqual(
            state.message,
            'Publish 2 more product(s) within 7 day(s) to unlock your 3-month '
            'free trial. Drafts do not count.',
        )
        self.assertEqual(state.primary_cta_label, 'Add product')
        self.assertEqual(state.primary_cta_url_name, 'vendors:product_create')
        self.assertIsNone(state.secondary_cta_label)
        self.assertFalse(state.is_restricted)
        self.assertEqual(state.qualification['products_done'], 1)
        self.assertEqual(state.qualification['products_needed'], 2)
        self.assertEqual(state.qualification['days_left'], 7)
        self.assertEqual(state.qualification['window'], 'in_progress')
        self.assertEqual(state.days_left, 7)
        self.assertEqual(state.end_date, timezone.localdate() + timedelta(days=7))

    def test_state_3_qualifying_grace(self):
        vendor, store = self.make_vendor('p6-state3')
        self.make_product(vendor, store, 1, status='published')
        self.set_sub(vendor, first_product_at=timezone.now() - timedelta(days=8))

        state = self.state_of(vendor)
        self.assertEqual(state.key, 'qualifying_grace')
        self.assertEqual(state.tone, 'warning')
        self.assertEqual(state.title, 'Grace period: 1 of 3 published products')
        self.assertEqual(
            state.message,
            'Your first 7 days are over. You have 6 more day(s) to publish 2 '
            'more product(s). After that, buyers will see Vendor Unavailable '
            'and you will not be able to add products until you subscribe.',
        )
        self.assertEqual(state.primary_cta_label, 'Add product')
        self.assertEqual(state.primary_cta_url_name, 'vendors:product_create')
        self.assertEqual(state.secondary_cta_label, 'View plans')
        self.assertEqual(state.secondary_cta_url_name, 'vendors:subscription_plans')
        self.assertFalse(state.is_restricted, 'inside the 14-day window')
        self.assertEqual(state.qualification['window'], 'grace')
        self.assertEqual(state.qualification['days_left'], 6)
        self.assertEqual(state.days_left, 6)

    def test_state_4_trial_active_success(self):
        vendor, store = self.make_vendor(
            'p6-state4',
            sub_fields={
                'status': 'trial',
                'trial_ends_at': timezone.now() + timedelta(days=30),
            },
        )
        state = self.state_of(vendor)

        self.assertEqual(state.key, 'trial_active')
        self.assertEqual(state.tone, 'success')
        self.assertEqual(state.title, 'Free trial active')
        self.assertEqual(state.days_left, 30)
        self.assertIsNotNone(state.end_date)
        self.assertRegex(
            state.message, r'^30 day\(s\) left \(ends [A-Z][a-z]{2} \d{2}, \d{4}\)\.$'
        )
        self.assertEqual(state.primary_cta_label, 'View plans')
        self.assertEqual(state.primary_cta_url_name, 'vendors:subscription_plans')
        self.assertFalse(state.is_restricted)
        self.assertIsNone(state.qualification)

    def test_state_4_trial_active_warning_under_seven_days(self):
        vendor, store = self.make_vendor(
            'p6-state4b',
            sub_fields={
                'status': 'trial',
                'trial_ends_at': timezone.now() + timedelta(days=5),
            },
        )
        state = self.state_of(vendor)

        self.assertEqual(state.key, 'trial_active')
        self.assertEqual(state.tone, 'warning')
        self.assertEqual(state.days_left, 5)
        self.assertTrue(state.message.endswith(
            ' Choose a plan to keep your store available to buyers.'
        ))

    def test_state_5_paid_active(self):
        vendor, store = self.make_vendor(
            'p6-state5', sub_fields=self.available_paid()
        )
        state = self.state_of(vendor)

        self.assertEqual(state.key, 'paid_active')
        self.assertEqual(state.tone, 'success')
        self.assertEqual(state.title, 'Basic Plan active')
        self.assertRegex(state.message, r'^Renews on [A-Z][a-z]{2} \d{2}, \d{4}\.$')
        self.assertEqual(state.primary_cta_label, 'Manage subscription')
        self.assertEqual(state.primary_cta_url_name, 'vendors:subscription_plans')
        self.assertFalse(state.is_restricted)
        self.assertEqual(state.plan_name, 'Basic Plan')
        self.assertEqual(state.status_label, 'Active')
        self.assertEqual(state.days_left, 20)

    def test_state_5_cancel_at_period_end_is_a_warning(self):
        vendor, store = self.make_vendor(
            'p6-state5b',
            sub_fields=self.available_paid(cancel_at_period_end=True),
        )
        state = self.state_of(vendor)

        self.assertEqual(state.key, 'paid_active')
        self.assertEqual(state.tone, 'warning')
        self.assertRegex(
            state.message,
            r'^Your plan ends on [A-Z][a-z]{2} \d{2}, \d{4}\. '
            r'No automatic charge will occur\.$',
        )

    def test_state_6_payment_grace(self):
        vendor, store = self.make_vendor(
            'p6-state6',
            sub_fields={
                'status': 'past_due',
                'plan': 'premium',
                'grace_ends_at': timezone.now() + timedelta(days=3),
            },
        )
        state = self.state_of(vendor)

        self.assertEqual(state.key, 'payment_grace')
        self.assertEqual(state.tone, 'warning')
        self.assertEqual(state.title, 'Payment problem')
        self.assertRegex(
            state.message,
            r'^Your store stays available until [A-Z][a-z]{2} \d{2}, \d{4}\. '
            r'Subscribe again to keep contact buttons and product creation\.$',
        )
        self.assertEqual(state.primary_cta_label, 'Subscribe')
        self.assertEqual(state.primary_cta_url_name, 'vendors:subscription_plans')
        self.assertFalse(state.is_restricted, 'grace keeps the store up')
        self.assertEqual(state.plan_name, 'Premium Plan')
        self.assertEqual(state.days_left, 3)

    def test_state_7_restricted_qualification_failed(self):
        vendor, store = self.make_vendor(
            'p6-state7',
            sub_fields={
                'status': 'expired',
                'qualification_status': 'failed',
                'first_product_at': timezone.now() - timedelta(days=15),
            },
        )
        self.make_product(vendor, store, 1, status='published')

        state = self.state_of(vendor)
        self.assertEqual(state.key, 'restricted_qualification_failed')
        self.assertEqual(state.tone, 'danger')
        self.assertTrue(state.is_restricted)
        self.assertEqual(state.title, 'Free trial not unlocked')
        self.assertTrue(state.message.startswith(
            'You did not publish 3 products within 14 days of your first product. '
        ))
        self.assertIn(RESTRICTED_MESSAGE, state.message)
        self.assertEqual(state.primary_cta_label, 'Subscribe')
        self.assertEqual(state.primary_cta_url_name, 'vendors:subscription_plans')
        self.assertEqual(state.days_left, 0)
        self.assertEqual(state.qualification['window'], 'failed')
        self.assertEqual(state.qualification['products_done'], 1)

    def test_state_8_restricted_trial_expired(self):
        vendor, store = self.make_vendor('p6-state8', sub_fields=self.restricted('8'))
        state = self.state_of(vendor)

        self.assertEqual(state.key, 'restricted_trial_expired')
        self.assertEqual(state.tone, 'danger')
        self.assertTrue(state.is_restricted)
        self.assertEqual(state.title, 'Free trial ended')
        self.assertEqual(state.message, RESTRICTED_MESSAGE)
        self.assertEqual(state.primary_cta_label, 'Subscribe')
        self.assertEqual(state.days_left, 0)
        self.assertIsNone(state.qualification)

    def test_state_9_restricted_subscription_expired(self):
        vendor, store = self.make_vendor(
            'p6-state9a',
            sub_fields={
                'status': 'active',
                'plan': 'premium',
                'period_end': timezone.now() - DAY,
            },
        )
        state = self.state_of(vendor)
        self.assertEqual(state.key, 'restricted_subscription_expired')
        self.assertEqual(state.tone, 'danger')
        self.assertTrue(state.is_restricted)
        self.assertEqual(state.title, 'Subscription expired')
        self.assertEqual(state.message, RESTRICTED_MESSAGE)
        self.assertEqual(state.plan_name, 'Premium Plan')
        self.assertIsNone(state.qualification)

        # expired status without a trial history lands on the same state
        vendor_b, store_b = self.make_vendor('p6-state9b', sub_fields={
            'status': 'expired',
            'qualification_status': 'skipped',
        })
        state_b = self.state_of(vendor_b)
        self.assertEqual(state_b.key, 'restricted_subscription_expired')
        self.assertTrue(state_b.is_restricted)

    def test_state_10_no_subscription(self):
        vendor, store = self.make_vendor('p6-state10', delete_subscription=True)
        state = self.state_of(vendor)

        self.assertEqual(state.key, 'no_subscription')
        self.assertEqual(state.tone, 'neutral')
        self.assertEqual(state.title, 'No subscription found')
        self.assertEqual(state.message, 'Open the plans page to choose a plan.')
        self.assertEqual(state.primary_cta_label, 'View plans')
        self.assertEqual(state.primary_cta_url_name, 'vendors:subscription_plans')
        self.assertTrue(state.is_restricted)
        self.assertEqual(state.plan_name, 'No plan')
        self.assertEqual(state.status_label, 'None')
        self.assertIsNone(state.days_left)
        self.assertIsNone(state.end_date)


class DescriptorQueryAndPurityTests(RestrictedUxFixture):

    def descriptor_queries(self, vendor):
        vendor = VendorProfile.objects.get(pk=vendor.pk)
        with CaptureQueriesContext(connection) as ctx:
            state = describe_subscription_state(vendor)
        return state, ctx.captured_queries

    def test_at_most_one_published_product_count_query(self):
        """The descriptor counts published products at most once, never N+1."""
        cases = {}

        vendor, store = self.make_vendor('p6-q1')
        cases['qualifying_not_started'] = vendor

        vendor, store = self.make_vendor('p6-q2')
        self.make_product(vendor, store, 1, status='published')
        cases['qualifying_in_progress'] = vendor

        vendor, store = self.make_vendor('p6-q3', sub_fields=self.available_paid())
        cases['paid_active'] = vendor

        vendor, store = self.make_vendor('p6-q4', sub_fields=self.restricted('q4'))
        cases['restricted_trial_expired'] = vendor

        for key, vendor in cases.items():
            state, sqls = self.descriptor_queries(vendor)
            expected = 1 if key.startswith('qualifying_') else 0
            self.assertEqual(
                len(count_product_queries(sqls)), expected,
                f'{key}: {[q["sql"] for q in sqls]}',
            )
            self.assertTrue(state.key)

    def test_descriptor_never_writes(self):
        """A stale stored label stays stale: the descriptor only reads."""
        vendor, store = self.make_vendor('p6-pure')
        self.make_product(vendor, store, 1, status='published')
        self.set_sub(vendor, first_product_at=timezone.now() - timedelta(days=8))

        before = Subscription.objects.get(vendor=vendor)
        self.assertEqual(before.qualification_status, 'in_progress')

        state = self.state_of(vendor)
        self.assertEqual(state.key, 'qualifying_grace')

        after = Subscription.objects.get(vendor=vendor)
        self.assertEqual(after.qualification_status, 'in_progress')
        self.assertEqual(after.status, 'qualifying')
        self.assertEqual(after.first_product_at, before.first_product_at)

    def test_state_5_runs_no_count_query_at_all(self):
        vendor, store = self.make_vendor(
            'p6-q5', sub_fields=self.available_paid()
        )
        state, sqls = self.descriptor_queries(vendor)
        self.assertEqual(state.key, 'paid_active')
        self.assertEqual(count_product_queries(sqls), [])


# =========================================================================
# Task 3 - the gate: everything open except product creation
# =========================================================================

class RestrictedVendorAccessTests(RestrictedUxFixture):

    def login(self, vendor):
        self.client.force_login(vendor.user)

    def test_all_manage_pages_stay_open_for_a_restricted_vendor(self):
        vendor, store = self.make_vendor('p6-open', sub_fields=self.restricted('open'))
        product = self.make_product(vendor, store, 1, status='published')
        self.login(vendor)

        for name, kwargs in (
            ('products_list', {}),
            ('product_detail', {'slug': product.slug}),
            ('product_edit', {'slug': product.slug}),
            ('product_delete', {'slug': product.slug}),
            ('dashboard', {}),
            ('subscription_plans', {}),
            ('verification_center', {}),
        ):
            response = self.client.get(reverse(f'vendors:{name}', kwargs=kwargs))
            self.assertEqual(
                response.status_code, 200, f'{name} is no longer reachable'
            )

    def test_restricted_vendor_can_delete_its_own_product(self):
        vendor, store = self.make_vendor('p6-del', sub_fields=self.restricted('del'))
        product = self.make_product(vendor, store, 1, status='published')
        self.login(vendor)

        confirm = self.client.get(
            reverse('vendors:product_delete', kwargs={'slug': product.slug})
        )
        self.assertEqual(confirm.status_code, 200)

        response = self.client.post(
            reverse('vendors:product_delete', kwargs={'slug': product.slug})
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse('vendors:products_list'))
        self.assertFalse(Product.objects.filter(pk=product.pk).exists())

    def test_product_create_get_renders_the_subscription_prompt(self):
        vendor, store = self.make_vendor('p6-prompt', sub_fields=self.restricted('prompt'))
        self.login(vendor)

        response = self.client.get(reverse('vendors:product_create'))
        body = self.content_of(response)

        self.assertEqual(response.status_code, 200)
        self.assertIn(PROMPT_HEADING, body)
        self.assertIn(reverse('vendors:subscription_plans'), body)
        self.assertIn(reverse('vendors:products_list'), body)
        self.assertIn('Cancel', body)
        self.assertNotIn(OLD_CREATE_GATE_MESSAGE, body)
        self.assertNotIn('id_subcategory', body, 'the product form must not render')

    def test_product_create_post_creates_nothing(self):
        """
        Same payload for both vendors: an available vendor reaches form
        processing (the image formset rejects it), a restricted vendor never
        does - it gets the prompt and no Product row at all.

        The image formset requires at least 3 images, so neither payload can
        actually save; what differs is WHERE the request stops.
        """
        payload = {
            'title': 'Phase 6 gated product',
            'subcategory': str(self.subcategory.pk),
            'description': 'Created by the Phase 6 restricted UX tests',
            'price': '1500.00',
            'stock_quantity': '10',
            'low_stock_threshold': '5',
            'status': 'draft',
            'sku': 'P6-GATED',
            'images-TOTAL_FORMS': '0',
            'images-INITIAL_FORMS': '0',
            'images-MIN_NUM_FORMS': '0',
            'images-MAX_NUM_FORMS': '4',
        }

        # A: an available (trial) vendor - the form runs and rejects the post
        ok_vendor, ok_store = self.make_vendor('p6-post-ok', sub_fields={
            'status': 'trial',
            'trial_ends_at': timezone.now() + timedelta(days=10),
        })
        self.client.force_login(ok_vendor.user)
        before_ok = Product.objects.filter(vendor=ok_vendor).count()
        ok_response = self.client.post(reverse('vendors:product_create'), payload)
        ok_body = self.content_of(ok_response)

        self.assertEqual(ok_response.status_code, 200)
        self.assertNotIn(PROMPT_HEADING, ok_body)
        self.assertIn('id_subcategory', ok_body, 'the product form must render')
        self.assertIn('Please upload at least 3 images', ok_body)
        self.assertEqual(
            Product.objects.filter(vendor=ok_vendor).count(), before_ok
        )

        # B: the restricted vendor posts the identical payload
        restricted_vendor, restricted_store = self.make_vendor(
            'p6-post-blocked', sub_fields=self.restricted('blocked')
        )
        self.client.force_login(restricted_vendor.user)
        sub_before = Subscription.objects.get(vendor=restricted_vendor)
        before_blocked = Product.objects.filter(vendor=restricted_vendor).count()

        blocked = dict(payload)
        blocked['title'] = 'Phase 6 blocked vendor product'
        blocked['sku'] = 'P6-BLOCKED'
        response = self.client.post(reverse('vendors:product_create'), blocked)
        blocked_body = self.content_of(response)

        self.assertEqual(response.status_code, 200)
        self.assertIn(PROMPT_HEADING, blocked_body)
        self.assertNotIn('id_subcategory', blocked_body)
        self.assertNotIn(
            'Please upload at least 3 images', blocked_body,
            'the form must not run for a restricted vendor',
        )
        self.assertEqual(
            Product.objects.filter(vendor=restricted_vendor).count(), before_blocked
        )

        sub_after = Subscription.objects.get(vendor=restricted_vendor)
        self.assertEqual(sub_after.status, sub_before.status)
        self.assertEqual(sub_after.qualification_status, sub_before.qualification_status)
        self.assertEqual(sub_after.first_product_at, sub_before.first_product_at)

    def test_store_setup_is_still_required_first(self):
        vendor, store = self.make_vendor(
            'p6-no-store-setup',
            sub_fields=self.restricted('no-setup'),
            store_setup=False,
        )
        self.login(vendor)

        for name in ('products_list', 'product_create', 'product_edit'):
            kwargs = {'slug': 'whatever'} if name == 'product_edit' else {}
            response = self.client.get(reverse(f'vendors:{name}', kwargs=kwargs))
            self.assertEqual(response.status_code, 302, name)
            self.assertEqual(response.url, reverse('vendors:store_setup'))

    def test_non_vendor_and_anonymous_visitors_are_refused(self):
        vendor, store = self.make_vendor('p6-gate', sub_fields=self.restricted('gate'))

        customer = CustomUser.objects.create_user(
            email='p6-customer@example.com',
            password='password123',
            username='p6_customer',
            role='customer',
        )
        self.assertFalse(hasattr(customer, 'vendorprofile'))
        self.client.force_login(customer)
        response = self.client.get(reverse('vendors:products_list'))
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, '/')

        self.client.logout()
        response = self.client.get(reverse('vendors:products_list'))
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse('users:login'), response.url)

    def test_available_vendors_still_get_the_real_product_form(self):
        vendor, store = self.make_vendor('p6-form-open')  # qualifying, available
        self.login(vendor)

        response = self.client.get(reverse('vendors:product_create'))
        body = self.content_of(response)
        self.assertEqual(response.status_code, 200)
        self.assertNotIn(PROMPT_HEADING, body)
        self.assertIn('id_subcategory', body)

    def test_vendor_inside_the_payment_grace_window_can_still_create(self):
        vendor, store = self.make_vendor('p6-grace-create', sub_fields={
            'status': 'past_due',
            'grace_ends_at': timezone.now() + timedelta(days=2),
        })
        self.login(vendor)

        response = self.client.get(reverse('vendors:product_create'))
        self.assertEqual(response.status_code, 200)
        self.assertNotIn(PROMPT_HEADING, self.content_of(response))


# =========================================================================
# Task 5 - templates: banner, chips, verification note, prompt
# =========================================================================

class BannerRenderingTests(RestrictedUxFixture):

    def login(self, vendor):
        self.client.force_login(vendor.user)

    def test_dashboard_shows_the_state_and_drops_the_old_verification_pushes(self):
        vendor, store = self.make_vendor('p6-dash-restricted', sub_fields=self.restricted('dash'))
        self.login(vendor)

        response = self.client.get(reverse('vendors:dashboard'))
        body = self.content_of(response)

        self.assertEqual(response.status_code, 200)
        self.assertIn('Free trial ended', body)
        self.assertIn('Plan: Free Plan', body)
        self.assertIn('Status: Trial', body)
        self.assertIn(reverse('vendors:subscription_plans'), body)

        self.assertNotIn(OLD_DASHBOARD_FLASH, body)
        self.assertNotIn(OLD_DASHBOARD_BANNER, body)
        self.assertNotIn('Complete Verification', body)

    def test_dashboard_shows_the_plan_row_for_a_paid_vendor(self):
        vendor, store = self.make_vendor(
            'p6-dash-paid', sub_fields=self.available_paid()
        )
        self.login(vendor)

        response = self.client.get(reverse('vendors:dashboard'))
        body = self.content_of(response)

        self.assertEqual(response.status_code, 200)
        self.assertIn('Basic Plan active', body)
        self.assertIn('Renews on', body)
        self.assertIn('Plan', body)
        self.assertIn('Basic Plan (Active)', body)

    def test_dashboard_shows_the_qualification_countdown(self):
        vendor, store = self.make_vendor('p6-dash-qualifying')
        self.make_product(vendor, store, 1, status='published')
        self.login(VendorProfile.objects.get(pk=vendor.pk))

        response = self.client.get(reverse('vendors:dashboard'))
        body = self.content_of(response)

        self.assertEqual(response.status_code, 200)
        self.assertIn('Free trial qualification: 1 of 3 published products', body)
        self.assertIn('1 of 3 published products', body)
        self.assertIn('Add product', body)
        self.assertIn('day(s) left', body)

    def test_products_list_banner_is_conditional(self):
        restricted, store = self.make_vendor('p6-list-restricted', sub_fields=self.restricted('list'))
        self.login(restricted)
        body = self.content_of(self.client.get(reverse('vendors:products_list')))
        self.assertIn('Free trial ended', body)

        self.client.logout()
        paid, store = self.make_vendor('p6-list-paid', sub_fields=self.available_paid())
        self.login(paid)
        body = self.content_of(self.client.get(reverse('vendors:products_list')))
        self.assertNotIn('Free trial ended', body)
        self.assertNotIn('Subscription expired', body)

    def test_prompt_page_links_subscribe_and_cancel(self):
        vendor, store = self.make_vendor('p6-prompt-links', sub_fields=self.restricted('links'))
        self.login(vendor)

        body = self.content_of(self.client.get(reverse('vendors:product_create')))
        self.assertIn(PROMPT_HEADING, body)
        self.assertIn(f'href="{reverse("vendors:subscription_plans")}"', body)
        self.assertIn(f'href="{reverse("vendors:products_list")}"', body)
        self.assertIn('Current plan: Free Plan (Trial)', body)

    def test_chip_reads_restricted_from_the_descriptor(self):
        vendor, store = self.make_vendor('p6-chip', sub_fields=self.restricted('chip'))
        self.login(vendor)

        response = self.client.get(reverse('vendors:subscription_plans'))
        body = self.content_of(response)

        self.assertEqual(response.status_code, 200)
        self.assertIn('Restricted', body)
        self.assertNotIn('Complete Verification', body)

    def test_chip_keeps_the_old_text_when_the_vendor_is_not_restricted(self):
        vendor, store = self.make_vendor(
            'p6-chip-pending', sub_fields=self.available_paid(), store_setup=False
        )
        self.login(vendor)

        body = self.content_of(self.client.get(reverse('vendors:subscription_plans')))
        self.assertIn('Complete Verification', body)
        self.assertNotIn('Restricted', body)

    def test_verification_center_explains_the_subscription_block(self):
        vendor, store = self.make_vendor('p6-center', sub_fields=self.restricted('center'))
        self.login(vendor)

        response = self.client.get(reverse('vendors:verification_center'))
        body = self.content_of(response)

        self.assertEqual(response.status_code, 200)
        self.assertIn('Your selling access depends on your subscription.', body)
        self.assertIn('See plans', body)
        self.assertIn(reverse('vendors:subscription_plans'), body)
        self.assertIn('Free trial ended', body)
        self.assertNotIn(OLD_CREATE_GATE_MESSAGE, body)

    def test_verification_center_has_no_note_for_an_available_vendor(self):
        vendor, store = self.make_vendor('p6-center-ok', sub_fields=self.available_paid())
        self.login(vendor)

        body = self.content_of(self.client.get(reverse('vendors:verification_center')))
        self.assertNotIn('Your selling access depends on your subscription.', body)


class DashboardQueryBudgetTests(RestrictedUxFixture):

    # Measured: 14 queries with the banner rendered (see print below).
    DASHBOARD_QUERY_BOUND = 20

    def dashboard_queries(self, vendor):
        self.client.force_login(vendor.user)
        with CaptureQueriesContext(connection) as ctx:
            response = self.client.get(reverse('vendors:dashboard'))
        self.assertEqual(response.status_code, 200)
        return len(ctx.captured_queries)

    def test_banner_does_not_grow_the_dashboard_query_count(self):
        restricted, store = self.make_vendor(
            'p6-q-restricted', sub_fields=self.restricted('q-restricted')
        )
        active, store = self.make_vendor(
            'p6-q-active', sub_fields=self.available_paid('q-active')
        )

        restricted_count = self.dashboard_queries(restricted)
        active_count = self.dashboard_queries(active)

        print(
            'dashboard query count: restricted=%s active=%s bound=%s'
            % (restricted_count, active_count, self.DASHBOARD_QUERY_BOUND)
        )

        self.assertLessEqual(
            restricted_count, self.DASHBOARD_QUERY_BOUND,
            f'restricted dashboard uses {restricted_count} queries',
        )
        self.assertLessEqual(
            abs(restricted_count - active_count), 1,
            f'restricted={restricted_count} active={active_count}',
        )


# =========================================================================
# Task 0 - admin restart qualifies on the spot
# =========================================================================

class AdminRestartQualificationTests(RestrictedUxFixture):

    def setUp(self):
        super().setUp()
        self.User = get_user_model()
        self.superuser = self.User.objects.create_superuser(
            email='p6admin@example.com', password='password123',
        )

    def test_restart_qualifies_a_vendor_that_already_has_three_products(self):
        vendor, store = self.make_vendor('p6-restart')
        for n in (1, 2, 3):
            self.make_product(vendor, store, n, status='published')

        # third product qualified the vendor; force it back to failed
        Subscription.objects.filter(vendor=vendor).update(
            status='expired',
            qualification_status='failed',
            first_product_at=timezone.now() - timedelta(days=20),
            trial_ends_at=None,
            qualified_at=None,
        )
        sub = Subscription.objects.get(vendor=vendor)
        self.assertEqual(sub.status, 'expired')

        self.client.force_login(self.superuser)
        response = self.client.post(
            reverse('admin:vendors_subscription_changelist'),
            {
                'action': 'restart_qualification_window',
                '_selected_action': [str(sub.pk)],
            },
            follow=True,
        )
        self.assertEqual(response.status_code, 200)

        texts = [str(m) for m in response.context['messages']]
        self.assertTrue(
            any(
                'Restarted 1 qualification window(s); skipped 0' in text
                for text in texts
            ),
            texts,
        )
        self.assertTrue(any('qualified immediately' in text for text in texts), texts)

        sub.refresh_from_db()
        self.assertEqual(sub.status, 'trial')
        self.assertEqual(sub.qualification_status, 'qualified')
        self.assertIsNotNone(sub.qualified_at)
        self.assertIsNotNone(sub.trial_ends_at)
        self.assertTrue(VendorProfile.objects.get(pk=vendor.pk).is_available)
        self.assertGreater(
            sub.trial_ends_at, timezone.now() + timedelta(days=89)
        )

    def test_restart_still_leaves_vendors_without_three_products_qualifying(self):
        vendor, store = self.make_vendor('p6-restart-partial')
        self.make_product(vendor, store, 1, status='published')
        Subscription.objects.filter(vendor=vendor).update(
            status='expired',
            qualification_status='failed',
            first_product_at=timezone.now() - timedelta(days=20),
        )
        sub = Subscription.objects.get(vendor=vendor)

        self.client.force_login(self.superuser)
        response = self.client.post(
            reverse('admin:vendors_subscription_changelist'),
            {
                'action': 'restart_qualification_window',
                '_selected_action': [str(sub.pk)],
            },
            follow=True,
        )
        self.assertEqual(response.status_code, 200)

        texts = [str(m) for m in response.context['messages']]
        self.assertTrue(
            any(
                'Restarted 1 qualification window(s); skipped 0' in text
                for text in texts
            ),
            texts,
        )
        self.assertFalse(any('qualified immediately' in text for text in texts), texts)

        sub.refresh_from_db()
        self.assertEqual(sub.status, 'qualifying')
        self.assertEqual(sub.qualification_status, 'in_progress')
