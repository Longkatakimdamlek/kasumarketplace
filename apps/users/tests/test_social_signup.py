from django.test import TestCase, RequestFactory
from django.conf import settings
from django.contrib.auth import get_user_model
from allauth.socialaccount.models import SocialLogin, SocialAccount
from apps.users.adapters import SocialAccountAdapter


class SocialSignupTests(TestCase):
    def setUp(self):
        self.rf = RequestFactory()
        self.adapter = SocialAccountAdapter()

    def _make_request_with_session(self, path='/', session_data=None):
        request = self.rf.get(path)
        # attach minimal user so adapters/signals expecting request.user work
        from django.contrib.auth.models import AnonymousUser
        request.user = AnonymousUser()
        # RequestFactory doesn't provide a session by default; use middleware stub.
        from django.contrib.sessions.middleware import SessionMiddleware
        middleware = SessionMiddleware(lambda req: None)
        middleware.process_request(request)
        request.session.save()
        if session_data:
            for k, v in session_data.items():
                request.session[k] = v
            request.session.save()
        return request

    def test_vendor_role_assigned_in_populate_user(self):
        request = self._make_request_with_session(session_data={'signup_role': 'vendor'})
        user = get_user_model()()
        account = SocialAccount(provider='google', uid='123')
        sociallogin = SocialLogin(user=user, account=account)
        data = {'email': 'vendor@example.com'}

        populated = self.adapter.populate_user(request, sociallogin, data)
        # role should be set before save
        self.assertEqual(populated.role, 'vendor')

    def test_save_user_creates_vendor_profile_and_redirect(self):
        request = self._make_request_with_session(session_data={'signup_role': 'vendor'})
        User = get_user_model()
        # prepare sociallogin with minimal attributes
        user = User(email='vendor@example.com')
        account = SocialAccount(provider='google', uid='456')
        sociallogin = SocialLogin(user=user, account=account)
        # call adapter save_user
        saved = self.adapter.save_user(request, sociallogin, form=None)
        # user should now be saved and vendor
        self.assertTrue(saved.pk, "User should be saved to DB")
        self.assertTrue(saved.is_vendor)
        # vendor profile should exist
        self.assertTrue(hasattr(saved, 'vendorprofile'))

    def test_get_login_redirect_url_based_on_role(self):
        # anonymous request for vendor
        request = self._make_request_with_session()
        User = get_user_model()
        vendor = User.objects.create(email='v@example.com', role='vendor')
        request.user = vendor
        url = self.adapter.get_login_redirect_url(request)
        self.assertIn('vendors:dashboard', url)

        buyer = User.objects.create(email='b@example.com', role='buyer')
        request.user = buyer
        url = self.adapter.get_login_redirect_url(request)
        self.assertIn('users:buyer_dashboard', url)

        # fallback when role unknown
        other = User.objects.create(email='o@example.com', role='')
        request.user = other
        url = self.adapter.get_login_redirect_url(request)
        self.assertEqual(url, settings.LOGIN_REDIRECT_URL)

    def test_signals_do_not_downgrade_vendor(self):
        # simulate social signup flow where adapter already set vendor role
        request = self._make_request_with_session(session_data={'signup_role': 'vendor'})
        User = get_user_model()
        user = User(email='vendor2@example.com')
        account = SocialAccount(provider='google', uid='9999')
        sociallogin = SocialLogin(user=user, account=account)
        # adapter creates/saves user
        saved = self.adapter.save_user(request, sociallogin, form=None)
        # now explicitly invoke the social signup signal handler
        from apps.users.signals import assign_role_on_social_signup
        assign_role_on_social_signup(request, sociallogin)
        # role should remain vendor
        self.assertEqual(sociallogin.user.role, 'vendor')

    def test_conflicting_role_on_social_signup(self):
        """Attempting opposite-role social signup should be blocked."""
        request = self._make_request_with_session(session_data={'signup_role': 'vendor'})
        User = get_user_model()
        existing = User.objects.create(
            email='conflict@example.com',
            role='buyer',
            is_active=True,
            is_verified=True
        )
        # try to sign up as vendor using same email
        user = User(email='conflict@example.com')
        account = SocialAccount(provider='google', uid='1234')
        sociallogin = SocialLogin(user=user, account=account)
        from allauth.exceptions import ImmediateHttpResponse
        from django.contrib.auth.models import AnonymousUser
        with self.assertRaises(ImmediateHttpResponse) as cm:
            self.adapter.pre_social_login(request, sociallogin)
        resp = cm.exception.response
        # should redirect to login page with error
        self.assertEqual(resp.url, '/login/')
        # the adapter should have logged out the request if it had been
        # authenticated (ensures we don't accidentally keep users logged in)
        self.assertIsInstance(request.user, AnonymousUser)
        # existing role should remain untouched
        existing.refresh_from_db()
        self.assertEqual(existing.role, 'buyer')

    def test_form_signup_collision(self):
        """Regular signup form should raise validation error if email exists."""
        User = get_user_model()
        User.objects.create(email='taken@example.com', role='vendor')
        from apps.users.forms import BuyerSignupForm
        form = BuyerSignupForm(data={'email': 'taken@example.com','password1':'Password123!','password2':'Password123!'})
        self.assertFalse(form.is_valid())
        self.assertIn('email', form.errors)


class LoginRoleTests(TestCase):
    """Ensure explicit login does not flip user role to buyer."""
    def setUp(self):
        self.client = self.client_class()
        self.User = get_user_model()

    def test_vendor_login_does_not_change_role(self):
        # create a vendor user with password
        user = self.User.objects.create(
            email='vendorlogin@example.com',
            role='vendor',
            is_active=True,
            is_verified=True
        )
        user.set_password('Password123!')
        user.save()
        # ensure vendorprofile exists (signals may have created it, use get_or_create)
        from apps.vendors.models import VendorProfile
        VendorProfile.objects.get_or_create(user=user)

        # login via the normal form
        response = self.client.post(
            '/login/',
            {'email': 'vendorlogin@example.com', 'password': 'Password123!'}
        )
        # after login we should be redirected to vendor dashboard
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response['Location'].endswith('/vendors/dashboard/'))

        # refresh from db and confirm role still vendor
        user.refresh_from_db()
        self.assertEqual(user.role, 'vendor')

    def test_session_signup_role_cleared_on_login(self):
        # simulate lingering signup_role in session
        session = self.client.session
        session['signup_role'] = 'vendor'
        session.save()

        user = self.User.objects.create(
            email='clearrole@example.com',
            role='buyer',
            is_active=True,
            is_verified=True
        )
        user.set_password('Password123!')
        user.save()

        self.client.post(
            '/login/',
            {'email': 'clearrole@example.com', 'password': 'Password123!'}
        )
        # after login the session should no longer contain the key
        session = self.client.session
        self.assertNotIn('signup_role', session)
