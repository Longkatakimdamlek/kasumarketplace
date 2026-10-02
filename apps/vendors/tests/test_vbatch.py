"""
Phase 8 - V-Batch (persistent badge) + BVN admin toggle
=======================================================

Covers:
  - award_vbatch(): first award, idempotence, source never overwritten,
    race safety (conditional UPDATE loses when the row changed underneath)
  - Premium trigger: activate_subscription, Basic -> Premium upgrade, and
    the fact that Basic / Free never award
  - persistence: downgrade / cancel / expiry / restriction / suspension never
    clear the flag, plus a repo-wide grep that no production code clears it
  - BVN trigger and the admin suspension toggle (ON awards, OFF does not,
    OFF after an award keeps the badge)
  - notification: one in-app + one email on the first award, nothing on
    repeat, nothing from the backfill
  - backfill_vbatch: dry-run writes nothing, --apply awards with the right
    sources, re-run is a no-op, no notifications
  - display: product card, product detail, storefront; absent for a vendor
    without it; still present when the vendor is restricted
  - independence: V-Batch never changes restricted/selling state
  - public pages issue the same number of queries with and without the flag

No existing test is modified.
"""

import re
from datetime import datetime, timedelta
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from django.conf import settings
from django.contrib import admin as django_admin
from django.contrib.messages.storage.fallback import FallbackStorage
from django.core import mail
from django.core.management import call_command
from django.db import connection
from django.test import RequestFactory, TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from apps.marketplace.models import ContactIntent
from apps.users.models import CustomUser
from apps.vendors.models import (
    MainCategory,
    Notification,
    Product,
    Store,
    SubCategory,
    Subscription,
    VendorProfile,
)
from apps.vendors.services.subscription_service import (
    SubscriptionService,
    subscription_service,
)
from apps.vendors.vbatch import award_vbatch

NOW = timezone.now()
PHONE = '08099887766'
WHATSAPP = '2348099887766'

VALID_TRIAL = {'status': 'trial', 'trial_ends_at': NOW + timedelta(days=10)}
EXPIRED_TRIAL = {'status': 'trial', 'trial_ends_at': NOW - timedelta(days=1)}
ACTIVE_PREMIUM = {
    'status': 'active',
    'plan': 'premium',
    'period_end': NOW + timedelta(days=25),
}
ACTIVE_BASIC = {
    'status': 'active',
    'plan': 'basic',
    'period_end': NOW + timedelta(days=25),
}

VBATCH_TITLE = 'V-Batch earned'
VBATCH_MESSAGE = (
    'Your store now has the V-Batch. It stays on your store permanently.'
)


class VbatchFixture(TestCase):

    def setUp(self):
        self.category = MainCategory.objects.create(
            name='Electronics', slug='vb-electronics',
        )
        self.subcategory = SubCategory.objects.create(
            main_category=self.category, name='Phones', slug='vb-phones',
        )

    # ------------------------------------------------------------------
    # factories
    # ------------------------------------------------------------------
    def make_vendor(self, key, sub_fields=None, verification_status='pending',
                    vbatch=False, vbatch_source='bvn'):
        user = CustomUser.objects.create_user(
            email=f'{key}@example.com',
            password='password123',
            username=key.replace('-', '_'),
            role='vendor',
        )
        vendor = user.vendorprofile
        vendor.verification_status = verification_status
        vendor.store_setup_completed = True
        if vbatch:
            vendor.has_vbatch = True
            vendor.vbatch_earned_at = NOW
            vendor.vbatch_source = vbatch_source
        vendor.save()

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
        if sub_fields:
            # QuerySet.update keeps the Premium signal out of the fixtures
            # that must start with no badge.
            Subscription.objects.filter(pk=subscription.pk).update(**sub_fields)

        # drop the "Store Created" / "Product Created" system notices
        mail.outbox.clear()
        Notification.objects.all().delete()

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
            description='A product for the phase eight tests',
            price='2500.00',
            status='published',
        )
        product.store = store
        return product

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------
    @staticmethod
    def sub_of(vendor):
        return Subscription.objects.get(vendor=vendor)

    @staticmethod
    def reload(vendor):
        return VendorProfile.objects.get(pk=vendor.pk)

    @staticmethod
    def content_of(response):
        return response.content.decode('utf-8')

    @staticmethod
    def bvn_awards(vendor):
        return Notification.objects.filter(
            user=vendor.user, title=VBATCH_TITLE,
        )

    @staticmethod
    def bvn_emails():
        return [m for m in mail.outbox if m.subject == VBATCH_TITLE]

    @staticmethod
    def suspend(vendor, status='suspended'):
        VendorProfile.objects.filter(pk=vendor.pk).update(
            verification_status=status,
        )
        return VendorProfile.objects.get(pk=vendor.pk)

    @staticmethod
    def run_backfill(*args):
        out = StringIO()
        call_command('backfill_vbatch', *args, stdout=out)
        return out.getvalue()

    @staticmethod
    def paystack_ok():
        """Paystack HTTP is irrelevant here - answer every call with success."""
        return patch.object(
            SubscriptionService, '_request',
            return_value={'status': True, 'data': {}},
        )

    @staticmethod
    def product_detail_url(store, product):
        return reverse('product_detail_public', kwargs={
            'store_slug': store.slug, 'product_slug': product.slug,
        })

    @staticmethod
    def store_url(store):
        return reverse('store_public', kwargs={'slug': store.slug})


