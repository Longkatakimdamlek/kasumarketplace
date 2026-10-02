"""
Phase 5 - Free-plan first-product qualification
===============================================

Time simulation technique
--------------------------
The clock is never patched.  Rows are backdated with QuerySet.update() so the
real timezone.now() used by the hook and the properties sees a past timestamp:

    Subscription.objects.filter(...).update(first_product_at=now - <delta>)
    Product.objects.filter(...).update(created_at=now - <delta>)

Product creation, publication and deletion always go through the real ORM so
the real post_save hook (sync_vendor_qualification) runs.

Spec Task 7 items covered:
  1  new vendor signal defaults
  2  store creation never starts the countdown
  3  first product starts it, later products / deletion do not reset it
  4  third published product qualifies immediately (spec example)
  5  drafts do not count
  6  boundaries: day 6:23, day 8 (grace), day 14 + 1 minute
  7  effective_qualification_status / is_available timeline
  8  failure restricts the vendor (hook + command paths)
  9  a failed vendor never qualifies again via ORM saves
 10  paid plan skips qualification and the hook short-circuits
 11  hook ignores trial / active / expired rows
 12  no buyer reactivation notifications on qualification transitions
 13  backfill_subscriptions dry-run / --apply / idempotent / protected rows
14  check_subscription_status syncs and is idempotent
15  admin fields editable + restart action behaviour
16  plans page renders 200 with Subscribe buttons
17  computed property values
"""

from datetime import timedelta
from io import StringIO

from django.contrib import admin as django_admin
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.db import connection
from django.test import RequestFactory, TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from apps.marketplace.models import Wishlist
from apps.vendors.models import (
    MainCategory, Notification, Product, Store, SubCategory, Subscription,
    VendorProfile,
)
from apps.vendors.qualification import (
    FREE_TRIAL_DAYS,
    QUALIFICATION_DAYS,
    QUALIFICATION_GRACE_DAYS,
    effective_state,
    on_product_saved,
)
from apps.vendors.services.subscription_service import subscription_service
from apps.users.models import CustomUser

DAY = timedelta(days=1)


def hook_count_queries(sqls):
    """
    The published-product count run by on_product_saved filters on vendor_id;
    the unrelated store.total_products count filters on store_id.  Only the
    vendor_id COUNT on the product table belongs to the hook.
    """
    table = Product._meta.db_table
    return [
        sql for sql in sqls
        if 'COUNT(*)' in sql.upper()
        and table in sql
        and 'vendor_id' in sql
        and 'store_id' not in sql
    ]


class QualificationFixture(TestCase):
    """Shared vendor / store / product factory."""

    def setUp(self):
        self.category = MainCategory.objects.create(name='Watches', slug='watches-p5')
        self.subcategory = SubCategory.objects.create(
            main_category=self.category, name='Digital', slug='digital-p5',
        )

    def make_vendor(self, key, store_published=True, store_setup=True):
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
            is_published=store_published,
        )
        # Re-fetch: the profile -> subscription cache may be stale after the
        # signal created the row.
        return VendorProfile.objects.get(pk=vendor.pk), store

    def make_product(self, vendor, store, n, status='draft'):
        return Product.objects.create(
            vendor=vendor,
            store=store,
            subcategory=self.subcategory,
            title=f'{vendor.pk} product {n}',
            slug=f'p5-{vendor.pk}-{n}',
            description='A product for qualification tests',
            price='1500.00',
            status=status,
        )

    @staticmethod
    def sub_of(vendor):
        return Subscription.objects.get(vendor=vendor)

    @staticmethod
    def backdate_first_product(vendor, delta):
        Subscription.objects.filter(vendor=vendor).update(
            first_product_at=timezone.now() - delta
        )

    @staticmethod
    def product_detail_url(store, product):
        return reverse('product_detail_public', kwargs={
            'store_slug': store.slug, 'product_slug': product.slug,
        })


# =========================================================================
# 1-2: signup and store setup
# =========================================================================

