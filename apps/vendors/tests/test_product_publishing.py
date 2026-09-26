from django.test import TestCase
from django.urls import reverse

from apps.vendors.models import Product, Store, MainCategory, SubCategory
from apps.users.models import CustomUser


class ProductPublishingTest(TestCase):
    def setUp(self):
        self.user = CustomUser.objects.create_user(
            email='vendor@example.com',
            password='password123',
            username='vendor',
            role='vendor',
        )
        self.vendor = self.user.vendorprofile
        self.category = MainCategory.objects.create(name='Tech', slug='tech')
        self.subcategory = SubCategory.objects.create(
            main_category=self.category,
            name='Phones',
            slug='phones',
        )
        self.store = Store.objects.create(
            vendor=self.vendor,
            store_name='Test Store',
            slug='test-store',
            main_category=self.category,
            is_published=False,
        )

    def test_publishing_product_makes_store_visible(self):
        product = Product.objects.create(
            vendor=self.vendor,
            store=self.store,
            subcategory=self.subcategory,
            title='Test Product',
            slug='test-product',
            description='Desc',
            price='10.00',
            status='draft',
        )

        product.status = 'published'
        product.save()

        self.store.refresh_from_db()
        self.assertTrue(self.store.is_published)
        self.assertEqual(product.status, 'published')

    def test_store_settings_edit_preserves_published_state(self):
        self.store.is_published = True
        self.store.save(update_fields=['is_published'])

        self.client.force_login(self.user)
        response = self.client.post(reverse('vendors:store_settings'), data={
            'store_name': self.store.store_name,
            'main_category': self.category.id,
            'tagline': 'A great store',
            'description': 'A store description',
            'phone': '08012345678',
            'business_email': 'store@example.com',
            'whatsapp': '08012345678',
            'address': 'Lagos',
            'instagram': '',
            'facebook': '',
            'twitter': '',
            'shipping_policy': '',
            'return_policy': '',
        })

        self.assertEqual(response.status_code, 302)
        self.store.refresh_from_db()
        self.assertTrue(self.store.is_published)

    def test_delete_confirmation_page_uses_standard_submit_flow(self):
        self.vendor.bank_status = 'verified'
        self.vendor.save(update_fields=['bank_status'])

        product = Product.objects.create(
            vendor=self.vendor,
            store=self.store,
            subcategory=self.subcategory,
            title='Delete Me',
            slug='delete-me',
            description='Desc',
            price='10.00',
            status='draft',
        )

        self.client.force_login(self.user)
        response = self.client.get(reverse('vendors:product_delete', kwargs={'slug': product.slug}))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'id="delete-product-form"')
        self.assertContains(response, 'id="confirm-delete-button"')
        self.assertContains(response, 'id="delete-confirmation"')
        self.assertNotContains(response, 'x-model="confirmed"')
        self.assertNotContains(response, '@click="deleting = true"')
