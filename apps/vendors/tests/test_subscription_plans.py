"""
Comprehensive tests for subscription plans, models, services, and views.
All Paystack network calls are mocked.
"""
from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch, MagicMock
import hmac
import hashlib
import logging

from django.contrib.auth import get_user_model
from django.contrib.messages import get_messages
from django.test import TestCase, RequestFactory, override_settings
from django.urls import reverse
from django.utils import timezone
from django.core.exceptions import ValidationError
from django.contrib import admin as django_admin

from apps.vendors.models import (
    MainCategory, SubCategory, Store, Product, Subscription, WebhookEvent
)
from apps.vendors.plans import (
    get_plan, paid_plans, plan_for_paystack_code, format_price,
    get_paystack_plan_code, get_plan_price_kobo
)
from apps.vendors.services.subscription_service import (
    subscription_service, SubscriptionServiceError,
    verify_subscription_webhook_signature, process_subscription_webhook,
    build_callback_url,
)
from apps.users.models import CustomUser


class PlansConfigTests(TestCase):
    """Test the plans configuration module."""

    def test_plan_identifiers_exist(self):
        """All three plan identifiers should exist."""
        self.assertEqual(get_plan('free')['identifier'], 'free')
        self.assertEqual(get_plan('basic')['identifier'], 'basic')
        self.assertEqual(get_plan('premium')['identifier'], 'premium')

    def test_free_plan_config(self):
        """Free plan should have correct config."""
        plan = get_plan('free')
        self.assertEqual(plan['identifier'], 'free')
        self.assertEqual(plan['display_name'], 'Free Plan')
        self.assertEqual(plan['price_naira'], 0)
        self.assertEqual(plan['price_kobo'], 0)
        self.assertFalse(plan['is_paid'])
        self.assertEqual(plan['benefits'], [])

    def test_basic_plan_config(self):
        """Basic plan should have correct config."""
        plan = get_plan('basic')
        self.assertEqual(plan['identifier'], 'basic')
        self.assertEqual(plan['display_name'], 'Basic Plan')
        self.assertEqual(plan['price_naira'], 1200)
        self.assertEqual(plan['price_kobo'], 120000)
        self.assertTrue(plan['is_paid'])
        self.assertEqual(plan['paystack_plan_code_setting'], 'PAYSTACK_BASIC_PLAN_CODE')
        expected_benefits = [
            'Premium Store Control',
            'Unlimited Product Listing',
            'No marketplace restrictions',
            'Free Subdomain',
        ]
        self.assertEqual(plan['benefits'], expected_benefits)

    def test_premium_plan_config(self):
        """Premium plan should have correct config."""
        plan = get_plan('premium')
        self.assertEqual(plan['identifier'], 'premium')
        self.assertEqual(plan['display_name'], 'Premium Plan')
        self.assertEqual(plan['price_naira'], 3000)
        self.assertEqual(plan['price_kobo'], 300000)
        self.assertTrue(plan['is_paid'])
        self.assertEqual(plan['paystack_plan_code_setting'], 'PAYSTACK_PREMIUM_PLAN_CODE')
        expected_benefits = [
            'Everything in Basic',
            'Product Promotion',
            'Store Promotion',
            'V-Batch',
            'Search/Discovery promotion',
            'SEO service',
        ]
        self.assertEqual(plan['benefits'], expected_benefits)

    def test_paid_plans_returns_only_paid(self):
        """paid_plans() should return only basic and premium."""
        plans = paid_plans()
        identifiers = [p['identifier'] for p in plans]
        self.assertEqual(sorted(identifiers), ['basic', 'premium'])

    def test_unknown_plan_raises_keyerror(self):
        """Getting unknown plan should raise KeyError."""
        with self.assertRaises(KeyError):
            get_plan('unknown')

    def test_plan_for_paystack_code_known(self):
        """plan_for_paystack_code should map known codes."""
        with override_settings(PAYSTACK_BASIC_PLAN_CODE='basic_code_123',
                               PAYSTACK_PREMIUM_PLAN_CODE='premium_code_456'):
            self.assertEqual(plan_for_paystack_code('basic_code_123'), 'basic')
            self.assertEqual(plan_for_paystack_code('premium_code_456'), 'premium')

    def test_plan_for_paystack_code_unknown(self):
        """Unknown Paystack code should return None."""
        with override_settings(PAYSTACK_BASIC_PLAN_CODE='basic_code',
                               PAYSTACK_PREMIUM_PLAN_CODE='premium_code'):
            self.assertIsNone(plan_for_paystack_code('unknown_code'))
            self.assertIsNone(plan_for_paystack_code(''))

    def test_format_price(self):
        """format_price should format with Naira sign and comma."""
        self.assertEqual(format_price(1200), '₦1,200')
        self.assertEqual(format_price(3000), '₦3,000')
        self.assertEqual(format_price(15000), '₦15,000')

    def test_get_paystack_plan_code(self):
        """get_paystack_plan_code should read from settings."""
        with override_settings(PAYSTACK_BASIC_PLAN_CODE='basic_123'):
            self.assertEqual(get_paystack_plan_code('basic'), 'basic_123')
        with override_settings(PAYSTACK_PREMIUM_PLAN_CODE='premium_456'):
            self.assertEqual(get_paystack_plan_code('premium'), 'premium_456')
        # Empty string for free (no setting)
        self.assertEqual(get_paystack_plan_code('free'), '')

    def test_get_plan_price_kobo(self):
        """get_plan_price_kobo returns correct kobo values."""
        self.assertEqual(get_plan_price_kobo('free'), 0)
        self.assertEqual(get_plan_price_kobo('basic'), 120000)
        self.assertEqual(get_plan_price_kobo('premium'), 300000)

    def test_get_plan_price_naira(self):
        """get_plan_price_naira returns correct naira values."""
        self.assertEqual(get_plan('free')['price_naira'], 0)
        self.assertEqual(get_plan('basic')['price_naira'], 1200)
        self.assertEqual(get_plan('premium')['price_naira'], 3000)


class SubscriptionModelTests(TestCase):
    """Test Subscription model fields and clean() validation."""

    def setUp(self):
        self.User = get_user_model()
        self.user = self.User.objects.create_user(
            email='vendor_admin@example.com',
            password='password123',
            username='vendor_admin',
            role='vendor',
        )
        self.vendor = self.user.vendorprofile
        Subscription.objects.filter(vendor=self.vendor).delete()
        # Delete any existing subscription from signals
        Subscription.objects.filter(vendor=self.vendor).delete()
        self.category = MainCategory.objects.create(name='Tech', slug='tech')
        self.subcategory = SubCategory.objects.create(
            main_category=self.category,
            name='Phones',
            slug='phones',
        )
        self.store = Store.objects.create(
            vendor=self.vendor,
            store_name='Test Store',
            slug='test-store',
            main_category=self.category,
        )

    def test_plan_field_default(self):
        """New subscription should have plan='free' by default."""
        sub = Subscription.objects.create(vendor=self.vendor)
        self.assertEqual(sub.plan, 'free')

    def test_cancel_at_period_end_default(self):
        """New subscription should have cancel_at_period_end=False."""
        sub = Subscription.objects.create(vendor=self.vendor)
        self.assertFalse(sub.cancel_at_period_end)

    def test_pending_plan_default(self):
        """New subscription should have pending_plan=''."""
        sub = Subscription.objects.create(vendor=self.vendor)
        self.assertEqual(sub.pending_plan, '')

    def test_plan_choices(self):
        """Plan field should only accept free/basic/premium."""
        sub = Subscription(vendor=self.vendor, plan='basic', status='active',
                          period_end=timezone.now() + timedelta(days=30))
        sub.full_clean()  # Should not raise

        sub.plan = 'invalid'
        with self.assertRaises(ValidationError):
            sub.full_clean()

    def test_pending_plan_choices(self):
        """pending_plan should only accept free/basic/premium or empty."""
        sub = Subscription(vendor=self.vendor, pending_plan='basic', status='active',
                          period_end=timezone.now() + timedelta(days=30))
        sub.full_clean()

        sub.pending_plan = 'invalid'
        with self.assertRaises(ValidationError):
            sub.full_clean()

        sub.pending_plan = ''
        sub.full_clean()  # Empty is valid

    def test_clean_active_requires_period_end(self):
        """Active status requires period_end."""
        sub = Subscription(vendor=self.vendor, status='active', period_end=None)
        with self.assertRaises(ValidationError) as cm:
            sub.clean()
        self.assertIn('period_end', cm.exception.message_dict)

    def test_clean_trial_requires_trial_ends_at(self):
        """Trial status requires trial_ends_at."""
        sub = Subscription(vendor=self.vendor, status='trial', trial_ends_at=None)
        with self.assertRaises(ValidationError) as cm:
            sub.clean()
        self.assertIn('trial_ends_at', cm.exception.message_dict)

    def test_clean_active_with_period_end_passes(self):
        """Active with period_end should pass."""
        sub = Subscription(
            vendor=self.vendor,
            status='active',
            period_end=timezone.now() + timedelta(days=30)
        )
        sub.clean()  # Should not raise

    def test_clean_trial_with_trial_ends_at_passes(self):
        """Trial with trial_ends_at should pass."""
        sub = Subscription(
            vendor=self.vendor,
            status='trial',
            trial_ends_at=timezone.now() + timedelta(days=30)
        )
        sub.clean()  # Should not raise

    def test_clean_other_statuses_pass(self):
        """past_due, cancelled, expired should pass without dates."""
        for status in ['past_due', 'cancelled', 'expired']:
            sub = Subscription(vendor=self.vendor, status=status)
            sub.clean()  # Should not raise


class SubscriptionServiceTests(TestCase):
    """Test subscription service methods with mocked Paystack."""

    def setUp(self):
        self.User = get_user_model()
        self.user = self.User.objects.create_user(
            email='vendor_admin@example.com',
            password='password123',
            username='vendor_admin',
            role='vendor',
        )
        self.vendor = self.user.vendorprofile
        Subscription.objects.filter(vendor=self.vendor).delete()

    @patch('apps.vendors.services.subscription_service.requests.post')
    def test_initialize_subscription_invalid_plan_raises(self, mock_post):
        """initialize_subscription should raise for invalid plan."""
        with self.assertRaises(SubscriptionServiceError):
            subscription_service.initialize_subscription(
                email='test@example.com',
                plan='invalid',
            )

    @patch('apps.vendors.services.subscription_service.requests.post')
    def test_initialize_subscription_missing_paystack_code_raises(self, mock_post):
        """Missing Paystack plan code should raise clear error."""
        with override_settings(PAYSTACK_BASIC_PLAN_CODE=''):
            with self.assertRaises(SubscriptionServiceError) as cm:
                subscription_service.initialize_subscription(
                    email='test@example.com',
                    plan='basic',
                )
            self.assertIn('not configured', str(cm.exception))

    @patch('apps.vendors.services.subscription_service.requests.post')
    def test_initialize_subscription_success(self, mock_post):
        """Successful initialization returns authorization_url."""
        mock_post.return_value.json.return_value = {
            'status': True,
            'data': {
                'authorization_url': 'https://paystack.com/pay/xyz',
                'access_code': 'acc_123',
                'reference': 'ref_123',
            }
        }
        mock_post.return_value.raise_for_status = MagicMock()

        with override_settings(PAYSTACK_BASIC_PLAN_CODE='basic_code'):
            success, data = subscription_service.initialize_subscription(
                email='test@example.com',
                plan='basic',
                metadata={'vendor_id': 'vendor_123'},
            )

        self.assertTrue(success)
        self.assertEqual(data['authorization_url'], 'https://paystack.com/pay/xyz')
        mock_post.assert_called_once()

    @patch('apps.vendors.services.subscription_service.requests.post')
    def test_initialize_subscription_uses_correct_amount(self, mock_post):
        """initialize_subscription should use correct price per plan."""
        mock_post.return_value.json.return_value = {
            'status': True,
            'data': {'authorization_url': 'https://paystack.com/pay/xyz', 'reference': 'ref'}
        }
        mock_post.return_value.raise_for_status = MagicMock()

        with override_settings(PAYSTACK_BASIC_PLAN_CODE='basic_code',
                               PAYSTACK_PREMIUM_PLAN_CODE='premium_code'):
            # Test basic plan amount
            subscription_service.initialize_subscription('test@test.com', 'basic')
            call_args = mock_post.call_args
            payload = call_args[1]['json']
            self.assertEqual(payload['amount'], 120000)  # basic = 120000 kobo

            # Test premium plan amount
            subscription_service.initialize_subscription('test@test.com', 'premium')
            call_args = mock_post.call_args
            payload = call_args[1]['json']
            self.assertEqual(payload['amount'], 300000)  # premium = 300000 kobo

    @patch('apps.vendors.services.subscription_service.requests.post')
    def test_initialize_subscription_passes_callback_url(self, mock_post):
        """The Paystack payload must carry the absolute callback_url."""
        mock_post.return_value.json.return_value = {
            'status': True,
            'data': {'authorization_url': 'https://paystack.com/pay/xyz', 'reference': 'ref'},
        }
        mock_post.return_value.raise_for_status = MagicMock()

        with override_settings(PAYSTACK_BASIC_PLAN_CODE='basic_code',
                               SITE_URL='https://kasumarketplace.com.ng'):
            success, data = subscription_service.initialize_subscription(
                'test@test.com', 'basic', metadata={'vendor_id': 'v1'},
            )
            payload = mock_post.call_args[1]['json']

        self.assertTrue(success)
        self.assertEqual(
            payload['callback_url'],
            'https://kasumarketplace.com.ng/vendors/subscription/callback/',
        )
        self.assertEqual(data['callback_url'], payload['callback_url'])

    def test_build_callback_url_is_absolute(self):
        """build_callback_url returns an absolute URL for vendors:subscription_callback."""
        with override_settings(SITE_URL='https://example.test/'):
            url = build_callback_url()
        self.assertEqual(url, 'https://example.test/vendors/subscription/callback/')


