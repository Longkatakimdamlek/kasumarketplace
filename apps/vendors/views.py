"""
Vendor App Views
All views for vendor dashboard, verification, products, orders, wallet, etc.
"""

from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_http_methods
from django.http import JsonResponse, HttpResponse
from django.db.models import Sum, Count, Q
from django.utils import timezone
from django.core.paginator import Paginator
from decimal import Decimal

from .models import (
    VendorProfile, Store, Product, ProductImage, 
    Order, OrderItem, Wallet, Transaction,
    MainCategory, SubCategory, CategoryChangeRequest,
    Notification
)
from .forms import (
    NINEntryForm, NINOTPForm, BVNEntryForm, BVNOTPForm,
    StudentVerificationForm, StoreSetupForm, ProductForm,
    ProductImageFormSet, OrderStatusUpdateForm, CategoryChangeRequestForm
)
from .decorators import (
    vendor_required, vendor_verified_required, 
    vendor_owns_product, vendor_owns_order,
    rate_limit_verification
)
from .services import dojah_service, paystack_service, notification_service
from .services.utils import generate_reference, calculate_commission

import logging

logger = logging.getLogger(__name__)


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
            quantity__lte=5
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
    
    # Calculate step status
    steps = [
        {
            'number': 1,
            'name': 'Identity (NIN)',
            'status': vendor.identity_status,
            'completed': vendor.identity_status == 'nin_verified',
            'url': 'vendors:nin_entry',
            'icon': 'user-check'
        },
        {
            'number': 2,
            'name': 'Banking (BVN)',
            'status': vendor.bank_status,
            'completed': vendor.bank_status == 'bvn_verified',
            'url': 'vendors:bvn_entry',
            'icon': 'credit-card',
            'locked': vendor.identity_status != 'nin_verified'
        },
        {
            'number': 3,
            'name': 'Store Setup',
            'status': 'completed' if vendor.store_setup_completed else 'pending',
            'completed': vendor.store_setup_completed,
            'url': 'vendors:store_setup',
            'icon': 'store',
            'skippable': True,
            'locked': vendor.bank_status != 'bvn_verified'
        },
        {
            'number': 4,
            'name': 'Student Verification (Optional)',
            'status': vendor.student_status,
            'completed': vendor.student_status == 'verified',
            'url': 'vendors:student_verification',
            'icon': 'graduation-cap',
            'optional': True
        },
        {
            'number': 5,
            'name': 'Admin Review',
            'status': vendor.verification_status,
            'completed': vendor.verification_status == 'approved',
            'icon': 'shield-check'
        }
    ]
    
    context = {
        'vendor': vendor,
        'steps': steps,
        'completion_percentage': vendor.completion_percentage,
        'current_step': vendor.current_step,
        'can_sell': vendor.can_sell
    }
    
    return render(request, 'vendors/verification/center.html', context)


@vendor_required
@rate_limit_verification
def nin_entry(request):
    """
    Step 1: NIN Entry
    """
    vendor = request.user.vendorprofile
    
    # If already verified, redirect
    if vendor.identity_status == 'nin_verified':
        messages.info(request, 'NIN already verified')
        return redirect('vendors:verification_center')
    
    if request.method == 'POST':
        form = NINEntryForm(request.POST)
        
        if form.is_valid():
            nin_number = form.cleaned_data['nin_number']
            
            # Call Dojah API
            success, data = dojah_service.verify_nin(nin_number)
            
            if success:
                # Update vendor profile
                vendor.nin_number = nin_number
                vendor.full_name = f"{data.get('firstname')} {data.get('surname')}"
                vendor.phone = data.get('phone', vendor.phone)
                vendor.dob = data.get('birthdate')
                vendor.gender = data.get('gender', '').lower()
                vendor.address = data.get('residence_address')
                vendor.state = data.get('residence_state')
                vendor.lga = data.get('residence_lga')
                # TODO: Download and save photo
                vendor.identity_status = 'nin_verified'
                vendor.nin_verified_at = timezone.now()
                vendor.save()
                
                # Send notification
                notification_service.send_nin_verified(vendor)
                
                messages.success(request, 'NIN verified successfully! ✅')
                return redirect('vendors:bvn_entry')
            else:
                messages.error(request, f"NIN verification failed: {data.get('error')}")
    else:
        form = NINEntryForm()
    
    return render(request, 'vendors/verification/nin_entry.html', {'form': form})


