from apps.marketplace.services.cart_service import get_or_create_cart
import logging

logger = logging.getLogger(__name__)

def cart_context(request):
    try:
        cart = get_or_create_cart(request)
        return {'cart_count': cart.total_items}
    except Exception as e:
        logger.error(f"Error in cart_context: {str(e)}", exc_info=True)
        return {'cart_count': 0}