class SubscriptionTemplateMatrixTests(TestCase):
    """
    One rendering test per state of the plans.html button matrix.

    Assertions are scoped to the two paid cards (between the
    '<!-- Basic Plan Card -->' and '<!-- Help Text -->' markers) so the
    free card's own status text cannot mask a missing/extra button.
    """

    SUBSCRIBE_BASIC = 'Subscribe to Basic Plan'
    SUBSCRIBE_PREMIUM = 'Subscribe to Premium Plan'
    CURRENT_PLAN = 'Current Plan'
    UPGRADE_PREMIUM = 'Upgrade to Premium'
    SWITCH_BASIC = 'Switch to Basic at End of Billing Period'
    CANCEL = 'Cancel Subscription'

    def setUp(self):
        self.User = get_user_model()
        self.user = self.User.objects.create_user(
            email='vendor_matrix@example.com',
            password='password123',
            username='vendor_matrix',
            role='vendor',
        )
        self.vendor = self.user.vendorprofile
        Subscription.objects.filter(vendor=self.vendor).delete()
        self.category = MainCategory.objects.create(name='Tech', slug='tech')
        self.store = Store.objects.create(
            vendor=self.vendor,
            store_name='Matrix Store',
            slug='matrix-store',
            main_category=self.category,
        )
        self.client.force_login(self.user)

    def paid_cards(self, **kwargs):
        response = self.client.get(reverse('vendors:subscription_plans'))
        self.assertEqual(response.status_code, 200)
        html = response.content.decode()
        start = html.index('<!-- Basic Plan Card -->')
        end = html.index('<!-- Help Text -->')
        return html[start:end]

    def assert_buttons(self, present, absent):
        html = self.paid_cards()
        for text in present:
            self.assertIn(text, html, f'expected button/label {text!r} to be rendered')
        for text in absent:
            self.assertNotIn(text, html, f'expected {text!r} NOT to be rendered')

    def test_state_trial_free_plan(self):
        """Trial / no paid plan -> both subscribe buttons, no cancel or switch."""
        Subscription.objects.create(
            vendor=self.vendor, status='trial', plan='free',
            trial_ends_at=timezone.now() + timedelta(days=30),
        )
        self.assert_buttons(
            present=[self.SUBSCRIBE_BASIC, self.SUBSCRIBE_PREMIUM],
            absent=[self.CURRENT_PLAN, self.UPGRADE_PREMIUM, self.SWITCH_BASIC, self.CANCEL],
        )

    def test_state_expired_paid_plan(self):
        """Paid but expired -> both subscribe buttons (plan is re-bought)."""
        Subscription.objects.create(
            vendor=self.vendor, status='expired', plan='premium',
            period_end=timezone.now() - timedelta(days=1),
        )
        self.assert_buttons(
            present=[self.SUBSCRIBE_BASIC, self.SUBSCRIBE_PREMIUM],
            absent=[self.CURRENT_PLAN, self.UPGRADE_PREMIUM, self.SWITCH_BASIC, self.CANCEL],
        )

    def test_state_cancelled_paid_plan(self):
        """Cancelled -> both subscribe buttons."""
        Subscription.objects.create(
            vendor=self.vendor, status='cancelled', plan='basic',
            grace_ends_at=timezone.now() + timedelta(days=5),
        )
        self.assert_buttons(
            present=[self.SUBSCRIBE_BASIC, self.SUBSCRIBE_PREMIUM],
            absent=[self.CURRENT_PLAN, self.UPGRADE_PREMIUM, self.SWITCH_BASIC, self.CANCEL],
        )

    def test_state_past_due_paid_plan(self):
        """past_due -> both subscribe buttons."""
        Subscription.objects.create(
            vendor=self.vendor, status='past_due', plan='basic',
            grace_ends_at=timezone.now() + timedelta(days=5),
        )
        self.assert_buttons(
            present=[self.SUBSCRIBE_BASIC, self.SUBSCRIBE_PREMIUM],
            absent=[self.CURRENT_PLAN, self.UPGRADE_PREMIUM, self.SWITCH_BASIC, self.CANCEL],
        )

    def test_state_paid_active_basic(self):
        """paid-active basic -> Current Plan + Upgrade + Cancel (POST)."""
        Subscription.objects.create(
            vendor=self.vendor, status='active', plan='basic',
            paystack_subscription_code='sub_basic',
            period_end=timezone.now() + timedelta(days=20),
        )
        html = self.paid_cards()
        for text in [self.CURRENT_PLAN, self.UPGRADE_PREMIUM, self.CANCEL]:
            self.assertIn(text, html)
        for text in [self.SUBSCRIBE_BASIC, self.SUBSCRIBE_PREMIUM, self.SWITCH_BASIC]:
            self.assertNotIn(text, html)
        self.assertIn(reverse('vendors:subscription_cancel'), html)
        self.assertIn(reverse('vendors:subscription_subscribe'), html)

    def test_state_paid_active_premium(self):
        """paid-active premium -> Current Plan + Switch + Cancel (POST)."""
        Subscription.objects.create(
            vendor=self.vendor, status='active', plan='premium',
            paystack_subscription_code='sub_premium',
            period_end=timezone.now() + timedelta(days=20),
        )
        html = self.paid_cards()
        for text in [self.CURRENT_PLAN, self.SWITCH_BASIC, self.CANCEL]:
            self.assertIn(text, html)
        for text in [self.SUBSCRIBE_BASIC, self.SUBSCRIBE_PREMIUM, self.UPGRADE_PREMIUM]:
            self.assertNotIn(text, html)
        self.assertIn(reverse('vendors:subscription_cancel'), html)
        self.assertIn(reverse('vendors:subscription_downgrade'), html)

    def test_state_paid_active_basic_cancelling(self):
        """paid-active basic + cancel_at_period_end -> notice only, no buttons."""
        Subscription.objects.create(
            vendor=self.vendor, status='active', plan='basic',
            cancel_at_period_end=True,
            period_end=timezone.now() + timedelta(days=10),
        )
        response = self.client.get(reverse('vendors:subscription_plans'))
        html = response.content.decode()
        start = html.index('<!-- Basic Plan Card -->')
        end = html.index('<!-- Help Text -->')
        cards = html[start:end]

        self.assertIn('Your plan ends on', html)
        self.assertIn('No automatic charge will occur.', html)
        for text in [self.UPGRADE_PREMIUM, self.CANCEL, self.SWITCH_BASIC,
                     self.SUBSCRIBE_BASIC, self.SUBSCRIBE_PREMIUM]:
            self.assertNotIn(text, cards, f'expected {text!r} NOT to be rendered')
        self.assertNotIn('You chose to switch to Basic', html)

    def test_state_paid_active_premium_cancelling_pending_basic(self):
        """paid-active premium + cancel_at_period_end + pending basic -> notice, no buttons."""
        Subscription.objects.create(
            vendor=self.vendor, status='active', plan='premium',
            cancel_at_period_end=True, pending_plan='basic',
            period_end=timezone.now() + timedelta(days=10),
        )
        response = self.client.get(reverse('vendors:subscription_plans'))
        html = response.content.decode()
        start = html.index('<!-- Basic Plan Card -->')
        end = html.index('<!-- Help Text -->')
        cards = html[start:end]

        self.assertIn('Your plan ends on', html)
        self.assertIn('No automatic charge will occur.', html)
        self.assertIn(
            'You chose to switch to Basic. Subscribe to Basic after your current period ends.',
            html,
        )
        for text in [self.CANCEL, self.SWITCH_BASIC, self.UPGRADE_PREMIUM,
                     self.SUBSCRIBE_BASIC, self.SUBSCRIBE_PREMIUM]:
            self.assertNotIn(text, cards, f'expected {text!r} NOT to be rendered')

    def test_no_premium_pending_plan_ui_path(self):
        """No rendered copy mentions switching to Premium as a pending plan."""
        Subscription.objects.create(
            vendor=self.vendor, status='active', plan='premium',
            cancel_at_period_end=True, pending_plan='basic',
            period_end=timezone.now() + timedelta(days=10),
        )
        response = self.client.get(reverse('vendors:subscription_plans'))
        html = response.content.decode()
        self.assertNotIn('switch to Premium Plan', html)
        self.assertNotIn('will switch to Premium', html)


class SubscriptionCallbackTests(TestCase):
    """Browser callback: verification, ownership, and webhook/callback idempotency."""

    def setUp(self):
        self.User = get_user_model()
        self.user = self.User.objects.create_user(
            email='vendor_cb@example.com',
            password='password123',
            username='vendor_cb',
            role='vendor',
        )
        self.vendor = self.user.vendorprofile
        Subscription.objects.filter(vendor=self.vendor).delete()
        self.category = MainCategory.objects.create(name='Tech', slug='tech')
        self.store = Store.objects.create(
            vendor=self.vendor,
            store_name='Callback Store',
            slug='callback-store',
            main_category=self.category,
        )
        WebhookEvent.objects.all().delete()
        self.client.force_login(self.user)

    def transaction(self, **overrides):
        txn = {
            'status': 'success',
            'reference': 'ref_upgrade_1',
            'amount': 300000,
            'customer': {'customer_code': 'cus_cb', 'email': self.user.email},
            'plan': {'plan_code': 'PLN_premium'},
            'metadata': {
                'vendor_id': str(self.vendor.vendor_id),
                'plan': 'premium',
                'subscription_code': 'sub_cb_new',
            },
        }
        txn.update(overrides)
        return txn

    def webhook_payload(self):
        return {
            'metadata': {
                'vendor_id': str(self.vendor.vendor_id),
                'plan': 'premium',
                'subscription_code': 'sub_cb_new',
            },
            'subscription': {'subscription_code': 'sub_cb_new'},
            'plan': {'plan_code': 'PLN_premium'},
            'customer': {'customer_code': 'cus_cb'},
        }

    @patch('apps.vendors.services.subscription_service.SubscriptionService._request')
    def test_callback_then_webhook_activates_once(self, mock_request):
        mock_request.return_value = {'status': True, 'data': {}}
        sub = Subscription.objects.create(
            vendor=self.vendor, status='active', plan='basic',
            paystack_subscription_code='sub_cb_old',
            period_end=timezone.now() + timedelta(days=10),
        )

        with override_settings(PAYSTACK_PREMIUM_PLAN_CODE='PLN_premium'):
            with patch.object(subscription_service, 'verify_transaction', return_value=self.transaction()):
                response = self.client.get(
                    reverse('vendors:subscription_callback'),
                    {'reference': 'ref_upgrade_1'},
                )
            self.assertEqual(response.status_code, 302)
            sub.refresh_from_db()
            self.assertEqual(sub.plan, 'premium')
            self.assertEqual(sub.paystack_subscription_code, 'sub_cb_new')
            period_after_callback = sub.period_end

            result = process_subscription_webhook(
                'charge.success', self.webhook_payload(), event_id='evt_after_cb',
            )

        self.assertIn('replay', result['message'])
        sub.refresh_from_db()
        self.assertEqual(sub.plan, 'premium')
        self.assertEqual(sub.period_end, period_after_callback)
        disable_calls = [c for c in mock_request.call_args_list if 'disable' in c[0][1]]
        self.assertEqual(len(disable_calls), 1)
        self.assertEqual(disable_calls[0][0][1], '/subscription/sub_cb_old/disable')

    @patch('apps.vendors.services.subscription_service.SubscriptionService._request')
    def test_webhook_then_callback_activates_once(self, mock_request):
        mock_request.return_value = {'status': True, 'data': {}}
        sub = Subscription.objects.create(
            vendor=self.vendor, status='active', plan='basic',
            paystack_subscription_code='sub_cb_old',
            period_end=timezone.now() + timedelta(days=10),
        )

        with override_settings(PAYSTACK_PREMIUM_PLAN_CODE='PLN_premium'):
            result = process_subscription_webhook(
                'charge.success', self.webhook_payload(), event_id='evt_before_cb',
            )
            self.assertNotIn('replay', result['message'])
            sub.refresh_from_db()
            self.assertEqual(sub.plan, 'premium')
            period_after_webhook = sub.period_end

            with patch.object(subscription_service, 'verify_transaction', return_value=self.transaction()):
                response = self.client.get(
                    reverse('vendors:subscription_callback'),
                    {'reference': 'ref_upgrade_1'},
                )

        self.assertEqual(response.status_code, 302)
        sub.refresh_from_db()
        self.assertEqual(sub.plan, 'premium')
        self.assertEqual(sub.period_end, period_after_webhook)
        disable_calls = [c for c in mock_request.call_args_list if 'disable' in c[0][1]]
        self.assertEqual(len(disable_calls), 1)

    def test_callback_for_another_vendor_is_rejected(self):
        other = self.User.objects.create_user(
            email='other_vendor@example.com',
            password='password123',
            username='other_vendor',
            role='vendor',
        )
        sub = Subscription.objects.create(
            vendor=self.vendor, status='trial', plan='free',
            trial_ends_at=timezone.now() + timedelta(days=30),
        )
        txn = self.transaction(
            customer={'customer_code': 'cus_other', 'email': other.email},
            metadata={
                'vendor_id': str(other.vendorprofile.vendor_id),
                'plan': 'premium',
                'subscription_code': 'sub_other',
            },
        )

        with patch.object(subscription_service, 'verify_transaction', return_value=txn):
            response = self.client.get(
                reverse('vendors:subscription_callback'), {'reference': 'ref_other'},
                follow=True,
            )

        msgs = [str(m) for m in get_messages(response.wsgi_request)]
        self.assertTrue(
            any('does not belong to your account' in m for m in msgs), msgs
        )
        sub.refresh_from_db()
        self.assertEqual(sub.status, 'trial')
        self.assertEqual(sub.plan, 'free')
        self.assertFalse(WebhookEvent.objects.exists())

    def test_callback_rejected_by_email_mismatch(self):
        sub = Subscription.objects.create(
            vendor=self.vendor, status='trial', plan='free',
            trial_ends_at=timezone.now() + timedelta(days=30),
        )
        txn = self.transaction(
            customer={'customer_code': 'cus_other', 'email': 'someone.else@example.com'},
            metadata={'plan': 'premium', 'subscription_code': 'sub_other'},
        )
        with patch.object(subscription_service, 'verify_transaction', return_value=txn):
            response = self.client.get(
                reverse('vendors:subscription_callback'), {'reference': 'ref_other'},
                follow=True,
            )
        msgs = [str(m) for m in get_messages(response.wsgi_request)]
        self.assertTrue(any('does not belong to your account' in m for m in msgs), msgs)
        sub.refresh_from_db()
        self.assertEqual(sub.status, 'trial')

    def test_callback_without_ownership_info_is_rejected(self):
        """No metadata vendor_id and no payer email -> ownership unverifiable."""
        sub = Subscription.objects.create(
            vendor=self.vendor, status='trial', plan='free',
            trial_ends_at=timezone.now() + timedelta(days=30),
        )
        txn = self.transaction(
            customer={'customer_code': 'cus_anon'},
            metadata={'plan': 'premium', 'subscription_code': 'sub_anon'},
        )
        with patch.object(subscription_service, 'verify_transaction', return_value=txn):
            response = self.client.get(
                reverse('vendors:subscription_callback'), {'reference': 'ref_anon'},
                follow=True,
            )
        msgs = [str(m) for m in get_messages(response.wsgi_request)]
        self.assertTrue(any('does not belong to your account' in m for m in msgs), msgs)
        sub.refresh_from_db()
        self.assertEqual(sub.status, 'trial')
        self.assertEqual(sub.plan, 'free')
        self.assertFalse(WebhookEvent.objects.exists())

    def test_failed_payment_changes_nothing(self):
        sub = Subscription.objects.create(
            vendor=self.vendor, status='trial', plan='free',
            trial_ends_at=timezone.now() + timedelta(days=30),
        )
        txn = self.transaction(status='abandoned')

        with patch.object(subscription_service, 'verify_transaction', return_value=txn):
            response = self.client.get(
                reverse('vendors:subscription_callback'), {'reference': 'ref_failed'},
                follow=True,
            )

        msgs = [str(m) for m in get_messages(response.wsgi_request)]
        self.assertTrue(any('was not completed' in m for m in msgs), msgs)
        sub.refresh_from_db()
        self.assertEqual(sub.status, 'trial')
        self.assertEqual(sub.plan, 'free')
        self.assertEqual(sub.paystack_subscription_code, '')
        self.assertFalse(WebhookEvent.objects.exists())

    def test_verification_api_failure_changes_nothing(self):
        sub = Subscription.objects.create(
            vendor=self.vendor, status='trial', plan='free',
            trial_ends_at=timezone.now() + timedelta(days=30),
        )
        with patch.object(
            subscription_service, 'verify_transaction',
            side_effect=SubscriptionServiceError('boom'),
        ):
            response = self.client.get(
                reverse('vendors:subscription_callback'), {'reference': 'ref_boom'},
                follow=True,
            )
        msgs = [str(m) for m in get_messages(response.wsgi_request)]
        self.assertTrue(any('Unable to verify payment' in m for m in msgs), msgs)
        sub.refresh_from_db()
        self.assertEqual(sub.status, 'trial')
        self.assertFalse(WebhookEvent.objects.exists())

    def test_callback_without_reference_changes_nothing(self):
        sub = Subscription.objects.create(
            vendor=self.vendor, status='trial', plan='free',
            trial_ends_at=timezone.now() + timedelta(days=30),
        )
        response = self.client.get(reverse('vendors:subscription_callback'))
        self.assertEqual(response.status_code, 302)
        sub.refresh_from_db()
        self.assertEqual(sub.status, 'trial')
        self.assertFalse(WebhookEvent.objects.exists())


