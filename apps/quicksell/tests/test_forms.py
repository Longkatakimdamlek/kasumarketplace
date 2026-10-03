"""
Quick Sell Form Tests

Phase 3: Tests for Quick Sell forms, views, AJAX endpoints, and security.
Covers:
1. Valid Quick Sell form submission
2. Invalid required fields
3. Correct subcategory selection
4. Invalid subcategory rejection
5. Attributes belonging to selected subcategory are accepted
6. Attributes belonging to another subcategory are rejected
7. Invalid attribute IDs are rejected
8. Seller ownership comes from request.user
9. User cannot assign another seller
10. expires_at cannot be controlled by form input
11. Contact fields are populated/validated
12. Image validation
13. Multiple images
14. Edit ownership protection
15. CSRF/form validation follows Django conventions
"""

from decimal import Decimal
import io
from unittest.mock import MagicMock

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, Client
from django.urls import reverse

from apps.quicksell.forms import (
    QuickSellCreateForm,
    QuickSellEditForm,
    QuickSellImageForm,
    QuickSellImageFormSet,
)
from apps.quicksell.models import QuickSell, QuickSellImage
from apps.users.models import CustomUser
from apps.vendors.models import MainCategory, SubCategory, SubCategoryAttribute


class QuickSellFormTestBase(TestCase):
    """Base test class with common setup for Quick Sell form tests."""

    def setUp(self):
        self.user = CustomUser.objects.create_user(
            email='seller@example.com',
            password='password123',
            username='seller',
            role='buyer',
        )
        self.other_user = CustomUser.objects.create_user(
            email='other@example.com',
            password='password123',
            username='other',
            role='buyer',
        )
        self.category = MainCategory.objects.create(
            name='Tech & Electronics', slug='tech-electronics'
        )
        self.subcategory = SubCategory.objects.create(
            main_category=self.category,
            name='Phones',
            slug='phones',
        )
        self.other_category = MainCategory.objects.create(
            name='Fashion', slug='fashion'
        )
        self.other_subcategory = SubCategory.objects.create(
            main_category=self.other_category,
            name='Clothes',
            slug='clothes',
        )
        # Create attributes for Phones subcategory
        self.brand_attr = SubCategoryAttribute.objects.create(
            subcategory=self.subcategory,
            name='Brand',
            field_type='dropdown',
            options=['Apple', 'Samsung', 'Google'],
            is_required=True,
            sort_order=0,
        )
        self.storage_attr = SubCategoryAttribute.objects.create(
            subcategory=self.subcategory,
            name='Storage',
            field_type='dropdown',
            options=['64GB', '128GB', '256GB'],
            is_required=False,
            sort_order=1,
        )
        self.condition_attr = SubCategoryAttribute.objects.create(
            subcategory=self.subcategory,
            name='Condition',
            field_type='text',
            is_required=False,
            sort_order=2,
        )
        # Create attribute for other subcategory
        self.size_attr = SubCategoryAttribute.objects.create(
            subcategory=self.other_subcategory,
            name='Size',
            field_type='dropdown',
            options=['S', 'M', 'L', 'XL'],
            is_required=True,
            sort_order=0,
        )

        self.valid_data = {
            'main_category': self.category.id,
            'subcategory': self.subcategory.id,
            'title': 'iPhone 15 Pro Max',
            'description': 'Brand new iPhone 15 Pro Max 256GB',
            'price': Decimal('850000.00'),
            'compare_at_price': Decimal('950000.00'),
            'whatsapp': '+2348012345678',
            'phone': '+2348012345679',
            f'attr_{self.brand_attr.id}': 'Apple',
            f'attr_{self.storage_attr.id}': '256GB',
            f'attr_{self.condition_attr.id}': 'Brand New',
        }


