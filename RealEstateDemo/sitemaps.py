from django.contrib.sitemaps import Sitemap
from django.urls import reverse


class PublicPageSitemap(Sitemap):
    """Only include the public landing page in search results."""

    protocol = "https"

    def items(self):
        return ("public_home",)

    def location(self, url_name):
        return reverse(url_name)

    def get_domain(self, site=None):
        # Keep canonical sitemap URLs independent of Railway request hostnames.
        return "realestate360.site"
