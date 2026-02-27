"""
Vendor App Views
All views for vendor dashboard, verification, products, orders, wallet, etc.
"""

from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_http_methods
from django.http import JsonResponse, HttpResponse
from django.http import Http404
from django.db.models import Sum, Count, Q
from django.utils import timezone
from django.db.models import F
from django.core.paginator import Paginator
from django.urls import reverse
from decimal import Decimal
from datetime import datetime, date
import logging

from .models import (
    VendorProfile, Store, Product, ProductImage, 
    Order, OrderItem, Wallet, Transaction,
    MainCategory, SubCategory, SubCategoryAttribute, CategoryChangeRequest,
    Notification
)
from .forms import (
    NINEntryForm, NINOTPForm, BVNEntryForm, BVNOTPForm,
    StudentVerificationForm, StoreSetupForm, StoreSettingsForm,
    ProductForm, ProductImageFormSet, OrderStatusUpdateForm, 
    CategoryChangeRequestForm
)
from .decorators import (
    vendor_required, vendor_verified_required, 
    vendor_owns_product, vendor_owns_order,
    rate_limit_verification
)
from .services import dojah_service, paystack_service, notification_service
from .services.utils import generate_reference, calculate_commission



logger = logging.getLogger(__name__)


# ==========================================
# PROFILE
# ==========================================

@vendor_required
def profile_view(request):
    """
    View vendor profile (read-only display)
    Shows auto-filled NIN/BVN data with masked sensitive info
    """
    vendor = request.user.vendorprofile
    
    context = {
        'vendor': vendor,
        'hide_verification_badge': True,
    }
    
    return render(request, 'vendors/profile/view.html', context)


# ==========================================
# DASHBOARD
# ==========================================

@vendor_required
def dashboard(request):
    """
    Main vendor dashboard with stats and overview
    """
    vendor = request.user.vendorprofile
    
    # Get stats
    context = {
        'vendor': vendor,
        'total_products': vendor.products.filter(status='published').count(),
        'pending_orders': vendor.orders.filter(status__in=['pending', 'confirmed']).count(),
        'total_sales': vendor.store.total_sales if hasattr(vendor, 'store') else 0,
        'wallet_balance': vendor.wallet.balance if hasattr(vendor, 'wallet') else 0,
        
        # Recent orders
        'recent_orders': vendor.orders.all()[:5],
        
        # Low stock products
        'low_stock_products': vendor.products.filter(
            status='published',
            track_inventory=True,
            stock_quantity__lte=5
        )[:5],
        
        # Unread notifications
        'unread_notifications': vendor.notifications.filter(is_read=False).count(),
    }
    
    # Show verification banner if not verified
    if not vendor.can_sell:
        messages.info(
            request,
            f'Complete verification to start selling. Progress: {vendor.completion_percentage}%'
        )
    
    context['hide_verification_badge'] = True
    return render(request, 'vendors/dashboard.html', context)


# ==========================================
# VERIFICATION VIEWS
# ==========================================

@vendor_required
def verification_center(request):
    """
    Verification center - shows progress and next steps
    """
    vendor = request.user.vendorprofile
    
    # If already approved, redirect to dashboard
    if vendor.is_verified:
        messages.success(request, "You're already verified!")
        return redirect('vendors:dashboard')
    
    # Map raw status to badge status and label (for NIN/BVN)
    def _nin_badge(s):
        if s == 'nin_verified':
            return 'completed', 'Verified'
        if s in ('nin_otp_sent', 'nin_entered'):
            return 'in_progress', 'OTP Sent' if s == 'nin_otp_sent' else 'In Progress'
        if s == 'failed':
            return 'failed', 'Failed'
        return 'not_started', 'Not Started'

    def _bvn_badge(s):
        if s == 'bvn_verified':
            return 'completed', 'Verified'
        if s in ('bvn_otp_sent', 'bvn_entered'):
            return 'in_progress', 'OTP Sent' if s == 'bvn_otp_sent' else 'In Progress'
        if s == 'failed':
            return 'failed', 'Failed'
        return 'not_started', 'Not Started'

    # Calculate step status
    nin_badge_status, nin_status_label = _nin_badge(vendor.identity_status)
    bvn_badge_status, bvn_status_label = _bvn_badge(vendor.bank_status)

    steps = [
    {
        'number': 1,
        'name': 'Verify Your Identity (nin)',
        'title': 'Verify Your Identity (nin)',
        'status': nin_badge_status,
        'status_label': nin_status_label,
        'completed': vendor.identity_status == 'nin_verified',
        'url': 'vendors:nin_entry',
        'verification_type': 'nin',
        'icon': '''<svg class="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                     <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M16 7a4 4 0 11-8 0 4 4 0 018 0zM12 14a7 7 0 00-7 7h14a7 7 0 00-7-7z"/>
                   </svg>'''
    },
    {
        'number': 2,
        'name': 'Verify Your Banking (bvn)',
        'title': 'Verify Your Banking (bvn)',
        'status': bvn_badge_status,
        'status_label': bvn_status_label,
        'completed': vendor.bank_status == 'bvn_verified',
        'url': 'vendors:bvn_entry',
        'verification_type': 'bvn',
        'icon': '''<svg class="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                     <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M3 10h18M7 15h1m4 0h1m-7 4h12a3 3 0 003-3V8a3 3 0 00-3-3H6a3 3 0 00-3 3v8a3 3 0 003 3z"/>
                   </svg>'''
    },
    {
        'number': 3,
        'name': 'Set Up Your Store',
        'title': 'Set Up Your Store',
        'status': 'completed' if vendor.store_setup_completed else 'pending',
        'status_label': 'Completed' if vendor.store_setup_completed else 'Pending',
        'completed': vendor.store_setup_completed,
        'url': 'vendors:store_setup',
        'icon': '''<svg class="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                     <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 21V5a2 2 0 00-2-2H7a2 2 0 00-2 2v16m14 0h2m-2 0h-5m-9 0H3m2 0h5M9 7h1m-1 4h1m4-4h1m-1 4h1m-5 10v-5a1 1 0 011-1h2a1 1 0 011 1v5m-4 0h4"/>
                   </svg>'''
    },
    {
        'number': 4,
        'name': 'Verify Student Status (optional)',
        'title': 'Verify Student Status (optional)',
        'status': ('completed' if vendor.student_status == 'verified' else
                  'pending' if vendor.student_status == 'pending' else
                  'not_started'),
        'status_label': ('Verified' if vendor.student_status == 'verified' else
                        'Pending' if vendor.student_status == 'pending' else
                        'Not Started'),
        'completed': vendor.student_status == 'verified',
        'url': 'vendors:student_verification',
        'icon': '''<svg class="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                     <path d="M12 14l9-5-9-5-9 5 9 5z"/>
                     <path d="M12 14l6.16-3.422a12.083 12.083 0 01.665 6.479A11.952 11.952 0 0012 20.055a11.952 11.952 0 00-6.824-2.998 12.078 12.078 0 01.665-6.479L12 14z"/>
                     <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 14l9-5-9-5-9 5 9 5zm0 0l6.16-3.422a12.083 12.083 0 01.665 6.479A11.952 11.952 0 0012 20.055a11.952 11.952 0 00-6.824-2.998 12.078 12.078 0 01.665-6.479L12 14zm-4 6v-7.5l4-2.222"/>
                   </svg>'''
    },
    {
        'number': 5,
        'name': 'Pending Admin Review',
        'title': 'Pending Admin Review',
        'status': ('completed' if vendor.verification_status == 'approved' else
                  'failed' if vendor.verification_status == 'rejected' else
                  'pending'),
        'status_label': ('Approved' if vendor.verification_status == 'approved' else
                        'Rejected' if vendor.verification_status == 'rejected' else
                        'Pending'),
        'completed': vendor.verification_status == 'approved',
        'url': 'vendors:pending_review',
        'icon': '''<svg class="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                     <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 12l2 2 4-4m5.618-4.016A11.955 11.955 0 0112 2.944a11.955 11.955 0 01-8.618 3.04A12.02 12.02 0 003 9c0 5.591 3.824 10.29 9 11.622 5.176-1.332 9-6.03 9-11.622 0-1.042-.133-2.052-.382-3.016z"/>
                   </svg>'''
    }
]
    
    context = {
        'vendor': vendor,
        'steps': steps,
        'completion_percentage': vendor.completion_percentage,
        'current_step': vendor.current_step,
        'can_sell': vendor.can_sell,
        'hide_verification_badge': True,
    }
    
    return render(request, 'vendors/verification/center.html', context)


