"""
Marketplace URL Configuration
All buyer-facing URLs for KasuMarketplace.
Namespace: marketplace
"""

from django.urls import path
from apps.marketplace import views

app_name = 'marketplace'

urlpatterns = [

    # ---- PRODUCTS ----
    path(
        '',
        views.product_list,
        name='product_list'
    ),
    path(
        'about/',
        views.about_page,
        name='about'
    ),
    path(
        'cookies/',
        views.cookies_page,
        name='cookies'
    ),
    path(
        'privacy/',
        views.privacy_policy,
        name='privacy'
    ),
    path(
        'terms/',
        views.terms_of_service,
        name='terms'
    ),
    path(
        'search/',
        views.search_results,
        name='search'
    ),
    path(
        'new-arrivals/',
        views.new_arrivals,
        name='new_arrivals'
    ),
    path(
        'deals/',
        views.deals,
        name='deals'
    ),
    path(
        'quick-sell/',
        views.quicksell_listing,
        name='quicksell_listing'
    ),
    path(
        'trending/',
        views.trending,
        name='trending'
    ),
    path(
        'sponsored/',
        views.sponsored_products,
        name='sponsored_products'
    ),
    path(
        'stores/',
        views.store_directory,
        name='store_directory'
    ),
    path(
        'category/<slug:slug>/',
        views.category_landing,
        name='category_landing'
    ),
    path(
        'product/<slug:slug>/',
        views.product_detail,
        name='product_detail'
    ),

    # ---- STORE ----
    path(
        'store/<slug:slug>/',
        views.store_detail,
        name='store_detail'
    ),

    # ---- WISHLIST ----
    path(
        'wishlist/',
        views.wishlist_view,
        name='wishlist'
    ),
    path(
        'wishlist/update-qty/',
        views.wishlist_update_qty,
        name='wishlist_update_qty'
    ),
    path(
        'wishlist/remove/',
        views.wishlist_remove,
        name='wishlist_remove'
    ),

    # ---- BUYER LOCATION ----
    path(
        'location/update/',
        views.update_buyer_location,
        name='update_buyer_location'
    ),
    path('profile/', views.profile, name='profile'),
    path('profile/personal-information/', views.personal_information, name='personal_information'),
    path('contact/', views.contact_us, name='contact'),
    path('help/', views.help_center, name='help'),
    path('buyer-protection/', views.buyer_protection, name='buyer_protection'),
    path('community-guidelines/', views.community_guidelines, name='community_guidelines'),
    path('request-account-deletion/', views.request_account_deletion, name='request_account_deletion'),
    path('product/<int:product_id>/report/', views.report_product, name='report_product'),

    # ---- BUYER NOTIFICATIONS ----
    path('notifications/', views.buyer_notifications_list, name='buyer_notifications_list'),
    path('notifications/mark-all-read/', views.buyer_notifications_mark_all_read, name='buyer_notifications_mark_all_read'),
    path('notifications/<int:notification_id>/mark-read/', views.buyer_notification_mark_read, name='buyer_notification_mark_read'),
    path('notifications/<int:notification_id>/delete/', views.buyer_notification_delete, name='buyer_notification_delete'),
    path('notifications/<int:notification_id>/', views.buyer_notification_detail, name='buyer_notification_detail'),
]