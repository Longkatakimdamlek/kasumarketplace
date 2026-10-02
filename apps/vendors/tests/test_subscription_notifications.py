"""
Phase 7 - Subscription / qualification notifications + daily cron
=================================================================

Fixed clock, locmem email outbox.

Covers the six kinds (exact title / message / link / email), the
(subscription, kind, cycle_key) dedupe, the 7-day trial warning window,
suppression (active paid, admin-suspended), the expiry lookback, failure
isolation, --dry-run / --no-notify, a silent backfill_subscriptions
--apply, the admin restart action, regression coverage for the existing
payment-failed / renewed notifications, and the bounded query count of the
command loop.

No existing test is modified.
"""

from datetime import datetime, timedelta
from io import StringIO
from unittest.mock import patch

from django.conf import settings
from django.contrib import admin as django_admin
from django.contrib.auth import get_user_model
from django.core import mail
from django.core.management import call_command
from django.db import IntegrityError, connection, transaction
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from apps.vendors.models import (
    MainCategory,
    Notification,
    Product,
    Store,
    SubCategory,
    Subscription,
    SubscriptionNotificationLog,
    VendorProfile,
)
from apps.vendors.services import notification_dispatch
from apps.vendors.subscription_state import RESTRICTED_MESSAGE
from apps.users.models import CustomUser

DAY = timedelta(days=1)
PLANS_LINK = reverse('vendors:subscription_plans')

# Fixed clock used by the day-window tests.
FIXED_NOW = timezone.make_aware(datetime(2026, 6, 15, 12, 0))


def fmt_date(value):
    """Same rendering as subscription_state.DATE_FORMAT ('%b %d, %Y')."""
    if hasattr(value, 'date'):
        value = value.date()
    return value.strftime('%b %d, %Y')


class SubscriptionNotificationFixture(TestCase):

    def setUp(self):
        self.category = MainCategory.objects.create(name='Watches', slug='watches-p7')
        self.subcategory = SubCategory.objects.create(
            main_category=self.category, name='Digital', slug='digital-p7',
        )

    # ------------------------------------------------------------------
    # factories (same shape as the Phase 5 fixture)
    # ------------------------------------------------------------------
    def make_vendor(self, key, store_published=True):
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
            is_published=store_published,
        )
        # store creation already emails a "Store Created" system notice;
        # drop it so every test starts from an empty outbox.
        mail.outbox.clear()
        return VendorProfile.objects.get(pk=vendor.pk)

    def make_product(self, vendor, store, n, status='draft'):
        return Product.objects.create(
            vendor=vendor,
            store=store,
            subcategory=self.subcategory,
            title=f'{vendor.pk} product {n}',
            slug=f'p7-{vendor.pk}-{n}',
            description='A product for notification tests',
            price='1500.00',
            status=status,
        )

    @staticmethod
    def store_of(vendor):
        return Store.objects.get(vendor=vendor)

    @staticmethod
    def sub_of(vendor):
        return Subscription.objects.get(vendor=vendor)

    @staticmethod
    def update_sub(vendor, **fields):
        Subscription.objects.filter(vendor=vendor).update(**fields)
        return Subscription.objects.get(vendor=vendor)

    @staticmethod
    def suspend(vendor):
        VendorProfile.objects.filter(pk=vendor.pk).update(
            verification_status='suspended',
        )
        return VendorProfile.objects.get(pk=vendor.pk)

    @staticmethod
    def run_command(*args, **kwargs):
        out = StringIO()
        call_command('check_subscription_status', *args, stdout=out, **kwargs)
        return out.getvalue()

    # ------------------------------------------------------------------
    # assertions
    # ------------------------------------------------------------------
    def notifications_for(self, vendor, title=None):
        # only this phase's kinds: other signals create system notices too
        qs = Notification.objects.filter(
            user=vendor.user, notification_type='subscription',
        )
        if title:
            qs = qs.filter(title=title)
        return qs

    @staticmethod
    def emails_with_subject(title):
        return [m for m in mail.outbox if m.subject == title]

    @staticmethod
    def subscription_notifications():
        return Notification.objects.filter(notification_type='subscription')

    def assert_notified(self, vendor, title, message, emails=1):
        notif = Notification.objects.get(
            user=vendor.user, notification_type='subscription', title=title,
        )
        self.assertEqual(notif.message, message)
        self.assertEqual(notif.link, PLANS_LINK)
        self.assertEqual(notif.channel, 'both')
        self.assertIsNotNone(notif.email_sent_at)
        self.assertEqual(notif.vendor_id, vendor.pk)

        matching = self.emails_with_subject(title)
        self.assertEqual(len(matching), emails, f'{len(matching)} emails for {title}')
        email = matching[-1]
        self.assertEqual(email.to, [vendor.user.email])
        self.assertIn(message, email.body)
        html = email.alternatives[0][0]
        self.assertIn(f'{settings.SITE_URL}{PLANS_LINK}', html)
        return notif

    def assert_not_notified(self, vendor, title):
        self.assertFalse(
            self.notifications_for(vendor, title).exists(),
            f'{vendor.user.email} must not receive {title}',
        )


