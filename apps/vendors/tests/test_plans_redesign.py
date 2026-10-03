"""
Phase 6B - plans page visual redesign
=====================================

Render-level regression tests for the redesigned plans page:

  - the Phase 6 button matrix is unchanged: the same forms, actions, button
    labels and conditions render for every subscription state
  - the "Active" pill lands on exactly one card (or none when the vendor is
    restricted) and the "Best value" tag only on the featured premium card
  - the rendered HTML contains no non-ASCII emoji (icons are inline SVG)
  - the page's query count did not grow versus the pre-redesign measurement

Baseline query counts were captured BEFORE the redesign with this same
fixture (see report.txt):
    no_subscription 9, free_qualifying 10, trial_free 9, basic_active 9,
    premium_active 9, basic_cancelling 9, premium_cancelling_pending 9,
    restricted_expired 9

Phase 9 Task 7 then added exactly ONE query to every vendor page (the
memoised platform BVN toggle read in the vendor context processor); the
test allows that single query on top of each baseline and nothing more.
"""
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from apps.vendors.models import MainCategory, Store, Subscription

SUBSCRIBE = reverse('vendors:subscription_subscribe')
CANCEL = reverse('vendors:subscription_cancel')
DOWNGRADE = reverse('vendors:subscription_downgrade')

L_SUBSCRIBE_BASIC = 'Subscribe to Basic Plan'
L_SUBSCRIBE_PREMIUM = 'Subscribe to Premium Plan'
L_CURRENT = 'Current Plan'
L_UPGRADE = 'Upgrade to Premium'
L_SWITCH = 'Switch to Basic at End of Billing Period'
L_CANCEL = 'Cancel Subscription'

# Query counts measured before the redesign (see module docstring).
BASELINE_QUERIES = {
    'no_subscription': 9,
    'free_qualifying': 10,
    'trial_free': 9,
    'basic_active': 9,
    'premium_active': 9,
    'basic_cancelling': 9,
    'premium_cancelling_pending': 9,
    'restricted_expired': 9,
}

# Phase 9 Task 7 adds EXACTLY ONE query to every vendor page: the platform
# BVN toggle read in apps/vendors/context_processors.py::vendor_context.
# It is memoised on the request object, so it can never cost more than one
# query per request, and anonymous/public pages never pay for it (their
# context processor returns early).  This is the only permitted growth
# over the pre-redesign baseline above.
TASK7_BVN_TOGGLE_QUERY = 1

# state -> (subscription fields, present labels, absent labels, actions,
#           active-pill count, featured-tag count)
STATES = {
    'free_qualifying': (
        {'status': 'qualifying', 'plan': 'free'},
        [L_SUBSCRIBE_BASIC, L_SUBSCRIBE_PREMIUM],
        [L_CURRENT, L_UPGRADE, L_SWITCH, L_CANCEL],
        [SUBSCRIBE],
        1, 1,
    ),
    'trial_free': (
        {'status': 'trial', 'plan': 'free',
         'trial_ends_at': timezone.now() + timedelta(days=30)},
        [L_SUBSCRIBE_BASIC, L_SUBSCRIBE_PREMIUM],
        [L_CURRENT, L_UPGRADE, L_SWITCH, L_CANCEL],
        [SUBSCRIBE],
        1, 1,
    ),
    'basic_active': (
        {'status': 'active', 'plan': 'basic',
         'paystack_subscription_code': 'sub_basic',
         'period_end': timezone.now() + timedelta(days=20)},
        [L_CURRENT, L_UPGRADE, L_CANCEL],
        [L_SUBSCRIBE_BASIC, L_SUBSCRIBE_PREMIUM, L_SWITCH],
        [SUBSCRIBE, CANCEL],
        1, 1,
    ),
    'premium_active': (
        {'status': 'active', 'plan': 'premium',
         'paystack_subscription_code': 'sub_premium',
         'period_end': timezone.now() + timedelta(days=20)},
        [L_CURRENT, L_SWITCH, L_CANCEL],
        [L_SUBSCRIBE_BASIC, L_SUBSCRIBE_PREMIUM, L_UPGRADE],
        [CANCEL, DOWNGRADE],
        1, 0,
    ),
    'basic_cancelling': (
        {'status': 'active', 'plan': 'basic', 'cancel_at_period_end': True,
         'period_end': timezone.now() + timedelta(days=10)},
        [],
        [L_UPGRADE, L_CANCEL, L_SWITCH, L_SUBSCRIBE_BASIC, L_SUBSCRIBE_PREMIUM],
        [],
        1, 1,
    ),
    'premium_cancelling_pending': (
        {'status': 'active', 'plan': 'premium', 'cancel_at_period_end': True,
         'pending_plan': 'basic',
         'period_end': timezone.now() + timedelta(days=10)},
        [],
        [L_CANCEL, L_SWITCH, L_UPGRADE, L_SUBSCRIBE_BASIC, L_SUBSCRIBE_PREMIUM],
        [],
        1, 0,
    ),
    'restricted_expired': (
        {'status': 'expired', 'plan': 'premium',
         'period_end': timezone.now() - timedelta(days=1)},
        [L_SUBSCRIBE_BASIC, L_SUBSCRIBE_PREMIUM],
        [L_CURRENT, L_UPGRADE, L_SWITCH, L_CANCEL],
        [SUBSCRIBE],
        0, 1,
    ),
    'no_subscription': (
        None,
        [L_SUBSCRIBE_BASIC, L_SUBSCRIBE_PREMIUM],
        [L_CURRENT, L_UPGRADE, L_SWITCH, L_CANCEL],
        [SUBSCRIBE],
        0, 1,
    ),
}

