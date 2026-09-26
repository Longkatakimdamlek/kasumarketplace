"""
Quick Sell Forms

Phase 3: Quick Sell forms that reuse the EXISTING Vendor Product taxonomy.
Uses the same MainCategory -> SubCategory -> SubCategoryAttribute hierarchy.

DO NOT create QuickSellCategory, QuickSellSubCategory, or QuickSellAttribute.
The existing Vendor taxonomy is the SINGLE SOURCE OF TRUTH.
"""

import re
from django import forms
from django.core.exceptions import ValidationError
from django.forms import inlineformset_factory, BaseInlineFormSet

from apps.vendors.models import MainCategory, SubCategory, SubCategoryAttribute
from apps.quicksell.models import QuickSell, QuickSellImage


def _validate_nigerian_phone(phone):
    """
    Validate a Nigerian phone number.
    Accepts: 0XXXXXXXXXX (11 digits) or +234XXXXXXXXXX (13 digits)
    Returns cleaned phone or raises ValidationError.
    """
    if not phone:
        return phone
    phone = re.sub(r'[\s\-\(\)]', '', phone.strip())
    if not re.match(r'^(0|\+234)[7-9][0-1]\d{8}$', phone):
        raise ValidationError('Enter a valid Nigerian phone number (e.g. 080XXXXXXXX or +234XXXXXXXXXX)')
    return phone


# ==========================================
# QUICK SELL FORMS
# ==========================================

class QuickSellCreateForm(forms.ModelForm):
    """
    Form for creating Quick Sell listings.
    Reuses the EXISTING Vendor Product taxonomy (MainCategory -> SubCategory -> SubCategoryAttribute).
    """

    main_category = forms.ModelChoiceField(
        queryset=MainCategory.objects.filter(is_active=True).order_by('sort_order', 'name'),
        required=True,
        empty_label='-- Select Category --',
        label='Category',
        widget=forms.Select(attrs={
            'class': 'w-full px-4 py-3 border-2 border-gray-300 rounded-lg focus:ring-2 focus:ring-primary focus:border-primary',
            'id': 'id_main_category'
        })
    )

    class Meta:
        model = QuickSell
        fields = [
            'title', 'subcategory', 'description',
            'price', 'compare_at_price',
            'whatsapp', 'phone',
            'video',
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
                'placeholder': 'Describe your item in detail...'
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
            'whatsapp': forms.TextInput(attrs={
                'class': 'w-full px-4 py-3 border-2 border-gray-300 rounded-lg focus:ring-2 focus:ring-primary focus:border-primary',
                'placeholder': '+234...'
            }),
            'phone': forms.TextInput(attrs={
                'class': 'w-full px-4 py-3 border-2 border-gray-300 rounded-lg focus:ring-2 focus:ring-primary focus:border-primary',
                'placeholder': '+234...'
            }),
            'video': forms.ClearableFileInput(attrs={
                'class': 'hidden',
                'accept': 'video/mp4,video/quicktime'
            }),
        }

    def __init__(self, *args, **kwargs):
        self.user = kwargs.pop('user', None)
        self.subcategory_id = kwargs.pop('subcategory_id', None)
        self.is_editing = kwargs.pop('is_editing', False)
        super().__init__(*args, **kwargs)

        # Set is_editing based on instance
        if self.instance and self.instance.pk:
            self.is_editing = True

        # Filter subcategories: show all active (will be filtered by AJAX on frontend)
        self.fields['subcategory'].queryset = SubCategory.objects.filter(
            is_active=True
        ).order_by('name')
        self.fields['subcategory'].empty_label = '-- Select Subcategory --'

        # Set initial main_category if editing
        if self.is_editing and self.instance.pk and self.instance.subcategory:
            self.fields['main_category'].initial = self.instance.subcategory.main_category

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
        """
        Dynamically add form fields based on the selected subcategory's SubCategoryAttribute records.
        Reuses the SAME SubCategoryAttribute model used by Vendor Products.
        """
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
                field_kwargs = {
                    'required': attr.is_required,
                    'label': attr.name,
                }
                if attr.min_value is not None:
                    field_kwargs['min_value'] = attr.min_value
                if attr.max_value is not None:
                    field_kwargs['max_value'] = attr.max_value
                self.fields[field_name] = forms.IntegerField(**field_kwargs)

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
                # text, radio, and any other types
                self.fields[field_name] = forms.CharField(
                    required=attr.is_required,
                    label=attr.name
                )

            if self.instance.pk and initial_value is not None:
                if attr.field_type == 'checkbox':
                    self.initial[field_name] = str(initial_value).lower() == 'true'
                else:
                    self.initial[field_name] = initial_value

    def clean(self):
        cleaned_data = super().clean()

        # Validate compare_at_price > price
        price = cleaned_data.get('price')
        compare_price = cleaned_data.get('compare_at_price')

        if compare_price and price and compare_price <= price:
            raise ValidationError({
                'compare_at_price': 'Compare at price must be greater than selling price'
            })

        # Validate required dynamic attributes
        for field_name, field in self.fields.items():
            if field_name.startswith('attr_'):
                value = cleaned_data.get(field_name)
                if field.required and (value is None or value == ''):
                    self.add_error(field_name, f"{field.label} is required.")

        # Validate that submitted attribute IDs belong to the selected subcategory
        subcategory = cleaned_data.get('subcategory')
        if subcategory:
            valid_attr_ids = set(
                str(attr.id) for attr in
                SubCategoryAttribute.objects.filter(
                    subcategory=subcategory,
                    is_active=True
                )
            )
            # Check fields in self.fields (dynamically added for the selected subcategory)
            for field_name in self.fields:
                if field_name.startswith('attr_'):
                    attr_id = field_name.split('_', 1)[1]
                    if attr_id not in valid_attr_ids:
                        self.add_error(field_name, 'Invalid attribute for selected subcategory.')

            # Also check raw POST data for attr_* keys not in self.fields
            # (prevents injection of attributes from other subcategories)
            if hasattr(self, 'data') and self.data:
                invalid_attrs = []
                for key in self.data:
                    if key.startswith('attr_') and key not in self.fields:
                        invalid_attrs.append(key)
                if invalid_attrs:
                    raise ValidationError(
                        'Invalid attributes submitted for the selected subcategory.'
                    )

        return cleaned_data

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

    def clean_phone(self):
        return _validate_nigerian_phone(self.cleaned_data.get('phone', ''))

    def clean_whatsapp(self):
        return _validate_nigerian_phone(self.cleaned_data.get('whatsapp', ''))

    def save(self, commit=True):
        instance = super().save(commit=False)

        # Set ownership from authenticated user — NEVER from client data
        if self.user and not instance.user_id:
            instance.user = self.user

        # Collect dynamic attributes into JSONField
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