# ==========================================================================
# 1. award_vbatch() itself
# ==========================================================================

class AwardVbatchTests(VbatchFixture):

    def test_first_call_awards_and_sets_every_field(self):
        vendor, _store, _product = self.make_vendor('aw-1')

        self.assertFalse(vendor.has_vbatch)
        self.assertTrue(award_vbatch(vendor, 'bvn'))

        vendor = self.reload(vendor)
        self.assertTrue(vendor.has_vbatch)
        self.assertEqual(vendor.vbatch_source, 'bvn')
        self.assertIsNotNone(vendor.vbatch_earned_at)

    def test_second_call_is_false_and_changes_nothing(self):
        vendor, _store, _product = self.make_vendor('aw-2')

        self.assertTrue(award_vbatch(vendor, 'bvn'))
        earned_at = self.reload(vendor).vbatch_earned_at

        self.assertFalse(award_vbatch(vendor, 'bvn'))
        again = self.reload(vendor)
        self.assertTrue(again.has_vbatch)
        self.assertEqual(again.vbatch_earned_at, earned_at)

    def test_a_different_second_source_never_overwrites(self):
        vendor, _store, _product = self.make_vendor('aw-3')

        self.assertTrue(award_vbatch(vendor, 'bvn'))
        earned_at = self.reload(vendor).vbatch_earned_at

        self.assertFalse(award_vbatch(vendor, 'premium'))
        self.assertFalse(award_vbatch(vendor, 'legacy'))

        after = self.reload(vendor)
        self.assertEqual(after.vbatch_source, 'bvn')
        self.assertEqual(after.vbatch_earned_at, earned_at)

    def test_losing_the_conditional_update_reports_false(self):
        """The row flipped underneath the in-memory instance: no double award."""
        vendor, _store, _product = self.make_vendor('aw-4')
        stale = self.reload(vendor)          # has_vbatch False in memory
        VendorProfile.objects.filter(pk=vendor.pk).update(
            has_vbatch=True,
            vbatch_earned_at=NOW,
            vbatch_source='bvn',
        )

        self.assertFalse(award_vbatch(stale, 'premium'))
        after = self.reload(vendor)
        self.assertEqual(after.vbatch_source, 'bvn')
        self.assertEqual(after.vbatch_earned_at, NOW)

    def test_unsaved_vendor_is_refused(self):
        vendor = VendorProfile(user=None)
        vendor.has_vbatch = False
        self.assertFalse(award_vbatch(vendor, 'bvn'))

    def test_award_never_writes_false(self):
        vendor, _store, _product = self.make_vendor('aw-6', vbatch=True)
        self.assertFalse(award_vbatch(vendor, 'premium'))
        self.assertTrue(self.reload(vendor).has_vbatch)


# ==========================================================================
# 2. Premium trigger
# ==========================================================================

