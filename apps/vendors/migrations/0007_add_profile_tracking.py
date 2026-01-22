# Generated migration file
from django.db import migrations, models
import django.core.validators
from django.utils import timezone


class Migration(migrations.Migration):

    dependencies = [
        ('vendors', '0006_remove_productimage_low_stock_threshold_and_more'),
    ]

    operations = [
        # VendorProfile fields
        migrations.AddField(
            model_name='vendorprofile',
            name='registration_ip',
            field=models.GenericIPAddressField(blank=True, help_text='IP address used during registration', null=True),
        ),
        migrations.AddField(
            model_name='vendorprofile',
            name='nin_verification_ip',
            field=models.GenericIPAddressField(blank=True, help_text='IP address used during NIN verification', null=True),
        ),
        migrations.AddField(
            model_name='vendorprofile',
            name='bvn_verification_ip',
            field=models.GenericIPAddressField(blank=True, help_text='IP address used during BVN verification', null=True),
        ),
        migrations.AddField(
            model_name='vendorprofile',
            name='has_name_mismatch',
            field=models.BooleanField(default=False, help_text='True if NIN name ≠ BVN name'),
        ),
        migrations.AddField(
            model_name='vendorprofile',
            name='name_mismatch_details',
            field=models.CharField(blank=True, help_text="Details about name mismatch", max_length=500),
        ),
        migrations.AddField(
            model_name='vendorprofile',
            name='has_duplicate_nin',
            field=models.BooleanField(default=False, help_text='True if NIN exists on another account'),
        ),
        migrations.AddField(
            model_name='vendorprofile',
            name='duplicate_nin_vendor_id',
            field=models.CharField(blank=True, help_text='Vendor ID of account with same NIN', max_length=100),
        ),
        migrations.AddField(
            model_name='vendorprofile',
            name='has_duplicate_bvn',
            field=models.BooleanField(default=False, help_text='True if BVN exists on another account'),
        ),
        migrations.AddField(
            model_name='vendorprofile',
            name='duplicate_bvn_vendor_id',
            field=models.CharField(blank=True, help_text='Vendor ID of account with same BVN', max_length=100),
        ),
        migrations.AddField(
            model_name='vendorprofile',
            name='is_underage',
            field=models.BooleanField(default=False, help_text='True if vendor is under 18 years old'),
        ),
        migrations.AddField(
            model_name='vendorprofile',
            name='calculated_age',
            field=models.PositiveIntegerField(blank=True, help_text="Vendor's age calculated from DOB", null=True),
        ),
        migrations.AddField(
            model_name='vendorprofile',
            name='admin_internal_notes',
            field=models.TextField(blank=True, help_text='Private notes visible only to admins'),
        ),
        migrations.AddField(
            model_name='vendorprofile',
            name='risk_score',
            field=models.IntegerField(
                default=0,
                help_text='Automated risk assessment score (0-100)',
                validators=[django.core.validators.MinValueValidator(0), django.core.validators.MaxValueValidator(100)]
            ),
        ),
        migrations.AddField(
            model_name='vendorprofile',
            name='bvn_full_name',
            field=models.CharField(blank=True, help_text='Full name from BVN verification', max_length=200),
        ),
    ]
