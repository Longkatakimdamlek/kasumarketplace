from django.urls import path
from . import views

app_name = 'vendors'

urlpatterns = [
    # Dashboard
    path('', views.dashboard, name='dashboard'),
    
    # ==========================================
    # VERIFICATION FLOW (Complete)
    # ==========================================
    path('verification/', views.verification_center, name='verification_center'),
    
    # NIN Flow
    path('verification/nin/', views.nin_entry, name='nin_entry'),
    path('verification/nin-otp/', views.nin_otp, name='nin_otp'),
    path('verification/nin-success/', views.nin_success, name='nin_success'),
    
    # BVN Flow
    path('verification/bvn/', views.bvn_entry, name='bvn_entry'),
    path('verification/bvn-otp/', views.bvn_otp, name='bvn_otp'),
    path('verification/bvn-success/', views.bvn_success, name='bvn_success'),
    
    # Store Setup & Student
    path('verification/store/', views.store_setup, name='store_setup'),
    path('verification/student/', views.student_verification, name='student_verification'),
    path('verification/pending-review/', views.pending_review, name='pending_review'),
    
    # ==========================================
    # PRODUCTS
    # ==========================================
    path('products/', views.products_list, name='products_list'),
    path('products/create/', views.product_create, name='product_create'),
    path('products/<slug:slug>/', views.product_detail, name='product_detail'),
    path('products/<slug:slug>/edit/', views.product_edit, name='product_edit'),
    path('products/<slug:slug>/delete/', views.product_delete, name='product_delete'),
    
    # ==========================================
    # ORDERS
    # ==========================================
    path('orders/', views.orders_list, name='orders_list'),
    path('orders/<uuid:order_id>/', views.order_detail, name='order_detail'),
    path('orders/<uuid:order_id>/update-status/', views.order_status_update_ajax, name='order_status_update_ajax'),
    
    # ==========================================
    # WALLET
    # ==========================================
    path('wallet/', views.wallet_overview, name='wallet_overview'),
    path('wallet/transactions/', views.wallet_transactions, name='wallet_transactions'),
    path('wallet/payout/', views.request_payout, name='request_payout'),
    path('wallet/payment-method/', views.payment_method, name='payment_method'),
    
    # ==========================================
    # STORE MANAGEMENT
    # ==========================================
    path('store/settings/', views.store_settings, name='store_settings'),
    path('store/preview/', views.store_public_preview, name='store_preview'),
    path('store/category-change/', views.category_change_request, name='category_change_request'),
    # NOTE: Public storefront URL moved to main urls.py (see below)
    
    # ==========================================
    # NOTIFICATIONS
    # ==========================================
    path('notifications/', views.notifications_list, name='notifications_list'),
    path('notifications/<int:notification_id>/', views.notification_detail, name='notification_detail'),
    
    # ==========================================
    # PROFILE
    # ==========================================
    path('profile/', views.profile_view, name='profile_view'),
    path('profile/edit/', views.profile_edit, name='profile_edit'),
    
    # ==========================================
    # AJAX ENDPOINTS
    # ==========================================
    path('ajax/subcategories/', views.get_subcategories_ajax, name='get_subcategories_ajax'),
    path('ajax/attributes/', views.get_category_attributes_ajax, name='get_attributes_ajax'),
]