class QuickSellEditForm(forms.ModelForm):
    """
    Form for editing Quick Sell listings.
    Reuses the EXISTING Vendor Product taxonomy.
    Ownership is enforced server-side — NOT through form fields.
    """

    main_category = forms.ModelChoiceField(
        queryset=MainCategory.objects.filter(is_active=True).order_by('sort_order', 'name'),
        required=True,
        empty_label='-- Select Category --',
        label='Category',
        widget=forms.Select(attrs={
            'class': 'w-full px-4 py-3 border-2 border-gray-300 rounded-lg focus:ring-2 focus:ring-primary focus:border-primary',
            'id': 'id_main_category'
        })
    )

    class Meta:
        model = QuickSell
        fields = [
            'title', 'subcategory', 'description',
            'price', 'compare_at_price',
            'whatsapp', 'phone',
            'video',
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
                'placeholder': 'Describe your item in detail...'
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
            'whatsapp': forms.TextInput(attrs={
                'class': 'w-full px-4 py-3 border-2 border-gray-300 rounded-lg focus:ring-2 focus:ring-primary focus:border-primary',
                'placeholder': '+234...'
            }),
            'phone': forms.TextInput(attrs={
                'class': 'w-full px-4 py-3 border-2 border-gray-300 rounded-lg focus:ring-2 focus:ring-primary focus:border-primary',
                'placeholder': '+234...'
            }),
            'video': forms.ClearableFileInput(attrs={
                'class': 'hidden',
                'accept': 'video/mp4,video/quicktime'
            }),
        }

    def __init__(self, *args, **kwargs):
        self.user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)

        # Filter subcategories: show all active
        self.fields['subcategory'].queryset = SubCategory.objects.filter(
            is_active=True
        ).order_by('name')
        self.fields['subcategory'].empty_label = '-- Select Subcategory --'

        # Set initial main_category from existing instance
        if self.instance.pk and self.instance.subcategory:
            self.fields['main_category'].initial = self.instance.subcategory.main_category

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
        """
        Dynamically add form fields based on the selected subcategory's SubCategoryAttribute records.
        Reuses the SAME SubCategoryAttribute model used by Vendor Products.
        """
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
                field_kwargs = {
                    'required': attr.is_required,
                    'label': attr.name,
                }
                if attr.min_value is not None:
                    field_kwargs['min_value'] = attr.min_value
                if attr.max_value is not None:
                    field_kwargs['max_value'] = attr.max_value
                self.fields[field_name] = forms.IntegerField(**field_kwargs)

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
                # text, radio, and any other types
                self.fields[field_name] = forms.CharField(
                    required=attr.is_required,
                    label=attr.name
                )

            if self.instance.pk and initial_value is not None:
                if attr.field_type == 'checkbox':
                    self.initial[field_name] = str(initial_value).lower() == 'true'
                else:
                    self.initial[field_name] = initial_value

    def clean(self):
        cleaned_data = super().clean()

        # Validate compare_at_price > price
        price = cleaned_data.get('price')
        compare_price = cleaned_data.get('compare_at_price')

        if compare_price and price and compare_price <= price:
            raise ValidationError({
                'compare_at_price': 'Compare at price must be greater than selling price'
            })

        # Validate required dynamic attributes
        for field_name, field in self.fields.items():
            if field_name.startswith('attr_'):
                value = cleaned_data.get(field_name)
                if field.required and (value is None or value == ''):
                    self.add_error(field_name, f"{field.label} is required.")

        # Validate that submitted attribute IDs belong to the selected subcategory
        subcategory = cleaned_data.get('subcategory')
        if subcategory:
            valid_attr_ids = set(
                str(attr.id) for attr in
                SubCategoryAttribute.objects.filter(
                    subcategory=subcategory,
                    is_active=True
                )
            )
            # Check fields in self.fields (dynamically added for the selected subcategory)
            for field_name in self.fields:
                if field_name.startswith('attr_'):
                    attr_id = field_name.split('_', 1)[1]
                    if attr_id not in valid_attr_ids:
                        self.add_error(field_name, 'Invalid attribute for selected subcategory.')

            # Also check raw POST data for attr_* keys not in self.fields
            # (prevents injection of attributes from other subcategories)
            if hasattr(self, 'data') and self.data:
                invalid_attrs = []
                for key in self.data:
                    if key.startswith('attr_') and key not in self.fields:
                        invalid_attrs.append(key)
                if invalid_attrs:
                    raise ValidationError(
                        'Invalid attributes submitted for the selected subcategory.'
                    )

        return cleaned_data

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

    def clean_phone(self):
        return _validate_nigerian_phone(self.cleaned_data.get('phone', ''))

    def clean_whatsapp(self):
        return _validate_nigerian_phone(self.cleaned_data.get('whatsapp', ''))

    def save(self, commit=True):
        instance = super().save(commit=False)

        # Collect dynamic attributes into JSONField
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
# QUICK SELL IMAGE FORMSET
# ==========================================

