from django.urls import path
from .views import (
    manual_gcash_payment,
    f2f_cash_payment,
    paymongo_checkout,
    paymongo_success,
    paymongo_webhook,
    admin_paymongo_checkout_generate,
)

urlpatterns = [
    path("gcash/manual/", manual_gcash_payment, name="manual_gcash_payment"),
    path("cash/f2f/", f2f_cash_payment, name="f2f_cash_payment"),
    path("paymongo/checkout/", paymongo_checkout, name="paymongo_checkout"),
    path("paymongo/success/", paymongo_success, name="paymongo_success"),
    path("paymongo/webhook/", paymongo_webhook, name="paymongo_webhook"),
    path("paymongo/admin-checkout/", admin_paymongo_checkout_generate, name="admin_paymongo_checkout"),
]