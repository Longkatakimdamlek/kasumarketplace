"""
Vendor App Signals
Automatically handle wallet creation, store creation, stats updates, notifications, etc.
"""

from django.db.models.signals import post_save, pre_save, post_delete
from django.dispatch import receiver
from django.contrib.auth import get_user_model
from django.utils import timezone
from django.db.models import Sum, Avg, F

from .models import (
    VendorProfile, Wallet, Store, Product, Order, OrderItem,
    Transaction, Notification, RefundRequest, CategoryChangeRequest
)

User = get_user_model()


# ==========================================
# USER SIGNALS (CREATE VENDORPROFILE)
# ==========================================

@receiver(post_save, sender=User)
def create_vendor_profile_for_vendor_users(sender, instance, created, **kwargs):
    """
    Automatically create VendorProfile when a vendor User is created
    This runs AFTER the user is saved to the database
    """
    if created and hasattr(instance, 'role') and instance.role == 'vendor':
        # Create VendorProfile
        vendor_profile = VendorProfile.objects.create(user=instance)
        print(f"✅ VendorProfile created for vendor: {instance.email}")


# ==========================================
# VENDOR PROFILE SIGNALS
# ==========================================

@receiver(post_save, sender=VendorProfile)
def create_vendor_wallet(sender, instance, created, **kwargs):
    """
    Automatically create a Wallet when VendorProfile is created
    """
    if created:
        Wallet.objects.create(
            vendor=instance,
            commission_rate=10.00  # Default 10% commission
        )
        print(f"✓ Wallet created for vendor: {instance.full_name or instance.user.email}")


@receiver(post_save, sender=VendorProfile)
def send_verification_notifications(sender, instance, created, **kwargs):
    """
    Send notifications when verification status changes
    """
    if not created:
        # Check if verification status changed to approved
        if instance.verification_status == 'approved' and instance.approved_at:
            # Create notification
            Notification.objects.get_or_create(
                vendor=instance,
                notification_type='verification',
                title='Verification Approved! 🎉',
                defaults={
                    'message': 'Congratulations! Your vendor account has been approved. You can now start listing products and selling on KasuMarketplace.',
                    'link': '/vendors/dashboard/'
                }
            )
            print(f"✓ Approval notification sent to: {instance.full_name}")
            
            # TODO: Send email notification
            # from .services.notifications import send_verification_approved_email
            # send_verification_approved_email(instance)
        
        # Check if verification status changed to rejected
        elif instance.verification_status == 'rejected':
            Notification.objects.get_or_create(
                vendor=instance,
                notification_type='verification',
                title='Verification Rejected',
                defaults={
                    'message': f'Your verification was rejected. Reason: {instance.admin_comment or "Please contact support for details."}',
                    'link': '/vendors/verification/'
                }
            )
            print(f"✓ Rejection notification sent to: {instance.full_name}")


# ==========================================
# STORE SIGNALS
# ==========================================

@receiver(post_save, sender=Store)
def update_store_stats(sender, instance, created, **kwargs):
    """
    Update store statistics when products or orders change
    This is called when store is saved, but real updates happen in product/order signals
    """
    if created:
        print(f"✓ Store created: {instance.store_name}")
        
        # Send notification to vendor
        Notification.objects.create(
            vendor=instance.vendor,
            notification_type='system',
            title='Store Created! 🏪',
            message=f'Your store "{instance.store_name}" has been created successfully. You can now add products.',
            link=f'/vendors/store/settings/'
        )


@receiver(post_save, sender=Store)
def notify_category_lock(sender, instance, created, **kwargs):
    """
    Notify vendor when main category is locked
    """
    if not created and instance.main_category_locked:
        # Check if lock status just changed
        old_instance = Store.objects.filter(pk=instance.pk).first()
        if old_instance and not old_instance.main_category_locked:
            Notification.objects.create(
                vendor=instance.vendor,
                notification_type='system',
                title='Category Locked 🔒',
                message=f'Your main category "{instance.main_category.name}" has been locked. To change it, submit a category change request.',
                link='/vendors/store/settings/'
            )


# ==========================================
# PRODUCT SIGNALS
# ==========================================

@receiver(post_save, sender=Product)
def update_store_product_count(sender, instance, created, **kwargs):
    """
    Update store's total_products count when product is added/removed
    """
    store = instance.store
    
    # Count only published products
    store.total_products = store.products.filter(status='published').count()
    store.save(update_fields=['total_products'])
    
    if created:
        print(f"✓ Product created: {instance.title} in store: {store.store_name}")
        
        # Notify vendor
        Notification.objects.create(
            vendor=instance.vendor,
            notification_type='system',
            title='Product Created 📦',
            message=f'Your product "{instance.title}" has been created. Publish it to make it visible to customers.',
            link=f'/vendors/products/{instance.slug}/'
        )