@vendor_required
@rate_limit_verification
def nin_entry(request):
    """Step 1: NIN Entry with security checks"""
    vendor = request.user.vendorprofile
    
    if vendor.identity_status == 'nin_verified':
        messages.info(request, 'NIN already verified')
        return redirect('vendors:verification_center')
    
    if request.method == 'POST':
        form = NINEntryForm(request.POST)
        
        if form.is_valid():
            nin_number = form.cleaned_data['nin_number']
            
            # ✅ CHECK FOR DUPLICATE NIN BEFORE API CALL
            duplicate_vendor = VendorProfile.objects.filter(
                nin_number=nin_number
            ).exclude(id=vendor.id).first()
            
            if duplicate_vendor:
                vendor.has_duplicate_nin = True
                vendor.duplicate_nin_vendor_id = str(duplicate_vendor.vendor_id)
                vendor.save()
                logger.warning(f"⚠️ Duplicate NIN detected: {nin_number} (Vendor: {duplicate_vendor.vendor_id})")
                messages.error(
                    request,
                    "⚠️ This NIN is already registered. If this is your NIN, please contact support."
                )
                return render(request, 'vendors/verification/nin_entry.html', {'form': form})
            
            # Call Dojah API
            success, data = dojah_service.verify_nin(nin_number)
            
            if success:
                # Store NIN data
                vendor.nin_number = nin_number

                first = data.get('firstname', '') or data.get('first_name', '') or ''
                middle = data.get('middlename', '') or data.get('middle_name', '') or ''
                last = data.get('surname', '') or data.get('lastname', '') or data.get('last_name', '') or ''
                vendor.full_name = " ".join([p for p in [first, middle, last] if p]).strip()
                
                # ✅ Extract phone (advanced endpoint uses phone_number)
                phone_from_dojah = (
                    data.get('phone_number') 
                    or data.get('phone', '') 
                    or data.get('telephoneno', '')
                )
                if phone_from_dojah:
                    vendor.phone = phone_from_dojah
                
                # ✅ HANDLE DOB WITH AGE CHECK (advanced endpoint uses date_of_birth)
                birthdate = (
                    data.get('date_of_birth')
                    or data.get('birthdate') 
                    or data.get('dateofbirth')
                )
                if birthdate and birthdate.strip():
                    try:
                        parsed_date = datetime.strptime(birthdate, '%Y-%m-%d')
                        vendor.dob = parsed_date.date()
                        
                        # Calculate age
                        today = date.today()
                        age = today.year - vendor.dob.year - (
                            (today.month, today.day) < (vendor.dob.month, vendor.dob.day)
                        )
                        vendor.calculated_age = age
                        
                        # Check if underage
                        if age < 18:
                            vendor.is_underage = True
                            logger.warning(f"⚠️ Underage vendor detected: {age} years old")
                        
                    except (ValueError, AttributeError) as e:
                        logger.warning(f"Invalid birthdate format from Dojah: {birthdate}")
                        vendor.dob = None
                else:
                    vendor.dob = None
                
                vendor.gender = (data.get('gender', '') or '').lower()
                
                # ✅ Extract address (now includes combined address_line_1 + address_line_2 from advanced endpoint)
                vendor.address = (
                    data.get('residence_address') 
                    or data.get('address') 
                    or ''
                ).strip()
                
                # ✅ Extract state (from advanced endpoint)
                vendor.state = (
                    data.get('residence_state') 
                    or data.get('state') 
                    or ''
                ).strip()
                
                # ✅ Extract LGA (from advanced endpoint)
                vendor.lga = (
                    data.get('residence_lga') 
                    or data.get('lga') 
                    or ''
                ).strip()
                
                # Log for debugging
                if vendor.address or vendor.state or vendor.lga:
                    logger.info(f'✅ Address data extracted - Address: {vendor.address[:50] if vendor.address else "N/A"} | State: {vendor.state} | LGA: {vendor.lga}')
                
                # ✅ CAPTURE IP ADDRESS
                vendor.nin_verification_ip = request.META.get('REMOTE_ADDR')
                
                vendor.identity_status = 'nin_otp_sent'
                vendor.save()
                
                # Calculate initial risk score
                vendor.calculate_risk_score()
                vendor.save()
                
                # Send OTP
                otp_success, otp_data = dojah_service.send_nin_otp(nin_number)
                
                if otp_success:
                    messages.success(request, f"OTP sent to {otp_data.get('phone', 'your phone')}! ✅")
                    return redirect('vendors:nin_otp')
                else:
                    messages.warning(request, 'Could not send OTP. Please contact support.')
                    vendor.identity_status = 'nin_verified'
                    vendor.nin_verified_at = timezone.now()
                    vendor.save()
                    return redirect('vendors:bvn_entry')
            else:
                messages.error(request, f"NIN verification failed: {data.get('error')}")
    else:
        form = NINEntryForm()
    
    return render(request, 'vendors/verification/nin_entry.html', {
        'form': form,
        'hide_verification_badge': True
    })


    