class NewVendorSignalTests(QualificationFixture):

    def test_new_vendor_starts_qualifying(self):
        """(1) status qualifying, plan free, not_started, no trial date."""
        vendor, store = self.make_vendor('signup', store_setup=False)
        sub = self.sub_of(vendor)

        self.assertEqual(sub.status, 'qualifying')
        self.assertEqual(sub.plan, 'free')
        self.assertEqual(sub.qualification_status, 'not_started')
        self.assertIsNone(sub.trial_ends_at)
        self.assertIsNone(sub.first_product_at)
        self.assertTrue(sub.is_publicly_active)
        self.assertTrue(vendor.is_available)

        self.assertFalse(vendor.can_sell, 'store setup not completed yet')
        vendor.store_setup_completed = True
        vendor.save(update_fields=['store_setup_completed'])
        vendor = VendorProfile.objects.get(pk=vendor.pk)
        self.assertTrue(vendor.can_sell)

    def test_store_creation_never_starts_the_countdown(self):
        """(2) store creation alone leaves first_product_at None."""
        vendor, store = self.make_vendor('store-only')
        sub = self.sub_of(vendor)

        self.assertIsNone(sub.first_product_at)
        self.assertEqual(sub.qualification_status, 'not_started')
        self.assertEqual(sub.status, 'qualifying')

        # A subscription row created 30 days ago with no product: still live.
        Subscription.objects.filter(pk=sub.pk).update(
            created_at=timezone.now() - timedelta(days=30)
        )
        sub = self.sub_of(vendor)
        self.assertIsNone(sub.first_product_at)
        self.assertEqual(sub.qualification_status, 'not_started')
        self.assertTrue(sub.is_publicly_active)
        self.assertTrue(VendorProfile.objects.get(pk=vendor.pk).is_available)


# =========================================================================
# 3: the countdown start is immutable
# =========================================================================

class FirstProductCountdownTests(QualificationFixture):

    def test_first_draft_starts_the_countdown(self):
        """(3) a draft starts it and the label becomes in_progress."""
        vendor, store = self.make_vendor('first-draft')
        p1 = self.make_product(vendor, store, 1, status='draft')

        sub = self.sub_of(vendor)
        self.assertIsNotNone(sub.first_product_at)
        self.assertLess(abs(sub.first_product_at - p1.created_at), timedelta(seconds=2))
        self.assertEqual(sub.qualification_status, 'in_progress')
        self.assertEqual(sub.status, 'qualifying')

    def test_second_product_and_deletion_do_not_reset_the_start(self):
        """(3) only the very first product sets first_product_at."""
        vendor, store = self.make_vendor('immutability')
        p1 = self.make_product(vendor, store, 1, status='draft')
        started = self.sub_of(vendor).first_product_at

        p2 = self.make_product(vendor, store, 2, status='draft')
        self.assertEqual(self.sub_of(vendor).first_product_at, started)

        p1.delete()
        p2.delete()
        sub = self.sub_of(vendor)
        self.assertEqual(sub.first_product_at, started)
        self.assertEqual(sub.qualification_status, 'in_progress')
        self.assertEqual(sub.qualified_products_count, 0)


# =========================================================================
# 4-5: qualifying and drafts
# =========================================================================

class QualificationSuccessTests(QualificationFixture):

    def test_third_published_product_qualifies_immediately(self):
        """(4) product 1 day 1, product 2 day 3, product 3 published day 5."""
        vendor, store = self.make_vendor('spec-example')
        now = timezone.now()

        p1 = self.make_product(vendor, store, 1, status='published')
        # timeline: first product 4 days ago (day 1 of a 5-day window)
        Subscription.objects.filter(vendor=vendor).update(
            first_product_at=now - timedelta(days=4)
        )
        Product.objects.filter(pk=p1.pk).update(created_at=now - timedelta(days=4))

        p2 = self.make_product(vendor, store, 2, status='published')
        Product.objects.filter(pk=p2.pk).update(created_at=now - timedelta(days=2))
        self.assertEqual(self.sub_of(vendor).status, 'qualifying')
        self.assertEqual(self.sub_of(vendor).qualification_products_needed, 1)

        # day 5: the third published product triggers qualification at once
        self.make_product(vendor, store, 3, status='published')

        sub = self.sub_of(vendor)
        self.assertEqual(sub.status, 'trial')
        self.assertEqual(sub.plan, 'free')
        self.assertEqual(sub.qualification_status, 'qualified')
        self.assertIsNotNone(sub.qualified_at)
        expected_trial_end = timezone.now() + timedelta(days=FREE_TRIAL_DAYS)
        self.assertLess(abs(sub.trial_ends_at - expected_trial_end), timedelta(minutes=1))
        self.assertIsNone(sub.grace_ends_at)
        self.assertIsNone(sub.period_end)
        self.assertLess(
            abs(sub.first_product_at - (now - timedelta(days=4))), timedelta(seconds=2),
        )

    def test_drafts_do_not_count_until_published(self):
        """(5) three drafts do not qualify; publishing them does."""
        vendor, store = self.make_vendor('drafts-only')
        drafts = [
            self.make_product(vendor, store, n, status='draft') for n in (1, 2, 3)
        ]

        sub = self.sub_of(vendor)
        self.assertEqual(sub.status, 'qualifying')
        self.assertEqual(sub.qualified_products_count, 0)
        self.assertEqual(sub.qualification_products_needed, 3)

        for index, product in enumerate(drafts[:2]):
            product.status = 'published'
            product.save()
            sub = self.sub_of(vendor)
            self.assertEqual(sub.status, 'qualifying')
            self.assertEqual(sub.qualification_products_needed, 2 - index)

        drafts[2].status = 'published'
        drafts[2].save()
        sub = self.sub_of(vendor)
        self.assertEqual(sub.status, 'trial')
        self.assertEqual(sub.qualification_status, 'qualified')
        self.assertEqual(sub.qualified_products_count, 3)