# =========================================================================
# Kind 1 - trial_unlocked (synchronous at qualifying -> trial)
# =========================================================================

class TrialUnlockedTests(SubscriptionNotificationFixture):

    def test_fires_on_third_published_product_with_exact_copy(self):
        vendor = self.make_vendor('k1-third')
        store = self.store_of(vendor)
        self.make_product(vendor, store, 1, status='published')
        self.make_product(vendor, store, 2, status='published')
        self.assertEqual(self.notifications_for(vendor).count(), 0)

        self.make_product(vendor, store, 3, status='published')

        sub = self.sub_of(vendor)
        self.assertEqual(sub.status, 'trial')
        expected = (
            'You published 3 products. Your 3-month free trial is active '
            f'until {fmt_date(sub.trial_ends_at)}.'
        )
        self.assert_notified(vendor, 'Free trial unlocked', expected)
        self.assertEqual(SubscriptionNotificationLog.objects.filter(
            kind='trial_unlocked', subscription=sub,
        ).count(), 1)

    def test_drafts_do_not_fire_and_fourth_product_does_not_refire(self):
        # drafts only
        draft_vendor = self.make_vendor('k1-drafts')
        draft_store = self.store_of(draft_vendor)
        for n in (1, 2, 3):
            self.make_product(draft_vendor, draft_store, n, status='draft')
        self.assertEqual(self.notifications_for(draft_vendor).count(), 0)
        self.assertEqual(self.sub_of(draft_vendor).status, 'qualifying')

        # two published + one draft
        mixed_vendor = self.make_vendor('k1-mixed')
        mixed_store = self.store_of(mixed_vendor)
        self.make_product(mixed_vendor, mixed_store, 1, status='published')
        self.make_product(mixed_vendor, mixed_store, 2, status='published')
        self.make_product(mixed_vendor, mixed_store, 3, status='draft')
        self.assertEqual(self.notifications_for(mixed_vendor).count(), 0)

        # third published product, then a fourth
        vendor = self.make_vendor('k1-fourth')
        store = self.store_of(vendor)
        for n in (1, 2, 3, 4):
            self.make_product(vendor, store, n, status='published')
        self.assertEqual(self.notifications_for(vendor).count(), 1)
        self.assertEqual(SubscriptionNotificationLog.objects.filter(
            kind='trial_unlocked',
        ).count(), 1)

    def test_qualified_vendor_survives_a_restart_on_the_same_cycle(self):
        vendor = self.make_vendor('k1-restart')
        store = self.store_of(vendor)
        for n in (1, 2, 3):
            self.make_product(vendor, store, n, status='published')
        self.assertEqual(self.notifications_for(vendor).count(), 1)

        from apps.vendors.qualification import evaluate_qualification
        sub = self.sub_of(vendor)
        sub.status = 'qualifying'
        sub.qualification_status = 'in_progress'
        sub.trial_ends_at = None
        sub.save(update_fields=['status', 'qualification_status', 'trial_ends_at'])

        self.assertTrue(evaluate_qualification(sub))
        self.assertEqual(self.notifications_for(vendor).count(), 1)


# =========================================================================
# Kinds 2-6 - the daily command
# =========================================================================

