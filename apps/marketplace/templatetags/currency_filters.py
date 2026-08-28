from django import template
from decimal import Decimal

register = template.Library()


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
    except (TypeError, ValueError, Decimal.InvalidOperation):
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
