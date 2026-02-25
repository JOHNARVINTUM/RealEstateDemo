from django.contrib import admin
from .models import MonthlyBill


@admin.register(MonthlyBill)
class MonthlyBillAdmin(admin.ModelAdmin):
    list_display = (
        "lease",
        "billing_month",
        "due_date",
        "total_due",
        "status",
        "paid_at",
        "payment_reference",
    )
    list_filter = ("status", "billing_month", "due_date")
    search_fields = ("lease__tenant__email", "lease__unit__number", "payment_reference")
    ordering = ("-billing_month",)
    list_select_related = ("lease",)