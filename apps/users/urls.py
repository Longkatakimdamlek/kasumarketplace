from django.urls import path
from . import views
from .views import CustomPasswordResetView

app_name = "users"

urlpatterns = [
    # AUTH
    path("signup/buyer/", views.BuyerSignupView.as_view(), name="buyer_signup"),
    path("signup/vendor/", views.VendorSignupView.as_view(), name="vendor_signup"),
    path("login/", views.LoginView.as_view(), name="login"),
    path("logout/", views.logout_view, name="logout"),

    # OTP
    path("verify-otp/", views.OTPVerificationView.as_view(), name="verify_otp"),
    path("resend-otp/", views.ResendOTPView.as_view(), name="resend_otp"),

    # DASHBOARDS
    path("buyer/dashboard/", views.buyer_dashboard, name="buyer_dashboard"),
    path("vendor/dashboard/", views.vendor_dashboard, name="vendor_dashboard"),

    # PASSWORD RESET
    path("password-reset/", CustomPasswordResetView.as_view(), name="password_reset"),
    path("password-reset/done/", views.PasswordResetDoneView.as_view(), name="password_reset_done"),
    path("password-reset-confirm/<uidb64>/<token>/", views.PasswordResetConfirmView.as_view(), name="password_reset_confirm"),
    path("password-reset-complete/", views.PasswordResetCompleteView.as_view(), name="password_reset_complete"),
]
