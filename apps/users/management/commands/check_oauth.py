"""
Management command to check OAuth configuration
Usage: python manage.py check_oauth
"""

from django.core.management.base import BaseCommand
from django.contrib.sites.models import Site
from allauth.socialaccount.models import SocialApp


class Command(BaseCommand):
    help = 'Check OAuth application configuration'

    def handle(self, *args, **options):
        self.stdout.write(self.style.SUCCESS('=== OAUTH Configuration Check ===\n'))
        
        # Check Sites
        self.stdout.write(self.style.HTTP_INFO('Current Site:'))
        try:
            current_site = Site.objects.get_current()
            self.stdout.write(f'  Domain: {current_site.domain}')
            self.stdout.write(f'  Name: {current_site.name}\n')
        except Exception as e:
            self.stdout.write(self.style.ERROR(f'  Error: {str(e)}\n'))
        
        # Check Social Apps
        self.stdout.write(self.style.HTTP_INFO('Registered Social Apps:'))
        apps = SocialApp.objects.all()
        if not apps:
            self.stdout.write(self.style.WARNING('  ⚠️ No social apps configured!\n'))
        else:
            for app in apps:
                self.stdout.write(f'\n  Provider: {app.provider.upper()}')
                self.stdout.write(f'  Name: {app.name}')
                self.stdout.write(f'  Client ID: {app.client_id[:10]}...' if app.client_id else '  Client ID: NOT SET')
                self.stdout.write(f'  Secret Key: {"SET" if app.secret else "NOT SET"}')
                self.stdout.write(f'  Sites: {", ".join([s.domain for s in app.sites.all()])}')
        
        self.stdout.write('\n' + self.style.SUCCESS('=== Google OAuth Redirect URI ==='))
        self.stdout.write('Add this to Google Cloud Console under:')
        self.stdout.write('APIs & Services → Credentials → [Your OAuth 2.0 Client] → Authorized redirect URIs\n')
        
        try:
            current_site = Site.objects.get_current()
            protocol = 'https'  # Use https by default
            redirect_uri = f'{protocol}://{current_site.domain}/accounts/google/login/callback/'
            self.stdout.write(self.style.SUCCESS(f'Redirect URI: {redirect_uri}\n'))
        except Exception as e:
            self.stdout.write(self.style.ERROR(f'Could not generate redirect URI: {str(e)}\n'))
        
        self.stdout.write(self.style.WARNING('For local testing with localhost, use:'))
        self.stdout.write('  http://localhost:8000/accounts/google/login/callback/\n')
