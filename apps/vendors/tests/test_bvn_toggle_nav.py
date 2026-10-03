"""
Phase 9 Task 7 - no BVN dead ends in vendor navigation
======================================================

With PlatformSettings.bvn_verification_enabled OFF (the shipping default)
the BVN flow refuses before any Dojah call, so the navbar chip "Complete
Verification" and the sidebar chip "Pending" promise something the vendor
cannot finish: they link to the verification center where step 1 is
unavailable.

Rules under test here:
  - toggle OFF + BVN not completed -> the non-restricted chips do not render
    (the Restricted chip is untouched and still renders)
  - toggle ON                       -> both chips render exactly as before
  - a vendor that already completed BVN (bank_status == 'verified') keeps
    its chip either way - step 2 (store setup) is still a live target
  - the dashboard never pushes verification in either state
  - the toggle is read AT MOST ONCE per request (no per-chip query loop)

The toggle itself lives in the vendor context processor, memoised on the
request object (apps/vendors/context_processors.py).
"""

from datetime import timedelta

from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from apps.users.models import CustomUser
from apps.vendors.models import (
    MainCategory, PlatformSettings, Store, SubCategory, Subscription,
    VendorProfile,
)

DAY = timedelta(days=1)

NAVBAR_CHIP = 'Complete Verification'
SIDEBAR_CHIP = 'Pending'
RESTRICTED_CHIP = 'Restricted'


