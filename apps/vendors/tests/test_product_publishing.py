from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.vendors.models import Product, Store, MainCategory, SubCategory
from apps.users.models import CustomUser
from apps.marketplace.models import SubOrder, MainOrder


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

    def test_vendor_order_reject_redirects_to_existing_order_list(self):
        from apps.marketplace.models import MainOrder

        main_order = MainOrder.objects.create(
            reference='REF-TEST',
            buyer=self.user,
            total=110.00,
            payment_status='SUCCESS',
            delivery_address='Lagos',
            delivery_phone='08012345678',
        )

        sub_order = SubOrder.objects.create(
            main_order=main_order,
            store=self.store,
            subtotal=100.00,
            status='PENDING_VENDOR',
            payment_status='SUCCESS',
            vendor_deadline=timezone.now(),
        )

        self.vendor.bank_status = 'verified'
        self.vendor.verification_status = 'approved'
        self.vendor.save(update_fields=['bank_status', 'verification_status'])

        self.client.force_login(self.user)
        response = self.client.post(
            reverse('vendors:vendor_order_reject', kwargs={'suborder_id': sub_order.id}),
            {'rejection_reason': 'Out of stock'}
        )

        self.assertEqual(response.status_code, 302)
        self.assertRedirects(response, reverse('vendors:orders_list'))

    def test_buyer_order_views_show_vendor_rejection_reason(self):
        buyer = CustomUser.objects.create_user(
            email='buyer@example.com',
            password='password123',
            username='buyer',
            role='buyer',
        )
        main_order = MainOrder.objects.create(
            reference='REF-BUYER-TEST',
            buyer=buyer,
            total=110.00,
            payment_status='REFUNDED',
            delivery_address='Lagos',
            delivery_phone='08012345678',
        )
        sub_order = SubOrder.objects.create(
            main_order=main_order,
            store=self.store,
            subtotal=100.00,
            status='REFUNDED',
            payment_status='REFUNDED',
            vendor_deadline=timezone.now(),
            rejection_reason='We are currently out of stock.',
        )

        self.client.force_login(buyer)
        order_list_response = self.client.get(reverse('marketplace:order_list'))
        self.assertContains(order_list_response, 'Reason from vendor')
        self.assertContains(order_list_response, 'We are currently out of stock.')

        order_detail_response = self.client.get(reverse('marketplace:order_detail', kwargs={'order_number': main_order.order_number}))
        self.assertContains(order_detail_response, 'Reason from vendor')
        self.assertContains(order_detail_response, 'We are currently out of stock.')

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
