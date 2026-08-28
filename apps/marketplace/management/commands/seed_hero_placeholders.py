"""
Management command: seed_hero_placeholders
Generates placeholder images for hero_brand Promotion slides and uploads them to Cloudinary.

Usage:
    python manage.py seed_hero_placeholders
"""

import io
import os

from django.core.management.base import BaseCommand
from PIL import Image, ImageDraw, ImageFont

import cloudinary.uploader

from apps.marketplace.models import Promotion


SLIDE_CONFIGS = [
    {
        'title': 'Campus Essentials',
        'bg_color': '#0F6B3D',
        'filename': 'placeholder_campus_essentials.png',
    },
    {
        'title': 'Tech & Electronics',
        'bg_color': '#1a1a2e',
        'filename': 'placeholder_tech_electronics.png',
    },
    {
        'title': 'Fashion & Accessories',
        'bg_color': '#3C3489',
        'filename': 'placeholder_fashion_accessories.png',
    },
    {
        'title': 'Food & Beverages',
        'bg_color': '#D85A30',
        'filename': 'placeholder_food_beverages.png',
    },
    {
        'title': 'Deals & Marketplace',
        'bg_color': '#EF9F27',
        'filename': 'placeholder_deals_marketplace.png',
    },
]

WIDTH = 800
HEIGHT = 400
FONT_SIZE = 42
LABEL = 'PLACEHOLDER'


def hex_to_rgb(hex_color):
    h = hex_color.lstrip('#')
    return tuple(int(h[i:i+2], 16) for i in (0, 2, 4))


def generate_placeholder(title, bg_hex):
    """Generate a solid-color placeholder image with centred title text."""
    bg = hex_to_rgb(bg_hex)
    img = Image.new('RGB', (WIDTH, HEIGHT), bg)
    draw = ImageDraw.Draw(img)

    # Use default font (no .ttf dependency)
    try:
        font_title = ImageFont.truetype("arial.ttf", FONT_SIZE)
        font_label = ImageFont.truetype("arial.ttf", 18)
    except OSError:
        try:
            font_title = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", FONT_SIZE)
            font_label = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 18)
        except OSError:
            font_title = ImageFont.load_default()
            font_label = ImageFont.load_default()

    # Semi-transparent overlay band across the middle
    overlay = Image.new('RGBA', (WIDTH, HEIGHT), (0, 0, 0, 0))
    overlay_draw = ImageDraw.Draw(overlay)
    band_top = HEIGHT // 2 - 60
    band_bottom = HEIGHT // 2 + 60
    overlay_draw.rectangle([0, band_top, WIDTH, band_bottom], fill=(0, 0, 0, 120))
    img = Image.alpha_composite(img.convert('RGBA'), overlay).convert('RGB')
    draw = ImageDraw.Draw(img)

    # Title text (centred)
    bbox = draw.textbbox((0, 0), title, font=font_title)
    tw = bbox[2] - bbox[0]
    th = bbox[3] - bbox[1]
    draw.text(((WIDTH - tw) / 2, (HEIGHT - th) / 2 - 10), title, fill='white', font=font_title)

    # "PLACEHOLDER" label at bottom
    label_bbox = draw.textbbox((0, 0), LABEL, font=font_label)
    lw = label_bbox[2] - label_bbox[0]
    draw.text(((WIDTH - lw) / 2, HEIGHT - 36), LABEL, fill=(255, 255, 255, 200), font=font_label)

    return img


class Command(BaseCommand):
    help = "Generate placeholder images for hero_brand slides and upload to Cloudinary."

    def handle(self, *args, **options):
        slides = Promotion.objects.filter(slide_type='hero_brand').order_by('sort_order')
        if not slides.exists():
            self.stdout.write(self.style.ERROR("No hero_brand slides found. Run seed_hero_brand_slides first."))
            return

        for slide in slides:
            config = next((c for c in SLIDE_CONFIGS if c['title'] == slide.title), None)
            if not config:
                self.stdout.write(self.style.WARNING(f"  Skipped (no config): {slide.title}"))
                continue

            self.stdout.write(f"  Generating: {config['filename']} ...")

            img = generate_placeholder(slide.title, config['bg_color'])

            # Save to in-memory buffer
            buf = io.BytesIO()
            img.save(buf, format='PNG')
            buf.seek(0)

            # Upload to Cloudinary
            result = cloudinary.uploader.upload(
                buf,
                folder='hero_placeholders',
                public_id=config['filename'].replace('.png', ''),
                overwrite=True,
                resource_type='image',
            )
            image_url = result.get('secure_url') or result.get('url')
            self.stdout.write(f"    Uploaded: {image_url}")

            # Attach to the Promotion record
            # CloudinaryField accepts the URL or public_id directly
            slide.background_image = result.get('public_id')
            slide.save(update_fields=['background_image'])
            self.stdout.write(self.style.SUCCESS(f"    Attached to: {slide.title}"))

        self.stdout.write(self.style.SUCCESS("\nDone."))
