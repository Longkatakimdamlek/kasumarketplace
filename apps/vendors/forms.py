"""
Vendor App Forms
All forms for verification, store setup, products, etc.
"""

from django import forms
from django.core.exceptions import ValidationError
from django.core.validators import RegexValidator
from django.utils.text import slugify
from django.utils import timezone
from django.forms import inlineformset_factory, BaseInlineFormSet
from .models import (
    VendorProfile, Store, Product, ProductImage, 
    MainCategory, SubCategory, SubCategoryAttribute,
    CategoryChangeRequest, Order
)
import re
import logging

logger = logging.getLogger(__name__)


class VendorProfileEditForm(forms.ModelForm):
    """
    Form for editing vendor profile - ONLY editable fields
    Verified information (NIN, BVN, Email, Legal Name) is READ-ONLY
    """
    
    alternative_phone = forms.CharField(
        max_length=20,
        required=False,
        label='Alternative Phone Number',
        widget=forms.TextInput(attrs={
            'class': 'w-full px-4 py-3 border-2 border-gray-300 rounded-lg focus:ring-2 focus:ring-primary focus:border-primary',
            'placeholder': '08012345678',
            'pattern': '^(0|\+234)[7-9][0-1]\d{8}$'
        }),
        help_text='Optional backup phone number for customer contact'
    )
    
    whatsapp = forms.CharField(
        max_length=20,
        required=False,
        label='WhatsApp Number',
        widget=forms.TextInput(attrs={
            'class': 'w-full px-4 py-3 border-2 border-gray-300 rounded-lg focus:ring-2 focus:ring-green-500 focus:border-green-500',
            'placeholder': '08012345678',
            'pattern': '^(0|\+234)[7-9][0-1]\d{8}$'
        }),
        help_text='WhatsApp number for quick customer communication'
    )
    
    class Meta:
        model = VendorProfile
        fields = []  # No model fields directly, using custom fields
    
    def clean_alternative_phone(self):
        """Validate alternative phone number format"""
        phone = self.cleaned_data.get('alternative_phone')
        
        if phone:
            # Remove spaces, dashes, parentheses
            phone = re.sub(r'[\s\-\(\)]', '', phone)
            
            # Nigerian phone validation
            if not re.match(r'^(0|\+234)[7-9][0-1]\d{8}$', phone):
                raise ValidationError('Invalid Nigerian phone number format. Use format: 08012345678')
            
            # Normalize to 0XXXXXXXXXX format
            if phone.startswith('+234'):
                phone = '0' + phone[4:]
        
        return phone
    
    def clean_whatsapp(self):
        """Validate WhatsApp number format"""
        whatsapp = self.cleaned_data.get('whatsapp')
        
        if whatsapp:
            # Remove spaces, dashes, parentheses
            whatsapp = re.sub(r'[\s\-\(\)]', '', whatsapp)
            
            # Nigerian phone validation
            if not re.match(r'^(0|\+234)[7-9][0-1]\d{8}$', whatsapp):
                raise ValidationError('Invalid WhatsApp number format. Use format: 08012345678')
            
            # Normalize to 0XXXXXXXXXX format
            if whatsapp.startswith('+234'):
                whatsapp = '0' + whatsapp[4:]
        
        return whatsapp

# ==========================================
# VERIFICATION FORMS
# ==========================================

class NINEntryForm(forms.Form):
    """
    Step 1: Vendor enters NIN (11 digits)
    """
    nin_number = forms.CharField(
        max_length=11,
        min_length=11,
        label='National Identity Number (NIN)',
        widget=forms.TextInput(attrs={
            'class': 'form-input',
            'placeholder': '12345678901',
            'pattern': '[0-9]{11}',
            'maxlength': '11',
            'autocomplete': 'off'
        }),
        validators=[
            RegexValidator(
                regex=r'^\d{11}$',
                message='NIN must be exactly 11 digits'
            )
        ]
    )
    
    def clean_nin_number(self):
        nin = self.cleaned_data.get('nin_number')
        
        # Remove any spaces or dashes
        nin = re.sub(r'[\s\-]', '', nin)
        
        # Check if already used by another vendor
        if VendorProfile.objects.filter(nin_number=nin).exists():
            raise ValidationError('This NIN is already registered with another vendor account.')
        
        return nin


class NINOTPForm(forms.Form):
    """
    Step 2: Verify OTP sent to NIN-linked phone
    """
    otp_code = forms.CharField(
        max_length=6,
        min_length=6,
        label='Enter OTP',
        widget=forms.TextInput(attrs={
            'class': 'form-input otp-input',
            'placeholder': '123456',
            'pattern': '[0-9]{6}',
            'maxlength': '6',
            'autocomplete': 'off',
            'inputmode': 'numeric'
        }),
        validators=[
            RegexValidator(
                regex=r'^\d{6}$',
                message='OTP must be exactly 6 digits'
            )
        ]
    )
    
    def clean_otp_code(self):
        otp = self.cleaned_data.get('otp_code')
        # Remove any spaces
        otp = re.sub(r'\s', '', otp)
        return otp


class BVNEntryForm(forms.Form):
    """
    Step 3: Vendor enters BVN and bank details
    """
    
    NIGERIAN_BANKS = [
        ('', '-- Select Bank --'),
        ('Access Bank', 'Access Bank'),
        ('Citibank', 'Citibank'),
        ('Ecobank', 'Ecobank Nigeria'),
        ('Fidelity Bank', 'Fidelity Bank'),
        ('First Bank', 'First Bank of Nigeria'),
        ('FCMB', 'First City Monument Bank'),
        ('GTBank', 'Guaranty Trust Bank'),
        ('Heritage Bank', 'Heritage Bank'),
        ('Keystone Bank', 'Keystone Bank'),
        ('Polaris Bank', 'Polaris Bank'),
        ('Providus Bank', 'Providus Bank'),
        ('Stanbic IBTC', 'Stanbic IBTC Bank'),
        ('Standard Chartered', 'Standard Chartered Bank'),
        ('Sterling Bank', 'Sterling Bank'),
        ('Union Bank', 'Union Bank of Nigeria'),
        ('UBA', 'United Bank for Africa'),
        ('Unity Bank', 'Unity Bank'),
        ('Wema Bank', 'Wema Bank'),
        ('Zenith Bank', 'Zenith Bank'),
    ]
    
    bvn_number = forms.CharField(
        max_length=11,
        min_length=11,
        label='Bank Verification Number (BVN)',
        widget=forms.TextInput(attrs={
            'class': 'form-input',
            'placeholder': '22334455667',
            'pattern': '[0-9]{11}',
            'maxlength': '11',
            'autocomplete': 'off'
        }),
        validators=[
            RegexValidator(
                regex=r'^\d{11}$',
                message='BVN must be exactly 11 digits'
            )
        ]
    )
    
    bank_name = forms.ChoiceField(
        choices=NIGERIAN_BANKS,
        label='Select Your Bank',
        widget=forms.Select(attrs={
            'class': 'form-select'
        })
    )
    
    def clean_bvn_number(self):
        bvn = self.cleaned_data.get('bvn_number')
        
        # Remove any spaces or dashes
        bvn = re.sub(r'[\s\-]', '', bvn)
        
        # Check if already used
        if VendorProfile.objects.filter(bvn_number=bvn).exists():
            raise ValidationError('This BVN is already registered with another vendor account.')
        
        return bvn


