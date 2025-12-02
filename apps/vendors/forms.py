"""
Vendor App Forms
All forms for verification, store setup, products, etc.
"""

from django import forms
from django.core.exceptions import ValidationError
from django.core.validators import RegexValidator
from django.utils.text import slugify
from .models import (
    VendorProfile, Store, Product, ProductImage, 
    MainCategory, SubCategory, SubCategoryAttribute,
    CategoryChangeRequest, Order
)
import re


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
                'placeholder': 'e.g., CSC/2020/1234'
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
            raise ValidationError('Invalid matric number format. Expected format: ABC/2020/1234')
        
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
    
    main_category = forms.ModelChoiceField(
        queryset=MainCategory.objects.filter(is_active=True),
        empty_label='-- Select Main Category --',
        widget=forms.Select(attrs={
            'class': 'form-select',
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
                'class': 'form-input',
                'placeholder': "e.g., John's Fashion Hub",
                'maxlength': '100'
            }),
            'tagline': forms.TextInput(attrs={
                'class': 'form-input',
                'placeholder': 'Short description of your store',
                'maxlength': '150'
            }),
            'description': forms.Textarea(attrs={
                'class': 'form-textarea',
                'rows': 4,
                'placeholder': 'Tell customers about your store...',
                'maxlength': '1000'
            }),
            'logo': forms.FileInput(attrs={
                'class': 'form-file',
                'accept': 'image/*'
            }),
            'banner': forms.FileInput(attrs={
                'class': 'form-file',
                'accept': 'image/*'
            }),
            'primary_color': forms.TextInput(attrs={
                'type': 'color',
                'class': 'form-color'
            }),
            'business_email': forms.EmailInput(attrs={
                'class': 'form-input',
                'placeholder': 'store@example.com'
            }),
            'phone': forms.TextInput(attrs={
                'class': 'form-input',
                'placeholder': '08012345678'
            }),
            'whatsapp': forms.TextInput(attrs={
                'class': 'form-input',
                'placeholder': '08012345678'
            }),
            'address': forms.Textarea(attrs={
                'class': 'form-textarea',
                'rows': 3,
                'placeholder': 'Store address or pickup location'
            }),
            'instagram': forms.URLInput(attrs={
                'class': 'form-input',
                'placeholder': 'https://instagram.com/yourstore'
            }),
            'facebook': forms.URLInput(attrs={
                'class': 'form-input',
                'placeholder': 'https://facebook.com/yourstore'
            }),
            'twitter': forms.URLInput(attrs={
                'class': 'form-input',
                'placeholder': 'https://twitter.com/yourstore'
            }),
            'shipping_policy': forms.Textarea(attrs={
                'class': 'form-textarea',
                'rows': 4,
                'placeholder': 'Describe your shipping/delivery policy...'
            }),
            'return_policy': forms.Textarea(attrs={
                'class': 'form-textarea',
                'rows': 4,
                'placeholder': 'Describe your return/refund policy...'
            }),
        }
    
    def __init__(self, *args, **kwargs):
        self.vendor = kwargs.pop('vendor', None)
        super().__init__(*args, **kwargs)
        
        # If editing existing store, hide category lock checkbox
        if self.instance and self.instance.pk:
            if self.instance.main_category_locked:
                self.fields['main_category'].disabled = True
                self.fields['main_category'].help_text = '🔒 Locked - Submit a change request to modify'
                del self.fields['confirm_category_lock']
    
    def clean_store_name(self):
        store_name = self.cleaned_data.get('store_name')
        
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
# PRODUCT FORM (Dynamic Attributes)
# ==========================================

