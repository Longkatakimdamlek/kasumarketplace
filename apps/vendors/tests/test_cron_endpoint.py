"""
Tests for the internal cron endpoint: vendors:cron_check_subscriptions.

POST-only, bearer-token protected trigger for check_subscription_status
(designed for external schedulers on Render FREE where cron/shell is
unavailable).  Covers: 405 on GET, 403 on missing/wrong token, 200 + command
invocation on the correct token, 404 when CRON_SECRET is unset, 500 with no
traceback on a command failure, 409 on overlapping runs, output truncation,
and that the token never appears in captured logs.
"""

import threading
from unittest.mock import patch

from django.test import TestCase, override_settings
from django.urls import reverse


URL = reverse('vendors:cron_check_subscriptions')
TOKEN = 'test-cron-secret-token'


@override_settings(CRON_SECRET=TOKEN)
class CronEndpointAuthTests(TestCase):

    def test_get_is_not_allowed(self):
        response = self.client.get(URL)
        self.assertEqual(response.status_code, 405)

    def test_post_without_token_returns_403(self):
        response = self.client.post(URL)
        self.assertEqual(response.status_code, 403)

    def test_post_with_wrong_token_returns_403(self):
        response = self.client.post(
            URL, HTTP_AUTHORIZATION='Bearer wrong-token',
        )
        self.assertEqual(response.status_code, 403)

    def test_post_with_malformed_authorization_header_returns_403(self):
        # correct token but missing the "Bearer " prefix
        response = self.client.post(URL, HTTP_AUTHORIZATION=TOKEN)
        self.assertEqual(response.status_code, 403)

    @patch('apps.vendors.views.call_command')
    def test_correct_token_runs_command_and_returns_200(self, mock_cmd):
        response = self.client.post(
            URL, HTTP_AUTHORIZATION=f'Bearer {TOKEN}',
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload['ok'])
        self.assertIn('output', payload)
        mock_cmd.assert_called_once()
        self.assertEqual(mock_cmd.call_args[0][0], 'check_subscription_status')

    def test_endpoint_disabled_when_cron_secret_unset(self):
        with override_settings(CRON_SECRET=''):
            response = self.client.post(
                URL, HTTP_AUTHORIZATION=f'Bearer {TOKEN}',
            )
        self.assertEqual(response.status_code, 404)

    def test_command_invoked_for_real_with_correct_token(self):
        # end-to-end: no mock; the real command runs against the test DB
        response = self.client.post(
            URL, HTTP_AUTHORIZATION=f'Bearer {TOKEN}',
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload['ok'])
        self.assertIn('summary:', payload['output'])


class CronEndpointFailureTests(TestCase):

    @override_settings(CRON_SECRET=TOKEN)
    @patch('apps.vendors.views.call_command', side_effect=RuntimeError('boom'))
    def test_command_exception_returns_500_without_traceback(self, mock_cmd):
        response = self.client.post(
            URL, HTTP_AUTHORIZATION=f'Bearer {TOKEN}',
        )
        self.assertEqual(response.status_code, 500)
        payload = response.json()
        self.assertFalse(payload['ok'])
        body = response.content.decode()
        self.assertNotIn('Traceback', body)
        self.assertNotIn('boom', body)

    @override_settings(CRON_SECRET=TOKEN)
    def test_overlapping_run_returns_409(self):
        from apps.vendors import views as vendor_views

        started = threading.Event()
        release = threading.Event()

        def slow_command(*args, **kwargs):
            started.set()
            release.wait(timeout=5)

        with patch.object(vendor_views, 'call_command', side_effect=slow_command):
            results = {}

            def hit():
                results['response'] = self.client.post(
                    URL, HTTP_AUTHORIZATION=f'Bearer {TOKEN}',
                )

            worker = threading.Thread(target=hit)
            worker.start()
            try:
                self.assertTrue(started.wait(timeout=5))
                overlap = self.client.post(
                    URL, HTTP_AUTHORIZATION=f'Bearer {TOKEN}',
                )
                self.assertEqual(overlap.status_code, 409)
            finally:
                release.set()
                worker.join(timeout=5)

        self.assertEqual(results['response'].status_code, 200)


class CronEndpointSecurityTests(TestCase):

    @override_settings(CRON_SECRET=TOKEN)
    @patch('apps.vendors.views.call_command')
    def test_token_never_appears_in_logs(self, mock_cmd):
        with self.assertLogs('apps.vendors.views', level='DEBUG') as captured:
            ok = self.client.post(
                URL, HTTP_AUTHORIZATION=f'Bearer {TOKEN}',
            )
            bad = self.client.post(
                URL, HTTP_AUTHORIZATION='Bearer some-other-secret',
            )

        self.assertEqual(ok.status_code, 200)
        self.assertEqual(bad.status_code, 403)

        all_logs = '\n'.join(captured.output)
        self.assertNotIn(TOKEN, all_logs)
        self.assertNotIn('some-other-secret', all_logs)

    @override_settings(CRON_SECRET=TOKEN)
    @patch('apps.vendors.views.call_command')
    def test_output_is_truncated_to_last_2000_chars(self, mock_cmd):
        long_output = 'x' * 5000 + 'TAIL'

        def fake_call_command(*args, **kwargs):
            kwargs['stdout'].write(long_output)

        mock_cmd.side_effect = fake_call_command

        response = self.client.post(
            URL, HTTP_AUTHORIZATION=f'Bearer {TOKEN}',
        )
        self.assertEqual(response.status_code, 200)
        output = response.json()['output']
        self.assertLessEqual(len(output), 2000)
        self.assertTrue(output.endswith('TAIL'))
