"""
Data migration: clear raw BVN numbers for vendors whose identity
has already been verified (bank_status in 'verified' or 'pending_review').

The raw BVN is never retained long-term — this migration retroactively
enforces that policy for rows that were created before the field was
programmatically cleared after verification.
"""

from django.db import migrations


def clear_bvn_numbers(apps, schema_editor):
    VendorProfile = apps.get_model('vendors', 'VendorProfile')
    VendorProfile.objects.filter(
        bank_status__in=['verified', 'pending_review']
    ).exclude(
        bvn_number=''
    ).update(bvn_number='')


def reverse_clear_bvn_numbers(apps, schema_editor):
    # Cannot reverse — raw BVN values are intentionally destroyed.
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('vendors', '0021_add_bvn_consent_fields'),
    ]

    operations = [
        migrations.RunPython(clear_bvn_numbers, reverse_clear_bvn_numbers),
    ]
