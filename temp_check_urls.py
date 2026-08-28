import os, django
os.environ['DJANGO_SETTINGS_MODULE'] = 'KasuMarketplace.settings'
django.setup()

from django.test import Client

c = Client()
resp = c.get('/')
html = resp.content.decode()

# Find hero-defaults URLs in the mobile section
mobile_end = html.find('<!-- ==================== DESKTOP LAYOUT ==================== -->')
mobile = html[:mobile_end] if mobile_end > 0 else html

import re
urls = re.findall(r"marketplace/img/hero-defaults/[^\s'\"]+", mobile)
print("Hero-defaults URLs found in mobile HTML:")
for u in set(urls):
    print(f"  {u}")

# Also check if WhiteNoise is serving hashed versions
all_urls = re.findall(r"/static/[^\"'\s]+hero-defaults[^\"'\s]+", html)
print(f"\nAll hero-defaults static URLs (full path):")
for u in set(all_urls):
    print(f"  {u}")