class DailyCronKindTests(SubscriptionNotificationFixture):

    def test_kind2_qualification_grace(self):
        vendor = self.make_vendor('k2-grace')
        store = self.store_of(vendor)
        self.make_product(vendor, store, 1, status='published')
        Subscription.objects.filter(vendor=vendor).update(
            first_product_at=timezone.now() - timedelta(days=8),
            qualification_status='in_progress',
        )
        sub = self.sub_of(vendor)
        self.assertEqual(sub.qualification_days_left, 6)

        self.run_command()

        expected = (
            'You have published 1 of 3 products. You have 6 more day(s) to '
            'publish 2 more product(s). After that, buyers will see Vendor '
            'Unavailable and you will not be able to add products until you '
            'subscribe.'
        )
        self.assert_notified(vendor, 'Grace period started', expected)
        self.assert_not_notified(vendor, 'Free trial not unlocked')

    def test_kind3_qualification_failed(self):
        vendor = self.make_vendor('k3-failed')
        store = self.store_of(vendor)
        self.make_product(vendor, store, 1, status='published')
        Subscription.objects.filter(vendor=vendor).update(
            first_product_at=timezone.now() - timedelta(days=15),
            qualification_status='in_progress',
        )

        self.run_command()

        sub = self.sub_of(vendor)
        self.assertEqual(sub.status, 'expired')
        self.assertEqual(sub.qualification_status, 'failed')
        expected = (
            'You did not publish 3 products within 14 days of your first '
            f'product. {RESTRICTED_MESSAGE}'
        )
        self.assert_notified(vendor, 'Free trial not unlocked', expected)

    def test_kind4_trial_ending_soon(self):
        vendor = self.make_vendor('k4-ending')
        self.update_sub(
            vendor,
            status='trial',
            qualification_status='qualified',
            trial_ends_at=timezone.now() + timedelta(days=5),
        )
        sub = self.sub_of(vendor)

        self.run_command()

        expected_title = 'Your free trial ends in 5 day(s)'
        expected = (
            f'Your free trial ends on {fmt_date(sub.trial_ends_at)}. '
            'Choose a plan to keep your store available to buyers.'
        )
        self.assert_notified(vendor, expected_title, expected)

    def test_kind5_trial_ended(self):
        vendor = self.make_vendor('k5-ended')
        self.update_sub(
            vendor,
            status='trial',
            qualification_status='qualified',
            trial_ends_at=timezone.now() - timedelta(days=1),
        )

        self.run_command()

        self.assert_notified(vendor, 'Free trial ended', RESTRICTED_MESSAGE)

    def test_kind6_subscription_expired(self):
        vendor = self.make_vendor('k6-expired')
        self.update_sub(
            vendor,
            status='expired',
            plan='basic',
            qualification_status='skipped',
            trial_ends_at=None,
            period_end=timezone.now() - timedelta(days=1),
            grace_ends_at=None,
        )

        self.run_command()

        self.assert_notified(vendor, 'Subscription expired', RESTRICTED_MESSAGE)

    def test_summary_line_reports_processed_sent_and_skipped(self):
        vendor = self.make_vendor('k-sum')
        self.update_sub(
            vendor,
            status='trial',
            qualification_status='qualified',
            trial_ends_at=timezone.now() + timedelta(days=5),
        )

        output = self.run_command()

        self.assertIn('summary: processed 1', output)
        self.assertIn('trial_ending_soon=1', output)
        self.assertIn('errors: 0', output)
        # ASCII only on stdout
        self.assertNotIn('\u2705', output)


# =========================================================================
# Dedupe
# =========================================================================

class DedupeTests(SubscriptionNotificationFixture):

    def test_running_the_command_twice_sends_once(self):
        vendor = self.make_vendor('dedupe-twice')
        self.update_sub(
            vendor,
            status='trial',
            qualification_status='qualified',
            trial_ends_at=timezone.now() - timedelta(days=1),
        )

        self.run_command()
        self.run_command()

        self.assertEqual(self.notifications_for(vendor).count(), 1)
        self.assertEqual(SubscriptionNotificationLog.objects.filter(
            kind='trial_ended',
        ).count(), 1)

    def test_a_new_cycle_sends_again(self):
        vendor = self.make_vendor('dedupe-cycle')
        self.update_sub(
            vendor,
            status='trial',
            qualification_status='qualified',
            trial_ends_at=timezone.now() - timedelta(days=1),
        )
        self.run_command()
        self.assertEqual(self.notifications_for(vendor).count(), 1)

        # a different trial_ends_at date is a different cycle
        self.update_sub(vendor, trial_ends_at=timezone.now() - timedelta(days=2))
        self.run_command()

        self.assertEqual(self.notifications_for(vendor).count(), 2)
        self.assertEqual(SubscriptionNotificationLog.objects.filter(
            kind='trial_ended',
        ).count(), 2)

    def test_concurrent_claim_writes_a_single_row(self):
        vendor = self.make_vendor('dedupe-race')
        sub = self.sub_of(vendor)
        SubscriptionNotificationLog.objects.create(
            subscription=sub, kind='trial_ended', cycle_key='2026-06-15',
        )
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                SubscriptionNotificationLog.objects.create(
                    subscription=sub, kind='trial_ended', cycle_key='2026-06-15',
                )
        self.assertEqual(SubscriptionNotificationLog.objects.filter(
            subscription=sub, kind='trial_ended',
        ).count(), 1)


