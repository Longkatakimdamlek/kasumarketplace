"""
Authentication views for KasuMarketplace.
Location: apps/users/views.py
"""

import random
import string
from datetime import timedelta

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import login, logout, authenticate
from django.contrib.auth.decorators import login_required
from django.core.mail import send_mail
from django.shortcuts import render, redirect
from django.template.loader import render_to_string
from django.utils import timezone
from django.utils.html import strip_tags
from django.views import View
from django.views.decorators.http import require_http_methods
from django.contrib.auth.views import PasswordResetView
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from django.contrib.auth.tokens import default_token_generator
from django.contrib.auth.views import (
    PasswordResetView as DjangoPasswordResetView,
    PasswordResetDoneView as DjangoPasswordResetDoneView,
    PasswordResetConfirmView as DjangoPasswordResetConfirmView,
    PasswordResetCompleteView as DjangoPasswordResetCompleteView,
)
from django.urls import reverse_lazy
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode

from .forms import (
    BuyerSignupForm,
    VendorSignupForm,
    LoginForm,
    OTPVerificationForm,
    ResendOTPForm
)
from .forms import (
    PasswordResetRequestForm,
    PasswordResetConfirmForm,
)
from .models import CustomUser


# ===========================
# HELPER FUNCTIONS
# ===========================

def generate_otp(length=6):
    """
    Generate a random OTP code.
    
    Args:
        length (int): Length of OTP code (default: 6)
    
    Returns:
        str: Random numeric OTP code
    """
    return ''.join(random.choices(string.digits, k=length))


def send_otp_email(user, otp):
    """
    Send OTP verification email to user.
    
    Args:
        user (CustomUser): User instance
        otp (str): OTP code to send
    
    Returns:
        bool: True if email sent successfully, False otherwise
    """
    try:
        subject = 'Verify Your Email - KasuMarketplace'
        
        # Create HTML email content
        html_message = render_to_string('users/emails/otp_email.html', {
            'user': user,
            'otp': otp,
            'expiry_time': settings.OTP_EXPIRY_TIME,
        })
        
        # Create plain text version
        plain_message = strip_tags(html_message)
        
        # Send email
        send_mail(
            subject=subject,
            message=plain_message,
            from_email=settings.DEFAULT_FROM_EMAIL if hasattr(settings, 'DEFAULT_FROM_EMAIL') else 'noreply@kasumarketplace.com',
            recipient_list=[user.email],
            html_message=html_message,
            fail_silently=False,
        )
        
        return True
    
    except Exception as e:
        print(f"Error sending OTP email: {str(e)}")
        return False


def save_otp_to_user(user, otp):
    """
    Save OTP code to user model with timestamp.
    
    Args:
        user (CustomUser): User instance
        otp (str): OTP code to save
    """
    user.otp_code = otp
    user.last_login = timezone.now()  # Track when OTP was sent
    user.save(update_fields=['otp_code', 'last_login'])


def is_otp_valid(user, otp):
    """
    Check if OTP is valid and not expired.
    
    Args:
        user (CustomUser): User instance
        otp (str): OTP code to validate
    
    Returns:
        bool: True if OTP is valid, False otherwise
    """
    if not user.otp_code or user.otp_code != otp:
        return False
    
    # Check if OTP has expired
    otp_expiry = getattr(settings, 'OTP_EXPIRY_TIME', 10)  # Default 10 minutes
    expiry_time = user.last_login + timedelta(minutes=otp_expiry)
    
    if timezone.now() > expiry_time:
        return False
    
    return True


# ===========================
# AUTHENTICATION VIEWS
# ===========================

class BuyerSignupView(View):
    """Handle buyer registration."""
    
    template_name = 'users/signup_buyer.html'
    form_class = BuyerSignupForm
    
    def get(self, request):
        """Display buyer signup form."""
        if request.user.is_authenticated:
            return redirect('users:buyer_dashboard')
        
        form = self.form_class()
        return render(request, self.template_name, {'form': form})
    
    def post(self, request):
        """Process buyer signup form."""
        form = self.form_class(request.POST)
        
        if form.is_valid():
            # Save user
            user = form.save()
            
            # Generate and send OTP
            otp = generate_otp()
            save_otp_to_user(user, otp)
            
            if send_otp_email(user, otp):
                messages.success(
                    request,
                    'Registration successful! Please check your email for the verification code.'
                )
                # Store email in session for OTP verification
                request.session['verify_email'] = user.email
                return redirect('users:verify_otp')
            else:
                messages.error(
                    request,
                    'Registration successful, but we couldn\'t send the verification email. Please try resending.'
                )
                request.session['verify_email'] = user.email
                return redirect('users:verify_otp')
        
        return render(request, self.template_name, {'form': form})