class PremiumAwardTests(VbatchFixture):

    def test_activate_subscription_premium_awards(self):
        vendor, _store, _product = self.make_vendor('pre-1')
        sub = self.sub_of(vendor)

        with self.paystack_ok():
            changed = subscription_service.activate_subscription(
                sub, {'customer_code': 'cus_1', 'plan_code': 'PLN_premium'},
                plan='premium',
            )

        self.assertTrue(changed)
        vendor = self.reload(vendor)
        self.assertTrue(vendor.has_vbatch)
        self.assertEqual(vendor.vbatch_source, 'premium')
        self.assertEqual(self.bvn_awards(vendor).count(), 1)

    def test_basic_activation_does_not_award(self):
        vendor, _store, _product = self.make_vendor('pre-2')
        sub = self.sub_of(vendor)

        with self.paystack_ok():
            subscription_service.activate_subscription(
                sub, {'customer_code': 'cus_2', 'plan_code': 'PLN_basic'},
                plan='basic',
            )

        vendor = self.reload(vendor)
        self.assertEqual(vendor.vbatch_source, '')
        self.assertFalse(vendor.has_vbatch)

    def test_free_trial_row_never_awards(self):
        vendor, _store, _product = self.make_vendor(
            'pre-3', sub_fields=VALID_TRIAL,
        )
        self.assertFalse(self.reload(vendor).has_vbatch)

        sub = self.sub_of(vendor)
        sub.save()          # a plain save of a free row must not award
        self.assertFalse(self.reload(vendor).has_vbatch)

    def test_basic_to_premium_upgrade_awards(self):
        vendor, _store, _product = self.make_vendor('pre-4')
        sub = Subscription.objects.get(vendor=vendor)
        # start as an active Basic row (QuerySet.update -> no signal yet)
        Subscription.objects.filter(pk=sub.pk).update(
            status='active', plan='basic',
            period_end=NOW + timedelta(days=10),
        )
        sub.refresh_from_db()
        self.assertFalse(self.reload(vendor).has_vbatch)

        with self.paystack_ok():
            changed = subscription_service.upgrade_subscription(sub, {
                'customer_code': 'cus_4',
                'subscription_code': 'sub_prem_4',
                'plan_code': 'PLN_premium',
            })

        self.assertTrue(changed)
        vendor = self.reload(vendor)
        self.assertTrue(vendor.has_vbatch)
        self.assertEqual(vendor.vbatch_source, 'premium')

    def test_admin_edit_of_subscription_awards(self):
        """The stock admin change form writes through save()."""
        vendor, _store, _product = self.make_vendor('pre-5')
        sub = self.sub_of(vendor)

        sub.plan = 'premium'
        sub.status = 'active'
        sub.period_end = NOW + timedelta(days=30)
        sub.save()

        self.assertTrue(self.reload(vendor).has_vbatch)
        self.assertEqual(self.reload(vendor).vbatch_source, 'premium')

    def test_premium_row_saved_again_does_not_duplicate_notification(self):
        vendor, _store, _product = self.make_vendor('pre-6')
        sub = self.sub_of(vendor)

        with self.paystack_ok():
            subscription_service.activate_subscription(
                sub, {'customer_code': 'cus_6', 'plan_code': 'PLN_premium'},
                plan='premium',
            )
        first = self.bvn_awards(self.reload(vendor)).count()

        sub.refresh_from_db()
        sub.save()                       # recurring save on the same row
        self.assertEqual(self.bvn_awards(self.reload(vendor)).count(), first)

    def test_no_status_change_still_survives_every_downgrade_flow(self):
        vendor, _store, _product = self.make_vendor('pre-7')
        sub = self.sub_of(vendor)

        with self.paystack_ok():
            subscription_service.activate_subscription(
                sub, {'customer_code': 'cus_7', 'plan_code': 'PLN_premium'},
                plan='premium',
            )
        self.assertTrue(self.reload(vendor).has_vbatch)

        sub.refresh_from_db()
        subscription_service.downgrade_subscription(sub)     # -> basic pending
        self.assertTrue(self.reload(vendor).has_vbatch)

        sub.refresh_from_db()
        subscription_service.disable_subscription(sub)       # -> cancelled
        self.assertEqual(self.sub_of(vendor).status, 'cancelled')
        self.assertTrue(self.reload(vendor).has_vbatch)

        sub.refresh_from_db()
        subscription_service.handle_failed_payment(sub)      # -> past_due
        self.assertIn(
            self.sub_of(vendor).status, ('past_due', 'expired'),
        )
        self.assertTrue(self.reload(vendor).has_vbatch)

        # admin hard-reset of the row (QuerySet.update) also keeps it
        Subscription.objects.filter(pk=sub.pk).update(
            status='expired', plan='free', period_end=None,
        )
        self.assertTrue(self.reload(vendor).has_vbatch)

    def test_suspending_the_vendor_keeps_the_badge(self):
        vendor, _store, _product = self.make_vendor('pre-8', vbatch=True)
        self.suspend(vendor)
        self.assertTrue(self.reload(vendor).has_vbatch)

        VendorProfile.objects.filter(pk=vendor.pk).update(
            verification_status='rejected',
        )
        self.assertTrue(self.reload(vendor).has_vbatch)


# ==========================================================================
# 3. BVN trigger + the existing admin suspension toggle
# ==========================================================================

