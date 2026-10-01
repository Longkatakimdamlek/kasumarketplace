"""
Phase C Follow-Up Tests
=======================
FIX 1: Vendor self-views excluded from ProductView tracking
FIX 2: ContactIntent for authenticated buyer (force_login)
FIX 3: B7 same-store vs similar-to-wishlist de-duplication
"""

from django.test import TestCase, Client
from django.urls import reverse
from django.utils import timezone
from datetime import timedelta

from apps.users.models import CustomUser
from apps.vendors.models import VendorProfile, Store, Product, MainCategory, SubCategory, Subscription, Notification
from apps.marketplace.models import ProductView, ContactIntent, Wishlist


class Fix1VendorSelfViewExclusionTest(TestCase):
    """FIX 1: Verify vendor self-views do NOT create ProductView rows."""

    def setUp(self):
        # Create vendor user
        self.vendor_user = CustomUser.objects.create_user(
            email='vendor@test.com',
            password='testpass123',
            username='vendor1',
            role='vendor',
        )
        self.vendor = self.vendor_user.vendorprofile
        # Subscription is auto-created by signal; ensure trial is active
        sub, _ = Subscription.objects.get_or_create(
            vendor=self.vendor,
            defaults={
                'status': 'trial',
                'trial_ends_at': timezone.now() + timedelta(days=90),
            },
        )
        if sub.trial_ends_at is None or sub.trial_ends_at < timezone.now():
            sub.status = 'trial'
            sub.trial_ends_at = timezone.now() + timedelta(days=90)
            sub.save(update_fields=['status', 'trial_ends_at'])

        # Create category/subcategory
        self.category = MainCategory.objects.create(name='Fashion', slug='fashion')
        self.subcategory = SubCategory.objects.create(
            main_category=self.category,
            name='Shoes',
            slug='shoes',
        )

        # Create store
        self.store = Store.objects.create(
            vendor=self.vendor,
            store_name='Vendor Store',
            slug='vendor-store',
            main_category=self.category,
            is_published=True,
        )

        # Create published product
        self.product = Product.objects.create(
            vendor=self.vendor,
            store=self.store,
            subcategory=self.subcategory,
            title='Test Shoes',
            slug='test-shoes',
            description='Nice shoes',
            price='50.00',
            status='published',
        )

        # Create buyer user
        self.buyer_user = CustomUser.objects.create_user(
            email='buyer@test.com',
            password='testpass123',
            username='buyer1',
            role='buyer',
        )

    def test_vendor_self_view_does_not_create_productview(self):
        """When the owning vendor views their own product, no ProductView row is created."""
        self.client.force_login(self.vendor_user)
        initial_count = ProductView.objects.filter(product=self.product).count()
        self.client.get(
            reverse('product_detail_public', kwargs={
                'store_slug': self.store.slug,
                'product_slug': self.product.slug,
            })
        )
        self.assertEqual(
            ProductView.objects.filter(product=self.product).count(),
            initial_count,
            "Vendor self-view should NOT create a ProductView row",
        )
        # views_count should still increment
        self.product.refresh_from_db()
        self.assertEqual(self.product.views_count, 1)

    def test_buyer_view_creates_productview(self):
        """When a buyer views the product, a ProductView row IS created."""
        self.client.force_login(self.buyer_user)
        self.client.get(
            reverse('product_detail_public', kwargs={
                'store_slug': self.store.slug,
                'product_slug': self.product.slug,
            })
        )
        pv = ProductView.objects.filter(
            product=self.product,
            user=self.buyer_user,
        )
        self.assertEqual(pv.count(), 1, "Buyer view should create a ProductView row")
        self.assertEqual(pv.first().store, self.store)

    def test_anonymous_view_creates_productview(self):
        """When an anonymous user views the product, a ProductView row IS created."""
        self.client.get(
            reverse('product_detail_public', kwargs={
                'store_slug': self.store.slug,
                'product_slug': self.product.slug,
            })
        )
        pv = ProductView.objects.filter(
            product=self.product,
            user=None,
        )
        self.assertTrue(pv.exists(), "Anonymous view should create a ProductView row")

    def test_vendor_then_buyer_views(self):
        """Vendor view doesn't create row; buyer view does."""
        # Vendor views
        self.client.force_login(self.vendor_user)
        self.client.get(
            reverse('product_detail_public', kwargs={
                'store_slug': self.store.slug,
                'product_slug': self.product.slug,
            })
        )
        self.assertEqual(ProductView.objects.filter(product=self.product).count(), 0)

        # Buyer views
        self.client.force_login(self.buyer_user)
        self.client.get(
            reverse('product_detail_public', kwargs={
                'store_slug': self.store.slug,
                'product_slug': self.product.slug,
            })
        )
        self.assertEqual(ProductView.objects.filter(product=self.product).count(), 1)


