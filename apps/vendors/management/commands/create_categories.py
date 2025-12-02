from django.core.management.base import BaseCommand
from apps.vendors.models import MainCategory, SubCategory


class Command(BaseCommand):
    help = 'Create initial main categories and subcategories for KasuMarketplace'

    def handle(self, *args, **kwargs):
        categories_data = {
            'Fashion & Accessories': [
                'Clothes', 'Shoes', 'Jewelry', 'Bags', 'Sunglasses', 'Watches', 'Luxury items'
            ],
            'Tech & Electronics': [
                'Phones', 'Tablets', 'Laptops', 'Accessories (chargers, cases, earphones, power banks)', 'Speakers'
            ],
            'Food & Beverages': [
                'Snacks', 'Drinks', 'Fresh food', 'Homemade meals', 'Packaged food'
            ],
            'Beauty & Personal Care': [
                'Skincare', 'Hair products', 'Makeup', 'Perfumes', 'Deodorants', 'Grooming kits'
            ],
            'Education & Stationery': [
                'Textbooks', 'Notebooks', 'Pens', 'Calculators', 'Past questions', 'Printing/photocopy'
            ],
            'Home & Lifestyle': [
                'Bedsheets', 'Room decor', 'Lamps', 'Kitchen items', 'Cleaning supplies', 'Small furniture'
            ],
            'Sports & Fitness': [
                'Sportswear', 'Gym equipment', 'Football items', 'Supplements', 'Fitness accessories'
            ],
            'Services': [
                'Barbing', 'Hairdressing', 'Makeup services', 'Laundry', 'Delivery', 'Repairs (phones/laptops)'
            ],
            'Events & Entertainment': [
                'Event tickets', 'Speaker rental', 'Photography', 'Videography', 'Console rentals', 'Party items'
            ],
            'Miscellaneous': [
                'Crafts', 'Handmade items', 'Religious items', 'Thrift items', 'Campus merch (hoodies, caps)'
            ],
        }

        sort_order = 0
        for main_cat_name, subcats in categories_data.items():
            # Create main category
            main_cat, created = MainCategory.objects.get_or_create(
                name=main_cat_name,
                defaults={'sort_order': sort_order, 'is_active': True}
            )
            
            if created:
                self.stdout.write(self.style.SUCCESS(f'✓ Created main category: {main_cat_name}'))
            else:
                self.stdout.write(self.style.WARNING(f'- Main category already exists: {main_cat_name}'))
            
            # Create subcategories
            sub_sort = 0
            for subcat_name in subcats:
                subcat, sub_created = SubCategory.objects.get_or_create(
                    main_category=main_cat,
                    name=subcat_name,
                    defaults={'sort_order': sub_sort, 'is_active': True}
                )
                
                if sub_created:
                    self.stdout.write(f'  ✓ Created subcategory: {subcat_name}')
                
                sub_sort += 1
            
            sort_order += 1

        self.stdout.write(self.style.SUCCESS('\n✅ All categories created successfully!'))
        self.stdout.write(f'Total main categories: {MainCategory.objects.count()}')
        self.stdout.write(f'Total subcategories: {SubCategory.objects.count()}')