class BVNOTPForm(forms.Form):
    """
    Step 4: Verify OTP sent to BVN-linked phone
    """
    otp_code = forms.CharField(
        max_length=6,
        min_length=6,
        label='Enter OTP',
        widget=forms.TextInput(attrs={
            'class': 'form-input otp-input',
            'placeholder': '123456',
            'pattern': '[0-9]{6}',
            'maxlength': '6',
            'autocomplete': 'off',
            'inputmode': 'numeric'
        }),
        validators=[
            RegexValidator(
                regex=r'^\d{6}$',
                message='OTP must be exactly 6 digits'
            )
        ]
    )


class StudentVerificationForm(forms.ModelForm):
    """
    Optional: Student verification for badge/perks
    """
    
    LEVEL_CHOICES = [
        ('', '-- Select Level --'),
        ('100', '100 Level'),
        ('200', '200 Level'),
        ('300', '300 Level'),
        ('400', '400 Level'),
        ('500', '500 Level'),
        ('PG', 'Postgraduate'),
    ]
    
    level = forms.ChoiceField(
        choices=LEVEL_CHOICES,
        required=True,
        widget=forms.Select(attrs={'class': 'form-select'})
    )
    
    class Meta:
        model = VendorProfile
        fields = ['matric_number', 'department', 'level', 'student_id_image', 'selfie']
        widgets = {
            'matric_number': forms.TextInput(attrs={
                'class': 'form-input',
                'placeholder': 'e.g., KASU/CSC/2020/1234'
            }),
            'department': forms.TextInput(attrs={
                'class': 'form-input',
                'placeholder': 'e.g., Computer Science'
            }),
            'student_id_image': forms.FileInput(attrs={
                'class': 'form-file',
                'accept': 'image/*'
            }),
            'selfie': forms.FileInput(attrs={
                'class': 'form-file',
                'accept': 'image/*',
                'capture': 'user'  # Opens front camera on mobile
            })
        }
    
    def clean_matric_number(self):
        matric = self.cleaned_data.get('matric_number')
        
        # Basic format validation (adjust to your institution's format)
        if not re.match(r'^[A-Z]{3}/\d{4}/\d{3,4}$', matric.upper()):
            raise ValidationError('Invalid matric number format. Expected format: KASU/ABC/2020/1234')
        
        return matric.upper()
    
    def clean_student_id_image(self):
        image = self.cleaned_data.get('student_id_image')
        
        if image:
            # Check file size (max 5MB)
            if image.size > 5 * 1024 * 1024:
                raise ValidationError('Student ID image must be less than 5MB')
            
            # Check file type
            if not image.content_type in ['image/jpeg', 'image/jpg', 'image/png']:
                raise ValidationError('Only JPG and PNG images are allowed')
        
        return image
    
    def clean_selfie(self):
        image = self.cleaned_data.get('selfie')
        
        if image:
            # Check file size (max 5MB)
            if image.size > 5 * 1024 * 1024:
                raise ValidationError('Selfie must be less than 5MB')
            
            # Check file type
            if not image.content_type in ['image/jpeg', 'image/jpg', 'image/png']:
                raise ValidationError('Only JPG and PNG images are allowed')
        
        return image


# ==========================================
# STORE SETUP FORM
# ==========================================