class SubscriptionSubscribeUpgradeTests(TestCase):
    """The Upgrade to Premium button must reach Paystack, not bounce."""

    def setUp(self):
        self.User = get_user_model()
        self.user = self.User.objects.create_user(
            email='vendor_sub@example.com',
            password='password123',
            username='vendor_sub',
            role='vendor',
        )
        self.vendor = self.user.vendorprofile
        Subscription.objects.filter(vendor=self.vendor).delete()

    @patch('apps.vendors.services.subscription_service.subscription_service.initialize_subscription')
    def test_upgrade_post_reaches_paystack(self, mock_init):
        mock_init.return_value = (True, {'authorization_url': 'https://paystack.com/pay/up'})
        Subscription.objects.create(
            vendor=self.vendor, status='active', plan='basic',
            paystack_subscription_code='sub_basic',
            period_end=timezone.now() + timedelta(days=20),
        )
        self.client.force_login(self.user)
        response = self.client.post(
            reverse('vendors:subscription_subscribe'), {'plan': 'premium'},
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, 'https://paystack.com/pay/up')
        self.assertEqual(mock_init.call_args[1]['plan'], 'premium')

    @patch('apps.vendors.services.subscription_service.subscription_service.initialize_subscription')
    def test_repeat_premium_post_is_blocked(self, mock_init):
        mock_init.return_value = (True, {'authorization_url': 'https://paystack.com/pay/up'})
        Subscription.objects.create(
            vendor=self.vendor, status='active', plan='premium',
            paystack_subscription_code='sub_premium',
            period_end=timezone.now() + timedelta(days=20),
        )
        self.client.force_login(self.user)
        response = self.client.post(
            reverse('vendors:subscription_subscribe'), {'plan': 'premium'}, follow=True,
        )
        msgs = [str(m) for m in get_messages(response.wsgi_request)]
        self.assertTrue(any('already have an active Premium Plan subscription' in m for m in msgs), msgs)
        mock_init.assert_not_called()

    @patch('apps.vendors.services.subscription_service.subscription_service.initialize_subscription')
    def test_upgrade_post_blocked_while_cancelling(self, mock_init):
        mock_init.return_value = (True, {'authorization_url': 'https://paystack.com/pay/up'})
        Subscription.objects.create(
            vendor=self.vendor, status='active', plan='basic',
            cancel_at_period_end=True,
            period_end=timezone.now() + timedelta(days=20),
        )
        self.client.force_login(self.user)
        response = self.client.post(
            reverse('vendors:subscription_subscribe'), {'plan': 'premium'}, follow=True,
        )
        msgs = [str(m) for m in get_messages(response.wsgi_request)]
        self.assertTrue(any('already scheduled to end' in m for m in msgs), msgs)
        mock_init.assert_not_called()


class SubscriptionModelWebhookTests(TestCase):
    """Test webhook processing with mocked Paystack."""

    def setUp(self):
        self.User = get_user_model()
        self.user = self.User.objects.create_user(
            email='vendor_webhook@example.com',
            password='password123',
            username='vendor_webhook',
            role='vendor',
        )
        self.vendor = self.user.vendorprofile
        Subscription.objects.filter(vendor=self.vendor).delete()
        # Delete any subscription created by signals
        Subscription.objects.filter(vendor=self.vendor).delete()

    def test_plan_for_paystack_code_in_webhook(self):
        """Webhook should map Paystack plan code to plan identifier."""
        with override_settings(PAYSTACK_BASIC_PLAN_CODE='basic_123',
                               PAYSTACK_PREMIUM_PLAN_CODE='premium_456'):
            # Test basic
            data = {'plan': {'plan_code': 'basic_123'}}
            self.assertEqual(plan_for_paystack_code('basic_123'), 'basic')
            self.assertEqual(plan_for_paystack_code('premium_456'), 'premium')
            self.assertIsNone(plan_for_paystack_code('unknown'))

    @patch('apps.vendors.services.subscription_service.SubscriptionService._request')
    def test_webhook_activates_subscription_with_plan(self, mock_request):
        """Webhook should set plan on activation based on Paystack plan code."""
        mock_request.return_value = {
            'status': True,
            'data': {'authorization_url': 'https://paystack.com/pay/xyz'}
        }

        # Create subscription with basic plan code
        sub = Subscription.objects.create(
            vendor=self.vendor,
            status='trial',
            paystack_subscription_code='sub_basic_123',
        )

        with override_settings(PAYSTACK_BASIC_PLAN_CODE='basic_123',
                               PAYSTACK_PREMIUM_PLAN_CODE='premium_456'):
            # Simulate charge.success INITIAL payment (has metadata.subscription_code)
            data = {
                'metadata': {'subscription_code': 'sub_basic_123'},
                'subscription': {
                    'subscription_code': 'sub_basic_123',
                    'plan_code': 'basic_123',
                },
                'plan': {'plan_code': 'basic_123'},
                'customer': {'customer_code': 'cus_123'},
            }
            result = process_subscription_webhook('charge.success', data, event_id='evt_1')

        self.assertTrue(result['success'])
        sub.refresh_from_db()
        self.assertEqual(sub.status, 'active')
        self.assertEqual(sub.plan, 'basic')

    @patch('apps.vendors.services.subscription_service.SubscriptionService._request')
    def test_webhook_premium_activates_premium(self, mock_request):
        """Premium plan code should activate premium plan."""
        mock_request.return_value = {'status': True, 'data': {'authorization_url': 'https://x'}}

        sub = Subscription.objects.create(
            vendor=self.vendor,
            status='trial',
            paystack_subscription_code='sub_premium_123',
        )

        with override_settings(PAYSTACK_BASIC_PLAN_CODE='basic_123',
                               PAYSTACK_PREMIUM_PLAN_CODE='premium_456'):
            data = {
                'metadata': {'subscription_code': 'sub_premium_123'},
                'subscription': {
                    'subscription_code': 'sub_premium_123',
                    'plan_code': 'premium_456',
                },
                'plan': {'plan_code': 'premium_456'},
                'customer': {'customer_code': 'cus_123'},
            }
            result = process_subscription_webhook('charge.success', data, event_id='evt_2')

        self.assertTrue(result['success'])
        sub.refresh_from_db()
        self.assertEqual(sub.plan, 'premium')

    def test_webhook_unknown_plan_code_ignored(self):
        """Unknown Paystack plan code should not activate subscription."""
        sub = Subscription.objects.create(
            vendor=self.vendor,
            status='trial',
            paystack_subscription_code='sub_unknown_123',
        )

        with override_settings(PAYSTACK_BASIC_PLAN_CODE='basic_123',
                               PAYSTACK_PREMIUM_PLAN_CODE='premium_456'):
            data = {
                'subscription_code': 'sub_unknown_123',
                'plan': {'plan_code': 'unknown_code'},
                'customer': {'customer_code': 'cus_123'},
            }
            result = process_subscription_webhook('charge.success', data, event_id='evt_3')

        # Should still acknowledge but not activate with a specific plan
        sub.refresh_from_db()
        self.assertEqual(sub.plan, 'free')  # Remains free (default)

    def test_webhook_duplicate_idempotent(self):
        """Duplicate webhook events should be skipped idempotently."""
        sub = Subscription.objects.create(
            vendor=self.vendor,
            status='trial',
            paystack_subscription_code='sub_dup_123',
        )

        with override_settings(PAYSTACK_BASIC_PLAN_CODE='basic_123'):
            data = {
                'subscription_code': 'sub_dup_123',
                'plan': {'plan_code': 'basic_123'},
            }
            # First call
            result1 = process_subscription_webhook('charge.success', data, event_id='evt_dup')
            # Second call with same event_id
            result2 = process_subscription_webhook('charge.success', data, event_id='evt_dup')

        self.assertTrue(result1['success'])
        self.assertIn('already processed', result2['message'])