# =========================================================================
# 6-7: boundaries and the status timeline
# =========================================================================

class QualificationBoundaryTests(QualificationFixture):

    def test_third_published_at_day_6_23_qualifies(self):
        """(6) 6 days 23 hours after the first product still qualifies."""
        vendor, store = self.make_vendor('day-6')
        self.make_product(vendor, store, 1, status='published')
        self.backdate_first_product(vendor, timedelta(days=6, hours=23))

        self.make_product(vendor, store, 2, status='published')
        self.assertEqual(self.sub_of(vendor).status, 'qualifying')

        self.make_product(vendor, store, 3, status='published')
        self.assertEqual(self.sub_of(vendor).status, 'trial')
        self.assertEqual(self.sub_of(vendor).qualification_status, 'qualified')

    def test_third_published_on_day_8_qualifies_and_starts_the_trial(self):
        """(6) inside the grace window the third product still qualifies."""
        vendor, store = self.make_vendor('day-8')
        self.make_product(vendor, store, 1, status='published')
        self.backdate_first_product(vendor, timedelta(days=8))

        sub = self.sub_of(vendor)
        self.assertEqual(sub.effective_qualification_status, 'grace')
        self.assertTrue(sub.is_publicly_active)

        self.make_product(vendor, store, 2, status='published')
        self.assertEqual(self.sub_of(vendor).qualification_status, 'grace')

        self.make_product(vendor, store, 3, status='published')
        sub = self.sub_of(vendor)
        self.assertEqual(sub.status, 'trial')
        self.assertEqual(sub.qualification_status, 'qualified')

    def test_after_day_14_the_third_product_does_not_qualify(self):
        """(6) 14 days + 1 minute: failed, never qualified."""
        vendor, store = self.make_vendor('day-14')
        self.make_product(vendor, store, 1, status='published')
        self.backdate_first_product(vendor, timedelta(days=14, minutes=1))

        self.make_product(vendor, store, 2, status='published')
        sub = self.sub_of(vendor)
        self.assertEqual(sub.status, 'expired')
        self.assertEqual(sub.qualification_status, 'failed')
        self.assertEqual(sub.effective_qualification_status, 'failed')

        # a further product never revives it
        self.make_product(vendor, store, 3, status='published')
        sub = self.sub_of(vendor)
        self.assertEqual(sub.status, 'expired')
        self.assertEqual(sub.qualification_status, 'failed')
        self.assertIsNone(sub.qualified_at)

    def test_effective_status_and_availability_timeline(self):
        """(7) day 3 in_progress/True, day 8 grace/True, day 15 failed/False."""
        vendor, store = self.make_vendor('timeline')

        for delta, expected_state, expected_available in (
            (timedelta(days=3), 'in_progress', True),
            (timedelta(days=8), 'grace', True),
            (timedelta(days=15), 'failed', False),
        ):
            self.backdate_first_product(vendor, delta)
            sub = self.sub_of(vendor)
            self.assertEqual(sub.effective_qualification_status, expected_state)
            self.assertEqual(sub.is_publicly_active, expected_available)
            self.assertEqual(
                VendorProfile.objects.get(pk=vendor.pk).is_available,
                expected_available,
            )

        # the pure helper agrees with the stored-label property
        sub = self.sub_of(vendor)
        self.assertEqual(effective_state(sub, timezone.now()), 'failed')
        self.assertEqual(sub.status, 'qualifying', 'no product -> hook never ran')


# =========================================================================
# 8-9: failure is a restriction, not a reset
# =========================================================================