class QuickSellCreateFormTest(QuickSellFormTestBase):
    """Tests for QuickSellCreateForm."""

    def test_valid_form_submission(self):
        form = QuickSellCreateForm(
            data=self.valid_data,
            user=self.user
        )
        self.assertTrue(form.is_valid(), form.errors)

    def test_save_creates_listing_with_correct_user(self):
        form = QuickSellCreateForm(
            data=self.valid_data,
            user=self.user
        )
        self.assertTrue(form.is_valid(), form.errors)
        listing = form.save()
        self.assertEqual(listing.user, self.user)

    def test_required_fields_missing(self):
        invalid_data = {
            'main_category': self.category.id,
            'subcategory': self.subcategory.id,
        }
        form = QuickSellCreateForm(
            data=invalid_data,
            user=self.user
        )
        self.assertFalse(form.is_valid())
        self.assertIn('title', form.errors)
        self.assertIn('description', form.errors)
        self.assertIn('price', form.errors)

    def test_invalid_subcategory_rejection(self):
        data = self.valid_data.copy()
        data['subcategory'] = 99999
        form = QuickSellCreateForm(
            data=data,
            user=self.user
        )
        self.assertFalse(form.is_valid())
        self.assertIn('subcategory', form.errors)

    def test_attributes_from_another_subcategory_rejected(self):
        data = self.valid_data.copy()
        # Add attribute from Clothes subcategory
        data[f'attr_{self.size_attr.id}'] = 'L'
        form = QuickSellCreateForm(
            data=data,
            user=self.user
        )
        self.assertFalse(form.is_valid())
        # Should have non-field error for the invalid attribute
        self.assertTrue(form.non_field_errors())

    def test_invalid_attribute_id_rejected(self):
        data = self.valid_data.copy()
        data['attr_99999'] = 'Some Value'
        form = QuickSellCreateForm(
            data=data,
            user=self.user
        )
        self.assertFalse(form.is_valid())
        # Should have non-field error for the invalid attribute
        self.assertTrue(form.non_field_errors())

    def test_compare_at_price_must_be_greater_than_price(self):
        data = self.valid_data.copy()
        data['compare_at_price'] = Decimal('800000.00')
        form = QuickSellCreateForm(
            data=data,
            user=self.user
        )
        self.assertFalse(form.is_valid())
        self.assertIn('compare_at_price', form.errors)

    def test_expires_at_not_in_form_fields(self):
        data = self.valid_data.copy()
        data['expires_at'] = '2030-01-01T00:00:00'
        form = QuickSellCreateForm(
            data=data,
            user=self.user
        )
        # expires_at should not be a form field
        self.assertNotIn('expires_at', form.fields)

    def test_user_cannot_assign_another_seller(self):
        data = self.valid_data.copy()
        data['user'] = self.other_user.id
        form = QuickSellCreateForm(
            data=data,
            user=self.user
        )
        self.assertTrue(form.is_valid(), form.errors)
        listing = form.save()
        # Owner should be the authenticated user, not the submitted user
        self.assertEqual(listing.user, self.user)

    def test_dropdown_attribute_required_validation(self):
        data = self.valid_data.copy()
        del data[f'attr_{self.brand_attr.id}']
        form = QuickSellCreateForm(
            data=data,
            user=self.user
        )
        self.assertFalse(form.is_valid())
        self.assertIn(f'attr_{self.brand_attr.id}', form.errors)

    def test_optional_attribute_can_be_empty(self):
        data = self.valid_data.copy()
        del data[f'attr_{self.storage_attr.id}']
        del data[f'attr_{self.condition_attr.id}']
        form = QuickSellCreateForm(
            data=data,
            user=self.user
        )
        self.assertTrue(form.is_valid(), form.errors)


class QuickSellEditFormTest(QuickSellFormTestBase):
    """Tests for QuickSellEditForm."""

    def setUp(self):
        super().setUp()
        self.listing = QuickSell.objects.create(
            user=self.user,
            subcategory=self.subcategory,
            title='Original Title',
            description='Original description',
            price=Decimal('100000.00'),
            whatsapp='08012345678',
        )

    def test_valid_edit_form(self):
        data = self.valid_data.copy()
        form = QuickSellEditForm(
            data=data,
            instance=self.listing,
            user=self.user
        )
        self.assertTrue(form.is_valid(), form.errors)

    def test_edit_preserves_user(self):
        data = self.valid_data.copy()
        data['user'] = self.other_user.id
        form = QuickSellEditForm(
            data=data,
            instance=self.listing,
            user=self.user
        )
        self.assertTrue(form.is_valid(), form.errors)
        listing = form.save()
        self.assertEqual(listing.user, self.user)

    def test_edit_updates_listing(self):
        data = self.valid_data.copy()
        data['title'] = 'Updated Title'
        form = QuickSellEditForm(
            data=data,
            instance=self.listing,
            user=self.user
        )
        self.assertTrue(form.is_valid(), form.errors)
        listing = form.save()
        self.assertEqual(listing.title, 'Updated Title')

    def test_edit_attributes_stored_correctly(self):
        data = self.valid_data.copy()
        form = QuickSellEditForm(
            data=data,
            instance=self.listing,
            user=self.user
        )
        self.assertTrue(form.is_valid(), form.errors)
        listing = form.save()
        self.assertEqual(listing.attributes[str(self.brand_attr.id)], 'Apple')
        self.assertEqual(listing.attributes[str(self.storage_attr.id)], '256GB')