class QuickSellImageForm(forms.ModelForm):
    """Form for individual Quick Sell images."""

    class Meta:
        model = QuickSellImage
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
                has_valid_content_type = image.content_type in [
                    'image/jpeg', 'image/jpg', 'image/png', 'image/webp'
                ]

            if not (has_valid_ext or has_valid_content_type):
                raise ValidationError('Only JPG, PNG and WebP images are allowed')

        return image


class QuickSellImageBaseFormSet(BaseInlineFormSet):
    """Custom base formset to validate Quick Sell images."""

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

        # Quick Sell: at least 1 image, max 4
        if image_count < 1:
            raise ValidationError(
                f'Please upload at least 1 image. You currently have {image_count} image(s).'
            )

        if image_count > 4:
            raise ValidationError(
                f'Maximum 4 images allowed. You have {image_count} image(s). '
                f'Please remove {image_count - 4} image(s).'
            )

        # Ensure exactly one primary image
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
        """Override save to ensure forms with images are saved."""
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
                    image_instance = QuickSellImage(
                        quicksell=self.instance,
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


QuickSellImageFormSet = inlineformset_factory(
    QuickSell,
    QuickSellImage,
    form=QuickSellImageForm,
    formset=QuickSellImageBaseFormSet,
    extra=4,
    can_delete=True,
    min_num=0,
    validate_min=False,
    max_num=4,
    validate_max=True,
)