class Fix2ContactIntentAuthenticatedBuyerTest(TestCase):
    """FIX 2: Verify ContactIntent works for authenticated buyers."""

    def setUp(self):
        self.vendor_user = CustomUser.objects.create_user(
            email='vendor_ci@test.com',
            password='testpass123',
            username='vendor_ci',
            role='vendor',
        )
        self.vendor = self.vendor_user.vendorprofile
        sub, _ = Subscription.objects.get_or_create(
            vendor=self.vendor,
            defaults={
                'status': 'trial',
                'trial_ends_at': timezone.now() + timedelta(days=90),
            },
        )
        if sub.trial_ends_at is None or sub.trial_ends_at < timezone.now():
            sub.status = 'trial'
            sub.trial_ends_at = timezone.now() + timedelta(days=90)
            sub.save(update_fields=['status', 'trial_ends_at'])

        self.category = MainCategory.objects.create(name='Tech', slug='tech-ci')
        self.subcategory = SubCategory.objects.create(
            main_category=self.category,
            name='Phones',
            slug='phones-ci',
        )
        self.store = Store.objects.create(
            vendor=self.vendor,
            store_name='CI Store',
            slug='ci-store',
            main_category=self.category,
            is_published=True,
        )
        self.product = Product.objects.create(
            vendor=self.vendor,
            store=self.store,
            subcategory=self.subcategory,
            title='Test Phone',
            slug='test-phone-ci',
            description='A phone',
            price='200.00',
            status='published',
        )

        self.buyer_user = CustomUser.objects.create_user(
            email='buyer_ci@test.com',
            password='testpass123',
            username='buyer_ci',
            role='buyer',
        )

    def test_contact_intent_user_field_set_for_authenticated_buyer(self):
        """ContactIntent.user is set to the buyer when authenticated."""
        self.client.force_login(self.buyer_user)
        response = self.client.post(
            reverse('vendors:contact_intent', kwargs={'product_id': self.product.id}),
            data={'channel': 'call'},
        )
        self.assertEqual(response.status_code, 200)
        ci = ContactIntent.objects.filter(
            product=self.product,
            user=self.buyer_user,
        ).first()
        self.assertIsNotNone(ci, "ContactIntent should be created for the buyer")
        self.assertEqual(ci.user, self.buyer_user)

    def test_contact_intent_notification_shows_buyer_email(self):
        """Vendor notification shows buyer email, not 'a visitor'."""
        self.client.force_login(self.buyer_user)
        self.client.post(
            reverse('vendors:contact_intent', kwargs={'product_id': self.product.id}),
            data={'channel': 'whatsapp'},
        )
        notif = Notification.objects.filter(
            user=self.vendor_user,
            notification_type='system',
        ).order_by('-created_at').first()
        self.assertIsNotNone(notif)
        self.assertIn(self.buyer_user.email, notif.message)
        self.assertNotIn('a visitor', notif.message)

    def test_contact_intent_anonymous_user_gets_session_key(self):
        """Anonymous contact intent gets session_key, no user."""
        response = self.client.post(
            reverse('vendors:contact_intent', kwargs={'product_id': self.product.id}),
            data={'channel': 'call'},
        )
        self.assertEqual(response.status_code, 200)
        ci = ContactIntent.objects.filter(product=self.product).order_by('-contacted_at').first()
        self.assertIsNone(ci.user)
        self.assertTrue(len(ci.session_key) > 0)