class BvnToggleTests(VbatchFixture):

    def run_bvn_flow(self, vendor):
        """Drive the real BVN+selfie executor with a mocked Dojah call."""
        from apps.vendors import views as vendor_views

        request = RequestFactory().post('/vendors/verification/bvn/selfie/')
        request.session = {}
        setattr(request, '_messages', FallbackStorage(request))

        payload = {
            'full_name': 'VB Test Vendor',
            'gender': 'male',
            'phone': '08000000000',
            'selfie_match': True,
            'selfie_confidence': 97.5,
            'selfie_image_url': '',
            'dateofbirth': '1990-01-01',
        }
        with patch.object(
            vendor_views.dojah_service, 'verify_bvn_with_selfie',
            return_value=(True, payload),
        ):
            vendor_views._process_bvn_with_selfie(
                request, vendor, '12345678901',
                'data:image/jpeg;base64,AAAA',
            )

    def test_toggle_on_bvn_success_awards(self):
        vendor, _store, _product = self.make_vendor('bvn-1')
        self.assertEqual(vendor.verification_status, 'pending')  # toggle ON

        self.run_bvn_flow(vendor)

        vendor = self.reload(vendor)
        self.assertEqual(vendor.bank_status, 'verified')
        self.assertTrue(vendor.has_vbatch)
        self.assertEqual(vendor.vbatch_source, 'bvn')

    def test_toggle_off_bvn_success_does_not_award(self):
        vendor, _store, _product = self.make_vendor('bvn-2')
        vendor = self.suspend(vendor)          # toggle OFF
        self.assertEqual(vendor.verification_status, 'suspended')

        self.run_bvn_flow(vendor)

        vendor = self.reload(vendor)
        self.assertEqual(vendor.bank_status, 'verified')   # flow unchanged
        self.assertFalse(vendor.has_vbatch)
        self.assertEqual(vendor.vbatch_source, '')

    def test_turning_the_toggle_off_after_an_award_keeps_the_badge(self):
        vendor, _store, _product = self.make_vendor('bvn-3')

        self.run_bvn_flow(vendor)
        self.assertTrue(self.reload(vendor).has_vbatch)

        self.suspend(vendor)                  # toggle switched off later
        self.assertTrue(self.reload(vendor).has_vbatch)
        self.assertEqual(self.reload(vendor).vbatch_source, 'bvn')

    def test_toggle_reader_semantics(self):
        from apps.vendors.vbatch import _bvn_toggle_is_on

        vendor, _store, _product = self.make_vendor('bvn-4')
        self.assertTrue(_bvn_toggle_is_on(vendor))           # ON  = not suspended
        self.suspend(vendor)
        vendor = self.reload(vendor)
        self.assertFalse(_bvn_toggle_is_on(vendor))          # OFF = suspended

    def test_awarding_when_the_toggle_is_off_is_a_no_op_even_if_called(self):
        vendor, _store, _product = self.make_vendor('bvn-5')
        vendor = self.suspend(vendor)
        self.assertFalse(award_vbatch(vendor, 'bvn'))


# ==========================================================================
# 4. Nothing in the repo can remove V-Batch
# ==========================================================================