class VendorSignupView(View):
    """Handle vendor registration."""
    
    template_name = 'users/signup_vendor.html'
    form_class = VendorSignupForm
    
    def get(self, request):
        """Display vendor signup form."""
        if request.user.is_authenticated:
            return redirect('users:vendor_dashboard')
        
        form = self.form_class()
        return render(request, self.template_name, {'form': form})
    
    def post(self, request):
        """Process vendor signup form."""
        form = self.form_class(request.POST)
        
        if form.is_valid():
            # Save user
            user = form.save()
            
            # Generate and send OTP
            otp = generate_otp()
            save_otp_to_user(user, otp)
            
            if send_otp_email(user, otp):
                messages.success(
                    request,
                    'Registration successful! Please check your business email for the verification code.'
                )
                # Store email in session for OTP verification
                request.session['verify_email'] = user.email
                return redirect('users:verify_otp')
            else:
                messages.error(
                    request,
                    'Registration successful, but we couldn\'t send the verification email. Please try resending.'
                )
                request.session['verify_email'] = user.email
                return redirect('users:verify_otp')
        
        return render(request, self.template_name, {'form': form})


class LoginView(View):
    """Handle user login."""
    
    template_name = 'users/login.html'
    form_class = LoginForm
    
    def get(self, request):
        """Display login form."""
        if request.user.is_authenticated:
            # Redirect based on user role
            if request.user.is_vendor:
                return redirect('users:vendor_dashboard')
            return redirect('users:buyer_dashboard')
        
        form = self.form_class()
        return render(request, self.template_name, {'form': form})
    
    def post(self, request):
        """Process login form."""
        form = self.form_class(request=request, data=request.POST)
        
        if form.is_valid():
            user = form.get_user()
            
            # Login user (explicit backend required when multiple auth backends are configured)
            login(request, user, backend='django.contrib.auth.backends.ModelBackend')
            
            # Handle "remember me" functionality
            if not form.cleaned_data.get('remember_me'):
                request.session.set_expiry(0)
            
            messages.success(request, f'Welcome back, {user.get_short_name()}!')
            
            # Redirect based on user role
            if user.is_vendor:
                return redirect('users:vendor_dashboard')
            elif user.is_buyer:
                return redirect('users:buyer_dashboard')
            else:
                return redirect('home')
        
        return render(request, self.template_name, {'form': form})


class OTPVerificationView(View):
    """Handle OTP verification."""
    
    template_name = 'users/verify_otp.html'
    form_class = OTPVerificationForm
    
    def get(self, request):
        """Display OTP verification form."""
        # Check if email is in session
        email = request.session.get('verify_email')
        if not email:
            messages.error(request, 'No verification pending. Please sign up first.')
            return redirect('users:login')
        
        form = self.form_class()
        return render(request, self.template_name, {
            'form': form,
            'email': email,
        })
    
    def post(self, request):
        """Process OTP verification."""
        email = request.session.get('verify_email')
        if not email:
            messages.error(request, 'Session expired. Please sign up again.')
            return redirect('users:buyer_signup')
        
        form = self.form_class(request.POST)
        
        if form.is_valid():
            otp = form.cleaned_data['otp_code']
            
            try:
                user = CustomUser.objects.get(email=email)
                
                # Validate OTP
                if is_otp_valid(user, otp):
                    # Mark user as verified
                    user.is_verified = True
                    user.otp_code = None  # Clear OTP
                    user.save(update_fields=['is_verified', 'otp_code'])
                    
                    # Clear session
                    if 'verify_email' in request.session:
                        del request.session['verify_email']
                    
                    # Log user in (explicit backend required when multiple auth backends are configured)
                    login(request, user, backend='django.contrib.auth.backends.ModelBackend')
                    
                    messages.success(
                        request,
                        'Email verified successfully! Welcome to KasuMarketplace.'
                    )
                    
                    # Redirect based on role
                    if user.is_vendor:
                        return redirect('users:vendor_dashboard')
                    return redirect('users:buyer_dashboard')
                else:
                    messages.error(
                        request,
                        'Invalid or expired verification code. Please try again or request a new code.'
                    )
            
            except CustomUser.DoesNotExist:
                messages.error(request, 'User not found. Please sign up again.')
                return redirect('users:buyer_signup')
        
        return render(request, self.template_name, {
            'form': form,
            'email': email,
        })


class ResendOTPView(View):
    """Handle OTP resend requests."""
    
    template_name = 'users/resend_otp.html'
    form_class = ResendOTPForm
    
    def get(self, request):
        """Display resend OTP form."""
        # Pre-fill email from session if available
        email = request.session.get('verify_email', '')
        form = self.form_class(initial={'email': email})
        return render(request, self.template_name, {'form': form})
    
    def post(self, request):
        """Process OTP resend request."""
        form = self.form_class(request.POST)
        
        if form.is_valid():
            email = form.cleaned_data['email']
            
            try:
                user = CustomUser.objects.get(email=email)
                
                # Generate and send new OTP
                otp = generate_otp()
                save_otp_to_user(user, otp)
                
                if send_otp_email(user, otp):
                    messages.success(
                        request,
                        'A new verification code has been sent to your email.'
                    )
                    # Store email in session
                    request.session['verify_email'] = email
                    return redirect('users:verify_otp')
                else:
                    messages.error(
                        request,
                        'Failed to send verification email. Please try again later.'
                    )
            
            except CustomUser.DoesNotExist:
                # Don't reveal if email exists for security
                messages.error(request, 'If this email is registered, a new code will be sent.')
        
        return render(request, self.template_name, {'form': form})