# =========================================================================
# 7-day trial warning window
# =========================================================================

class TrialEndingWindowTests(SubscriptionNotificationFixture):

    def trial_vendor(self, key, trial_ends_at):
        vendor = self.make_vendor(key)
        self.update_sub(
            vendor,
            status='trial',
            qualification_status='qualified',
            trial_ends_at=trial_ends_at,
        )
        return vendor

    def test_day_8_is_too_early(self):
        vendor = self.trial_vendor('win-day8', FIXED_NOW + timedelta(days=8))
        with patch('django.utils.timezone.now', return_value=FIXED_NOW):
            self.run_command()
        self.assertEqual(self.notifications_for(vendor).count(), 0)

    def test_day_7_and_day_3_send_once(self):
        vendor = self.trial_vendor('win-day7', FIXED_NOW + timedelta(days=7))

        with patch('django.utils.timezone.now', return_value=FIXED_NOW):
            self.run_command()
        self.assertEqual(
            self.notifications_for(vendor, 'Your free trial ends in 7 day(s)').count(),
            1,
        )

        # 4 days later the trial ends in 3 days: same cycle, no second send
        with patch(
            'django.utils.timezone.now',
            return_value=FIXED_NOW + timedelta(days=4),
        ):
            self.run_command()
        self.assertEqual(self.notifications_for(vendor).count(), 1)
        self.assertFalse(
            self.notifications_for(vendor, 'Your free trial ends in 3 day(s)').exists(),
        )

    def test_day_3_alone_sends(self):
        vendor = self.trial_vendor('win-day3', FIXED_NOW + timedelta(days=3))
        with patch('django.utils.timezone.now', return_value=FIXED_NOW):
            self.run_command()
        self.assertEqual(
            self.notifications_for(vendor, 'Your free trial ends in 3 day(s)').count(),
            1,
        )

    def test_day_0_and_past_never_send_kind4(self):
        today = self.trial_vendor('win-day0', FIXED_NOW)
        past = self.trial_vendor('win-past', FIXED_NOW - timedelta(days=2))

        with patch('django.utils.timezone.now', return_value=FIXED_NOW):
            self.run_command()

        for v in (today, past):
            self.assertFalse(
                self.notifications_for(v).filter(
                    title__startswith='Your free trial ends in',
                ).exists(),
                v.user.email,
            )
        # the trial-ended kind takes over instead
        self.assertEqual(
            self.notifications_for(today, 'Free trial ended').count(), 1,
        )
        self.assertEqual(
            self.notifications_for(past, 'Free trial ended').count(), 1,
        )


# =========================================================================
# Suppression
# =========================================================================