@vendor_required
@rate_limit_verification
def bvn_entry(request):
    """Step 2: BVN Entry with name matching"""
    vendor = request.user.vendorprofile
    
    if vendor.identity_status != 'nin_verified':
        messages.warning(request, 'Please verify NIN first')
        return redirect('vendors:nin_entry')
    
    if vendor.bank_status == 'bvn_verified':
        messages.info(request, 'BVN already verified')
        return redirect('vendors:verification_center')
    
    if request.method == 'POST':
        form = BVNEntryForm(request.POST)
        
        if form.is_valid():
            bvn_number = form.cleaned_data['bvn_number']
            bank_name = form.cleaned_data['bank_name']
            
            # ✅ CHECK FOR DUPLICATE BVN
            duplicate_vendor = VendorProfile.objects.filter(
                bvn_number=bvn_number
            ).exclude(id=vendor.id).first()
            
            if duplicate_vendor:
                vendor.has_duplicate_bvn = True
                vendor.duplicate_bvn_vendor_id = str(duplicate_vendor.vendor_id)
                vendor.save()
                logger.warning(f"⚠️ Duplicate BVN detected: {bvn_number}")
                messages.error(
                    request,
                    "⚠️ This BVN is already registered. If this is your BVN, please contact support."
                )
                return render(request, 'vendors/verification/bvn_entry.html', {
                    'form': form,
                    'vendor': vendor
                })
            
            # Call Dojah API
            success, data = dojah_service.verify_bvn(bvn_number)
            
            if success:
                # Extract BVN name
                bvn_first = data.get('firstname', data.get('first_name', ''))
                bvn_last = data.get('lastname', data.get('last_name', data.get('surname', '')))
                bvn_full_name = f"{bvn_first} {bvn_last}".strip()
                
                vendor.bvn_full_name = bvn_full_name
                
                # ✅ CHECK NAME MATCH
                matches, similarity, details = vendor.check_name_match(bvn_full_name)
                
                if not matches:
                    vendor.has_name_mismatch = True
                    vendor.name_mismatch_details = details
                    logger.warning(f"⚠️ {details}")
                else:
                    vendor.has_name_mismatch = False
                    vendor.name_mismatch_details = ""
                
                # Update vendor
                vendor.bvn_number = bvn_number
                vendor.bank_status = 'bvn_verified'
                vendor.bvn_verified_at = timezone.now()
                
                # ✅ CAPTURE IP ADDRESS
                vendor.bvn_verification_ip = request.META.get('REMOTE_ADDR')
                
                vendor.save()
                
                # Update wallet
                wallet = vendor.wallet
                
                # ✅ Extract account holder name from BVN (auto-fill, read-only)
                # Try account_name first, then construct from firstname+lastname, fallback to vendor full_name
                account_name = (
                    data.get('account_name', '') 
                    or bvn_full_name  # Use the BVN full name we extracted
                    or vendor.full_name  # Fallback to NIN name
                )
                wallet.account_holder_name = account_name.strip()
                
                # Bank name and account number can be changed by user
                wallet.bank_name = bank_name
                wallet.account_number = data.get('account_number', '')
                wallet.is_verified = True
                wallet.verified_at = timezone.now()
                wallet.save()
                
                logger.info(f'✅ Wallet updated - Account Holder: {wallet.account_holder_name} | Bank: {wallet.bank_name} | Account: {wallet.account_number}')
                
                # Calculate risk score
                vendor.calculate_risk_score()
                vendor.save()
                
                # Send notification
                notification_service.send_bvn_verified(vendor)
                
                messages.success(request, 'BVN verified successfully! ✅')
                return redirect('vendors:store_setup')
            else:
                messages.error(request, f"BVN verification failed: {data.get('error')}")
    else:
        form = BVNEntryForm()
    
    return render(request, 'vendors/verification/bvn_entry.html', {
        'form': form,
        'vendor': vendor,
        'hide_verification_badge': True
    })


@vendor_required
def store_setup(request):
    """
    Step 3: Store Setup (can be skipped)
    """
    vendor = request.user.vendorprofile
    
    # Check prerequisites - must have NIN and BVN verified
    if vendor.identity_status != 'nin_verified' or vendor.bank_status != 'bvn_verified':
        messages.warning(request, 'Please complete NIN and BVN verification first')
        return redirect('vendors:verification_center')
    
    # Get or create store
    try:
        store = vendor.store
        is_new = False
    except Store.DoesNotExist:
        store = None
        is_new = True
    
    if request.method == 'POST':
        # Check for skip action
        if 'skip' in request.POST:
            vendor.store_setup_skipped = True
            vendor.save()
            messages.info(request, 'Store setup skipped. You can complete it later.')
            return redirect('vendors:verification_center')
        
        form = StoreSetupForm(request.POST, request.FILES, instance=store, vendor=vendor)
        
        if form.is_valid():
            store = form.save()
            vendor.store_setup_completed = True
            vendor.save()
            
            messages.success(request, 'Store setup complete! ✅')
            return redirect('vendors:verification_center')
    else:
        form = StoreSetupForm(instance=store, vendor=vendor)
    
    # ✅ FIX: Pass categories and vendor to template
    context = {
        'form': form,
        'vendor': vendor,
        'graduation_years': range(2024, 2031),
        'is_new': is_new,
        'categories': MainCategory.objects.filter(is_active=True).order_by('sort_order'),
        'store': store,  # In case we're editing
        'hide_verification_badge': True,
    }
    
    return render(request, 'vendors/verification/store_setup.html', context)
    

@vendor_required
def student_verification(request):
    """
    Step 4: Student & Alumni Verification (Optional)
    Exclusive for Kaduna State University (KASU) community
    """
    vendor = request.user.vendorprofile
    current_year = datetime.now().year
    
    if request.method == 'POST':
        form = StudentVerificationForm(request.POST, request.FILES, instance=vendor)
        
        if form.is_valid():
            vendor = form.save(commit=False)
            
            # ✅ Force KASU as institution (hardcoded)
            vendor.institution = "Kaduna State University (KASU)"
            
            # Set status to pending for admin review
            vendor.student_status = 'pending'
            
            vendor.save()
            
            messages.success(
                request, 
                '✅ Student/Alumni verification submitted! We\'ll review your documents within 24-48 hours and notify you via email.'
            )
            return redirect('vendors:verification_center')
        else:
            messages.error(request, '❌ Please correct the errors below.')
    else:
        form = StudentVerificationForm(instance=vendor)
    
    context = {
        'form': form,
        'vendor': vendor,
        'graduation_years': range(current_year - 5, current_year + 8),  # ✅ 2021-2033 (5 years alumni + 7 years future)
        'hide_verification_badge': True,
    }
    
    return render(request, 'vendors/verification/student_verification.html', context)

@vendor_required
@rate_limit_verification
def nin_otp(request):
    """
    Step 1b: NIN OTP Verification
    (Currently skipped in mock mode, but needed for production)
    """
    vendor = request.user.vendorprofile
    
    # Check if NIN entered first
    if vendor.identity_status != 'nin_otp_sent':
        messages.warning(request, 'Please enter NIN first')
        return redirect('vendors:nin_entry')
    
    if request.method == 'POST':
        form = NINOTPForm(request.POST)
        
        if form.is_valid():
            otp_code = form.cleaned_data['otp_code']
            
            # Verify OTP via Dojah
            nin_number = vendor.nin_number
            success, data = dojah_service.verify_nin_otp(nin_number, otp_code)
            
            if success:
                vendor.identity_status = 'nin_verified'
                vendor.nin_verified_at = timezone.now()
                
                # ✅ CHECK FOR DUPLICATE NIN
                duplicate_nin = VendorProfile.objects.filter(
                    nin_number=vendor.nin_number
                ).exclude(id=vendor.id).exists()
                
                if duplicate_nin:
                    vendor.has_duplicate_nin = True
                    logger.warning(f"⚠️ Duplicate NIN detected: {vendor.nin_number}")
                    # Don't block, but flag for admin review
                
                # ✅ CHECK AGE (must be 18+)
                if vendor.dob:
                    today = date.today()
                    age = today.year - vendor.dob.year - (
                        (today.month, today.day) < (vendor.dob.month, vendor.dob.day)
                    )
                    
                    if age < 18:
                        vendor.is_underage = True
                        logger.warning(f"⚠️ Underage vendor detected: {age} years old")
                        # Flag for admin review
                
                # ✅ CAPTURE IP ADDRESS
                vendor.nin_verification_ip = request.META.get('REMOTE_ADDR')
                
                vendor.save()
                
                messages.success(request, 'NIN verified successfully!')
                return redirect('vendors:nin_success')
            else:
                messages.error(request, 'Invalid OTP. Please try again.')
    else:
        form = NINOTPForm()
    
    # Resend OTP option
    context = {
        'form': form,
        'vendor': vendor,
        'phone_last_4': vendor.phone[-4:] if vendor.phone else '****',
        'hide_verification_badge': True,
    }
    
    return render(request, 'vendors/verification/nin_otp.html', context)


@vendor_required
def nin_success(request):
    """
    Step 1c: NIN Success Page
    """
    vendor = request.user.vendorprofile
    
    if vendor.identity_status != 'nin_verified':
        return redirect('vendors:nin_entry')
    
    return render(request, 'vendors/verification/nin_success.html', {'vendor': vendor, 'hide_verification_badge': True})