class SubscriptionActionTests(TestCase):
    """Test cancel, downgrade, upgrade, and expiry logic."""

    def setUp(self):
        self.User = get_user_model()
        self.user = self.User.objects.create_user(
            email='vendor_action@example.com',
            password='password123',
            username='vendor_action',
            role='vendor',
        )
        self.vendor = self.user.vendorprofile
        Subscription.objects.filter(vendor=self.vendor).delete()
        # Ensure clean slate - delete any subscription created by signals
        Subscription.objects.filter(vendor=self.vendor).delete()
        from apps.vendors.models import WebhookEvent
        WebhookEvent.objects.all().delete()

    def test_request_cancel_sets_flag(self):
        """request_cancel should set cancel_at_period_end=True."""
        sub = Subscription.objects.create(
            vendor=self.vendor,
            status='active',
            plan='basic',
            period_end=timezone.now() + timedelta(days=30),
        )
        subscription_service.cancel_subscription(sub)
        sub.refresh_from_db()
        self.assertTrue(sub.cancel_at_period_end)
        self.assertEqual(sub.pending_plan, '')

    def test_request_downgrade_sets_pending_plan(self):
        """request_downgrade should set cancel_at_period_end=True and pending_plan."""
        sub = Subscription.objects.create(
            vendor=self.vendor,
            status='active',
            plan='premium',
            period_end=timezone.now() + timedelta(days=30),
        )
        subscription_service.downgrade_subscription(sub, 'basic')
        sub.refresh_from_db()
        self.assertTrue(sub.cancel_at_period_end)
        self.assertEqual(sub.pending_plan, 'basic')

    def test_downgrade_invalid_plan_raises(self):
        """Downgrade to invalid plan should raise error."""
        sub = Subscription.objects.create(vendor=self.vendor, plan='premium')
        with self.assertRaises(SubscriptionServiceError):
            subscription_service.downgrade_subscription(sub, 'invalid')

    def test_downgrade_to_premium_is_rejected(self):
        """pending_plan can only be '' or 'basic'; never 'premium'."""
        sub = Subscription.objects.create(
            vendor=self.vendor, plan='premium', status='active',
            period_end=timezone.now() + timedelta(days=30),
        )
        with self.assertRaises(SubscriptionServiceError):
            subscription_service.downgrade_subscription(sub, 'premium')
        sub.refresh_from_db()
        self.assertEqual(sub.pending_plan, '')
        self.assertFalse(sub.cancel_at_period_end)

    @patch('apps.vendors.services.subscription_service.SubscriptionService._request')
    def test_upgrade_disables_old_subscription(self, mock_request):
        """Basic -> premium upgrade disables the OLD Paystack subscription once."""
        mock_request.return_value = {'status': True, 'data': {}}

        sub = Subscription.objects.create(
            vendor=self.vendor,
            status='active',
            plan='basic',
            paystack_customer_code='cus_old',
            paystack_subscription_code='sub_basic_old',
            period_end=timezone.now() + timedelta(days=10),
        )

        changed = subscription_service.upgrade_subscription(sub, {
            'customer_code': 'cus_new',
            'subscription_code': 'sub_premium_new',
            'plan_code': 'PLN_premium',
        })

        self.assertTrue(changed)
        sub.refresh_from_db()
        self.assertEqual(sub.status, 'active')
        self.assertEqual(sub.plan, 'premium')
        self.assertEqual(sub.paystack_subscription_code, 'sub_premium_new')
        self.assertEqual(sub.paystack_customer_code, 'cus_new')

        disable_calls = [c for c in mock_request.call_args_list if 'disable' in c[0][1]]
        self.assertEqual(len(disable_calls), 1)
        self.assertEqual(disable_calls[0][0][1], '/subscription/sub_basic_old/disable')

    def test_upgrade_disable_failure_keeps_premium_and_logs_error(self):
        """If the old subscription cannot be disabled, Premium stays active."""
        def fake_request(method, endpoint, data=None):
            if endpoint.endswith('/disable'):
                raise SubscriptionServiceError('paystack 500')
            return {'status': True, 'data': {}}

        sub = Subscription.objects.create(
            vendor=self.vendor,
            status='active',
            plan='basic',
            paystack_subscription_code='sub_basic_old',
            period_end=timezone.now() + timedelta(days=10),
        )

        with patch.object(subscription_service, '_request', side_effect=fake_request):
            with self.assertLogs('apps.vendors.services.subscription_service', level='ERROR') as logs:
                changed = subscription_service.upgrade_subscription(sub, {
                    'customer_code': 'cus_new',
                    'subscription_code': 'sub_premium_new',
                    'plan_code': 'PLN_premium',
                })

        self.assertTrue(changed)
        sub.refresh_from_db()
        self.assertEqual(sub.status, 'active')
        self.assertEqual(sub.plan, 'premium')
        joined = '\n'.join(logs.output)
        self.assertIn('sub_basic_old', joined)
        self.assertIn(str(sub.pk), joined)

    @patch('apps.vendors.services.subscription_service.SubscriptionService._request')
    def test_upgrade_replay_changes_nothing(self, mock_request):
        """A duplicate upgrade charge must not re-disable or re-flip the plan."""
        mock_request.return_value = {'status': True, 'data': {}}

        sub = Subscription.objects.create(
            vendor=self.vendor,
            status='active',
            plan='basic',
            paystack_subscription_code='sub_basic_old',
            period_end=timezone.now() + timedelta(days=10),
        )
        payload = {
            'customer_code': 'cus_new',
            'subscription_code': 'sub_premium_new',
            'plan_code': 'PLN_premium',
        }

        self.assertTrue(subscription_service.upgrade_subscription(sub, payload))
        sub.refresh_from_db()
        period_after_first = sub.period_end

        self.assertFalse(subscription_service.upgrade_subscription(sub, payload))
        sub.refresh_from_db()
        self.assertEqual(sub.plan, 'premium')
        self.assertEqual(sub.period_end, period_after_first)

        disable_calls = [c for c in mock_request.call_args_list if 'disable' in c[0][1]]
        self.assertEqual(len(disable_calls), 1)

    @patch('apps.vendors.services.subscription_service.SubscriptionService._request')
    def test_first_time_subscribe_disables_nothing(self, mock_request):
        """First-time subscribe has no old Paystack code, so nothing is disabled."""
        mock_request.return_value = {'status': True, 'data': {}}

        sub = Subscription.objects.create(
            vendor=self.vendor,
            status='trial',
            plan='free',
            paystack_subscription_code='',
        )

        changed = subscription_service.activate_subscription(sub, {
            'customer_code': 'cus_new',
            'subscription_code': 'sub_basic_new',
            'plan_code': 'PLN_basic',
        }, plan='basic')

        self.assertTrue(changed)
        sub.refresh_from_db()
        self.assertEqual(sub.status, 'active')
        self.assertEqual(sub.plan, 'basic')
        self.assertEqual(sub.paystack_subscription_code, 'sub_basic_new')
        mock_request.assert_not_called()

    @patch('apps.vendors.services.subscription_service.SubscriptionService._request')
    def test_replayed_upgrade_webhook_disables_only_once(self, mock_request):
        """Two upgrade webhooks with different event ids -> one activation, one disable."""
        mock_request.return_value = {'status': True, 'data': {}}

        Subscription.objects.create(
            vendor=self.vendor,
            status='active',
            plan='basic',
            paystack_subscription_code='sub_basic_old',
            period_end=timezone.now() + timedelta(days=10),
        )

        with override_settings(PAYSTACK_PREMIUM_PLAN_CODE='PLN_premium'):
            data = {
                'metadata': {
                    'subscription_code': 'sub_premium_new',
                    'vendor_id': str(self.vendor.vendor_id),
                    'plan': 'premium',
                },
                'subscription': {'subscription_code': 'sub_premium_new'},
                'plan': {'plan_code': 'PLN_premium'},
                'customer': {'customer_code': 'cus_new'},
            }
            first = process_subscription_webhook('charge.success', data, event_id='evt_up_1')
            second = process_subscription_webhook('charge.success', data, event_id='evt_up_2')

        self.assertNotIn('replay', first['message'])
        self.assertIn('replay', second['message'])

        sub = Subscription.objects.filter(vendor=self.vendor).get()
        self.assertEqual(sub.plan, 'premium')
        self.assertEqual(sub.paystack_subscription_code, 'sub_premium_new')

        disable_calls = [c for c in mock_request.call_args_list if 'disable' in c[0][1]]
        self.assertEqual(len(disable_calls), 1)
        self.assertEqual(disable_calls[0][0][1], '/subscription/sub_basic_old/disable')

    @patch('apps.vendors.services.subscription_service.SubscriptionService._request')
    def test_upgrade_charge_for_non_basic_vendor_raises(self, mock_request):
        """A Premium charge for a vendor NOT on basic is rejected, row untouched."""
        sub = Subscription.objects.create(
            vendor=self.vendor,
            status='active',
            plan='premium',
            paystack_subscription_code='sub_premium_existing',
            period_end=timezone.now() + timedelta(days=10),
        )
        with self.assertRaises(SubscriptionServiceError):
            subscription_service.upgrade_subscription(sub, {
                'subscription_code': 'sub_premium_new',
                'plan_code': 'PLN_premium',
            })
        sub.refresh_from_db()
        self.assertEqual(sub.plan, 'premium')
        self.assertEqual(sub.paystack_subscription_code, 'sub_premium_existing')

    def test_expire_grace_periods_expires_past_due(self):
        """expire_grace_periods should expire past_due past grace period."""
        now = timezone.now()
        # Create a second vendor for the second subscription
        user2 = self.User.objects.create_user(
            email='vendor2@example.com',
            password='password123',
            username='vendor2',
            role='vendor',
        )
        vendor2 = user2.vendorprofile
        Subscription.objects.filter(vendor=vendor2).delete()

        sub1 = Subscription.objects.create(
            vendor=self.vendor,
            status='past_due',
            grace_ends_at=now - timedelta(days=1),
        )
        sub2 = Subscription.objects.create(
            vendor=vendor2,
            status='cancelled',
            grace_ends_at=now - timedelta(days=1),
        )

        count = subscription_service.expire_grace_periods()
        self.assertEqual(count, 2)
        sub1.refresh_from_db()
        sub2.refresh_from_db()
        self.assertEqual(sub1.status, 'expired')
        self.assertEqual(sub2.status, 'expired')

    def test_expire_grace_periods_expires_cancel_at_period_end(self):
        """expire_grace_periods should expire cancel_at_period_end past period_end directly."""
        now = timezone.now()
        sub = Subscription.objects.create(
            vendor=self.vendor,
            status='active',
            cancel_at_period_end=True,
            period_end=now - timedelta(days=1),
        )

        count = subscription_service.expire_grace_periods()
        self.assertEqual(count, 1)
        sub.refresh_from_db()
        self.assertEqual(sub.status, 'expired')
        self.assertFalse(sub.cancel_at_period_end)
        self.assertEqual(sub.pending_plan, '')

    def test_expire_does_not_reset_plan(self):
        """Expiry should not reset the plan field."""
        sub = Subscription.objects.create(
            vendor=self.vendor,
            status='active',
            plan='premium',
            cancel_at_period_end=True,
            period_end=timezone.now() - timedelta(days=1),
        )

        subscription_service.expire_grace_periods()
        sub.refresh_from_db()
        self.assertEqual(sub.status, 'expired')
        self.assertEqual(sub.plan, 'premium')  # Plan preserved


