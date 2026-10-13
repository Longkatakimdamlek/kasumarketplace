
from django.contrib import admin
from django.urls import path, include
from django.views.generic.base import RedirectView
from django.conf import settings
from django.conf.urls.static import static
from django.contrib.sitemaps.views import sitemap
from .sitemaps import sitemaps  # <-- use the full production-ready sitemaps.py
from apps.users import views as user_views
# Import views for direct routes
from apps.vendors import views as vendor_views

urlpatterns = [
    # Browsers request this conventional root path even when HTML declares
    # additional favicon variants under the static files namespace.
    path(
        'favicon.ico',
        RedirectView.as_view(
            url=f'{settings.STATIC_URL}images/favicon/favicon.ico',
            permanent=False,
        ),
        name='favicon',
    ),

    # Admin
    path('admin/', admin.site.urls),

    # Marketplace URLs
    path('', include('apps.marketplace.urls', namespace='marketplace')),

    # Users URLs
    path('', include(('apps.users.urls', 'users'), namespace='users')),

    # Quick Sell URLs
    path(
        'quick-sell/',
        include('apps.quicksell.urls', namespace='quicksell'),
    ),

    # Vendors URLs
    path('vendors/', include(('apps.vendors.urls', 'vendors'), namespace='vendors')),

    # Public store page
    path('shop/<slug:slug>/', vendor_views.store_public, name='store_public'),

    # Public product detail page
    path('shop/<slug:store_slug>/products/<slug:product_slug>/', 
         vendor_views.product_detail_public, 
         name='product_detail_public'),
        path('shop/<slug:store_slug>/products/<slug:product_slug>/review/',
            vendor_views.submit_review,
            name='submit_review'),
        path('shop/<slug:store_slug>/products/<slug:product_slug>/wishlist/',
            vendor_views.toggle_wishlist,
            name='toggle_wishlist'),

    # Authentication
    # override allauth login route so that /accounts/login/ uses our styled page
    path('accounts/login/', user_views.LoginView.as_view(), name='account_login'),
    path('accounts/', include('allauth.urls')),

    # ✅ Sitemap
    path('sitemap.xml', sitemap, {'sitemaps': sitemaps}, name='sitemap'),
]

# Serve static and media files in development
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)

    # serve the PWA web manifest at the root URL so that browsers can fetch
    # it as `/site.webmanifest` without the `/static/` prefix.  the file
    # resides in our static directory, so point Django's static serve at it.
    from django.views.static import serve

    urlpatterns += [
        path(
            'site.webmanifest',
            serve,
            {
                'document_root': settings.STATICFILES_DIRS[0],
                'path': 'site.webmanifest',
            },
        ),
    ]

# ---------------------------------------------------------------------------
# Branded error handlers (see KasuMarketplace/error_views.py)
# ---------------------------------------------------------------------------
handler400 = "KasuMarketplace.error_views.bad_request"
handler403 = "KasuMarketplace.error_views.permission_denied"
handler404 = "KasuMarketplace.error_views.page_not_found"
handler500 = "KasuMarketplace.error_views.server_error"

# Local visual preview of the error pages.  Must not exist in production.
if settings.DEBUG:
    from KasuMarketplace import error_views

    # NB: MEDIA_URL resolves to "/" here, so the media static() helper above
    # registers a catch-all regex pattern.  A route appended after it would
    # never match, so register the preview just before that catch-all.
    _preview = path("__errors__/<str:kind>/", error_views.preview, name="error_preview")
    _catch_all = next(
        (i for i, p in enumerate(urlpatterns) if str(p.pattern).startswith("^")),
        None,
    )
    if _catch_all is None:
        urlpatterns.append(_preview)
    else:
        urlpatterns.insert(_catch_all, _preview)