@vendor_required
@rate_limit_verification
def bvn_otp(request):
    """
    Step 2b: BVN OTP Verification
    """
    vendor = request.user.vendorprofile
    
    if vendor.bank_status != 'bvn_otp_sent':
        messages.warning(request, 'Please enter BVN first')
        return redirect('vendors:bvn_entry')
    
    if request.method == 'POST':
        form = BVNOTPForm(request.POST)
        
        if form.is_valid():
            otp_code = form.cleaned_data['otp_code']
            
            # Verify OTP
            bvn_number = vendor.bvn_number
            success, data = dojah_service.verify_bvn_otp(bvn_number, otp_code)
            
            if success:
                vendor.bank_status = 'bvn_verified'
                vendor.bvn_verified_at = timezone.now()
                vendor.save()
                
                # Update wallet
                wallet = vendor.wallet
                wallet.is_verified = True
                wallet.verified_at = timezone.now()
                wallet.save()
                
                messages.success(request, 'BVN verified successfully!')
                return redirect('vendors:bvn_success')
            else:
                messages.error(request, 'Invalid OTP. Please try again.')
    else:
        form = BVNOTPForm()
    
    context = {
        'form': form,
        'vendor': vendor,
        'phone_last_4': vendor.phone[-4:] if vendor.phone else '****',
        'hide_verification_badge': True,
    }
    
    return render(request, 'vendors/verification/bvn_otp.html', context)


@vendor_required
def bvn_success(request):
    """
    Step 2c: BVN Success Page
    """
    vendor = request.user.vendorprofile
    
    if vendor.bank_status != 'bvn_verified':
        return redirect('vendors:bvn_entry')
    
    return render(request, 'vendors/verification/bvn_success.html', {'vendor': vendor, 'hide_verification_badge': True})

@vendor_required
def pending_review(request):
    """
    Step 5: Waiting for Admin Review
    Shows after all verification steps complete
    """
    vendor = request.user.vendorprofile
    
    # Check if vendor completed all steps
    if not vendor.can_sell:
        messages.warning(request, 'Please complete verification steps first')
        return redirect('vendors:verification_center')
    
    # If already approved
    if vendor.verification_status == 'approved':
        messages.success(request, "You're already verified!")
        return redirect('vendors:dashboard')
    
    context = {
        'vendor': vendor,
        'submitted_at': vendor.bvn_verified_at or vendor.nin_verified_at,
        'estimated_review_time': '24-48 hours',
        'hide_verification_badge': True,
    }
    
    return render(request, 'vendors/verification/pending_review.html', context)


# ==========================================
# PRODUCT VIEWS
# ==========================================

@vendor_verified_required
def products_list(request):
    """List all vendor products with filters and stock status"""
    vendor = request.user.vendorprofile
    
    # Filters
    status = request.GET.get('status', '')
    stock_filter = request.GET.get('stock', '')
    search = request.GET.get('search', '')

    products = vendor.products.all()
    
    # Apply filters
    if status:
        products = products.filter(status=status)
    
    # ✅ NEW: Stock filter
    if stock_filter == 'low_stock':
        products = products.filter(
            track_inventory=True,
            stock_quantity__gt=0,
            stock_quantity__lte=F('low_stock_threshold')
        )
    elif stock_filter == 'out_of_stock':
        products = products.filter(track_inventory=True, stock_quantity=0)
    
    if search:
        products = products.filter(
            Q(title__icontains=search) | 
            Q(description__icontains=search) |
            Q(sku__icontains=search)
        )

    products = products.order_by('-created_at')
    
    # Pagination
    paginator = Paginator(products, 20)
    page_obj = paginator.get_page(request.GET.get('page'))
    
    # ✅ STATS
    context = {
        'products': page_obj,
        'total_products': vendor.products.count(),
        'published_count': vendor.products.filter(status='published').count(),
        'draft_count': vendor.products.filter(status='draft').count(),
        'low_stock_count': vendor.products.filter(
            track_inventory=True,
            stock_quantity__gt=0,
            stock_quantity__lte=F('low_stock_threshold')
        ).count(),
        'out_of_stock_count': vendor.products.filter(
            track_inventory=True, 
            stock_quantity=0
        ).count(),
        'current_status': status,
        'stock_filter': stock_filter,
        'search_query': search,
        'hide_verification_badge': True,
    }
    
    return render(request, 'vendors/products/list.html', context)


@vendor_verified_required
def product_create(request):
    """Create new product with dynamic attributes and images"""
    vendor = request.user.vendorprofile

    if not hasattr(vendor, 'store'):
        messages.warning(request, 'Please complete store setup first')
        return redirect('vendors:store_setup')
    
    if request.method == 'POST':
        subcategory_id = request.POST.get('subcategory')
        form = ProductForm(
            request.POST,
            vendor=vendor,
            subcategory_id=subcategory_id,
            is_editing=False  # ✅ Explicitly mark as creation
        )
        # Provide a temporary Product instance so the inline formset can bind correctly
        temp_product = Product()
        formset = ProductImageFormSet(request.POST, request.FILES, instance=temp_product)
        
        # ✅ SERVER-SIDE VALIDATION: Block discontinued on create
        if 'status' in request.POST and request.POST['status'] == 'discontinued':
            messages.error(request, '❌ You cannot set a new product as discontinued.')
            form.add_error('status', 'Products can only be discontinued after creation.')
        
        if form.is_valid() and formset.is_valid():
            try:
                product = form.save()
                
                # Save images
                formset.instance = product
                formset.save()
                
                # ✅ CHECK: Ensure at least one primary image
                if not product.images.filter(is_primary=True).exists():
                    first_image = product.images.first()
                    if first_image:
                        first_image.is_primary = True
                        first_image.save()
                
                messages.success(request, f'✅ Product "{product.title}" created successfully!')
                return redirect('vendors:product_detail', slug=product.slug)
                
            except Exception as e:
                messages.error(request, f'❌ Error: {str(e)}')
                import traceback
                print(traceback.format_exc())
        else:
            messages.error(request, '❌ Please correct the errors below.')
    else:
        form = ProductForm(vendor=vendor, is_editing=False)  # ✅ Mark as creation
        formset = ProductImageFormSet(instance=Product())
    
    # Get subcategories
    subcategories = SubCategory.objects.filter(
        main_category=vendor.store.main_category,
        is_active=True
    ).order_by('name')
    
    context = {
        'form': form,
        'formset': formset,
        'vendor': vendor,
        'subcategories': subcategories,
        'hide_verification_badge': True,
    }
    
    return render(request, 'vendors/products/create.html', context)