@receiver(post_delete, sender=Product)
def update_store_product_count_on_delete(sender, instance, **kwargs):
    """
    Update store's total_products count when product is deleted
    """
    store = instance.store
    store.total_products = store.products.filter(status='published').count()
    store.save(update_fields=['total_products'])
    
    print(f"✓ Product deleted: {instance.title}")


@receiver(post_save, sender=Product)
def handle_product_publish(sender, instance, created, **kwargs):
    """
    Handle product status change to published
    """
    if not created and instance.status == 'published' and not instance.published_at:
        instance.published_at = timezone.now()
        instance.save(update_fields=['published_at'])
        
        # Notify vendor
        Notification.objects.create(
            vendor=instance.vendor,
            notification_type='system',
            title='Product Published! ✅',
            message=f'Your product "{instance.title}" is now live and visible to customers.',
            link=f'/vendors/products/{instance.slug}/'
        )


# ==========================================
# ORDER SIGNALS
# ==========================================

@receiver(post_save, sender=Order)
def notify_vendor_new_order(sender, instance, created, **kwargs):
    """
    Notify vendor when new order is placed
    """
    if created:
        Notification.objects.create(
            vendor=instance.vendor,
            notification_type='order',
            title='New Order Received! 🛒',
            message=f'You have a new order (#{str(instance.order_id)[:8]}) worth ₦{instance.total_amount}. Please process it promptly.',
            link=f'/vendors/orders/{instance.order_id}/'
        )
        
        print(f"✓ New order notification sent to: {instance.vendor.full_name}")
        
        # TODO: Send email/SMS notification
        # from .services.notifications import send_new_order_email
        # send_new_order_email(instance)


@receiver(post_save, sender=Order)
def update_wallet_on_order_payment(sender, instance, created, **kwargs):
    """
    Update vendor wallet when order is paid
    Add to pending_balance until order is delivered
    """
    if not created and instance.payment_status == 'paid' and instance.paid_at:
        wallet = instance.vendor.wallet
        
        # Check if we already created a transaction for this payment
        existing_transaction = Transaction.objects.filter(
            wallet=wallet,
            order=instance,
            transaction_type='credit',
            status='pending'
        ).first()
        
        if not existing_transaction:
            # Calculate vendor amount (total - commission)
            vendor_amount = instance.vendor_amount
            commission_amount = instance.commission_amount
            
            # Add to pending balance
            balance_before = wallet.balance
            wallet.pending_balance += vendor_amount
            wallet.save(update_fields=['pending_balance'])
            
            # Create transaction record
            Transaction.objects.create(
                wallet=wallet,
                transaction_type='credit',
                amount=vendor_amount,
                status='pending',
                reference=f"ORDER-{instance.order_id}",
                description=f"Payment for order #{str(instance.order_id)[:8]}",
                order=instance,
                balance_before=balance_before,
                balance_after=balance_before  # Balance unchanged, pending increased
            )
            
            print(f"✓ Added ₦{vendor_amount} to pending balance for: {instance.vendor.full_name}")
            
            # Notify vendor
            Notification.objects.create(
                vendor=instance.vendor,
                notification_type='payment',
                title='Payment Received 💰',
                message=f'Payment of ₦{vendor_amount} received for order #{str(instance.order_id)[:8]}. Amount will be available after delivery.',
                link=f'/vendors/wallet/'
            )


@receiver(post_save, sender=Order)
def update_wallet_on_order_delivery(sender, instance, created, **kwargs):
    """
    Move funds from pending_balance to balance when order is delivered
    """
    if not created and instance.status == 'delivered' and instance.delivered_at:
        wallet = instance.vendor.wallet
        
        # Check if we already processed this delivery
        existing_transaction = Transaction.objects.filter(
            wallet=wallet,
            order=instance,
            transaction_type='credit',
            status='completed'
        ).first()
        
        if not existing_transaction:
            vendor_amount = instance.vendor_amount
            
            # Move from pending to available balance
            balance_before = wallet.balance
            wallet.pending_balance -= vendor_amount
            wallet.balance += vendor_amount
            wallet.total_earned += vendor_amount
            wallet.save(update_fields=['pending_balance', 'balance', 'total_earned'])
            
            # Update existing transaction
            transaction = Transaction.objects.filter(
                wallet=wallet,
                order=instance,
                transaction_type='credit',
                status='pending'
            ).first()
            
            if transaction:
                transaction.status = 'completed'
                transaction.balance_after = wallet.balance
                transaction.completed_at = timezone.now()
                transaction.save()
            
            print(f"✓ Moved ₦{vendor_amount} to available balance for: {instance.vendor.full_name}")
            
            # Notify vendor
            Notification.objects.create(
                vendor=instance.vendor,
                notification_type='payment',
                title='Funds Available! 💵',
                message=f'₦{vendor_amount} from order #{str(instance.order_id)[:8]} is now available for withdrawal.',
                link=f'/vendors/wallet/'
            )


