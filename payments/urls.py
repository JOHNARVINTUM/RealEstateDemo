from django.urls import path
from .views import manual_gcash_payment, f2f_cash_payment

urlpatterns = [
    path("gcash/manual/", manual_gcash_payment, name="manual_gcash_payment"),
    path("cash/f2f/", f2f_cash_payment, name="f2f_cash_payment"),
]