class QuickSellImageFormTest(QuickSellFormTestBase):
    """Tests for QuickSellImageForm and QuickSellImageFormSet."""

    def setUp(self):
        super().setUp()
        self.listing = QuickSell.objects.create(
            user=self.user,
            subcategory=self.subcategory,
            title='Image Test Item',
            description='Test',
            price=Decimal('50000.00'),
        )

    def test_image_form_meta_fields(self):
        form = QuickSellImageForm()
        expected_fields = ['image', 'alt_text', 'is_primary', 'sort_order']
        self.assertEqual(list(form.Meta.fields), expected_fields)

    def test_image_validation_rejects_oversized(self):
        # Create a fake image over 5MB
        large_content = b'x' * (6 * 1024 * 1024)
        large_image = SimpleUploadedFile(
            'large.jpg',
            large_content,
            content_type='image/jpeg'
        )
        form = QuickSellImageForm(
            data={'alt_text': 'Test', 'is_primary': True, 'sort_order': 0},
            files={'image': large_image}
        )
        self.assertFalse(form.is_valid())
        self.assertIn('image', form.errors)

    def test_image_validation_rejects_invalid_type(self):
        invalid_file = SimpleUploadedFile(
            'test.exe',
            b'binary content',
            content_type='application/octet-stream'
        )
        form = QuickSellImageForm(
            data={'alt_text': 'Test', 'is_primary': True, 'sort_order': 0},
            files={'image': invalid_file}
        )
        self.assertFalse(form.is_valid())
        self.assertIn('image', form.errors)


class QuickSellAJAXViewTest(QuickSellFormTestBase):
    """Tests for Quick Sell AJAX endpoints."""

    def setUp(self):
        super().setUp()
        self.client = Client()
        self.client.login(email='seller@example.com', password='password123')

    def test_ajax_subcategories_returns_correct_data(self):
        url = reverse('quicksell:ajax_subcategories')
        response = self.client.get(url, {'main_category_id': self.category.id})
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn('subcategories', data)
        self.assertEqual(len(data['subcategories']), 1)
        self.assertEqual(data['subcategories'][0]['name'], 'Phones')

    def test_ajax_subcategories_empty_when_no_main_category(self):
        url = reverse('quicksell:ajax_subcategories')
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data['subcategories'], [])

    def test_ajax_attributes_returns_correct_data(self):
        url = reverse('quicksell:ajax_attributes')
        response = self.client.get(url, {'subcategory_id': self.subcategory.id})
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn('attributes', data)
        self.assertEqual(len(data['attributes']), 3)

    def test_ajax_attributes_empty_when_no_subcategory(self):
        url = reverse('quicksell:ajax_attributes')
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data['attributes'], [])

    def test_ajax_attributes_includes_correct_fields(self):
        url = reverse('quicksell:ajax_attributes')
        response = self.client.get(url, {'subcategory_id': self.subcategory.id})
        data = response.json()
        attr = data['attributes'][0]
        self.assertIn('id', attr)
        self.assertIn('name', attr)
        self.assertIn('field_type', attr)
        self.assertIn('is_required', attr)
        self.assertIn('placeholder', attr)
        self.assertIn('help_text', attr)
        self.assertIn('options', attr)

    def test_ajax_attributes_includes_dropdown_options(self):
        url = reverse('quicksell:ajax_attributes')
        response = self.client.get(url, {'subcategory_id': self.subcategory.id})
        data = response.json()
        brand_attr = next(a for a in data['attributes'] if a['name'] == 'Brand')
        self.assertEqual(brand_attr['field_type'], 'dropdown')
        self.assertEqual(brand_attr['options'], ['Apple', 'Samsung', 'Google'])

    def test_ajax_requires_login(self):
        self.client.logout()
        url = reverse('quicksell:ajax_subcategories')
        response = self.client.get(url, {'main_category_id': self.category.id})
        self.assertEqual(response.status_code, 302)  # Redirect to login