@vendor_verified_required
@vendor_owns_product
def product_edit(request, slug):
    """Edit existing product"""
    product = request.product
    vendor = request.user.vendorprofile

    
    if request.method == 'POST':
        form = ProductForm(
            request.POST,
            request.FILES,
            instance=product,
            vendor=vendor,
            is_editing=True
        )
        formset = ProductImageFormSet(request.POST, request.FILES, instance=product)
        
        if form.is_valid() and formset.is_valid():
            product = form.save()
            formset.save()
            
            messages.success(request, '✅ Product updated successfully!')
            return redirect('vendors:product_detail', slug=product.slug)
        else:
            # ✅ DEBUG: Print errors to console
            print("=" * 50)
            print("FORM ERRORS:", form.errors)
            print("FORM NON-FIELD ERRORS:", form.non_field_errors())
            print("FORMSET ERRORS:", formset.errors)
            print("FORMSET NON-FORM ERRORS:", formset.non_form_errors())
            print("=" * 50)
            
            messages.error(request, '❌ Please correct the errors below.')
    else:
        form = ProductForm(
            instance=product,
            vendor=vendor,
            is_editing=True
        )
        formset = ProductImageFormSet(instance=product)

    # Get subcategories for editing
    import json
    subcategories = SubCategory.objects.filter(
        main_category=vendor.store.main_category,
        is_active=True
    ).values('id', 'name').order_by('name')
    
    # Get current attributes for the product
    current_attributes = SubCategoryAttribute.objects.filter(
        subcategory=product.subcategory,
        is_active=True
    ).order_by('sort_order')

    # Build attributes JSON with current values
    attributes_json = json.dumps([
        {
            "id": attr.id,
            "name": attr.name,
            "field_type": attr.field_type,
            "options": attr.options if isinstance(attr.options, list) else [],
            "is_required": attr.is_required,
            "placeholder": attr.placeholder,
            "help_text": attr.help_text,
            "current_value": product.attributes.get(str(attr.id)) if product.attributes else ""
        }
        for attr in current_attributes
    ])
    
    context = {
        'form': form,
        'formset': formset,
        'product': product,
        'vendor': vendor,
        'is_editing': True,
        'subcategories': list(subcategories),
        'subcategories_json': json.dumps(list(subcategories)),
        'attributes_json': attributes_json,
        'hide_verification_badge': True,
    }
    
    return render(request, 'vendors/products/edit.html', context)


@vendor_verified_required
@vendor_owns_product
def product_delete(request, slug):
    """Delete product"""
    product = request.product
    
    if request.method == 'POST':
        title = product.title
        product.delete()
        
        messages.success(request, f'🗑️ Product "{title}" deleted successfully')
        return redirect('vendors:products_list')
    
    context = {
        'product': product,
        'hide_verification_badge': True,
    }
    
    return render(request, 'vendors/products/delete_confirm.html', context)


@vendor_verified_required
@vendor_owns_product
def product_detail(request, slug):
    """View product details"""
    product = request.product  # Set by decorator
    vendor = request.user.vendorprofile
    
    # Get product stats
    context = {
        'product': product,
        'vendor': vendor,
        'total_orders': OrderItem.objects.filter(product=product).count(),
        'total_revenue': OrderItem.objects.filter(
            product=product,
            order__status='delivered'
        ).aggregate(total=Sum('total'))['total'] or 0,
        'hide_verification_badge': True,
    }
    
    return render(request, 'vendors/products/detail.html', context)

# ==========================================
# PUBLIC BUYER PRODUCT DETAIL
# ==========================================

def product_detail_public(request, store_slug, product_slug):
    """
    Public-facing product detail page for buyers
    
    URL: /shop/<store_slug>/products/<product_slug>/
    
    Shows:
    - Product info (name, price, images, description)
    - Dynamic specifications from attributes
    - Simple stock status (In Stock / Out of Stock)
    - Store info and link
    - Units sold (social proof)
    - Add to cart / Contact seller actions
    
    Does NOT show:
    - Inventory internals
    - Revenue/analytics
    - Product ID/SKU/slug
    - Vendor dashboard controls
    """
    # Get store (allow owner to view even if not published)
    try:
        store = Store.objects.get(slug=store_slug)
    except Store.DoesNotExist:
        raise Http404("No Store matches the given query.")

    # Check if current user is the store owner
    is_owner = (
        request.user.is_authenticated and 
        hasattr(request.user, 'vendorprofile') and 
        request.user.vendorprofile == store.vendor
    )

    # If store is not published, only allow owner to view
    if not store.is_published and not is_owner:
        raise Http404("No Store matches the given query.")
    
    # Get product
    # - For public visitors: must be published
    # - For owner: can view their own unpublished products
    product_qs = Product.objects.filter(slug=product_slug, store=store)
    if not is_owner:
        product_qs = product_qs.filter(status='published')
    product = get_object_or_404(product_qs)
    
    # Increment view count
    product.views_count = F('views_count') + 1
    product.save(update_fields=['views_count'])
    product.refresh_from_db()  # Get actual value
    
    # Get subcategory attributes for rendering specifications
    attributes = SubCategoryAttribute.objects.filter(
        subcategory=product.subcategory,
        is_active=True
    ).order_by('sort_order')
    
    # Build specifications list with proper labels
    specifications = []
    for attr in attributes:
        value = product.attributes.get(attr.name)
        if value:  # Only show if product has this attribute filled
            specifications.append({
                'label': attr.name.replace('_', ' ').title(),
                'value': value,
                'field_type': attr.field_type
            })
    context = {
        'product': product,
        'store': store,
        'vendor': store.vendor,
        'specifications': specifications,
        'is_owner': is_owner,
        'is_preview': not store.is_published and is_owner,
        # Simple stock status for buyers
        'in_stock': product.is_in_stock,
    }
    
    return render(request, 'products/product_detail.html', context)

    
# ==========================================
# AJAX ENDPOINTS FOR DYNAMIC FORMS
# ==========================================

@vendor_required
def ajax_get_subcategories(request):
    """Get subcategories for vendor's main category"""
    vendor = request.user.vendorprofile
    
    if not hasattr(vendor, 'store'):
        return JsonResponse({'subcategories': []})
    
    subcategories = SubCategory.objects.filter(
        main_category=vendor.store.main_category,
        is_active=True
    ).values('id', 'name').order_by('name')
    
    return JsonResponse({
        'subcategories': list(subcategories)
    })


@vendor_required
def ajax_get_attributes(request):
    """Get attributes for a specific subcategory"""
    subcategory_id = request.GET.get('subcategory_id')
    
    if not subcategory_id:
        return JsonResponse({'attributes': []})
    
    attributes = SubCategoryAttribute.objects.filter(
        subcategory_id=subcategory_id,
        is_active=True
    ).order_by('sort_order')
    
    attrs_data = []
    for attr in attributes:
        attrs_data.append({
            'id': attr.id,
            'name': attr.name,
            'field_type': attr.field_type,
            'is_required': attr.is_required,
            'placeholder': attr.placeholder,
            'help_text': attr.help_text,
            'options': attr.options if attr.field_type == 'dropdown' else []
        })
    
    return JsonResponse({'attributes': attrs_data})


# ==========================================
# ORDER VIEWS
# ==========================================

@vendor_required
def orders_list(request):
    """
    List all vendor orders with filters
    """
    vendor = request.user.vendorprofile
    
    # Get filter parameters
    status = request.GET.get('status', '')
    
    # Base queryset
    orders = vendor.orders.all()
    
    # Apply filters
    if status:
        orders = orders.filter(status=status)
    
    # Order by newest first
    orders = orders.order_by('-created_at')
    
    # Pagination
    paginator = Paginator(orders, 20)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    
    # Stats
    context = {
        'orders': page_obj,
        'total_orders': vendor.orders.count(),
        'pending_count': vendor.orders.filter(status__in=['pending', 'confirmed']).count(),
        'completed_count': vendor.orders.filter(status='delivered').count(),
        'current_status': status
    }

    return render(request, 'vendors/orders/list.html', {
        'page_obj': page_obj,
        'orders': page_obj,
        'hide_verification_badge': True,
    })


@vendor_required
@vendor_owns_order
def order_detail(request, order_id):
    """
    View order details and update status
    """
    order = request.order  # Set by decorator
    
    if request.method == 'POST':
        form = OrderStatusUpdateForm(request.POST, instance=order)
        
        if form.is_valid():
            order = form.save()
            
            # Send notification to customer
            notification_service.send_order_status_update(order, order.customer.email)
            
            messages.success(request, f'Order status updated to {order.get_status_display()}')
            return redirect('vendors:order_detail', order_id=order.order_id)
    else:
        form = OrderStatusUpdateForm(instance=order)
    
    context = {
        'order': order,
        'form': form,
        'items': order.items.all(),
        'hide_verification_badge': True,
    }
    
    return render(request, 'vendors/orders/detail.html', context)