class SuppressionTests(SubscriptionNotificationFixture):

    def test_active_paid_vendor_gets_no_kind4(self):
        vendor = self.make_vendor('sup-paid')
        self.update_sub(
            vendor,
            status='active',
            plan='basic',
            qualification_status='skipped',
            trial_ends_at=None,
            period_end=timezone.now() + timedelta(days=20),
        )

        self.run_command()

        self.assert_not_notified(vendor, 'Your free trial ends in 5 day(s)')
        self.assertEqual(self.notifications_for(vendor).count(), 0)
        self.assertEqual(len(mail.outbox), 0)

    def test_admin_suspended_vendor_gets_no_kind4(self):
        vendor = self.make_vendor('sup-suspended')
        vendor = self.suspend(vendor)
        self.update_sub(
            vendor,
            status='trial',
            qualification_status='qualified',
            trial_ends_at=timezone.now() + timedelta(days=5),
        )

        output = self.run_command()

        self.assertEqual(self.notifications_for(vendor).count(), 0)
        self.assertEqual(len(mail.outbox), 0)
        self.assertIn('suppressed=1', output)

    def test_admin_suspended_vendor_gets_no_kinds_2_3_5_6(self):
        grace = self.make_vendor('sup-grace')
        self.make_product(grace, Store.objects.get(vendor=grace), 1, status='published')
        Subscription.objects.filter(vendor=grace).update(
            first_product_at=timezone.now() - timedelta(days=8),
        )
        grace = self.suspend(grace)

        failed = self.make_vendor('sup-failed')
        self.make_product(failed, Store.objects.get(vendor=failed), 1, status='published')
        Subscription.objects.filter(vendor=failed).update(
            first_product_at=timezone.now() - timedelta(days=15),
        )
        failed = self.suspend(failed)

        ended = self.make_vendor('sup-ended')
        self.update_sub(
            ended, status='trial', qualification_status='qualified',
            trial_ends_at=timezone.now() - timedelta(days=1),
        )
        ended = self.suspend(ended)

        expired = self.make_vendor('sup-expired')
        self.update_sub(
            expired, status='expired', plan='basic', qualification_status='skipped',
            trial_ends_at=None, period_end=timezone.now() - timedelta(days=1),
        )
        expired = self.suspend(expired)

        output = self.run_command()

        for v in (grace, failed, ended, expired):
            self.assertEqual(self.notifications_for(v).count(), 0, v.user.email)
        self.assertEqual(self.subscription_notifications().count(), 0)
        self.assertEqual(len(mail.outbox), 0)
        self.assertIn('suppressed=4', output)


# =========================================================================
# Lookback cap
# =========================================================================

class LookbackTests(SubscriptionNotificationFixture):

    def expired_vendor(self, key, days_ago):
        vendor = self.make_vendor(key)
        self.update_sub(
            vendor,
            status='expired',
            plan='basic',
            qualification_status='skipped',
            trial_ends_at=None,
            period_end=timezone.now() - timedelta(days=days_ago),
            grace_ends_at=None,
        )
        return vendor

    def test_expiry_10_days_ago_sends_nothing(self):
        vendor = self.expired_vendor('look-10', days_ago=10)
        output = self.run_command()
        self.assertEqual(self.notifications_for(vendor).count(), 0)
        self.assertEqual(len(mail.outbox), 0)
        self.assertIn('lookback=1', output)

    def test_expiry_1_day_ago_sends(self):
        vendor = self.expired_vendor('look-1', days_ago=1)
        output = self.run_command()
        self.assert_notified(vendor, 'Subscription expired', RESTRICTED_MESSAGE)
        self.assertIn('subscription_expired=1', output)

    def test_lookback_days_option_widens_the_window(self):
        vendor = self.expired_vendor('look-opt', days_ago=5)
        self.assertEqual(self.notifications_for(vendor).count(), 0)
        self.run_command('--lookback-days', '7')
        self.assert_notified(vendor, 'Subscription expired', RESTRICTED_MESSAGE)

    def test_expired_long_ago_stays_silent_for_failed_qualification(self):
        vendor = self.make_vendor('look-old-fail')
        store = self.store_of(vendor)
        self.make_product(vendor, store, 1, status='published')
        Subscription.objects.filter(vendor=vendor).update(
            first_product_at=timezone.now() - timedelta(days=30),
        )
        output = self.run_command()
        self.assertEqual(self.notifications_for(vendor).count(), 0)
        self.assertIn('lookback=', output)


# =========================================================================
# Failure isolation
# =========================================================================