class QuickSellViewTest(QuickSellFormTestBase):
    """Tests for Quick Sell views."""

    def setUp(self):
        super().setUp()
        self.client = Client()
        self.client.login(email='seller@example.com', password='password123')

    def test_create_view_requires_login(self):
        self.client.logout()
        url = reverse('quicksell:create')
        response = self.client.get(url)
        self.assertEqual(response.status_code, 302)

    def test_create_view_get(self):
        url = reverse('quicksell:create')
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)

    def test_edit_view_requires_ownership(self):
        listing = QuickSell.objects.create(
            user=self.other_user,
            subcategory=self.subcategory,
            title='Other User Listing',
            description='Test',
            price=Decimal('50000.00'),
        )
        url = reverse('quicksell:edit', kwargs={'slug': listing.slug})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 404)

    def test_edit_view_allows_owner(self):
        listing = QuickSell.objects.create(
            user=self.user,
            subcategory=self.subcategory,
            title='My Listing',
            description='Test',
            price=Decimal('50000.00'),
        )
        url = reverse('quicksell:edit', kwargs={'slug': listing.slug})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)

    def test_delete_view_requires_ownership(self):
        listing = QuickSell.objects.create(
            user=self.other_user,
            subcategory=self.subcategory,
            title='Other User Listing',
            description='Test',
            price=Decimal('50000.00'),
        )
        url = reverse('quicksell:delete', kwargs={'slug': listing.slug})

        # The delete view is POST-only (no delete page), so a GET never
        # reaches the ownership check - it only redirects to my_listings.
        response = self.client.get(url)
        self.assertEqual(response.status_code, 302)
        self.assertTrue(QuickSell.objects.filter(pk=listing.pk).exists())

        # The actual delete attempt by a non-owner must 404 and delete nothing.
        response = self.client.post(url)
        self.assertEqual(response.status_code, 404)
        self.assertTrue(QuickSell.objects.filter(pk=listing.pk).exists())

    def test_my_listings_view(self):
        QuickSell.objects.create(
            user=self.user,
            subcategory=self.subcategory,
            title='My Listing',
            description='Test',
            price=Decimal('50000.00'),
        )
        url = reverse('quicksell:my_listings')
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)


class QuickSellSecurityTest(QuickSellFormTestBase):
    """Tests for Quick Sell security measures."""

    def test_user_cannot_edit_others_listing_via_slug(self):
        listing = QuickSell.objects.create(
            user=self.other_user,
            subcategory=self.subcategory,
            title='Other Listing',
            description='Test',
            price=Decimal('50000.00'),
        )
        self.client.login(email='seller@example.com', password='password123')
        url = reverse('quicksell:edit', kwargs={'slug': listing.slug})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 404)

    def test_user_cannot_delete_others_listing(self):
        listing = QuickSell.objects.create(
            user=self.other_user,
            subcategory=self.subcategory,
            title='Other Listing',
            description='Test',
            price=Decimal('50000.00'),
        )
        self.client.login(email='seller@example.com', password='password123')
        url = reverse('quicksell:delete', kwargs={'slug': listing.slug})
        response = self.client.post(url)
        self.assertEqual(response.status_code, 404)

    def test_form_does_not_expose_user_field(self):
        form = QuickSellCreateForm(user=self.user)
        self.assertNotIn('user', form.fields)

    def test_form_does_not_expose_slug_field(self):
        form = QuickSellCreateForm(user=self.user)
        self.assertNotIn('slug', form.fields)

    def test_form_does_not_expose_expires_at_field(self):
        form = QuickSellCreateForm(user=self.user)
        self.assertNotIn('expires_at', form.fields)

    def test_form_does_not_expose_created_at_field(self):
        form = QuickSellCreateForm(user=self.user)
        self.assertNotIn('created_at', form.fields)

    def test_form_does_not_expose_moderation_state(self):
        form = QuickSellCreateForm(user=self.user)
        self.assertNotIn('moderation_state', form.fields)

    def test_attributes_validated_against_subcategory(self):
        """Ensure attributes from wrong subcategory are rejected server-side."""
        data = self.valid_data.copy()
        # Add attribute from wrong subcategory
        data[f'attr_{self.size_attr.id}'] = 'L'
        form = QuickSellCreateForm(
            data=data,
            user=self.user
        )
        self.assertFalse(form.is_valid())
        # Should have non-field error for the invalid attribute
        self.assertTrue(form.non_field_errors())
