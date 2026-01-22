"""
Dojah API Integration Service
Handles NIN and BVN verification with OTP
Documentation: https://docs.dojah.io/

Environment Variables Required:
- DOJAH_SECRET_KEY (use test_sk_xxx for sandbox)
- DOJAH_APP_ID
- DOJAH_BASE_URL (https://sandbox.dojah.io for testing, https://api.dojah.io for production)
"""

import os
import requests
import logging
from typing import Dict, Optional, Tuple
from datetime import datetime, timedelta
from django.core.cache import cache
from django.conf import settings

logger = logging.getLogger(__name__)


class DojahAPIError(Exception):
    """Custom exception for Dojah API errors"""
    pass


class DojahService:
    """
    Service class for interacting with Dojah API
    Handles NIN and BVN verification with OTP
    """
    
    def __init__(self):
        self.secret_key = os.getenv('DOJAH_SECRET_KEY', '')
        self.app_id = os.getenv('DOJAH_APP_ID', '')
        self.base_url = os.getenv('DOJAH_BASE_URL', 'https://api.dojah.io')
        
        # OTP expiry time (10 minutes)
        self.otp_expiry_minutes = 10
        
        # Check environment
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
        
        # Log request (hide sensitive data)
        logger.info(f"🌐 Dojah API Request: {method} {url}")
        if data:
            safe_data = {k: '***' if k in ['nin', 'bvn'] else v for k, v in data.items()}
            logger.debug(f"📦 Request data: {safe_data}")
        
        try:
            if method.upper() == 'GET':
                response = requests.get(url, headers=self._get_headers(), params=data, timeout=30)
            else:
                response = requests.post(url, headers=self._get_headers(), json=data, timeout=30)
            
            # Log response status
            logger.info(f"📥 Response status: {response.status_code}")
            
            response.raise_for_status()
            result = response.json()
            
            # Log success
            logger.debug(f"✅ Response data: {result}")
            
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
                    error_msg = error_data.get('message', str(e))
                except:
                    error_msg = str(e)
            else:
                error_msg = str(e)
            
            raise DojahAPIError(f'API Error: {error_msg}')
    
    # ==========================================
    # NIN VERIFICATION
    # ==========================================
    
    def verify_nin(self, nin_number: str) -> Tuple[bool, Dict]:
        """
        Verify NIN and retrieve identity information
        
        Args:
            nin_number: 11-digit National Identity Number
            
        Returns:
            Tuple of (success: bool, data: dict)
        """
        logger.info(f"🔍 Verifying NIN: ***{nin_number[-4:]}")
        
        try:
            # Use GET with query parameters (not POST with JSON body)
            response = self._make_request(
                'GET',
                '/api/v1/kyc/nin',
                data={'nin': nin_number}  # This becomes ?nin=xxx in GET request
            )
            
            # Extract data from response
            if response.get('entity'):
                data = response['entity']
                
                # Normalize data
                normalized_data = {
                    'firstname': data.get('firstname', ''),
                    'surname': data.get('surname', ''),
                    'middlename': data.get('middlename', ''),
                    'phone': data.get('telephoneno', data.get('phone', '')),
                    'birthdate': data.get('birthdate', data.get('dateofbirth', '')),
                    'gender': data.get('gender', ''),
                    'residence_address': data.get('residence_address', data.get('address', '')),
                    'residence_state': data.get('residence_state', data.get('state', '')),
                    'residence_lga': data.get('residence_lga', data.get('lga', '')),
                    'photo': data.get('photo', ''),
                    'raw_response': data
                }
                
                logger.info(f'✅ NIN verified successfully: ***{nin_number[-4:]}')
                logger.debug(f'📋 Normalized data: {normalized_data}')
                return True, normalized_data
            
            else:
                logger.warning(f'⚠️ NIN verification failed: No entity data in response')
                logger.debug(f'Response: {response}')
                return False, {'error': 'Invalid NIN or no data found'}
        
        except DojahAPIError as e:
            logger.error(f'❌ NIN verification error: {str(e)}')
            return False, {'error': str(e)}
    
    def send_nin_otp(self, nin_number: str) -> Tuple[bool, Dict]:
        """Send OTP to phone number linked to NIN"""
        logger.info(f"📱 Sending NIN OTP: ***{nin_number[-4:]}")
        
        try:
            response = self._make_request(
                'POST',
                '/api/v1/messaging/otp/send',
                data={
                    'nin': nin_number,
                    'channel': 'sms'
                }
            )
            
            otp_ref = response.get('reference')
            if otp_ref:
                cache_key = f'nin_otp_{nin_number}'
                cache.set(cache_key, otp_ref, timeout=self.otp_expiry_minutes * 60)
                logger.info(f'💾 OTP reference cached: {otp_ref}')
            
            return True, {
                'reference': otp_ref,
                'phone': response.get('phone', ''),
                'expires_at': (datetime.now() + timedelta(minutes=self.otp_expiry_minutes)).isoformat()
            }
        
        except DojahAPIError as e:
            logger.error(f'❌ NIN OTP send error: {str(e)}')
            return False, {'error': str(e)}
    
    def verify_nin_otp(self, nin_number: str, otp_code: str) -> Tuple[bool, Dict]:
        """Verify OTP code sent to NIN-linked phone"""
        logger.info(f"🔐 Verifying NIN OTP: ***{nin_number[-4:]}")
        
        try:
            cache_key = f'nin_otp_{nin_number}'
            otp_ref = cache.get(cache_key)
            
            if not otp_ref:
                logger.warning(f'⚠️ OTP reference not found in cache')
                return False, {'error': 'OTP expired or not found. Please request a new OTP.'}
            
            response = self._make_request(
                'POST',
                '/api/v1/messaging/otp/validate',
                data={
                    'reference': otp_ref,
                    'code': otp_code
                }
            )
            
            if response.get('valid'):
                cache.delete(cache_key)
                logger.info(f'✅ NIN OTP verified successfully: ***{nin_number[-4:]}')
                return True, {'message': 'OTP verified successfully'}
            else:
                logger.warning(f'⚠️ Invalid OTP code provided')
                return False, {'error': 'Invalid OTP code'}
        
        except DojahAPIError as e:
            logger.error(f'❌ NIN OTP verification error: {str(e)}')
            return False, {'error': str(e)}
    
    # ==========================================
    # BVN VERIFICATION
    # ==========================================
    
    def verify_bvn(self, bvn_number: str, bank_code: str = None) -> Tuple[bool, Dict]:
        """Verify BVN and retrieve banking information"""
        logger.info(f"🏦 Verifying BVN: ***{bvn_number[-4:]}")
        
        try:
            # Use GET with query parameters (not POST with JSON body)
            response = self._make_request(
                'GET',
                '/api/v1/kyc/bvn',
                data={'bvn': bvn_number}  # This becomes ?bvn=xxx in GET request
            )
            
            if response.get('entity'):
                data = response['entity']
                
                normalized_data = {
                    'firstname': data.get('firstname', data.get('first_name', '')),
                    'lastname': data.get('lastname', data.get('last_name', data.get('surname', ''))),
                    'middlename': data.get('middlename', data.get('middle_name', '')),
                    'phone': data.get('phone', data.get('phonenumber', '')),
                    'dateofbirth': data.get('dateofbirth', data.get('dob', '')),
                    'account_name': data.get('account_name', ''),
                    'account_number': data.get('account_number', ''),
                    'bank_name': data.get('bank_name', ''),
                    'raw_response': data
                }
                
                logger.info(f'✅ BVN verified successfully: ***{bvn_number[-4:]}')
                return True, normalized_data
            else:
                logger.warning(f'⚠️ BVN verification failed: No entity data')
                return False, {'error': 'Invalid BVN or no data found'}
        
        except DojahAPIError as e:
            logger.error(f'❌ BVN verification error: {str(e)}')
            return False, {'error': str(e)}
    
    def send_bvn_otp(self, bvn_number: str) -> Tuple[bool, Dict]:
        """Send OTP to phone number linked to BVN"""
        logger.info(f"📱 Sending BVN OTP: ***{bvn_number[-4:]}")
        
        try:
            response = self._make_request(
                'POST',
                '/api/v1/messaging/otp/send',
                data={
                    'bvn': bvn_number,
                    'channel': 'sms'
                }
            )
            
            otp_ref = response.get('reference')
            if otp_ref:
                cache_key = f'bvn_otp_{bvn_number}'
                cache.set(cache_key, otp_ref, timeout=self.otp_expiry_minutes * 60)
                logger.info(f'💾 OTP reference cached: {otp_ref}')
            
            return True, {
                'reference': otp_ref,
                'phone': response.get('phone', ''),
                'expires_at': (datetime.now() + timedelta(minutes=self.otp_expiry_minutes)).isoformat()
            }
        
        except DojahAPIError as e:
            logger.error(f'❌ BVN OTP send error: {str(e)}')
            return False, {'error': str(e)}
    
    def verify_bvn_otp(self, bvn_number: str, otp_code: str) -> Tuple[bool, Dict]:
        """Verify OTP code sent to BVN-linked phone"""
        logger.info(f"🔐 Verifying BVN OTP: ***{bvn_number[-4:]}")
        
        try:
            cache_key = f'bvn_otp_{bvn_number}'
            otp_ref = cache.get(cache_key)
            
            if not otp_ref:
                logger.warning(f'⚠️ OTP reference not found in cache')
                return False, {'error': 'OTP expired or not found. Please request a new OTP.'}
            
            response = self._make_request(
                'POST',
                '/api/v1/messaging/otp/validate',
                data={
                    'reference': otp_ref,
                    'code': otp_code
                }
            )
            
            if response.get('valid'):
                cache.delete(cache_key)
                logger.info(f'✅ BVN OTP verified successfully: ***{bvn_number[-4:]}')
                return True, {'message': 'OTP verified successfully'}
            else:
                logger.warning(f'⚠️ Invalid OTP code provided')
                return False, {'error': 'Invalid OTP code'}
        
        except DojahAPIError as e:
            logger.error(f'❌ BVN OTP verification error: {str(e)}')
            return False, {'error': str(e)}


# Singleton instance
dojah_service = DojahService()