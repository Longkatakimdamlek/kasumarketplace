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
]