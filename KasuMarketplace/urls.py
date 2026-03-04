
from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from django.contrib.sitemaps.views import sitemap
from .sitemaps import sitemaps  # <-- use the full production-ready sitemaps.py

# Import views for direct routes
from apps.vendors import views as vendor_views

urlpatterns = [
    # Admin
    path('admin/', admin.site.urls),

    # Marketplace URLs
    path('', include('apps.marketplace.urls', namespace='marketplace')),

    # Users URLs
    path('', include(('apps.users.urls', 'users'), namespace='users')),

    # Vendors URLs
    path('vendors/', include(('apps.vendors.urls', 'vendors'), namespace='vendors')),

    # Public store page
    path('shop/<slug:slug>/', vendor_views.store_public, name='store_public'),

    # Public product detail page
    path('shop/<slug:store_slug>/products/<slug:product_slug>/', 
         vendor_views.product_detail_public, 
         name='product_detail_public'),

    # Authentication
    path('accounts/', include('allauth.urls')),

    # ✅ Sitemap
    path('sitemap.xml', sitemap, {'sitemaps': sitemaps}, name='sitemap'),
]

# Serve static and media files in development
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)