@vendor_required
@vendor_owns_order
@require_http_methods(["POST"])
def order_status_update_ajax(request, order_id):
    """
    AJAX endpoint for quick status update
    """
    order = request.order
    
    new_status = request.POST.get('status')
    tracking_number = request.POST.get('tracking_number', '')
    
    # Validate status transition
    allowed_statuses = {
        'pending': ['confirmed', 'cancelled'],
        'confirmed': ['processing', 'cancelled'],
        'processing': ['shipped'],
        'shipped': ['delivered']
    }
    
    if new_status in allowed_statuses.get(order.status, []):
        order.status = new_status
        if tracking_number:
            order.tracking_number = tracking_number
        order.save()
        
        # Send notification
        notification_service.send_order_status_update(order, order.customer.email)
        
        return JsonResponse({'success': True, 'message': 'Status updated'})
    else:
        return JsonResponse({'success': False, 'error': 'Invalid status transition'}, status=400)


# ==========================================
# WALLET VIEWS
# ==========================================

@vendor_required
def wallet_overview(request):
    """
    Wallet overview with balance and transactions
    """
    vendor = request.user.vendorprofile
    wallet = vendor.wallet
    
    # Recent transactions
    transactions = wallet.transactions.all()[:10]
    
    # Stats
    context = {
        'wallet': wallet,
        'transactions': transactions,
        'total_earned': wallet.total_earned,
        'total_withdrawn': wallet.total_withdrawn,
        'pending_balance': wallet.pending_balance,
        'hide_verification_badge': True,
    }
    
    return render(request, 'vendors/wallet/overview.html', context)


@vendor_required
def wallet_transactions(request):
    """
    Full transaction history
    """
    vendor = request.user.vendorprofile
    wallet = vendor.wallet
    
    # Get transactions
    transactions = wallet.transactions.all().order_by('-created_at')
    
    # Pagination
    paginator = Paginator(transactions, 50)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    
    context = {
        'wallet': wallet,
        'transactions': page_obj
    }
    # wallet_transactions
    return render(request, 'vendors/wallet/transactions.html', {
        'page_obj': page_obj,
        'transactions': page_obj,
        'wallet': wallet,
        'hide_verification_badge': True,
    })


@vendor_required
def request_payout(request):
    """
    Request payout/withdrawal
    """
    vendor = request.user.vendorprofile
    wallet = vendor.wallet
    
    # Check minimum balance
    min_payout = Decimal('1000.00')
    
    if wallet.balance < min_payout:
        messages.error(request, f'Minimum payout amount is ₦{min_payout}')
        return redirect('vendors:wallet_overview')
    
    if request.method == 'POST':
        amount = Decimal(request.POST.get('amount', 0))
        
        # Validate amount
        if amount > wallet.balance:
            messages.error(request, 'Insufficient balance')
        elif amount < min_payout:
            messages.error(request, f'Minimum payout is ₦{min_payout}')
        else:
            # Create transfer recipient if not exists
            if not hasattr(wallet, 'paystack_recipient_code'):
                success, recipient_data = paystack_service.create_transfer_recipient(
                    account_number=wallet.account_number,
                    bank_code=wallet.bank_code or '058',  # TODO: Get actual bank code
                    name=wallet.account_holder_name
                )
                
                if success:
                    wallet.paystack_recipient_code = recipient_data.get('recipient_code')
                    wallet.save()
            
            # Initiate transfer
            reference = generate_reference('PAYOUT')
            success, transfer_data = paystack_service.initiate_transfer(
                recipient_code=wallet.paystack_recipient_code,
                amount=amount,
                reason=f'Payout to {vendor.full_name}',
                reference=reference
            )
            
            if success:
                # Deduct from balance
                wallet.balance -= amount
                wallet.total_withdrawn += amount
                wallet.save()
                
                # Create transaction
                Transaction.objects.create(
                    wallet=wallet,
                    transaction_type='payout',
                    amount=amount,
                    status='completed',
                    reference=reference,
                    balance_before=wallet.balance + amount,
                    balance_after=wallet.balance
                )
                
                # Send notification
                notification_service.send_payout_successful(vendor, amount, wallet.bank_name)
                
                messages.success(request, f'Payout of ₦{amount} initiated successfully!')
            else:
                messages.error(request, f"Payout failed: {transfer_data.get('error')}")
        
        return redirect('vendors:wallet_overview')
    
    context = {
        'wallet': wallet,
        'min_payout': min_payout,
        'hide_verification_badge': True,
    }
    
    return render(request, 'vendors/wallet/payout_request.html', context)
@vendor_required
def payment_method(request):
    """
    View/Edit bank account details
    Account Holder Name is READ-ONLY if BVN is verified (auto-filled from BVN)
    Account Number and Bank Name can be changed
    """
    vendor = request.user.vendorprofile
    wallet = vendor.wallet
    
    # Check if BVN is verified (account holder name should be locked)
    bvn_verified = vendor.bank_status == 'bvn_verified'
    
    if request.method == 'POST':
        # Handle bank account update
        account_number = request.POST.get('account_number', '').strip()
        bank_name = request.POST.get('bank_name', '').strip()
        confirm = request.POST.get('confirm')  # Checkbox confirmation
        
        # Validate required fields
        errors = []
        if not bank_name:
            errors.append('Bank name is required.')
        if not account_number:
            errors.append('Account number is required.')
        if not confirm:
            errors.append('Please confirm that the details are correct.')
        
        if errors:
            for error in errors:
                messages.error(request, error)
        else:
            try:
                # ✅ Account Holder Name is READ-ONLY if BVN verified
                # Only update if BVN is NOT verified (shouldn't happen, but safety check)
                if not bvn_verified:
                    account_holder_name = request.POST.get('account_name', '').strip()
                    if account_holder_name:
                        wallet.account_holder_name = account_holder_name
                
                # Account Number and Bank Name can always be updated
                wallet.account_number = account_number
                wallet.bank_name = bank_name
                wallet.save()
                
                logger.info(f'✅ Bank account updated for vendor {vendor.vendor_id}: Bank={bank_name}, Account={account_number}')
                messages.success(request, '✅ Bank account updated successfully!')
                return redirect('vendors:payment_method')
            except Exception as e:
                logger.error(f'❌ Error updating bank account: {str(e)}')
                messages.error(request, f'Failed to update bank account: {str(e)}')
    
    # Create a simple form-like object for template compatibility
    class SimpleForm:
        def __init__(self):
            self.bank_name = type('obj', (object,), {'html_name': 'bank_name', 'id_for_label': 'id_bank_name'})()
            self.account_number = type('obj', (object,), {'html_name': 'account_number', 'id_for_label': 'id_account_number'})()
            self.account_name = type('obj', (object,), {'html_name': 'account_name', 'id_for_label': 'id_account_name'})()
    
    context = {
        'wallet': wallet,
        'vendor': vendor,
        'bank_account': wallet,  # For template compatibility
        'form': SimpleForm(),  # Simple form object for template
        'bvn_verified': bvn_verified,  # Pass flag to template
        'hide_verification_badge': True,
    }
    
    return render(request, 'vendors/wallet/payment_method.html', context)


# ==========================================
# STORE SETTINGS VIEWS
# ==========================================