@require_http_methods(["GET", "POST"])
def logout_view(request):
    """Handle user logout."""
    if request.user.is_authenticated:
        user_name = request.user.get_short_name()
        logout(request)
        messages.success(request, f'Goodbye, {user_name}! You have been logged out successfully.')
    
    return redirect('home')


# ===========================
# DASHBOARD VIEWS (PLACEHOLDER)
# ===========================

@login_required
def buyer_dashboard(request):
    """Buyer dashboard view."""
    if not request.user.is_buyer:
        messages.error(request, 'Access denied. Buyers only.')
        return redirect('home')
    
    return render(request, 'users/buyer_dashboard.html', {
        'user': request.user,
    })


@login_required
def vendor_dashboard(request):
    """Vendor dashboard view."""
    if not request.user.is_vendor:
        messages.error(request, 'Access denied. Vendors only.')
        return redirect('home')
    
    return render(request, 'users/vendor_dashboard.html', {
        'user': request.user,
    })


# ===========================
# HOME VIEW (PLACEHOLDER)
# ===========================

def home(request):
    """Homepage view."""
    return render(request, 'home.html')


# ============================================
# FILE 2: apps/users/views.py (ADD THESE VIEWS)
# ============================================
"""
Add these password reset views to your existing views.py
"""
class PasswordResetRequestView(DjangoPasswordResetView):
    """
    View for requesting password reset.
    Sends email with reset link.
    """
    template_name = 'users/password_reset_request.html'
    email_template_name = 'users/emails/password_reset_email.html'
    subject_template_name = 'users/emails/password_reset_subject.txt'
    form_class = PasswordResetRequestForm
    success_url = reverse_lazy('users:password_reset_done')
    
    def form_valid(self, form):
        """Send password reset email as multipart (plain + html)."""
        email = form.cleaned_data.get('email')
        users = list(form.get_users(email))
        protocol = 'https' if self.request.is_secure() else 'http'
        domain = self.request.get_host()

        # If no matching users, do not reveal that — still show success page.
        if not users:
            messages.success(
                self.request,
                'If an account exists with that email, you will receive password reset instructions.'
            )
            return redirect(self.success_url)

        for user in users:
            uid = urlsafe_base64_encode(force_bytes(user.pk))
            token = default_token_generator.make_token(user)
            context = {
                'email': user.email,
                'domain': domain,
                'site_name': getattr(settings, 'SITE_NAME', 'KasuMarketplace'),
                'uid': uid,
                'user': user,
                'token': token,
                'protocol': protocol,
            }

            # Render subject, HTML and plain text bodies
            subject = render_to_string(self.subject_template_name, context).strip()
            html_message = render_to_string(self.email_template_name, context)
            plain_message = strip_tags(html_message)

            from_email = getattr(settings, 'DEFAULT_FROM_EMAIL', None)
            msg = EmailMultiAlternatives(subject, plain_message, from_email, [user.email])
            msg.attach_alternative(html_message, "text/html")
            msg.send(fail_silently=False)

        messages.success(
            self.request,
            'If an account exists with that email, you will receive password reset instructions.'
        )
        return redirect(self.success_url)


class PasswordResetDoneView(DjangoPasswordResetDoneView):
    """
    View shown after password reset email is sent.
    """
    template_name = 'users/password_reset_done.html'


class PasswordResetConfirmView(DjangoPasswordResetConfirmView):
    """
    View for setting new password using reset link.
    """
    template_name = 'users/password_reset_confirm.html'
    form_class = PasswordResetConfirmForm
    success_url = reverse_lazy('users:password_reset_complete')
    
    def form_valid(self, form):
        """Reset password and show success message."""
        response = super().form_valid(form)
        messages.success(
            self.request,
            'Your password has been reset successfully! You can now log in with your new password.'
        )
        return response


class PasswordResetCompleteView(DjangoPasswordResetCompleteView):
    """
    View shown after password has been reset successfully.
    """
    template_name = 'users/password_reset_complete.html'

class CustomPasswordResetView(PasswordResetView):
    def send_mail(self, subject_template_name, email_template_name,
                  context, from_email, to_email, html_email_template_name=None):
        subject = render_to_string(subject_template_name, context).strip()
        html_content = render_to_string(email_template_name, context)
        text_content = "Please open this email in HTML view to reset your password."

        msg = EmailMultiAlternatives(subject, text_content, from_email, [to_email])
        msg.attach_alternative(html_content, "text/html")
        msg.send()