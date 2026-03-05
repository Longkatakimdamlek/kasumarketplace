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
# Cleanly recreate all SocialApp records.
# Deletes ALL existing records for each provider first
# to prevent MultipleObjectsReturned errors from allauth.
# This is safe because credentials come from env vars.
# -------------------------------------------------------

# --- Google ---
count, _ = SocialApp.objects.filter(provider='google').delete()
print(f"Deleted {count} existing Google SocialApp record(s).")
google_client_id = os.environ.get('GOOGLE_CLIENT_ID', '')
google_secret = os.environ.get('GOOGLE_CLIENT_SECRET', '')
if google_client_id and google_secret:
    google_app = SocialApp.objects.create(
        provider='google',
        name='Google',
        client_id=google_client_id,
        secret=google_secret,
    )
    google_app.sites.add(site)
    print("Google SocialApp created and linked to:", site.domain)
else:
    print("WARNING: GOOGLE_CLIENT_ID or GOOGLE_CLIENT_SECRET not set — skipping Google SocialApp.")

# --- Facebook ---
count, _ = SocialApp.objects.filter(provider='facebook').delete()
print(f"Deleted {count} existing Facebook SocialApp record(s).")
fb_client_id = os.environ.get('FACEBOOK_CLIENT_ID', '')
fb_secret = os.environ.get('FACEBOOK_CLIENT_SECRET', '')
if fb_client_id and fb_secret:
    fb_app = SocialApp.objects.create(
        provider='facebook',
        name='Facebook',
        client_id=fb_client_id,
        secret=fb_secret,
    )
    fb_app.sites.add(site)
    print("Facebook SocialApp created and linked to:", site.domain)
else:
    print("WARNING: FACEBOOK_CLIENT_ID or FACEBOOK_CLIENT_SECRET not set — skipping Facebook SocialApp.")

# --- Apple ---
count, _ = SocialApp.objects.filter(provider='apple').delete()
print(f"Deleted {count} existing Apple SocialApp record(s).")
apple_client_id = os.environ.get('APPLE_CLIENT_ID', '')
apple_secret = os.environ.get('APPLE_TEAM_ID', '')
apple_key = os.environ.get('APPLE_KEY_ID', '')
if apple_client_id and apple_secret:
    apple_app = SocialApp.objects.create(
        provider='apple',
        name='Apple',
        client_id=apple_client_id,
        secret=apple_secret,
        key=apple_key,
    )
    apple_app.sites.add(site)
    print("Apple SocialApp created and linked to:", site.domain)
else:
    print("WARNING: APPLE_CLIENT_ID or APPLE_TEAM_ID not set — skipping Apple SocialApp.")