class ProductForm(forms.ModelForm):
    """
    Dynamic product form that loads category-specific fields
    """
    
    class Meta:
        model = Product
        fields = [
            'title', 'subcategory', 'description',
            'price', 'compare_at_price', 'quantity', 'sku',
            'status'
        ]
        widgets = {
            'title': forms.TextInput(attrs={
                'class': 'form-input',
                'placeholder': 'Product title',
                'maxlength': '200'
            }),
            'subcategory': forms.Select(attrs={
                'class': 'form-select',
                'id': 'id_subcategory'
            }),
            'description': forms.Textarea(attrs={
                'class': 'form-textarea',
                'rows': 5,
                'placeholder': 'Describe your product...'
            }),
            'price': forms.NumberInput(attrs={
                'class': 'form-input',
                'placeholder': '0.00',
                'step': '0.01',
                'min': '0.01'
            }),
            'compare_at_price': forms.NumberInput(attrs={
                'class': 'form-input',
                'placeholder': '0.00 (optional)',
                'step': '0.01'
            }),
            'quantity': forms.NumberInput(attrs={
                'class': 'form-input',
                'min': '0'
            }),
            'sku': forms.TextInput(attrs={
                'class': 'form-input',
                'placeholder': 'Optional SKU'
            }),
            'status': forms.Select(attrs={
                'class': 'form-select'
            })
        }
    
    def __init__(self, *args, **kwargs):
        self.vendor = kwargs.pop('vendor', None)
        self.subcategory_id = kwargs.pop('subcategory_id', None)
        super().__init__(*args, **kwargs)
        
        # Filter subcategories to only vendor's main category
        if self.vendor and hasattr(self.vendor, 'store'):
            self.fields['subcategory'].queryset = SubCategory.objects.filter(
                main_category=self.vendor.store.main_category,
                is_active=True
            )
            self.fields['subcategory'].help_text = f"Only {self.vendor.store.main_category.name} subcategories"
        
        # Add dynamic fields based on selected subcategory
        if self.instance and self.instance.pk and self.instance.subcategory:
            self._add_dynamic_fields(self.instance.subcategory)
        elif self.subcategory_id:
            try:
                subcategory = SubCategory.objects.get(id=self.subcategory_id)
                self._add_dynamic_fields(subcategory)
            except SubCategory.DoesNotExist:
                pass
    
    def _add_dynamic_fields(self, subcategory):
        """Add category-specific attribute fields dynamically"""
        attributes = SubCategoryAttribute.objects.filter(
            subcategory=subcategory,
            is_active=True
        ).order_by('sort_order')
        
        for attr in attributes:
            field_name = f'attr_{attr.id}'
            
            # Get existing value if editing
            initial_value = None
            if self.instance and self.instance.attributes:
                initial_value = self.instance.attributes.get(attr.name)
            
            # Create field based on type
            if attr.field_type == 'text':
                self.fields[field_name] = forms.CharField(
                    label=attr.name,
                    required=attr.is_required,
                    initial=initial_value,
                    widget=forms.TextInput(attrs={
                        'class': 'form-input',
                        'placeholder': attr.placeholder or f'Enter {attr.name}'
                    }),
                    help_text=attr.help_text
                )
            
            elif attr.field_type == 'number':
                self.fields[field_name] = forms.IntegerField(
                    label=attr.name,
                    required=attr.is_required,
                    initial=initial_value,
                    min_value=attr.min_value,
                    max_value=attr.max_value,
                    widget=forms.NumberInput(attrs={
                        'class': 'form-input',
                        'placeholder': attr.placeholder
                    }),
                    help_text=attr.help_text
                )
            
            elif attr.field_type == 'dropdown':
                choices = [('', f'-- Select {attr.name} --')] + [(opt, opt) for opt in attr.options]
                self.fields[field_name] = forms.ChoiceField(
                    label=attr.name,
                    required=attr.is_required,
                    choices=choices,
                    initial=initial_value,
                    widget=forms.Select(attrs={'class': 'form-select'}),
                    help_text=attr.help_text
                )
            
            elif attr.field_type == 'textarea':
                self.fields[field_name] = forms.CharField(
                    label=attr.name,
                    required=attr.is_required,
                    initial=initial_value,
                    widget=forms.Textarea(attrs={
                        'class': 'form-textarea',
                        'rows': 3,
                        'placeholder': attr.placeholder
                    }),
                    help_text=attr.help_text
                )
            
            elif attr.field_type == 'checkbox':
                self.fields[field_name] = forms.BooleanField(
                    label=attr.name,
                    required=attr.is_required,
                    initial=initial_value == 'True' or initial_value == True,
                    widget=forms.CheckboxInput(attrs={'class': 'form-checkbox'}),
                    help_text=attr.help_text
                )
    
    def clean(self):
        cleaned_data = super().clean()
        
        # Validate compare_at_price > price
        price = cleaned_data.get('price')
        compare_price = cleaned_data.get('compare_at_price')
        
        if compare_price and price and compare_price <= price:
            raise ValidationError({
                'compare_at_price': 'Compare at price must be greater than selling price'
            })
        
        return cleaned_data
    
    def save(self, commit=True):
        product = super().save(commit=False)
        
        if self.vendor:
            product.vendor = self.vendor
            product.store = self.vendor.store
        
        # Save dynamic attributes to JSON field
        attributes = {}
        for field_name, value in self.cleaned_data.items():
            if field_name.startswith('attr_'):
                attr_id = int(field_name.replace('attr_', ''))
                try:
                    attr = SubCategoryAttribute.objects.get(id=attr_id)
                    # Convert boolean to string for consistency
                    if isinstance(value, bool):
                        value = str(value)
                    attributes[attr.name] = value
                except SubCategoryAttribute.DoesNotExist:
                    pass
        
        product.attributes = attributes
        
        if commit:
            product.save()
        
        return product


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
                'class': 'form-file',
                'accept': 'image/*'
            }),
            'alt_text': forms.TextInput(attrs={
                'class': 'form-input',
                'placeholder': 'Image description'
            }),
            'is_primary': forms.CheckboxInput(attrs={
                'class': 'form-checkbox'
            }),
            'sort_order': forms.NumberInput(attrs={
                'class': 'form-input',
                'min': '0'
            })
        }
    
    def clean_image(self):
        image = self.cleaned_data.get('image')
        
        if image:
            # Check file size (max 5MB)
            if image.size > 5 * 1024 * 1024:
                raise ValidationError('Image must be less than 5MB')
            
            # Check file type
            if not image.content_type in ['image/jpeg', 'image/jpg', 'image/png']:
                raise ValidationError('Only JPG and PNG images are allowed')
        
        return image