class SubscriptionOwnDisableWebhookTests(TestCase):
    """
    Phase 2C: events our own disable calls trigger must not undo a scheduled
    cancel, a disable event for a superseded (old) code must be ignored, and a
    Premium charge must activate even while the row is cancelling.
    Paystack is mocked throughout; no network access.
    """

    def setUp(self):
        self.User = get_user_model()
        self.user = self.User.objects.create_user(
            email='vendor_own_disable@example.com',
            password='password123',
            username='vendor_own_disable',
            role='vendor',
        )
        self.vendor = self.user.vendorprofile
        Subscription.objects.filter(vendor=self.vendor).delete()
        WebhookEvent.objects.all().delete()

    def make_basic(self, **overrides):
        fields = {
            'vendor': self.vendor,
            'status': 'active',
            'plan': 'basic',
            'paystack_subscription_code': 'sub_basic_1',
            'period_end': timezone.now() + timedelta(days=20),
        }
        fields.update(overrides)
        return Subscription.objects.create(**fields)

    @staticmethod
    def disable_payload(code):
        return {'subscription': {'subscription_code': code}}

    def snapshot(self, sub):
        return (
            sub.status, sub.plan, sub.period_end, sub.grace_ends_at,
            sub.paystack_subscription_code, sub.cancel_at_period_end, sub.pending_plan,
        )

    # ---- Task 1: our own disable events must not undo the schedule ----

    @patch('apps.vendors.services.subscription_service.SubscriptionService._request')
    def test_own_disable_webhook_keeps_scheduled_cancel(self, mock_request):
        """The disable event sent because WE cancelled must change nothing."""
        mock_request.return_value = {'status': True, 'data': {}}
        sub = self.make_basic()
        subscription_service.cancel_subscription(sub)
        sub.refresh_from_db()
        self.assertTrue(sub.cancel_at_period_end)
        before = self.snapshot(sub)

        result = process_subscription_webhook(
            'subscription.disable', self.disable_payload('sub_basic_1'),
            event_id='evt_own_dis_1',
        )

        self.assertTrue(result['success'])
        self.assertIn('scheduled to end', result['message'])
        sub.refresh_from_db()
        self.assertEqual(self.snapshot(sub), before)
        self.assertTrue(sub.cancel_at_period_end)
        self.assertIsNone(sub.grace_ends_at)
        self.assertEqual(sub.pending_plan, '')
        self.assertTrue(WebhookEvent.objects.filter(event_id='evt_own_dis_1').exists())

    @patch('apps.vendors.services.subscription_service.SubscriptionService._request')
    def test_own_not_renew_webhook_keeps_scheduled_cancel(self, mock_request):
        """subscription.not_renew for a row we already disabled: acknowledged only."""
        mock_request.return_value = {'status': True, 'data': {}}
        sub = self.make_basic()
        subscription_service.cancel_subscription(sub)
        sub.refresh_from_db()
        before = self.snapshot(sub)

        result = process_subscription_webhook(
            'subscription.not_renew', self.disable_payload('sub_basic_1'),
            event_id='evt_own_nr_1',
        )

        self.assertTrue(result['success'])
        self.assertIn('scheduled to end', result['message'])
        sub.refresh_from_db()
        self.assertEqual(self.snapshot(sub), before)
        self.assertTrue(sub.cancel_at_period_end)
        self.assertIsNone(sub.grace_ends_at)
        self.assertTrue(WebhookEvent.objects.filter(event_id='evt_own_nr_1').exists())

    def test_disable_webhook_without_scheduled_cancel_still_cancels(self):
        """A disable from outside our UI (no cancel scheduled) still cancels."""
        sub = self.make_basic(paystack_subscription_code='sub_basic_3')

        result = process_subscription_webhook(
            'subscription.disable', self.disable_payload('sub_basic_3'),
            event_id='evt_dis_3',
        )

        self.assertTrue(result['success'])
        sub.refresh_from_db()
        self.assertEqual(sub.status, 'cancelled')
        self.assertIsNotNone(sub.grace_ends_at)
        self.assertFalse(sub.cancel_at_period_end)
        self.assertEqual(sub.pending_plan, '')
        self.assertEqual(sub.plan, 'basic')
        self.assertTrue(WebhookEvent.objects.filter(event_id='evt_dis_3').exists())

    # ---- Task 2: a stale (superseded) code must be ignored ----

    @patch('apps.vendors.services.subscription_service.SubscriptionService._request')
    def test_disable_for_old_code_after_upgrade_is_ignored(self, mock_request):
        """Events for the old Basic code must not touch the upgraded Premium row."""
        mock_request.return_value = {'status': True, 'data': {}}
        sub = self.make_basic(paystack_subscription_code='sub_basic_old')
        self.assertTrue(subscription_service.upgrade_subscription(sub, {
            'customer_code': 'cus_new',
            'subscription_code': 'sub_premium_new',
            'plan_code': 'PLN_premium',
        }))
        sub.refresh_from_db()
        before = self.snapshot(sub)

        with self.assertLogs('apps.vendors.services.subscription_service', level='INFO') as logs:
            result = process_subscription_webhook(
                'subscription.disable', self.disable_payload('sub_basic_old'),
                event_id='evt_stale_dis_1',
            )

        self.assertTrue(result['success'])
        self.assertIn('non-current subscription code', result['message'])
        sub.refresh_from_db()
        self.assertEqual(self.snapshot(sub), before)
        self.assertEqual(sub.plan, 'premium')
        self.assertEqual(sub.paystack_subscription_code, 'sub_premium_new')
        self.assertTrue(WebhookEvent.objects.filter(event_id='evt_stale_dis_1').exists())
        self.assertIn(
            'ignored: event for non-current subscription code',
            '\n'.join(logs.output),
        )
        # the stale event must not trigger a second disable call
        disable_calls = [c for c in mock_request.call_args_list if 'disable' in c[0][1]]
        self.assertEqual(len(disable_calls), 1)

    # ---- Task 3: a Premium charge lands even while cancelling ----

    @override_settings(PAYSTACK_PREMIUM_PLAN_CODE='PLN_premium')
    def test_upgrade_while_cancelling_activates_without_error_log(self):
        """Cancelling basic vendor + Premium charge -> premium, no ERROR logged."""
        calls = []

        def fake_request(method, endpoint, data=None):
            calls.append(endpoint)
            if endpoint.endswith('/disable'):
                raise SubscriptionServiceError('paystack 500')
            return {'status': True, 'data': {}}

        sub = self.make_basic(
            paystack_subscription_code='sub_basic_cancel',
            cancel_at_period_end=True,
            pending_plan='basic',
        )
        data = {
            'metadata': {
                'subscription_code': 'sub_premium_new',
                'vendor_id': str(self.vendor.vendor_id),
                'plan': 'premium',
            },
            'subscription': {'subscription_code': 'sub_premium_new'},
            'plan': {'plan_code': 'PLN_premium'},
            'customer': {'customer_code': 'cus_new'},
        }

        with patch.object(subscription_service, '_request', side_effect=fake_request):
            with self.assertLogs('apps.vendors.services.subscription_service', level='INFO') as logs:
                result = process_subscription_webhook('charge.success', data, event_id='evt_up_cancel_1')

        self.assertTrue(result['success'])
        self.assertNotIn('replay', result['message'])
        sub.refresh_from_db()
        self.assertEqual(sub.plan, 'premium')
        self.assertEqual(sub.status, 'active')
        self.assertEqual(sub.paystack_subscription_code, 'sub_premium_new')
        self.assertFalse(sub.cancel_at_period_end)
        self.assertEqual(sub.pending_plan, '')
        self.assertIsNotNone(sub.period_end)
        # the old Basic code was still attempted, and its failure was INFO
        self.assertIn('/subscription/sub_basic_cancel/disable', calls)
        errors = [r.getMessage() for r in logs.records if r.levelno >= logging.ERROR]
        self.assertEqual(errors, [])
        self.assertTrue(any(
            r.levelno == logging.INFO
            and 'Failed to disable Paystack subscription sub_basic_cancel' in r.getMessage()
            for r in logs.records
        ))
        self.assertTrue(WebhookEvent.objects.filter(event_id='evt_up_cancel_1').exists())

    @override_settings(PAYSTACK_PREMIUM_PLAN_CODE='PLN_premium')
    def test_replay_of_upgrade_while_cancelling_changes_nothing(self):
        """A duplicate Premium charge for a row that is now premium is a replay."""
        calls = []

        def fake_request(method, endpoint, data=None):
            calls.append(endpoint)
            if endpoint.endswith('/disable'):
                raise SubscriptionServiceError('paystack 500')
            return {'status': True, 'data': {}}

        sub = self.make_basic(
            paystack_subscription_code='sub_basic_cancel',
            cancel_at_period_end=True,
            pending_plan='basic',
        )
        data = {
            'metadata': {
                'subscription_code': 'sub_premium_new',
                'vendor_id': str(self.vendor.vendor_id),
                'plan': 'premium',
            },
            'subscription': {'subscription_code': 'sub_premium_new'},
            'plan': {'plan_code': 'PLN_premium'},
            'customer': {'customer_code': 'cus_new'},
        }

        with patch.object(subscription_service, '_request', side_effect=fake_request):
            first = process_subscription_webhook('charge.success', data, event_id='evt_up_cancel_1')
            sub.refresh_from_db()
            before = self.snapshot(sub)
            second = process_subscription_webhook('charge.success', data, event_id='evt_up_cancel_2')

        self.assertNotIn('replay', first['message'])
        self.assertIn('replay', second['message'])
        sub.refresh_from_db()
        self.assertEqual(self.snapshot(sub), before)
        self.assertEqual(sub.plan, 'premium')
        disable_calls = [c for c in calls if 'disable' in c]
        self.assertEqual(len(disable_calls), 1)


    # ---- Phase 3, Task 0: tolerant subscription-code extraction ----

    @patch('apps.vendors.services.subscription_service.SubscriptionService._request')
    def test_top_level_and_nested_codes_behave_identically(self, mock_request):
        """data.subscription_code and data.subscription.subscription_code agree."""
        mock_request.return_value = {'status': True, 'data': {}}
        sub = self.make_basic()
        subscription_service.cancel_subscription(sub)
        sub.refresh_from_db()
        before = self.snapshot(sub)

        nested = process_subscription_webhook(
            'subscription.disable', self.disable_payload('sub_basic_1'),
            event_id='evt_code_nested',
        )
        top_level = process_subscription_webhook(
            'subscription.disable', {'subscription_code': 'sub_basic_1'},
            event_id='evt_code_top_level',
        )

        self.assertEqual(nested, top_level)
        self.assertTrue(nested['success'])
        self.assertIn('scheduled to end', nested['message'])
        sub.refresh_from_db()
        self.assertEqual(self.snapshot(sub), before)
        self.assertTrue(sub.cancel_at_period_end)
        self.assertEqual(
            WebhookEvent.objects.filter(event_type='subscription.disable').count(), 2,
        )

    def test_top_level_code_reaches_the_disable_path(self):
        """A top-level code is extracted well enough to reach disable_subscription."""
        sub = self.make_basic(paystack_subscription_code='sub_basic_top')

        result = process_subscription_webhook(
            'subscription.disable', {'subscription_code': 'sub_basic_top'},
            event_id='evt_code_top_disable',
        )

        self.assertTrue(result['success'])
        self.assertIn('processed', result['message'])
        sub.refresh_from_db()
        self.assertEqual(sub.status, 'cancelled')

    @patch('apps.vendors.services.subscription_service.SubscriptionService._request')
    def test_top_level_code_for_stale_subscription_is_ignored(self, mock_request):
        """The stale-code ignore rule works when the code is top-level."""
        mock_request.return_value = {'status': True, 'data': {}}
        sub = self.make_basic(paystack_subscription_code='sub_basic_old')
        self.assertTrue(subscription_service.upgrade_subscription(sub, {
            'customer_code': 'cus_new',
            'subscription_code': 'sub_premium_new',
            'plan_code': 'PLN_premium',
        }))
        sub.refresh_from_db()
        before = self.snapshot(sub)

        result = process_subscription_webhook(
            'subscription.disable', {'subscription_code': 'sub_basic_old'},
            event_id='evt_code_top_stale',
        )

        self.assertTrue(result['success'])
        self.assertIn('non-current subscription code', result['message'])
        sub.refresh_from_db()
        self.assertEqual(self.snapshot(sub), before)
        self.assertEqual(sub.plan, 'premium')