@vendor_required
@rate_limit_verification
def bvn_entry(request):
    """
    Step 2: BVN Entry
    """
    vendor = request.user.vendorprofile
    
    # Check NIN verified first
    if vendor.identity_status != 'nin_verified':
        messages.warning(request, 'Please verify NIN first')
        return redirect('vendors:nin_entry')
    
    # If already verified
    if vendor.bank_status == 'bvn_verified':
        messages.info(request, 'BVN already verified')
        return redirect('vendors:verification_center')
    
    if request.method == 'POST':
        form = BVNEntryForm(request.POST)
        
        if form.is_valid():
            bvn_number = form.cleaned_data['bvn_number']
            bank_name = form.cleaned_data['bank_name']
            
            # Call Dojah API
            success, data = dojah_service.verify_bvn(bvn_number)
            
            if success:
                # Update vendor
                vendor.bvn_number = bvn_number
                vendor.bank_status = 'bvn_verified'
                vendor.bvn_verified_at = timezone.now()
                vendor.save()
                
                # Update wallet
                wallet = vendor.wallet
                wallet.account_holder_name = data.get('account_name', vendor.full_name)
                wallet.bank_name = bank_name
                wallet.account_number = data.get('account_number', '')
                wallet.is_verified = True
                wallet.verified_at = timezone.now()
                wallet.save()
                
                # Send notification
                notification_service.send_bvn_verified(vendor)
                
                messages.success(request, 'BVN verified successfully! ✅')
                return redirect('vendors:store_setup')
            else:
                messages.error(request, f"BVN verification failed: {data.get('error')}")
    else:
        form = BVNEntryForm()
    
    return render(request, 'vendors/verification/bvn_entry.html', {'form': form, 'vendor': vendor})


@vendor_required
def store_setup(request):
    """
    Step 3: Store Setup (can be skipped)
    """
    vendor = request.user.vendorprofile
    
    # Check prerequisites
    if not vendor.can_sell:
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
    
    context = {
        'form': form,
        'vendor': vendor,
        'is_new': is_new,
        'categories': MainCategory.objects.filter(is_active=True)
    }
    
    return render(request, 'vendors/verification/store_setup.html', context)


@vendor_required
def student_verification(request):
    """
    Step 4: Student Verification (Optional)
    """
    vendor = request.user.vendorprofile
    
    if request.method == 'POST':
        form = StudentVerificationForm(request.POST, request.FILES, instance=vendor)
        
        if form.is_valid():
            vendor = form.save(commit=False)
            vendor.student_status = 'pending'
            vendor.save()
            
            messages.success(request, 'Student verification submitted! Waiting for admin review.')
            return redirect('vendors:verification_center')
    else:
        form = StudentVerificationForm(instance=vendor)
    
    return render(request, 'vendors/verification/student_verification.html', {'form': form})

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
        'phone_last_4': vendor.phone[-4:] if vendor.phone else '****'
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
    
    return render(request, 'vendors/verification/nin_success.html', {'vendor': vendor})


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
        'phone_last_4': vendor.phone[-4:] if vendor.phone else '****'
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
    
    return render(request, 'vendors/verification/bvn_success.html', {'vendor': vendor})

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
        'estimated_review_time': '24-48 hours'
    }
    
    return render(request, 'vendors/verification/pending_review.html', context)


# ==========================================
# PRODUCT VIEWS
# ==========================================

