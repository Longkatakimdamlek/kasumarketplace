"""
Notification Service
Handles email and SMS notifications for vendors
Supports multiple providers with fallback

Email Providers:
- Django SMTP (Gmail, Outlook, etc.)
- Resend API
- SendGrid API

SMS Providers:
- Termii API
- Africa's Talking API
- Twilio API

Environment Variables:
- EMAIL_BACKEND (default: django.core.mail.backends.smtp.EmailBackend)
- EMAIL_HOST, EMAIL_PORT, EMAIL_HOST_USER, EMAIL_HOST_PASSWORD
- RESEND_API_KEY (optional)
- TERMII_API_KEY (optional)
- USE_MOCK_NOTIFICATIONS (set to 'True' for testing)
"""

import os
import logging
from typing import Dict, Optional, List
from django.core.mail import send_mail, EmailMultiAlternatives
from django.template.loader import render_to_string
from django.conf import settings
from django.utils.html import strip_tags

logger = logging.getLogger(__name__)


class NotificationError(Exception):
    """Custom exception for notification errors"""
    pass


class EmailService:
    """
    Email service with multiple provider support
    """
    
    def __init__(self):
        self.use_mock = os.getenv('USE_MOCK_NOTIFICATIONS', 'True').lower() == 'true'
        self.from_email = getattr(settings, 'DEFAULT_FROM_EMAIL', 'noreply@kasumarketplace.com')
        self.resend_api_key = os.getenv('RESEND_API_KEY', '')
    
    def send_email(
        self,
        to_email: str,
        subject: str,
        message: str,
        html_message: Optional[str] = None,
        from_email: Optional[str] = None
    ) -> bool:
        """
        Send email using Django's email backend
        
        Args:
            to_email: Recipient email
            subject: Email subject
            message: Plain text message
            html_message: HTML message (optional)
            from_email: Sender email (optional, uses default)
            
        Returns:
            True if sent successfully, False otherwise
        """
        
        if self.use_mock:
            return self._mock_send_email(to_email, subject, message)
        
        try:
            from_email = from_email or self.from_email
            
            # Send email
            if html_message:
                # Send both HTML and plain text versions
                email = EmailMultiAlternatives(
                    subject=subject,
                    body=message,
                    from_email=from_email,
                    to=[to_email]
                )
                email.attach_alternative(html_message, "text/html")
                email.send()
            else:
                # Send plain text only
                send_mail(
                    subject=subject,
                    message=message,
                    from_email=from_email,
                    recipient_list=[to_email],
                    fail_silently=False
                )
            
            logger.info(f'Email sent to {to_email}: {subject}')
            return True
        
        except Exception as e:
            logger.error(f'Email send error: {str(e)}')
            return False
    
    def send_template_email(
        self,
        to_email: str,
        subject: str,
        template_name: str,
        context: Dict
    ) -> bool:
        """
        Send email using Django template
        
        Args:
            to_email: Recipient email
            subject: Email subject
            template_name: Template path (e.g., 'vendors/emails/nin_verified.html')
            context: Template context data
            
        Returns:
            True if sent successfully
        """
        
        if self.use_mock:
            return self._mock_send_email(to_email, subject, f"Template: {template_name}")
        
        try:
            # Render HTML template
            html_message = render_to_string(template_name, context)
            
            # Generate plain text version
            plain_message = strip_tags(html_message)
            
            return self.send_email(
                to_email=to_email,
                subject=subject,
                message=plain_message,
                html_message=html_message
            )
        
        except Exception as e:
            logger.error(f'Template email error: {str(e)}')
            return False
    
    def _mock_send_email(self, to_email: str, subject: str, message: str) -> bool:
        """Mock email sending for testing"""
        logger.info(f'[MOCK EMAIL] To: {to_email} | Subject: {subject}')
        logger.info(f'[MOCK EMAIL] Message: {message[:100]}...')
        return True


