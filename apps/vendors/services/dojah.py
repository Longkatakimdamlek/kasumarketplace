"""
Dojah API Integration Service
Handles BVN verification with live selfie match (single-call KYC).
Documentation: https://docs.dojah.io/

Environment Variables Required:
- DOJAH_SECRET_KEY (use test_sk_xxx for sandbox)
- DOJAH_APP_ID
- DOJAH_BASE_URL (https://sandbox.dojah.io for testing, https://api.dojah.io for production)

NOTE: OTP-based verification flows have been removed entirely. BVN + live
selfie is the sole identity verification method. Dojah returns identity
fields + a selfie_verification block (confidence_value, match) in a single
synchronous response - no OTP round-trip required.
"""

import os
import requests
import logging
from typing import Dict, Optional, Tuple

logger = logging.getLogger(__name__)


class DojahAPIError(Exception):
    """Custom exception for Dojah API errors"""
    pass


class DojahService:
    """
    Service class for interacting with Dojah API.
    Sole method: BVN verification with live selfie match.
    """

    def __init__(self):
        self.secret_key = os.getenv('DOJAH_SECRET_KEY', '')
        self.app_id = os.getenv('DOJAH_APP_ID', '')
        self.base_url = os.getenv('DOJAH_BASE_URL', 'https://api.dojah.io')

        self.is_sandbox = 'sandbox' in self.base_url

        if not self.secret_key or not self.app_id:
            raise ValueError('Dojah API credentials (DOJAH_SECRET_KEY and DOJAH_APP_ID) must be configured.')

        if self.is_sandbox:
            logger.info('🧪 Dojah Service running in SANDBOX mode')
        else:
            logger.info('🚀 Dojah Service running in PRODUCTION mode')

    def _get_headers(self) -> Dict[str, str]:
        """Get headers for API requests"""
        return {
            'Authorization': self.secret_key,  # Dojah expects the key directly, not "Bearer xxx"
            'AppId': self.app_id,
            'Content-Type': 'application/json',
            'Accept': 'application/json'
        }

    def _make_request(
        self,
        method: str,
        endpoint: str,
        data: Optional[Dict] = None
    ) -> Dict:
        """
        Make HTTP request to Dojah API

        Args:
            method: HTTP method (GET, POST)
            endpoint: API endpoint
            data: Request payload

        Returns:
            Response data as dictionary

        Raises:
            DojahAPIError: If API request fails
        """
        url = f"{self.base_url}{endpoint}"

        logger.info(f"🌐 Dojah API Request: {method} {url}")
        if data:
            safe_data = {k: '***' if k in ('bvn', 'selfie_image') else v for k, v in data.items()}
            logger.debug(f"📦 Request data: {safe_data}")

        try:
            if method.upper() == 'GET':
                response = requests.get(url, headers=self._get_headers(), params=data, timeout=30)
            else:
                response = requests.post(url, headers=self._get_headers(), json=data, timeout=30)

            logger.info(f"📥 Response status: {response.status_code}")

            response.raise_for_status()
            result = response.json()

            logger.debug(f"✅ Response data received")

            return result

        except requests.exceptions.Timeout:
            logger.error(f'⏱️ Dojah API timeout: {endpoint}')
            raise DojahAPIError('Request timeout. Please try again.')

        except requests.exceptions.RequestException as e:
            logger.error(f'❌ Dojah API error: {str(e)}')
            if hasattr(e, 'response') and e.response is not None:
                try:
                    error_data = e.response.json()
                    logger.error(f'📛 Error response: {error_data}')
                    # Dojah uses 'error' as the key for its error message,
                    # not 'message' - check both so the specific reason
                    # (e.g. "BVN Not Found") surfaces instead of a generic
                    # HTTP status string.
                    error_msg = error_data.get('error') or error_data.get('message') or str(e)
                except Exception:
                    error_msg = str(e)
            else:
                error_msg = str(e)

            raise DojahAPIError(error_msg)

    # ==========================================
    # BVN + SELFIE VERIFICATION (sole identity method)
    # ==========================================

    def verify_bvn_with_selfie(self, bvn_number: str, selfie_base64: str) -> Tuple[bool, Dict]:
        """
        Verify BVN with live selfie match in a single call.
        Endpoint: /api/v1/kyc/bvn/verify (POST)

        Confirmed request body (per Dojah docs):
            bvn            string  required - valid BVN number
            selfie_image   string  required - base64 buffer WITHOUT the
                                    "data:image/jpeg;base64," prefix -
                                    pass only the buffer starting with "/9"

        Args:
            bvn_number: 11-digit Bank Verification Number
            selfie_base64: base64 buffer with the data-URI prefix already
                           stripped by the caller (view layer).

        Returns:
            Tuple of (success: bool, data: dict)

            On success, data contains:
                - firstname, lastname, middlename, full_name
                - phone (from phone_number1)
                - dateofbirth (raw string - format is inconsistent across
                  Dojah responses, e.g. "1993-05-06" vs "01-January-1907" -
                  caller must parse defensively, trying multiple formats)
                - gender
                - selfie_match: bool        (Dojah's own true/false, hardcoded
                                              90% cutoff - too coarse for our
                                              3-tier outcome, use confidence instead)
                - selfie_confidence: float  (0-100 - THIS drives the 3-tier
                                              auto-verify / pending_review / failed logic)
                - selfie_image_url: str
                - raw_response: dict (full original payload, for VerificationAttempt logging)

            On failure, data contains:
                - error: str
        """
        logger.info(f"🏦 Verifying BVN with selfie: ***{bvn_number[-4:]}")

        try:
            response = self._make_request(
                'POST',
                '/api/v1/kyc/bvn/verify',
                data={
                    'bvn': bvn_number,
                    'selfie_image': selfie_base64,
                }
            )

            if response.get('entity'):
                data = response['entity']

                def safe_str(value, default=''):
                    """Convert value to string, handling dicts/lists/None defensively"""
                    if value is None:
                        return default
                    if isinstance(value, dict):
                        return default
                    if isinstance(value, (list, tuple)):
                        return ' '.join(str(v) for v in value if v) if value else default
                    return str(value).strip() if value else default

                firstname = safe_str(data.get('first_name') or data.get('firstname'))
                lastname = safe_str(data.get('last_name') or data.get('lastname') or data.get('surname'))
                middlename = safe_str(data.get('middle_name') or data.get('middlename'))

                phone = safe_str(
                    data.get('phone_number1')
                    or data.get('phone_number')
                    or data.get('phone')
                )

                # Date format is inconsistent across Dojah responses - pass
                # the raw string through, let the view's date parser try
                # multiple formats rather than assuming one here.
                dob_raw = safe_str(data.get('date_of_birth') or data.get('dateofbirth'))

                gender = safe_str(data.get('gender'))

                selfie_verification = data.get('selfie_verification') or {}
                selfie_match = selfie_verification.get('match', False)
                selfie_confidence = selfie_verification.get('confidence_value', 0.0)
                selfie_image_url = safe_str(data.get('selfie_image_url'))

                full_name = ' '.join(p for p in [firstname, middlename, lastname] if p).strip()

                normalized_data = {
                    'firstname': firstname,
                    'lastname': lastname,
                    'middlename': middlename,
                    'full_name': full_name,
                    'phone': phone,
                    'dateofbirth': dob_raw,
                    'gender': gender,
                    'selfie_match': bool(selfie_match),
                    'selfie_confidence': float(selfie_confidence) if selfie_confidence else 0.0,
                    'selfie_image_url': selfie_image_url,
                    'raw_response': data,
                }

                logger.info(
                    f"✅ BVN+selfie response received: ***{bvn_number[-4:]} | "
                    f"match={selfie_match} | confidence={selfie_confidence}"
                )
                return True, normalized_data

            else:
                logger.warning(f"⚠️ BVN verification failed: No entity data in response")
                return False, {'error': 'Invalid BVN or no data found'}

        except DojahAPIError as e:
            logger.error(f"❌ BVN+selfie verification error: {str(e)}")
            return False, {'error': str(e)}


# Singleton instance
dojah_service = DojahService()