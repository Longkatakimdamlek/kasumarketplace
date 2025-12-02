"""
Vendor App Utility Functions
Helper functions for encryption, validation, file handling, etc.
"""

import os
import hashlib
import secrets
import string
import re
from typing import Optional, Tuple, Dict, Any
from decimal import Decimal
from datetime import datetime, timedelta
from django.core.files.uploadedfile import UploadedFile
from django.utils.text import slugify
from django.core.cache import cache
from django.conf import settings
from PIL import Image
import io
import logging

logger = logging.getLogger(__name__)


# ==========================================
# ENCRYPTION & SECURITY
# ==========================================

def encrypt_sensitive_data(data: str) -> str:
    """
    Encrypt sensitive data (NIN, BVN, etc.)
    Uses simple encryption for demo - replace with proper encryption in production
    
    Args:
        data: Data to encrypt
        
    Returns:
        Encrypted string
    """
    # TODO: Implement proper encryption using cryptography library
    # For now, just obfuscate the data
    if not data:
        return ''
    
    # Show only last 4 digits
    if len(data) > 4:
        return '*' * (len(data) - 4) + data[-4:]
    
    return data


def decrypt_sensitive_data(encrypted_data: str) -> str:
    """
    Decrypt sensitive data
    
    Args:
        encrypted_data: Encrypted string
        
    Returns:
        Decrypted string
    """
    # TODO: Implement proper decryption
    return encrypted_data


def hash_data(data: str) -> str:
    """
    Create SHA256 hash of data
    Useful for comparing sensitive data without storing it
    
    Args:
        data: Data to hash
        
    Returns:
        SHA256 hash as hex string
    """
    return hashlib.sha256(data.encode()).hexdigest()


def generate_reference(prefix: str = 'REF', length: int = 10) -> str:
    """
    Generate unique reference code
    
    Args:
        prefix: Reference prefix (e.g., 'ORD', 'PAY', 'REF')
        length: Length of random part
        
    Returns:
        Reference string (e.g., 'ORD_A8K3M9P2L5')
    """
    chars = string.ascii_uppercase + string.digits
    random_part = ''.join(secrets.choice(chars) for _ in range(length))
    timestamp = datetime.now().strftime('%Y%m%d')
    
    return f"{prefix}_{timestamp}_{random_part}"


def generate_otp(length: int = 6) -> str:
    """
    Generate numeric OTP code
    
    Args:
        length: OTP length (default 6)
        
    Returns:
        OTP string
    """
    return ''.join(secrets.choice(string.digits) for _ in range(length))


def store_otp_in_cache(key: str, otp: str, expiry_minutes: int = 10) -> bool:
    """
    Store OTP in cache with expiry
    
    Args:
        key: Cache key (e.g., 'nin_otp_12345678901')
        otp: OTP code
        expiry_minutes: Expiry time in minutes
        
    Returns:
        True if stored successfully
    """
    try:
        cache.set(key, otp, timeout=expiry_minutes * 60)
        return True
    except Exception as e:
        logger.error(f'Cache storage error: {str(e)}')
        return False


def verify_otp_from_cache(key: str, otp: str) -> bool:
    """
    Verify OTP from cache
    
    Args:
        key: Cache key
        otp: OTP to verify
        
    Returns:
        True if OTP matches and hasn't expired
    """
    stored_otp = cache.get(key)
    
    if not stored_otp:
        return False
    
    if stored_otp == otp:
        # Delete OTP after successful verification
        cache.delete(key)
        return True
    
    return False


# ==========================================
# VALIDATION
# ==========================================

def validate_nin(nin: str) -> Tuple[bool, str]:
    """
    Validate Nigerian National Identity Number
    
    Args:
        nin: NIN string
        
    Returns:
        Tuple of (is_valid: bool, error_message: str)
    """
    # Remove spaces and dashes
    nin = re.sub(r'[\s\-]', '', nin)
    
    # Check if 11 digits
    if not re.match(r'^\d{11}$', nin):
        return False, 'NIN must be exactly 11 digits'
    
    return True, ''