EMOJI_RANGES = (
    (0x1F000, 0x1FAFF),   # emoticons, transport, symbols, supplemental
    (0x2600, 0x27BF),     # misc symbols + dingbats
    (0x2B00, 0x2BFF),     # misc symbols and arrows
    (0xFE00, 0xFE0F),     # variation selectors
    (0x200D, 0x200D),     # zero width joiner
    (0x20E3, 0x20E3),     # combining enclosing keycap
)


def emoji_chars(text):
    """Non-ASCII emoji code points found in `text` (digits/symbols ignored)."""
    found = []
    for char in text:
        code = ord(char)
        if code < 0x80:
            continue
        for low, high in EMOJI_RANGES:
            if low <= code <= high:
                found.append(char)
                break
    return found


class PlansPageFixture(TestCase):
    """Vendor + store + one subscription state, rendered plans page."""

    def setUp(self):
        user = get_user_model().objects.create_user(
            email='plans_6b@example.com',
            password='password123',
            username='plans_6b',
            role='vendor',
        )
        self.vendor = user.vendorprofile
        Subscription.objects.filter(vendor=self.vendor).delete()
        category = MainCategory.objects.create(name='Redesign', slug='redesign-6b')
        Store.objects.create(
            vendor=self.vendor,
            store_name='Redesign Store',
            slug='redesign-store',
            main_category=category,
        )
        self.client.force_login(user)

    def render(self, fields):
        Subscription.objects.filter(vendor=self.vendor).delete()
        if fields is not None:
            Subscription.objects.create(vendor=self.vendor, **fields)
        response = self.client.get(reverse('vendors:subscription_plans'))
        self.assertEqual(response.status_code, 200)
        return response.content.decode('utf-8')

    @staticmethod
    def paid_region(html):
        """Same slicing the Phase 6 matrix tests use."""
        return html[html.index('<!-- Basic Plan Card -->'):
                    html.index('<!-- Help Text -->')]

    @staticmethod
    def plans_region(html):
        """The plans page's own markup (shared chrome excluded).

        The base template's notification dropdown carries a pre-existing
        emoji in a notification title, which is not part of this page.
        """
        return html[html.index('<div class="kasu-plans'):
                    html.index('<!-- Footer -->')]


