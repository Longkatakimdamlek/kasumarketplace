from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
from django.http import Http404
from django.test import Client, RequestFactory, TestCase, override_settings
from unittest import mock

from KasuMarketplace import error_views


@override_settings(DEBUG=False, SECURE_SSL_REDIRECT=False)
class ErrorPageTests(TestCase):
    """Branded error pages render correctly, safely and role-aware."""

    def setUp(self):
        self.User = get_user_model()
        self.factory = RequestFactory()

    # ------------------------------------------------------------------ 1
    def test_unknown_url_renders_branded_404(self):
        response = self.client.get("/this-page-does-not-exist-xyz/")
        self.assertEqual(response.status_code, 404)
        content = response.content.decode()
        self.assertIn("We can't find that page", content)
        self.assertIn("Go to Marketplace", content)

    # ------------------------------------------------------------------ 2
    def test_404_primary_button_is_role_aware(self):
        vendor = self.User.objects.create_user(
            email="vendor-err@example.com",
            password="Password123!",
            username="vendor-err",
            role="vendor",
        )
        buyer = self.User.objects.create_user(
            email="buyer-err@example.com",
            password="Password123!",
            username="buyer-err",
            role="buyer",
        )

        self.client.force_login(vendor)
        response = self.client.get("/this-page-does-not-exist-xyz-2/")
        self.assertEqual(response.status_code, 404)
        self.assertIn("Go to your dashboard", response.content.decode())
        self.client.logout()

        self.client.force_login(buyer)
        response = self.client.get("/this-page-does-not-exist-xyz-3/")
        self.assertEqual(response.status_code, 404)
        self.assertIn("Go to Marketplace", response.content.decode())

    # ------------------------------------------------------------------ 3
    def test_404_ajax_returns_json(self):
        response = self.client.get(
            "/this-page-does-not-exist-xyz-4/",
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(response.status_code, 404)
        self.assertIn("application/json", response["Content-Type"])
        data = response.json()
        self.assertFalse(data["success"])
        self.assertIn("error", data)

    # ------------------------------------------------------------------ 4
    def test_server_error_renders_500_html(self):
        request = self.factory.get("/")
        request.user = AnonymousUser()
        response = error_views.server_error(request)
        self.assertEqual(response.status_code, 500)
        content = response.content.decode()
        self.assertIn("Something went wrong on our side", content)

    # ------------------------------------------------------------------ 5
    def test_server_error_survives_reverse_failure(self):
        request = self.factory.get("/")
        request.user = AnonymousUser()
        with mock.patch(
            "KasuMarketplace.error_views.reverse", side_effect=Exception("boom")
        ):
            response = error_views.server_error(request)
        self.assertEqual(response.status_code, 500)
        content = response.content.decode()
        self.assertIn('href="/"', content)

    # ------------------------------------------------------------------ 6
    def test_csrf_failure_renders_branded_page(self):
        client = Client(enforce_csrf_checks=True)
        response = client.post("/accounts/login/", {})
        self.assertEqual(response.status_code, 403)
        self.assertIn("Your session expired", response.content.decode())

    # ------------------------------------------------------------------ 7
    def test_permission_denied_handler_renders_branded_page(self):
        request = self.factory.get("/")
        request.user = AnonymousUser()
        response = error_views.permission_denied(request, Exception("nope"))
        self.assertEqual(response.status_code, 403)
        self.assertIn("You don't have access to this page", response.content.decode())

    # ------------------------------------------------------------------ 8
    def test_404_does_not_run_context_processors(self):
        with mock.patch(
            "apps.marketplace.context_processors.categories_processor",
            side_effect=AssertionError("context processor must not run"),
        ) as patched:
            response = self.client.get("/this-page-does-not-exist-xyz-5/")
        self.assertEqual(response.status_code, 404)
        self.assertFalse(patched.called)

    # ------------------------------------------------------------------ 9
    def test_error_bodies_leak_no_internals(self):
        forbidden = ("Traceback", "DoesNotExist", "Exception")

        client_responses = [
            self.client.get("/this-page-does-not-exist-xyz-6/"),
            self.client.get(
                "/this-page-does-not-exist-xyz-7/",
                HTTP_ACCEPT="application/json",
            ),
        ]
        request = self.factory.get("/")
        request.user = AnonymousUser()
        direct = [
            error_views.server_error(request),
            error_views.bad_request(request, Exception("x")),
            error_views.permission_denied(request, Exception("x")),
            error_views.page_not_found(request, Http404("x")),
            error_views.csrf_failure(request, reason="token mismatch"),
        ]

        for response in client_responses + direct:
            body = response.content.decode()
            for word in forbidden:
                self.assertNotIn(word, body)

    # ------------------------------------------------------------------ 10
    def test_preview_route_absent_when_debug_is_false(self):
        response = self.client.get("/__errors__/404/")
        self.assertEqual(response.status_code, 404)
        self.assertIn("We can't find that page", response.content.decode())
