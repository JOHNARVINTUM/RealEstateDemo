from django.contrib import admin
from .models import Payment

@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = ("lease", "billing_month", "status", "amount_paid", "paid_at")
    list_filter = ("status", "billing_month")
    search_fields = ("lease__tenant__email", "lease__unit__number", "payment_reference")
