"""
Vendor App Forms
All forms for verification, store setup, products, etc.

CHANGED IN THIS VERSION:
- DELETED: NINEntryForm, NINOTPForm, BVNOTPForm, old BVNEntryForm
- ADDED: BVNVerificationForm (single-screen BVN + live selfie verification,
  replaces the old OTP-based verification flow)

Everything else (StudentVerificationForm, StoreSetupForm, StoreSettingsForm,
CategoryChangeRequestForm, ProductForm, ProductImageForm, etc.) is UNCHANGED.
"""

from django import forms
from django.core.exceptions import ValidationError
from django.core.validators import RegexValidator
from django.utils.text import slugify
from django.utils import timezone
from django.db import models
from django.db.models import Q
from django.forms import inlineformset_factory, BaseInlineFormSet
from .models import (
    VendorProfile, Store, Product, ProductImage,
    MainCategory, SubCategory, SubCategoryAttribute,
    CategoryChangeRequest
)
import re
import logging

logger = logging.getLogger(__name__)


# ==========================================
# BVN VERIFICATION FORMS (2-step flow)
# Step 1: BVN + consent
# Step 2: live selfie capture (auto-submitted)
# ==========================================

class BVNEntryForm(forms.Form):
    """Page 1 — BVN number and consent only."""

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
            RegexValidator(regex=r'^\d{11}$', message='BVN must be exactly 11 digits')
        ]
    )

    consent = forms.BooleanField(
        required=True,
        label='I consent to KasuMarketplace collecting and submitting my BVN to Dojah for identity verification purposes.',
        error_messages={'required': 'You must consent to BVN collection to proceed with verification.'}
    )

    def clean_bvn_number(self):
        bvn = self.cleaned_data.get('bvn_number')
        return re.sub(r'[\s\-]', '', bvn)

class BVNSelfieForm(forms.Form):
    """Page 2 — selfie only; BVN comes from session."""

    selfie_image = forms.CharField(
        widget=forms.HiddenInput(),
        label='Selfie capture',
        error_messages={'required': 'Please capture a selfie before submitting.'}
    )

    def clean_selfie_image(self):
        data = self.cleaned_data.get('selfie_image', '')
        if not data or len(data) < 1000:
            raise ValidationError('Selfie capture failed or is incomplete. Please try again.')
        return data


class BVNVerificationForm(forms.Form):
    """
    Legacy combined form — kept for backwards compatibility if needed.
    Prefer BVNEntryForm + BVNSelfieForm for the 2-page flow.
    """

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
            RegexValidator(regex=r'^\d{11}$', message='BVN must be exactly 11 digits')
        ]
    )

    selfie_image = forms.CharField(
        widget=forms.HiddenInput(),
        label='Selfie capture',
        error_messages={'required': 'Please capture a selfie before submitting.'}
    )

    def clean_bvn_number(self):
        bvn = self.cleaned_data.get('bvn_number')
        bvn = re.sub(r'[\s\-]', '', bvn)
        return bvn

    def clean_selfie_image(self):
        data = self.cleaned_data.get('selfie_image', '')
        # A real base64-encoded JPEG selfie is always several thousand
        # characters long. A short string here means the camera capture
        # didn't actually fire (e.g. JS failed silently, or the hidden
        # field was submitted empty/with a placeholder).
        if not data or len(data) < 1000:
            raise ValidationError('Selfie capture failed or is incomplete. Please try again.')
        return data


# ==========================================
# STORE SETUP FORM (UNCHANGED)
# ==========================================

