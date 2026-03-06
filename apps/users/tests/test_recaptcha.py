from django.test import TestCase, override_settings
from django.conf import settings
from django.urls import reverse
from django.contrib.auth import get_user_model

from apps.users.forms import BuyerSignupForm, LoginForm

from unittest.mock import patch


class ReCaptchaFormTests(TestCase):
    """Verify backend enforcement of the "I'm not a robot" challenge."""

    def setUp(self):
        # make sure dummy keys exist as they do in .env by default
        self.old_public = getattr(settings, 'RECAPTCHA_PUBLIC_KEY', None)
        self.old_private = getattr(settings, 'RECAPTCHA_PRIVATE_KEY', None)
        settings.RECAPTCHA_PUBLIC_KEY = '6LeIxAcTAAAAAJcZVRqyHh71UMIEGNQ_MXjiZKhI'
        settings.RECAPTCHA_PRIVATE_KEY = '6LeIxAcTAAAAAGG-vFI1TnRWxMZNFuojJ4WifJWe'

    def tearDown(self):
        settings.RECAPTCHA_PUBLIC_KEY = self.old_public
        settings.RECAPTCHA_PRIVATE_KEY = self.old_private

    def test_signup_form_rejects_missing_token(self):
        form = BuyerSignupForm(data={
            'email': 'foo@example.com',
            'password1': 'Password123!',
            'password2': 'Password123!',
            'recaptcha': '',
        })
        self.assertFalse(form.is_valid())
        self.assertIn('recaptcha', form.errors)

    def test_signup_form_calls_validator(self):
        form = BuyerSignupForm(data={
            'email': 'bar@example.com',
            'password1': 'Password123!',
            'password2': 'Password123!',
            'recaptcha': 'token',
        })
        with patch.object(BuyerSignupForm, '_validate_recaptcha', return_value=False) as mock:
            self.assertFalse(form.is_valid())
            mock.assert_called_once_with('token')

    def test_login_form_rejects_missing_token(self):
        # create a valid user so authentication passes when recaptcha is removed
        User = get_user_model()
        user = User.objects.create(email='login@test.com', role='buyer', is_active=True, is_verified=True)
        user.set_password('Password123!')
        user.save()

        form = LoginForm(data={
            'email': 'login@test.com',
            'password': 'Password123!',
            'recaptcha': '',
        })
        self.assertFalse(form.is_valid())
        self.assertIn('recaptcha', form.errors)

    def test_login_form_validator_used(self):
        User = get_user_model()
        user = User.objects.create(email='login2@test.com', role='buyer', is_active=True, is_verified=True)
        user.set_password('Password123!')
        user.save()

        form = LoginForm(data={
            'email': 'login2@test.com',
            'password': 'Password123!',
            'recaptcha': 'abc',
        })
        with patch.object(LoginForm, '_validate_recaptcha', return_value=False) as mock:
            self.assertFalse(form.is_valid())
            mock.assert_called_once_with('abc')


class ReCaptchaViewTests(TestCase):
    """Check that the widget is rendered and that server rejects posts."""

    def setUp(self):
        settings.RECAPTCHA_PUBLIC_KEY = 'public'
        settings.RECAPTCHA_PRIVATE_KEY = 'private'
        User = get_user_model()
        self.user = User.objects.create(email='v@test.com', role='buyer', is_active=True, is_verified=True)
        self.user.set_password('Password123!')
        self.user.save()

    def test_signup_page_contains_widget(self):
        resp = self.client.get(reverse('users:buyer_signup'))
        self.assertContains(resp, 'g-recaptcha')
        self.assertContains(resp, 'data-callback="onRecaptchaSuccess"')
        self.assertContains(resp, 'id="submitButton"')
        # initial state should be disabled until challenge completes
        self.assertContains(resp, 'disabled')

    def test_login_page_contains_widget(self):
        resp = self.client.get(reverse('users:login'))
        self.assertContains(resp, 'g-recaptcha')
        self.assertContains(resp, 'id="submitButton"')
        self.assertContains(resp, 'disabled')

    def test_signup_view_rejects_without_token(self):
        resp = self.client.post(reverse('users:buyer_signup'), {
            'email': 'x@ya.com',
            'password1': 'Password123!',
            'password2': 'Password123!',
            'recaptcha': '',
        })
        self.assertEqual(resp.status_code, 200)
        form = resp.context.get('form')
        self.assertIsNotNone(form, "form should be in context")
        self.assertIn('recaptcha', form.errors)
        self.assertEqual(form.errors['recaptcha'], ['reCAPTCHA validation failed.'])

    def test_signup_view_allows_with_valid_token(self):
        # patch validation to avoid external call
        with patch.object(BuyerSignupForm, '_validate_recaptcha', return_value=True):
            resp = self.client.post(reverse('users:buyer_signup'), {
                'email': 'y@ya.com',
                'password1': 'Password123!',
                'password2': 'Password123!',
                'recaptcha': 'goodtoken',
            })
        # successful registration -> redirect to otp page
        self.assertEqual(resp.status_code, 302)

    def test_login_view_rejects_without_token(self):
        resp = self.client.post(reverse('users:login'), {
            'email': 'v@test.com',
            'password': 'Password123!',
            'recaptcha': '',
        })
        self.assertEqual(resp.status_code, 200)
        form = resp.context.get('form')
        self.assertIsNotNone(form, "form should be in context")
        self.assertIn('recaptcha', form.errors)
        self.assertEqual(form.errors['recaptcha'], ['reCAPTCHA validation failed.'])

    def test_login_view_allows_with_valid_token(self):
        with patch.object(LoginForm, '_validate_recaptcha', return_value=True):
            resp = self.client.post(reverse('users:login'), {
                'email': 'v@test.com',
                'password': 'Password123!',
                'recaptcha': 'tok',
            })
        self.assertEqual(resp.status_code, 302)

    def test_validate_recaptcha_calls_google(self):
        from apps.users.forms import BuyerSignupForm
        form = BuyerSignupForm()
        with patch('apps.users.forms.requests.post') as mock_post:
            mock_post.return_value.json.return_value = {'success': True}
            self.assertTrue(form._validate_recaptcha('token'))
            mock_post.assert_called_once()