class FailureIsolationTests(SubscriptionNotificationFixture):

    def test_one_vendor_email_failure_does_not_stop_the_loop(self):
        vendors = []
        for key in ('mail-fail', 'mail-ok-1', 'mail-ok-2'):
            vendor = self.make_vendor(key)
            self.update_sub(
                vendor,
                status='trial',
                qualification_status='qualified',
                trial_ends_at=timezone.now() + timedelta(days=5),
            )
            vendors.append(vendor)
        failing = vendors[0]

        original = notification_dispatch._send_notification_email

        def flaky(user, title, message, link=''):
            if user.email == failing.user.email:
                raise RuntimeError('smtp down')
            return original(user, title, message, link)

        with patch.object(
            notification_dispatch, '_send_notification_email', side_effect=flaky,
        ):
            output = self.run_command()

        # the command completed and reported the run
        self.assertIn('summary: processed 3', output)
        # in-app rows for everybody (create_notification never rolls back)
        for v in vendors:
            self.assertEqual(self.notifications_for(v).count(), 1, v.user.email)
        failed_notif = self.notifications_for(failing).first()
        self.assertIsNone(failed_notif.email_sent_at)
        # only the two healthy vendors produced an email
        self.assertEqual(len(mail.outbox), 2)

    def test_a_broken_row_is_counted_and_skipped(self):
        ok = self.make_vendor('loop-ok')
        self.update_sub(
            ok, status='trial', qualification_status='qualified',
            trial_ends_at=timezone.now() + timedelta(days=5),
        )
        broken = self.make_vendor('loop-broken')
        self.update_sub(
            broken, status='trial', qualification_status='qualified',
            trial_ends_at=timezone.now() - timedelta(days=1),
        )

        original = notification_dispatch.create_notification

        def boom(user, *args, **kwargs):
            if user.email == broken.user.email:
                raise RuntimeError('boom')
            return original(user, *args, **kwargs)

        with patch.object(
            notification_dispatch, 'create_notification', side_effect=boom,
        ):
            output = self.run_command()

        # one vendor failed, the loop continued and reported it
        self.assertIn('errors: 1', output)
        self.assertIn('trial_ending_soon=1', output)
        self.assertEqual(self.notifications_for(ok).count(), 1)
        self.assertEqual(self.notifications_for(broken).count(), 0)


# =========================================================================
# Command flags
# =========================================================================

class CommandFlagTests(SubscriptionNotificationFixture):

    def due_trial_vendor(self, key):
        vendor = self.make_vendor(key)
        self.update_sub(
            vendor, status='trial', qualification_status='qualified',
            trial_ends_at=timezone.now() + timedelta(days=5),
        )
        return vendor

    def test_dry_run_writes_and_sends_nothing(self):
        vendor = self.due_trial_vendor('flags-dry')
        out = StringIO()
        call_command('check_subscription_status', '--dry-run', stdout=out)
        output = out.getvalue()

        self.assertEqual(self.subscription_notifications().count(), 0)
        self.assertEqual(SubscriptionNotificationLog.objects.count(), 0)
        self.assertEqual(len(mail.outbox), 0)
        self.assertIn(f'[dry-run] would notify {vendor.user.email}', output)
        self.assertIn('would send: trial_unlocked=0', output)
        self.assertIn('trial_ending_soon=1', output)
        self.assertIn('errors: 0', output)

    def test_no_notify_sends_nothing(self):
        vendor = self.due_trial_vendor('flags-nonotify')
        out = StringIO()
        call_command('check_subscription_status', '--no-notify', stdout=out)
        output = out.getvalue()

        self.assertEqual(self.subscription_notifications().count(), 0)
        self.assertEqual(SubscriptionNotificationLog.objects.count(), 0)
        self.assertEqual(len(mail.outbox), 0)
        self.assertIn('notifications: skipped (--no-notify)', output)
        # old behaviour still ran
        self.assertIn('No subscriptions to expire.', output)
        self.assertIn('qualification synced: 0, failed: 0', output)
        self.assert_not_notified(vendor, 'Your free trial ends in 5 day(s)')

    def test_backfill_apply_sends_nothing(self):
        now = timezone.now()

        # (1) no Subscription row at all
        v1 = self.make_vendor('bf-no-sub')
        store1 = Store.objects.get(vendor=v1)
        self.make_product(v1, store1, 1, status='published')
        Subscription.objects.filter(vendor=v1).delete()

        # (2) legacy signup trial that is ALREADY due for kind 5
        v2 = self.make_vendor('bf-trial')
        self.update_sub(
            v2, status='trial', qualification_status='not_started',
            trial_ends_at=now - timedelta(days=1),
        )

        # (3) legacy free "active" row that is ALREADY due for kind 6
        v3 = self.make_vendor('bf-active')
        self.update_sub(
            v3, status='active', plan='free', period_end=now - timedelta(days=1),
        )

        # protected rows (already due as well: apply must not touch them)
        v4 = self.make_vendor('bf-paystack')
        self.update_sub(
            v4, status='trial', qualification_status='not_started',
            trial_ends_at=now - timedelta(days=1), paystack_subscription_code='SUB_42',
        )
        v5 = self.make_vendor('bf-expired')
        self.update_sub(v5, status='expired', qualification_status='failed')

        notifications_before = self.subscription_notifications().count()
        logs_before = SubscriptionNotificationLog.objects.count()

        out = StringIO()
        call_command('backfill_subscriptions', '--apply', stdout=out)
        self.assertIn('created 1', out.getvalue())

        self.assertEqual(self.subscription_notifications().count(), notifications_before)
        self.assertEqual(SubscriptionNotificationLog.objects.count(), logs_before)
        self.assertEqual(len(mail.outbox), 0)

        # grandfathered rows come back with a fresh, silent trial
        sub2 = self.sub_of(v2)
        self.assertEqual(sub2.status, 'trial')
        self.assertGreater(sub2.trial_ends_at, timezone.now())
        # protected rows are untouched
        self.assertEqual(
            self.sub_of(v4).paystack_subscription_code, 'SUB_42',
        )
        self.assertEqual(self.sub_of(v5).qualification_status, 'failed')