@vendor_required
def store_settings(request):
    """
    Edit store settings with 1-YEAR CHANGE LIMIT on store name
    Displays warning if store name is locked
    """
    vendor = request.user.vendorprofile
    
    # Check if store exists
    try:
        store = vendor.store
    except Store.DoesNotExist:
        messages.warning(request, 'Please complete store setup first')
        return redirect('vendors:store_setup')
    
    if request.method == 'POST':
        form = StoreSettingsForm(request.POST, request.FILES, instance=store)
        
        if form.is_valid():
            # Check if store name is being changed
            old_store_name = store.store_name
            new_store_name = form.cleaned_data.get('store_name')
            
            store = form.save()
            
            # Log store name change
            if old_store_name != new_store_name:
                logger.warning(
                    f"🔄 STORE NAME CHANGED: '{old_store_name}' → '{new_store_name}' "
                    f"(Vendor: {vendor.full_name}, Change #{store.store_name_change_count})"
                )
                messages.success(
                    request,
                    f'✅ Store name changed to "{new_store_name}". '
                    f'You can change it again after {(store.store_name_last_changed_at + timezone.timedelta(days=365)).strftime("%B %d, %Y")}.'
                )
            else:
                messages.success(request, '✅ Store settings updated successfully!')
            
            return redirect('vendors:store_settings')
        else:
            messages.error(request, '❌ Please correct the errors below.')
    else:
        form = StoreSettingsForm(instance=store)
    
    # Get change limit info for template
    can_change_name = store.can_change_store_name()
    days_until_name_change = store.days_until_next_name_change()
    can_change_category = store.can_request_category_change()
    days_until_category_change = store.days_until_next_category_change()
    
    # Get published products count
    active_products_count = vendor.products.filter(status='published').count()
    
    context = {
        'store': store,
        'form': form,
        'vendor': vendor,
        'active_products_count': active_products_count,
        'can_change_name': can_change_name,
        'days_until_name_change': days_until_name_change,
        'can_change_category': can_change_category,
        'days_until_category_change': days_until_category_change,
        'hide_verification_badge': True,
    }
    
    return render(request, 'vendors/store/settings.html', context)


# ==========================================
# STORE PUBLIC PREVIEW VIEW FOR VENDORS
# ==========================================
@vendor_required
def store_public_preview(request):
    """
    Preview public storefront
    """
    vendor = request.user.vendorprofile
    
    try:
        store = vendor.store
    except Store.DoesNotExist:
        messages.warning(request, 'Store not set up yet')
        return redirect('vendors:store_setup')
    
    # Get products
    products = vendor.products.filter(status='published')[:12]
    
    context = {
        'store': store,
        'products': products,
        'is_preview': True,
        'hide_verification_badge': True,
    }
    
    return render(request, 'vendors/store/preview.html', context)


# ==========================================
# CATEGORY CHANGE REQUEST VIEWS
# ==========================================

@vendor_required
def category_change_request(request):
    """
    Request to change locked main category
    Enforces 1-YEAR LIMIT on category change requests
    """
    vendor = request.user.vendorprofile
    
    # Check if store exists
    try:
        store = vendor.store
    except Store.DoesNotExist:
        messages.warning(request, 'Store not set up yet')
        return redirect('vendors:store_setup')
    
    # Check if category is locked
    if not store.main_category_locked:
        messages.info(request, 'Your category is not locked yet. You can change it in store settings.')
        return redirect('vendors:store_settings')
    
    # Check if they can request a change (1-year limit)
    if not store.can_request_category_change():
        days_left = store.days_until_next_category_change()
        next_change_date = (
            store.main_category_last_changed_at + timezone.timedelta(days=365)
        ).strftime('%B %d, %Y')
        
        messages.warning(
            request,
            f'🔒 Category change requests are limited to once per year. '
            f'You can submit a new request on {next_change_date} ({days_left} days remaining).'
        )
        return redirect('vendors:store_settings')
    
    # Check for pending requests
    pending_request = CategoryChangeRequest.objects.filter(
        store=store,
        status='pending'
    ).first()
    
    if pending_request:
        messages.info(
            request,
            f'You already have a pending category change request '
            f'(from {pending_request.current_category.name} to {pending_request.requested_category.name}). '
            f'Please wait for admin review.'
        )
        return redirect('vendors:store_settings')
    
    if request.method == 'POST':
        form = CategoryChangeRequestForm(request.POST, store=store)
        
        if form.is_valid():
            change_request = form.save()
            
            logger.info(
                f"📋 Category change request submitted: {store.store_name} "
                f"({change_request.current_category.name} → {change_request.requested_category.name})"
            )
            
            messages.success(
                request,
                f'✅ Category change request submitted successfully! '
                f'We will review your request to change from "{change_request.current_category.name}" '
                f'to "{change_request.requested_category.name}" and notify you via email.'
            )
            return redirect('vendors:store_settings')
        else:
            messages.error(request, '❌ Please correct the errors below.')
    else:
        form = CategoryChangeRequestForm(store=store)
    
    # Get change history
    previous_requests = CategoryChangeRequest.objects.filter(
        store=store
    ).exclude(status='pending').order_by('-created_at')[:5]
    
    context = {
        'form': form,
        'store': store,
        'vendor': vendor,
        'previous_requests': previous_requests,
        'can_request_change': store.can_request_category_change(),
        'days_until_next_change': store.days_until_next_category_change(),
        'hide_verification_badge': True,
    }
    
    return render(request, 'vendors/store/category_change_request.html', context)


@vendor_required
def category_change_status(request):
    """
    View status of category change requests
    """
    vendor = request.user.vendorprofile
    
    try:
        store = vendor.store
    except Store.DoesNotExist:
        messages.warning(request, 'Store not set up yet')
        return redirect('vendors:store_setup')
    
    # Get all requests
    all_requests = CategoryChangeRequest.objects.filter(
        store=store
    ).order_by('-created_at')
    
    # Separate by status
    pending_requests = all_requests.filter(status='pending')
    approved_requests = all_requests.filter(status='approved')
    rejected_requests = all_requests.filter(status='rejected')
    
    context = {
        'store': store,
        'vendor': vendor,
        'pending_requests': pending_requests,
        'approved_requests': approved_requests,
        'rejected_requests': rejected_requests,
        'can_request_change': store.can_request_category_change(),
        'days_until_next_change': store.days_until_next_category_change(),
        'hide_verification_badge': True,
    }
    
    return render(request, 'vendors/store/category_change_status.html', context)


def approve_category_change(category_request_id, admin_user):
    """
    Helper function to approve category change request
    Called from admin panel action
    
    Args:
        category_request_id: ID of CategoryChangeRequest
        admin_user: User object of admin approving
    
    Returns:
        tuple: (success: bool, message: str)
    """
    try:
        change_request = CategoryChangeRequest.objects.get(id=category_request_id)
        
        if change_request.status != 'pending':
            return False, f'Request is already {change_request.status}'
        
        # Update store category
        store = change_request.store
        old_category = store.main_category
        new_category = change_request.requested_category
        
        store.main_category = new_category
        store.main_category_last_changed_at = timezone.now()
        store.main_category_change_count = (store.main_category_change_count or 0) + 1
        store.save()
        
        # Update request
        change_request.status = 'approved'
        change_request.reviewed_by = admin_user
        change_request.reviewed_at = timezone.now()
        change_request.save()
        
        logger.info(
            f"✅ Category change APPROVED: {store.store_name} "
            f"({old_category.name} → {new_category.name}) by {admin_user.email}"
        )
        
        # TODO: Send notification email to vendor
        
        return True, f'Category changed from {old_category.name} to {new_category.name}'
        
    except CategoryChangeRequest.DoesNotExist:
        return False, 'Category change request not found'
    except Exception as e:
        logger.error(f'Error approving category change: {str(e)}')
        return False, f'Error: {str(e)}'


