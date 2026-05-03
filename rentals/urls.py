from django.urls import path
from . import views

urlpatterns = [
    path("", views.tenant_dashboard, name="tenant_dashboard"),
    path("billing/", views.tenant_billing, name="tenant_billing"),
    path("pay/", views.tenant_pay_advance, name="tenant_pay_advance"),
    path("mark-welcome-seen/", views.mark_unit_welcome_seen, name="mark_unit_welcome_seen"),
]