@vendor_verified_required
def products_list(request):
    """
    List all vendor products with filters
    """
    vendor = request.user.vendorprofile
    
    # Get filter parameters
    status = request.GET.get('status', '')
    search = request.GET.get('search', '')
    
    # Base queryset
    products = vendor.products.all()
    
    # Apply filters
    if status:
        products = products.filter(status=status)
    
    if search:
        products = products.filter(
            Q(title__icontains=search) | 
            Q(description__icontains=search)
        )
    
    # Order by newest first
    products = products.order_by('-created_at')
    
    # Pagination
    paginator = Paginator(products, 20)  # 20 per page
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    
    context = {
        'products': page_obj,
        'total_products': vendor.products.count(),
        'published_count': vendor.products.filter(status='published').count(),
        'draft_count': vendor.products.filter(status='draft').count(),
        'current_status': status,
        'search_query': search
    }
    
    return render(request, 'vendors/products/list.html', context)


@vendor_verified_required
def product_create(request):
    """
    Create new product with dynamic attributes
    """
    vendor = request.user.vendorprofile
    
    # Check if store setup is complete
    if not hasattr(vendor, 'store'):
        messages.warning(request, 'Please complete store setup first')
        return redirect('vendors:store_setup')
    
    if request.method == 'POST':
        form = ProductForm(request.POST, vendor=vendor)
        formset = ProductImageFormSet(request.POST, request.FILES)
        
        if form.is_valid() and formset.is_valid():
            product = form.save()
            
            # Save images
            formset.instance = product
            formset.save()
            
            messages.success(request, f'Product "{product.title}" created successfully!')
            return redirect('vendors:products_list')
    else:
        # Get subcategory if selected
        subcategory_id = request.GET.get('subcategory')
        form = ProductForm(vendor=vendor, subcategory_id=subcategory_id)
        formset = ProductImageFormSet()
    
    context = {
        'form': form,
        'formset': formset,
        'subcategories': SubCategory.objects.filter(
            main_category=vendor.store.main_category,
            is_active=True
        )
    }
    
    return render(request, 'vendors/products/create.html', context)


@vendor_verified_required
@vendor_owns_product
def product_edit(request, slug):
    """
    Edit existing product
    """
    product = request.product  # Set by decorator
    
    if request.method == 'POST':
        form = ProductForm(request.POST, instance=product, vendor=request.user.vendorprofile)
        formset = ProductImageFormSet(request.POST, request.FILES, instance=product)
        
        if form.is_valid() and formset.is_valid():
            product = form.save()
            formset.save()
            
            messages.success(request, 'Product updated successfully!')
            return redirect('vendors:products_list')
    else:
        form = ProductForm(instance=product, vendor=request.user.vendorprofile)
        formset = ProductImageFormSet(instance=product)
    
    context = {
        'form': form,
        'formset': formset,
        'product': product,
        'is_editing': True
    }
    
    return render(request, 'vendors/products/edit.html', context)


@vendor_verified_required
@vendor_owns_product
def product_delete(request, slug):
    """
    Delete product
    """
    product = request.product
    
    if request.method == 'POST':
        title = product.title
        product.delete()
        
        messages.success(request, f'Product "{title}" deleted')
        return redirect('vendors:products_list')
    
    return render(request, 'vendors/products/delete_confirm.html', {'product': product})


@vendor_verified_required
@vendor_owns_product
def product_detail(request, slug):
    """
    View product details
    """
    product = request.product
    
    # Get product stats
    context = {
        'product': product,
        'total_orders': OrderItem.objects.filter(product=product).count(),
        'total_revenue': OrderItem.objects.filter(
            product=product,
            order__status='delivered'
        ).aggregate(total=Sum('total'))['total'] or 0
    }
    
    return render(request, 'vendors/products/detail.html', context)


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
    
    return render(request, 'vendors/orders/list.html', context)


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
        'items': order.items.all()
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
        'pending_balance': wallet.pending_balance
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
    
    return render(request, 'vendors/wallet/transactions.html', context)


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
        'min_payout': min_payout
    }
    
    return render(request, 'vendors/wallet/payout_request.html', context)
