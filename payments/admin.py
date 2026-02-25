from django.contrib import admin
from django.utils import timezone
from .models import ManualPayment
from billing.models import MonthlyBill

@admin.register(ManualPayment)
class ManualPaymentAdmin(admin.ModelAdmin):
    list_display = ("user", "reference_code", "status", "created_at")
    list_filter = ("status", "created_at")
    search_fields = ("user__email", "reference_code", "bill_ids")
    ordering = ("-created_at",)
    list_select_related = ("user",)

    def save_model(self, request, obj, form, change):
        # 1. First, save the ManualPayment object as usual
        super().save_model(request, obj, form, change)
        
        # 2. If the admin just changed the status to APPROVED, update the bills!
        if obj.status == "APPROVED" and obj.bill_ids:
            # Split the comma-separated string back into a list (e.g., "27,28" -> ["27", "28"])
            bill_id_list = [bid.strip() for bid in obj.bill_ids.split(",") if bid.strip()]
            
            for bill_id in bill_id_list:
                try:
                    # Find the exact bill
                    bill = MonthlyBill.objects.get(id=bill_id)
                    
                    # If it's not already paid, mark it PAID and record the exact time
                    if bill.status != "PAID":
                        bill.status = "PAID"
                        bill.paid_at = timezone.now()
                        bill.save()
                        
                except MonthlyBill.DoesNotExist:
                    continue