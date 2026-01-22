"""
Main URL configuration for KasuMarketplace project.
"""
from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static

# Import views for direct routes
from apps.users import views as user_views
from apps.vendors import views as vendor_views

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', user_views.home, name='home'),
    path('', include(('apps.users.urls', 'users'), namespace='users')),
    path('vendors/', include(('apps.vendors.urls', 'vendors'), namespace='vendors')),
    
    # ==========================================
    # PUBLIC STORE & PRODUCT ROUTES
    # ==========================================
    # Public store page
    path('shop/<slug:slug>/', vendor_views.store_public, name='store_public'),
    
    # ✅ NEW: Public product detail (store-scoped)
    path('shop/<slug:store_slug>/products/<slug:product_slug>/', 
         vendor_views.product_detail_public, 
         name='product_detail_public'),
    
    path('accounts/', include('allauth.urls')),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
    