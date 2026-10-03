"""
Phase 9 Task 6 - no Subscribe offer for an admin-suspended vendor
=================================================================

`subscription_state.is_restricted` is `not vendor.is_available`, and
`is_available` only reads the subscription dates - it knows nothing about
`verification_status`.  An admin-SUSPENDED vendor could therefore be shown
"Subscribe to restore everything" on the product-creation prompt and in the
dashboard hero, even though subscribing cannot lift a suspension.

Both surfaces must now show this exact copy instead, and only for suspended:

    Your store is currently suspended. Contact support for help.

linked to support@kasumarketplace.com.ng, the address already used across
the vendor templates (bvn_verification.html, verification/center.html, ...).

Restricted (non-suspended) and normal vendors keep today's behaviour.  The
descriptor (apps.vendors.subscription_state), its state keys, and every
visibility/contact rule are untouched.
"""

from datetime import timedelta

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.users.models import CustomUser
from apps.vendors.models import (
    MainCategory, Store, SubCategory, Subscription, VendorProfile,
)

DAY = timedelta(days=1)

SUSPENDED_COPY = 'Your store is currently suspended. Contact support for help.'
SUPPORT_MAILTO = 'mailto:support@kasumarketplace.com.ng'
SUBSCRIBE_RESTORES = 'Subscribe to restore everything'
PROMPT_HEADING = 'Subscription needed to add products'


class SuspendedSubscribeCopyTests(TestCase):
    """suspended vs restricted vs normal, on both surfaces."""

    def setUp(self):
        self.category = MainCategory.objects.create(name='Bags', slug='bags-p9')
        self.subcategory = SubCategory.objects.create(
            main_category=self.category, name='Totes', slug='totes-p9',
        )

    def make_vendor(self, key, suspended=False, restricted=False):
        user = CustomUser.objects.create_user(
            email=f'{key}@example.com',
            password='password123',
            username=key.replace('-', '_'),
            role='vendor',
        )
        vendor = user.vendorprofile
        vendor.store_setup_completed = True
        vendor.save(update_fields=['store_setup_completed'])
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
        if suspended:
            VendorProfile.objects.filter(pk=vendor.pk).update(
                verification_status='suspended'
            )
        # Re-fetch: the profile -> subscription cache may be stale.
        return VendorProfile.objects.get(pk=vendor.pk)

    @staticmethod
    def body(response):
        return response.content.decode('utf-8')

    # ------------------------------------------------------------------
    # Surface 1 - product-creation prompt page
    # ------------------------------------------------------------------
    def test_prompt_suspended_offers_support_instead_of_subscribe(self):
        vendor = self.make_vendor('p9-prompt-susp', suspended=True, restricted=True)
        self.client.force_login(vendor.user)

        response = self.client.get(reverse('vendors:product_create'))
        body = self.body(response)

        self.assertEqual(response.status_code, 200)
        self.assertIn(SUSPENDED_COPY, body)
        self.assertIn(SUPPORT_MAILTO, body)
        self.assertNotIn('Subscribe', body)
        self.assertNotIn(SUBSCRIBE_RESTORES, body)

    def test_prompt_restricted_still_offers_subscribe(self):
        vendor = self.make_vendor('p9-prompt-restr', restricted=True)
        self.client.force_login(vendor.user)

        response = self.client.get(reverse('vendors:product_create'))
        body = self.body(response)

        self.assertEqual(response.status_code, 200)
        self.assertIn(PROMPT_HEADING, body)
        self.assertIn('Subscribe', body)
        self.assertIn(reverse('vendors:subscription_plans'), body)
        self.assertNotIn(SUSPENDED_COPY, body)

    def test_prompt_normal_vendor_gets_the_form_not_the_prompt(self):
        vendor = self.make_vendor('p9-prompt-normal')
        self.client.force_login(vendor.user)

        response = self.client.get(reverse('vendors:product_create'))
        body = self.body(response)

        self.assertEqual(response.status_code, 200)
        self.assertNotIn(PROMPT_HEADING, body)
        self.assertNotIn(SUSPENDED_COPY, body)
        self.assertNotIn(SUPPORT_MAILTO, body)
        self.assertIn('id_subcategory', body)

    # ------------------------------------------------------------------
    # Surface 2 - dashboard hero button
    # ------------------------------------------------------------------
    def test_dashboard_suspended_offers_support_instead_of_subscribe(self):
        vendor = self.make_vendor('p9-dash-susp', suspended=True, restricted=True)
        self.client.force_login(vendor.user)

        response = self.client.get(reverse('vendors:dashboard'))
        body = self.body(response)

        self.assertEqual(response.status_code, 200)
        self.assertIn(SUSPENDED_COPY, body)
        self.assertIn(SUPPORT_MAILTO, body)
        self.assertNotIn('Subscribe', body)
        self.assertNotIn(SUBSCRIBE_RESTORES, body)

    def test_dashboard_suspended_with_active_subscription_still_no_subscribe(self):
        """Suspension alone must never produce a Subscribe CTA."""
        vendor = self.make_vendor('p9-dash-susp-paid', suspended=True)
        Subscription.objects.filter(vendor=vendor).update(
            status='active',
            plan='basic',
            period_end=timezone.now() + timedelta(days=20),
        )
        self.client.force_login(VendorProfile.objects.get(pk=vendor.pk).user)

        response = self.client.get(reverse('vendors:dashboard'))
        body = self.body(response)

        self.assertEqual(response.status_code, 200)
        self.assertIn(SUSPENDED_COPY, body)
        self.assertIn(SUPPORT_MAILTO, body)
        self.assertNotIn('Subscribe', body)

    def test_dashboard_restricted_still_offers_subscribe(self):
        vendor = self.make_vendor('p9-dash-restr', restricted=True)
        self.client.force_login(vendor.user)

        response = self.client.get(reverse('vendors:dashboard'))
        body = self.body(response)

        self.assertEqual(response.status_code, 200)
        self.assertIn('Subscribe', body)
        self.assertIn(reverse('vendors:subscription_plans'), body)
        self.assertNotIn(SUSPENDED_COPY, body)

    def test_dashboard_normal_vendor_has_no_hero_cta(self):
        vendor = self.make_vendor('p9-dash-normal')
        self.client.force_login(vendor.user)

        response = self.client.get(reverse('vendors:dashboard'))
        body = self.body(response)

        self.assertEqual(response.status_code, 200)
        self.assertIn('View Marketplace', body)
        self.assertNotIn(SUSPENDED_COPY, body)
        self.assertNotIn(SUPPORT_MAILTO, body)
        self.assertNotIn('Subscribe', body)
