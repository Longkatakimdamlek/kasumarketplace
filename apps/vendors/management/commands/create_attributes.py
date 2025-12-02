"""
Management command to create sample product attributes for subcategories
Run: python manage.py create_attributes
"""

from django.core.management.base import BaseCommand
from apps.vendors.models import SubCategory, SubCategoryAttribute


class Command(BaseCommand):
    help = 'Create sample product attributes for subcategories in KasuMarketplace'

    def handle(self, *args, **kwargs):
        """
        Creates attributes for each subcategory based on product type
        """
        
        # Define attributes for each subcategory
        attributes_data = {
            # Fashion & Accessories
            'Clothes': [
                {'name': 'Size', 'field_type': 'dropdown', 'options': ['XS', 'S', 'M', 'L', 'XL', 'XXL'], 'is_required': True},
                {'name': 'Color', 'field_type': 'text', 'placeholder': 'e.g., Black, Blue, Red', 'is_required': True},
                {'name': 'Material', 'field_type': 'text', 'placeholder': 'e.g., Cotton, Polyester', 'is_required': False},
                {'name': 'Brand', 'field_type': 'text', 'placeholder': 'e.g., Zara, H&M', 'is_required': False},
                {'name': 'Gender', 'field_type': 'dropdown', 'options': ['Male', 'Female', 'Unisex'], 'is_required': True},
                {'name': 'Condition', 'field_type': 'dropdown', 'options': ['New', 'Used - Like New', 'Used - Good', 'Used - Fair'], 'is_required': True},
            ],
            'Shoes': [
                {'name': 'Size', 'field_type': 'dropdown', 'options': ['36', '37', '38', '39', '40', '41', '42', '43', '44', '45', '46'], 'is_required': True},
                {'name': 'Color', 'field_type': 'text', 'placeholder': 'e.g., Black, White, Brown', 'is_required': True},
                {'name': 'Material', 'field_type': 'text', 'placeholder': 'e.g., Leather, Canvas, Suede', 'is_required': False},
                {'name': 'Brand', 'field_type': 'text', 'placeholder': 'e.g., Nike, Adidas, Converse', 'is_required': False},
                {'name': 'Gender', 'field_type': 'dropdown', 'options': ['Male', 'Female', 'Unisex'], 'is_required': True},
                {'name': 'Condition', 'field_type': 'dropdown', 'options': ['New', 'Used - Like New', 'Used - Good'], 'is_required': True},
            ],
            'Jewelry': [
                {'name': 'Type', 'field_type': 'dropdown', 'options': ['Necklace', 'Bracelet', 'Earrings', 'Ring', 'Anklet'], 'is_required': True},
                {'name': 'Material', 'field_type': 'dropdown', 'options': ['Gold', 'Silver', 'Stainless Steel', 'Beads', 'Other'], 'is_required': True},
                {'name': 'Gender', 'field_type': 'dropdown', 'options': ['Male', 'Female', 'Unisex'], 'is_required': False},
                {'name': 'Condition', 'field_type': 'dropdown', 'options': ['New', 'Used'], 'is_required': True},
            ],
            'Bags': [
                {'name': 'Type', 'field_type': 'dropdown', 'options': ['Backpack', 'Handbag', 'Tote', 'Crossbody', 'Laptop Bag', 'Travel Bag'], 'is_required': True},
                {'name': 'Material', 'field_type': 'text', 'placeholder': 'e.g., Leather, Canvas, Nylon', 'is_required': False},
                {'name': 'Color', 'field_type': 'text', 'placeholder': 'e.g., Black, Brown, Tan', 'is_required': True},
                {'name': 'Brand', 'field_type': 'text', 'placeholder': 'e.g., Nike, Adidas, Generic', 'is_required': False},
                {'name': 'Condition', 'field_type': 'dropdown', 'options': ['New', 'Used - Like New', 'Used - Good'], 'is_required': True},
            ],
            'Watches': [
                {'name': 'Type', 'field_type': 'dropdown', 'options': ['Digital', 'Analog', 'Smartwatch'], 'is_required': True},
                {'name': 'Brand', 'field_type': 'text', 'placeholder': 'e.g., Casio, Rolex, Apple', 'is_required': False},
                {'name': 'Gender', 'field_type': 'dropdown', 'options': ['Male', 'Female', 'Unisex'], 'is_required': True},
                {'name': 'Condition', 'field_type': 'dropdown', 'options': ['New', 'Used - Like New', 'Used - Good'], 'is_required': True},
            ],
            
            # Tech & Electronics
            'Phones': [
                {'name': 'Brand', 'field_type': 'dropdown', 'options': ['Apple', 'Samsung', 'Xiaomi', 'Infinix', 'Tecno', 'Other'], 'is_required': True},
                {'name': 'Model', 'field_type': 'text', 'placeholder': 'e.g., iPhone 13, Galaxy S21', 'is_required': True},
                {'name': 'Storage', 'field_type': 'dropdown', 'options': ['16GB', '32GB', '64GB', '128GB', '256GB', '512GB', '1TB'], 'is_required': True},
                {'name': 'RAM', 'field_type': 'dropdown', 'options': ['2GB', '3GB', '4GB', '6GB', '8GB', '12GB', '16GB'], 'is_required': True},
                {'name': 'Battery', 'field_type': 'text', 'placeholder': 'e.g., 4000mAh, 5000mAh', 'is_required': False},
                {'name': 'Color', 'field_type': 'text', 'placeholder': 'e.g., Black, White, Blue', 'is_required': False},
                {'name': 'Condition', 'field_type': 'dropdown', 'options': ['New', 'Used - Like New', 'Used - Good', 'Refurbished'], 'is_required': True},
                {'name': 'Warranty', 'field_type': 'dropdown', 'options': ['Yes', 'No'], 'is_required': False},
            ],
            'Laptops': [
                {'name': 'Brand', 'field_type': 'dropdown', 'options': ['HP', 'Dell', 'Lenovo', 'Apple', 'Asus', 'Acer', 'Microsoft', 'Other'], 'is_required': True},
                {'name': 'Model', 'field_type': 'text', 'placeholder': 'e.g., Pavilion 15, MacBook Pro', 'is_required': True},
                {'name': 'Processor', 'field_type': 'dropdown', 'options': ['Intel Core i3', 'Intel Core i5', 'Intel Core i7', 'Intel Core i9', 'AMD Ryzen 3', 'AMD Ryzen 5', 'AMD Ryzen 7', 'M1', 'M2'], 'is_required': True},
                {'name': 'RAM', 'field_type': 'dropdown', 'options': ['4GB', '8GB', '16GB', '32GB', '64GB'], 'is_required': True},
                {'name': 'Storage', 'field_type': 'dropdown', 'options': ['128GB SSD', '256GB SSD', '512GB SSD', '1TB SSD', '2TB SSD', '500GB HDD', '1TB HDD'], 'is_required': True},
                {'name': 'Screen Size', 'field_type': 'text', 'placeholder': 'e.g., 13.3", 15.6", 17"', 'is_required': False},
                {'name': 'GPU', 'field_type': 'text', 'placeholder': 'e.g., Integrated, NVIDIA GTX 1650', 'is_required': False},
                {'name': 'Condition', 'field_type': 'dropdown', 'options': ['New', 'Used - Like New', 'Used - Good', 'Refurbished'], 'is_required': True},
                {'name': 'Warranty', 'field_type': 'dropdown', 'options': ['Yes', 'No'], 'is_required': False},
            ],
            'Tablets': [
                {'name': 'Brand', 'field_type': 'dropdown', 'options': ['Apple', 'Samsung', 'Huawei', 'Lenovo', 'Other'], 'is_required': True},
                {'name': 'Model', 'field_type': 'text', 'placeholder': 'e.g., iPad Pro, Galaxy Tab', 'is_required': True},
                {'name': 'Storage', 'field_type': 'dropdown', 'options': ['32GB', '64GB', '128GB', '256GB', '512GB'], 'is_required': True},
                {'name': 'Screen Size', 'field_type': 'text', 'placeholder': 'e.g., 10.1", 11", 12.9"', 'is_required': False},
                {'name': 'Condition', 'field_type': 'dropdown', 'options': ['New', 'Used - Like New', 'Used - Good'], 'is_required': True},
            ],
            'Speakers': [
                {'name': 'Brand', 'field_type': 'text', 'placeholder': 'e.g., JBL, Sony, Bose', 'is_required': False},
                {'name': 'Type', 'field_type': 'dropdown', 'options': ['Bluetooth', 'Wired', 'Smart Speaker'], 'is_required': True},
                {'name': 'Condition', 'field_type': 'dropdown', 'options': ['New', 'Used - Like New', 'Used - Good'], 'is_required': True},
            ],
            
            # Food & Beverages
            'Snacks': [
                {'name': 'Type', 'field_type': 'dropdown', 'options': ['Chips', 'Cookies', 'Candy', 'Nuts', 'Other'], 'is_required': False},
                {'name': 'Brand', 'field_type': 'text', 'placeholder': 'e.g., Doritos, Oreo', 'is_required': False},
                {'name': 'Expiry Date', 'field_type': 'text', 'placeholder': 'e.g., Dec 2024', 'is_required': True},
            ],
            'Drinks': [
                {'name': 'Type', 'field_type': 'dropdown', 'options': ['Soft Drink', 'Juice', 'Water', 'Energy Drink', 'Other'], 'is_required': False},
                {'name': 'Brand', 'field_type': 'text', 'placeholder': 'e.g., Coca-Cola, Pepsi', 'is_required': False},
                {'name': 'Volume', 'field_type': 'text', 'placeholder': 'e.g., 500ml, 1L, 2L', 'is_required': False},
                {'name': 'Expiry Date', 'field_type': 'text', 'placeholder': 'e.g., Jan 2025', 'is_required': True},
            ],
            'Homemade meals': [
                {'name': 'Meal Type', 'field_type': 'dropdown', 'options': ['Rice & Stew', 'Jollof Rice', 'Fried Rice', 'Beans', 'Spaghetti', 'Soup', 'Snack', 'Other'], 'is_required': True},
                {'name': 'Serving Size', 'field_type': 'dropdown', 'options': ['Small', 'Medium', 'Large', 'Extra Large'], 'is_required': True},
                {'name': 'Delivery Available', 'field_type': 'dropdown', 'options': ['Yes', 'No'], 'is_required': True},
                {'name': 'Preparation Time', 'field_type': 'text', 'placeholder': 'e.g., 30 mins, 1 hour', 'is_required': False},
            ],
            
            # Beauty & Personal Care
            'Skincare': [
                {'name': 'Type', 'field_type': 'dropdown', 'options': ['Cleanser', 'Moisturizer', 'Serum', 'Sunscreen', 'Toner', 'Face Mask'], 'is_required': True},
                {'name': 'Brand', 'field_type': 'text', 'placeholder': 'e.g., Nivea, Olay, Neutrogena', 'is_required': False},
                {'name': 'Skin Type', 'field_type': 'dropdown', 'options': ['All Skin Types', 'Oily', 'Dry', 'Combination', 'Sensitive'], 'is_required': False},
                {'name': 'Condition', 'field_type': 'dropdown', 'options': ['New/Sealed', 'Opened/Used'], 'is_required': True},
            ],
            'Makeup': [
                {'name': 'Type', 'field_type': 'dropdown', 'options': ['Foundation', 'Lipstick', 'Eyeshadow', 'Mascara', 'Eyeliner', 'Blush', 'Powder'], 'is_required': True},
                {'name': 'Brand', 'field_type': 'text', 'placeholder': 'e.g., MAC, Maybelline, Fenty', 'is_required': False},
                {'name': 'Shade/Color', 'field_type': 'text', 'placeholder': 'e.g., Nude, Red, Brown', 'is_required': False},
                {'name': 'Condition', 'field_type': 'dropdown', 'options': ['New/Sealed', 'Swatched', 'Gently Used'], 'is_required': True},
            ],
            'Perfumes': [
                {'name': 'Brand', 'field_type': 'text', 'placeholder': 'e.g., Dior, Chanel, Tom Ford', 'is_required': False},
                {'name': 'Type', 'field_type': 'dropdown', 'options': ['Eau de Parfum', 'Eau de Toilette', 'Body Spray', 'Oil'], 'is_required': True},
                {'name': 'Volume', 'field_type': 'text', 'placeholder': 'e.g., 50ml, 100ml', 'is_required': False},
                {'name': 'Gender', 'field_type': 'dropdown', 'options': ['Male', 'Female', 'Unisex'], 'is_required': False},
                {'name': 'Condition', 'field_type': 'dropdown', 'options': ['New/Sealed', 'Opened'], 'is_required': True},
            ],
            
            # Education & Stationery
            'Textbooks': [
                {'name': 'Book Title', 'field_type': 'text', 'placeholder': 'Full title of the book', 'is_required': True},
                {'name': 'Author', 'field_type': 'text', 'placeholder': 'Author name', 'is_required': False},
                {'name': 'Course Code', 'field_type': 'text', 'placeholder': 'e.g., CSC101, MTH201', 'is_required': False},
                {'name': 'Edition', 'field_type': 'text', 'placeholder': 'e.g., 5th Edition, 2020', 'is_required': False},
                {'name': 'Condition', 'field_type': 'dropdown', 'options': ['New', 'Like New', 'Good', 'Fair - Has Markings'], 'is_required': True},
            ],
            'Calculators': [
                {'name': 'Type', 'field_type': 'dropdown', 'options': ['Scientific', 'Graphing', 'Basic'], 'is_required': True},
                {'name': 'Brand', 'field_type': 'text', 'placeholder': 'e.g., Casio, Texas Instruments', 'is_required': False},
                {'name': 'Model', 'field_type': 'text', 'placeholder': 'e.g., fx-991ES, TI-84', 'is_required': False},
                {'name': 'Condition', 'field_type': 'dropdown', 'options': ['New', 'Used - Like New', 'Used - Good'], 'is_required': True},
            ],
            
            # Home & Lifestyle
            'Bedsheets': [
                {'name': 'Size', 'field_type': 'dropdown', 'options': ['Single', 'Double', 'Queen', 'King'], 'is_required': True},
                {'name': 'Material', 'field_type': 'text', 'placeholder': 'e.g., Cotton, Silk, Polyester', 'is_required': False},
                {'name': 'Color/Pattern', 'field_type': 'text', 'placeholder': 'e.g., White, Floral, Striped', 'is_required': False},
                {'name': 'Condition', 'field_type': 'dropdown', 'options': ['New', 'Used - Like New'], 'is_required': True},
            ],
            'Lamps': [
                {'name': 'Type', 'field_type': 'dropdown', 'options': ['Desk Lamp', 'Floor Lamp', 'Bedside Lamp', 'LED Strip'], 'is_required': True},
                {'name': 'Power Source', 'field_type': 'dropdown', 'options': ['Plug-in', 'Battery', 'Rechargeable', 'Solar'], 'is_required': False},
                {'name': 'Condition', 'field_type': 'dropdown', 'options': ['New', 'Used - Working'], 'is_required': True},
            ],
            
            # Sports & Fitness
            'Sportswear': [
                {'name': 'Type', 'field_type': 'dropdown', 'options': ['Jersey', 'Shorts', 'Tracksuit', 'Sports Bra', 'Leggings'], 'is_required': True},
                {'name': 'Size', 'field_type': 'dropdown', 'options': ['XS', 'S', 'M', 'L', 'XL', 'XXL'], 'is_required': True},
                {'name': 'Brand', 'field_type': 'text', 'placeholder': 'e.g., Nike, Adidas, Puma', 'is_required': False},
                {'name': 'Gender', 'field_type': 'dropdown', 'options': ['Male', 'Female', 'Unisex'], 'is_required': True},
                {'name': 'Condition', 'field_type': 'dropdown', 'options': ['New', 'Used - Like New', 'Used - Good'], 'is_required': True},
            ],
            'Gym equipment': [
                {'name': 'Type', 'field_type': 'dropdown', 'options': ['Dumbbells', 'Resistance Bands', 'Yoga Mat', 'Jump Rope', 'Kettlebell', 'Other'], 'is_required': True},
                {'name': 'Weight/Specs', 'field_type': 'text', 'placeholder': 'e.g., 5kg, 10kg, Adjustable', 'is_required': False},
                {'name': 'Condition', 'field_type': 'dropdown', 'options': ['New', 'Used - Like New', 'Used - Good'], 'is_required': True},
            ],
            
            # Services
            'Barbing': [
                {'name': 'Service Type', 'field_type': 'dropdown', 'options': ['Haircut', 'Shave', 'Haircut + Shave', 'Beard Trim', 'Hair Coloring'], 'is_required': True},
                {'name': 'Duration', 'field_type': 'text', 'placeholder': 'e.g., 30 mins, 1 hour', 'is_required': True},
                {'name': 'Location', 'field_type': 'text', 'placeholder': 'Where service is provided', 'is_required': True},
                {'name': 'Availability', 'field_type': 'text', 'placeholder': 'e.g., Mon-Sat 9AM-6PM', 'is_required': True},
            ],
            'Hairdressing': [
                {'name': 'Service Type', 'field_type': 'dropdown', 'options': ['Braiding', 'Weaving', 'Fixing', 'Washing & Blow Dry', 'Treatment', 'Styling'], 'is_required': True},
                {'name': 'Duration', 'field_type': 'text', 'placeholder': 'e.g., 2 hours, 3 hours', 'is_required': True},
                {'name': 'Location', 'field_type': 'text', 'placeholder': 'Where service is provided', 'is_required': True},
                {'name': 'Availability', 'field_type': 'text', 'placeholder': 'e.g., Mon-Sat 8AM-7PM', 'is_required': True},
            ],
            'Laundry': [
                {'name': 'Service Type', 'field_type': 'dropdown', 'options': ['Wash Only', 'Wash & Iron', 'Dry Cleaning', 'Iron Only'], 'is_required': True},
                {'name': 'Pricing', 'field_type': 'text', 'placeholder': 'e.g., Per kg, Per item', 'is_required': False},
                {'name': 'Turnaround Time', 'field_type': 'text', 'placeholder': 'e.g., Same day, Next day, 2-3 days', 'is_required': True},
                {'name': 'Pickup/Delivery', 'field_type': 'dropdown', 'options': ['Yes', 'No'], 'is_required': True},
            ],
            'Repairs (phones/laptops)': [
                {'name': 'Device Type', 'field_type': 'dropdown', 'options': ['Phone', 'Laptop', 'Tablet', 'Other'], 'is_required': True},
                {'name': 'Repair Type', 'field_type': 'text', 'placeholder': 'e.g., Screen replacement, Battery, Software', 'is_required': True},
                {'name': 'Turnaround Time', 'field_type': 'text', 'placeholder': 'e.g., Same day, 1-2 days', 'is_required': True},
                {'name': 'Warranty', 'field_type': 'dropdown', 'options': ['Yes', 'No'], 'is_required': False},
            ],
        }
        
        created_count = 0
        skipped_count = 0
        
        for subcat_name, attributes in attributes_data.items():
            try:
                subcategory = SubCategory.objects.get(name=subcat_name)
                
                self.stdout.write(f'\n📦 Processing: {subcategory.main_category.name} → {subcat_name}')
                
                for idx, attr_data in enumerate(attributes):
                    attr, created = SubCategoryAttribute.objects.get_or_create(
                        subcategory=subcategory,
                        name=attr_data['name'],
                        defaults={
                            'field_type': attr_data.get('field_type', 'text'),
                            'options': attr_data.get('options', []),
                            'is_required': attr_data.get('is_required', False),
                            'placeholder': attr_data.get('placeholder', ''),
                            'help_text': attr_data.get('help_text', ''),
                            'sort_order': idx,
                            'is_active': True
                        }
                    )
                    
                    if created:
                        self.stdout.write(f'  ✓ Created attribute: {attr_data["name"]} ({attr_data.get("field_type", "text")})')
                        created_count += 1
                    else:
                        skipped_count += 1
                
            except SubCategory.DoesNotExist:
                self.stdout.write(self.style.WARNING(f'  ⚠️ Subcategory "{subcat_name}" not found. Skipping...'))
        
        self.stdout.write(self.style.SUCCESS(f'\n✅ Attribute creation complete!'))
        self.stdout.write(f'✓ Created: {created_count} attributes')
        self.stdout.write(f'- Skipped: {skipped_count} (already exist)')
        self.stdout.write(f'📊 Total attributes in database: {SubCategoryAttribute.objects.count()}')