import os
from django.contrib.auth import get_user_model
from django.contrib.sites.models import Site
from allauth.socialaccount.models import SocialApp

# Create superuser if not exists
User = get_user_model()
if not User.objects.filter(email='admin@kasumarketplace.com.ng').exists():
    User.objects.create_superuser(
        email='admin@kasumarketplace.com.ng',
        password=os.environ['DJANGO_SUPERUSER_PASSWORD']
    )
    print("Superuser created.")
else:
    print("Superuser already exists.")

# Fix site domain
site = Site.objects.get(id=1)
site.domain = 'kasumarketplace.com.ng'
site.name = 'KasuMarketplace'
site.save()
print("Site domain set to:", site.domain)

# Create or update Google SocialApp
google_app, created = SocialApp.objects.get_or_create(
    provider='google',
    defaults={
        'name': 'Google',
        'client_id': os.environ.get('GOOGLE_CLIENT_ID', ''),
        'secret': os.environ.get('GOOGLE_CLIENT_SECRET', ''),
    }
)
if not created:
    google_app.client_id = os.environ.get('GOOGLE_CLIENT_ID', '')
    google_app.secret = os.environ.get('GOOGLE_CLIENT_SECRET', '')
    google_app.save()

google_app.sites.add(site)
print("Google SocialApp linked to:", site.domain)