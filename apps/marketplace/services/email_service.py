"""
Email Service
Sends transactional emails for marketplace order events.

Events:
- order_placed       → buyer confirmation + vendor notification
- order_accepted     → buyer notified, contact unlocked
- order_rejected     → buyer notified, refund triggered
- order_confirmed    → vendor notified, 24h hold starts
- order_cancelled    → buyer notified (timeout), refund triggered
- order_disputed     → admin notified

Uses Django's built-in send_mail.
Configure in settings.py:
    EMAIL_BACKEND = 'django.core.mail.backends.smtp.EmailBackend'
    EMAIL_HOST = 'smtp.gmail.com'
    EMAIL_PORT = 587
    EMAIL_USE_TLS = True
    EMAIL_HOST_USER = 'your@email.com'
    EMAIL_HOST_PASSWORD = 'your_app_password'
    DEFAULT_FROM_EMAIL = 'KasuMarketplace <noreply@kasumarketplace.com>'
"""

import logging
from django.core.mail import send_mail
from django.conf import settings
from django.template.loader import render_to_string
from django.utils.html import strip_tags

logger = logging.getLogger(__name__)

FROM_EMAIL = getattr(settings, 'DEFAULT_FROM_EMAIL', 'KasuMarketplace <noreply@kasumarketplace.com>')
ADMIN_EMAIL = getattr(settings, 'ADMIN_EMAIL', settings.ADMINS[0][1] if settings.ADMINS else None)


def _send(subject, message, recipient_list, html_message=None):
    """
    Safe wrapper around send_mail.
    Logs errors but never raises — email failure must not break order flow.
    """
    try:
        send_mail(
            subject=subject,
            message=message,
            from_email=FROM_EMAIL,
            recipient_list=recipient_list,
            html_message=html_message,
            fail_silently=False,
        )
        logger.info(f'Email sent: "{subject}" → {recipient_list}')
    except Exception as e:
        logger.error(f'Email failed: "{subject}" → {recipient_list}: {str(e)}')


# ==========================================
# ORDER PLACED
# ==========================================

def send_order_placed(main_order):
    """
    Buyer: order confirmation.
    Each vendor: notification of new SubOrder.
    """
    buyer = main_order.buyer
    buyer_email = buyer.email

    # ---- BUYER EMAIL ----
    subject = f'Order Confirmed — {main_order.order_number}'
    suborders_summary = '\n'.join([
        f'  • {sub.store.store_name}: ₦{sub.subtotal:,.0f} ({sub.items.count()} item(s))'
        for sub in main_order.suborders.all()
    ])
    message = f"""Hi {buyer_email},

Your order has been placed successfully!

Order Number: {main_order.order_number}
Total: ₦{main_order.total:,.0f}

Items ordered:
{suborders_summary}

Delivery to: {main_order.delivery_address}, {main_order.delivery_city}

Each vendor has 48 hours to accept your order.
You will be notified when they respond.

Thank you for shopping on KasuMarketplace!
"""
    _send(subject, message, [buyer_email])

    # ---- VENDOR EMAILS ----
    for sub in main_order.suborders.select_related('store__vendor__user').all():
        vendor_email = sub.store.vendor.user.email
        items_list = '\n'.join([
            f'  • {item.product_title} x{item.quantity} — ₦{item.subtotal:,.0f}'
            for item in sub.items.all()
        ])
        vendor_subject = f'New Order — {main_order.order_number}'
        vendor_message = f"""Hi {sub.store.store_name},

You have a new order!

Order: {main_order.order_number}
Subtotal: ₦{sub.subtotal:,.0f}

Items:
{items_list}

Delivery address: {main_order.delivery_address}, {main_order.delivery_city}
Buyer phone: {main_order.delivery_phone}

⚠️ You have 48 hours to accept or reject this order.
Log in to your vendor dashboard to respond.

KasuMarketplace
"""
        _send(vendor_subject, vendor_message, [vendor_email])


# ==========================================
# ORDER ACCEPTED
# ==========================================

