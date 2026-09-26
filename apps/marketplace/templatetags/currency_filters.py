from django import template
from decimal import Decimal, InvalidOperation

register = template.Library()


@register.filter
def split_title(title):
    """
    Split a hero slide title into first word and the rest.
    'Tech & Electronics' -> ['Tech', '& Electronics']
    'Campus Essentials' -> ['Campus', 'Essentials']
    """
    if not title:
        return ['']
    parts = title.strip().split(None, 1)
    if len(parts) == 1:
        return parts
    return [parts[0], parts[1]]


@register.filter
def normalize_wa(phone):
    """
    Normalize a Nigerian phone number for wa.me links.
    Input: '08012345678', '+2348012345678', '2348012345678'
    Output: '2348012345678'
    """
    if not phone:
        return ''
    digits = ''.join(c for c in str(phone) if c.isdigit())
    if digits.startswith('0') and len(digits) == 11:
        return '234' + digits[1:]
    if digits.startswith('234'):
        return digits
    return digits


@register.filter
def naira(value):
    """
    Format a number as Nigerian Naira currency.
    Example: 500000 -> "₦500,000.00"
    """
    if value is None:
        return '₦0.00'
    try:
        value = Decimal(str(value))
    except (TypeError, ValueError, InvalidOperation):
        return '₦0.00'
    negative = value < 0
    value = abs(value)
    int_part = int(value)
    dec_part = value - int_part
    int_str = '{:,}'.format(int_part)
    dec_str = '{:.2f}'.format(dec_part)[1:]  # includes the "."
    result = f'₦{int_str}{dec_str}'
    if negative:
        result = f'-{result}'
    return result
