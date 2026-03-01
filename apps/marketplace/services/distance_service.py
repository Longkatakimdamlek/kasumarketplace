"""
Distance Service
Haversine formula — calculates straight-line distance
between buyer location and store location.
No external API required.
"""

import math
from decimal import Decimal


def haversine_distance(lat1, lon1, lat2, lon2) -> float:
    """
    Calculate distance in kilometres between two coordinates
    using the Haversine formula.

    Args:
        lat1, lon1: Buyer coordinates (float or Decimal)
        lat2, lon2: Store coordinates (float or Decimal)

    Returns:
        Distance in kilometres (float), rounded to 1 decimal place.
    """
    # Convert Decimal to float if needed
    lat1 = float(lat1)
    lon1 = float(lon1)
    lat2 = float(lat2)
    lon2 = float(lon2)

    # Earth radius in kilometres
    R = 6371.0

    # Convert degrees to radians
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)

    # Haversine formula
    a = (
        math.sin(delta_phi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2) ** 2
    )
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

    distance = R * c
    return round(distance, 1)


def get_distance_to_store(buyer_lat, buyer_lon, store) -> str:
    """
    Get formatted distance string from buyer to a store.

    Args:
        buyer_lat: Buyer latitude (float, Decimal, or None)
        buyer_lon: Buyer longitude (float, Decimal, or None)
        store: Store instance with .latitude and .longitude fields

    Returns:
        Formatted string: "3.2 km away" or "Distance unavailable"
    """
    if buyer_lat is None or buyer_lon is None:
        return "Distance unavailable"

    if store.latitude is None or store.longitude is None:
        return "Distance unavailable"

    try:
        km = haversine_distance(buyer_lat, buyer_lon, store.latitude, store.longitude)
        if km < 1.0:
            # Show in metres for very close stores
            metres = int(km * 1000)
            return f"{metres}m away"
        return f"{km} km away"
    except (ValueError, TypeError):
        return "Distance unavailable"


def annotate_products_with_distance(products, buyer_lat, buyer_lon) -> list:
    """
    Takes a queryset of products and returns a list of dicts,
    each with the product and its distance string.

    Args:
        products: QuerySet of Product instances
        buyer_lat: Buyer latitude or None
        buyer_lon: Buyer longitude or None

    Returns:
        List of dicts: [{'product': <Product>, 'distance': '3.2 km away'}, ...]
    """
    result = []
    for product in products.select_related('store'):
        distance = get_distance_to_store(buyer_lat, buyer_lon, product.store)
        result.append({
            'product': product,
            'distance': distance,
        })
    return result