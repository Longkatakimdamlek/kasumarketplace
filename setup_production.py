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

# -------------------------------------------------------
# Fix duplicate SocialApp records (the cause of the 500)
# Delete ALL existing Google SocialApp entries and
# recreate a single clean one.
# -------------------------------------------------------
deleted_count, _ = SocialApp.objects.filter(provider='google').delete()
print(f"Deleted {deleted_count} existing Google SocialApp record(s).")

google_app = SocialApp.objects.create(
    provider='google',
    name='Google',
    client_id=os.environ.get('GOOGLE_CLIENT_ID', ''),
    secret=os.environ.get('GOOGLE_CLIENT_SECRET', ''),
)
google_app.sites.add(site)
print("Google SocialApp created and linked to:", site.domain)

# Also clean up any duplicate Facebook/Apple entries just in case
for provider in ['facebook', 'apple']:
    apps = SocialApp.objects.filter(provider=provider)
    if apps.count() > 1:
        first_id = apps.first().id
        dupes_deleted, _ = apps.exclude(id=first_id).delete()
        print(f"Cleaned up {dupes_deleted} duplicate {provider} SocialApp record(s).")