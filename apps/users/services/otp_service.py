"""
OTP Service Module
Location: apps/users/services/otp_service.py

Handles all OTP generation, verification, and management.
Production-ready with secure hashing and expiration handling.
"""

import random
import string
from typing import Dict, Tuple

from django.conf import settings
from django.core.mail import send_mail
from django.template.loader import render_to_string
from django.utils import timezone
from django.utils.html import strip_tags

from apps.users.models import OTPVerification, CustomUser


class OTPService:
    """Service class for OTP operations."""
    
    DEFAULT_OTP_LENGTH = 6
    
    @staticmethod
    def generate_otp(length: int = None) -> str:
        """
        Generate a random numeric OTP code.
        
        Args:
            length (int): Length of OTP code (default: 6)
        
        Returns:
            str: Random numeric OTP code
        """
        if length is None:
            length = getattr(settings, 'OTP_LENGTH', OTPService.DEFAULT_OTP_LENGTH)
        
        return ''.join(random.choices(string.digits, k=length))
    
    @staticmethod
    def create_otp(user: CustomUser) -> Tuple[OTPVerification, str]:
        """
        Create a new OTP for the user.
        Checks generation rate limit first.
        
        Args:
            user (CustomUser): User requesting OTP
        
        Returns:
            Tuple[OTPVerification, str] or Tuple[None, str]: Created OTP instance and plain OTP code,
                                                            or (None, error_message) if rate limited
        """
        # Check generation rate limit
        is_rate_limited, error_msg, time_until_retry = OTPVerification.check_generation_rate_limit(user)
        if is_rate_limited:
            return None, error_msg
        
        otp_code = OTPService.generate_otp()
        otp_instance = OTPVerification.create_otp(user, otp_code)
        return otp_instance, otp_code
    
    @staticmethod
    def verify_otp(user: CustomUser, otp_code: str) -> Dict:
        """
        Verify the OTP code for a user.
        
        Args:
            user (CustomUser): User verifying OTP
            otp_code (str): Plain text OTP code to verify
        
        Returns:
            Dict: {
                'success': bool,
                'error': str or None,
                'remaining_attempts': int,
                'time_remaining': int (seconds)
            }
        """
        try:
            otp = OTPVerification.objects.get(user=user)
        except OTPVerification.DoesNotExist:
            return {
                'success': False,
                'error': 'No OTP found. Please request a new one.',
                'remaining_attempts': 0,
                'time_remaining': 0
            }
        
        result = otp.verify_otp(otp_code)
        
        return {
            'success': result['success'],
            'error': result['error'],
            'remaining_attempts': otp.remaining_attempts,
            'time_remaining': otp.time_remaining
        }
    
    @staticmethod
    def get_otp(user: CustomUser) -> OTPVerification or None:
        """
        Get the current OTP for a user.
        
        Args:
            user (CustomUser): User to get OTP for
        
        Returns:
            OTPVerification or None: OTP instance if exists, None otherwise
        """
        try:
            return OTPVerification.objects.get(user=user)
        except OTPVerification.DoesNotExist:
            return None
    
    @staticmethod
    def delete_otp(user: CustomUser) -> bool:
        """
        Delete OTP for a user.
        
        Args:
            user (CustomUser): User to delete OTP for
        
        Returns:
            bool: True if deleted, False otherwise
        """
        try:
            OTPVerification.objects.get(user=user).delete()
            return True
        except OTPVerification.DoesNotExist:
            return False
    
    @staticmethod
    def send_otp_email(user: CustomUser, otp_code: str) -> Tuple[bool, str]:
        """
        Send OTP verification email to user.
        
        Args:
            user (CustomUser): User instance
            otp_code (str): OTP code to send
        
        Returns:
            Tuple[bool, str]: (success: bool, message: str)
        """
        try:
            if not otp_code or not isinstance(otp_code, str):
                return False, "Invalid OTP code provided"
            
            subject = 'Verify Your Email - KasuMarketplace'
            
            # Create HTML email content
            html_message = render_to_string('users/emails/otp_email.html', {
                'user': user,
                'otp': otp_code,
                'expiry_time': OTPVerification.OTP_EXPIRY_MINUTES,
            })
            
            # Create plain text version
            plain_message = strip_tags(html_message)
            
            # Send email
            from_email = getattr(
                settings,
                'DEFAULT_FROM_EMAIL',
                'noreply@kasumarketplace.com'
            )
            
            send_mail(
                subject=subject,
                message=plain_message,
                from_email=from_email,
                recipient_list=[user.email],
                html_message=html_message,
                fail_silently=False,
            )
            
            return True, "OTP email sent successfully"
        
        except Exception as e:
            error_msg = f"Error sending OTP email: {str(e)}"
            return False, error_msg
    
    @staticmethod
    def clean_expired_otps() -> int:
        """
        Delete all expired OTPs from the database.
        Should be run periodically via management command.
        
        Returns:
            int: Number of expired OTPs deleted
        """
        expired_otps = OTPVerification.objects.filter(
            expires_at__lt=timezone.now()
        )
        count, _ = expired_otps.delete()
        return count
    
    @staticmethod
    def clean_used_otps(days: int = 7) -> int:
        """
        Delete used OTPs older than specified days.
        Helps keep database clean.
        
        Args:
            days (int): Number of days to keep used OTPs
        
        Returns:
            int: Number of used OTPs deleted
        """
        cutoff_date = timezone.now() - timezone.timedelta(days=days)
        used_otps = OTPVerification.objects.filter(
            is_used=True,
            used_at__lt=cutoff_date
        )
        count, _ = used_otps.delete()
        return count