class StoreSetupForm(forms.ModelForm):
    """
    Store creation form — minimal fields for quick store setup.
    """

    main_category = forms.ModelChoiceField(
        queryset=None,
        empty_label='-- Select Main Category --',
        widget=forms.Select(attrs={
            'class': 'w-full px-4 py-3 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary focus:border-primary transition-all text-sm',
            'id': 'id_main_category'
        }),
    )

    class Meta:
        model = Store
        fields = [
            'store_name', 'description', 'main_category',
            'business_email', 'phone', 'whatsapp', 'state', 'city',
            'latitude', 'longitude',
        ]
        widgets = {
            'store_name': forms.TextInput(attrs={
                'class': 'w-full px-4 py-3 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary focus:border-primary text-sm',
                'placeholder': "e.g. Tech Haven, Fashion Palace",
                'maxlength': '100'
            }),
            'description': forms.Textarea(attrs={
                'class': 'w-full px-4 py-3 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary focus:border-primary text-sm resize-none',
                'rows': 3,
                'placeholder': 'What do you sell?',
                'maxlength': '1000'
            }),
            'business_email': forms.EmailInput(attrs={
                'class': 'w-full px-4 py-3 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary focus:border-primary text-sm',
                'placeholder': 'store@example.com'
            }),
            'phone': forms.TextInput(attrs={
                'class': 'w-full px-4 py-3 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary focus:border-primary text-sm',
                'placeholder': '08012345678'
            }),
            'whatsapp': forms.TextInput(attrs={
                'class': 'w-full px-4 py-3 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary focus:border-primary text-sm',
                'placeholder': '08012345678'
            }),
            'state': forms.TextInput(attrs={
                'class': 'w-full px-4 py-3 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary focus:border-primary text-sm',
                'placeholder': 'e.g. Kaduna',
                'maxlength': '100'
            }),
            'city': forms.TextInput(attrs={
                'class': 'w-full px-4 py-3 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary focus:border-primary text-sm',
                'placeholder': 'e.g. Kawo',
                'maxlength': '100'
            }),
            'latitude': forms.HiddenInput(),
            'longitude': forms.HiddenInput(),
        }

    def __init__(self, *args, **kwargs):
        self.vendor = kwargs.pop('vendor', None)
        super().__init__(*args, **kwargs)

        self.fields['main_category'].queryset = MainCategory.objects.filter(
            is_active=True
        ).order_by('sort_order', 'name')

        self.fields['business_email'].required = False
        self.fields['latitude'].required = True
        self.fields['longitude'].required = True

    def _clean_nigerian_phone(self, value, field_name):
        if not value:
            raise ValidationError('This field is required.')
        value = re.sub(r'[\s\-\(\)]', '', value)
        if not re.match(r'^0[7-9][0-1]\d{8}$', value):
            raise ValidationError('Invalid phone number')
        return value

    def clean_store_name(self):
        store_name = self.cleaned_data.get('store_name')
        if not store_name or not store_name.strip():
            raise ValidationError('This field is required.')
        qs = Store.objects.filter(store_name__iexact=store_name.strip())
        if self.instance and self.instance.pk:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise ValidationError('This store name is already taken.')
        return store_name.strip()

    def clean_description(self):
        description = self.cleaned_data.get('description')
        if not description or not description.strip():
            raise ValidationError('This field is required.')
        return description.strip()

    def clean_phone(self):
        return self._clean_nigerian_phone(self.cleaned_data.get('phone'), 'phone')

    def clean_whatsapp(self):
        return self._clean_nigerian_phone(self.cleaned_data.get('whatsapp'), 'whatsapp')

    def clean_state(self):
        state = self.cleaned_data.get('state')
        if not state or not state.strip():
            raise ValidationError('This field is required.')
        return state.strip()

    def clean_city(self):
        city = self.cleaned_data.get('city')
        if not city or not city.strip():
            raise ValidationError('This field is required.')
        return city.strip()

    def clean_latitude(self):
        lat = self.cleaned_data.get('latitude')
        if lat is None or lat == '':
            raise ValidationError('Please capture your location')
        return lat

    def clean_longitude(self):
        lon = self.cleaned_data.get('longitude')
        if lon is None or lon == '':
            raise ValidationError('Please capture your location')
        return lon

    def save(self, commit=True):
        store = super().save(commit=False)

        if self.vendor:
            store.vendor = self.vendor

        if not store.store_name_last_changed_at:
            store.store_name_last_changed_at = timezone.now()

        if not store.slug:
            store.slug = slugify(store.store_name)

        if commit:
            store.save()
            if not store.main_category_locked:
                store.lock_main_category()

        return store

