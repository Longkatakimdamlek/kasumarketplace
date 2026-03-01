"""
Cart Service
All cart operations — get, add, update, remove, clear.
Session-based: no login required.
Cart merges into user account on login (handled by signals).
"""

from apps.marketplace.models import Cart, CartItem
from apps.vendors.models import Product


def get_or_create_cart(request) -> Cart:
    """
    Get the cart for the current request.
    - If user is logged in: get or create cart linked to user
    - If anonymous: get or create cart linked to session key
    Always ensures session exists first.
    """
    # Ensure session exists
    if not request.session.session_key:
        request.session.create()

    session_key = request.session.session_key

    if request.user.is_authenticated:
        # Try to get user's cart first
        cart = Cart.objects.filter(user=request.user).first()
        if cart:
            return cart
        # No user cart — get or create by session
        cart, created = Cart.objects.get_or_create(session_key=session_key)
        if created or cart.user is None:
            cart.user = request.user
            cart.save(update_fields=['user'])
        return cart
    else:
        cart, _ = Cart.objects.get_or_create(session_key=session_key)
        return cart


def merge_session_cart_to_user(session_key: str, user) -> None:
    """Utility called when the session key is known explicitly.

    This encapsulates the merging logic used by the login signal and by
    our custom login view.  ``session_key`` should be the *old* (anonymous)
    key; after Django logs the user in the request.session.session_key will
    have been rotated.  If ``None`` or empty, the function is a no-op.
    """
    if not session_key:
        return

    try:
        anon_cart = Cart.objects.get(session_key=session_key, user__isnull=True)
    except Cart.DoesNotExist:
        return

    try:
        user_cart = Cart.objects.get(user=user)
    except Cart.DoesNotExist:
        anon_cart.user = user
        anon_cart.save(update_fields=['user'])
        return

    for anon_item in anon_cart.items.all():
        existing = user_cart.items.filter(product=anon_item.product).first()
        if existing:
            existing.quantity += anon_item.quantity
            existing.save(update_fields=['quantity'])
        else:
            anon_item.cart = user_cart
            anon_item.save(update_fields=['cart'])

    anon_cart.delete()


def add_to_cart(request, product_id: int, quantity: int = 1) -> dict:
    """
    Add a product to the cart or increase its quantity.

    Returns:
        dict with keys: success (bool), message (str), cart_total_items (int)
    """
    try:
        product = Product.objects.select_related('store').get(
            pk=product_id,
            status='published'
        )
    except Product.DoesNotExist:
        return {
            'success': False,
            'message': 'Product not found or unavailable.'
        }

    # Check stock
    if product.track_inventory and product.stock_quantity < quantity:
        return {
            'success': False,
            'message': f'Only {product.stock_quantity} item(s) left in stock.'
        }

    cart = get_or_create_cart(request)

    cart_item, created = CartItem.objects.get_or_create(
        cart=cart,
        product=product,
        defaults={'quantity': quantity}
    )

    if not created:
        # Product already in cart — increase quantity
        new_quantity = cart_item.quantity + quantity

        # Check stock for updated quantity
        if product.track_inventory and product.stock_quantity < new_quantity:
            return {
                'success': False,
                'message': f'Cannot add more. Only {product.stock_quantity} item(s) available.'
            }

        cart_item.quantity = new_quantity
        cart_item.save(update_fields=['quantity'])

    return {
        'success': True,
        'message': f'"{product.title}" added to cart.',
        'cart_total_items': cart.total_items,
    }


def update_cart_item(request, product_id: int, quantity: int) -> dict:
    """
    Set a specific quantity for a cart item.
    If quantity <= 0, remove the item.

    Returns:
        dict with keys: success (bool), message (str), cart_total_items (int)
    """
    if quantity <= 0:
        return remove_from_cart(request, product_id)

    cart = get_or_create_cart(request)

    try:
        cart_item = CartItem.objects.select_related('product').get(
            cart=cart,
            product_id=product_id
        )
    except CartItem.DoesNotExist:
        return {'success': False, 'message': 'Item not found in cart.'}

    product = cart_item.product

    # Check stock
    if product.track_inventory and product.stock_quantity < quantity:
        return {
            'success': False,
            'message': f'Only {product.stock_quantity} item(s) available.'
        }

    cart_item.quantity = quantity
    cart_item.save(update_fields=['quantity'])

    return {
        'success': True,
        'message': 'Cart updated.',
        'cart_total_items': cart.total_items,
    }


def remove_from_cart(request, product_id: int) -> dict:
    """
    Remove a product entirely from the cart.

    Returns:
        dict with keys: success (bool), message (str), cart_total_items (int)
    """
    cart = get_or_create_cart(request)

    deleted, _ = CartItem.objects.filter(
        cart=cart,
        product_id=product_id
    ).delete()

    if deleted:
        return {
            'success': True,
            'message': 'Item removed from cart.',
            'cart_total_items': cart.total_items,
        }
    return {
        'success': False,
        'message': 'Item not found in cart.',
        'cart_total_items': cart.total_items,
    }


def clear_cart(cart: Cart) -> None:
    """
    Delete all items from a cart.
    Called after successful order creation.
    """
    cart.items.all().delete()


def get_cart_summary(request) -> dict:
    """
    Get full cart data for display in templates.

    Returns dict with:
        - cart: Cart instance
        - items_by_store: {store: [CartItem, ...]}
        - grand_total: Decimal
        - total_items: int
        - is_empty: bool
    """
    cart = get_or_create_cart(request)

    return {
        'cart': cart,
        'items_by_store': cart.get_items_by_store(),
        'grand_total': cart.grand_total,
        'total_items': cart.total_items,
        'is_empty': cart.is_empty,
    }