@receiver(post_save, sender=Order)
def update_store_order_stats(sender, instance, created, **kwargs):
    """
    Update store's total_orders and total_sales when order is placed/updated
    """
    store = instance.vendor.store
    
    # Count completed orders
    store.total_orders = store.vendor.orders.filter(
        status__in=['delivered', 'completed']
    ).count()
    
    # Sum total sales from delivered orders
    store.total_sales = store.vendor.orders.filter(
        status__in=['delivered', 'completed']
    ).aggregate(
        total=Sum('vendor_amount')
    )['total'] or 0
    
    store.save(update_fields=['total_orders', 'total_sales'])


@receiver(post_save, sender=OrderItem)
def update_product_sales_count(sender, instance, created, **kwargs):
    """
    Update product's sales_count when order is completed
    """
    if instance.order.status in ['delivered', 'completed']:
        product = instance.product
        product.sales_count = OrderItem.objects.filter(
            product=product,
            order__status__in=['delivered', 'completed']
        ).aggregate(
            total_quantity=Sum('quantity')
        )['total_quantity'] or 0
        
        product.save(update_fields=['sales_count'])



@receiver(post_save, sender=OrderItem)
def reduce_product_quantity(sender, instance, created, **kwargs):
    """Reduce product stock when order is placed"""
    if created:
        product = instance.product
        
        # ✅ ONLY REDUCE IF TRACKING INVENTORY
        if product.track_inventory:
            if product.stock_quantity >= instance.quantity:
                product.stock_quantity -= instance.quantity
                product.save(update_fields=['stock_quantity'])
                
                # ✅ CHECK: Low stock alert
                if product.is_low_stock:
                    Notification.objects.create(
                        vendor=product.vendor,
                        notification_type='system',
                        title=f'Low Stock Alert: {product.title}',
                        message=f'Only {product.stock_quantity} units left! Restock soon.',
                        link=f'/vendors/products/{product.slug}/edit/'
                    )
                
                if product.stock_quantity == 0:
                    product.status = 'out_of_stock'
                    product.save(update_fields=['status'])
                    
                    Notification.objects.create(
                        vendor=product.vendor,
                        notification_type='system',
                        title=f'Out of Stock: {product.title}',
                        message=f'Your product is now out of stock. Update inventory to continue selling.',
                        link=f'/vendors/products/{product.slug}/edit/'
                    )
            else:
                print(f"âš ï¸ WARNING: Insufficient stock for {product.title}")



# ==========================================
# REFUND SIGNALS
# ==========================================

@receiver(post_save, sender=RefundRequest)
def notify_vendor_refund_request(sender, instance, created, **kwargs):
    """
    Notify vendor when customer requests refund
    """
    if created:
        Notification.objects.create(
            vendor=instance.vendor,
            notification_type='refund',
            title='Refund Request Received',
            message=f'Customer requested refund for order #{str(instance.order.order_id)[:8]}. Reason: {instance.get_reason_display()}',
            link=f'/vendors/refunds/{instance.refund_id}/'
        )
        
        print(f"✓ Refund request notification sent to: {instance.vendor.full_name}")


@receiver(post_save, sender=RefundRequest)
def process_approved_refund(sender, instance, created, **kwargs):
    """
    Process refund when approved by admin
    Deduct amount from vendor wallet
    """
    if not created and instance.status == 'approved':
        # Check if we already processed this refund
        existing_transaction = Transaction.objects.filter(
            wallet=instance.vendor.wallet,
            transaction_type='refund',
            reference=f"REFUND-{instance.refund_id}"
        ).exists()
        
        if not existing_transaction:
            wallet = instance.vendor.wallet
            refund_amount = instance.amount
            
            # Deduct from balance
            balance_before = wallet.balance
            wallet.balance -= refund_amount
            wallet.save(update_fields=['balance'])
            
            # Create transaction
            Transaction.objects.create(
                wallet=wallet,
                transaction_type='refund',
                amount=refund_amount,
                status='completed',
                reference=f"REFUND-{instance.refund_id}",
                description=f"Refund for order #{str(instance.order.order_id)[:8]}",
                order=instance.order,
                balance_before=balance_before,
                balance_after=wallet.balance,
                completed_at=timezone.now()
            )
            
            print(f"✓ Refund processed: ₦{refund_amount} deducted from {instance.vendor.full_name}")
            
            # Notify vendor
            Notification.objects.create(
                vendor=instance.vendor,
                notification_type='refund',
                title='Refund Processed',
                message=f'Refund of ₦{refund_amount} has been processed for order #{str(instance.order.order_id)[:8]}.',
                link=f'/vendors/wallet/transactions/'
            )


