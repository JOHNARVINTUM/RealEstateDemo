from django.urls import path
from .views import tenant_dashboard, tenant_pay_qr

urlpatterns = [
    path("", tenant_dashboard, name="tenant_dashboard"),
    path("pay/", tenant_pay_qr, name="tenant_pay_qr"),
]
