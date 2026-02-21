from django.urls import path
from .views import manual_gcash_payment

urlpatterns = [
    path("gcash/manual/", manual_gcash_payment, name="manual_gcash_payment"),
]