# ==========================================
# STORE SETTINGS FORM (UNCHANGED, WITH 1-YEAR LIMIT)
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
            'state',
            'city',
            'latitude',
            'longitude',
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
            'state': forms.TextInput(attrs={
                'class': 'w-full px-4 py-3 border-2 border-gray-300 rounded-lg focus:ring-2 focus:ring-primary focus:border-primary',
                'placeholder': 'e.g. Kaduna',
                'maxlength': '100'
            }),
            'city': forms.TextInput(attrs={
                'class': 'w-full px-4 py-3 border-2 border-gray-300 rounded-lg focus:ring-2 focus:ring-primary focus:border-primary',
                'placeholder': 'e.g. Kawo',
                'maxlength': '100'
            }),
            'latitude': forms.HiddenInput(),
            'longitude': forms.HiddenInput(),
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
                'class': 'w-full px-4 py-3 border-2 border-gray-300 rounded-lg focus:ring-2 focus:ring-primary focus:border-primary'
            }),
            'return_policy': forms.Textarea(attrs={
                'rows': 4,
                'class': 'w-full px-4 py-3 border-2 border-gray-300 rounded-lg focus:ring-2 focus:ring-primary focus:border-primary'
            }),
            'primary_color': forms.TextInput(attrs={
                'type': 'color',
                'class': 'w-20 h-10 border-2 border-gray-300 rounded cursor-pointer'
            }),
            'is_published': forms.CheckboxInput(attrs={
                'class': 'peer sr-only'
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

        # SET MAIN CATEGORY QUERYSET
        # Include current category even if inactive, so it shows in the dropdown
        queryset = MainCategory.objects.filter(is_active=True)
        if self.instance and self.instance.pk and self.instance.main_category:
            # Include the current category even if it's inactive
            queryset = MainCategory.objects.filter(
                Q(is_active=True) | Q(pk=self.instance.main_category.pk)
            )
        self.fields['main_category'].queryset = queryset.order_by('sort_order', 'name')

        # CHECK IF STORE NAME CAN BE CHANGED
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

            # MAIN CATEGORY LOCK CHECK
            if not self.instance.can_request_category_change():
                days_left = self.instance.days_until_next_category_change()
                last_change_date = self.instance.main_category_last_changed_at.strftime('%B %d, %Y')

                # Make field read-only and not required (since disabled fields don't submit)
                self.fields['main_category'].widget.attrs.update({
                    'disabled': 'disabled',
                    'class': 'w-full px-4 py-3 border-2 border-gray-300 rounded-lg bg-gray-50 text-gray-500 cursor-not-allowed'
                })
                # Make it not required when disabled - we'll use instance value in clean method
                self.fields['main_category'].required = False
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

        # ENFORCE 1-YEAR LIMIT
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

        # If field is disabled, it won't be in POST data - use instance value
        if self.instance and self.instance.pk:
            # If main_category is None (disabled field not submitted), use instance value
            if main_category is None:
                main_category = self.instance.main_category

            old_category = self.instance.main_category
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

    def clean_is_published(self):
        """Preserve current visibility when the publish toggle is not submitted."""
        is_published = self.cleaned_data.get('is_published')

        if self.instance and self.instance.pk and 'is_published' not in self.data:
            return self.instance.is_published

        return is_published

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

    def clean_state(self):
        state = self.cleaned_data.get('state')
        if not state or not state.strip():
            raise ValidationError('This field is required.')
        return state.strip()

    def clean_city(self):
        city = self.cleaned_data.get('city')
        if not city or not city.strip():
            raise ValidationError('This field is required.')
        return city.strip()

    def clean_latitude(self):
        lat = self.cleaned_data.get('latitude')
        if lat is None or lat == '':
            raise ValidationError('Please capture your location')
        return lat

    def clean_longitude(self):
        lon = self.cleaned_data.get('longitude')
        if lon is None or lon == '':
            raise ValidationError('Please capture your location')
        return lon

    def save(self, commit=True):
        """Save and track store name & category changes"""
        store = super().save(commit=False)

        # PREVENT STORE NAME CHANGE IF LOCKED (Server-side enforcement)
        if self.instance.pk:
            old_store_name = Store.objects.get(pk=self.instance.pk).store_name
            old_main_category = Store.objects.get(pk=self.instance.pk).main_category

            new_store_name = self.cleaned_data.get('store_name')
            new_main_category = self.cleaned_data.get('main_category')

            # Handle store name changes
            if old_store_name != new_store_name:
                if not self.instance.can_change_store_name():
                    # REJECT THE CHANGE - keep old name
                    store.store_name = old_store_name
                    logger.warning(
                        f"🚫 BLOCKED: Attempted to change store name while locked. "
                        f"Store ID: {self.instance.pk}, Attempted: {new_store_name}"
                    )
                else:
                    # ALLOW - Update tracking
                    store.store_name_last_changed_at = timezone.now()
                    store.store_name_change_count = (self.instance.store_name_change_count or 0) + 1
                    logger.info(
                        f"📝 Store name changed: '{old_store_name}' → '{new_store_name}' "
                        f"(Change #{store.store_name_change_count})"
                    )

            # Handle category changes
            if old_main_category != new_main_category:
                if not self.instance.can_request_category_change():
                    # REJECT THE CHANGE - keep old category
                    store.main_category = old_main_category
                    logger.warning(
                        f"🚫 BLOCKED: Attempted to change category while locked. "
                        f"Store ID: {self.instance.pk}, Attempted: {new_main_category}"
                    )
                else:
                    # ALLOW - Update tracking
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
# SETTINGS PAGE FORMS (LIGHTWEIGHT)
# ==========================================


class StoreVisibilityForm(forms.ModelForm):
    """Toggle store published/unpublished status."""

    class Meta:
        model = Store
        fields = ['is_published']
        widgets = {
            'is_published': forms.CheckboxInput(attrs={
                'class': 'sr-only peer',
                'id': 'visibility-toggle',
            }),
        }

    def save(self, commit=True):
        store = super().save(commit=False)
        if commit:
            store.save(update_fields=['is_published', 'updated_at'])
        return store


class StoreReviewsForm(forms.ModelForm):
    """Toggle allow_reviews on/off."""

    class Meta:
        model = Store
        fields = ['allow_reviews']
        widgets = {
            'allow_reviews': forms.CheckboxInput(attrs={
                'class': 'sr-only peer',
                'id': 'reviews-toggle',
            }),
        }

    def save(self, commit=True):
        store = super().save(commit=False)
        if commit:
            store.save(update_fields=['allow_reviews', 'updated_at'])
        return store


class StoreContactLocationForm(forms.ModelForm):
    """Edit contact details and location after store setup."""

    class Meta:
        model = Store
        fields = [
            'phone', 'whatsapp', 'business_email',
            'state', 'city', 'latitude', 'longitude',
        ]
        widgets = {
            'phone': forms.TextInput(attrs={
                'class': 'w-full px-4 py-3 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary focus:border-primary text-sm',
                'placeholder': '08012345678',
                'type': 'tel',
            }),
            'whatsapp': forms.TextInput(attrs={
                'class': 'w-full px-4 py-3 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary focus:border-primary text-sm',
                'placeholder': '08012345678',
                'type': 'tel',
            }),
            'business_email': forms.EmailInput(attrs={
                'class': 'w-full px-4 py-3 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary focus:border-primary text-sm',
                'placeholder': 'store@example.com',
            }),
            'state': forms.TextInput(attrs={
                'class': 'w-full px-4 py-3 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary focus:border-primary text-sm',
                'placeholder': 'e.g. Kaduna',
                'maxlength': '100',
            }),
            'city': forms.TextInput(attrs={
                'class': 'w-full px-4 py-3 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary focus:border-primary text-sm',
                'placeholder': 'e.g. Kawo',
                'maxlength': '100',
            }),
            'latitude': forms.HiddenInput(),
            'longitude': forms.HiddenInput(),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['business_email'].required = False

    def _clean_nigerian_phone(self, value):
        if not value:
            raise ValidationError('This field is required.')
        value = re.sub(r'[\s\-\(\)]', '', value)
        if not re.match(r'^(0|\+234)[7-9][0-1]\d{8}$', value):
            raise ValidationError('Invalid phone number')
        return value

    def clean_phone(self):
        return self._clean_nigerian_phone(self.cleaned_data.get('phone'))

    def clean_whatsapp(self):
        return self._clean_nigerian_phone(self.cleaned_data.get('whatsapp'))

    def clean_state(self):
        state = self.cleaned_data.get('state')
        if not state or not state.strip():
            raise ValidationError('This field is required.')
        return state.strip()

    def clean_city(self):
        city = self.cleaned_data.get('city')
        if not city or not city.strip():
            raise ValidationError('This field is required.')
        return city.strip()

    def clean_latitude(self):
        lat = self.cleaned_data.get('latitude')
        if lat is None or lat == '':
            raise ValidationError('Please capture your location')
        return lat

    def clean_longitude(self):
        lon = self.cleaned_data.get('longitude')
        if lon is None or lon == '':
            raise ValidationError('Please capture your location')
        return lon

    def save(self, commit=True):
        store = super().save(commit=False)
        if commit:
            store.save(update_fields=[
                'phone', 'whatsapp', 'business_email',
                'state', 'city', 'latitude', 'longitude',
                'updated_at',
            ])
        return store


# ==========================================
# CATEGORY CHANGE REQUEST FORM (UNCHANGED, 1-YEAR LIMIT)
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

            # CHECK IF CHANGE REQUEST IS ALLOWED
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

        # ENFORCE 1-YEAR LIMIT
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
# HELPER FUNCTION FOR DISPLAYING LIMITS (UNCHANGED)
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
# PRODUCT FORM (UNCHANGED, Dynamic Attributes)
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
            'sku', 'status', 'video'
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
            'video': forms.FileInput(attrs={
                'class': 'hidden',
                'accept': 'video/mp4,video/quicktime'
            }),
        }


    def __init__(self, *args, **kwargs):
        self.vendor = kwargs.pop('vendor', None)
        self.subcategory_id = kwargs.pop('subcategory_id', None)
        self.is_editing = kwargs.pop('is_editing', False)
        super().__init__(*args, **kwargs)
        self.fields['video'].required = False

        # Set is_editing based on instance
        if self.instance and self.instance.pk:
            self.is_editing = True

        # Filter subcategories to ONLY vendor's main category
        if self.vendor and hasattr(self.vendor, 'store'):
            self.fields['subcategory'].queryset = SubCategory.objects.filter(
                main_category=self.vendor.store.main_category,
                is_active=True
            ).order_by('name')
            self.fields['subcategory'].empty_label = '-- Select Subcategory --'

        # CONFIGURE STATUS FIELD BASED ON CREATE VS EDIT
        if self.is_editing:
            self.fields['status'].choices = [
                ('draft', 'Save as Draft'),
                ('published', 'Publish'),
                ('discontinued', 'Discontinued'),
            ]
        else:
            self.fields['status'].choices = [
                ('draft', 'Save as Draft'),
                ('published', 'Publish'),
            ]

        # Determine the subcategory to load dynamic fields for
        subcategory = None

        if self.instance and getattr(self.instance, 'pk', None):
            subcategory = self.instance.subcategory
        else:
            subcategory = self.data.get('subcategory') or self.initial.get('subcategory')

        if subcategory:
            if not isinstance(subcategory, SubCategory):
                subcategory = SubCategory.objects.filter(id=subcategory).first()

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

            options = []
            if attr.options:
                if isinstance(attr.options, list):
                    options = attr.options
                elif isinstance(attr.options, str):
                    options = [o.strip() for o in attr.options.split(',') if o.strip()]

            initial_value = None
            if self.instance.pk and self.instance.attributes:
                initial_value = self.instance.attributes.get(str(attr.id))

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

            if self.instance.pk and initial_value is not None:
                if attr.field_type == 'checkbox':
                    self.initial[field_name] = str(initial_value).lower() == 'true'
                else:
                    self.initial[field_name] = initial_value

    def clean_video(self):
        video = self.cleaned_data.get('video')
        if video and hasattr(video, 'size'):
            if video.size > 50 * 1024 * 1024:
                raise ValidationError('Video must be under 50MB.')
            filename = video.name.lower() if hasattr(video, 'name') else ''
            valid_extensions = ('.mp4', '.mov')
            has_valid_ext = filename.endswith(valid_extensions)
            has_valid_content_type = True
            if hasattr(video, 'content_type'):
                has_valid_content_type = video.content_type in ['video/mp4', 'video/quicktime']
            if not (has_valid_ext or has_valid_content_type):
                raise ValidationError('Only MP4 and MOV videos are allowed.')
        return video

    def clean(self):
        cleaned_data = super().clean()

        status = cleaned_data.get('status')

        # Validate compare_at_price > price
        price = cleaned_data.get('price')
        compare_price = cleaned_data.get('compare_at_price')

        if compare_price and price and compare_price <= price:
            raise ValidationError({
                'compare_at_price': 'Compare at price must be greater than selling price'
            })

        # Prevent discontinued status on NEW products
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

        if hasattr(self, 'vendor') and self.vendor:
            instance.vendor = self.vendor
            instance.store = self.vendor.store

        attributes = {}
        for name, field in self.fields.items():
            if name.startswith('attr_'):
                value = self.cleaned_data.get(name)
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
# PRODUCT IMAGE FORMSET (UNCHANGED)
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

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['image'].required = False
        self.empty_permitted = True

    def has_changed(self):
        if self.instance and self.instance.pk:
            return super().has_changed()

        if hasattr(self, 'files') and self.files and 'image' in self.files:
            file_obj = self.files.get('image')
            if file_obj and hasattr(file_obj, 'size') and file_obj.size > 0:
                return True

        if hasattr(self, 'cleaned_data') and self.cleaned_data and self.cleaned_data.get('image'):
            return True

        return False

    def clean_image(self):
        image = self.cleaned_data.get('image')

        if image and hasattr(image, 'size'):
            if image.size > 5 * 1024 * 1024:
                raise ValidationError('Image must be less than 5MB')

            filename = image.name.lower() if hasattr(image, 'name') else ''
            valid_extensions = ('.jpg', '.jpeg', '.png', '.webp')

            has_valid_ext = filename.endswith(valid_extensions)

            has_valid_content_type = True
            if hasattr(image, 'content_type'):
                has_valid_content_type = image.content_type in ['image/jpeg', 'image/jpg', 'image/png', 'image/webp']

            if not (has_valid_ext or has_valid_content_type):
                raise ValidationError('Only JPG, PNG and WebP images are allowed')

        return image



class ProductImageBaseFormSet(BaseInlineFormSet):
    """Custom base formset to validate 3-5 images"""

    def _has_image(self, form):
        if form.instance and form.instance.pk and hasattr(form.instance, 'image') and form.instance.image:
            return True
        if form.cleaned_data and form.cleaned_data.get('image'):
            return True
        if hasattr(self, 'files') and self.files:
            form_prefix = form.prefix
            image_key = f'{form_prefix}-image'
            if image_key in self.files and self.files[image_key]:
                return True
        if hasattr(form, 'files') and form.files and form.files.get('image'):
            return True
        return False

    def clean(self):
        for form in self.forms:
            is_empty = not self._has_image(form)

            if is_empty and form.errors:
                if 'image' in form.errors:
                    form.errors.pop('image', None)

        super().clean()

        for form in self.forms:
            is_empty = not self._has_image(form)

            if is_empty and 'image' in form.errors:
                form.errors.pop('image', None)

        image_count = 0
        for i, form in enumerate(self.forms):
            if form.cleaned_data and form.cleaned_data.get('DELETE'):
                continue

            if self._has_image(form):
                image_count += 1
            elif hasattr(self, 'files') and self.files:
                form_prefix = form.prefix
                image_key = f'{form_prefix}-image'
                if image_key in self.files and self.files[image_key]:
                    image_count += 1

        if image_count < 3:
            raise ValidationError(
                f'Please upload at least 3 images. You currently have {image_count} image(s). '
                f'Please add {3 - image_count} more image(s).'
            )

        if image_count > 4:
            raise ValidationError(
                f'Maximum 4 images allowed. You have {image_count} image(s). '
                f'Please remove {image_count - 4} image(s).'
            )

        primary_count = 0
        for form in self.forms:
            if form.cleaned_data and not form.cleaned_data.get('DELETE'):
                if form.cleaned_data.get('is_primary'):
                    primary_count += 1
                elif form.instance and form.instance.pk and form.instance.is_primary:
                    primary_count += 1

        if image_count > 0 and primary_count == 0:
            for form in self.forms:
                if self._has_image(form) and form.cleaned_data and not form.cleaned_data.get('DELETE'):
                    form.cleaned_data['is_primary'] = True
                    break

        if primary_count > 1:
            raise ValidationError('Only one image can be set as primary.')

    def save(self, commit=True):
        """Override save to ensure forms with images are saved"""
        instances = super().save(commit=False)

        saved_indices = set()
        for i, form in enumerate(self.forms):
            if form.instance and form.instance.pk:
                saved_indices.add(i)

        if hasattr(self, 'files') and self.files:
            for i, form in enumerate(self.forms):
                if i in saved_indices:
                    continue
                if form.cleaned_data and form.cleaned_data.get('DELETE'):
                    continue

                form_prefix = form.prefix
                image_key = f'{form_prefix}-image'

                if image_key in self.files and self.files[image_key]:
                    from apps.vendors.models import ProductImage
                    image_instance = ProductImage(
                        product=self.instance,
                        image=self.files[image_key]
                    )

                    if form.cleaned_data:
                        if 'is_primary' in form.cleaned_data:
                            image_instance.is_primary = form.cleaned_data['is_primary']
                        elif i == 0:
                            image_instance.is_primary = True
                        if 'sort_order' in form.cleaned_data:
                            image_instance.sort_order = form.cleaned_data['sort_order']
                        else:
                            image_instance.sort_order = i
                        if 'alt_text' in form.cleaned_data:
                            image_instance.alt_text = form.cleaned_data['alt_text']

                    if commit:
                        image_instance.save()
                    instances.append(image_instance)

        return instances


ProductImageFormSet = inlineformset_factory(
    Product,
    ProductImage,
    form=ProductImageForm,
    formset=ProductImageBaseFormSet,
    extra=4,
    can_delete=True,
    min_num=0,
    validate_min=False,
    max_num=4,
    validate_max=True,
)