def reject_category_change(category_request_id, admin_user, reason=''):
    """
    Helper function to reject category change request
    Called from admin panel action
    
    Args:
        category_request_id: ID of CategoryChangeRequest
        admin_user: User object of admin rejecting
        reason: Optional rejection reason
    
    Returns:
        tuple: (success: bool, message: str)
    """
    try:
        change_request = CategoryChangeRequest.objects.get(id=category_request_id)
        
        if change_request.status != 'pending':
            return False, f'Request is already {change_request.status}'
        
        # Update request
        change_request.status = 'rejected'
        change_request.reviewed_by = admin_user
        change_request.reviewed_at = timezone.now()
        if reason:
            change_request.admin_comment = reason
        change_request.save()
        
        logger.info(
            f"❌ Category change REJECTED: {change_request.store.store_name} "
            f"({change_request.current_category.name} → {change_request.requested_category.name}) "
            f"by {admin_user.email}"
        )
        
        # TODO: Send notification email to vendor
        
        return True, 'Category change request rejected'
        
    except CategoryChangeRequest.DoesNotExist:
        return False, 'Category change request not found'
    except Exception as e:
        logger.error(f'Error rejecting category change: {str(e)}')
        return False, f'Error: {str(e)}'

def get_store_change_summary(store):
    """
    Get summary of store changes for display
    
    Returns:
        dict: Summary of change limits and history
    """
    return {
        # Store Name
        'can_change_name': store.can_change_store_name(),
        'days_until_name_change': store.days_until_next_name_change(),
        'name_change_count': store.store_name_change_count or 0,
        'name_last_changed': store.store_name_last_changed_at,
        'original_name': store.original_store_name,
        
        # Category
        'can_change_category': store.can_request_category_change(),
        'days_until_category_change': store.days_until_next_category_change(),
        'category_change_count': store.main_category_change_count or 0,
        'category_last_changed': store.main_category_last_changed_at,
        'original_category': store.original_main_category,
        'category_locked': store.main_category_locked,
    }


def check_vendor_can_edit_profile(vendor):
    """
    Check what profile fields vendor can edit
    
    Returns:
        dict: Permissions for each field type
    """
    return {
        # Read-Only (Cannot Edit)
        'cannot_edit': {
            'full_name': 'Verified from NIN',
            'email': 'Account email',
            'nin_number': 'Verified identity',
            'bvn_number': 'Verified banking',
            'dob': 'From NIN',
            'gender': 'From NIN',
            'primary_phone': 'From NIN',
            'address': 'From NIN',
            'state': 'From NIN',
            'lga': 'From NIN',
        },
        
        # Can Edit
        'can_edit': {
            'alternative_phone': 'Backup contact',
            'whatsapp': 'WhatsApp contact',
        },
        
        # Special Cases
        'special': {
            'store_name': {
                'can_edit': vendor.store.can_change_store_name() if hasattr(vendor, 'store') else False,
                'reason': 'Once per year limit',
            },
            'main_category': {
                'can_edit': False,
                'reason': 'Requires admin approval',
            }
        }
    }

# ==========================================
# PUBLIC STOREFRONT VIEW

def store_public(request, slug):
    """
    Public-facing store (accessible to customers)
    No login required
    
    Store owners can preview their store even if not published.
    Non-owners can only see published stores.
    """
    # First, try to get the store by slug (without is_published filter)
    try:
        store = Store.objects.get(slug=slug)
    except Store.DoesNotExist:
        raise Http404("No Store matches the given query.")
    
    # Check if store is published
    is_owner = (request.user.is_authenticated and 
                hasattr(request.user, 'vendorprofile') and 
                request.user.vendorprofile == store.vendor)
    
    # If not published, only allow owner to view
    if not store.is_published and not is_owner:
        raise Http404("No Store matches the given query.")
    
    # Get published products
    products = store.vendor.products.filter(status='published').order_by('-created_at')
    
    # Pagination
    from django.core.paginator import Paginator
    paginator = Paginator(products, 12)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    
    context = {
        'store': store,
        'vendor': store.vendor,
        'products': page_obj,
        'total_products': products.count(),
        'is_owner': is_owner,
        'is_preview': not store.is_published and is_owner,  # Show preview banner for owners
    }
    
    return render(request, 'vendors/store/public_storefront.html', context)


# ==========================================
# NOTIFICATIONS
# ==========================================

@vendor_required
def notifications_list(request):
    """
    List all notifications
    """
    vendor = request.user.vendorprofile
    
    notifications = vendor.notifications.all().order_by('-created_at')
    
    # Mark as read
    unread = notifications.filter(is_read=False)
    unread.update(is_read=True, read_at=timezone.now())
    
    # Pagination
    paginator = Paginator(notifications, 20)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    
    return render(request, 'vendors/notifications/list.html', {
        'page_obj': page_obj,
        'notifications': page_obj,
        'hide_verification_badge': True,
    })

@vendor_required
def notification_detail(request, notification_id):
    """
    View single notification
    """
    vendor = request.user.vendorprofile
    notification = get_object_or_404(Notification, id=notification_id, vendor=vendor)
    
    # Mark as read
    if not notification.is_read:
        notification.is_read = True
        notification.read_at = timezone.now()
        notification.save()
    
    return render(request, 'vendors/notifications/detail.html', {'notification': notification, 'hide_verification_badge': True})


# Notification actions
@vendor_required
@require_http_methods(["POST"])
def notification_mark_read(request, notification_id):
    vendor = request.user.vendorprofile
    notification = get_object_or_404(Notification, id=notification_id, vendor=vendor)
    if not notification.is_read:
        notification.is_read = True
        notification.read_at = timezone.now()
        notification.save()
    return redirect('vendors:notification_detail', notification_id=notification.id)


@vendor_required
@require_http_methods(["POST"])
def notification_delete(request, notification_id):
    vendor = request.user.vendorprofile
    notification = get_object_or_404(Notification, id=notification_id, vendor=vendor)
    notification.delete()
    return redirect('vendors:notifications_list')


@vendor_required
@require_http_methods(["POST"])
def notifications_mark_all_read(request):
    vendor = request.user.vendorprofile
    qs = vendor.notifications.filter(is_read=False)
    qs.update(is_read=True, read_at=timezone.now())
    return redirect('vendors:notifications_list')


# ==========================================
# AJAX / API ENDPOINTS
# ==========================================

@vendor_required
@require_http_methods(["GET"])
def get_subcategories_ajax(request):
    """
    Get subcategories for a main category (AJAX)
    """
    main_category_id = request.GET.get('main_category_id')
    
    if not main_category_id:
        return JsonResponse({'error': 'Missing main_category_id'}, status=400)
    
    subcategories = SubCategory.objects.filter(
        main_category_id=main_category_id,
        is_active=True
    ).values('id', 'name')
    
    return JsonResponse({'subcategories': list(subcategories)})


@vendor_required
@require_http_methods(["GET"])
def get_category_attributes_ajax(request):
    """
    Get attributes for a subcategory (AJAX)
    Used for dynamic product form
    """
    subcategory_id = request.GET.get('subcategory_id')
    
    if not subcategory_id:
        return JsonResponse({'error': 'Missing subcategory_id'}, status=400)
    
    try:
        subcategory = SubCategory.objects.get(id=subcategory_id)
        attributes = subcategory.attributes.filter(is_active=True).values(
            'id', 'name', 'field_type', 'options', 'is_required', 
            'placeholder', 'help_text', 'sort_order'
        ).order_by('sort_order')
        
        return JsonResponse({
            'subcategory': subcategory.name,
            'attributes': list(attributes)
        })
    
    except SubCategory.DoesNotExist:
        return JsonResponse({'error': 'Subcategory not found'}, status=404)