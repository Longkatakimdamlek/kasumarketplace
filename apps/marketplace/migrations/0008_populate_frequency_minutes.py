"""
Data migration: populate frequency_minutes from frequency_hours before removing the old field.
"""
from django.db import migrations


def convert_hours_to_minutes(apps, schema_editor):
    Promotion = apps.get_model('marketplace', 'Promotion')
    for promo in Promotion.objects.all():
        promo.frequency_minutes = (promo.frequency_hours or 24) * 60
        promo.save(update_fields=['frequency_minutes'])


def reverse_convert(apps, schema_editor):
    Promotion = apps.get_model('marketplace', 'Promotion')
    for promo in Promotion.objects.all():
        promo.frequency_hours = (promo.frequency_minutes or 1440) // 60
        promo.save(update_fields=['frequency_hours'])


class Migration(migrations.Migration):

    dependencies = [
        ('marketplace', '0007_add_frequency_minutes'),
    ]

    operations = [
        migrations.RunPython(convert_hours_to_minutes, reverse_convert),
    ]