def validate_bvn(bvn: str) -> Tuple[bool, str]:
    """
    Validate Bank Verification Number
    
    Args:
        bvn: BVN string
        
    Returns:
        Tuple of (is_valid: bool, error_message: str)
    """
    # Remove spaces and dashes
    bvn = re.sub(r'[\s\-]', '', bvn)
    
    # Check if 11 digits
    if not re.match(r'^\d{11}$', bvn):
        return False, 'BVN must be exactly 11 digits'
    
    return True, ''


def validate_nigerian_phone(phone: str) -> Tuple[bool, str]:
    """
    Validate Nigerian phone number
    
    Args:
        phone: Phone number
        
    Returns:
        Tuple of (is_valid: bool, error_message: str)
    """
    # Remove spaces, dashes, parentheses
    phone = re.sub(r'[\s\-\(\)]', '', phone)
    
    # Check format: 080XXXXXXXX or +234XXXXXXXXXX or 234XXXXXXXXXX
    if re.match(r'^0[7-9][0-1]\d{8}$', phone):
        return True, ''
    elif re.match(r'^\+?234[7-9][0-1]\d{8}$', phone):
        return True, ''
    
    return False, 'Invalid Nigerian phone number format'


def validate_email(email: str) -> Tuple[bool, str]:
    """
    Validate email address
    
    Args:
        email: Email string
        
    Returns:
        Tuple of (is_valid: bool, error_message: str)
    """
    pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    
    if re.match(pattern, email):
        return True, ''
    
    return False, 'Invalid email format'


# ==========================================
# FILE HANDLING
# ==========================================

def validate_image_file(file: UploadedFile, max_size_mb: int = 5) -> Tuple[bool, str]:
    """
    Validate uploaded image file
    
    Args:
        file: Uploaded file
        max_size_mb: Maximum file size in MB
        
    Returns:
        Tuple of (is_valid: bool, error_message: str)
    """
    # Check file size
    max_size_bytes = max_size_mb * 1024 * 1024
    if file.size > max_size_bytes:
        return False, f'File size must be less than {max_size_mb}MB'
    
    # Check file type
    allowed_types = ['image/jpeg', 'image/jpg', 'image/png']
    if file.content_type not in allowed_types:
        return False, 'Only JPG and PNG images are allowed'
    
    # Try to open image
    try:
        img = Image.open(file)
        img.verify()
        return True, ''
    except Exception as e:
        return False, 'Invalid image file'


def compress_image(file: UploadedFile, max_width: int = 1200, quality: int = 85) -> io.BytesIO:
    """
    Compress and resize image
    
    Args:
        file: Uploaded image file
        max_width: Maximum width in pixels
        quality: JPEG quality (1-100)
        
    Returns:
        Compressed image as BytesIO
    """
    try:
        img = Image.open(file)
        
        # Convert RGBA to RGB if necessary
        if img.mode in ('RGBA', 'LA', 'P'):
            background = Image.new('RGB', img.size, (255, 255, 255))
            background.paste(img, mask=img.split()[-1] if img.mode == 'RGBA' else None)
            img = background
        
        # Resize if too large
        if img.width > max_width:
            ratio = max_width / img.width
            new_height = int(img.height * ratio)
            img = img.resize((max_width, new_height), Image.Resampling.LANCZOS)
        
        # Save to BytesIO
        output = io.BytesIO()
        img.save(output, format='JPEG', quality=quality, optimize=True)
        output.seek(0)
        
        return output
    
    except Exception as e:
        logger.error(f'Image compression error: {str(e)}')
        return None


def generate_unique_filename(original_filename: str, prefix: str = '') -> str:
    """
    Generate unique filename to avoid collisions
    
    Args:
        original_filename: Original filename
        prefix: Optional prefix
        
    Returns:
        Unique filename
    """
    # Get file extension
    name, ext = os.path.splitext(original_filename)
    
    # Clean filename
    name = slugify(name)
    
    # Add timestamp and random string
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    random_str = secrets.token_hex(4)
    
    if prefix:
        return f"{prefix}_{name}_{timestamp}_{random_str}{ext}"
    
    return f"{name}_{timestamp}_{random_str}{ext}"