class StoreSetupForm(forms.ModelForm):
    """
    Multi-step store setup form
    Includes category lock warning
    """
    
    # Don't define queryset here - do it in __init__
    main_category = forms.ModelChoiceField(
        queryset=None,  # ← Will be set in __init__
        empty_label='-- Select Main Category --',
        widget=forms.Select(attrs={
            'class': 'w-full px-4 py-3 border-2 border-gray-300 rounded-lg focus:ring-2 focus:ring-primary focus:border-primary transition-all',
            'id': 'id_main_category'
        }),
        help_text='⚠️ This will be locked after confirmation and cannot be changed without admin approval'
    )
    
    confirm_category_lock = forms.BooleanField(
        required=True,
        label='I understand that my main category will be locked after confirmation',
        widget=forms.CheckboxInput(attrs={
            'class': 'form-checkbox'
        })
    )
    
    class Meta:
        model = Store
        fields = [
            'store_name', 'tagline', 'description', 'main_category',
            'logo', 'banner', 'primary_color',
            'business_email', 'phone', 'whatsapp', 'address',
            'instagram', 'facebook', 'twitter',
            'shipping_policy', 'return_policy'
        ]
        widgets = {
            'store_name': forms.TextInput(attrs={
                'class': 'w-full px-4 py-3 border-2 border-gray-300 rounded-lg focus:ring-2 focus:ring-primary focus:border-primary',
                'placeholder': "e.g., John's Fashion Hub",
                'maxlength': '100'
            }),
            'tagline': forms.TextInput(attrs={
                'class': 'w-full px-4 py-3 border-2 border-gray-300 rounded-lg focus:ring-2 focus:ring-primary focus:border-primary',
                'placeholder': 'Short description of your store',
                'maxlength': '150'
            }),
            'description': forms.Textarea(attrs={
                'class': 'w-full px-4 py-3 border-2 border-gray-300 rounded-lg focus:ring-2 focus:ring-primary focus:border-primary',
                'rows': 4,
                'placeholder': 'Tell customers about your store...',
                'maxlength': '1000'
            }),
            'logo': forms.FileInput(attrs={
                'class': 'hidden',
                'accept': 'image/*'
            }),
            'banner': forms.FileInput(attrs={
                'class': 'hidden',
                'accept': 'image/*'
            }),
            'primary_color': forms.TextInput(attrs={
                'type': 'color',
                'class': 'w-20 h-10 border-2 border-gray-300 rounded cursor-pointer'
            }),
            'business_email': forms.EmailInput(attrs={
                'class': 'w-full px-4 py-3 border-2 border-gray-300 rounded-lg focus:ring-2 focus:ring-primary focus:border-primary',
                'placeholder': 'store@example.com'
            }),
            'phone': forms.TextInput(attrs={
                'class': 'w-full px-4 py-3 border-2 border-gray-300 rounded-lg focus:ring-2 focus:ring-primary focus:border-primary',
                'placeholder': '08012345678'
            }),
            'whatsapp': forms.TextInput(attrs={
                'class': 'w-full px-4 py-3 border-2 border-gray-300 rounded-lg focus:ring-2 focus:ring-primary focus:border-primary',
                'placeholder': '08012345678'
            }),
            'address': forms.Textarea(attrs={
                'class': 'w-full px-4 py-3 border-2 border-gray-300 rounded-lg focus:ring-2 focus:ring-primary focus:border-primary',
                'rows': 3,
                'placeholder': 'Store address or pickup location'
            }),
            'instagram': forms.URLInput(attrs={
                'class': 'w-full px-4 py-3 border-2 border-gray-300 rounded-lg focus:ring-2 focus:ring-primary focus:border-primary',
                'placeholder': 'https://instagram.com/yourstore'
            }),
            'facebook': forms.URLInput(attrs={
                'class': 'w-full px-4 py-3 border-2 border-gray-300 rounded-lg focus:ring-2 focus:ring-primary focus:border-primary',
                'placeholder': 'https://facebook.com/yourstore'
            }),
            'twitter': forms.URLInput(attrs={
                'class': 'w-full px-4 py-3 border-2 border-gray-300 rounded-lg focus:ring-2 focus:ring-primary focus:border-primary',
                'placeholder': 'https://twitter.com/yourstore'
            }),
            'shipping_policy': forms.Textarea(attrs={
                'class': 'w-full px-4 py-3 border-2 border-gray-300 rounded-lg focus:ring-2 focus:ring-primary focus:border-primary',
                'rows': 4,
                'placeholder': 'Describe your shipping/delivery policy...'
            }),
            'return_policy': forms.Textarea(attrs={
                'class': 'w-full px-4 py-3 border-2 border-gray-300 rounded-lg focus:ring-2 focus:ring-primary focus:border-primary',
                'rows': 4,
                'placeholder': 'Describe your return/refund policy...'
            }),
        }
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        
        # ✅ SET QUERYSET HERE - when form is instantiated
        self.fields['main_category'].queryset = MainCategory.objects.filter(is_active=True).order_by('sort_order', 'name')
        
        # If editing existing store, enforce store name 1-year lock
        if self.instance and self.instance.pk:
            # Check store name lock
            if not self.instance.can_change_store_name():
                days_left = self.instance.days_until_next_name_change()
                last_changed = self.instance.store_name_last_changed_at.strftime('%B %d, %Y')
                can_change_date = (self.instance.store_name_last_changed_at + timezone.timedelta(days=365)).strftime('%B %d, %Y')
                
                self.fields['store_name'].disabled = True
                self.fields['store_name'].help_text = (
                    f'🔒 Locked for {days_left} more days. '
                    f'Last changed: {last_changed}. '
                    f'Can change again on: {can_change_date}'
                )
            
            # Check category lock
            if self.instance.main_category_locked:
                self.fields['main_category'].disabled = True
                self.fields['main_category'].help_text = '🔒 Locked - Submit a change request to modify'
                del self.fields['confirm_category_lock']
    
    def clean_store_name(self):
        store_name = self.cleaned_data.get('store_name')
        
        # Check if trying to change store name
        if self.instance and self.instance.pk:
            old_store_name = Store.objects.get(pk=self.instance.pk).store_name
            if old_store_name != store_name:
                # Attempting to change store name - enforce 1-year lock
                if not self.instance.can_change_store_name():
                    days_left = self.instance.days_until_next_name_change()
                    last_changed = self.instance.store_name_last_changed_at.strftime('%B %d, %Y')
                    can_change_date = (self.instance.store_name_last_changed_at + timezone.timedelta(days=365)).strftime('%B %d, %Y')
                    
                    raise ValidationError(
                        f'Store name is locked for another {days_left} days. '
                        f'Last changed: {last_changed}. '
                        f'You can change it again on {can_change_date}. '
                        f'Contact support if you need to change it urgently.'
                    )
        
        # Check uniqueness (exclude current instance if editing)
        qs = Store.objects.filter(store_name__iexact=store_name)
        if self.instance and self.instance.pk:
            qs = qs.exclude(pk=self.instance.pk)
        
        if qs.exists():
            raise ValidationError('This store name is already taken. Please choose another.')
        
        return store_name
    
    def clean_logo(self):
        logo = self.cleaned_data.get('logo')
        
        if logo:
            # Check file size (max 5MB)
            if logo.size > 5 * 1024 * 1024:
                raise ValidationError('Logo must be less than 5MB')
            
            # Check file type
            if not logo.content_type in ['image/jpeg', 'image/jpg', 'image/png']:
                raise ValidationError('Only JPG and PNG images are allowed for logo')
        
        return logo
    
    def clean_banner(self):
        banner = self.cleaned_data.get('banner')
        
        if banner:
            # Check file size (max 8MB)
            if banner.size > 8 * 1024 * 1024:
                raise ValidationError('Banner must be less than 8MB')
            
            # Check file type
            if not banner.content_type in ['image/jpeg', 'image/jpg', 'image/png']:
                raise ValidationError('Only JPG and PNG images are allowed for banner')
        
        return banner
    
    def clean_phone(self):
        phone = self.cleaned_data.get('phone')
        
        # Basic Nigerian phone validation
        if phone:
            phone = re.sub(r'[\s\-\(\)]', '', phone)
            if not re.match(r'^(0|\+234)[7-9][0-1]\d{8}$', phone):
                raise ValidationError('Invalid Nigerian phone number format')
        
        return phone
    
    def save(self, commit=True):
        store = super().save(commit=False)
        
        if self.vendor:
            store.vendor = self.vendor
        
        # Track store name changes
        if self.instance and self.instance.pk:
            old_store_name = Store.objects.get(pk=self.instance.pk).store_name
            new_store_name = store.store_name
            
            if old_store_name != new_store_name:
                # Update store name change tracking
                store.store_name_last_changed_at = timezone.now()
                store.store_name_change_count += 1
        else:
            # First time creation - set initial timestamp
            if not store.store_name_last_changed_at:
                store.store_name_last_changed_at = timezone.now()
        
        # Auto-generate slug from store name
        if not store.slug:
            store.slug = slugify(store.store_name)
        
        if commit:
            store.save()
            
            # Lock category if this is first save and checkbox confirmed
            if self.cleaned_data.get('confirm_category_lock') and not store.main_category_locked:
                store.lock_main_category()
        
        return store

# ==========================================
# STORE SETTINGS FORM (WITH 1-YEAR LIMIT)
# ==========================================