# ==========================================
# TRANSACTION SIGNALS
# ==========================================

@receiver(post_save, sender=Transaction)
def notify_vendor_payout(sender, instance, created, **kwargs):
    """
    Notify vendor when payout is completed
    """
    if instance.transaction_type == 'payout' and instance.status == 'completed':
        Notification.objects.create(
            vendor=instance.wallet.vendor,
            notification_type='payment',
            title='Payout Successful 💸',
            message=f'Your payout of ₦{instance.amount} has been sent to your bank account ({instance.wallet.bank_name}).',
            link='/vendors/wallet/payout-history/'
        )
        
        print(f"✓ Payout notification sent: ₦{instance.amount} to {instance.wallet.vendor.full_name}")


# ==========================================
# HELPER FUNCTIONS
# ==========================================

def recalculate_store_stats(store):
    """
    Manually recalculate all store statistics
    Useful for fixing inconsistencies
    """
    # Total products (published only)
    store.total_products = store.products.filter(status='published').count()
    
    # Total orders (completed only)
    store.total_orders = store.vendor.orders.filter(
        status__in=['delivered', 'completed']
    ).count()
    
    # Total sales
    store.total_sales = store.vendor.orders.filter(
        status__in=['delivered', 'completed']
    ).aggregate(total=Sum('vendor_amount'))['total'] or 0
    
    # Average rating (if you add reviews later)
    # store.average_rating = ...
    
    store.save()
    print(f"✓ Store stats recalculated for: {store.store_name}")


def recalculate_wallet_balances(wallet):
    """
    Manually recalculate wallet balances from transactions
    Useful for auditing/fixing inconsistencies
    """
    # Calculate balance from completed credit transactions
    total_credits = Transaction.objects.filter(
        wallet=wallet,
        transaction_type='credit',
        status='completed'
    ).aggregate(total=Sum('amount'))['total'] or 0
    
    # Calculate total debits (payouts + refunds)
    total_debits = Transaction.objects.filter(
        wallet=wallet,
        transaction_type__in=['payout', 'refund'],
        status='completed'
    ).aggregate(total=Sum('amount'))['total'] or 0
    
    # Calculate pending balance
    pending = Transaction.objects.filter(
        wallet=wallet,
        transaction_type='credit',
        status='pending'
    ).aggregate(total=Sum('amount'))['total'] or 0
    
    # Update wallet
    wallet.balance = total_credits - total_debits
    wallet.pending_balance = pending
    wallet.total_earned = total_credits
    wallet.total_withdrawn = Transaction.objects.filter(
        wallet=wallet,
        transaction_type='payout',
        status='completed'
    ).aggregate(total=Sum('amount'))['total'] or 0
    
    wallet.save()
    print(f"✓ Wallet balances recalculated for: {wallet.vendor.full_name}")


# ==========================================
# ADMIN MESSAGE SIGNALS
# ==========================================

@receiver(post_save, sender=CategoryChangeRequest)
def notify_vendor_of_admin_message(sender, instance, created, **kwargs):
    """
    Create notification when admin sends message to vendor via CategoryChangeRequest
    """
    if not created and instance.admin_comment:
        # Check if we already sent a notification for this comment
        last_notification = Notification.objects.filter(
            vendor=instance.store.vendor,
            notification_type='admin_message',
            title__icontains='Category Change Request'
        ).order_by('-created_at').first()
        
        # Only create new notification if admin_comment has changed or is new
        if not last_notification or last_notification.message != instance.admin_comment:
            Notification.objects.create(
                vendor=instance.store.vendor,
                notification_type='admin_message',
                title=f'📧 Admin Update - Category Change Request #{instance.id}',
                message=instance.admin_comment,
                link=f'/vendors/store/category-change-request/{instance.id}/'
            )
            
            print(f"✓ Admin message notification sent to: {instance.store.vendor.full_name}")