class QualificationFailureTests(QualificationFixture):

    def test_hook_failure_restricts_the_vendor(self):
        """(8) hook path: expired/failed but still public, contact hidden."""
        vendor, store = self.make_vendor('fail-hook')
        p1 = self.make_product(vendor, store, 1, status='published')
        self.backdate_first_product(vendor, timedelta(days=14, minutes=1))
        self.make_product(vendor, store, 2, status='published')

        sub = self.sub_of(vendor)
        vendor = VendorProfile.objects.get(pk=vendor.pk)
        self.assertEqual(sub.status, 'expired')
        self.assertEqual(sub.qualification_status, 'failed')
        self.assertFalse(vendor.is_available)
        self.assertFalse(vendor.can_sell)

        # store and product stay publicly listed
        self.assertIn(store, Store.objects.publicly_visible())
        p1.refresh_from_db()
        self.assertIn(p1, Product.objects.publicly_visible())

        # Phase 4 contact gating hides the contact controls
        response = self.client.get(self.product_detail_url(store, p1))
        self.assertEqual(response.status_code, 200)
        self.assertIn('Vendor Unavailable', response.content.decode('utf-8'))

        # Phase 6: product creation is blocked by the subscription prompt,
        # not by a redirect to the verification center (was vendor_verified_required).
        self.client.force_login(vendor.user)
        prompt = self.client.get(reverse('vendors:product_create'))
        self.assertEqual(prompt.status_code, 200)
        body = prompt.content.decode('utf-8')
        self.assertIn('Subscription needed to add products', body)
        self.assertIn(reverse('vendors:subscription_plans'), body)

    def test_command_failure_path_matches_the_hook(self):
        """(8) command path: same expired/failed end state."""
        vendor, store = self.make_vendor('fail-command')
        self.make_product(vendor, store, 1, status='published')
        self.backdate_first_product(vendor, timedelta(days=15))

        out = StringIO()
        call_command('check_subscription_status', stdout=out)

        sub = self.sub_of(vendor)
        vendor = VendorProfile.objects.get(pk=vendor.pk)
        self.assertEqual(sub.status, 'expired')
        self.assertEqual(sub.qualification_status, 'failed')
        self.assertFalse(vendor.is_available)
        self.assertFalse(vendor.can_sell)

    def test_failed_vendor_never_qualifies_again(self):
        """(9) ORM saves by a failed vendor change nothing."""
        vendor, store = self.make_vendor('fail-orm')
        p1 = self.make_product(vendor, store, 1, status='published')
        self.backdate_first_product(vendor, timedelta(days=14, minutes=1))
        self.make_product(vendor, store, 2, status='published')

        before = self.sub_of(vendor)
        started = before.first_product_at
        self.assertEqual(before.status, 'expired')

        for n in (3, 4, 5, 6):
            self.make_product(vendor, store, n, status='published')

        after = self.sub_of(vendor)
        self.assertEqual(after.status, 'expired')
        self.assertEqual(after.qualification_status, 'failed')
        self.assertEqual(after.first_product_at, started)
        self.assertIsNone(after.qualified_at)
        self.assertIsNone(after.trial_ends_at)
        self.assertEqual(on_product_saved(p1), False)


# =========================================================================
# 10-11: paid skip and hook scope
# =========================================================================

class PaidSkipAndHookScopeTests(QualificationFixture):

    def test_paid_plan_skips_qualification_and_hook_short_circuits(self):
        """(10) activate_subscription -> skipped, later saves skip counting."""
        vendor, store = self.make_vendor('paid-skip')
        sub = self.sub_of(vendor)
        self.assertEqual(sub.status, 'qualifying')

        subscription_service.activate_subscription(
            sub,
            {
                'customer_code': 'cus_test',
                'subscription_code': 'sub_test',
                'plan_code': 'PLN_test',
            },
            'basic',
        )
        sub = self.sub_of(vendor)
        self.assertEqual(sub.status, 'active')
        self.assertEqual(sub.plan, 'basic')
        self.assertEqual(sub.qualification_status, 'skipped')

        paid_product = self.make_product(vendor, store, 1, status='published')
        with CaptureQueriesContext(connection) as ctx:
            paid_product.save()
        self.assertEqual(
            hook_count_queries([q['sql'] for q in ctx.captured_queries]), [],
            'the hook must not count products for a paid vendor',
        )
        sub = self.sub_of(vendor)
        self.assertEqual(sub.status, 'active')
        self.assertEqual(sub.plan, 'basic')
        self.assertEqual(sub.qualification_status, 'skipped')
        self.assertIsNone(sub.first_product_at)

        # positive control: a qualifying vendor does run the count query
        other, other_store = self.make_vendor('still-qualifying')
        other_product = self.make_product(other, other_store, 1, status='published')
        with CaptureQueriesContext(connection) as ctx:
            other_product.save()
        self.assertEqual(len(hook_count_queries([q['sql'] for q in ctx.captured_queries])), 1)

    def test_hook_ignores_trial_active_and_expired_rows(self):
        """(11) non-qualifying statuses are never touched or counted."""
        for status in ('trial', 'active', 'expired'):
            vendor, store = self.make_vendor(f'ignore-{status}')
            Subscription.objects.filter(vendor=vendor).update(
                status=status,
                trial_ends_at=timezone.now() + timedelta(days=30),
                period_end=timezone.now() + timedelta(days=30),
                qualification_status='not_started',
            )
            product = self.make_product(vendor, store, 1, status='published')

            with CaptureQueriesContext(connection) as ctx:
                result = on_product_saved(product)
            self.assertFalse(result, f'{status}: hook must return early')

            sub = self.sub_of(vendor)
            self.assertEqual(sub.status, status)
            self.assertIsNone(sub.first_product_at)
            self.assertEqual(sub.qualification_status, 'not_started')
            self.assertEqual(
                hook_count_queries([q['sql'] for q in ctx.captured_queries]), [],
                f'{status}: no product count for a non-qualifying vendor',
            )


