from django.contrib.sitemaps import Sitemap
from django.urls import reverse

class StaticViewSitemap(Sitemap):
    priority = 1.0
    changefreq = 'weekly'

    def items(self):
        return ['marketplace:product_list']

    def location(self, item):
        # Only return the path; Django will add scheme + domain automatically
        return reverse(item)