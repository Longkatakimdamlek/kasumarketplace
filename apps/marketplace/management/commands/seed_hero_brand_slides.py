"""
Management command: seed_hero_brand_slides
Creates 5 placeholder hero_brand Promotion records for the mobile hero carousel.

Usage:
    python manage.py seed_hero_brand_slides
"""

from django.core.management.base import BaseCommand

from apps.marketplace.models import Promotion


SLIDES = [
    {
        'title': 'Campus Essentials',
        'subtitle': 'Everything you need for campus life',
        'link_url': '/',
        'sort_order': 1,
    },
    {
        'title': 'Tech & Electronics',
        'subtitle': 'Phones, laptops, and gadgets',
        'link_url': '/category/tech-electronics/',
        'sort_order': 2,
    },
    {
        'title': 'Fashion & Accessories',
        'subtitle': 'Style that fits your vibe',
        'link_url': '/category/fashion-accessories/',
        'sort_order': 3,
    },
    {
        'title': 'Food & Beverages',
        'subtitle': 'Quick bites and campus favourites',
        'link_url': '/category/food-beverages/',
        'sort_order': 4,
    },
    {
        'title': 'Deals & Marketplace',
        'subtitle': 'Discounts you don\'t want to miss',
        'link_url': '/deals/',
        'sort_order': 5,
    },
]


class Command(BaseCommand):
    help = "Seed 5 hero_brand Promotion records for the mobile hero carousel."

    def handle(self, *args, **options):
        created = 0
        skipped = 0
        for slide_data in SLIDES:
            obj, was_created = Promotion.objects.get_or_create(
                title=slide_data['title'],
                slide_type='hero_brand',
                defaults={
                    'subtitle': slide_data['subtitle'],
                    'link_url': slide_data['link_url'],
                    'sort_order': slide_data['sort_order'],
                    'is_active': True,
                },
            )
            if was_created:
                created += 1
                self.stdout.write(self.style.SUCCESS(
                    f"  Created: {obj.title} -> {obj.link_url} (sort_order={obj.sort_order})"
                ))
            else:
                skipped += 1
                self.stdout.write(self.style.WARNING(
                    f"  Skipped (already exists): {obj.title}"
                ))

        self.stdout.write(self.style.SUCCESS(
            f"\nDone. Created {created} slide(s), skipped {skipped}."
        ))