# =========================================================================
# 12: buyer notifications
# =========================================================================

class BuyerReactivationNotificationTests(QualificationFixture):

    @staticmethod
    def back_notifications():
        return Notification.objects.filter(title__icontains='is Back')

    def wishlisted_buyer(self, vendor, product):
        buyer = CustomUser.objects.create_user(
            email=f'buyer-{vendor.pk}@example.com',
            password='password123',
            username=f'buyer_{vendor.pk}',
            role='buyer',
        )
        Wishlist.objects.create(user=buyer, product=product)
        return buyer

    def test_qualification_transitions_do_not_notify_buyers(self):
        """(12) qualifying->trial and qualifying->expired stay silent."""
        # (a) qualifying -> trial through the product hook
        vendor_a, store_a = self.make_vendor('react-trial')
        product_a = self.make_product(vendor_a, store_a, 1, status='published')
        self.wishlisted_buyer(vendor_a, product_a)
        self.backdate_first_product(vendor_a, timedelta(days=2))
        self.make_product(vendor_a, store_a, 2, status='published')
        self.make_product(vendor_a, store_a, 3, status='published')
        self.assertEqual(self.sub_of(vendor_a).status, 'trial')
        self.assertEqual(self.back_notifications().count(), 0)

        # (b) qualifying -> expired through the command
        vendor_b, store_b = self.make_vendor('react-expired')
        product_b = self.make_product(vendor_b, store_b, 1, status='published')
        self.wishlisted_buyer(vendor_b, product_b)
        self.backdate_first_product(vendor_b, timedelta(days=15))
        call_command('check_subscription_status', stdout=StringIO())
        self.assertEqual(self.sub_of(vendor_b).status, 'expired')
        self.assertEqual(self.back_notifications().count(), 0)

        # (c) positive control: expired -> trial DOES notify
        vendor_c, store_c = self.make_vendor('react-control')
        product_c = self.make_product(vendor_c, store_c, 1, status='published')
        self.wishlisted_buyer(vendor_c, product_c)
        Subscription.objects.filter(vendor=vendor_c).update(status='expired')
        sub_c = self.sub_of(vendor_c)
        sub_c.status = 'trial'
        sub_c.trial_ends_at = timezone.now() + timedelta(days=90)
        sub_c.save()
        self.assertEqual(self.back_notifications().count(), 1)


# =========================================================================
# 13: backfill_subscriptions
# =========================================================================

