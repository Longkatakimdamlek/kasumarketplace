"""
Phase A: Extend Notification model for unified vendor + buyer notifications.

Adds user FK, channel, is_in_app_only, email_sent_at, and fixes
TYPE_CHOICES to include 'inventory' and 'wishlist'.
"""

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('vendors', '0026_add_store_state_city'),
    ]

    operations = [
        # 1. Add the new user FK (nullable initially)
        migrations.AddField(
            model_name='notification',
            name='user',
            field=models.ForeignKey(
                to=settings.AUTH_USER_MODEL,
                on_delete=django.db.models.deletion.CASCADE,
                related_name='notifications',
                null=True,
                blank=True,
                help_text='Recipient of this notification.',
            ),
        ),
        # 2. Make vendor nullable
        migrations.AlterField(
            model_name='notification',
            name='vendor',
            field=models.ForeignKey(
                to='vendors.VendorProfile',
                on_delete=django.db.models.deletion.CASCADE,
                related_name='notifications_legacy',
                null=True,
                blank=True,
                help_text='Legacy field — kept for backward-compat. Prefer user FK.',
            ),
        ),
        # 3. Add channel field
        migrations.AddField(
            model_name='notification',
            name='channel',
            field=models.CharField(
                max_length=10,
                choices=[('in_app', 'In-App Only'), ('both', 'In-App + Email')],
                default='both',
                help_text="'both' = in-app + email; 'in_app' = no email sent.",
            ),
        ),
        # 4. Add is_in_app_only field
        migrations.AddField(
            model_name='notification',
            name='is_in_app_only',
            field=models.BooleanField(
                default=False,
                help_text="Convenience flag: True means channel='in_app'.",
            ),
        ),
        # 5. Add email_sent_at field
        migrations.AddField(
            model_name='notification',
            name='email_sent_at',
            field=models.DateTimeField(
                null=True,
                blank=True,
                help_text='Set when the email dispatch for this notification succeeded.',
            ),
        ),
        # 6. Update TYPE_CHOICES to include inventory and wishlist
        migrations.AlterField(
            model_name='notification',
            name='notification_type',
            field=models.CharField(
                max_length=20,
                choices=[
                    ('order', 'New Order'),
                    ('payment', 'Payment Received'),
                    ('refund', 'Refund Request'),
                    ('verification', 'Verification Update'),
                    ('admin_message', 'Admin Message'),
                    ('system', 'System Message'),
                    ('inventory', 'Inventory Alert'),
                    ('wishlist', 'Wishlist Activity'),
                ],
            ),
        ),
    ]
