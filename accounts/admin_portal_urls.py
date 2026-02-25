from django.urls import path
from .admin_portal_views import (
    admin_dashboard,
    admin_tenants,
    admin_tenant_detail,
    admin_billing,
    admin_payments,
    admin_maintenance,
    admin_announcements,
    admin_create_tenant_profile,
    admin_create_announcement,
)

urlpatterns = [
    path("dashboard/", admin_dashboard, name="admin_dashboard"),
    path("tenants/", admin_tenants, name="admin_tenants"),
    path("tenants/<int:tenant_id>/", admin_tenant_detail, name="admin_tenant_detail"),
    path("billing/", admin_billing, name="admin_billing"),
    path("payments/", admin_payments, name="admin_payments"),
    path("maintenance/", admin_maintenance, name="admin_maintenance"),
    path("announcements/", admin_announcements, name="admin_announcements"),

    # Create pages
    path("tenants/add/", admin_create_tenant_profile, name="admin_create_tenant_profile"),
    path("announcements/add/", admin_create_announcement, name="admin_create_announcement"),
   
]