class BvnToggleNavTests(TestCase):

    def setUp(self):
        self.category = MainCategory.objects.create(name='Bags', slug='bags-p9b')
        self.subcategory = SubCategory.objects.create(
            main_category=self.category, name='Totes', slug='totes-p9b',
        )

    @staticmethod
    def set_bvn_toggle(on):
        PlatformSettings.get_solo()
        PlatformSettings.objects.filter(
            pk=PlatformSettings.SINGLETON_PK
        ).update(bvn_verification_enabled=on)

    def make_vendor(self, key, store_setup=False, restricted=False,
                    bank_status='not_started'):
        user = CustomUser.objects.create_user(
            email=f'{key}@example.com',
            password='password123',
            username=key.replace('-', '_'),
            role='vendor',
        )
        vendor = user.vendorprofile
        vendor.store_setup_completed = store_setup
        vendor.bank_status = bank_status
        vendor.save(update_fields=['store_setup_completed', 'bank_status'])
        Store.objects.create(
            vendor=vendor,
            store_name=f'{key} store',
            slug=key,
            main_category=self.category,
            is_published=True,
        )
        if restricted:
            Subscription.objects.filter(vendor=vendor).update(
                status='trial',
                trial_ends_at=timezone.now() - DAY,
            )
        else:
            Subscription.objects.filter(vendor=vendor).update(
                status='active',
                plan='basic',
                period_end=timezone.now() + timedelta(days=20),
            )
        return VendorProfile.objects.get(pk=vendor.pk)

    @staticmethod
    def body(response):
        return response.content.decode('utf-8')

    def get_chips_page(self, vendor):
        self.client.force_login(vendor.user)
        response = self.client.get(reverse('vendors:subscription_plans'))
        self.assertEqual(response.status_code, 200)
        return self.body(response)

    # ------------------------------------------------------------------
    # toggle OFF (default) - no dead-end prompts
    # ------------------------------------------------------------------
    def test_toggle_off_hides_navbar_and_sidebar_chips(self):
        self.set_bvn_toggle(False)
        vendor = self.make_vendor('p9b-off', store_setup=False)

        body = self.get_chips_page(vendor)

        self.assertNotIn(NAVBAR_CHIP, body)
        self.assertNotIn(SIDEBAR_CHIP, body)

    def test_toggle_on_shows_navbar_and_sidebar_chips(self):
        self.set_bvn_toggle(True)
        vendor = self.make_vendor('p9b-on', store_setup=False)

        body = self.get_chips_page(vendor)

        self.assertIn(NAVBAR_CHIP, body)
        self.assertIn(SIDEBAR_CHIP, body)
        self.assertNotIn(RESTRICTED_CHIP, body)

    def test_toggle_off_keeps_the_restricted_chip(self):
        self.set_bvn_toggle(False)
        vendor = self.make_vendor('p9b-off-restr', store_setup=False, restricted=True)

        body = self.get_chips_page(vendor)

        self.assertIn(RESTRICTED_CHIP, body)
        self.assertNotIn(NAVBAR_CHIP, body)
        self.assertNotIn(SIDEBAR_CHIP, body)

    def test_toggle_on_keeps_the_restricted_chip(self):
        self.set_bvn_toggle(True)
        vendor = self.make_vendor('p9b-on-restr', store_setup=False, restricted=True)

        body = self.get_chips_page(vendor)

        self.assertIn(RESTRICTED_CHIP, body)
        self.assertNotIn(NAVBAR_CHIP, body)

    def test_toggle_off_keeps_the_chip_for_a_finished_bvn(self):
        """BVN already done: step 2 (store setup) is still a live target."""
        self.set_bvn_toggle(False)
        vendor = self.make_vendor(
            'p9b-off-bvndone', store_setup=False, bank_status='verified'
        )

        body = self.get_chips_page(vendor)

        self.assertIn(NAVBAR_CHIP, body)
        self.assertIn(SIDEBAR_CHIP, body)

    # ------------------------------------------------------------------
    # dashboard
    # ------------------------------------------------------------------
    def test_dashboard_never_pushes_verification_in_either_state(self):
        vendor = self.make_vendor('p9b-dash', store_setup=False)
        self.client.force_login(vendor.user)

        self.set_bvn_toggle(False)
        off = self.body(self.client.get(reverse('vendors:dashboard')))
        self.assertNotIn(NAVBAR_CHIP, off)
        self.assertNotIn(SIDEBAR_CHIP, off)

        self.set_bvn_toggle(True)
        on = self.body(self.client.get(reverse('vendors:dashboard')))
        self.assertNotIn(NAVBAR_CHIP, on)
        self.assertNotIn(SIDEBAR_CHIP, on)

        # the sidebar navigation entry itself is a menu item, not a chip,
        # and stays in place either way
        self.assertIn(reverse('vendors:verification_center'), off)
        self.assertIn(reverse('vendors:verification_center'), on)

    # ------------------------------------------------------------------
    # one read per request (no loop)
    # ------------------------------------------------------------------
    @staticmethod
    def toggle_reads(queries):
        return [
            q for q in queries
            if 'platformsettings' in q['sql'].lower()
        ]

    def test_chip_page_reads_the_toggle_at_most_once(self):
        self.set_bvn_toggle(False)
        vendor = self.make_vendor('p9b-reads', store_setup=False)
        self.client.force_login(vendor.user)

        with CaptureQueriesContext(connection) as ctx:
            response = self.client.get(reverse('vendors:subscription_plans'))
        self.assertEqual(response.status_code, 200)

        reads = self.toggle_reads(ctx.captured_queries)
        print(
            'chip page query count: %s (platformsettings reads: %s)'
            % (len(ctx.captured_queries), len(reads))
        )
        self.assertLessEqual(len(reads), 1)

    def test_dashboard_reads_the_toggle_at_most_once(self):
        self.set_bvn_toggle(False)
        vendor = self.make_vendor('p9b-dash-reads', store_setup=False)
        self.client.force_login(vendor.user)

        with CaptureQueriesContext(connection) as ctx:
            response = self.client.get(reverse('vendors:dashboard'))
        self.assertEqual(response.status_code, 200)

        reads = self.toggle_reads(ctx.captured_queries)
        print(
            'dashboard query count: %s (platformsettings reads: %s)'
            % (len(ctx.captured_queries), len(reads))
        )
        self.assertLessEqual(len(reads), 1)

    def test_public_pages_do_not_read_the_toggle_for_anonymous_visitors(self):
        self.make_vendor('p9b-anon', store_setup=False)

        with CaptureQueriesContext(connection) as ctx:
            response = self.client.get(reverse('marketplace:product_list'))
        self.assertEqual(response.status_code, 200)

        reads = self.toggle_reads(ctx.captured_queries)
        print(
            'public product list query count: %s (platformsettings reads: %s)'
            % (len(ctx.captured_queries), len(reads))
        )
        self.assertEqual(len(reads), 0)