# =========================================================================
# Admin restart action
# =========================================================================

class AdminRestartTests(SubscriptionNotificationFixture):

    def setUp(self):
        super().setUp()
        self.User = get_user_model()
        self.superuser = self.User.objects.create_superuser(
            email='p7admin@example.com', password='password123',
        )

    def _admin(self):
        from apps.vendors.admin import SubscriptionAdmin
        return SubscriptionAdmin(Subscription, django_admin.site)

    def _post_restart(self, *subs):
        self.client.force_login(self.superuser)
        return self.client.post(
            reverse('admin:vendors_subscription_changelist'),
            {
                'action': 'restart_qualification_window',
                '_selected_action': [str(s.pk) for s in subs],
            },
            follow=True,
        )

    def test_restart_action_does_not_duplicate_already_sent_kinds(self):
        vendor = self.make_vendor('admin-dup')
        store = self.store_of(vendor)
        for n in (1, 2, 3):
            self.make_product(vendor, store, n, status='published')
        self.assertEqual(self.notifications_for(vendor).count(), 1)

        sub = self.sub_of(vendor)
        response = self._post_restart(sub)
        self.assertEqual(response.status_code, 200)
        sub.refresh_from_db()
        self.assertEqual(sub.status, 'trial')

        # same-day restart => same trial_ends_at cycle => no second send
        self.assertEqual(self.notifications_for(vendor).count(), 1)
        self.assertEqual(SubscriptionNotificationLog.objects.filter(
            kind='trial_unlocked',
        ).count(), 1)

        # a restarted window that is NOT due for anything sends nothing
        short = self.make_vendor('admin-short')
        self.make_product(short, Store.objects.get(vendor=short), 1, status='published')
        Subscription.objects.filter(vendor=short).update(
            status='expired', qualification_status='failed',
            first_product_at=timezone.now() - timedelta(days=15),
        )
        before = self.subscription_notifications().count()

        self._post_restart(self.sub_of(short))
        self.assertEqual(self.subscription_notifications().count(), before)


# =========================================================================
# Regression: existing payment notifications still fire
# =========================================================================

class ExistingPaymentNotificationTests(SubscriptionNotificationFixture):

    def test_payment_failed_and_renewed_notifications_still_fire(self):
        from apps.vendors.services.subscription_service import (
            process_subscription_webhook,
        )

        vendor = self.make_vendor('pay-webhooks')
        self.update_sub(
            vendor, status='active', plan='basic',
            qualification_status='skipped',
            paystack_subscription_code='SUB_P7',
            period_end=timezone.now() + timedelta(days=20),
        )

        failed = process_subscription_webhook(
            'invoice.payment_failed',
            {'subscription_code': 'SUB_P7', 'amount': 500000},
            event_id='evt_p7_failed',
        )
        self.assertTrue(failed['success'], failed)
        self.assertTrue(Notification.objects.filter(
            user=vendor.user, title__startswith='Payment Failed',
        ).exists())

        renewed = process_subscription_webhook(
            'charge.success',
            {'subscription_code': 'SUB_P7', 'amount': 500000},
            event_id='evt_p7_renewed',
        )
        self.assertTrue(renewed['success'], renewed)
        self.assertTrue(Notification.objects.filter(
            user=vendor.user, title__startswith='Subscription Renewed',
        ).exists())

        self.assertEqual(self.subscription_notifications().count(), 2)
        self.assertEqual(len(mail.outbox), 2)
        subjects = [m.subject for m in mail.outbox]
        self.assertTrue(any(s.startswith('Payment Failed') for s in subjects), subjects)
        self.assertTrue(any(s.startswith('Subscription Renewed') for s in subjects), subjects)


