"""
Dojah API Integration Service
Handles NIN and BVN verification with OTP
Documentation: https://docs.dojah.io/

Environment Variables Required:
- DOJAH_API_KEY
- DOJAH_APP_ID
- DOJAH_BASE_URL (optional, defaults to production)
- USE_MOCK_DOJAH (set to 'True' for testing without real API)
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
        self.api_key = os.getenv('DOJAH_API_KEY', '')
        self.app_id = os.getenv('DOJAH_APP_ID', '')
        self.base_url = os.getenv('DOJAH_BASE_URL', 'https://api.dojah.io')
        self.use_mock = os.getenv('USE_MOCK_DOJAH', 'True').lower() == 'true'
        
        # OTP expiry time (10 minutes)
        self.otp_expiry_minutes = 10
        
        if not self.use_mock and (not self.api_key or not self.app_id):
            logger.warning('Dojah API credentials not configured. Using mock mode.')
            self.use_mock = True
    
    def _get_headers(self) -> Dict[str, str]:
        """Get headers for API requests"""
        return {
            'Authorization': f'Bearer {self.api_key}',
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
        
        try:
            if method.upper() == 'GET':
                response = requests.get(url, headers=self._get_headers(), params=data, timeout=30)
            else:
                response = requests.post(url, headers=self._get_headers(), json=data, timeout=30)
            
            response.raise_for_status()
            return response.json()
            
        except requests.exceptions.Timeout:
            logger.error(f'Dojah API timeout: {endpoint}')
            raise DojahAPIError('Request timeout. Please try again.')
        
        except requests.exceptions.RequestException as e:
            logger.error(f'Dojah API error: {str(e)}')
            if hasattr(e, 'response') and e.response is not None:
                try:
                    error_data = e.response.json()
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
            
        Example response data:
            {
                'firstname': 'John',
                'surname': 'Doe',
                'middlename': 'Smith',
                'phone': '08012345678',
                'birthdate': '1990-01-15',
                'gender': 'Male',
                'residence_address': '123 Lagos Street',
                'residence_state': 'Lagos',
                'residence_lga': 'Ikeja',
                'photo': 'base64_encoded_image_or_url'
            }
        """
        
        # Use mock data if in test mode
        if self.use_mock:
            return self._mock_verify_nin(nin_number)
        
        try:
            response = self._make_request(
                'POST',
                '/api/v1/kyc/nin',
                data={'nin': nin_number}
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
                    'raw_response': data  # Store full response for debugging
                }
                
                logger.info(f'NIN verified successfully: {nin_number[-4:]}')
                return True, normalized_data
            
            else:
                logger.warning(f'NIN verification failed: No entity data')
                return False, {'error': 'Invalid NIN or no data found'}
        
        except DojahAPIError as e:
            logger.error(f'NIN verification error: {str(e)}')
            return False, {'error': str(e)}
    
    def send_nin_otp(self, nin_number: str) -> Tuple[bool, Dict]:
        """
        Send OTP to phone number linked to NIN
        
        Args:
            nin_number: 11-digit NIN
            
        Returns:
            Tuple of (success: bool, data: dict)
            
        Example response:
            {
                'reference': 'otp_ref_12345',
                'phone': '080****5678',
                'expires_at': '2024-01-01T10:10:00'
            }
        """
        
        if self.use_mock:
            return self._mock_send_nin_otp(nin_number)
        
        try:
            response = self._make_request(
                'POST',
                '/api/v1/messaging/otp/send',
                data={
                    'nin': nin_number,
                    'channel': 'sms'
                }
            )
            
            # Store OTP reference in cache
            otp_ref = response.get('reference')
            if otp_ref:
                cache_key = f'nin_otp_{nin_number}'
                cache.set(cache_key, otp_ref, timeout=self.otp_expiry_minutes * 60)
            
            return True, {
                'reference': otp_ref,
                'phone': response.get('phone', ''),
                'expires_at': (datetime.now() + timedelta(minutes=self.otp_expiry_minutes)).isoformat()
            }
        
        except DojahAPIError as e:
            logger.error(f'NIN OTP send error: {str(e)}')
            return False, {'error': str(e)}
    
    def verify_nin_otp(self, nin_number: str, otp_code: str) -> Tuple[bool, Dict]:
        """
        Verify OTP code sent to NIN-linked phone
        
        Args:
            nin_number: 11-digit NIN
            otp_code: 6-digit OTP code
            
        Returns:
            Tuple of (success: bool, data: dict)
        """
        
        if self.use_mock:
            return self._mock_verify_nin_otp(nin_number, otp_code)
        
        try:
            # Get OTP reference from cache
            cache_key = f'nin_otp_{nin_number}'
            otp_ref = cache.get(cache_key)
            
            if not otp_ref:
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
                # Clear OTP from cache
                cache.delete(cache_key)
                logger.info(f'NIN OTP verified successfully: {nin_number[-4:]}')
                return True, {'message': 'OTP verified successfully'}
            else:
                return False, {'error': 'Invalid OTP code'}
        
        except DojahAPIError as e:
            logger.error(f'NIN OTP verification error: {str(e)}')
            return False, {'error': str(e)}
    
    # ==========================================
    # BVN VERIFICATION
    # ==========================================
    
    def verify_bvn(self, bvn_number: str, bank_code: str = None) -> Tuple[bool, Dict]:
        """
        Verify BVN and retrieve banking information
        
        Args:
            bvn_number: 11-digit Bank Verification Number
            bank_code: Optional bank code
            
        Returns:
            Tuple of (success: bool, data: dict)
            
        Example response data:
            {
                'firstname': 'John',
                'lastname': 'Doe',
                'middlename': 'Smith',
                'phone': '08012345678',
                'dateofbirth': '1990-01-15',
                'account_name': 'John Doe',
                'account_number': '0123456789',
                'bank_name': 'GTBank'
            }
        """
        
        if self.use_mock:
            return self._mock_verify_bvn(bvn_number)
        
        try:
            response = self._make_request(
                'POST',
                '/api/v1/kyc/bvn',
                data={'bvn': bvn_number}
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
                
                logger.info(f'BVN verified successfully: {bvn_number[-4:]}')
                return True, normalized_data
            else:
                return False, {'error': 'Invalid BVN or no data found'}
        
        except DojahAPIError as e:
            logger.error(f'BVN verification error: {str(e)}')
            return False, {'error': str(e)}
    
    def send_bvn_otp(self, bvn_number: str) -> Tuple[bool, Dict]:
        """Send OTP to phone number linked to BVN"""
        
        if self.use_mock:
            return self._mock_send_bvn_otp(bvn_number)
        
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
            
            return True, {
                'reference': otp_ref,
                'phone': response.get('phone', ''),
                'expires_at': (datetime.now() + timedelta(minutes=self.otp_expiry_minutes)).isoformat()
            }
        
        except DojahAPIError as e:
            logger.error(f'BVN OTP send error: {str(e)}')
            return False, {'error': str(e)}
    
    def verify_bvn_otp(self, bvn_number: str, otp_code: str) -> Tuple[bool, Dict]:
        """Verify OTP code sent to BVN-linked phone"""
        
        if self.use_mock:
            return self._mock_verify_bvn_otp(bvn_number, otp_code)
        
        try:
            cache_key = f'bvn_otp_{bvn_number}'
            otp_ref = cache.get(cache_key)
            
            if not otp_ref:
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
                logger.info(f'BVN OTP verified successfully: {bvn_number[-4:]}')
                return True, {'message': 'OTP verified successfully'}
            else:
                return False, {'error': 'Invalid OTP code'}
        
        except DojahAPIError as e:
            logger.error(f'BVN OTP verification error: {str(e)}')
            return False, {'error': str(e)}
    
    # ==========================================
    # MOCK METHODS (FOR TESTING)
    # ==========================================
    
    def _mock_verify_nin(self, nin_number: str) -> Tuple[bool, Dict]:
        """Mock NIN verification for testing"""
        logger.info(f'[MOCK] NIN verification: {nin_number[-4:]}')
        
        return True, {
            'firstname': 'John',
            'surname': 'Doe',
            'middlename': 'Smith',
            'phone': '08012345678',
            'birthdate': '1990-01-15',
            'gender': 'Male',
            'residence_address': '123 Test Street, Ikeja',
            'residence_state': 'Lagos',
            'residence_lga': 'Ikeja',
            'photo': 'https://via.placeholder.com/150',
            'mock': True
        }
    
    def _mock_send_nin_otp(self, nin_number: str) -> Tuple[bool, Dict]:
        """Mock NIN OTP sending"""
        logger.info(f'[MOCK] NIN OTP sent: {nin_number[-4:]}')
        
        # Store mock OTP in cache
        cache_key = f'nin_otp_{nin_number}'
        cache.set(cache_key, '123456', timeout=self.otp_expiry_minutes * 60)
        
        return True, {
            'reference': f'mock_ref_{nin_number[-4:]}',
            'phone': '080****5678',
            'expires_at': (datetime.now() + timedelta(minutes=self.otp_expiry_minutes)).isoformat(),
            'mock': True,
            'test_otp': '123456'  # Only in mock mode!
        }
    
    def _mock_verify_nin_otp(self, nin_number: str, otp_code: str) -> Tuple[bool, Dict]:
        """Mock NIN OTP verification - accepts 123456"""
        logger.info(f'[MOCK] NIN OTP verification: {nin_number[-4:]}')
        
        # Accept any 6-digit code in mock mode (or specifically 123456)
        if len(otp_code) == 6 and otp_code.isdigit():
            return True, {'message': 'OTP verified successfully', 'mock': True}
        
        return False, {'error': 'Invalid OTP code'}
    
    def _mock_verify_bvn(self, bvn_number: str) -> Tuple[bool, Dict]:
        """Mock BVN verification"""
        logger.info(f'[MOCK] BVN verification: {bvn_number[-4:]}')
        
        return True, {
            'firstname': 'John',
            'lastname': 'Doe',
            'middlename': 'Smith',
            'phone': '08012345678',
            'dateofbirth': '1990-01-15',
            'account_name': 'John Doe',
            'account_number': '0123456789',
            'bank_name': 'GTBank',
            'mock': True
        }
    
    def _mock_send_bvn_otp(self, bvn_number: str) -> Tuple[bool, Dict]:
        """Mock BVN OTP sending"""
        logger.info(f'[MOCK] BVN OTP sent: {bvn_number[-4:]}')
        
        cache_key = f'bvn_otp_{bvn_number}'
        cache.set(cache_key, '123456', timeout=self.otp_expiry_minutes * 60)
        
        return True, {
            'reference': f'mock_ref_{bvn_number[-4:]}',
            'phone': '080****5678',
            'expires_at': (datetime.now() + timedelta(minutes=self.otp_expiry_minutes)).isoformat(),
            'mock': True,
            'test_otp': '123456'
        }
    
    def _mock_verify_bvn_otp(self, bvn_number: str, otp_code: str) -> Tuple[bool, Dict]:
        """Mock BVN OTP verification"""
        logger.info(f'[MOCK] BVN OTP verification: {bvn_number[-4:]}')
        
        if len(otp_code) == 6 and otp_code.isdigit():
            return True, {'message': 'OTP verified successfully', 'mock': True}
        
        return False, {'error': 'Invalid OTP code'}


# Singleton instance
dojah_service = DojahService()