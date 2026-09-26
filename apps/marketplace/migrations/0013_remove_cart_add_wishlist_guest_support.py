from django.conf import settings
from django.db import migrations, models
import django.core.validators


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('marketplace', '0012_remove_mainorder_buyer_remove_suborder_main_order_and_more'),
    ]

    operations = [
        # Delete CartItem first (has FK to Cart)
        migrations.DeleteModel(name='CartItem'),
        # Delete Cart
        migrations.DeleteModel(name='Cart'),
        # Add session_key to Wishlist
        migrations.AddField(
            model_name='wishlist',
            name='session_key',
            field=models.CharField(blank=True, default='', help_text='Set for anonymous (guest) wishlists', max_length=40),
        ),
        # Add quantity to Wishlist
        migrations.AddField(
            model_name='wishlist',
            name='quantity',
            field=models.PositiveIntegerField(default=1, validators=[django.core.validators.MinValueValidator(1)]),
        ),
        # Alter user FK to be nullable
        migrations.AlterField(
            model_name='wishlist',
            name='user',
            field=models.ForeignKey(
                blank=True,
                help_text='Set when user is authenticated',
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name='wishlist_items',
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        # Update unique_together
        migrations.AlterUniqueTogether(
            name='wishlist',
            unique_together={('user', 'product'), ('session_key', 'product')},
        ),
    ]
