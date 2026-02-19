from django.urls import path
from . import views

urlpatterns = [
    path("", views.tenant_dashboard, name="tenant_dashboard"),
    path("billing/", views.tenant_billing, name="tenant_billing"),
    path("pay/", views.tenant_pay_advance, name="tenant_pay_advance"),
    
]