class BackfillCommandTests(QualificationFixture):

    def build_rows(self):
        now = timezone.now()

        # (1) vendor with no Subscription row, with one product
        vendor1, store1 = self.make_vendor('bf-no-sub')
        product1 = self.make_product(vendor1, store1, 1, status='published')
        Subscription.objects.filter(vendor=vendor1).delete()

        # (2) legacy signup trial
        vendor2, store2 = self.make_vendor('bf-trial')
        Subscription.objects.filter(vendor=vendor2).update(
            status='trial', qualification_status='not_started',
        )

        # (3) legacy free "active" row from the old backfill
        vendor3, store3 = self.make_vendor('bf-active')
        Subscription.objects.filter(vendor=vendor3).update(
            status='active', plan='free', period_end=now + timedelta(days=30),
        )

        # protected rows
        vendor4, store4 = self.make_vendor('bf-paystack')
        Subscription.objects.filter(vendor=vendor4).update(
            status='trial', qualification_status='not_started',
            paystack_subscription_code='SUB_42',
        )
        vendor5, store5 = self.make_vendor('bf-expired')
        Subscription.objects.filter(vendor=vendor5).update(
            status='expired', qualification_status='failed',
        )
        vendor6, store6 = self.make_vendor('bf-qualifying')

        return {
            'v1': vendor1, 'p1': product1, 'v2': vendor2, 'v3': vendor3,
            'v4': vendor4, 'v5': vendor5, 'v6': vendor6,
        }

    @staticmethod
    def snapshot():
        return {
            sub.pk: (
                sub.status, sub.plan, sub.qualification_status,
                sub.trial_ends_at, sub.period_end, sub.first_product_at,
                sub.qualified_at, sub.paystack_subscription_code,
            )
            for sub in Subscription.objects.all()
        }

    def test_dry_run_changes_nothing_and_prints_counts(self):
        """(13) default is a no-op that reports per-category counts."""
        rows = self.build_rows()
        before = self.snapshot()
        notifications_before = Notification.objects.count()

        out = StringIO()
        call_command('backfill_subscriptions', stdout=out)
        output = out.getvalue()

        self.assertEqual(self.snapshot(), before, 'dry run must not write')
        self.assertEqual(Notification.objects.count(), notifications_before)
        self.assertIn('1 vendor(s) without a Subscription', output)
        self.assertIn('1 legacy signup trial(s)', output)
        self.assertIn('1 legacy free active row(s)', output)
        self.assertIn('DRY RUN', output)
        self.assertIn(rows['v2'].user.email, output)
        self.assertIn(rows['v3'].user.email, output)

    def test_apply_grandfather_every_category_and_skips_protected_rows(self):
        """(13) --apply handles (1)(2)(3), protects the rest, is idempotent."""
        rows = self.build_rows()
        protected_before = {
            pk: self.snapshot()[pk]
            for pk in (
                Subscription.objects.get(vendor=rows['v4']).pk,
                Subscription.objects.get(vendor=rows['v5']).pk,
                Subscription.objects.get(vendor=rows['v6']).pk,
            )
        }
        notifications_before = Notification.objects.count()

        out = StringIO()
        call_command('backfill_subscriptions', '--apply', stdout=out)
        self.assertIn('created 1', out.getvalue())

        now = timezone.now()

        # (1) created row
        sub1 = Subscription.objects.get(vendor=rows['v1'])
        self.assertEqual(sub1.status, 'trial')
        self.assertEqual(sub1.plan, 'free')
        self.assertEqual(sub1.qualification_status, 'qualified')
        self.assertIsNotNone(sub1.qualified_at)
        self.assertLess(abs(sub1.trial_ends_at - (now + timedelta(days=FREE_TRIAL_DAYS))), timedelta(seconds=5))
        self.assertEqual(sub1.first_product_at, rows['p1'].created_at)

        # (2) grandfathered legacy trial
        sub2 = Subscription.objects.get(vendor=rows['v2'])
        self.assertEqual(sub2.status, 'trial')
        self.assertEqual(sub2.qualification_status, 'qualified')
        self.assertLess(abs(sub2.trial_ends_at - (now + timedelta(days=FREE_TRIAL_DAYS))), timedelta(seconds=5))
        self.assertIsNone(sub2.first_product_at, 'vendor has no products')

        # (3) converted legacy active row
        sub3 = Subscription.objects.get(vendor=rows['v3'])
        self.assertEqual(sub3.status, 'trial')
        self.assertEqual(sub3.plan, 'free')
        self.assertEqual(sub3.qualification_status, 'qualified')
        self.assertIsNone(sub3.period_end)
        self.assertLess(abs(sub3.trial_ends_at - (now + timedelta(days=FREE_TRIAL_DAYS))), timedelta(seconds=5))

        # protected rows untouched
        after = self.snapshot()
        for pk, values in protected_before.items():
            self.assertEqual(after[pk], values, f'protected row {pk} changed')

        # no reactivation notifications
        self.assertEqual(Notification.objects.count(), notifications_before)

        # a second --apply is a no-op
        before_second = self.snapshot()
        out2 = StringIO()
        call_command('backfill_subscriptions', '--apply', stdout=out2)
        self.assertEqual(self.snapshot(), before_second)
        self.assertIn('Nothing to backfill', out2.getvalue())


# =========================================================================
# 14: check_subscription_status
# =========================================================================