# ==========================================
# MONEY & CALCULATIONS
# ==========================================

def calculate_commission(amount: Decimal, commission_rate: Decimal) -> Tuple[Decimal, Decimal]:
    """
    Calculate commission and vendor amount
    
    Args:
        amount: Total amount
        commission_rate: Commission percentage (e.g., 10.00 for 10%)
        
    Returns:
        Tuple of (commission_amount, vendor_amount)
    """
    commission = (amount * commission_rate) / 100
    vendor_amount = amount - commission
    
    # Round to 2 decimal places
    commission = round(commission, 2)
    vendor_amount = round(vendor_amount, 2)
    
    return commission, vendor_amount


def format_currency(amount: Decimal, currency: str = 'NGN') -> str:
    """
    Format amount as currency string
    
    Args:
        amount: Amount to format
        currency: Currency code
        
    Returns:
        Formatted string (e.g., '₦10,000.00')
    """
    if currency == 'NGN':
        symbol = '₦'
    elif currency == 'USD':
        symbol = '$'
    else:
        symbol = currency
    
    # Format with thousands separator
    formatted = f"{amount:,.2f}"
    
    return f"{symbol}{formatted}"


def parse_currency_input(input_str: str) -> Optional[Decimal]:
    """
    Parse currency input string to Decimal
    
    Args:
        input_str: User input (e.g., '10,000', '₦5000.50')
        
    Returns:
        Decimal value or None if invalid
    """
    # Remove currency symbols and spaces
    cleaned = re.sub(r'[₦$,\s]', '', input_str)
    
    try:
        return Decimal(cleaned)
    except:
        return None


# ==========================================
# TEXT PROCESSING
# ==========================================

def truncate_text(text: str, max_length: int = 100, suffix: str = '...') -> str:
    """
    Truncate text to max length
    
    Args:
        text: Text to truncate
        max_length: Maximum length
        suffix: Suffix to add (e.g., '...')
        
    Returns:
        Truncated text
    """
    if len(text) <= max_length:
        return text
    
    return text[:max_length - len(suffix)] + suffix


def mask_sensitive_info(text: str, visible_chars: int = 4) -> str:
    """
    Mask sensitive information (show only last N characters)
    
    Args:
        text: Text to mask
        visible_chars: Number of characters to show at end
        
    Returns:
        Masked text (e.g., '080****5678')
    """
    if not text or len(text) <= visible_chars:
        return text
    
    masked_length = len(text) - visible_chars
    return '*' * masked_length + text[-visible_chars:]


def generate_slug_from_title(title: str, max_length: int = 50) -> str:
    """
    Generate URL-friendly slug from title
    
    Args:
        title: Product/store title
        max_length: Maximum slug length
        
    Returns:
        Slug string
    """
    slug = slugify(title)
    
    if len(slug) > max_length:
        slug = slug[:max_length]
    
    return slug


# ==========================================
# DATE & TIME
# ==========================================

def format_datetime(dt: datetime, format_str: str = '%d %b %Y, %I:%M %p') -> str:
    """
    Format datetime to readable string
    
    Args:
        dt: Datetime object
        format_str: Format string
        
    Returns:
        Formatted string (e.g., '15 Jan 2024, 10:30 AM')
    """
    if not dt:
        return ''
    
    return dt.strftime(format_str)


def get_time_ago(dt: datetime) -> str:
    """
    Get human-readable time difference
    
    Args:
        dt: Datetime object
        
    Returns:
        String like 'just now', '5 minutes ago', '2 hours ago'
    """
    if not dt:
        return ''
    
    now = datetime.now()
    diff = now - dt
    
    seconds = diff.total_seconds()
    
    if seconds < 60:
        return 'just now'
    elif seconds < 3600:
        minutes = int(seconds / 60)
        return f'{minutes} minute{"s" if minutes > 1 else ""} ago'
    elif seconds < 86400:
        hours = int(seconds / 3600)
        return f'{hours} hour{"s" if hours > 1 else ""} ago'
    elif seconds < 604800:
        days = int(seconds / 86400)
        return f'{days} day{"s" if days > 1 else ""} ago'
    else:
        return format_datetime(dt, '%d %b %Y')


