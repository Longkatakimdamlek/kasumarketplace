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

    # ---- CART ----
    path(
        'cart/',
        views.cart_view,
        name='cart'
    ),
    path(
        'wishlist/',
        views.wishlist_view,
        name='wishlist'
    ),
    path(
        'cart/add/',
        views.cart_add,
        name='cart_add'
    ),
    path(
        'cart/update/',
        views.cart_update,
        name='cart_update'
    ),
    path(
        'cart/remove/',
        views.cart_remove,
        name='cart_remove'
    ),

    # ---- CHECKOUT ----
    path(
        'checkout/',
        views.checkout,
        name='checkout'
    ),
    path(
        'checkout/save-delivery/',
        views.checkout_save_delivery,
        name='checkout_save_delivery'
    ),

    # ---- PAYMENT ----
    path(
        'payment/verify/',
        views.payment_verify,
        name='payment_verify'
    ),
    path(
        'payment/webhook/',
        views.paystack_webhook,
        name='paystack_webhook'
    ),

    # ---- ORDERS ----
    path(
        'orders/',
        views.order_list,
        name='order_list'
    ),
    path(
        'orders/<str:order_number>/',
        views.order_detail,
        name='order_detail'
    ),

    # ---- ORDER ACTIONS ----
    path(
        'orders/suborder/<int:suborder_id>/confirm/',
        views.confirm_receipt,
        name='confirm_receipt'
    ),
    path(
        'orders/suborder/<int:suborder_id>/dispute/',
        views.report_issue,
        name='report_issue'
    ),

    # ---- BUYER LOCATION ----
    path(
        'location/update/',
        views.update_buyer_location,
        name='update_buyer_location'
    ),
    path('profile/', views.profile, name='profile'),
    path('contact/', views.contact_us, name='contact'),
    path('help/', views.help_center, name='help'),
    path('buyer-protection/', views.buyer_protection, name='buyer_protection'),
    path('community-guidelines/', views.community_guidelines, name='community_guidelines'),
    path('request-account-deletion/', views.request_account_deletion, name='request_account_deletion'),
    path('product/<int:product_id>/report/', views.report_product, name='report_product'),
]