class CheckSubscriptionStatusCommandTests(QualificationFixture):

    def test_syncs_stale_qualifying_row_and_is_idempotent(self):
        """(14) past day 14 -> failed/expired; second run writes nothing."""
        vendor, store = self.make_vendor('cmd-stale')
        self.make_product(vendor, store, 1, status='published')
        self.backdate_first_product(vendor, timedelta(days=15))

        out = StringIO()
        call_command('check_subscription_status', stdout=out)
        output = out.getvalue()
        self.assertIn('qualification synced: 1, failed: 1', output)

        sub = self.sub_of(vendor)
        self.assertEqual(sub.status, 'expired')
        self.assertEqual(sub.qualification_status, 'failed')

        out2 = StringIO()
        call_command('check_subscription_status', stdout=out2)
        self.assertIn('qualification synced: 0, failed: 0', out2.getvalue())
        self.assertEqual(self.sub_of(vendor).status, 'expired')

    def test_existing_grace_expiry_behaviour_is_unchanged(self):
        """(14) expire_grace_periods still runs first and is untouched."""
        vendor, store = self.make_vendor('cmd-grace')
        Subscription.objects.filter(vendor=vendor).update(
            status='past_due',
            grace_ends_at=timezone.now() - timedelta(days=1),
        )

        out = StringIO()
        call_command('check_subscription_status', stdout=out)
        self.assertIn('Expired 1 subscription(s)', out.getvalue())

        sub = self.sub_of(vendor)
        self.assertEqual(sub.status, 'expired')
        self.assertEqual(
            sub.qualification_status, 'not_started',
            'a non-qualifying row keeps its stored label',
        )

    def test_in_window_row_only_has_its_label_refreshed(self):
        """(14) inside the window the row stays qualifying."""
        vendor, store = self.make_vendor('cmd-in-window')
        self.make_product(vendor, store, 1, status='published')
        self.backdate_first_product(vendor, timedelta(days=3))
        Subscription.objects.filter(vendor=vendor).update(
            qualification_status='not_started'
        )

        out = StringIO()
        call_command('check_subscription_status', stdout=out)
        self.assertIn('qualification synced: 1, failed: 0', out.getvalue())

        sub = self.sub_of(vendor)
        self.assertEqual(sub.status, 'qualifying')
        self.assertEqual(sub.qualification_status, 'in_progress')


# =========================================================================
# 15: admin
# =========================================================================

class SubscriptionAdminQualificationTests(QualificationFixture):

    def setUp(self):
        super().setUp()
        self.User = get_user_model()
        self.superuser = self.User.objects.create_superuser(
            email='p5admin@example.com', password='password123',
        )

    def _admin(self):
        from apps.vendors.admin import SubscriptionAdmin
        return SubscriptionAdmin(Subscription, django_admin.site)

    def test_qualification_fields_are_exposed_and_editable(self):
        """(15) the three new fields are in the change form, not readonly."""
        vendor, store = self.make_vendor('admin-fields')
        sub = self.sub_of(vendor)
        model_admin = self._admin()

        self.assertIn('qualification_status', model_admin.list_display)
        self.assertIn('qualification_status', model_admin.list_filter)
        for field in ('qualification_status', 'first_product_at', 'qualified_at'):
            self.assertNotIn(field, model_admin.readonly_fields)

        request = RequestFactory().get(
            '/admin/vendors/subscription/%s/change/' % sub.pk
        )
        request.user = self.superuser
        form_class = model_admin.get_form(request, obj=sub, fields=None, change=True)
        base_fields = set(form_class.base_fields)
        for field in ('qualification_status', 'first_product_at', 'qualified_at'):
            self.assertIn(field, base_fields)

    def test_restart_qualification_window_action(self):
        """(15) restarts an eligible free row, skips paid/active rows."""
        now = timezone.now()

        # eligible: expired free vendor
        eligible_vendor, store = self.make_vendor('admin-restart')
        Subscription.objects.filter(vendor=eligible_vendor).update(
            status='expired',
            qualification_status='failed',
            trial_ends_at=now - timedelta(days=1),
            grace_ends_at=now - timedelta(days=1),
            qualified_at=now - timedelta(days=40),
        )

        # protected: has a Paystack code
        paid_vendor, store = self.make_vendor('admin-paystack')
        Subscription.objects.filter(vendor=paid_vendor).update(
            status='trial', paystack_subscription_code='SUB_77',
        )

        # protected: already active
        active_vendor, store = self.make_vendor('admin-active')
        Subscription.objects.filter(vendor=active_vendor).update(status='active')

        eligible = Subscription.objects.get(vendor=eligible_vendor)
        paid = Subscription.objects.get(vendor=paid_vendor)
        active = Subscription.objects.get(vendor=active_vendor)

        self.client.force_login(self.superuser)
        response = self.client.post(
            reverse('admin:vendors_subscription_changelist'),
            {
                'action': 'restart_qualification_window',
                '_selected_action': [str(eligible.pk), str(paid.pk), str(active.pk)],
            },
            follow=True,
        )
        self.assertEqual(response.status_code, 200)

        messages = [str(m) for m in response.context['messages']]
        self.assertTrue(
            any('Restarted 1 qualification window(s); skipped 2' in m for m in messages),
            messages,
        )
        self.assertTrue(any('has paystack subscription' in m for m in messages), messages)
        self.assertTrue(any('status active' in m for m in messages), messages)

        eligible.refresh_from_db()
        self.assertEqual(eligible.status, 'qualifying')
        self.assertEqual(eligible.qualification_status, 'in_progress')
        self.assertIsNone(eligible.qualified_at)
        self.assertIsNone(eligible.trial_ends_at)
        self.assertIsNone(eligible.grace_ends_at)
        self.assertLess(abs(eligible.first_product_at - timezone.now()), timedelta(seconds=10))

        paid.refresh_from_db()
        self.assertEqual(paid.status, 'trial')
        self.assertEqual(paid.paystack_subscription_code, 'SUB_77')

        active.refresh_from_db()
        self.assertEqual(active.status, 'active')


