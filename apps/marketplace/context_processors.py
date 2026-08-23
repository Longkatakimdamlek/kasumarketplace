from apps.marketplace.services.cart_service import get_or_create_cart
from apps.vendors.models import MainCategory
import logging

logger = logging.getLogger(__name__)

def cart_context(request):
    try:
        cart = get_or_create_cart(request)
        return {'cart_count': cart.total_items}
    except Exception as e:
        logger.error(f"Error in cart_context: {str(e)}", exc_info=True)
        return {'cart_count': 0}


def categories_processor(request):
    """Make active categories and their subcategories available globally."""
    try:
        return {
            'categories': MainCategory.objects.filter(
                is_active=True
            ).prefetch_related('subcategories').order_by('sort_order'),
        }
    except Exception as e:
        logger.error(f"Error in categories_processor: {str(e)}", exc_info=True)
        return {'categories': []}