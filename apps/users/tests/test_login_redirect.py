from django.contrib.auth import get_user_model
from django.contrib.messages.middleware import MessageMiddleware
from django.contrib.sessions.middleware import SessionMiddleware
from django.test import RequestFactory, TestCase
from django.urls import reverse

from apps.users.adapters import KasuAccountAdapter
from apps.users.services import OTPService


class VendorLoginRedirectTests(TestCase):
    """Vendors must always land on vendors:dashboard after authentication.

    The ``next`` parameter must be ignored for role == 'vendor'; buyers keep
    the existing safe-``next`` behaviour unchanged.
    """

    def setUp(self):
        self.User = get_user_model()
        self.vendor = self.User.objects.create(
            email='vendor-next@example.com',
            role='vendor',
            is_active=True,
            is_verified=True,
        )
        self.vendor.set_password('Password123!')
        self.vendor.save()

        self.buyer = self.User.objects.create(
            email='buyer-next@example.com',
            role='buyer',
            is_active=True,
            is_verified=True,
        )
        self.buyer.set_password('Password123!')
        self.buyer.save()

        self.dashboard = reverse('vendors:dashboard')
        self.buyer_dashboard = reverse('users:buyer_dashboard')

    def _post_login(self, user, extra=None):
        data = {'email': user.email, 'password': 'Password123!'}
        if extra:
            data.update(extra)
        return self.client.post(reverse('users:login'), data)

    def test_vendor_login_with_next_marketplace_page_goes_to_dashboard(self):
        response = self._post_login(self.vendor, {'next': '/about/'})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response['Location'], self.dashboard)

    def test_vendor_login_with_next_vendor_page_goes_to_dashboard(self):
        next_url = reverse('vendors:product_create')
        response = self._post_login(self.vendor, {'next': next_url})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response['Location'], self.dashboard)

    def test_authenticated_vendor_get_login_with_next_goes_to_dashboard(self):
        self.client.force_login(self.vendor)
        next_url = reverse('vendors:product_create')
        response = self.client.get(
            f"{reverse('users:login')}?next={next_url}"
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response['Location'], self.dashboard)

    def test_buyer_login_honors_safe_next(self):
        response = self._post_login(self.buyer, {'next': '/about/'})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response['Location'], '/about/')

    def test_buyer_login_unsafe_next_falls_back_to_dashboard(self):
        response = self._post_login(
            self.buyer, {'next': 'https://evil.example.com/phish'}
        )
        self.assertEqual(response.status_code, 302)
        self.assertFalse(response['Location'].startswith('http'))
        self.assertEqual(response['Location'], self.buyer_dashboard)

    def test_vendor_login_without_next_goes_to_dashboard(self):
        response = self._post_login(self.vendor)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response['Location'], self.dashboard)


class OtpCompletionRedirectTests(TestCase):
    """OTP verification completion must also land vendors on the dashboard."""

    def setUp(self):
        self.User = get_user_model()
        self.vendor = self.User.objects.create(
            email='vendor-otp-next@example.com',
            role='vendor',
            is_active=True,
            is_verified=False,
        )
        self.vendor.set_password('Password123!')
        self.vendor.save()
        self.dashboard = reverse('vendors:dashboard')

    def test_otp_completion_redirects_vendor_to_dashboard(self):
        otp_instance, otp_code = OTPService.create_otp(self.vendor)
        self.assertIsNotNone(otp_instance)

        session = self.client.session
        session['verify_email'] = self.vendor.email
        session.save()

        response = self.client.post(reverse('users:verify_otp'), {
            'otp_code': otp_code,
        })
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response['Location'], self.dashboard)

        self.vendor.refresh_from_db()
        self.assertTrue(self.vendor.is_verified)


class AllauthAdapterRedirectTests(TestCase):
    """Social / allauth login path: the account adapter must send vendors to
    the dashboard even when allauth resolved a ``next`` URL first.

    Mirrors the adapter-level pattern in test_social_signup.py.
    """

    def setUp(self):
        self.User = get_user_model()
        self.factory = RequestFactory()
        self.adapter = KasuAccountAdapter()

        self.vendor = self.User.objects.create(
            email='vendor-allauth@example.com',
            role='vendor',
            is_active=True,
            is_verified=True,
        )
        self.vendor.set_password('Password123!')
        self.vendor.save()

        self.buyer = self.User.objects.create(
            email='buyer-allauth@example.com',
            role='buyer',
            is_active=True,
            is_verified=True,
        )
        self.buyer.set_password('Password123!')
        self.buyer.save()

        self.dashboard = reverse('vendors:dashboard')

    def _make_request(self, user):
        request = self.factory.get('/accounts/login/')
        # allauth calls post_login after adapter.login(), so request.user is
        # already the authenticated user at that point.
        request.user = user
        SessionMiddleware(lambda req: None).process_request(request)
        request.session.save()
        MessageMiddleware(lambda req: None).process_request(request)
        return request

    def _post_login(self, request, user, redirect_url):
        return self.adapter.post_login(
            request,
            user,
            email_verification=None,
            signal_kwargs=None,
            email=None,
            signup=False,
            redirect_url=redirect_url,
        )

    def test_vendor_post_login_ignores_next(self):
        request = self._make_request(self.vendor)
        response = self._post_login(request, self.vendor, '/about/')
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response['Location'], self.dashboard)

    def test_buyer_post_login_keeps_next_behaviour(self):
        request = self._make_request(self.buyer)
        response = self._post_login(request, self.buyer, '/about/')
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response['Location'], '/about/')
