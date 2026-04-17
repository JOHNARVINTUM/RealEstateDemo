from django.contrib import admin
from .models import ManualPayment
from billing.services import approve_manual_payment

@admin.register(ManualPayment)
class ManualPaymentAdmin(admin.ModelAdmin):
    list_display = ("user", "reference_code", "status", "created_at")
    list_filter = ("status", "created_at")
    search_fields = ("user__email", "reference_code", "bill_ids")
    ordering = ("-created_at",)
    list_select_related = ("user",)

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        if obj.status == "APPROVED":
            approve_manual_payment(obj)
