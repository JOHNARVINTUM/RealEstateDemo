"""
URL configuration for RealEstateDemo project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/6.0/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from django.contrib.sitemaps.views import sitemap
from accounts.admin_portal_views import admin_dashboard
from accounts.views import RoleBasedLoginView
from django.contrib.auth.views import LogoutView
from .seo import robots_txt
from .sitemaps import PublicPageSitemap

sitemaps = {"public": PublicPageSitemap}

urlpatterns = [
    path("sitemap.xml", sitemap, {"sitemaps": sitemaps}, name="sitemap"),
    path("robots.txt", robots_txt, name="robots_txt"),
    path("admin/", admin.site.urls),

    # /login , /logout
    path("", include("accounts.urls")),

    # /tenant/...
    path("tenant/", include("rentals.urls")),

    path("maintenance/", include("maintenance.urls")), 

    path("payments/", include("payments.urls")),
    path("water/", include("water.urls")),
    path("admin-portal/dashboard/", admin_dashboard, name="admin_dashboard"),
    path("admin-portal/", include("accounts.admin_portal_urls")),

    path("login/", RoleBasedLoginView.as_view(), name="login"),
]

# Serve media files (development and production with WhiteNoise)
urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
