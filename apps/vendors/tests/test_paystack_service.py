from unittest.mock import patch
from django.test import SimpleTestCase

from apps.vendors.services.paystack import PaystackAPIError, PaystackService


class PaystackServiceFallbackTests(SimpleTestCase):
    def test_get_banks_returns_fallback_list_when_paystack_fails(self):
        service = PaystackService.__new__(PaystackService)

        with patch.object(service, '_make_request', side_effect=PaystackAPIError('boom')):
            success, banks = service.get_banks()

        self.assertTrue(success)
        self.assertGreaterEqual(len(banks), 5)
        self.assertTrue(any(bank['name'] == 'Guaranty Trust Bank' for bank in banks))