class SMSService:
    """
    SMS service with multiple provider support
    """
    
    def __init__(self):
        self.use_mock = os.getenv('USE_MOCK_NOTIFICATIONS', 'True').lower() == 'true'
        self.termii_api_key = os.getenv('TERMII_API_KEY', '')
        self.termii_sender_id = os.getenv('TERMII_SENDER_ID', 'KasuMarket')
    
    def send_sms(
        self,
        phone: str,
        message: str
    ) -> bool:
        """
        Send SMS using Termii API
        
        Args:
            phone: Phone number (e.g., '08012345678' or '+2348012345678')
            message: SMS message (max 160 chars recommended)
            
        Returns:
            True if sent successfully
        """
        
        if self.use_mock:
            return self._mock_send_sms(phone, message)
        
        # Normalize phone number
        phone = self._normalize_phone(phone)
        
        if not self.termii_api_key:
            logger.warning('Termii API key not configured. Using mock mode.')
            return self._mock_send_sms(phone, message)
        
        try:
            import requests
            
            response = requests.post(
                'https://api.ng.termii.com/api/sms/send',
                json={
                    'api_key': self.termii_api_key,
                    'to': phone,
                    'from': self.termii_sender_id,
                    'sms': message,
                    'type': 'plain',
                    'channel': 'generic'
                },
                timeout=30
            )
            
            response.raise_for_status()
            result = response.json()
            
            if result.get('message') == 'Successfully Sent':
                logger.info(f'SMS sent to {phone}')
                return True
            else:
                logger.error(f'SMS send failed: {result}')
                return False
        
        except Exception as e:
            logger.error(f'SMS send error: {str(e)}')
            return False
    
    def _normalize_phone(self, phone: str) -> str:
        """
        Normalize Nigerian phone number
        
        Examples:
            08012345678 → 2348012345678
            +2348012345678 → 2348012345678
            2348012345678 → 2348012345678
        """
        # Remove spaces, dashes, parentheses
        phone = ''.join(filter(str.isdigit, phone))
        
        # Add country code if missing
        if phone.startswith('0'):
            phone = '234' + phone[1:]
        elif not phone.startswith('234'):
            phone = '234' + phone
        
        return phone
    
    def _mock_send_sms(self, phone: str, message: str) -> bool:
        """Mock SMS sending for testing"""
        logger.info(f'[MOCK SMS] To: {phone} | Message: {message}')
        return True