class PlansRenderMatrixTests(PlansPageFixture):
    """One test per state: buttons, actions, pill, tag and no emoji."""

    def assert_state(self, name):
        fields, present, absent, actions, pills, featured = STATES[name]

        html = self.render(fields)
        region = self.paid_region(html)

        for label in present:
            self.assertIn(label, region, '%s: missing %r' % (name, label))
        for label in absent:
            self.assertNotIn(label, region, '%s: unexpected %r' % (name, label))

        for action in actions:
            self.assertIn(action, region, '%s: missing action %s' % (name, action))
        if not actions:
            for action in (SUBSCRIBE, CANCEL, DOWNGRADE):
                self.assertNotIn(action, region,
                                 '%s: unexpected action %s' % (name, action))

        if actions:
            self.assertIn('csrfmiddlewaretoken', region,
                          '%s: form is missing its CSRF token' % name)

        self.assertEqual(html.count('kasu-active-pill'), pills,
                         '%s: wrong number of Active pills' % name)
        self.assertEqual(html.count('kasu-best-value'), featured,
                         '%s: wrong number of Best value tags' % name)

        # Every card renders plan name, price and summary + dashed divider.
        self.assertEqual(html.count('<article'), 3, name)
        self.assertEqual(html.count('border-dashed'), 3, name)

        self.assertEqual(emoji_chars(self.plans_region(html)), [],
                         '%s: emoji in rendered HTML' % name)

        return html

    def test_state_free_qualifying(self):
        self.assert_state('free_qualifying')

    def test_state_trial_free(self):
        self.assert_state('trial_free')

    def test_state_basic_active(self):
        html = self.assert_state('basic_active')
        self.assertIn('Active', html)

    def test_state_premium_active(self):
        html = self.assert_state('premium_active')
        self.assertIn('/month', html)

    def test_state_basic_cancelling(self):
        html = self.assert_state('basic_cancelling')
        self.assertIn('Your plan ends on', html)
        self.assertIn('No automatic charge will occur.', html)

    def test_state_premium_cancelling_pending_basic(self):
        html = self.assert_state('premium_cancelling_pending')
        self.assertIn(
            'You chose to switch to Basic. Subscribe to Basic after your '
            'current period ends.',
            html,
        )

    def test_state_restricted_expired(self):
        self.assert_state('restricted_expired')

    def test_state_no_subscription(self):
        self.assert_state('no_subscription')

    def test_no_pending_premium_copy_is_rendered(self):
        """No copy may promise a pending switch to Premium."""
        html = self.render(STATES['premium_cancelling_pending'][0])
        self.assertNotIn('switch to Premium Plan', html)
        self.assertNotIn('will switch to Premium', html)

    def test_all_three_cards_and_prices_are_rendered(self):
        html = self.render(STATES['free_qualifying'][0])
        for name in ('Free Plan', 'Basic Plan', 'Premium Plan'):
            self.assertIn(name, html)
        self.assertIn('₦1,200', html)
        self.assertIn('/month', html)
        self.assertIn('Free', html)

    def test_feature_rows_come_from_plans_py(self):
        html = self.render(STATES['free_qualifying'][0])
        self.assertIn('Store and products stay public', html)
        self.assertIn('Free subdomain (coming soon)', html)
        self.assertIn('Search and discovery promotion', html)
        self.assertIn('V-Batch', html)

    def test_cards_are_mobile_first_and_three_up_from_md(self):
        html = self.render(STATES['free_qualifying'][0])
        self.assertIn('grid-cols-1', html)
        self.assertIn('md:grid-cols-3', html)
        self.assertIn('kasu-plans', html)
        self.assertNotIn('Annual', html)
        self.assertNotIn('Monthly', html)


class PlansQueryCountTests(PlansPageFixture):
    """The redesign must not add a single query (see TASK7_BVN_TOGGLE_QUERY)."""

    def test_query_count_did_not_increase(self):
        for name, state in STATES.items():
            fields = state[0]
            Subscription.objects.filter(vendor=self.vendor).delete()
            if fields is not None:
                Subscription.objects.create(vendor=self.vendor, **fields)
            with CaptureQueriesContext(connection) as ctx:
                response = self.client.get(reverse('vendors:subscription_plans'))
            self.assertEqual(response.status_code, 200, name)
            used = len(ctx.captured_queries)
            allowed = BASELINE_QUERIES[name] + TASK7_BVN_TOGGLE_QUERY
            print('PLANS_QUERY_AFTER %-26s n=%d (baseline %d + %d)'
                  % (name, used, BASELINE_QUERIES[name], TASK7_BVN_TOGGLE_QUERY))
            self.assertLessEqual(
                used, allowed,
                '%s used %d queries, baseline was %d' % (name, used, allowed),
            )