# Formset for multiple images
from django.forms import inlineformset_factory

ProductImageFormSet = inlineformset_factory(
    Product,
    ProductImage,
    form=ProductImageForm,
    extra=3,
    max_num=5,
    can_delete=True
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


# ==========================================
# CATEGORY CHANGE REQUEST FORM
# ==========================================

class CategoryChangeRequestForm(forms.ModelForm):
    """Vendor requests to change locked main category"""
    
    class Meta:
        model = CategoryChangeRequest
        fields = ['requested_category', 'reason']
        widgets = {
            'requested_category': forms.Select(attrs={
                'class': 'form-select'
            }),
            'reason': forms.Textarea(attrs={
                'class': 'form-textarea',
                'rows': 5,
                'placeholder': 'Please explain why you need to change your main category (minimum 50 characters)'
            })
        }
    
    def __init__(self, *args, **kwargs):
        self.store = kwargs.pop('store', None)
        super().__init__(*args, **kwargs)
        
        # Exclude current category from choices
        if self.store:
            self.fields['requested_category'].queryset = MainCategory.objects.filter(
                is_active=True
            ).exclude(id=self.store.main_category.id)
    
    def clean_reason(self):
        reason = self.cleaned_data.get('reason')
        
        if len(reason) < 50:
            raise ValidationError('Please provide a detailed reason (at least 50 characters)')
        
        return reason
    
    def save(self, commit=True):
        request = super().save(commit=False)
        
        if self.store:
            request.store = self.store
            request.current_category = self.store.main_category
        
        if commit:
            request.save()
        
        return request