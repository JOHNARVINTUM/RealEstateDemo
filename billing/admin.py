from django.contrib import admin
from .models import Payment, PaymentTransaction, MonthlyBill


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = ("lease", "billing_month", "status", "amount_paid", "paid_at", "payment_reference")
    list_filter = ("status", "billing_month")
    search_fields = ("lease__tenant__email", "lease__unit__number", "payment_reference")


@admin.register(PaymentTransaction)
class PaymentTransactionAdmin(admin.ModelAdmin):
    list_display = ("lease", "reference", "months_paid", "total_amount", "paid_at")
    list_filter = ("paid_at",)
    search_fields = ("reference", "lease__tenant__email", "lease__unit__number")
    ordering = ("-paid_at",)


@admin.register(MonthlyBill)
class MonthlyBillAdmin(admin.ModelAdmin):
    list_display = ("lease", "billing_month", "due_date", "base_rent", "water_amount", "interest", "total_due", "status", "paid_at")
    list_filter = ("status", "billing_month", "due_date")
    search_fields = ("lease__tenant__email", "lease__unit__number", "payment_reference")
    ordering = ("-billing_month",)