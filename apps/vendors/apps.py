"""
Vendor App Configuration
"""

from django.apps import AppConfig


class VendorsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.vendors'
    verbose_name = 'Vendors'
    
    def ready(self):
        """
        Import signals when app is ready
        """
        import apps.vendors.signals