class StoreSettingsForm(forms.ModelForm):
    """
    Form for editing store settings
    Enforces 1-year limit on store name changes and main category changes
    """
    
    main_category = forms.ModelChoiceField(
        queryset=None,  # Will be set in __init__
        empty_label='-- Select Main Category --',
        widget=forms.Select(attrs={
            'class': 'w-full px-4 py-3 border-2 border-gray-300 rounded-lg focus:ring-2 focus:ring-primary focus:border-primary transition-all',
            'id': 'id_main_category'
        }),
        help_text='Your product category. Locked for 1 year after each change.'
    )
    
    class Meta:
        model = Store
        fields = [
            'store_name',
            'main_category',
            'tagline', 
            'description',
            'logo',
            'banner',
            'primary_color',
            'business_email',
            'phone',
            'whatsapp',
            'address',
            'instagram',
            'facebook',
            'twitter',
            'shipping_policy',
            'return_policy',
            'is_published',
        ]
        widgets = {
            'store_name': forms.TextInput(attrs={
                'class': 'w-full px-4 py-3 border-2 border-gray-300 rounded-lg focus:ring-2 focus:ring-primary focus:border-primary',
                'placeholder': "e.g., John's Fashion Hub",
                'maxlength': '100'
            }),
            'main_category': forms.Select(attrs={
                'class': 'w-full px-4 py-3 border-2 border-gray-300 rounded-lg focus:ring-2 focus:ring-primary focus:border-primary'
            }),
            'tagline': forms.TextInput(attrs={
                'class': 'w-full px-4 py-3 border-2 border-gray-300 rounded-lg focus:ring-2 focus:ring-primary focus:border-primary',
                'placeholder': 'Short description of your store',
                'maxlength': '150'
            }),
            'description': forms.Textarea(attrs={
                'rows': 5,
                'class': 'w-full px-4 py-3 border-2 border-gray-300 rounded-lg focus:ring-2 focus:ring-primary focus:border-primary',
                'placeholder': 'Tell customers about your store...',
                'maxlength': '1000'
            }),
            'address': forms.Textarea(attrs={
                'rows': 3,
                'class': 'w-full px-4 py-3 border-2 border-gray-300 rounded-lg focus:ring-2 focus:ring-primary focus:border-primary',
                'placeholder': 'Store address or pickup location'
            }),
            'phone': forms.TextInput(attrs={
                'class': 'w-full px-4 py-3 border-2 border-gray-300 rounded-lg focus:ring-2 focus:ring-primary focus:border-primary',
                'placeholder': '08012345678'
            }),
            'business_email': forms.EmailInput(attrs={
                'class': 'w-full px-4 py-3 border-2 border-gray-300 rounded-lg focus:ring-2 focus:ring-primary focus:border-primary',
                'placeholder': 'store@example.com'
            }),
            'whatsapp': forms.TextInput(attrs={
                'class': 'w-full px-4 py-3 border-2 border-gray-300 rounded-lg focus:ring-2 focus:ring-primary focus:border-primary',
                'placeholder': '08012345678'
            }),
            'instagram': forms.URLInput(attrs={
                'class': 'w-full px-4 py-3 border-2 border-gray-300 rounded-lg focus:ring-2 focus:ring-primary focus:border-primary',
                'placeholder': 'https://instagram.com/yourstore'
            }),
            'facebook': forms.URLInput(attrs={
                'class': 'w-full px-4 py-3 border-2 border-gray-300 rounded-lg focus:ring-2 focus:ring-primary focus:border-primary',
                'placeholder': 'https://facebook.com/yourstore'
            }),
            'twitter': forms.URLInput(attrs={
                'class': 'w-full px-4 py-3 border-2 border-gray-300 rounded-lg focus:ring-2 focus:ring-primary focus:border-primary',
                'placeholder': 'https://twitter.com/yourstore'
            }),
            'shipping_policy': forms.Textarea(attrs={
                'rows': 4,
                'class': 'w-full px-4 py-3 border-2 border-gray-300 rounded-lg focus:ring-2 focus:ring-primary focus:border-primary',
                'placeholder': 'Describe your shipping/delivery policy...'
            }),
            'return_policy': forms.Textarea(attrs={
                'rows': 4,
                'class': 'w-full px-4 py-3 border-2 border-gray-300 rounded-lg focus:ring-2 focus:ring-primary focus:border-primary',
                'placeholder': 'Describe your return/refund policy...'
            }),
            'primary_color': forms.TextInput(attrs={
                'type': 'color',
                'class': 'w-20 h-10 border-2 border-gray-300 rounded cursor-pointer'
            }),
            'logo': forms.FileInput(attrs={
                'class': 'hidden',
                'accept': 'image/*'
            }),
            'banner': forms.FileInput(attrs={
                'class': 'hidden',
                'accept': 'image/*'
            }),
        }
    
    def __init__(self, *args, **kwargs):
        self.vendor = kwargs.pop('vendor', None)
        super().__init__(*args, **kwargs)
        
        # ✅ SET MAIN CATEGORY QUERYSET
        self.fields['main_category'].queryset = MainCategory.objects.filter(
            is_active=True
        ).order_by('sort_order', 'name')
        
        # ✅ CHECK IF STORE NAME CAN BE CHANGED
        if self.instance and self.instance.pk:
            # Store name lock check
            if not self.instance.can_change_store_name():
                days_left = self.instance.days_until_next_name_change()
                last_change_date = self.instance.store_name_last_changed_at.strftime('%B %d, %Y')
                
                # Make field read-only
                self.fields['store_name'].widget.attrs.update({
                    'readonly': 'readonly',
                    'class': 'w-full px-4 py-3 border-2 border-gray-300 rounded-lg bg-gray-50 text-gray-500 cursor-not-allowed'
                })
                self.fields['store_name'].help_text = (
                    f'🔒 <span class="text-red-600 font-semibold">Locked until {(self.instance.store_name_last_changed_at + timezone.timedelta(days=365)).strftime("%B %d, %Y")}</span>'
                )
            else:
                self.fields['store_name'].help_text = (
                    '✅ You can change your store name now. '
                    'Note: After changing, you must wait 1 year before changing again.'
                )
            
            # ✅ MAIN CATEGORY LOCK CHECK
            if not self.instance.can_request_category_change():
                days_left = self.instance.days_until_next_category_change()
                last_change_date = self.instance.main_category_last_changed_at.strftime('%B %d, %Y')
                
                # Make field read-only
                self.fields['main_category'].widget.attrs.update({
                    'disabled': 'disabled',
                    'class': 'w-full px-4 py-3 border-2 border-gray-300 rounded-lg bg-gray-50 text-gray-500 cursor-not-allowed'
                })
                self.fields['main_category'].help_text = (
                    f'🔒 <span class="text-red-600 font-semibold">Locked until {(self.instance.main_category_last_changed_at + timezone.timedelta(days=365)).strftime("%B %d, %Y")}</span>'
                )
            else:
                self.fields['main_category'].help_text = (
                    '✅ You can change your main category now. '
                    'Note: After changing, you must wait 1 year before changing again.'
                )
    
    def clean_store_name(self):
        """Validate store name and enforce 1-year limit"""
        store_name = self.cleaned_data.get('store_name')
        
        # ✅ ENFORCE 1-YEAR LIMIT
        if self.instance and self.instance.pk:
            # Check if name is being changed
            if store_name != self.instance.store_name:
                if not self.instance.can_change_store_name():
                    days_left = self.instance.days_until_next_name_change()
                    next_change_date = (
                        self.instance.store_name_last_changed_at + timezone.timedelta(days=365)
                    ).strftime('%B %d, %Y')
                    
                    raise ValidationError(
                        f'🔒 Store name can only be changed once per year. '
                        f'You can change it again on {next_change_date} ({days_left} days remaining).'
                    )
        
        # Check uniqueness (exclude current instance)
        qs = Store.objects.filter(store_name__iexact=store_name)
        if self.instance and self.instance.pk:
            qs = qs.exclude(pk=self.instance.pk)
        
        if qs.exists():
            raise ValidationError(
                'This store name is already taken. Please choose another.'
            )
        
        return store_name
    
    def clean_logo(self):
        """Validate logo file"""
        logo = self.cleaned_data.get('logo')
        
        if logo and hasattr(logo, 'size'):
            # Check file size (max 5MB)
            if logo.size > 5 * 1024 * 1024:
                raise ValidationError('Logo must be less than 5MB')
            
            # Check file type
            content_type = getattr(logo, 'content_type', None)
            if content_type and content_type not in ['image/jpeg', 'image/jpg', 'image/png', 'image/webp']:
                raise ValidationError('Only JPG, PNG and WebP images are allowed for logo')
        
        return logo
    
    def clean_banner(self):
        """Validate banner file"""
        banner = self.cleaned_data.get('banner')
        
        if banner and hasattr(banner, 'size'):
            # Check file size (max 8MB)
            if banner.size > 8 * 1024 * 1024:
                raise ValidationError('Banner must be less than 8MB')
            
            # Check file type
            content_type = getattr(banner, 'content_type', None)
            if content_type and content_type not in ['image/jpeg', 'image/jpg', 'image/png', 'image/webp']:
                raise ValidationError('Only JPG, PNG and WebP images are allowed for banner')
        
        return banner
    
    def clean_main_category(self):
        """Validate main category and enforce 1-year limit"""
        main_category = self.cleaned_data.get('main_category')
        
        # ✅ ENFORCE 1-YEAR CATEGORY LOCK
        if self.instance and self.instance.pk:
            old_category = Store.objects.get(pk=self.instance.pk).main_category
            if old_category != main_category:
                # Attempting to change category
                if not self.instance.can_request_category_change():
                    days_left = self.instance.days_until_next_category_change()
                    last_changed = self.instance.main_category_last_changed_at.strftime('%B %d, %Y')
                    can_change_date = (self.instance.main_category_last_changed_at + timezone.timedelta(days=365)).strftime('%B %d, %Y')
                    
                    raise ValidationError(
                        f'Category is locked for another {days_left} days. '
                        f'Last changed: {last_changed}. '
                        f'You can change it again on {can_change_date}. '
                        f'Contact support if you need to change it urgently.'
                    )
        
        return main_category
    
    def clean_phone(self):
        """Validate phone number"""
        phone = self.cleaned_data.get('phone')
        
        if phone:
            # Remove spaces, dashes, parentheses
            phone = re.sub(r'[\s\-\(\)]', '', phone)
            
            # Basic Nigerian phone validation
            if not re.match(r'^(0|\+234)[7-9][0-1]\d{8}$', phone):
                raise ValidationError('Invalid Nigerian phone number format')
        
        return phone
    
    def clean_whatsapp(self):
        """Validate WhatsApp number"""
        whatsapp = self.cleaned_data.get('whatsapp')
        
        if whatsapp:
            # Remove spaces, dashes, parentheses
            whatsapp = re.sub(r'[\s\-\(\)]', '', whatsapp)
            
            # Basic Nigerian phone validation
            if not re.match(r'^(0|\+234)[7-9][0-1]\d{8}$', whatsapp):
                raise ValidationError('Invalid WhatsApp number format')
        
        return whatsapp
    
    def save(self, commit=True):
        """Save and track store name & category changes"""
        store = super().save(commit=False)
        
        # ✅ CRITICAL: PREVENT STORE NAME CHANGE IF LOCKED (Server-side enforcement)
        if self.instance.pk:
            old_store_name = Store.objects.get(pk=self.instance.pk).store_name
            old_main_category = Store.objects.get(pk=self.instance.pk).main_category
            
            new_store_name = self.cleaned_data.get('store_name')
            new_main_category = self.cleaned_data.get('main_category')
            
            # Handle store name changes
            if old_store_name != new_store_name:
                if not self.instance.can_change_store_name():
                    # ❌ REJECT THE CHANGE - keep old name
                    store.store_name = old_store_name
                    logger.warning(
                        f"🚫 BLOCKED: Attempted to change store name while locked. "
                        f"Store ID: {self.instance.pk}, Attempted: {new_store_name}"
                    )
                else:
                    # ✅ ALLOW - Update tracking
                    store.store_name_last_changed_at = timezone.now()
                    store.store_name_change_count = (self.instance.store_name_change_count or 0) + 1
                    logger.info(
                        f"📝 Store name changed: '{old_store_name}' → '{new_store_name}' "
                        f"(Change #{store.store_name_change_count})"
                    )
            
            # Handle category changes
            if old_main_category != new_main_category:
                if not self.instance.can_request_category_change():
                    # ❌ REJECT THE CHANGE - keep old category
                    store.main_category = old_main_category
                    logger.warning(
                        f"🚫 BLOCKED: Attempted to change category while locked. "
                        f"Store ID: {self.instance.pk}, Attempted: {new_main_category}"
                    )
                else:
                    # ✅ ALLOW - Update tracking
                    store.main_category_last_changed_at = timezone.now()
                    store.main_category_change_count = (self.instance.main_category_change_count or 0) + 1
                    logger.info(
                        f"📝 Category changed: '{old_main_category}' → '{new_main_category}' "
                        f"(Change #{store.main_category_change_count})"
                    )
        
        if commit:
            store.save()
        
        return store
    
