"""
Read-only template access to apps.vendors.plans (Phase 6B).

The plans page context is built in views.subscription_plans and is not
allowed to change, so the card feature rows and summaries are read straight
from the PLANS dict through these tags.  Data only: no queries, no writes.
"""
from django import template

from apps.vendors.plans import get_plan

register = template.Library()


@register.simple_tag
def plan_features(identifier):
    """Feature rows (label + included) for one plan identifier."""
    return get_plan(identifier).get('features', [])


@register.simple_tag
def plan_summary(identifier):
    """One-line plan summary for one plan identifier."""
    return get_plan(identifier).get('summary', '')