@vendor_required
def payment_method(request):
    """
    View/Edit bank account details
    """
    vendor = request.user.vendorprofile
    wallet = vendor.wallet
    
    if request.method == 'POST':
        # Handle bank account update
        account_number = request.POST.get('account_number')
        bank_name = request.POST.get('bank_name')
        
        # Validate via Paystack (optional)
        # success, data = paystack_service.verify_account(account_number, bank_code)
        
        wallet.account_number = account_number
        wallet.bank_name = bank_name
        wallet.save()
        
        messages.success(request, 'Bank account updated!')
        return redirect('vendors:payment_method')
    
    context = {
        'wallet': wallet,
        'vendor': vendor
    }
    
    return render(request, 'vendors/wallet/payment_method.html', context)


# ==========================================
# STORE VIEWS
# ==========================================

@vendor_required
def store_settings(request):
    """
    Edit store settings
    """
    vendor = request.user.vendorprofile
    
    try:
        store = vendor.store
    except Store.DoesNotExist:
        messages.warning(request, 'Please complete store setup first')
        return redirect('vendors:store_setup')
    
    if request.method == 'POST':
        form = StoreSetupForm(request.POST, request.FILES, instance=store, vendor=vendor)
        
        if form.is_valid():
            form.save()
            messages.success(request, 'Store settings updated!')
            return redirect('vendors:store_settings')
    else:
        form = StoreSetupForm(instance=store, vendor=vendor)
    
    return render(request, 'vendors/store/settings.html', {'form': form, 'store': store})


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
        'is_preview': True
    }
    
    return render(request, 'vendors/store/preview.html', context)


@vendor_required
def category_change_request(request):
    """
    Request to change locked main category
    """
    vendor = request.user.vendorprofile
    
    try:
        store = vendor.store
    except Store.DoesNotExist:
        messages.warning(request, 'Store not set up yet')
        return redirect('vendors:store_setup')
    
    if not store.main_category_locked:
        messages.info(request, 'Your category is not locked yet')
        return redirect('vendors:store_settings')
    
    if request.method == 'POST':
        form = CategoryChangeRequestForm(request.POST, store=store)
        
        if form.is_valid():
            form.save()
            messages.success(request, 'Category change request submitted! Admin will review it.')
            return redirect('vendors:store_settings')
    else:
        form = CategoryChangeRequestForm(store=store)
    
    return render(request, 'vendors/store/category_change_request.html', {
        'form': form,
        'store': store
    })
def store_public(request, slug):
    """
    Public-facing store (accessible to customers)
    No login required
    """
    store = get_object_or_404(Store, slug=slug, is_published=True)
    
    # Get published products
    products = store.products.filter(status='published').order_by('-created_at')
    
    # Pagination
    paginator = Paginator(products, 12)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    
    context = {
        'store': store,
        'vendor': store.vendor,
        'products': page_obj,
        'total_products': products.count(),
        'is_owner': request.user.is_authenticated and 
                    hasattr(request.user, 'vendorprofile') and 
                    request.user.vendorprofile == store.vendor
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
    
    return render(request, 'vendors/notifications/list.html', {'notifications': page_obj})
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
    
    return render(request, 'vendors/notifications/detail.html', {'notification': notification})


# ==========================================
# PROFILE
# ==========================================

@vendor_required
def profile_view(request):
    """
    View vendor profile
    """
    vendor = request.user.vendorprofile
    
    return render(request, 'vendors/profile/view.html', {'vendor': vendor})

@vendor_required
def profile_edit(request):
    """
    Edit vendor profile (non-verification fields)
    """
    vendor = request.user.vendorprofile
    
    if request.method == 'POST':
        # Handle profile update
        vendor.phone = request.POST.get('phone', vendor.phone)
        vendor.address = request.POST.get('address', vendor.address)
        # Add more editable fields as needed
        vendor.save()
        
        messages.success(request, 'Profile updated!')
        return redirect('vendors:profile_view')
    
    return render(request, 'vendors/profile/edit.html', {'vendor': vendor})


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