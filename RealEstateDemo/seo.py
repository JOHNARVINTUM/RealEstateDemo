from django.http import HttpResponse


def robots_txt(request):
    content = """User-agent: *
Allow: /
Disallow: /admin/
Disallow: /admin-portal/
Disallow: /tenant/
Disallow: /maintenance/
Disallow: /payments/
Disallow: /water/
Disallow: /profile/
Disallow: /login/
Disallow: /logout/
Disallow: /password-change/

Sitemap: https://realestate360.site/sitemap.xml
"""
    return HttpResponse(content, content_type="text/plain; charset=utf-8")
