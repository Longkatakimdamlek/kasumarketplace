"""
Quick Sell Model Tests

Tests for QuickSell, QuickSellImage, and QuickSellReport models.
"""

from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from apps.quicksell.models import QuickSell, QuickSellImage, QuickSellReport
from apps.users.models import CustomUser
from apps.vendors.models import MainCategory, SubCategory


class QuickSellModelTest(TestCase):
    """Tests for the QuickSell model."""

    def setUp(self):
        self.user = CustomUser.objects.create_user(
            email='seller@example.com',
            password='password123',
            username='seller',
            role='buyer',
        )
        self.category = MainCategory.objects.create(
            name='Tech', slug='tech'
        )
        self.subcategory = SubCategory.objects.create(
            main_category=self.category,
            name='Phones',
            slug='phones',
        )

    def test_create_listing(self):
        listing = QuickSell.objects.create(
            user=self.user,
            subcategory=self.subcategory,
            title='iPhone 15',
            description='Used iPhone 15 for sale',
            price=Decimal('250000.00'),
            whatsapp='08012345678',
            phone='08012345678',
        )
        self.assertEqual(listing.title, 'iPhone 15')
        self.assertEqual(listing.user, self.user)
        self.assertEqual(listing.subcategory, self.subcategory)
        self.assertEqual(listing.price, Decimal('250000.00'))
        self.assertIsNotNone(listing.slug)
        self.assertIsNotNone(listing.expires_at)

    def test_slug_auto_generated(self):
        listing = QuickSell.objects.create(
            user=self.user,
            subcategory=self.subcategory,
            title='Samsung Galaxy S24',
            description='Brand new Samsung Galaxy S24',
            price=Decimal('180000.00'),
        )
        self.assertEqual(listing.slug, 'samsung-galaxy-s24')

    def test_slug_uniqueness(self):
        listing1 = QuickSell.objects.create(
            user=self.user,
            subcategory=self.subcategory,
            title='iPhone 15',
            description='First listing',
            price=Decimal('250000.00'),
        )
        listing2 = QuickSell.objects.create(
            user=self.user,
            subcategory=self.subcategory,
            title='iPhone 15',
            description='Second listing',
            price=Decimal('260000.00'),
        )
        self.assertNotEqual(listing1.slug, listing2.slug)
        self.assertEqual(listing2.slug, 'iphone-15-1')

    def test_expires_at_set_on_creation(self):
        listing = QuickSell.objects.create(
            user=self.user,
            subcategory=self.subcategory,
            title='Test Item',
            description='Test',
            price=Decimal('1000.00'),
        )
        self.assertIsNotNone(listing.expires_at)
        delta = listing.expires_at - timezone.now()
        self.assertAlmostEqual(delta.days, 10, delta=1)

    def test_is_active_property(self):
        listing = QuickSell.objects.create(
            user=self.user,
            subcategory=self.subcategory,
            title='Active Item',
            description='Test',
            price=Decimal('1000.00'),
        )
        self.assertTrue(listing.is_active)

    def test_is_active_expired(self):
        listing = QuickSell.objects.create(
            user=self.user,
            subcategory=self.subcategory,
            title='Expired Item',
            description='Test',
            price=Decimal('1000.00'),
        )
        listing.expires_at = timezone.now() - timezone.timedelta(days=1)
        listing.save(update_fields=['expires_at'])
        listing.refresh_from_db()
        self.assertFalse(listing.is_active)

    def test_days_remaining(self):
        listing = QuickSell.objects.create(
            user=self.user,
            subcategory=self.subcategory,
            title='Countdown Item',
            description='Test',
            price=Decimal('1000.00'),
        )
        days = listing.days_remaining
        self.assertIn(days, [9, 10])

    def test_days_remaining_expired(self):
        listing = QuickSell.objects.create(
            user=self.user,
            subcategory=self.subcategory,
            title='Expired Item',
            description='Test',
            price=Decimal('1000.00'),
        )
        listing.expires_at = timezone.now() - timezone.timedelta(days=1)
        listing.save(update_fields=['expires_at'])
        listing.refresh_from_db()
        self.assertEqual(listing.days_remaining, 0)

    def test_main_category_property(self):
        listing = QuickSell.objects.create(
            user=self.user,
            subcategory=self.subcategory,
            title='Category Test',
            description='Test',
            price=Decimal('1000.00'),
        )
        self.assertEqual(listing.main_category, self.category)

    def test_str(self):
        listing = QuickSell.objects.create(
            user=self.user,
            subcategory=self.subcategory,
            title='My Item',
            description='Test',
            price=Decimal('1000.00'),
        )
        self.assertEqual(str(listing), 'My Item')

    def test_user_set_null_on_delete(self):
        listing = QuickSell.objects.create(
            user=self.user,
            subcategory=self.subcategory,
            title='Orphan Test',
            description='Test',
            price=Decimal('1000.00'),
        )
        self.user.delete()
        listing.refresh_from_db()
        self.assertIsNone(listing.user)