class Fix3DeduplicationTest(TestCase):
    """FIX 3: B7 same-store vs similar-to-wishlist de-duplication."""

    def setUp(self):
        self.category = MainCategory.objects.create(name='Fashion', slug='fashion-dedup')
        self.subcategory = SubCategory.objects.create(
            main_category=self.category,
            name='Bags',
            slug='bags-dedup',
        )

        # Store X vendor
        self.vendor_x_user = CustomUser.objects.create_user(
            email='vendorx@dedup.com',
            password='testpass123',
            username='vendorx',
            role='vendor',
        )
        self.vendor_x = self.vendor_x_user.vendorprofile
        sub_x, _ = Subscription.objects.get_or_create(
            vendor=self.vendor_x,
            defaults={
                'status': 'trial',
                'trial_ends_at': timezone.now() + timedelta(days=90),
            },
        )
        if sub_x.trial_ends_at is None or sub_x.trial_ends_at < timezone.now():
            sub_x.status = 'trial'
            sub_x.trial_ends_at = timezone.now() + timedelta(days=90)
            sub_x.save(update_fields=['status', 'trial_ends_at'])

        self.store_x = Store.objects.create(
            vendor=self.vendor_x,
            store_name='Store X',
            slug='store-x-dedup',
            main_category=self.category,
            is_published=True,
        )

        # Store Z vendor (different store, same subcategory)
        self.vendor_z_user = CustomUser.objects.create_user(
            email='vendorz@dedup.com',
            password='testpass123',
            username='vendorz',
            role='vendor',
        )
        self.vendor_z = self.vendor_z_user.vendorprofile
        sub_z, _ = Subscription.objects.get_or_create(
            vendor=self.vendor_z,
            defaults={
                'status': 'trial',
                'trial_ends_at': timezone.now() + timedelta(days=90),
            },
        )
        if sub_z.trial_ends_at is None or sub_z.trial_ends_at < timezone.now():
            sub_z.status = 'trial'
            sub_z.trial_ends_at = timezone.now() + timedelta(days=90)
            sub_z.save(update_fields=['status', 'trial_ends_at'])

        self.store_z = Store.objects.create(
            vendor=self.vendor_z,
            store_name='Store Z',
            slug='store-z-dedup',
            main_category=self.category,
            is_published=True,
        )

        # Existing product in Store X, Subcategory Y
        self.existing_product = Product.objects.create(
            vendor=self.vendor_x,
            store=self.store_x,
            subcategory=self.subcategory,
            title='Existing Bag X',
            slug='existing-bag-x',
            description='A bag',
            price='30.00',
            status='published',
        )

        # Buyer who wishlists the existing product from Store X
        self.buyer = CustomUser.objects.create_user(
            email='buyer_dedup@dedup.com',
            password='testpass123',
            username='buyer_dedup',
            role='buyer',
        )
        Wishlist.objects.create(user=self.buyer, product=self.existing_product)

    def _clear_notifications(self):
        Notification.objects.all().delete()

    def _get_wishlist_notifications(self):
        return Notification.objects.filter(
            user=self.buyer,
            notification_type='wishlist',
        ).order_by('created_at')

    def test_same_store_notification_fires_not_similar(self):
        """
        Publish a new product from Store X (same store as wishlisted product)
        in the same subcategory. Buyer should receive EXACTLY ONE notification,
        and it should be the same-store version.
        """
        self._clear_notifications()

        new_product = Product.objects.create(
            vendor=self.vendor_x,
            store=self.store_x,
            subcategory=self.subcategory,
            title='New Bag X',
            slug='new-bag-x',
            description='Another bag',
            price='40.00',
            status='published',
        )

        notifs = self._get_wishlist_notifications()
        self.assertEqual(notifs.count(), 1, f"Expected 1 notification, got {notifs.count()}: {list(notifs.values('title', 'message'))}")
        notif = notifs.first()
        self.assertEqual(notif.title, f'New Product from {self.store_x.store_name}!')
        self.assertIn(self.store_x.store_name, notif.message)
        self.assertNotEqual(notif.title, 'Similar to Your Wishlist!')

    def test_different_store_fires_similar_notification(self):
        """
        Publish a new product from Store Z (different store, same subcategory).
        Buyer should receive the similar-to-wishlist notification.
        """
        self._clear_notifications()

        new_product = Product.objects.create(
            vendor=self.vendor_z,
            store=self.store_z,
            subcategory=self.subcategory,
            title='New Bag Z',
            slug='new-bag-z',
            description='Another bag from Z',
            price='35.00',
            status='published',
        )

        notifs = self._get_wishlist_notifications()
        self.assertEqual(notifs.count(), 1, f"Expected 1 notification, got {notifs.count()}: {list(notifs.values('title', 'message'))}")
        notif = notifs.first()
        self.assertEqual(notif.title, 'Similar to Your Wishlist!')
        self.assertIn(new_product.title, notif.message)

    def test_same_store_and_different_store_independently(self):
        """
        Control test: Publish one product from Store X and one from Store Z.
        Buyer gets same-store notification for Store X's product, and
        similar notification for Store Z's product.
        """
        self._clear_notifications()

        product_x = Product.objects.create(
            vendor=self.vendor_x,
            store=self.store_x,
            subcategory=self.subcategory,
            title='Bag from X',
            slug='bag-from-x',
            description='bag',
            price='25.00',
            status='published',
        )
        product_z = Product.objects.create(
            vendor=self.vendor_z,
            store=self.store_z,
            subcategory=self.subcategory,
            title='Bag from Z',
            slug='bag-from-z',
            description='bag',
            price='28.00',
            status='published',
        )

        notifs = self._get_wishlist_notifications()
        titles = list(notifs.values_list('title', flat=True))
        self.assertEqual(notifs.count(), 2, f"Expected 2 notifications, got {notifs.count()}: {titles}")

        store_x_title = f'New Product from {self.store_x.store_name}!'
        self.assertIn(store_x_title, titles, f"Same-store notification missing. Got: {titles}")
        self.assertIn('Similar to Your Wishlist!', titles, f"Similar notification missing. Got: {titles}")

    def test_no_duplicate_for_same_store_buyer(self):
        """
        When Store X publishes a product in the same subcategory as a wishlisted
        product, the buyer should NOT also get a 'Similar to Your Wishlist!'
        notification (de-duplication).
        """
        self._clear_notifications()

        new_product = Product.objects.create(
            vendor=self.vendor_x,
            store=self.store_x,
            subcategory=self.subcategory,
            title='Dedup Bag',
            slug='dedup-bag',
            description='bag',
            price='45.00',
            status='published',
        )

        notifs = self._get_wishlist_notifications()
        # Should get exactly 1 notification: same-store version
        self.assertEqual(notifs.count(), 1)
        notif = notifs.first()
        self.assertEqual(notif.title, f'New Product from {self.store_x.store_name}!')
        self.assertNotEqual(notif.title, 'Similar to Your Wishlist!',
                            "Should NOT get similar-to-wishlist notification for same-store buyer")