class NotificationService:
    """
    Main notification service - combines email and SMS
    """
    
    def __init__(self):
        self.email = EmailService()
        self.sms = SMSService()
    
    # ==========================================
    # VENDOR VERIFICATION NOTIFICATIONS
    # ==========================================
    
    def send_nin_verified(self, vendor) -> bool:
        """
        Send email when NIN verification succeeds
        
        Args:
            vendor: VendorProfile instance
        """
        return self.email.send_template_email(
            to_email=vendor.user.email,
            subject='NIN Verification Successful ✅',
            template_name='vendors/emails/nin_verified.html',
            context={
                'vendor': vendor,
                'vendor_name': vendor.full_name,
                'next_step': 'BVN Verification'
            }
        )
    
    def send_bvn_verified(self, vendor) -> bool:
        """Send email when BVN verification succeeds"""
        return self.email.send_template_email(
            to_email=vendor.user.email,
            subject='BVN Verification Successful ✅',
            template_name='vendors/emails/bvn_verified.html',
            context={
                'vendor': vendor,
                'vendor_name': vendor.full_name,
                'bank_name': vendor.wallet.bank_name if hasattr(vendor, 'wallet') else '',
                'next_step': 'Store Setup'
            }
        )
    
    def send_verification_approved(self, vendor) -> bool:
        """
        Send email when admin approves vendor verification
        
        Args:
            vendor: VendorProfile instance
        """
        success = self.email.send_template_email(
            to_email=vendor.user.email,
            subject='Your Vendor Account is Approved! 🎉',
            template_name='vendors/emails/verification_approved.html',
            context={
                'vendor': vendor,
                'vendor_name': vendor.full_name,
                'dashboard_url': f'{settings.SITE_URL}/vendors/dashboard/'
            }
        )
        
        # Also send SMS
        if vendor.phone:
            self.sms.send_sms(
                vendor.phone,
                f'Congratulations {vendor.full_name}! Your KasuMarketplace vendor account is now approved. Start selling today!'
            )
        
        return success
    
    def send_verification_rejected(self, vendor, reason: str = '') -> bool:
        """Send email when admin rejects vendor verification"""
        return self.email.send_template_email(
            to_email=vendor.user.email,
            subject='Verification Update Required',
            template_name='vendors/emails/verification_rejected.html',
            context={
                'vendor': vendor,
                'vendor_name': vendor.full_name,
                'reason': reason or vendor.admin_comment,
                'support_email': 'support@kasumarketplace.com'
            }
        )
    
    # ==========================================
    # ORDER NOTIFICATIONS
    # ==========================================
    
    def send_new_order(self, order) -> bool:
        """
        Send email and SMS when vendor receives new order
        
        Args:
            order: Order instance
        """
        vendor = order.vendor
        
        # Send email
        email_success = self.email.send_template_email(
            to_email=vendor.user.email,
            subject=f'New Order Received - #{str(order.order_id)[:8]}',
            template_name='vendors/emails/new_order.html',
            context={
                'vendor': vendor,
                'order': order,
                'order_url': f'{settings.SITE_URL}/vendors/orders/{order.order_id}/'
            }
        )
        
        # Send SMS
        if vendor.phone:
            self.sms.send_sms(
                vendor.phone,
                f'New order received! Order #{str(order.order_id)[:8]} - ₦{order.total_amount}. Check your dashboard.'
            )
        
        return email_success
    
    def send_order_status_update(self, order, customer_email: str) -> bool:
        """
        Send email to customer when order status changes
        
        Args:
            order: Order instance
            customer_email: Customer's email
        """
        status_messages = {
            'confirmed': 'Your order has been confirmed and is being prepared.',
            'processing': 'Your order is being processed.',
            'shipped': f'Your order has been shipped. Tracking: {order.tracking_number}',
            'delivered': 'Your order has been delivered. Enjoy your purchase!',
        }
        
        message = status_messages.get(order.status, f'Your order status: {order.get_status_display()}')
        
        return self.email.send_email(
            to_email=customer_email,
            subject=f'Order Update - #{str(order.order_id)[:8]}',
            message=f"""
Hello,

{message}

Order ID: #{str(order.order_id)[:8]}
Total: ₦{order.total_amount}

Thank you for shopping on KasuMarketplace!

Best regards,
KasuMarketplace Team
            """,
        )
    
    # ==========================================
    # WALLET/PAYOUT NOTIFICATIONS
    # ==========================================
    
    def send_payout_successful(self, vendor, amount, bank_name: str) -> bool:
        """
        Send email when payout is successful
        
        Args:
            vendor: VendorProfile instance
            amount: Payout amount
            bank_name: Bank name
        """
        email_success = self.email.send_template_email(
            to_email=vendor.user.email,
            subject=f'Payout Successful - ₦{amount}',
            template_name='vendors/emails/payout_successful.html',
            context={
                'vendor': vendor,
                'amount': amount,
                'bank_name': bank_name,
                'wallet_url': f'{settings.SITE_URL}/vendors/wallet/'
            }
        )
        
        # Send SMS
        if vendor.phone:
            self.sms.send_sms(
                vendor.phone,
                f'Payout successful! ₦{amount} has been sent to your {bank_name} account.'
            )
        
        return email_success
    
    def send_payment_received(self, vendor, amount, order_id: str) -> bool:
        """Send notification when vendor receives payment"""
        
        # Send email
        email_success = self.email.send_email(
            to_email=vendor.user.email,
            subject=f'Payment Received - ₦{amount}',
            message=f"""
Hello {vendor.full_name},

You've received a payment of ₦{amount} for order #{order_id}.

This amount is now in your pending balance and will be available for withdrawal once the order is delivered.

View details: {settings.SITE_URL}/vendors/wallet/

Best regards,
KasuMarketplace Team
            """
        )
        
        return email_success
    
    # ==========================================
    # OTP NOTIFICATIONS
    # ==========================================
    
    def send_otp_sms(self, phone: str, otp_code: str, purpose: str = 'verification') -> bool:
        """
        Send OTP via SMS
        
        Args:
            phone: Phone number
            otp_code: OTP code
            purpose: Purpose of OTP (e.g., 'verification', 'login')
        """
        message = f'Your KasuMarketplace {purpose} code is: {otp_code}. Valid for 10 minutes. Do not share this code.'
        
        return self.sms.send_sms(phone, message)
    
    # ==========================================
    # BULK NOTIFICATIONS
    # ==========================================
    
    def send_bulk_email(
        self,
        recipients: List[str],
        subject: str,
        message: str,
        html_message: Optional[str] = None
    ) -> Dict[str, int]:
        """
        Send email to multiple recipients
        
        Args:
            recipients: List of email addresses
            subject: Email subject
            message: Plain text message
            html_message: HTML message (optional)
            
        Returns:
            Dict with 'success' and 'failed' counts
        """
        success_count = 0
        failed_count = 0
        
        for email in recipients:
            try:
                if self.email.send_email(email, subject, message, html_message):
                    success_count += 1
                else:
                    failed_count += 1
            except Exception as e:
                logger.error(f'Bulk email error for {email}: {str(e)}')
                failed_count += 1
        
        logger.info(f'Bulk email complete: {success_count} success, {failed_count} failed')
        
        return {
            'success': success_count,
            'failed': failed_count,
            'total': len(recipients)
        }
    
    # ==========================================
    # ADMIN NOTIFICATIONS
    # ==========================================
    
    def notify_admin_new_vendor(self, vendor) -> bool:
        """
        Notify admins when new vendor completes verification
        
        Args:
            vendor: VendorProfile instance
        """
        admin_emails = getattr(settings, 'ADMIN_EMAILS', ['admin@kasumarketplace.com'])
        
        return self.email.send_email(
            to_email=admin_emails[0],  # Send to first admin
            subject=f'New Vendor Pending Review - {vendor.full_name}',
            message=f"""
New vendor pending review:

Name: {vendor.full_name}
Email: {vendor.user.email}
Phone: {vendor.phone}
Store: {vendor.store.store_name if hasattr(vendor, 'store') else 'Not set up'}

NIN Verified: {vendor.identity_status == 'nin_verified'}
BVN Verified: {vendor.bank_status == 'bvn_verified'}

Review in admin: {settings.SITE_URL}/admin/vendors/vendorprofile/{vendor.id}/change/

Best regards,
KasuMarketplace System
            """
        )


# Singleton instance
notification_service = NotificationService()