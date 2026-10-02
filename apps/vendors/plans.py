"""
Plan configuration for KasuMarketplace vendor subscriptions.
Single source of truth for plan identifiers, display names, prices, and benefits.
"""
from django.conf import settings


PLANS = {
    'free': {
        'identifier': 'free',
        'display_name': 'Free Plan',
        'price_naira': 0,
        'price_kobo': 0,
        'paystack_plan_code_setting': '',  # No Paystack plan for free tier
        'benefits': [],
        'is_paid': False,
        # Display data only (Phase 6B): one-line summary + the card feature
        # rows (label, included). Nothing here feeds billing or webhooks.
        'summary': (
            'Perfect for getting started - access dashboard, set up your '
            'store, and manage products.'
        ),
        'features': [
            {'label': 'Store and products stay public', 'included': True},
            {
                'label': (
                    '3-month free trial after you publish 3 products '
                    'within 7 days'
                ),
                'included': True,
            },
            {'label': 'V-Batch', 'included': False},
            {'label': 'Promotions', 'included': False},
            {'label': 'SEO service', 'included': False},
        ],
    },
    'basic': {
        'identifier': 'basic',
        'display_name': 'Basic Plan',
        'price_naira': 1200,
        'price_kobo': 120000,  # N1,200 in kobo
        'paystack_plan_code_setting': 'PAYSTACK_BASIC_PLAN_CODE',
        'benefits': [
            'Premium Store Control',
            'Unlimited Product Listing',
            'No marketplace restrictions',
            'Free Subdomain',
        ],
        'is_paid': True,
        'summary': (
            'Unlock unlimited products, premium store control, and a free '
            'subdomain.'
        ),
        'features': [
            {'label': 'Unlimited product listing', 'included': True},
            {'label': 'Full store control', 'included': True},
            {'label': 'No marketplace restrictions', 'included': True},
            {'label': 'Free subdomain (coming soon)', 'included': True},
            {'label': 'V-Batch', 'included': False},
            {'label': 'Promotions', 'included': False},
            {'label': 'SEO service', 'included': False},
        ],
    },
    'premium': {
        'identifier': 'premium',
        'display_name': 'Premium Plan',
        'price_naira': 3000,
        'price_kobo': 300000,  # N3,000 in kobo
        'paystack_plan_code_setting': 'PAYSTACK_PREMIUM_PLAN_CODE',
        'benefits': [
            'Everything in Basic',
            'Product Promotion',
            'Store Promotion',
            'V-Batch',
            'Search/Discovery promotion',
            'SEO service',
        ],
        'is_paid': True,
        'summary': (
            'Everything in Basic plus product/store promotion, V-Batch, '
            'search discovery boost, and SEO service.'
        ),
        'features': [
            {'label': 'Everything in Basic', 'included': True},
            {'label': 'Product and store promotions', 'included': True},
            {'label': 'V-Batch', 'included': True},
            {'label': 'Search and discovery promotion', 'included': True},
            {'label': 'SEO service', 'included': True},
        ],
    },
}


def get_plan(identifier: str) -> dict:
    """
    Get plan configuration by identifier.
    Raises KeyError if identifier is not found.
    """
    if identifier not in PLANS:
        raise KeyError(f"Unknown plan identifier: {identifier}")
    return PLANS[identifier]


def paid_plans() -> list:
    """Return list of paid plan configurations."""
    return [p for p in PLANS.values() if p['is_paid']]


def plan_for_paystack_code(code: str) -> str | None:
    """
    Map a Paystack plan code back to our internal plan identifier.
    Returns None if the code is not recognized.
    """
    basic_code = getattr(settings, 'PAYSTACK_BASIC_PLAN_CODE', '') or ''
    premium_code = getattr(settings, 'PAYSTACK_PREMIUM_PLAN_CODE', '') or ''
    if code == basic_code:
        return 'basic'
    if code == premium_code:
        return 'premium'
    return None


def format_price(naira: int) -> str:
    """Format price with Naira sign and thousands separator."""
    return f'₦{naira:,}'


def get_paystack_plan_code(identifier: str) -> str:
    """
    Get the Paystack plan code for a given plan identifier from settings.
    Returns empty string if not configured.
    """
    plan = get_plan(identifier)
    setting_name = plan['paystack_plan_code_setting']
    return getattr(settings, setting_name, '') or ''


def get_plan_price_kobo(identifier: str) -> int:
    """Get the price in kobo for a given plan identifier."""
    return get_plan(identifier)['price_kobo']


def get_plan_price_naira(identifier: str) -> int:
    """Get the price in naira for a given plan identifier."""
    return get_plan(identifier)['price_naira']