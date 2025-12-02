"""
Paystack API Integration Service
Handles payments, transfers, and payouts
Documentation: https://paystack.com/docs/api/

Environment Variables Required:
- PAYSTACK_SECRET_KEY
- PAYSTACK_PUBLIC_KEY
- USE_MOCK_PAYSTACK (set to 'True' for testing without real API)
"""

import os
import requests
import logging
from typing import Dict, Optional, Tuple
from decimal import Decimal
from django.conf import settings

logger = logging.getLogger(__name__)


class PaystackAPIError(Exception):
    """Custom exception for Paystack API errors"""
    pass


class PaystackService:
    """
    Service class for interacting with Paystack API
    Handles payment initialization, verification, and transfers (payouts)
    """
    
    def __init__(self):
        self.secret_key = os.getenv('PAYSTACK_SECRET_KEY', '')
        self.public_key = os.getenv('PAYSTACK_PUBLIC_KEY', '')
        self.base_url = 'https://api.paystack.co'
        self.use_mock = os.getenv('USE_MOCK_PAYSTACK', 'True').lower() == 'true'
        
        if not self.use_mock and not self.secret_key:
            logger.warning('Paystack API key not configured. Using mock mode.')
            self.use_mock = True
    
    def _get_headers(self) -> Dict[str, str]:
        """Get headers for API requests"""
        return {
            'Authorization': f'Bearer {self.secret_key}',
            'Content-Type': 'application/json',
        }
    
    def _make_request(
        self, 
        method: str, 
        endpoint: str, 
        data: Optional[Dict] = None
    ) -> Dict:
        """
        Make HTTP request to Paystack API
        
        Args:
            method: HTTP method (GET, POST)
            endpoint: API endpoint
            data: Request payload
            
        Returns:
            Response data as dictionary
            
        Raises:
            PaystackAPIError: If API request fails
        """
        url = f"{self.base_url}{endpoint}"
        
        try:
            if method.upper() == 'GET':
                response = requests.get(url, headers=self._get_headers(), params=data, timeout=30)
            else:
                response = requests.post(url, headers=self._get_headers(), json=data, timeout=30)
            
            response.raise_for_status()
            result = response.json()
            
            # Paystack always returns status field
            if not result.get('status'):
                error_msg = result.get('message', 'Unknown error')
                raise PaystackAPIError(error_msg)
            
            return result
            
        except requests.exceptions.Timeout:
            logger.error(f'Paystack API timeout: {endpoint}')
            raise PaystackAPIError('Request timeout. Please try again.')
        
        except requests.exceptions.RequestException as e:
            logger.error(f'Paystack API error: {str(e)}')
            if hasattr(e, 'response') and e.response is not None:
                try:
                    error_data = e.response.json()
                    error_msg = error_data.get('message', str(e))
                except:
                    error_msg = str(e)
            else:
                error_msg = str(e)
            
            raise PaystackAPIError(f'API Error: {error_msg}')
    
    def _convert_to_kobo(self, amount: Decimal) -> int:
        """
        Convert Naira to Kobo (Paystack uses kobo)
        1 Naira = 100 Kobo
        
        Args:
            amount: Amount in Naira (e.g., 1000.00)
            
        Returns:
            Amount in kobo (e.g., 100000)
        """
        return int(amount * 100)
    
    def _convert_to_naira(self, kobo: int) -> Decimal:
        """
        Convert Kobo to Naira
        
        Args:
            kobo: Amount in kobo
            
        Returns:
            Amount in Naira as Decimal
        """
        return Decimal(kobo) / 100
    
    # ==========================================
    # PAYMENT INITIALIZATION & VERIFICATION
    # ==========================================
    
    def initialize_payment(
        self,
        email: str,
        amount: Decimal,
        reference: Optional[str] = None,
        callback_url: Optional[str] = None,
        metadata: Optional[Dict] = None
    ) -> Tuple[bool, Dict]:
        """
        Initialize a payment transaction
        Customer will be redirected to Paystack payment page
        
        Args:
            email: Customer email
            amount: Amount in Naira
            reference: Unique transaction reference (auto-generated if not provided)
            callback_url: URL to redirect after payment
            metadata: Additional data (order_id, vendor_id, etc.)
            
        Returns:
            Tuple of (success: bool, data: dict)
            
        Example response:
            {
                'authorization_url': 'https://checkout.paystack.com/...',
                'access_code': 'access_code_here',
                'reference': 'ref_12345'
            }
        """
        
        if self.use_mock:
            return self._mock_initialize_payment(email, amount, reference)
        
        try:
            payload = {
                'email': email,
                'amount': self._convert_to_kobo(amount),
            }
            
            if reference:
                payload['reference'] = reference
            
            if callback_url:
                payload['callback_url'] = callback_url
            
            if metadata:
                payload['metadata'] = metadata
            
            response = self._make_request('POST', '/transaction/initialize', data=payload)
            
            if response.get('status'):
                data = response['data']
                logger.info(f'Payment initialized: {data.get("reference")}')
                
                return True, {
                    'authorization_url': data.get('authorization_url'),
                    'access_code': data.get('access_code'),
                    'reference': data.get('reference')
                }
            
            return False, {'error': response.get('message', 'Payment initialization failed')}
        
        except PaystackAPIError as e:
            logger.error(f'Payment initialization error: {str(e)}')
            return False, {'error': str(e)}
    
    def verify_payment(self, reference: str) -> Tuple[bool, Dict]:
        """
        Verify a payment transaction
        Call this after customer returns from payment page
        
        Args:
            reference: Transaction reference
            
        Returns:
            Tuple of (success: bool, data: dict)
            
        Example response:
            {
                'status': 'success',  # or 'failed', 'abandoned'
                'amount': Decimal('10000.00'),
                'paid_at': '2024-01-01T10:00:00',
                'customer': {'email': 'customer@example.com'},
                'metadata': {...}
            }
        """
        
        if self.use_mock:
            return self._mock_verify_payment(reference)
        
        try:
            response = self._make_request('GET', f'/transaction/verify/{reference}')
            
            if response.get('status'):
                data = response['data']
                
                # Check if payment was successful
                if data.get('status') == 'success':
                    logger.info(f'Payment verified: {reference}')
                    
                    return True, {
                        'status': 'success',
                        'amount': self._convert_to_naira(data.get('amount', 0)),
                        'paid_at': data.get('paid_at'),
                        'customer': data.get('customer', {}),
                        'metadata': data.get('metadata', {}),
                        'channel': data.get('channel'),
                        'currency': data.get('currency', 'NGN'),
                        'raw_response': data
                    }
                else:
                    # Payment failed or was abandoned
                    return False, {
                        'status': data.get('status'),
                        'error': f'Payment {data.get("status")}'
                    }
            
            return False, {'error': 'Verification failed'}
        
        except PaystackAPIError as e:
            logger.error(f'Payment verification error: {str(e)}')
            return False, {'error': str(e)}
    
    # ==========================================
    # TRANSFER RECIPIENTS (Vendor Bank Accounts)
    # ==========================================
    
    def create_transfer_recipient(
        self,
        account_number: str,
        bank_code: str,
        name: str,
        currency: str = 'NGN'
    ) -> Tuple[bool, Dict]:
        """
        Create a transfer recipient (save vendor's bank account)
        Do this once when vendor completes BVN verification
        
        Args:
            account_number: Bank account number
            bank_code: Bank code (e.g., '058' for GTBank)
            name: Account holder name
            currency: Currency code (default: NGN)
            
        Returns:
            Tuple of (success: bool, data: dict)
            
        Example response:
            {
                'recipient_code': 'RCP_xxx',
                'type': 'nuban',
                'name': 'John Doe',
                'account_number': '0123456789',
                'bank_name': 'Guaranty Trust Bank'
            }
        """
        
        if self.use_mock:
            return self._mock_create_transfer_recipient(account_number, bank_code, name)
        
        try:
            response = self._make_request(
                'POST',
                '/transferrecipient',
                data={
                    'type': 'nuban',
                    'name': name,
                    'account_number': account_number,
                    'bank_code': bank_code,
                    'currency': currency
                }
            )
            
            if response.get('status'):
                data = response['data']
                logger.info(f'Transfer recipient created: {data.get("recipient_code")}')
                
                return True, {
                    'recipient_code': data.get('recipient_code'),
                    'type': data.get('type'),
                    'name': data.get('name'),
                    'account_number': data.get('details', {}).get('account_number'),
                    'bank_name': data.get('details', {}).get('bank_name'),
                    'bank_code': data.get('details', {}).get('bank_code')
                }
            
            return False, {'error': response.get('message')}
        
        except PaystackAPIError as e:
            logger.error(f'Create recipient error: {str(e)}')
            return False, {'error': str(e)}
    
    def verify_account_number(
        self,
        account_number: str,
        bank_code: str
    ) -> Tuple[bool, Dict]:
        """
        Verify bank account number and get account name
        Use this to validate vendor's bank details
        
        Args:
            account_number: Bank account number
            bank_code: Bank code
            
        Returns:
            Tuple of (success: bool, data: dict)
            
        Example response:
            {
                'account_number': '0123456789',
                'account_name': 'John Doe',
                'bank_id': 1
            }
        """
        
        if self.use_mock:
            return self._mock_verify_account_number(account_number, bank_code)
        
        try:
            response = self._make_request(
                'GET',
                '/bank/resolve',
                data={
                    'account_number': account_number,
                    'bank_code': bank_code
                }
            )
            
            if response.get('status'):
                data = response['data']
                logger.info(f'Account verified: {account_number}')
                
                return True, {
                    'account_number': data.get('account_number'),
                    'account_name': data.get('account_name'),
                    'bank_id': data.get('bank_id')
                }
            
            return False, {'error': 'Invalid account number'}
        
        except PaystackAPIError as e:
            logger.error(f'Account verification error: {str(e)}')
            return False, {'error': str(e)}
    
    # ==========================================
    # TRANSFERS (Payouts to Vendors)
    # ==========================================
    
    def initiate_transfer(
        self,
        recipient_code: str,
        amount: Decimal,
        reason: str,
        reference: Optional[str] = None
    ) -> Tuple[bool, Dict]:
        """
        Initiate a transfer (payout to vendor)
        
        Args:
            recipient_code: Recipient code from create_transfer_recipient
            amount: Amount in Naira
            reason: Transfer reason/description
            reference: Unique transfer reference
            
        Returns:
            Tuple of (success: bool, data: dict)
            
        Example response:
            {
                'transfer_code': 'TRF_xxx',
                'reference': 'ref_12345',
                'amount': Decimal('5000.00'),
                'status': 'success',  # or 'pending', 'failed'
                'transferred_at': '2024-01-01T10:00:00'
            }
        """
        
        if self.use_mock:
            return self._mock_initiate_transfer(recipient_code, amount, reason, reference)
        
        try:
            payload = {
                'source': 'balance',
                'amount': self._convert_to_kobo(amount),
                'recipient': recipient_code,
                'reason': reason
            }
            
            if reference:
                payload['reference'] = reference
            
            response = self._make_request('POST', '/transfer', data=payload)
            
            if response.get('status'):
                data = response['data']
                logger.info(f'Transfer initiated: {data.get("transfer_code")}')
                
                return True, {
                    'transfer_code': data.get('transfer_code'),
                    'reference': data.get('reference'),
                    'amount': self._convert_to_naira(data.get('amount', 0)),
                    'status': data.get('status'),
                    'transferred_at': data.get('transferred_at'),
                    'recipient': data.get('recipient')
                }
            
            return False, {'error': response.get('message')}
        
        except PaystackAPIError as e:
            logger.error(f'Transfer initiation error: {str(e)}')
            return False, {'error': str(e)}
    
    def verify_transfer(self, reference: str) -> Tuple[bool, Dict]:
        """
        Verify a transfer status
        
        Args:
            reference: Transfer reference
            
        Returns:
            Tuple of (success: bool, data: dict)
        """
        
        if self.use_mock:
            return self._mock_verify_transfer(reference)
        
        try:
            response = self._make_request('GET', f'/transfer/verify/{reference}')
            
            if response.get('status'):
                data = response['data']
                
                return True, {
                    'status': data.get('status'),
                    'amount': self._convert_to_naira(data.get('amount', 0)),
                    'transferred_at': data.get('transferred_at'),
                    'recipient': data.get('recipient')
                }
            
            return False, {'error': 'Transfer verification failed'}
        
        except PaystackAPIError as e:
            logger.error(f'Transfer verification error: {str(e)}')
            return False, {'error': str(e)}
    
    # ==========================================
    # UTILITY METHODS
    # ==========================================
    
    def get_banks(self) -> Tuple[bool, list]:
        """
        Get list of Nigerian banks
        
        Returns:
            Tuple of (success: bool, banks: list)
            
        Example response:
            [
                {'name': 'Guaranty Trust Bank', 'code': '058', 'slug': 'guaranty-trust-bank'},
                {'name': 'Access Bank', 'code': '044', 'slug': 'access-bank'},
                ...
            ]
        """
        
        if self.use_mock:
            return self._mock_get_banks()
        
        try:
            response = self._make_request('GET', '/bank')
            
            if response.get('status'):
                banks = response['data']
                logger.info(f'Retrieved {len(banks)} banks')
                
                return True, [
                    {
                        'name': bank.get('name'),
                        'code': bank.get('code'),
                        'slug': bank.get('slug')
                    }
                    for bank in banks
                ]
            
            return False, []
        
        except PaystackAPIError as e:
            logger.error(f'Get banks error: {str(e)}')
            return False, []
    
    # ==========================================
    # MOCK METHODS (FOR TESTING)
    # ==========================================
    
    def _mock_initialize_payment(self, email: str, amount: Decimal, reference: Optional[str]) -> Tuple[bool, Dict]:
        """Mock payment initialization"""
        logger.info(f'[MOCK] Payment initialized: ₦{amount} for {email}')
        
        ref = reference or f'mock_ref_{int(amount)}'
        
        return True, {
            'authorization_url': f'https://mock-paystack.com/pay/{ref}',
            'access_code': f'mock_access_{ref}',
            'reference': ref,
            'mock': True
        }
    
    def _mock_verify_payment(self, reference: str) -> Tuple[bool, Dict]:
        """Mock payment verification - always returns success"""
        logger.info(f'[MOCK] Payment verified: {reference}')
        
        return True, {
            'status': 'success',
            'amount': Decimal('10000.00'),
            'paid_at': '2024-01-01T10:00:00',
            'customer': {'email': 'customer@example.com'},
            'metadata': {},
            'channel': 'card',
            'currency': 'NGN',
            'mock': True
        }
    
    def _mock_create_transfer_recipient(self, account_number: str, bank_code: str, name: str) -> Tuple[bool, Dict]:
        """Mock transfer recipient creation"""
        logger.info(f'[MOCK] Recipient created: {name} - {account_number}')
        
        return True, {
            'recipient_code': f'RCP_mock_{account_number[-4:]}',
            'type': 'nuban',
            'name': name,
            'account_number': account_number,
            'bank_name': 'Mock Bank',
            'bank_code': bank_code,
            'mock': True
        }
    
    def _mock_verify_account_number(self, account_number: str, bank_code: str) -> Tuple[bool, Dict]:
        """Mock account verification"""
        logger.info(f'[MOCK] Account verified: {account_number}')
        
        return True, {
            'account_number': account_number,
            'account_name': 'John Doe',
            'bank_id': 1,
            'mock': True
        }
    
    def _mock_initiate_transfer(self, recipient_code: str, amount: Decimal, reason: str, reference: Optional[str]) -> Tuple[bool, Dict]:
        """Mock transfer initiation"""
        logger.info(f'[MOCK] Transfer initiated: ₦{amount} - {reason}')
        
        ref = reference or f'mock_transfer_{int(amount)}'
        
        return True, {
            'transfer_code': f'TRF_mock_{ref[-4:]}',
            'reference': ref,
            'amount': amount,
            'status': 'success',
            'transferred_at': '2024-01-01T10:00:00',
            'recipient': recipient_code,
            'mock': True
        }
    
    def _mock_verify_transfer(self, reference: str) -> Tuple[bool, Dict]:
        """Mock transfer verification"""
        logger.info(f'[MOCK] Transfer verified: {reference}')
        
        return True, {
            'status': 'success',
            'amount': Decimal('5000.00'),
            'transferred_at': '2024-01-01T10:00:00',
            'recipient': 'RCP_mock_1234',
            'mock': True
        }
    
    def _mock_get_banks(self) -> Tuple[bool, list]:
        """Mock get banks"""
        logger.info('[MOCK] Retrieved banks list')
        
        return True, [
            {'name': 'Access Bank', 'code': '044', 'slug': 'access-bank'},
            {'name': 'GTBank', 'code': '058', 'slug': 'guaranty-trust-bank'},
            {'name': 'Zenith Bank', 'code': '057', 'slug': 'zenith-bank'},
            {'name': 'First Bank', 'code': '011', 'slug': 'first-bank-of-nigeria'},
            {'name': 'UBA', 'code': '033', 'slug': 'united-bank-for-africa'}
        ]


# Singleton instance
paystack_service = PaystackService()