# ==========================================
# CATEGORY CHANGE REQUEST FORM (1-YEAR LIMIT)
# ==========================================

class CategoryChangeRequestForm(forms.ModelForm):
    """
    Form for requesting main category change
    Enforces 1-year limit on category change requests
    """
    
    class Meta:
        model = CategoryChangeRequest
        fields = ['requested_category', 'reason']
        widgets = {
            'requested_category': forms.Select(attrs={
                'class': 'w-full px-4 py-3 border-2 border-gray-300 rounded-lg focus:ring-2 focus:ring-primary focus:border-primary'
            }),
            'reason': forms.Textarea(attrs={
                'class': 'w-full px-4 py-3 border-2 border-gray-300 rounded-lg focus:ring-2 focus:ring-primary focus:border-primary',
                'rows': 5,
                'placeholder': 'Please explain in detail why you need to change your main category (minimum 50 characters)'
            })
        }
    
    def __init__(self, *args, **kwargs):
        self.store = kwargs.pop('store', None)
        super().__init__(*args, **kwargs)
        
        # Exclude current category from choices
        if self.store:
            from .models import MainCategory
            self.fields['requested_category'].queryset = MainCategory.objects.filter(
                is_active=True
            ).exclude(id=self.store.main_category.id)
            
            self.fields['requested_category'].empty_label = '-- Select New Category --'
            
            # ✅ CHECK IF CHANGE REQUEST IS ALLOWED
            if not self.store.can_request_category_change():
                days_left = self.store.days_until_next_category_change()
                next_change_date = (
                    self.store.main_category_last_changed_at + timezone.timedelta(days=365)
                ).strftime('%B %d, %Y')
                
                # Disable the form
                self.fields['requested_category'].widget.attrs.update({
                    'disabled': 'disabled',
                    'class': 'w-full px-4 py-3 border-2 border-gray-300 rounded-lg bg-gray-50 text-gray-500 cursor-not-allowed'
                })
                self.fields['requested_category'].help_text = (
                    f'🔒 <span class="text-red-600 font-semibold">Category change requests are limited to once per year.</span><br>'
                    f'You can request a change again on: <strong>{next_change_date}</strong> ({days_left} days remaining)'
                )
                
                self.fields['reason'].widget.attrs.update({
                    'disabled': 'disabled',
                    'class': 'w-full px-4 py-3 border-2 border-gray-300 rounded-lg bg-gray-50 text-gray-500 cursor-not-allowed'
                })
            else:
                self.fields['requested_category'].help_text = (
                    '✅ Select the new category you want to switch to. '
                    'Your request will be reviewed by our admin team.'
                )
    
    def clean(self):
        """Validate category change request"""
        cleaned_data = super().clean()
        
        # ✅ ENFORCE 1-YEAR LIMIT
        if self.store and not self.store.can_request_category_change():
            days_left = self.store.days_until_next_category_change()
            next_change_date = (
                self.store.main_category_last_changed_at + timezone.timedelta(days=365)
            ).strftime('%B %d, %Y')
            
            raise ValidationError(
                f'🔒 Category can only be changed once per year. '
                f'You can request a change again on {next_change_date} ({days_left} days remaining).'
            )
        
        return cleaned_data
    
    def clean_reason(self):
        """Validate reason text"""
        reason = self.cleaned_data.get('reason')
        
        if not reason or len(reason.strip()) < 50:
            raise ValidationError(
                'Please provide a detailed reason for the category change (at least 50 characters). '
                'Explain why your current category is not suitable and how the new category better fits your business.'
            )
        
        # Check for spam/generic reasons
        generic_phrases = [
            'want to change',
            'need to change',
            'please approve',
            'i want',
            'test',
        ]
        
        reason_lower = reason.lower()
        if any(phrase in reason_lower for phrase in generic_phrases) and len(reason) < 100:
            raise ValidationError(
                'Please provide a more detailed explanation. Generic reasons may be rejected. '
                'Explain your specific business needs and why the category change is necessary.'
            )
        
        return reason
    
    def save(self, commit=True):
        """Save category change request"""
        request = super().save(commit=False)
        
        if self.store:
            request.store = self.store
            request.current_category = self.store.main_category
            request.status = 'pending'
        
        if commit:
            request.save()
            
            import logging
            logger = logging.getLogger(__name__)
            logger.info(
                f"📋 Category change request submitted: {self.store.store_name} "
                f"({self.store.main_category.name} → {request.requested_category.name})"
            )
        
        return request