# =========================================================================
# 16: plans page (Task 6 template check)
# =========================================================================

class PlansPageRenderingTests(QualificationFixture):

    def assert_plans_page(self, key, sub_fields, expected_status_label):
        vendor, store = self.make_vendor(key)
        sub = self.sub_of(vendor)
        for field, value in sub_fields.items():
            setattr(sub, field, value)
        sub.save()

        self.client.force_login(vendor.user)
        response = self.client.get(reverse('vendors:subscription_plans'))
        content = response.content.decode('utf-8')

        self.assertEqual(response.status_code, 200, key)
        self.assertIn(expected_status_label, content, key)
        self.assertIn('Subscribe to Basic Plan', content, key)
        self.assertIn('Subscribe to Premium Plan', content, key)
        self.assertIn(reverse('vendors:subscription_subscribe'), content, key)

    def test_plans_page_renders_for_every_status(self):
        """(16) qualifying / trial / expired all render 200 with buttons."""
        self.assert_plans_page('plans-qualifying', {}, 'Qualifying')
        self.assert_plans_page(
            'plans-trial',
            {'status': 'trial', 'trial_ends_at': timezone.now() + timedelta(days=90)},
            'Trial',
        )
        self.assert_plans_page(
            'plans-expired',
            {'status': 'expired', 'qualification_status': 'failed'},
            'Expired',
        )


# =========================================================================
# 17: computed properties
# =========================================================================

class QualificationPropertyTests(QualificationFixture):

    def test_needed_and_days_left_through_the_window(self):
        """(17) property values at several points in the timeline."""
        vendor, store = self.make_vendor('props')
        sub = self.sub_of(vendor)

        # not started: no deadline, no days left, everything needed
        self.assertIsNone(sub.qualification_deadline)
        self.assertIsNone(sub.qualification_grace_deadline)
        self.assertIsNone(sub.qualification_days_left)
        self.assertEqual(sub.qualification_products_needed, 3)
        self.assertEqual(sub.qualified_products_count, 0)
        self.assertEqual(sub.effective_qualification_status, 'not_started')

        # day 0: first product just created -> 7 days left
        self.make_product(vendor, store, 1, status='draft')
        sub = self.sub_of(vendor)
        self.assertIsNotNone(sub.qualification_deadline)
        self.assertEqual(
            sub.qualification_grace_deadline - sub.qualification_deadline,
            timedelta(days=QUALIFICATION_GRACE_DAYS),
        )
        self.assertEqual(sub.qualification_days_left, QUALIFICATION_DAYS)
        self.assertEqual(sub.effective_qualification_status, 'in_progress')

        # day 3 of the window -> 4 days left on the day-7 deadline
        self.backdate_first_product(vendor, timedelta(days=3))
        sub = self.sub_of(vendor)
        self.assertEqual(sub.qualification_days_left, 4)
        self.assertEqual(sub.effective_qualification_status, 'in_progress')

        # day 8 -> grace, 6 days left on the day-14 deadline
        self.backdate_first_product(vendor, timedelta(days=8))
        sub = self.sub_of(vendor)
        self.assertEqual(sub.effective_qualification_status, 'grace')
        self.assertEqual(sub.qualification_days_left, 6)

        # day 15 -> failed, no days left
        self.backdate_first_product(vendor, timedelta(days=15))
        sub = self.sub_of(vendor)
        self.assertEqual(sub.effective_qualification_status, 'failed')
        self.assertEqual(sub.qualification_days_left, 0)

    def test_needed_counts_only_published_products(self):
        """(17) drafts are not counted by qualified_products_count."""
        vendor, store = self.make_vendor('props-count')
        self.make_product(vendor, store, 1, status='draft')
        self.make_product(vendor, store, 2, status='draft')

        sub = self.sub_of(vendor)
        self.assertEqual(sub.qualified_products_count, 0)
        self.assertEqual(sub.qualification_products_needed, 3)

        published = self.make_product(vendor, store, 3, status='published')
        sub = self.sub_of(vendor)
        self.assertEqual(sub.qualified_products_count, 1)
        self.assertEqual(sub.qualification_products_needed, 2)

        # non-qualifying rows never need anything
        Subscription.objects.filter(vendor=vendor).update(status='active')
        sub = self.sub_of(vendor)
        self.assertEqual(sub.qualification_products_needed, 0)
        self.assertIsNone(sub.qualification_days_left)
        self.assertEqual(published.status, 'published')