class NeverRemovedTests(VbatchFixture):

    CLEARING = re.compile(r'has_vbatch\s*=\s*False')

    def test_no_production_code_clears_the_flag(self):
        root = Path(settings.BASE_DIR)
        offenders = []
        for path in root.rglob('*.py'):
            text = str(path)
            if any(skip in text for skip in (
                'venv', 'staticfiles', '__pycache__', '.git',
            )):
                continue
            if 'tests' in path.parts:          # never match this file itself
                continue
            try:
                source = path.read_text(encoding='utf-8')
            except OSError:                     # pragma: no cover
                continue
            for lineno, line in enumerate(source.splitlines(), 1):
                if self.CLEARING.search(line) and 'default=False' not in line:
                    offenders.append(f'{path}:{lineno}: {line.strip()}')

        self.assertEqual(
            offenders, [],
            'V-Batch must be removable only by a manual admin edit:\n'
            + '\n'.join(offenders),
        )

    def test_grep_finds_the_field_it_is_checking_for(self):
        """Guard against a silently broken pattern (self-check)."""
        self.assertTrue(self.CLEARING.search('x.has_vbatch = False'))
        self.assertTrue(self.CLEARING.search('has_vbatch=False'))
        self.assertFalse(self.CLEARING.search('has_vbatch=True'))
        self.assertFalse(self.CLEARING.search('default=False'))

    def test_every_removal_flows_known_to_the_repo_keep_the_badge(self):
        vendor, _store, _product = self.make_vendor('keep-1')
        sub = self.sub_of(vendor)

        with self.paystack_ok():
            subscription_service.activate_subscription(
                sub, {'customer_code': 'cus_k', 'plan_code': 'PLN_premium'},
                plan='premium',
            )
        self.assertTrue(self.reload(vendor).has_vbatch)

        # (a) cancellation + expiry via the service
        sub.refresh_from_db()
        subscription_service.disable_subscription(sub)
        sub.refresh_from_db()
        subscription_service.handle_failed_payment(sub)
        self.assertTrue(self.reload(vendor).has_vbatch)

        # (b) grace-period expiry (QuerySet.update)
        Subscription.objects.filter(pk=sub.pk).update(
            status='past_due', grace_ends_at=NOW - timedelta(days=1),
        )
        subscription_service.expire_grace_periods()
        self.assertEqual(self.sub_of(vendor).status, 'expired')
        self.assertTrue(self.reload(vendor).has_vbatch)

        # (c) admin reject / suspend (both write verification_status)
        VendorProfile.objects.filter(pk=vendor.pk).update(
            verification_status='rejected',
        )
        self.assertTrue(self.reload(vendor).has_vbatch)
        self.suspend(vendor)
        self.assertTrue(self.reload(vendor).has_vbatch)

        # (d) admin restart of the qualification window (admin action POST)
        self.client.force_login(
            CustomUser.objects.create_superuser(
                email='vb-admin@example.com', password='password123',
            )
        )
        response = self.client.post(
            reverse('admin:vendors_subscription_changelist'),
            {
                'action': 'restart_qualification_window',
                '_selected_action': [str(sub.pk)],
            },
            follow=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(self.reload(vendor).has_vbatch)

        # (e) direct model save with the flag untouched
        vendor = self.reload(vendor)
        vendor.admin_comment = 'checked'
        vendor.save()
        self.assertTrue(self.reload(vendor).has_vbatch)


# ==========================================================================
# 5. Notification
# ==========================================================================

class VbatchNotificationTests(VbatchFixture):

    def test_first_award_sends_one_in_app_and_one_email(self):
        vendor, _store, _product = self.make_vendor('ntf-1')
        mail.outbox.clear()

        self.assertTrue(award_vbatch(vendor, 'bvn'))

        notifs = self.bvn_awards(vendor)
        self.assertEqual(notifs.count(), 1)
        notif = notifs.get()
        self.assertEqual(notif.title, VBATCH_TITLE)
        self.assertEqual(notif.message, VBATCH_MESSAGE)
        self.assertEqual(notif.channel, 'both')
        self.assertEqual(notif.link, '/vendors/dashboard/')
        self.assertEqual(notif.notification_type, 'verification')

        self.assertEqual(len(self.bvn_emails()), 1)
        self.assertEqual(self.bvn_emails()[0].subject, VBATCH_TITLE)

    def test_repeat_awards_send_nothing_more(self):
        vendor, _store, _product = self.make_vendor('ntf-2')

        self.assertTrue(award_vbatch(vendor, 'bvn'))
        self.assertFalse(award_vbatch(vendor, 'premium'))
        self.assertFalse(award_vbatch(vendor, 'legacy'))

        self.assertEqual(self.bvn_awards(vendor).count(), 1)
        self.assertEqual(len(self.bvn_emails()), 1)

    def test_premium_activation_uses_the_same_single_notification(self):
        vendor, _store, _product = self.make_vendor('ntf-3')
        sub = self.sub_of(vendor)

        with self.paystack_ok():
            subscription_service.activate_subscription(
                sub, {'customer_code': 'cus_n', 'plan_code': 'PLN_premium'},
                plan='premium',
            )

        self.assertEqual(self.bvn_awards(vendor).count(), 1)
        self.assertEqual(len(self.bvn_emails()), 1)

    def test_backfill_is_silent(self):
        self.make_vendor('ntf-4', sub_fields=ACTIVE_PREMIUM)
        mail.outbox.clear()

        self.run_backfill('--apply')

        self.assertEqual(
            Notification.objects.filter(title=VBATCH_TITLE).count(), 0,
        )
        self.assertEqual(len(self.bvn_emails()), 0)


# ==========================================================================
# 6. Backfill
# ==========================================================================

class BackfillTests(VbatchFixture):

    def make_batch(self):
        premium, _s, _p = self.make_vendor(
            'bf-premium', sub_fields=ACTIVE_PREMIUM,
        )
        bvn, _s, _p = self.make_vendor('bf-bvn')
        VendorProfile.objects.filter(pk=bvn.pk).update(
            bank_status='verified', bvn_verified_at=NOW,
        )
        both, _s, _p = self.make_vendor(
            'bf-both', sub_fields=ACTIVE_PREMIUM,
        )
        VendorProfile.objects.filter(pk=both.pk).update(
            bank_status='verified', bvn_verified_at=NOW,
        )
        neither, _s, _p = self.make_vendor('bf-neither', sub_fields=VALID_TRIAL)
        return {
            'premium': self.reload(premium),
            'bvn': self.reload(bvn),
            'both': self.reload(both),
            'neither': self.reload(neither),
        }

    def test_dry_run_writes_nothing(self):
        vendors = self.make_batch()

        output = self.run_backfill()

        self.assertIn('DRY RUN', output)
        self.assertIn("rule 1", output)
        self.assertIn("rule 2", output)
        for vendor in vendors.values():
            self.assertFalse(self.reload(vendor).has_vbatch)

    def test_apply_awards_the_right_vendors_with_the_right_sources(self):
        vendors = self.make_batch()

        output = self.run_backfill('--apply')

        self.assertIn('APPLY', output)
        premium = self.reload(vendors['premium'])
        bvn = self.reload(vendors['bvn'])
        both = self.reload(vendors['both'])
        neither = self.reload(vendors['neither'])

        self.assertTrue(premium.has_vbatch)
        self.assertEqual(premium.vbatch_source, 'premium')

        self.assertTrue(bvn.has_vbatch)
        self.assertEqual(bvn.vbatch_source, 'legacy')

        self.assertTrue(both.has_vbatch)
        self.assertEqual(both.vbatch_source, 'premium')   # rule 1 wins

        self.assertFalse(neither.has_vbatch)
        self.assertEqual(neither.vbatch_source, '')

    def test_apply_prints_counts_per_rule(self):
        self.make_batch()
        output = self.run_backfill('--apply')
        self.assertIn('active Premium plan', output)
        self.assertIn('BVN verified on record', output)
        self.assertIn('Done - awarded 3, already earned 0.', output)

    def test_second_run_is_a_no_op(self):
        vendors = self.make_batch()
        self.run_backfill('--apply')

        first = {
            key: (self.reload(v).has_vbatch, self.reload(v).vbatch_source,
                  self.reload(v).vbatch_earned_at)
            for key, v in vendors.items()
        }

        output = self.run_backfill('--apply')

        self.assertIn('Done - awarded 0, already earned 3.', output)
        second = {
            key: (self.reload(v).has_vbatch, self.reload(v).vbatch_source,
                  self.reload(v).vbatch_earned_at)
            for key, v in vendors.items()
        }
        self.assertEqual(first, second)

    def test_apply_writes_without_touching_anything_else(self):
        vendors = self.make_batch()
        before = {
            key: (v.verification_status, v.bank_status)
            for key, v in vendors.items()
        }
        self.run_backfill('--apply')
        after = {
            key: (self.reload(v).verification_status,
                  self.reload(v).bank_status)
            for key, v in vendors.items()
        }
        self.assertEqual(before, after)


# ==========================================================================
# 7. Display
# ==========================================================================

class DisplayTests(VbatchFixture):

    def test_product_card_shows_the_badge_only_for_vbatch(self):
        vendor, store, _product = self.make_vendor('dis-1', vbatch=True)
        body = self.content_of(self.client.get(reverse('marketplace:product_list')))
        self.assertIn('aria-label="V-Batch"', body)

        VendorProfile.objects.filter(pk=vendor.pk).update(has_vbatch=False)
        body = self.content_of(self.client.get(reverse('marketplace:product_list')))
        self.assertNotIn('aria-label="V-Batch"', body)
        self.assertNotIn('is_verified', body)

    def test_product_detail_shows_the_badge_only_for_vbatch(self):
        vendor, store, product = self.make_vendor('dis-2', vbatch=True)

        body = self.content_of(self.client.get(self.product_detail_url(store, product)))
        self.assertIn('V-Batch', body)

        VendorProfile.objects.filter(pk=vendor.pk).update(has_vbatch=False)
        body = self.content_of(self.client.get(self.product_detail_url(store, product)))
        self.assertNotIn('V-Batch', body)

    def test_storefront_shows_the_badge_only_for_vbatch(self):
        vendor, store, _product = self.make_vendor('dis-3', vbatch=True)

        body = self.content_of(self.client.get(self.store_url(store)))
        self.assertIn('V-Batch', body)

        VendorProfile.objects.filter(pk=vendor.pk).update(has_vbatch=False)
        body = self.content_of(self.client.get(self.store_url(store)))
        self.assertNotIn('V-Batch', body)

    def test_storefront_product_card_shows_the_badge_only_for_vbatch(self):
        vendor, store, _product = self.make_vendor('dis-4', vbatch=True)

        body = self.content_of(self.client.get(self.store_url(store)))
        self.assertIn('aria-label="V-Batch"', body)

        VendorProfile.objects.filter(pk=vendor.pk).update(has_vbatch=False)
        body = self.content_of(self.client.get(self.store_url(store)))
        self.assertNotIn('aria-label="V-Batch"', body)

    def test_restricted_vbatch_vendor_still_shows_the_badge(self):
        vendor, store, product = self.make_vendor(
            'dis-5', vbatch=True, sub_fields=EXPIRED_TRIAL,
        )

        body = self.content_of(self.client.get(self.product_detail_url(store, product)))
        self.assertIn('V-Batch', body)
        self.assertIn('Vendor Unavailable', body)     # restriction unchanged

        body = self.content_of(self.client.get(self.store_url(store)))
        self.assertIn('V-Batch', body)

    def test_old_condition_is_gone_from_the_badge_templates(self):
        root = Path(settings.BASE_DIR)
        needles = {
            root / 'apps/marketplace/templates/marketplace/partials/product_card.html',
            root / 'apps/vendors/templates/vendors/store/partials/storefront_product_card.html',
            root / 'apps/vendors/templates/vendors/store/public_storefront.html',
            root / 'apps/vendors/templates/products/product_detail.html',
        }
        for path in needles:
            source = path.read_text(encoding='utf-8')
            self.assertNotIn(
                'vendor.is_verified', source,
                f'{path.name} still gates the badge on is_verified',
            )
            self.assertIn('vendor.has_vbatch', source)

    def test_verification_center_line_not_earned(self):
        vendor, _store, _product = self.make_vendor('dis-7')
        self.client.force_login(vendor.user)

        body = self.content_of(self.client.get(reverse('vendors:verification_center')))
        self.assertIn('V-Batch: Not earned', body)
        self.assertNotIn('V-Batch: Earned on', body)

    def test_verification_center_line_earned(self):
        vendor, _store, _product = self.make_vendor('dis-8')
        self.client.force_login(vendor.user)
        award_vbatch(vendor, 'premium')

        body = self.content_of(self.client.get(reverse('vendors:verification_center')))
        earned_on = self.reload(vendor).vbatch_earned_at.strftime('%b %d, %Y')
        self.assertIn(f'V-Batch: Earned on {earned_on} via Premium plan', body)

    def test_verification_center_line_uses_the_shared_date_format(self):
        from apps.vendors.subscription_state import DATE_FORMAT

        self.assertEqual(DATE_FORMAT, '%b %d, %Y')
        vendor, _store, _product = self.make_vendor('dis-9')
        self.client.force_login(vendor.user)
        award_vbatch(vendor, 'bvn')

        body = self.content_of(self.client.get(reverse('vendors:verification_center')))
        earned_on = self.reload(vendor).vbatch_earned_at.strftime(DATE_FORMAT)
        self.assertIn(f'V-Batch: Earned on {earned_on} via BVN verification', body)


# ==========================================================================
# 8. Independence
# ==========================================================================

class IndependenceTests(VbatchFixture):

    def test_vbatch_vendor_with_expired_trial_is_still_restricted(self):
        vendor, store, product = self.make_vendor(
            'ind-1', vbatch=True, sub_fields=EXPIRED_TRIAL,
        )

        body = self.content_of(self.client.get(self.product_detail_url(store, product)))
        self.assertIn('Vendor Unavailable', body)
        for leak in ('wa.me', 'tel:', PHONE, WHATSAPP):
            self.assertNotIn(leak, body)
        self.assertFalse(vendor.can_sell)

        body = self.content_of(self.client.get(reverse('marketplace:product_list')))
        self.assertIn('Vendor Unavailable', body)

    def test_vbatch_changes_no_visibility_or_qualification_state(self):
        vendor, store, product = self.make_vendor(
            'ind-2', vbatch=True, sub_fields=VALID_TRIAL,
        )
        sub = self.sub_of(vendor)

        self.assertTrue(vendor.can_sell)
        self.assertEqual(sub.status, 'trial')
        self.assertEqual(sub.plan, 'free')
        self.assertEqual(vendor.verification_status, 'pending')

        # awarding later must not move any of those
        award_vbatch(vendor, 'bvn')
        vendor = self.reload(vendor)
        sub = self.sub_of(vendor)
        self.assertTrue(vendor.can_sell)
        self.assertEqual(sub.status, 'trial')
        self.assertEqual(sub.plan, 'free')
        self.assertEqual(vendor.verification_status, 'pending')

    def test_unverified_non_vbatch_vendor_with_active_subscription_sells(self):
        vendor, store, product = self.make_vendor(
            'ind-3', sub_fields=ACTIVE_BASIC,
        )
        self.assertFalse(vendor.has_vbatch)
        self.assertNotEqual(vendor.verification_status, 'approved')
        self.assertTrue(vendor.can_sell)

        body = self.content_of(self.client.get(self.product_detail_url(store, product)))
        self.assertIn('wa.me', body)
        self.assertNotIn('Vendor Unavailable', body)
        self.assertNotIn('V-Batch', body)

    def test_contact_intent_still_works_for_a_vbatch_vendor(self):
        vendor, store, product = self.make_vendor(
            'ind-4', vbatch=True, sub_fields=VALID_TRIAL,
        )
        buyer = CustomUser.objects.create_user(
            email='ind-4-buyer@example.com',
            password='password123',
            username='ind_4_buyer',
        )
        ContactIntent.objects.create(
            user=buyer, vendor=vendor, product=product, channel='whatsapp',
        )
        self.assertEqual(ContactIntent.objects.count(), 1)
        self.assertTrue(self.reload(vendor).can_sell)


# ==========================================================================
# 9. Public page query counts
# ==========================================================================

class QueryCountTests(VbatchFixture):

    def queries_for(self, url, **data):
        with CaptureQueriesContext(connection) as ctx:
            response = self.client.get(url, data)
        self.assertEqual(response.status_code, 200)
        return len(ctx.captured_queries)

    def test_badge_costs_no_extra_query_on_public_pages(self):
        vendor, store, product = self.make_vendor('q-1', vbatch=True)
        detail = self.product_detail_url(store, product)

        pages = [
            ('product list', reverse('marketplace:product_list'), {}),
            ('product detail', detail, {}),
            ('store page', self.store_url(store), {}),
            ('search', reverse('marketplace:search'), {'q': product.title}),
        ]

        report = []
        for label, url, data in pages:
            self.client.get(url, data)          # warm one-off caches first
            on = self.queries_for(url, **data)
            VendorProfile.objects.filter(pk=vendor.pk).update(has_vbatch=False)
            off = self.queries_for(url, **data)
            VendorProfile.objects.filter(pk=vendor.pk).update(has_vbatch=True)
            report.append(f'{label}: flag on={on} off={off}')
            self.assertEqual(
                on, off,
                f'{label}: the V-Batch flag changed the query count',
            )

        print('QUERY COUNTS: ' + '; '.join(report))

    def test_the_old_condition_and_the_new_one_cost_the_same(self):
        """
        Before Phase 8 the badge was gated on is_verified, a property that
        reads verification_status off the VendorProfile row the page already
        loads.  Rendering the badge from that row and from has_vbatch must
        therefore issue an identical number of queries.
        """
        vendor, store, product = self.make_vendor('q-2')
        detail = self.product_detail_url(store, product)
        self.client.get(detail)                # warm one-off caches first

        # "before": old condition true (approved), new flag false
        VendorProfile.objects.filter(pk=vendor.pk).update(
            verification_status='approved', has_vbatch=False,
        )
        before = self.queries_for(detail)

        # "after": old condition false, new flag true
        VendorProfile.objects.filter(pk=vendor.pk).update(
            verification_status='pending', has_vbatch=True,
        )
        after = self.queries_for(detail)

        print(f'QUERY COUNTS: product detail before={before} after={after}')
        self.assertEqual(before, after)


# ==========================================================================
# 10. Admin exposure
# ==========================================================================

class AdminExposureTests(VbatchFixture):

    def test_admin_exposes_the_three_fields(self):
        model_admin = django_admin.site._registry[VendorProfile]

        self.assertIn('has_vbatch', model_admin.list_display)
        self.assertIn('has_vbatch', model_admin.list_filter)

        fields = []
        for _title, opts in model_admin.fieldsets:
            fields.extend(opts.get('fields', ()))
        for name in ('has_vbatch', 'vbatch_earned_at', 'vbatch_source'):
            self.assertIn(name, fields)
            self.assertNotIn(
                name, model_admin.readonly_fields,
                f'{name} must stay editable by a superuser',
            )

    def test_admin_can_clear_the_badge_manually(self):
        """The only removal path: a manual admin edit."""
        vendor, _store, _product = self.make_vendor('adm-1', vbatch=True)
        self.assertFalse(award_vbatch(vendor, 'bvn'))   # already earned

        VendorProfile.objects.filter(pk=vendor.pk).update(
            has_vbatch=False, vbatch_earned_at=None, vbatch_source='',
        )
        vendor = self.reload(vendor)
        self.assertFalse(vendor.has_vbatch)
        self.assertIsNone(vendor.vbatch_earned_at)
        self.assertEqual(vendor.vbatch_source, '')

        # and awarding again works, recording the new source
        self.assertTrue(award_vbatch(vendor, 'admin'))
        self.assertEqual(self.reload(vendor).vbatch_source, 'admin')


# ==========================================================================
# 11. Data model
# ==========================================================================

class ModelShapeTests(VbatchFixture):

    def test_defaults(self):
        vendor, _store, _product = self.make_vendor('mdl-1')
        self.assertFalse(vendor.has_vbatch)
        self.assertIsNone(vendor.vbatch_earned_at)
        self.assertEqual(vendor.vbatch_source, '')

    def test_source_choices(self):
        choices = dict(VendorProfile.VBATCH_SOURCE_CHOICES)
        self.assertEqual(
            set(choices), {'bvn', 'premium', 'admin', 'legacy'},
        )

    def test_the_only_new_migration_is_the_vbatch_one(self):
        from django.db.migrations.loader import MigrationLoader

        loader = MigrationLoader(connection)
        leafs = loader.graph.leaf_nodes('vendors')
        self.assertEqual(
            [node[1] for node in leafs], ['0036_add_vbatch_fields'],
        )
