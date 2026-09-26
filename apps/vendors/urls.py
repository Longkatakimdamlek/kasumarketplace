from django.urls import path
from . import views

app_name = 'vendors'

urlpatterns = [
    # Dashboard
    path('', views.dashboard, name='dashboard'),

    # ==========================================
    # VERIFICATION FLOW (BVN + Selfie only)
    # ==========================================
    path('verification/', views.verification_center, name='verification_center'),

    # BVN + Selfie Flow (2 pages: BVN entry → live selfie capture)
    path('verification/bvn/', views.bvn_verification, name='bvn_verification'),
    path('verification/bvn/selfie/', views.bvn_selfie_capture, name='bvn_selfie_capture'),
    path('verification/success/', views.verification_success, name='verification_success'),

    # Store Setup
    path('verification/store/', views.store_setup, name='store_setup'),

    # ==========================================
    # PRODUCTS (VENDOR DASHBOARD - PRIVATE)
    # ==========================================
    path('products/', views.products_list, name='products_list'),
    path('wishlist/', views.vendor_wishlist, name='vendor_wishlist'),
    path('reviews/', views.vendor_reviews, name='vendor_reviews'),
    path('products/create/', views.product_create, name='product_create'),
    path('products/<slug:slug>/', views.product_detail, name='product_detail'),
    path('products/<slug:slug>/edit/', views.product_edit, name='product_edit'),
    path('products/<slug:slug>/delete/', views.product_delete, name='product_delete'),

    # ==========================================
    # STORE MANAGEMENT
    # ==========================================
    # Specific store management routes must come before the public slug route
    path('store/settings/', views.store_settings, name='store_settings'),
    path('store/preview/', views.store_public_preview, name='store_preview'),
    path('store/category-change/', views.category_change_request, name='category_change_request'),
    # Public storefront (catch-all slug) should be last to avoid matching 'settings' etc.
    path('store/<slug:slug>/', views.store_public, name='store_public'),

    # ==========================================
    # NOTIFICATIONS
    # ==========================================
    path('notifications/', views.notifications_list, name='notifications_list'),
    path('notifications/mark-all-read/', views.notifications_mark_all_read, name='notifications_mark_all_read'),
    path('notifications/<int:notification_id>/mark-read/', views.notification_mark_read, name='notification_mark_read'),
    path('notifications/<int:notification_id>/delete/', views.notification_delete, name='notification_delete'),
    path('notifications/<int:notification_id>/', views.notification_detail, name='notification_detail'),

    # ==========================================
    # PROFILE
    # ==========================================
    path('profile/', views.profile_view, name='profile_view'),

    # ==========================================
    # ACCOUNT DELETION REQUEST
    # ==========================================
    path('request-account-deletion/', views.request_account_deletion, name='request_account_deletion'),

    # ==========================================
    # AJAX ENDPOINTS
    # ==========================================
    path('ajax/subcategories/', views.ajax_get_subcategories, name='ajax_subcategories'),
    path('ajax/attributes/', views.ajax_get_attributes, name='ajax_attributes'),

    # ==========================================
    # SUBSCRIPTION WEBHOOK
    # ==========================================
    path('subscription/webhook/', views.subscription_webhook, name='subscription_webhook'),

    # ==========================================
    # CONTACT INTENT (fire-and-forget)
    # ==========================================
    path('products/<int:product_id>/contact-intent/', views.contact_intent, name='contact_intent'),

    # ==========================================
    # VENDOR REVIEW REPLY
    # ==========================================
    path('ajax/reviews/<int:review_id>/reply/', views.vendor_reply_to_review, name='vendor_reply_to_review'),
]