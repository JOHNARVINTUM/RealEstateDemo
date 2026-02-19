from django.contrib import admin
from .models import WaterBill, WaterCharge

class WaterChargeInline(admin.TabularInline):
    model = WaterCharge
    extra = 1

@admin.register(WaterBill)
class WaterBillAdmin(admin.ModelAdmin):
    list_display = ("unit", "period_start", "period_end", "invoice_number", "status", "total_amount")
    list_filter = ("status", "period_end")
    search_fields = ("unit__number", "invoice_number")
    inlines = [WaterChargeInline]