class SubscriptionViewsTests(TestCase):
    """Test subscription views with mocked Paystack."""

    def setUp(self):
        self.User = get_user_model()
        self.user = self.User.objects.create_user(
            email='vendor_admin@example.com',
            password='password123',
            username='vendor_admin',
            role='vendor',
        )
        self.vendor = self.user.vendorprofile
        Subscription.objects.filter(vendor=self.vendor).delete()
        self.category = MainCategory.objects.create(name='Tech', slug='tech')
        self.store = Store.objects.create(
            vendor=self.vendor,
            store_name='Test Store',
            slug='test-store',
            main_category=self.category,
        )

    def test_subscription_page_requires_login(self):
        """Anonymous users should be redirected to login."""
        response = self.client.get(reverse('vendors:subscription_plans'))
        self.assertEqual(response.status_code, 302)
        self.assertIn('/login/', response.url)

    def test_subscription_page_accessible_to_vendor(self):
        """Authenticated vendor can access subscription page."""
        self.client.force_login(self.user)
        response = self.client.get(reverse('vendors:subscription_plans'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Subscription Plans')

    def test_subscription_page_shows_three_cards(self):
        """Page should show Free, Basic, Premium cards."""
        self.client.force_login(self.user)
        response = self.client.get(reverse('vendors:subscription_plans'))
        self.assertContains(response, 'Free Plan')
        self.assertContains(response, 'Basic Plan')
        self.assertContains(response, 'Premium Plan')

    def test_subscription_page_shows_current_plan(self):
        """Page should indicate current plan."""
        sub = Subscription.objects.create(vendor=self.vendor, plan='basic')
        self.client.force_login(self.user)
        response = self.client.get(reverse('vendors:subscription_plans'))
        self.assertContains(response, 'Basic Plan')

    def test_subscription_page_shows_cancel_at_period_end_notice(self):
        """Page should show the mandated cancel-at-period-end notice."""
        sub = Subscription.objects.create(
            vendor=self.vendor,
            status='active',
            plan='basic',
            cancel_at_period_end=True,
            period_end=timezone.now() + timedelta(days=10),
        )
        self.client.force_login(self.user)
        response = self.client.get(reverse('vendors:subscription_plans'))
        self.assertContains(response, 'Your plan ends on')
        self.assertContains(response, 'No automatic charge will occur.')

    def test_subscription_page_shows_pending_plan_notice(self):
        """Page should show the switch-to-Basic notice when pending_plan == 'basic'."""
        sub = Subscription.objects.create(
            vendor=self.vendor,
            status='active',
            plan='premium',
            cancel_at_period_end=True,
            pending_plan='basic',
            period_end=timezone.now() + timedelta(days=10),
        )
        self.client.force_login(self.user)
        response = self.client.get(reverse('vendors:subscription_plans'))
        self.assertContains(
            response,
            'You chose to switch to Basic. Subscribe to Basic after your current period ends.',
        )

    def test_subscribe_rejects_invalid_plan(self):
        """Subscribe POST with invalid plan should show error."""
        self.client.force_login(self.user)
        response = self.client.post(reverse('vendors:subscription_subscribe'), {'plan': 'invalid'})
        self.assertEqual(response.status_code, 302)
        # Should redirect back with error message

    @patch('apps.vendors.services.subscription_service.subscription_service.initialize_subscription')
    def test_subscribe_redirects_to_paystack(self, mock_init):
        """Valid subscribe should redirect to Paystack auth URL."""
        mock_init.return_value = (True, {'authorization_url': 'https://paystack.com/pay/xyz'})
        self.client.force_login(self.user)
        response = self.client.post(reverse('vendors:subscription_subscribe'), {'plan': 'basic'})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, 'https://paystack.com/pay/xyz')

    @patch('apps.vendors.services.subscription_service.subscription_service.initialize_subscription')
    def test_subscribe_handles_config_error(self, mock_init):
        """Configuration error should show friendly message."""
        from apps.vendors.services.subscription_service import SubscriptionServiceError
        mock_init.side_effect = SubscriptionServiceError('Paystack plan code not configured')
        self.client.force_login(self.user)
        response = self.client.post(reverse('vendors:subscription_subscribe'), {'plan': 'basic'})
        self.assertEqual(response.status_code, 302)
        # Should redirect back with error

    def test_cancel_requires_post(self):
        """Cancel view should reject GET."""
        self.client.force_login(self.user)
        response = self.client.get(reverse('vendors:subscription_cancel'))
        self.assertEqual(response.status_code, 405)

    def test_downgrade_requires_post(self):
        """Downgrade view should reject GET."""
        self.client.force_login(self.user)
        response = self.client.get(reverse('vendors:subscription_downgrade'))
        self.assertEqual(response.status_code, 405)

    def test_cancel_requires_active_subscription(self):
        """Cancel should fail if no active subscription."""
        self.client.force_login(self.user)
        response = self.client.post(reverse('vendors:subscription_cancel'))
        self.assertEqual(response.status_code, 302)

    def test_downgrade_only_from_premium(self):
        """Downgrade should only work from Premium."""
        sub = Subscription.objects.create(vendor=self.vendor, plan='basic')
        self.client.force_login(self.user)
        response = self.client.post(reverse('vendors:subscription_downgrade'))
        self.assertEqual(response.status_code, 302)

    def test_anonymous_redirected_for_state_changing(self):
        """Anonymous users redirected for subscribe/cancel/downgrade."""
        for url_name in ['vendors:subscription_subscribe', 'vendors:subscription_cancel', 'vendors:subscription_downgrade']:
            response = self.client.post(reverse(url_name), {'plan': 'basic'})
            self.assertEqual(response.status_code, 302)
            self.assertIn('/login/', response.url)

    def test_buyer_blocked(self):
        """Buyers should be blocked by vendor_required decorator."""
        buyer_user = get_user_model().objects.create_user(
            email='buyer@example.com',
            password='password123',
            username='buyer',
            role='buyer',
        )
        self.client.force_login(buyer_user)
        response = self.client.get(reverse('vendors:subscription_plans'))
        # vendor_required redirects non-vendors
        self.assertEqual(response.status_code, 302)


class AdminSubscriptionTests(TestCase):
    """Test SubscriptionAdmin configuration."""

    def setUp(self):
        self.User = get_user_model()
        self.superuser = self.User.objects.create_superuser(
            email='admin@example.com',
            password='password123',
        )
        self.user = self.User.objects.create_user(
            email='vendor_admin@example.com',
            password='password123',
            username='vendor_admin',
            role='vendor',
        )
        self.vendor = self.user.vendorprofile
        Subscription.objects.filter(vendor=self.vendor).delete()

    def test_admin_list_display_includes_new_fields(self):
        """Admin list_display should include plan, cancel_at_period_end."""
        from apps.vendors.admin import SubscriptionAdmin
        self.assertIn('plan', SubscriptionAdmin.list_display)
        self.assertIn('cancel_at_period_end', SubscriptionAdmin.list_display)

    def test_admin_list_filter_includes_new_fields(self):
        """Admin list_filter should include plan, cancel_at_period_end."""
        from apps.vendors.admin import SubscriptionAdmin
        self.assertIn('plan', SubscriptionAdmin.list_filter)
        self.assertIn('cancel_at_period_end', SubscriptionAdmin.list_filter)

    def test_superuser_has_delete_permission(self):
        """Superuser should have delete permission."""
        from apps.vendors.admin import SubscriptionAdmin
        from django.contrib import admin
        request = MagicMock()
        request.user = self.superuser
        admin = SubscriptionAdmin(Subscription, admin.site)
        self.assertTrue(admin.has_delete_permission(request))

    def test_non_superuser_has_no_delete_permission(self):
        """Non-superuser should not have delete permission."""
        from apps.vendors.admin import SubscriptionAdmin
        from django.contrib import admin
        request = MagicMock()
        request.user = self.user
        admin = SubscriptionAdmin(Subscription, admin.site)
        self.assertFalse(admin.has_delete_permission(request))

    def test_admin_shows_clean_error(self):
        """Admin should display clean() validation error for invalid active sub."""
        from apps.vendors.admin import SubscriptionAdmin
        from django.contrib.admin.helpers import InlineAdminFormSet

        sub = Subscription.objects.create(
            vendor=self.vendor,
            status='active',
            period_end=None,
        )

        # The clean() error should be raised when saving via admin
        # Test that the model's clean() is called
        with self.assertRaises(ValidationError):
            sub.full_clean()

    def _admin_instance(self):
        from apps.vendors.admin import SubscriptionAdmin
        return SubscriptionAdmin(Subscription, django_admin.site)

    def test_change_form_base_fields_include_plan_fields(self):
        """(a) get_form().base_fields for the change view exposes the plan fields."""
        sub = Subscription.objects.create(
            vendor=self.vendor, status='trial', plan='free',
            trial_ends_at=timezone.now() + timedelta(days=30),
        )
        model_admin = self._admin_instance()
        request = RequestFactory().get('/admin/vendors/subscription/%s/change/' % sub.pk)
        request.user = self.superuser

        form_class = model_admin.get_form(request, obj=sub, fields=None, change=True)
        base_fields = set(form_class.base_fields)

        print('\nSubscriptionAdmin change-form base_fields: %s' % sorted(base_fields))
        for field in ['plan', 'cancel_at_period_end', 'pending_plan', 'status',
                      'trial_ends_at', 'period_end', 'grace_ends_at']:
            self.assertIn(field, base_fields)

    def test_admin_post_active_without_period_end_is_rejected(self):
        """(b) Admin POST with status=active and empty period_end -> 200 + clean() error, row unchanged."""
        sub = Subscription.objects.create(
            vendor=self.vendor, status='trial', plan='free',
            trial_ends_at=timezone.now() + timedelta(days=30),
        )
        self.client.force_login(self.superuser)

        response = self.client.post(
            reverse('admin:vendors_subscription_change', args=[sub.pk]),
            {
                'status': 'active',
                'plan': 'basic',
                'cancel_at_period_end': False,
                'pending_plan': '',
                'trial_ends_at': (timezone.now() + timedelta(days=30)).strftime('%Y-%m-%d %H:%M:%S'),
                'period_end': '',
                'grace_ends_at': '',
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Active subscriptions must have a period_end date.')

        sub.refresh_from_db()
        self.assertEqual(sub.status, 'trial')
        self.assertIsNone(sub.period_end)
        self.assertEqual(sub.plan, 'free')

    def test_non_superuser_staff_delete_view_forbidden(self):
        """(c) Staff non-superuser gets 403 on the delete view and the row survives."""
        sub = Subscription.objects.create(
            vendor=self.vendor, status='trial', plan='free',
            trial_ends_at=timezone.now() + timedelta(days=30),
        )
        staff = self.User.objects.create_user(
            email='staff@example.com',
            password='password123',
            username='staff',
            role='admin',
            is_staff=True,
        )
        self.assertFalse(staff.is_superuser)

        self.client.force_login(staff)
        response = self.client.get(
            reverse('admin:vendors_subscription_delete', args=[sub.pk])
        )
        print('\nnon-superuser staff GET delete view -> HTTP %s' % response.status_code)
        self.assertEqual(response.status_code, 403)
        self.assertTrue(Subscription.objects.filter(pk=sub.pk).exists())

    def test_superuser_delete_view_allowed(self):
        """(c) Superuser can delete through the admin."""
        sub = Subscription.objects.create(
            vendor=self.vendor, status='trial', plan='free',
            trial_ends_at=timezone.now() + timedelta(days=30),
        )
        self.client.force_login(self.superuser)
        response = self.client.post(
            reverse('admin:vendors_subscription_delete', args=[sub.pk]),
            {'post': 'yes'},
        )
        print('\nsuperuser POST delete view -> HTTP %s' % response.status_code)
        self.assertIn(response.status_code, (200, 302))
        self.assertFalse(Subscription.objects.filter(pk=sub.pk).exists())


class VerifyWebhookSignatureTests(TestCase):
    """Test webhook signature verification."""

    def setUp(self):
        import os
        self.secret = 'test_secret'
        os.environ['PAYSTACK_SECRET_KEY'] = self.secret

    def tearDown(self):
        import os
        if 'PAYSTACK_SECRET_KEY' in os.environ:
            del os.environ['PAYSTACK_SECRET_KEY']

    def test_verify_valid_signature(self):
        """Valid HMAC signature should verify."""
        payload = b'{"event":"charge.success","data":{}}'
        expected = hmac.new(self.secret.encode('utf-8'), payload, hashlib.sha512).hexdigest()
        self.assertTrue(verify_subscription_webhook_signature(payload, expected))

    def test_verify_invalid_signature(self):
        """Invalid signature should fail."""
        payload = b'{"event":"charge.success"}'
        self.assertFalse(verify_subscription_webhook_signature(payload, 'invalid_signature'))

    def test_verify_missing_secret_logs_warning(self):
        """Missing secret key should log warning and return False."""
        import logging
        import os
        # Remove the secret temporarily
        del os.environ['PAYSTACK_SECRET_KEY']
        with self.assertLogs('apps.vendors.services.subscription_service', level='WARNING'):
            result = verify_subscription_webhook_signature(b'{}', 'sig')
        self.assertFalse(result)
        # Restore for tearDown
        os.environ['PAYSTACK_SECRET_KEY'] = self.secret


# Import needed modules for tests
import hmac
import hashlib
from unittest.mock import MagicMock


# ---------------------------------------------------------------------------
# Real-shape callback tests.
#
# The fixtures below copy the ACTUAL structure returned by Paystack's
# /transaction/verify endpoint in TEST mode (reference T674579335914694,
# captured 2026-10-03, and T344654379974387 for premium).  What matters:
#
#   * `plan` is a STRING plan code ("PLN_..."), never a dict
#   * `metadata` echoes only what checkout sent: vendor_id + plan
#     (there is NO subscription_code - we never send one)
#   * there is NO `subscription` key anywhere in the payload
#   * `customer` carries both `customer_code` and the numeric `id`, and the
#     GET /subscription customer filter only honours the numeric id
#
# No Paystack network call is made: verify is patched, and the subscription
# lookup is patched with the real /subscription response shape.
# ---------------------------------------------------------------------------

BASIC_PLAN_CODE = 'PLN_1xqxk3rzgsp9dgb'
PREMIUM_PLAN_CODE = 'PLN_it3camcsx4yjb8y'


class RealShapeSubscriptionCallbackTests(TestCase):
    """Callback driven by a real Paystack TEST verify response shape."""

    def setUp(self):
        self.User = get_user_model()
        self.user = self.User.objects.create_user(
            email='vendor_realshape@example.com',
            password='password123',
            username='vendor_realshape',
            role='vendor',
        )
        self.vendor = self.user.vendorprofile
        Subscription.objects.filter(vendor=self.vendor).delete()
        self.category = MainCategory.objects.create(name='RealTech', slug='realtech')
        self.store = Store.objects.create(
            vendor=self.vendor,
            store_name='RealShape Store',
            slug='realshape-store',
            main_category=self.category,
        )
        WebhookEvent.objects.all().delete()
        self.client.force_login(self.user)
        self.lookup_calls = []

    # -- fixtures ---------------------------------------------------------

    def real_verify(self, **overrides):
        """Real verify payload for a BASIC plan charge (120000 kobo)."""
        txn = {
            'amount': 120000,
            'channel': 'card',
            'currency': 'NGN',
            'customer': {
                'customer_code': 'CUS_dai6p1aijshoxvx',
                'email': self.user.email,
                'first_name': 'Remedy',
                'id': 405395500,
                'last_name': 'Longkat',
                'phone': '',
            },
            'domain': 'test',
            'gateway_response': 'Successful',
            'id': 3184567890,
            'ip_address': '127.0.0.1',
            'metadata': {
                'plan': 'basic',
                'vendor_id': str(self.vendor.vendor_id),
            },
            'paid_at': '2026-10-03T08:17:28.000Z',
            'created_at': '2026-10-03T08:17:16.000Z',
            'plan': BASIC_PLAN_CODE,  # STRING, not a dict
            'plan_object': {
                'amount': 120000,
                'currency': 'NGN',
                'interval': 'monthly',
                'name': 'KasuMarketplace Basic Plan',
                'plan_code': BASIC_PLAN_CODE,
            },
            'reference': 'T674579335914694',
            'requested_amount': 120000,
            'status': 'success',
            'transaction_date': '2026-10-03T08:17:16.000Z',
            # Real responses carry NO 'subscription' key at all.
        }
        txn.update(overrides)
        return txn

    def premium_verify(self, **overrides):
        """Real verify payload for a PREMIUM plan charge (300000 kobo)."""
        txn = self.real_verify(
            amount=300000,
            requested_amount=300000,
            plan=PREMIUM_PLAN_CODE,
            reference='T344654379974387',
            paid_at='2026-10-04T15:49:33.000Z',
            created_at='2026-10-04T15:49:25.000Z',
            metadata={
                'plan': 'premium',
                'vendor_id': str(self.vendor.vendor_id),
            },
        )
        txn['plan_object'] = {
            'amount': 300000,
            'currency': 'NGN',
            'interval': 'monthly',
            'name': 'KasuMarketplace Premium Plan',
            'plan_code': PREMIUM_PLAN_CODE,
        }
        txn.update(overrides)
        return txn

    def subscription_list(self):
        """Real GET /subscription data for customer 405395500 (both plans)."""
        return [
            {
                'subscription_code': 'SUB_ol9jrnqrdkcut21',
                'plan': {
                    'plan_code': PREMIUM_PLAN_CODE,
                    'amount': 300000,
                    'interval': 'monthly',
                    'name': 'KasuMarketplace Premium Plan',
                },
                'customer': {
                    'customer_code': 'CUS_dai6p1aijshoxvx',
                    'id': 405395500,
                    'email': self.user.email,
                },
                'amount': 300000,
                'status': 'active',
                'domain': 'test',
            },
            {
                'subscription_code': 'SUB_62l5lwtnfhb8qnk',
                'plan': {
                    'plan_code': BASIC_PLAN_CODE,
                    'amount': 120000,
                    'interval': 'monthly',
                    'name': 'KasuMarketplace Basic Plan',
                },
                'customer': {
                    'customer_code': 'CUS_dai6p1aijshoxvx',
                    'id': 405395500,
                    'email': self.user.email,
                },
                'amount': 120000,
                'status': 'active',
                'domain': 'test',
            },
        ]

    def verify_patch(self, txn):
        return patch.object(subscription_service, 'verify_transaction', return_value=txn)

    def lookup_patch(self, subscriptions=None):
        """Patch the Paystack HTTP layer with the real /subscription shape."""
        payload = self.subscription_list() if subscriptions is None else subscriptions

        def fake_request(method, endpoint, data=None):
            self.lookup_calls.append((method, endpoint, data))
            if endpoint == '/subscription':
                return payload
            if endpoint.endswith('/disable'):
                return {'status': True, 'message': 'Subscription disabled'}
            return {'status': True, 'data': {}}

        return patch.object(subscription_service, '_request', side_effect=fake_request)

    def hit_callback(self, reference, follow=True):
        return self.client.get(
            reverse('vendors:subscription_callback'),
            {'reference': reference, 'trxref': reference},
            follow=follow,
        )

    def messages_of(self, response):
        return [str(m) for m in get_messages(response.wsgi_request)]

    # -- plan + amount helpers -------------------------------------------

    def test_plan_code_from_transaction_accepts_both_shapes(self):
        from apps.vendors.services.subscription_service import plan_code_from_transaction
        self.assertEqual(plan_code_from_transaction({'plan': BASIC_PLAN_CODE}), BASIC_PLAN_CODE)
        self.assertEqual(plan_code_from_transaction({'plan': {'plan_code': 'PLN_x'}}), 'PLN_x')
        self.assertEqual(plan_code_from_transaction({'plan': None}), '')
        self.assertEqual(plan_code_from_transaction({}), '')

    def test_resolve_prefers_metadata_and_skips_the_lookup(self):
        txn = self.real_verify(metadata={
            'vendor_id': str(self.vendor.vendor_id),
            'plan': 'basic',
            'subscription_code': 'SUB_from_metadata',
        })
        with self.lookup_patch():
            code, source = subscription_service.resolve_subscription_code(txn, BASIC_PLAN_CODE)
        self.assertEqual((code, source), ('SUB_from_metadata', 'metadata'))
        self.assertEqual(self.lookup_calls, [])

    def test_resolve_uses_customer_numeric_id_and_plan_code(self):
        with self.lookup_patch():
            code, source = subscription_service.resolve_subscription_code(
                self.real_verify(), BASIC_PLAN_CODE,
            )
        self.assertEqual(code, 'SUB_62l5lwtnfhb8qnk')
        self.assertEqual(source, 'paystack_api')
        self.assertEqual(
            self.lookup_calls, [('GET', '/subscription', {'customer': 405395500})],
        )

    # -- activation -------------------------------------------------------

    @override_settings(
        PAYSTACK_BASIC_PLAN_CODE=BASIC_PLAN_CODE,
        PAYSTACK_PREMIUM_PLAN_CODE=PREMIUM_PLAN_CODE,
    )
    def test_basic_payment_with_real_shape_activates_basic(self):
        sub = Subscription.objects.create(
            vendor=self.vendor, status='qualifying', plan='free',
        )
        with self.verify_patch(self.real_verify()), self.lookup_patch():
            response = self.hit_callback('T674579335914694')

        self.assertEqual(response.redirect_chain[0][1], 302)
        sub.refresh_from_db()
        self.assertEqual(sub.status, 'active')
        self.assertEqual(sub.plan, 'basic')
        self.assertEqual(sub.paystack_subscription_code, 'SUB_62l5lwtnfhb8qnk')
        self.assertEqual(sub.paystack_plan_code, BASIC_PLAN_CODE)
        self.assertEqual(sub.paystack_customer_code, 'CUS_dai6p1aijshoxvx')
        self.assertEqual(sub.qualification_status, 'skipped')
        self.assertTrue(
            WebhookEvent.objects.filter(event_id='callback_T674579335914694').exists()
        )
        msgs = self.messages_of(response)
        self.assertTrue(any('Subscription activated successfully' in m for m in msgs), msgs)

    @override_settings(
        PAYSTACK_BASIC_PLAN_CODE=BASIC_PLAN_CODE,
        PAYSTACK_PREMIUM_PLAN_CODE=PREMIUM_PLAN_CODE,
    )
    def test_premium_payment_with_real_shape_activates_premium(self):
        sub = Subscription.objects.create(
            vendor=self.vendor, status='qualifying', plan='free',
        )
        with self.verify_patch(self.premium_verify()), self.lookup_patch():
            response = self.hit_callback('T344654379974387')

        self.assertEqual(response.redirect_chain[0][1], 302)
        sub.refresh_from_db()
        self.assertEqual(sub.status, 'active')
        self.assertEqual(sub.plan, 'premium')
        self.assertEqual(sub.paystack_subscription_code, 'SUB_ol9jrnqrdkcut21')
        self.assertEqual(sub.paystack_plan_code, PREMIUM_PLAN_CODE)
        msgs = self.messages_of(response)
        self.assertTrue(any('Subscription activated successfully' in m for m in msgs), msgs)

    @override_settings(
        PAYSTACK_BASIC_PLAN_CODE=BASIC_PLAN_CODE,
        PAYSTACK_PREMIUM_PLAN_CODE=PREMIUM_PLAN_CODE,
    )
    def test_reloading_the_callback_is_idempotent(self):
        sub = Subscription.objects.create(
            vendor=self.vendor, status='qualifying', plan='free',
        )
        with self.verify_patch(self.real_verify()), self.lookup_patch():
            first = self.hit_callback('T674579335914694')
        sub.refresh_from_db()
        period_after_first = sub.period_end
        self.assertEqual(sub.plan, 'basic')

        with self.verify_patch(self.real_verify()), self.lookup_patch():
            second = self.hit_callback('T674579335914694')

        sub.refresh_from_db()
        self.assertEqual(sub.status, 'active')
        self.assertEqual(sub.plan, 'basic')
        self.assertEqual(sub.period_end, period_after_first)
        self.assertEqual(WebhookEvent.objects.filter(event_id='callback_T674579335914694').count(), 1)
        msgs = self.messages_of(second)
        self.assertTrue(any('already applied' in m for m in msgs), msgs)

    @override_settings(
        PAYSTACK_BASIC_PLAN_CODE=BASIC_PLAN_CODE,
        PAYSTACK_PREMIUM_PLAN_CODE=PREMIUM_PLAN_CODE,
    )
    def test_paying_the_same_plan_again_is_a_friendly_no_op(self):
        sub = Subscription.objects.create(
            vendor=self.vendor, status='active', plan='basic',
            paystack_subscription_code='SUB_62l5lwtnfhb8qnk',
            paystack_plan_code=BASIC_PLAN_CODE,
            period_end=timezone.now() + timedelta(days=20),
        )
        before = sub.period_end

        with self.verify_patch(self.real_verify()), self.lookup_patch():
            response = self.hit_callback('T674579335914694')

        sub.refresh_from_db()
        self.assertEqual(sub.status, 'active')
        self.assertEqual(sub.plan, 'basic')
        self.assertEqual(sub.period_end, before)
        self.assertEqual(sub.paystack_subscription_code, 'SUB_62l5lwtnfhb8qnk')
        msgs = self.messages_of(response)
        self.assertTrue(any('already have an active Basic Plan subscription' in m for m in msgs), msgs)
        self.assertTrue(
            WebhookEvent.objects.filter(event_id='callback_T674579335914694').exists()
        )

    @override_settings(
        PAYSTACK_BASIC_PLAN_CODE=BASIC_PLAN_CODE,
        PAYSTACK_PREMIUM_PLAN_CODE=PREMIUM_PLAN_CODE,
    )
    def test_basic_to_premium_upgrade_with_real_shape(self):
        sub = Subscription.objects.create(
            vendor=self.vendor, status='active', plan='basic',
            paystack_subscription_code='SUB_basic_old',
            paystack_plan_code=BASIC_PLAN_CODE,
            period_end=timezone.now() + timedelta(days=10),
        )
        with self.verify_patch(self.premium_verify()), self.lookup_patch():
            response = self.hit_callback('T344654379974387')

        sub.refresh_from_db()
        self.assertEqual(sub.status, 'active')
        self.assertEqual(sub.plan, 'premium')
        self.assertEqual(sub.paystack_subscription_code, 'SUB_ol9jrnqrdkcut21')
        self.assertEqual(sub.paystack_plan_code, PREMIUM_PLAN_CODE)
        disable_calls = [c for c in self.lookup_calls if c[1].endswith('/disable')]
        self.assertEqual(len(disable_calls), 1)
        self.assertEqual(disable_calls[0][1], '/subscription/SUB_basic_old/disable')
        msgs = self.messages_of(response)
        self.assertTrue(any('Subscription activated successfully' in m for m in msgs), msgs)

    # -- rejections -------------------------------------------------------

    @override_settings(
        PAYSTACK_BASIC_PLAN_CODE=BASIC_PLAN_CODE,
        PAYSTACK_PREMIUM_PLAN_CODE=PREMIUM_PLAN_CODE,
    )
    def test_unknown_reference_is_rejected_without_activation(self):
        sub = Subscription.objects.create(
            vendor=self.vendor, status='qualifying', plan='free',
        )
        with patch.object(
            subscription_service, 'verify_transaction',
            side_effect=SubscriptionServiceError('Transaction reference not found'),
        ):
            response = self.hit_callback('T000000000000000')

        sub.refresh_from_db()
        self.assertEqual(sub.status, 'qualifying')
        self.assertEqual(sub.plan, 'free')
        self.assertEqual(sub.paystack_subscription_code, '')
        self.assertFalse(WebhookEvent.objects.exists())
        msgs = self.messages_of(response)
        self.assertTrue(any('Unable to verify payment' in m for m in msgs), msgs)

    @override_settings(
        PAYSTACK_BASIC_PLAN_CODE=BASIC_PLAN_CODE,
        PAYSTACK_PREMIUM_PLAN_CODE=PREMIUM_PLAN_CODE,
    )
    def test_charge_without_a_plan_is_rejected(self):
        """A successful non-plan charge (normal Paystack payment) must not activate."""
        sub = Subscription.objects.create(
            vendor=self.vendor, status='qualifying', plan='free',
        )
        txn = self.real_verify(
            plan=None,
            metadata={},
            amount=50000,
            reference='T111111111111111',
        )
        with self.verify_patch(txn), self.lookup_patch():
            response = self.hit_callback('T111111111111111')

        sub.refresh_from_db()
        self.assertEqual(sub.status, 'qualifying')
        self.assertEqual(sub.plan, 'free')
        self.assertEqual(sub.paystack_subscription_code, '')
        self.assertFalse(WebhookEvent.objects.exists())
        msgs = self.messages_of(response)
        self.assertTrue(any('could not be matched' in m for m in msgs), msgs)

    @override_settings(
        PAYSTACK_BASIC_PLAN_CODE=BASIC_PLAN_CODE,
        PAYSTACK_PREMIUM_PLAN_CODE=PREMIUM_PLAN_CODE,
    )
    def test_amount_mismatch_is_rejected(self):
        sub = Subscription.objects.create(
            vendor=self.vendor, status='qualifying', plan='free',
        )
        txn = self.real_verify(amount=50000, requested_amount=50000)
        with self.verify_patch(txn), self.lookup_patch():
            response = self.hit_callback('T674579335914694')

        sub.refresh_from_db()
        self.assertEqual(sub.status, 'qualifying')
        self.assertEqual(sub.plan, 'free')
        self.assertEqual(sub.paystack_subscription_code, '')
        self.assertFalse(WebhookEvent.objects.exists())
        msgs = self.messages_of(response)
        self.assertTrue(any('amount paid does not match' in m for m in msgs), msgs)

    @override_settings(
        PAYSTACK_BASIC_PLAN_CODE=BASIC_PLAN_CODE,
        PAYSTACK_PREMIUM_PLAN_CODE=PREMIUM_PLAN_CODE,
    )
    def test_plan_mismatch_is_rejected(self):
        """Premium plan code + basic metadata plan = inconsistent, reject."""
        sub = Subscription.objects.create(
            vendor=self.vendor, status='qualifying', plan='free',
        )
        txn = self.premium_verify(metadata={
            'plan': 'basic',
            'vendor_id': str(self.vendor.vendor_id),
        })
        with self.verify_patch(txn), self.lookup_patch():
            response = self.hit_callback('T344654379974387')

        sub.refresh_from_db()
        self.assertEqual(sub.status, 'qualifying')
        self.assertEqual(sub.plan, 'free')
        self.assertFalse(WebhookEvent.objects.exists())
        msgs = self.messages_of(response)
        self.assertTrue(any('could not be matched' in m for m in msgs), msgs)

    @override_settings(
        PAYSTACK_BASIC_PLAN_CODE=BASIC_PLAN_CODE,
        PAYSTACK_PREMIUM_PLAN_CODE=PREMIUM_PLAN_CODE,
    )
    def test_logged_in_vendor_mismatch_is_rejected(self):
        other = self.User.objects.create_user(
            email='other_realshape@example.com',
            password='password123',
            username='other_realshape',
            role='vendor',
        )
        sub = Subscription.objects.create(
            vendor=self.vendor, status='qualifying', plan='free',
        )
        txn = self.real_verify(metadata={
            'plan': 'basic',
            'vendor_id': str(other.vendorprofile.vendor_id),
        })
        with self.verify_patch(txn), self.lookup_patch():
            response = self.hit_callback('T674579335914694')

        sub.refresh_from_db()
        self.assertEqual(sub.status, 'qualifying')
        self.assertEqual(sub.plan, 'free')
        self.assertFalse(WebhookEvent.objects.exists())
        msgs = self.messages_of(response)
        self.assertTrue(any('does not belong to your account' in m for m in msgs), msgs)

    @override_settings(
        PAYSTACK_BASIC_PLAN_CODE=BASIC_PLAN_CODE,
        PAYSTACK_PREMIUM_PLAN_CODE=PREMIUM_PLAN_CODE,
    )
    def test_reference_not_created_by_this_session_is_rejected(self):
        sub = Subscription.objects.create(
            vendor=self.vendor, status='qualifying', plan='free',
        )
        session = self.client.session
        session['pending_subscription_references'] = ['T999999999999999']
        session.save()

        with self.verify_patch(self.real_verify()), self.lookup_patch():
            response = self.hit_callback('T674579335914694')

        sub.refresh_from_db()
        self.assertEqual(sub.status, 'qualifying')
        self.assertEqual(sub.plan, 'free')
        self.assertFalse(WebhookEvent.objects.exists())
        msgs = self.messages_of(response)
        self.assertTrue(any('does not belong to your account' in m for m in msgs), msgs)

    @override_settings(
        PAYSTACK_BASIC_PLAN_CODE=BASIC_PLAN_CODE,
        PAYSTACK_PREMIUM_PLAN_CODE=PREMIUM_PLAN_CODE,
    )
    def test_subscription_not_created_yet_is_reported_not_applied(self):
        sub = Subscription.objects.create(
            vendor=self.vendor, status='qualifying', plan='free',
        )
        with self.verify_patch(self.real_verify()), self.lookup_patch(subscriptions=[]):
            response = self.hit_callback('T674579335914694')

        sub.refresh_from_db()
        self.assertEqual(sub.status, 'qualifying')
        self.assertEqual(sub.plan, 'free')
        self.assertFalse(WebhookEvent.objects.exists())
        msgs = self.messages_of(response)
        self.assertTrue(any('not applied yet' in m for m in msgs), msgs)

    @override_settings(
        PAYSTACK_BASIC_PLAN_CODE=BASIC_PLAN_CODE,
        PAYSTACK_PREMIUM_PLAN_CODE=PREMIUM_PLAN_CODE,
    )
    def test_pending_transaction_reports_pending(self):
        sub = Subscription.objects.create(
            vendor=self.vendor, status='qualifying', plan='free',
        )
        txn = self.real_verify(status='pending')
        with self.verify_patch(txn), self.lookup_patch():
            response = self.hit_callback('T674579335914694')

        sub.refresh_from_db()
        self.assertEqual(sub.status, 'qualifying')
        self.assertFalse(WebhookEvent.objects.exists())
        msgs = self.messages_of(response)
        self.assertTrue(any('still pending' in m for m in msgs), msgs)

    @override_settings(
        PAYSTACK_BASIC_PLAN_CODE=BASIC_PLAN_CODE,
        PAYSTACK_PREMIUM_PLAN_CODE=PREMIUM_PLAN_CODE,
    )
    def test_subscribe_stores_the_reference_for_the_callback(self):
        """checkout remembers the reference it created, keyed to this session."""
        with patch.object(
            subscription_service, 'initialize_subscription',
            return_value=(True, {
                'authorization_url': 'https://checkout.paystack.com/abc',
                'reference': 'T222222222222222',
            }),
        ):
            response = self.client.post(
                reverse('vendors:subscription_subscribe'), {'plan': 'basic'},
            )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            self.client.session.get('pending_subscription_references'),
            ['T222222222222222'],
        )


@override_settings(
    PAYSTACK_BASIC_PLAN_CODE=BASIC_PLAN_CODE,
    PAYSTACK_PREMIUM_PLAN_CODE=PREMIUM_PLAN_CODE,
)
class WebhookRealPayloadTests(TestCase):
    """
    Phase 2D (webhook parity): subscription events in the shape Paystack
    really sends - `plan` as a STRING plan code, metadata that echoes only
    {plan, vendor_id}, NO `subscription` key anywhere, and a customer
    carrying customer_code + email + numeric id.
    """

    def setUp(self):
        self.User = get_user_model()
        self.user = self.User.objects.create_user(
            email='vendor_realwh@example.com',
            password='password123',
            username='vendor_realwh',
            role='vendor',
        )
        self.vendor = self.user.vendorprofile
        Subscription.objects.filter(vendor=self.vendor).delete()
        self.category = MainCategory.objects.create(name='RealWH', slug='realwh')
        self.store = Store.objects.create(
            vendor=self.vendor,
            store_name='RealWH Store',
            slug='realwh-store',
            main_category=self.category,
        )
        WebhookEvent.objects.all().delete()
        self.client.force_login(self.user)

    def charge(self, **overrides):
        """A real charge.success payload: plan string, no subscription key."""
        data = {
            'reference': 'T261006000000001',
            'amount': 120000,
            'status': 'success',
            'plan': BASIC_PLAN_CODE,
            'customer': {
                'customer_code': 'CUS_realwh',
                'email': self.user.email,
                'id': 405395500,
            },
            'metadata': {'plan': 'basic', 'vendor_id': str(self.vendor.vendor_id)},
        }
        data.update(overrides)
        return data

    def paystack(self, subscriptions=None):
        """Patch the Paystack HTTP layer (lookup + disable); no network."""
        payload = subscriptions or [{
            'subscription_code': 'SUB_realwh_1',
            'plan': {'plan_code': BASIC_PLAN_CODE, 'amount': 120000, 'interval': 'monthly'},
            'customer': {'customer_code': 'CUS_realwh', 'id': 405395500},
            'status': 'active',
            'created_at': '2026-10-01T10:00:00.000Z',
        }]

        def fake_request(method, endpoint, data=None):
            if endpoint == '/subscription':
                return payload
            if endpoint.endswith('/disable'):
                return {'status': True, 'message': 'Subscription disabled'}
            return {'status': True, 'data': {}}

        return patch.object(subscription_service, '_request', side_effect=fake_request)

    def verify_txn(self, reference):
        """The matching real /transaction/verify response for this charge."""
        return {
            'status': 'success',
            'reference': reference,
            'amount': 120000,
            'plan': BASIC_PLAN_CODE,
            'customer': {
                'customer_code': 'CUS_realwh',
                'email': self.user.email,
                'id': 405395500,
            },
            'metadata': {'plan': 'basic', 'vendor_id': str(self.vendor.vendor_id)},
        }

    def make_active_basic(self, **overrides):
        """An active Basic row; returns (row, period_end read from the DB)."""
        fields = {
            'vendor': self.vendor,
            'status': 'active',
            'plan': 'basic',
            'paystack_subscription_code': 'SUB_realwh_1',
            'paystack_customer_code': 'CUS_realwh',
            'paystack_plan_code': BASIC_PLAN_CODE,
            'period_end': timezone.now() + timedelta(days=10),
        }
        fields.update(overrides)
        sub = Subscription.objects.create(**fields)
        sub.refresh_from_db()
        return sub, sub.period_end

    def test_first_charge_activates_through_vendor_id(self):
        """First charge: no subscription key, matched by metadata.vendor_id."""
        sub = Subscription.objects.create(
            vendor=self.vendor, status='trial', plan='free',
            trial_ends_at=timezone.now() + timedelta(days=14),
        )
        with self.paystack():
            result = process_subscription_webhook(
                'charge.success', self.charge(), event_id='evt_real_first',
            )

        sub.refresh_from_db()
        self.assertTrue(result['success'], result)
        self.assertEqual(sub.status, 'active')
        self.assertEqual(sub.plan, 'basic')
        self.assertEqual(sub.paystack_subscription_code, 'SUB_realwh_1')
        self.assertEqual(sub.paystack_customer_code, 'CUS_realwh')
        self.assertEqual(sub.paystack_plan_code, BASIC_PLAN_CODE)
        self.assertIsNotNone(sub.period_end)
        self.assertTrue(WebhookEvent.objects.filter(
            event_id='evt_real_first', reference='T261006000000001',
        ).exists())

    def test_renewal_extends_period_end_once(self):
        sub, period = self.make_active_basic()
        data = self.charge(reference='T261006000000002')
        with self.paystack():
            result = process_subscription_webhook('charge.success', data, event_id='evt_real_renew')

        sub.refresh_from_db()
        self.assertTrue(result['success'], result)
        self.assertEqual(sub.status, 'active')
        self.assertEqual(sub.plan, 'basic')
        self.assertEqual(sub.period_end, period + timedelta(days=30))
        self.assertEqual(sub.paystack_subscription_code, 'SUB_realwh_1')

    def test_same_webhook_delivered_twice_is_a_no_op(self):
        sub, period = self.make_active_basic()
        data = self.charge(reference='T261006000000003')
        with self.paystack():
            first = process_subscription_webhook('charge.success', data, event_id='evt_real_twice_1')
            sub.refresh_from_db()
            renewed_to = sub.period_end
            second = process_subscription_webhook('charge.success', data, event_id='evt_real_twice_2')

        sub.refresh_from_db()
        self.assertTrue(first['success'], first)
        self.assertNotEqual(renewed_to, period)
        self.assertTrue(second['success'], second)
        self.assertIn('replay', second['message'])
        self.assertEqual(sub.period_end, renewed_to)
        self.assertEqual(sub.plan, 'basic')

    def test_zero_row_match_logs_warning_and_changes_nothing(self):
        sub, period = self.make_active_basic()
        data = self.charge(
            metadata={'plan': 'basic'},
            customer={'customer_code': 'CUS_nope', 'email': 'stranger@example.com', 'id': 99},
        )
        with self.assertLogs('apps.vendors.services.subscription_service', level='WARNING') as logs:
            with self.paystack():
                result = process_subscription_webhook('charge.success', data, event_id='evt_real_zero')

        sub.refresh_from_db()
        self.assertFalse(result['success'], result)
        self.assertIn('no unique match', '\n'.join(logs.output))
        self.assertEqual((sub.status, sub.plan, sub.period_end), ('active', 'basic', period))
        self.assertFalse(WebhookEvent.objects.filter(event_id='evt_real_zero').exists())

    def test_two_row_match_logs_warning_and_changes_nothing(self):
        sub, period = self.make_active_basic()
        other_user = self.User.objects.create_user(
            email='vendor_realwh_two@example.com', password='password123',
            username='vendor_realwh_two', role='vendor',
        )
        Subscription.objects.filter(vendor=other_user.vendorprofile).update(
            status='active', plan='basic',
            paystack_subscription_code='SUB_other_1',
            paystack_customer_code='CUS_realwh',
            paystack_plan_code=BASIC_PLAN_CODE,
            period_end=timezone.now() + timedelta(days=10),
        )
        data = self.charge(metadata={'plan': 'basic'})
        with self.assertLogs('apps.vendors.services.subscription_service', level='WARNING') as logs:
            with self.paystack():
                result = process_subscription_webhook(
                    'charge.success', data, event_id='evt_real_two_rows',
                )

        sub.refresh_from_db()
        self.assertFalse(result['success'], result)
        self.assertIn('no unique match', '\n'.join(logs.output))
        self.assertEqual((sub.status, sub.plan, sub.period_end), ('active', 'basic', period))
        self.assertFalse(WebhookEvent.objects.filter(event_id='evt_real_two_rows').exists())

    def test_renewal_matches_by_email_and_plan_when_code_is_empty(self):
        sub, period = self.make_active_basic(paystack_customer_code='')
        data = self.charge(metadata={'plan': 'basic'})
        with self.paystack():
            result = process_subscription_webhook('charge.success', data, event_id='evt_real_email')

        sub.refresh_from_db()
        self.assertTrue(result['success'], result)
        self.assertEqual(sub.status, 'active')
        self.assertEqual(sub.plan, 'basic')
        self.assertEqual(sub.period_end, period + timedelta(days=30))
        self.assertEqual(sub.paystack_customer_code, 'CUS_realwh')

    def test_subscription_create_links_identifiers_without_activating(self):
        sub = Subscription.objects.create(
            vendor=self.vendor, status='trial', plan='free',
            trial_ends_at=timezone.now() + timedelta(days=14),
        )
        data = self.charge(reference='T261006000000006', subscription_code='SUB_created_1')
        with self.paystack():
            result = process_subscription_webhook('subscription.create', data, event_id='evt_real_create')

        sub.refresh_from_db()
        self.assertTrue(result['success'], result)
        self.assertEqual(sub.status, 'trial')
        self.assertEqual(sub.plan, 'free')
        self.assertIsNone(sub.period_end)
        self.assertEqual(sub.paystack_subscription_code, 'SUB_created_1')
        self.assertEqual(sub.paystack_customer_code, 'CUS_realwh')
        self.assertEqual(sub.paystack_plan_code, BASIC_PLAN_CODE)
        self.assertTrue(WebhookEvent.objects.filter(event_id='evt_real_create').exists())

    def test_invoice_payment_failed_is_unchanged(self):
        from apps.vendors.models import Notification
        sub, _period = self.make_active_basic()
        with self.paystack():
            result = process_subscription_webhook(
                'invoice.payment_failed',
                {'subscription_code': 'SUB_realwh_1', 'amount': 120000},
                event_id='evt_real_failed',
            )

        sub.refresh_from_db()
        self.assertTrue(result['success'], result)
        self.assertEqual(sub.status, 'past_due')
        self.assertEqual(sub.retry_count, 1)
        self.assertIsNotNone(sub.grace_ends_at)
        self.assertEqual(sub.plan, 'basic')
        self.assertTrue(Notification.objects.filter(
            user=self.user, title__startswith='Payment Failed',
        ).exists())
        self.assertTrue(WebhookEvent.objects.filter(event_id='evt_real_failed').exists())

    def test_subscription_disable_is_unchanged(self):
        sub, _period = self.make_active_basic()
        with self.paystack():
            result = process_subscription_webhook(
                'subscription.disable',
                {'subscription': {'subscription_code': 'SUB_realwh_1'}},
                event_id='evt_real_disable',
            )

        sub.refresh_from_db()
        self.assertTrue(result['success'], result)
        self.assertIn('processed', result['message'])
        self.assertEqual(sub.status, 'cancelled')
        self.assertIsNotNone(sub.grace_ends_at)
        self.assertEqual(sub.plan, 'basic')
        self.assertTrue(WebhookEvent.objects.filter(event_id='evt_real_disable').exists())

    def test_subscription_not_renew_is_unchanged(self):
        sub, period = self.make_active_basic()
        with self.paystack():
            result = process_subscription_webhook(
                'subscription.not_renew',
                {'subscription': {'subscription_code': 'SUB_realwh_1'}},
                event_id='evt_real_not_renew',
            )

        sub.refresh_from_db()
        self.assertTrue(result['success'], result)
        self.assertIn('acknowledged', result['message'])
        self.assertEqual((sub.status, sub.plan, sub.period_end), ('active', 'basic', period))
        self.assertFalse(sub.cancel_at_period_end)
        self.assertTrue(WebhookEvent.objects.filter(event_id='evt_real_not_renew').exists())

    def test_bad_signature_returns_400_and_changes_nothing(self):
        import json
        sub, period = self.make_active_basic()
        response = self.client.post(
            reverse('vendors:subscription_webhook'),
            data=json.dumps({'event': 'charge.success', 'data': self.charge()}),
            content_type='application/json',
            HTTP_X_PAYSTACK_SIGNATURE='bad-signature',
        )

        sub.refresh_from_db()
        self.assertEqual(response.status_code, 400)
        self.assertEqual((sub.status, sub.plan, sub.period_end), ('active', 'basic', period))
        self.assertFalse(WebhookEvent.objects.exists())

    def test_callback_then_webhook_activates_exactly_once(self):
        sub = Subscription.objects.create(
            vendor=self.vendor, status='trial', plan='free',
            trial_ends_at=timezone.now() + timedelta(days=14),
        )
        reference = 'T261006000000009'
        with patch.object(subscription_service, 'verify_transaction', return_value=self.verify_txn(reference)):
            with self.paystack():
                response = self.client.get(
                    reverse('vendors:subscription_callback'), {'reference': reference},
                )

        self.assertEqual(response.status_code, 302)
        sub.refresh_from_db()
        self.assertEqual(sub.status, 'active')
        self.assertEqual(sub.plan, 'basic')
        period_after_callback = sub.period_end
        self.assertIsNotNone(period_after_callback)

        with self.paystack():
            result = process_subscription_webhook(
                'charge.success', self.charge(reference=reference), event_id='evt_real_after_cb',
            )

        self.assertIn('replay', result['message'])
        sub.refresh_from_db()
        self.assertEqual(sub.plan, 'basic')
        self.assertEqual(sub.period_end, period_after_callback)

    def test_webhook_then_callback_activates_exactly_once(self):
        sub = Subscription.objects.create(
            vendor=self.vendor, status='trial', plan='free',
            trial_ends_at=timezone.now() + timedelta(days=14),
        )
        reference = 'T261006000000010'
        with self.paystack():
            first = process_subscription_webhook(
                'charge.success', self.charge(reference=reference), event_id='evt_real_before_cb',
            )

        sub.refresh_from_db()
        self.assertEqual(sub.status, 'active')
        self.assertEqual(sub.plan, 'basic')
        self.assertNotIn('replay', first['message'])
        period_after_webhook = sub.period_end

        with patch.object(subscription_service, 'verify_transaction', return_value=self.verify_txn(reference)):
            with self.paystack():
                response = self.client.get(
                    reverse('vendors:subscription_callback'), {'reference': reference}, follow=True,
                )

        self.assertEqual(response.status_code, 200)
        sub.refresh_from_db()
        self.assertEqual(sub.status, 'active')
        self.assertEqual(sub.plan, 'basic')
        self.assertEqual(sub.period_end, period_after_webhook)
        msgs = [str(m) for m in get_messages(response.wsgi_request)]
        self.assertTrue(
            any('already have an active Basic Plan subscription' in m for m in msgs), msgs,
        )
