"""
URL configuration for KasuMarketplace users app.
Location: apps/users/urls.py
"""
<<<<<<< HEAD
=======
from .views import CustomPasswordResetView
>>>>>>> fcc348e5a2c27b1bd240c5f05727e083445490bf
from django.urls import path
from . import views

app_name = 'users'

urlpatterns = [
<<<<<<< HEAD
    # ==========================================
    # AUTHENTICATION
    # ==========================================
    path('signup/buyer/', views.BuyerSignupView.as_view(), name='buyer_signup'),
    path('signup/vendor/', views.VendorSignupView.as_view(), name='vendor_signup'),  
    path('login/', views.LoginView.as_view(), name='login'),
    path('logout/', views.logout_view, name='logout'),
    
    # OTP Verification
    path('verify-otp/', views.OTPVerificationView.as_view(), name='verify_otp'),
    path('resend-otp/', views.ResendOTPView.as_view(), name='resend_otp'),
    
    # ==========================================
    # DASHBOARDS (Redirects)
    # ==========================================
    path('buyer/dashboard/', views.buyer_dashboard, name='buyer_dashboard'),
    path('vendor/dashboard/', views.vendor_dashboard, name='vendor_dashboard'),  # Redirects to vendors:dashboard
    
    # ==========================================
    # PASSWORD RESET
    # ==========================================
    path('password-reset/', views.PasswordResetRequestView.as_view(), name='password_reset'),  # ✅ Only ONE definition
    path('password-reset/done/', views.PasswordResetDoneView.as_view(), name='password_reset_done'),
    path('password-reset-confirm/<uidb64>/<token>/', views.PasswordResetConfirmView.as_view(), name='password_reset_confirm'),
    path('password-reset-complete/', views.PasswordResetCompleteView.as_view(), name='password_reset_complete'),
=======
    path('signup/buyer/', views.BuyerSignupView.as_view(), name='buyer_signup'),
    path('signup/vendor/', views.VendorSignupView.as_view(), name='vendor_signup'),
    path('login/', views.LoginView.as_view(), name='login'),
    path('logout/', views.logout_view, name='logout'),
    path('verify-otp/', views.OTPVerificationView.as_view(), name='verify_otp'),
    path('resend-otp/', views.ResendOTPView.as_view(), name='resend_otp'),
    # Dashboard
    path('buyer/dashboard/', views.buyer_dashboard, name='buyer_dashboard'),
    path('vendor/dashboard/', views.vendor_dashboard, name='vendor_dashboard'),

    # reset password
    path('password-reset/', views.PasswordResetRequestView.as_view(), name='password_reset'),
    path('password-reset/done/', views.PasswordResetDoneView.as_view(), name='password_reset_done'),
    path('password-reset-confirm/<uidb64>/<token>/', views.PasswordResetConfirmView.as_view(), name='password_reset_confirm'),
    path('password-reset-complete/', views.PasswordResetCompleteView.as_view(), name='password_reset_complete'),
    path('password-reset/', CustomPasswordResetView.as_view(), name='password_reset'),
>>>>>>> fcc348e5a2c27b1bd240c5f05727e083445490bf
]