def is_business_hours(current_time: datetime = None) -> bool:
    """
    Check if current time is within business hours (9 AM - 6 PM, Mon-Sat)
    
    Args:
        current_time: Time to check (defaults to now)
        
    Returns:
        True if within business hours
    """
    if not current_time:
        current_time = datetime.now()
    
    # Check day of week (0 = Monday, 6 = Sunday)
    if current_time.weekday() == 6:  # Sunday
        return False
    
    # Check hour (9 AM to 6 PM)
    if 9 <= current_time.hour < 18:
        return True
    
    return False


# ==========================================
# DATA SANITIZATION
# ==========================================

def sanitize_filename(filename: str) -> str:
    """
    Sanitize filename to remove dangerous characters
    
    Args:
        filename: Original filename
        
    Returns:
        Sanitized filename
    """
    # Remove path separators and dangerous characters
    filename = re.sub(r'[/\\:*?"<>|]', '', filename)
    
    # Limit length
    name, ext = os.path.splitext(filename)
    if len(name) > 100:
        name = name[:100]
    
    return name + ext


def sanitize_phone_for_display(phone: str) -> str:
    """
    Format phone number for display
    
    Args:
        phone: Phone number
        
    Returns:
        Formatted phone (e.g., '0801 234 5678')
    """
    # Remove all non-digits
    phone = re.sub(r'\D', '', phone)
    
    # Format as 0801 234 5678
    if phone.startswith('234'):
        phone = '0' + phone[3:]
    
    if len(phone) == 11:
        return f'{phone[:4]} {phone[4:7]} {phone[7:]}'
    
    return phone


# ==========================================
# RATE LIMITING
# ==========================================

def check_rate_limit(key: str, max_attempts: int = 3, window_minutes: int = 60) -> Tuple[bool, int]:
    """
    Check if action is rate limited
    
    Args:
        key: Rate limit key (e.g., 'nin_verify_12345678901')
        max_attempts: Maximum attempts allowed
        window_minutes: Time window in minutes
        
    Returns:
        Tuple of (is_allowed: bool, remaining_attempts: int)
    """
    cache_key = f'rate_limit_{key}'
    attempts = cache.get(cache_key, 0)
    
    if attempts >= max_attempts:
        return False, 0
    
    # Increment attempts
    cache.set(cache_key, attempts + 1, timeout=window_minutes * 60)
    
    remaining = max_attempts - (attempts + 1)
    return True, remaining


def reset_rate_limit(key: str) -> bool:
    """
    Reset rate limit for a key
    
    Args:
        key: Rate limit key
        
    Returns:
        True if reset successfully
    """
    cache_key = f'rate_limit_{key}'
    cache.delete(cache_key)
    return True


# ==========================================
# ANALYTICS HELPERS
# ==========================================

def calculate_percentage_change(old_value: Decimal, new_value: Decimal) -> Decimal:
    """
    Calculate percentage change between two values
    
    Args:
        old_value: Old value
        new_value: New value
        
    Returns:
        Percentage change (e.g., 25.5 for 25.5% increase)
    """
    if old_value == 0:
        return Decimal('0')
    
    change = ((new_value - old_value) / old_value) * 100
    return round(change, 2)


def get_stats_comparison(current: Decimal, previous: Decimal) -> Dict[str, Any]:
    """
    Get comparison statistics
    
    Args:
        current: Current period value
        previous: Previous period value
        
    Returns:
        Dict with change info
    """
    change = current - previous
    percentage = calculate_percentage_change(previous, current)
    
    return {
        'current': current,
        'previous': previous,
        'change': change,
        'percentage': percentage,
        'trend': 'up' if change > 0 else 'down' if change < 0 else 'stable'
    }