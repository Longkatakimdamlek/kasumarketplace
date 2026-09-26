"""
Quick Sell URL Configuration

Namespace: quicksell
Root: /quick-sell/

Phase 1: URL structure established with placeholder views.
Phase 5: UI redesign with proper marketplace-native experience.
"""

from django.urls import path
from apps.quicksell import views

app_name = 'quicksell'

urlpatterns = [

    # ---- LISTING MANAGEMENT ----
    path(
        '',
        views.quick_sell_landing,
        name='landing'
    ),
    path(
        'create/',
        views.quick_sell_create,
        name='create'
    ),
    path(
        'my-listings/',
        views.quick_sell_my_listings,
        name='my_listings'
    ),

    # ---- LISTING DETAIL / EDIT / DELETE ----
    path(
        '<slug:slug>/',
        views.quick_sell_detail,
        name='detail'
    ),
    path(
        '<slug:slug>/edit/',
        views.quick_sell_edit,
        name='edit'
    ),
    path(
        '<slug:slug>/delete/',
        views.quick_sell_delete,
        name='delete'
    ),

    # ---- AJAX (dynamic form helpers) ----
    path(
        'ajax/subcategories/',
        views.ajax_quick_sell_subcategories,
        name='ajax_subcategories'
    ),
    path(
        'ajax/attributes/',
        views.ajax_quick_sell_attributes,
        name='ajax_attributes'
    ),

    # ---- REPORTING ----
    path(
        '<int:id>/report/',
        views.report_quick_sell,
        name='report'
    ),
]
