"""
Data migration: backfill Notification.user from Notification.vendor.user
for all existing rows where user IS NULL.
"""

from django.db import migrations


def backfill_user(apps, schema_editor):
    Notification = apps.get_model('vendors', 'Notification')
    # Update all notifications that have a vendor but no user set
    notifications = Notification.objects.filter(
        user__isnull=True,
        vendor__isnull=False,
    )
    count = 0
    for notif in notifications.select_related('vendor__user'):
        notif.user = notif.vendor.user
        notif.save(update_fields=['user'])
        count += 1
    print(f"  Backfilled user on {count} Notification(s).")


def reverse_backfill(apps, schema_editor):
    # Reverse is a no-op — we don't want to lose data
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('vendors', '0027_notification_unified_fields'),
    ]

    operations = [
        migrations.RunPython(backfill_user, reverse_backfill),
    ]