# ==========================================
# HELPER FUNCTION FOR DISPLAYING LIMITS
# ==========================================

def get_change_limit_message(store, field_type='store_name'):
    """
    Helper function to generate user-friendly messages about change limits
    
    Args:
        store: Store instance
        field_type: 'store_name' or 'category'
    
    Returns:
        dict with 'can_change', 'days_left', 'next_change_date', 'message'
    """
    if field_type == 'store_name':
        can_change = store.can_change_store_name()
        days_left = store.days_until_next_name_change()
        last_changed = store.store_name_last_changed_at
    else:  # category
        can_change = store.can_request_category_change()
        days_left = store.days_until_next_category_change()
        last_changed = store.main_category_last_changed_at
    
    if can_change:
        return {
            'can_change': True,
            'days_left': 0,
            'next_change_date': None,
            'message': f'✅ You can change your {field_type.replace("_", " ")} now.',
            'css_class': 'text-green-600'
        }
    else:
        next_change_date = (last_changed + timezone.timedelta(days=365)).strftime('%B %d, %Y')
        return {
            'can_change': False,
            'days_left': days_left,
            'next_change_date': next_change_date,
            'message': f'🔒 Can change on {next_change_date} ({days_left} days remaining)',
            'css_class': 'text-red-600'
        }
    

# ==========================================
# PRODUCT FORM (Dynamic Attributes)
# ==========================================