# =========================================================================
# Bounded query count of the command loop
# =========================================================================

class CommandQueryCountTests(SubscriptionNotificationFixture):

    @staticmethod
    def measure():
        out = StringIO()
        with CaptureQueriesContext(connection) as ctx:
            call_command('check_subscription_status', stdout=out)
        return len(ctx.captured_queries)

    def build_vendors(self, label, count, state):
        vendors = []
        for i in range(count):
            vendor = self.make_vendor(f'q-{label}-{state}-{i}')
            if state == 'trial':
                self.update_sub(
                    vendor, status='trial', qualification_status='qualified',
                    trial_ends_at=timezone.now() + timedelta(days=40),
                )
            elif state == 'dedupe':
                self.update_sub(
                    vendor, status='trial', qualification_status='qualified',
                    trial_ends_at=timezone.now() - timedelta(days=1),
                )
            vendors.append(vendor)
        return vendors

    def test_query_count_is_bounded_per_vendor(self):
        # -- nothing due: the loop must stay at the base query count
        self.build_vendors('a', 1, 'trial')
        q_none_1 = self.measure()

        self.build_vendors('b', 9, 'trial')
        q_none_10 = self.measure()

        # -- everything due and already sent: +1 dedupe lookup per vendor
        self.build_vendors('c', 1, 'dedupe')
        self.run_command()  # first run sends them all
        q_dedup_1 = self.measure()

        self.build_vendors('d', 9, 'dedupe')
        self.run_command()  # send only the 9 new ones
        q_dedup_10 = self.measure()

        per_vendor_none = (q_none_10 - q_none_1) / 9
        per_vendor_dedup = (q_dedup_10 - q_dedup_1) / 9

        print(
            'QUERY COUNTS: nothing-due 1 vendor=%d, 10 vendors=%d '
            '(%.2f per extra vendor); already-sent 1 vendor=%d, 10 vendors=%d '
            '(%.2f per extra vendor)' % (
                q_none_1, q_none_10, per_vendor_none,
                q_dedup_1, q_dedup_10, per_vendor_dedup,
            )
        )

        self.assertLessEqual(
            q_none_10 - q_none_1, 9 * 2,
            'per-vendor query cost must stay constant (product COUNT only)',
        )
        self.assertLessEqual(
            q_dedup_10 - q_dedup_1, 9 * 4,
            'per-vendor query cost must stay bounded (count + dedupe claim '
            '+ notification insert + email stamp)',
        )


# =========================================================================
# Report helper: sample rendered emails for kinds 1 and 4
# =========================================================================

class SampleEmailReportTests(SubscriptionNotificationFixture):

    def test_print_sample_email_for_kind1_and_kind4(self):
        vendor = self.make_vendor('sample-kind1')
        store = Store.objects.get(vendor=vendor)
        for n in (1, 2, 3):
            self.make_product(vendor, store, n, status='published')
        sub = self.sub_of(vendor)
        self.assertEqual(sub.status, 'trial')

        kind1 = self.emails_with_subject('Free trial unlocked')
        self.assertEqual(len(kind1), 1)
        print_sample_email(kind1[0])

        mail.outbox.clear()

        vendor4 = self.make_vendor('sample-kind4')
        self.update_sub(
            vendor4, status='trial', qualification_status='qualified',
            trial_ends_at=timezone.now() + timedelta(days=5),
        )
        self.run_command()

        kind4 = self.emails_with_subject('Your free trial ends in 5 day(s)')
        self.assertEqual(len(kind4), 1)
        print_sample_email(kind4[0])


def print_sample_email(message):
    print('--- SAMPLE EMAIL ---')
    print(f'Subject: {message.subject}')
    print(f'To: {", ".join(message.to)}')
    print('Body:')
    print(message.body.strip())
    print('--- END SAMPLE EMAIL ---')
