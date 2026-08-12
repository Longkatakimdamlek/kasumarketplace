"""
ZeptoMail HTTP API email sender.
Location: apps/users/services/zepto_api.py

Sends transactional email via ZeptoMail's HTTPS API instead of SMTP.
Render (and many PaaS hosts) block outbound SMTP ports (465/587) as an
anti-spam measure, which causes send_mail() / EmailMultiAlternatives to
hang until it times out. The API uses port 443 (regular HTTPS), which is
never blocked, since that's how every web request already works.

Drop-in replacement pattern: always returns (success: bool, message: str),
never raises — matches the existing OTPService.send_otp_email() contract.
"""

import logging
from typing import Tuple, Optional

import requests
from django.conf import settings

logger = logging.getLogger(__name__)

ZEPTO_API_URL = "https://api.zeptomail.com/v1.1/email"


def send_via_zepto_api(
    to_email: str,
    subject: str,
    html_body: str,
    plain_body: Optional[str] = None,
    to_name: str = "",
    reply_to: Optional[str] = None,
) -> Tuple[bool, str]:
    """
    Send a single transactional email via ZeptoMail's HTTP API.

    Args:
        to_email: Recipient email address
        subject: Email subject line
        html_body: HTML email body
        plain_body: Optional plain-text fallback (recommended)
        to_name: Optional recipient display name
        reply_to: Optional reply-to address

    Returns:
        Tuple[bool, str]: (success, message) — never raises.
    """
    api_token = getattr(settings, "ZEPTO_API_TOKEN", "") or getattr(
        settings, "EMAIL_HOST_PASSWORD", ""
    )
    from_email = getattr(settings, "DEFAULT_FROM_EMAIL", "no-reply@kasumarketplace.com.ng")

    if not api_token:
        return False, "ZeptoMail API token is not configured"

    headers = {
        "Authorization": api_token,
        "Content-Type": "application/json",
        "Accept": "application/json",
    }

    payload = {
        "from": {"address": from_email, "name": "KasuMarketplace"},
        "to": [
            {
                "email_address": {
                    "address": to_email,
                    "name": to_name or to_email.split("@")[0],
                }
            }
        ],
        "subject": subject,
        "htmlbody": html_body,
    }
    if plain_body:
        payload["textbody"] = plain_body
    if reply_to:
        payload["reply_to"] = [{"address": reply_to}]

    try:
        response = requests.post(
            ZEPTO_API_URL,
            json=payload,
            headers=headers,
            timeout=10,  # HTTPS is fast; 10s is generous, not a hang risk like SMTP
        )
    except requests.exceptions.Timeout:
        logger.error(f"ZeptoMail API timed out sending to {to_email}")
        return False, "Email service timed out. Please try again."
    except requests.exceptions.RequestException as e:
        logger.error(f"ZeptoMail API request failed for {to_email}: {e}")
        return False, "Email service is temporarily unavailable."

    if response.status_code in (200, 201):
        return True, "Email sent successfully"

    # Log full response for debugging but don't leak it to the user
    logger.error(
        f"ZeptoMail API error sending to {to_email}: "
        f"status={response.status_code} body={response.text[:500]}"
    )
    return False, f"Email failed to send (status {response.status_code})"