class ProductForm(forms.ModelForm):
    """
    Dynamic product form that loads category-specific fields
    Store's main category is locked, only subcategories within that category shown
    """
    
    class Meta:
        model = Product
        fields = [
            'title', 'subcategory', 'description',
            'price', 'compare_at_price', 
            'stock_quantity', 'low_stock_threshold', 'track_inventory',
            'sku', 'status'
        ]
        widgets = {
            'title': forms.TextInput(attrs={
                'class': 'w-full px-4 py-3 border-2 border-gray-300 rounded-lg focus:ring-2 focus:ring-primary focus:border-primary',
                'placeholder': 'e.g., iPhone 13 Pro Max 256GB',
                'maxlength': '200'
            }),
            'subcategory': forms.Select(attrs={
                'class': 'w-full px-4 py-3 border-2 border-gray-300 rounded-lg focus:ring-2 focus:ring-primary focus:border-primary',
                'id': 'id_subcategory'
            }),
            'description': forms.Textarea(attrs={
                'class': 'w-full px-4 py-3 border-2 border-gray-300 rounded-lg focus:ring-2 focus:ring-primary focus:border-primary',
                'rows': 5,
                'placeholder': 'Describe your product in detail...'
            }),
            'price': forms.NumberInput(attrs={
                'class': 'w-full px-4 py-3 border-2 border-gray-300 rounded-lg focus:ring-2 focus:ring-primary focus:border-primary',
                'placeholder': '0.00',
                'step': '0.01',
                'min': '0.01'
            }),
            'compare_at_price': forms.NumberInput(attrs={
                'class': 'w-full px-4 py-3 border-2 border-gray-300 rounded-lg focus:ring-2 focus:ring-primary focus:border-primary',
                'placeholder': '0.00 (optional)',
                'step': '0.01'
            }),
            'sku': forms.TextInput(attrs={
                'class': 'w-full px-4 py-3 border-2 border-gray-300 rounded-lg focus:ring-2 focus:ring-primary focus:border-primary',
                'placeholder': 'Optional SKU'
            }),
            'status': forms.Select(attrs={
                'class': 'w-full px-4 py-3 border-2 border-gray-300 rounded-lg focus:ring-2 focus:ring-primary focus:border-primary'
            }),
            'stock_quantity': forms.NumberInput(attrs={
                'class': 'w-full px-4 py-3 border-2 border-gray-300 rounded-lg focus:ring-2 focus:ring-primary focus:border-primary',
                'min': '0',
                'placeholder': 'Available stock quantity'
            }),
            'low_stock_threshold': forms.NumberInput(attrs={
                'class': 'w-full px-4 py-3 border-2 border-gray-300 rounded-lg focus:ring-2 focus:ring-primary focus:border-primary',
                'min': '1',
                'value': '5',
                'placeholder': 'Alert threshold'
            }),
            'track_inventory': forms.CheckboxInput(attrs={
                'class': 'w-4 h-4 text-primary border-gray-300 rounded focus:ring-primary'
            }),
        }
        
    
    def __init__(self, *args, **kwargs):
        self.vendor = kwargs.pop('vendor', None)
        self.subcategory_id = kwargs.pop('subcategory_id', None)
        self.is_editing = kwargs.pop('is_editing', False)  # ✅ NEW: Track if editing
        super().__init__(*args, **kwargs)

        # ✅ CRITICAL: Set is_editing based on instance
        if self.instance and self.instance.pk:
            self.is_editing = True

        # Filter subcategories to ONLY vendor's main category
        if self.vendor and hasattr(self.vendor, 'store'):
            self.fields['subcategory'].queryset = SubCategory.objects.filter(
                main_category=self.vendor.store.main_category,
                is_active=True
            ).order_by('name')
            self.fields['subcategory'].empty_label = '-- Select Subcategory --'

        # ✅ CONFIGURE STATUS FIELD BASED ON CREATE VS EDIT
        if self.is_editing:
            # EDITING: Allow Draft, Published, Discontinued
            self.fields['status'].choices = [
                ('draft', 'Save as Draft'),
                ('published', 'Publish'),
                ('discontinued', 'Discontinued'),
            ]
        else:
            # CREATING: Only Draft and Published
            self.fields['status'].choices = [
                ('draft', 'Save as Draft'),
                ('published', 'Publish'),
            ]

        # Determine the subcategory to load dynamic fields for
        subcategory = None

        if self.instance and getattr(self.instance, 'pk', None):
            subcategory = self.instance.subcategory
        else:
            # Try POST data first, then initial
            subcategory = self.data.get('subcategory') or self.initial.get('subcategory')

        if subcategory:
            # Ensure we have a SubCategory instance
            if not isinstance(subcategory, SubCategory):
                subcategory = SubCategory.objects.filter(id=subcategory).first()

        # Always attempt to add dynamic fields (safe if subcategory is None)
        self._add_dynamic_fields(subcategory)
    
    def _add_dynamic_fields(self, subcategory):
        from apps.vendors.models import SubCategoryAttribute

        if not subcategory:
            return

        attributes = (
            SubCategoryAttribute.objects
            .filter(subcategory=subcategory, is_active=True)
            .order_by('sort_order')
        )

        for attr in attributes:
            field_name = f"attr_{attr.id}"

            # Normalize options
            options = []
            if attr.options:
                if isinstance(attr.options, list):
                    options = attr.options
                elif isinstance(attr.options, str):
                    options = [o.strip() for o in attr.options.split(',') if o.strip()]

            # Fetch saved value using ATTRIBUTE ID
            initial_value = None
            if self.instance.pk and self.instance.attributes:
                initial_value = self.instance.attributes.get(str(attr.id))

            # Field creation
            if attr.field_type == 'dropdown':
                self.fields[field_name] = forms.ChoiceField(
                    choices=[('', '-- Select --')] + [(o, o) for o in options],
                    required=attr.is_required,
                    label=attr.name
                )

            elif attr.field_type == 'number':
                self.fields[field_name] = forms.IntegerField(
                    required=attr.is_required,
                    label=attr.name
                )

            elif attr.field_type == 'textarea':
                self.fields[field_name] = forms.CharField(
                    widget=forms.Textarea(attrs={'rows': 3}),
                    required=attr.is_required,
                    label=attr.name
                )

            elif attr.field_type == 'checkbox':
                self.fields[field_name] = forms.BooleanField(
                    required=False,
                    label=attr.name
                )

            else:
                self.fields[field_name] = forms.CharField(
                    required=attr.is_required,
                    label=attr.name
                )

            # ✅ CRITICAL FIX: manually inject initial value
            if self.instance.pk and initial_value is not None:
                if attr.field_type == 'checkbox':
                    self.initial[field_name] = str(initial_value).lower() == 'true'
                else:
                    self.initial[field_name] = initial_value
    
    def clean(self):
        cleaned_data = super().clean()

        status = cleaned_data.get('status')
        print(f"DEBUG: Status value = {status}")
        print(f"DEBUG: Is editing = {self.is_editing}")
        
        # Validate compare_at_price > price
        price = cleaned_data.get('price')
        compare_price = cleaned_data.get('compare_at_price')
        
        if compare_price and price and compare_price <= price:
            raise ValidationError({
                'compare_at_price': 'Compare at price must be greater than selling price'
            })
        
        # ✅ CRITICAL: Prevent discontinued status on NEW products
        status = cleaned_data.get('status')
        if not self.is_editing and status == 'discontinued':
            raise ValidationError({
                'status': 'You cannot set a new product as discontinued. Products can only be discontinued after creation.'
            })
        
        # Validate required dynamic attributes manually
        for field_name, field in self.fields.items():
            if field_name.startswith('attr_'):
                value = cleaned_data.get(field_name)
                if field.required and (value is None or value == ''):
                    self.add_error(field_name, f"{field.label} is required.")
        
        return cleaned_data
    
    def save(self, commit=True):
        instance = super().save(commit=False)

        # Attach vendor/store if provided
        if hasattr(self, 'vendor') and self.vendor:
            instance.vendor = self.vendor
            instance.store = self.vendor.store

        # Collect dynamic attributes from form fields (use attr id strings as keys)
        attributes = {}
        for name, field in self.fields.items():
            if name.startswith('attr_'):
                value = self.cleaned_data.get(name)
                # field name is 'attr_<id>' - store under the id as a string
                try:
                    attr_id = name.split('_', 1)[1]
                except Exception:
                    attr_id = name
                attributes[str(attr_id)] = value

        instance.attributes = attributes

        if commit:
            instance.save()

        return instance
        