class QuickSellQuerySetTest(TestCase):
    """Tests for the QuickSell custom QuerySet."""

    def setUp(self):
        self.user = CustomUser.objects.create_user(
            email='seller@example.com',
            password='password123',
            username='seller',
            role='buyer',
        )
        self.category = MainCategory.objects.create(
            name='Fashion', slug='fashion'
        )
        self.subcategory = SubCategory.objects.create(
            main_category=self.category,
            name='Clothes',
            slug='clothes',
        )

    def test_active_excludes_expired(self):
        active = QuickSell.objects.create(
            user=self.user,
            subcategory=self.subcategory,
            title='Active Listing',
            description='Test',
            price=Decimal('5000.00'),
        )
        expired = QuickSell.objects.create(
            user=self.user,
            subcategory=self.subcategory,
            title='Expired Listing',
            description='Test',
            price=Decimal('3000.00'),
        )
        expired.expires_at = timezone.now() - timezone.timedelta(days=1)
        expired.save(update_fields=['expires_at'])

        active_qs = QuickSell.objects.active()
        expired_qs = QuickSell.objects.expired()

        self.assertIn(active, active_qs)
        self.assertNotIn(expired, active_qs)
        self.assertIn(expired, expired_qs)
        self.assertNotIn(active, expired_qs)

    def test_active_empty_when_all_expired(self):
        expired = QuickSell.objects.create(
            user=self.user,
            subcategory=self.subcategory,
            title='Old Listing',
            description='Test',
            price=Decimal('1000.00'),
        )
        expired.expires_at = timezone.now() - timezone.timedelta(days=5)
        expired.save(update_fields=['expires_at'])

        self.assertEqual(QuickSell.objects.active().count(), 0)
        self.assertEqual(QuickSell.objects.expired().count(), 1)


class QuickSellImageModelTest(TestCase):
    """Tests for the QuickSellImage model."""

    def setUp(self):
        self.user = CustomUser.objects.create_user(
            email='seller@example.com',
            password='password123',
            username='seller',
            role='buyer',
        )
        self.category = MainCategory.objects.create(
            name='Home', slug='home'
        )
        self.subcategory = SubCategory.objects.create(
            main_category=self.category,
            name='Furniture',
            slug='furniture',
        )
        self.listing = QuickSell.objects.create(
            user=self.user,
            subcategory=self.subcategory,
            title='Wooden Table',
            description='Beautiful wooden table',
            price=Decimal('45000.00'),
        )

    def test_image_belongs_to_listing(self):
        image = QuickSellImage.objects.create(
            quicksell=self.listing,
            alt_text='Table front view',
            is_primary=True,
            sort_order=0,
        )
        self.assertEqual(image.quicksell, self.listing)
        self.assertIn(image, self.listing.images.all())

    def test_multiple_images_per_listing(self):
        QuickSellImage.objects.create(quicksell=self.listing, sort_order=0)
        QuickSellImage.objects.create(quicksell=self.listing, sort_order=1)
        QuickSellImage.objects.create(quicksell=self.listing, sort_order=2)
        self.assertEqual(self.listing.images.count(), 3)

    def test_image_ordering(self):
        img2 = QuickSellImage.objects.create(quicksell=self.listing, sort_order=2)
        img0 = QuickSellImage.objects.create(quicksell=self.listing, sort_order=0)
        img1 = QuickSellImage.objects.create(quicksell=self.listing, sort_order=1)
        images = list(self.listing.images.all())
        self.assertEqual(images, [img0, img1, img2])

    def test_str(self):
        image = QuickSellImage.objects.create(quicksell=self.listing, sort_order=3)
        self.assertEqual(str(image), 'Wooden Table - Image 3')

    def test_cascade_delete(self):
        QuickSellImage.objects.create(quicksell=self.listing, sort_order=0)
        QuickSellImage.objects.create(quicksell=self.listing, sort_order=1)
        self.assertEqual(QuickSellImage.objects.count(), 2)
        self.listing.delete()
        self.assertEqual(QuickSellImage.objects.count(), 0)


class QuickSellReportModelTest(TestCase):
    """Tests for the QuickSellReport model."""

    def setUp(self):
        self.seller = CustomUser.objects.create_user(
            email='seller@example.com',
            password='password123',
            username='seller',
            role='buyer',
        )
        self.reporter = CustomUser.objects.create_user(
            email='reporter@example.com',
            password='password123',
            username='reporter',
            role='buyer',
        )
        self.category = MainCategory.objects.create(
            name='Electronics', slug='electronics'
        )
        self.subcategory = SubCategory.objects.create(
            main_category=self.category,
            name='Laptops',
            slug='laptops',
        )
        self.listing = QuickSell.objects.create(
            user=self.seller,
            subcategory=self.subcategory,
            title='MacBook Pro',
            description='MacBook Pro 2023',
            price=Decimal('850000.00'),
        )

    def test_create_report(self):
        report = QuickSellReport.objects.create(
            reporter=self.reporter,
            quicksell=self.listing,
            reason='counterfeit',
            details='This is not a real MacBook',
            reporter_ip='127.0.0.1',
        )
        self.assertEqual(report.quicksell, self.listing)
        self.assertEqual(report.reporter, self.reporter)
        self.assertEqual(report.status, 'pending')

    def test_anonymous_report(self):
        report = QuickSellReport.objects.create(
            quicksell=self.listing,
            reason='prohibited',
        )
        self.assertIsNone(report.reporter)

    def test_report_status_choices(self):
        report = QuickSellReport.objects.create(
            reporter=self.reporter,
            quicksell=self.listing,
            reason='other',
        )
        valid_statuses = ['pending', 'reviewed', 'actioned', 'dismissed']
        for status in valid_statuses:
            report.status = status
            report.save(update_fields=['status'])
            self.assertEqual(report.status, status)

    def test_cascade_delete_listing(self):
        QuickSellReport.objects.create(
            reporter=self.reporter,
            quicksell=self.listing,
            reason='misleading',
        )
        self.assertEqual(QuickSellReport.objects.count(), 1)
        self.listing.delete()
        self.assertEqual(QuickSellReport.objects.count(), 0)

    def test_str_with_reporter(self):
        report = QuickSellReport.objects.create(
            reporter=self.reporter,
            quicksell=self.listing,
            reason='other',
        )
        self.assertIn('reporter@example.com', str(report))

    def test_str_without_reporter(self):
        report = QuickSellReport.objects.create(
            quicksell=self.listing,
            reason='other',
        )
        self.assertIn('Anonymous', str(report))