def send_order_accepted(sub_order):
    """
    Buyer: vendor accepted, contact now unlocked.
    """
    main_order = sub_order.main_order
    buyer_email = main_order.buyer.email
    store = sub_order.store

    subject = f'Order Accepted — {main_order.order_number}'
    message = f"""Hi {buyer_email},

Great news! {store.store_name} has accepted your order.

Order: {main_order.order_number}
Store: {store.store_name}
Amount: ₦{sub_order.subtotal:,.0f}

You can now see the vendor's contact details in your order.
Log in to coordinate delivery.

Once you receive your items, please confirm delivery to release payment to the vendor.

KasuMarketplace
"""
    _send(subject, message, [buyer_email])


# ==========================================
# ORDER REJECTED
# ==========================================

def send_order_rejected(sub_order):
    """
    Buyer: vendor rejected, refund coming.
    """
    main_order = sub_order.main_order
    buyer_email = main_order.buyer.email
    store = sub_order.store

    subject = f'Order Update — {main_order.order_number}'
    message = f"""Hi {buyer_email},

Unfortunately, {store.store_name} was unable to fulfil your order.

Order: {main_order.order_number}
Store: {store.store_name}
Amount: ₦{sub_order.subtotal:,.0f}

A full refund of ₦{sub_order.subtotal:,.0f} will be processed to your original payment method within 24 hours.

We're sorry for the inconvenience. You can continue browsing other vendors on KasuMarketplace.

KasuMarketplace
"""
    _send(subject, message, [buyer_email])


# ==========================================
# ORDER CONFIRMED (buyer pressed YES)
# ==========================================

def send_order_confirmed(sub_order):
    """
    Vendor: buyer confirmed receipt, funds releasing in 24h.
    """
    store = sub_order.store
    vendor_email = store.vendor.user.email
    main_order = sub_order.main_order

    subject = f'Payment Releasing — {main_order.order_number}'
    message = f"""Hi {store.store_name},

The buyer has confirmed receipt of their order.

Order: {main_order.order_number}
Amount: ₦{sub_order.subtotal:,.0f}

Your payment will be available in your wallet within 24 hours.

KasuMarketplace
"""
    _send(subject, message, [vendor_email])


# ==========================================
# ORDER CANCELLED (timeout)
# ==========================================

def send_order_cancelled_timeout(sub_order):
    """
    Buyer: order auto-cancelled because vendor didn't respond.
    """
    main_order = sub_order.main_order
    buyer_email = main_order.buyer.email
    store = sub_order.store

    subject = f'Order Cancelled — {main_order.order_number}'
    message = f"""Hi {buyer_email},

Your order from {store.store_name} has been automatically cancelled because the vendor did not respond within 48 hours.

Order: {main_order.order_number}
Amount: ₦{sub_order.subtotal:,.0f}

A full refund of ₦{sub_order.subtotal:,.0f} will be processed within 24 hours.

KasuMarketplace
"""
    _send(subject, message, [buyer_email])


# ==========================================
# DISPUTE OPENED
# ==========================================

def send_dispute_opened(dispute):
    """
    Admin: dispute opened, needs review.
    Buyer: confirmation that dispute was received.
    """
    sub_order = dispute.sub_order
    main_order = sub_order.main_order
    buyer_email = main_order.buyer.email

    # Buyer confirmation
    buyer_subject = f'Dispute Received — {main_order.order_number}'
    buyer_message = f"""Hi {buyer_email},

We have received your dispute for order {main_order.order_number}.

Store: {sub_order.store.store_name}
Amount: ₦{sub_order.subtotal:,.0f}
Reason: {dispute.reason}

Our team will review your case and contact you within 24 hours.
Funds are locked until the dispute is resolved.

KasuMarketplace Support
"""
    _send(buyer_subject, buyer_message, [buyer_email])

    # Admin notification
    if ADMIN_EMAIL:
        admin_subject = f'[Dispute] Order {main_order.order_number} — Action Required'
        admin_message = f"""New dispute opened.

Order: {main_order.order_number}
Buyer: {buyer_email}
Store: {sub_order.store.store_name}
Amount: ₦{sub_order.subtotal:,.0f}

Reason:
{dispute.reason}

Review in admin: /admin/marketplace/dispute/
"""
        _send(admin_subject, admin_message, [ADMIN_EMAIL])