# ==========================================
# PRODUCT IMAGE FORMSET
# ==========================================

class ProductImageForm(forms.ModelForm):
    """Form for individual product images"""
    
    class Meta:
        model = ProductImage
        fields = ['image', 'alt_text', 'is_primary', 'sort_order']
        widgets = {
            'image': forms.FileInput(attrs={
                'class': 'hidden',
                'accept': 'image/*'
            }),
            'alt_text': forms.TextInput(attrs={
                'class': 'w-full px-3 py-2 border border-gray-300 rounded-lg text-sm',
                'placeholder': 'Image description (optional)'
            }),
            'is_primary': forms.CheckboxInput(attrs={
                'class': 'w-4 h-4 text-primary border-gray-300 rounded focus:ring-primary'
            }),
            'sort_order': forms.NumberInput(attrs={
                'class': 'w-20 px-3 py-2 border border-gray-300 rounded-lg text-sm',
                'min': '0'
            })
        }
    
    def clean_image(self):
        image = self.cleaned_data.get('image')
        
        # Only validate if it's a new upload (has size attribute and is FieldFile)
        if image and hasattr(image, 'size'):
            # Check file size (max 5MB)
            if image.size > 5 * 1024 * 1024:
                raise ValidationError('Image must be less than 5MB')
            
            # Check file type using name extension or content_type if available
            filename = image.name.lower() if hasattr(image, 'name') else ''
            valid_extensions = ('.jpg', '.jpeg', '.png', '.webp')
            
            # First check by extension
            has_valid_ext = filename.endswith(valid_extensions)
            
            # Then check content_type if available (for new uploads)
            has_valid_content_type = True
            if hasattr(image, 'content_type'):
                has_valid_content_type = image.content_type in ['image/jpeg', 'image/jpg', 'image/png', 'image/webp']
            
            if not (has_valid_ext or has_valid_content_type):
                raise ValidationError('Only JPG, PNG and WebP images are allowed')
        
        return image



class ProductImageBaseFormSet(BaseInlineFormSet):
    """Custom base formset to validate 3-5 images"""
    
    def clean(self):
        super().clean()
        
        if any(self.errors):
            return
        
        # Count non-empty, non-deleted images
        image_count = 0
        for form in self.forms:
            if form.cleaned_data and not form.cleaned_data.get('DELETE'):
                if form.cleaned_data.get('image'):
                    image_count += 1
        
        # ✅ VALIDATE 3-5 IMAGES
        if image_count < 3:
            raise ValidationError(
                f'âŒ Minimum 3 images required. You uploaded {image_count}. '
                f'Please add {3 - image_count} more image(s).'
            )
        
        if image_count > 5:
            raise ValidationError(
                f'âŒ Maximum 5 images allowed. You uploaded {image_count}. '
                f'Please remove {image_count - 5} image(s).'
            )
        
        # ✅ ENSURE ONE PRIMARY IMAGE
        primary_count = sum(
            1 for form in self.forms 
            if form.cleaned_data and not form.cleaned_data.get('DELETE') 
            and form.cleaned_data.get('is_primary')
        )
        
        if image_count > 0 and primary_count == 0:
            # Auto-set first image as primary
            for form in self.forms:
                if form.cleaned_data and form.cleaned_data.get('image'):
                    form.cleaned_data['is_primary'] = True
                    break
        
        if primary_count > 1:
            raise ValidationError('âŒ Only one image can be set as primary.')


# Create an inline formset factory that binds Product -> ProductImage
# so the resulting formset class has the required `fk` attribute and can
# be instantiated in views as `ProductImageFormSet(...)`.
ProductImageFormSet = inlineformset_factory(
    Product,
    ProductImage,
    form=ProductImageForm,
    formset=ProductImageBaseFormSet,
    extra=0,  # No automatic extra forms
    can_delete=True,
    min_num=0,  # Allow 0 images temporarily
    validate_min=False,  # Don't enforce minimum on formset level
)


# ==========================================
# ORDER UPDATE FORM
# ==========================================

class OrderStatusUpdateForm(forms.ModelForm):
    """Vendor updates order status"""
    
    class Meta:
        model = Order
        fields = ['status', 'tracking_number', 'vendor_note']
        widgets = {
            'status': forms.Select(attrs={'class': 'form-select'}),
            'tracking_number': forms.TextInput(attrs={
                'class': 'form-input',
                'placeholder': 'Enter tracking number'
            }),
            'vendor_note': forms.Textarea(attrs={
                'class': 'form-textarea',
                'rows': 3,
                'placeholder': 'Add notes for customer (optional)'
            })
        }
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        
        # Limit status choices based on current status
        current_status = self.instance.status if self.instance else 'pending'
        
        # Define allowed transitions
        if current_status == 'pending':
            allowed_statuses = [('confirmed', 'Confirmed'), ('cancelled', 'Cancelled')]
        elif current_status == 'confirmed':
            allowed_statuses = [('processing', 'Processing'), ('cancelled', 'Cancelled')]
        elif current_status == 'processing':
            allowed_statuses = [('shipped', 'Shipped')]
        elif current_status == 'shipped':
            allowed_statuses = [('delivered', 'Delivered')]
        else:
            allowed_statuses = [(current_status, self.instance.get_status_display())]
        
        self.fields['status'].choices = allowed_statuses
    
    def clean(self):
        cleaned_data = super().clean()
        status = cleaned_data.get('status')
        tracking_number = cleaned_data.get('tracking_number')
        
        # Require tracking number if shipping
        if status == 'shipped' and not tracking_number:
            raise ValidationError({
                'tracking_number': 'Tracking number is required when marking order as shipped'
            })
        
        return cleaned_data

