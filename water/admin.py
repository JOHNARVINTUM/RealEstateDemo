from django.contrib import admin, messages
from django.utils.html import format_html
from django.utils.safestring import mark_safe
from decimal import Decimal

from .models import WaterBill, WaterCharge, WaterRate, WaterReading, WaterComputationLog
from .services import compute_water_reading, create_or_update_monthly_bill_from_reading


class WaterChargeInline(admin.TabularInline):
    model = WaterCharge
    extra = 1


@admin.register(WaterBill)
class WaterBillAdmin(admin.ModelAdmin):
    list_display = ("unit", "period_start", "period_end", "invoice_number", "status", "total_amount")
    list_filter = ("status", "period_end")
    search_fields = ("unit__number", "invoice_number")
    inlines = [WaterChargeInline]


@admin.register(WaterRate)
class WaterRateAdmin(admin.ModelAdmin):
    """Admin for global water rate configuration"""
    list_display = ("effective_date", "rate_per_cu_m", "is_active", "created_at")
    list_filter = ("is_active", "effective_date")
    search_fields = ("notes",)
    date_hierarchy = "effective_date"
    
    fieldsets = (
        (None, {
            "fields": ("effective_date", "rate_per_cu_m", "is_active")
        }),
        ("Notes", {
            "fields": ("notes",),
            "classes": ("collapse",)
        }),
    )
    
    def save_model(self, request, obj, form, change):
        obj.created_by = request.user
        super().save_model(request, obj, form, change)


@admin.register(WaterReading)
class WaterReadingAdmin(admin.ModelAdmin):
    """Admin for manual meter readings"""
    list_display = (
        "lease_info", 
        "reading_month", 
        "previous_reading", 
        "current_reading",
        "consumption",
        "computed_amount",
        "bill_status",
        "is_first_reading"
    )
    list_filter = ("is_first_reading", "reading_month")
    search_fields = ("lease__unit__number", "lease__tenant__email")
    date_hierarchy = "reading_month"
    
    readonly_fields = (
        "consumption", 
        "rate_used", 
        "computed_amount",
        "monthly_bill_status",
        "read_at"
    )
    
    fieldsets = (
        ("Lease & Month", {
            "fields": ("lease", "reading_month")
        }),
        ("Meter Readings", {
            "fields": ("previous_reading", "current_reading", "is_first_reading")
        }),
        ("Computed Values", {
            "fields": ("consumption", "rate_used", "computed_amount"),
            "classes": ("collapse",)
        }),
        ("Audit", {
            "fields": ("read_by", "read_at", "monthly_bill_status"),
            "classes": ("collapse",)
        }),
    )
    
    actions = ["compute_and_create_bill"]
    
    def lease_info(self, obj):
        unit = obj.lease.unit.number if obj.lease and obj.lease.unit else "?"
        tenant = obj.lease.tenant.email if obj.lease and obj.lease.tenant else "?"
        return f"Unit {unit} - {tenant}"
    lease_info.short_description = "Lease"
    
    def bill_status(self, obj):
        # Check if any MonthlyBill references this reading
        from billing.models import MonthlyBill
        bill = MonthlyBill.objects.filter(source_water_reading=obj).first()
        if bill:
            status = bill.status
            bill_id = bill.id
            color = "green" if status == "PAID" else "orange"
            return format_html(
                '<span style="color: {};">Bill #{} ({})</span>',
                color, bill_id, status
            )
        return format_html('<span style="color: gray;">No bill</span>', '')
    bill_status.short_description = "Bill Status"
    
    def monthly_bill_status(self, obj):
        # Show linked bill info
        from billing.models import MonthlyBill
        bill = MonthlyBill.objects.filter(source_water_reading=obj).first()
        if bill:
            from django.urls import reverse
            url = reverse("admin:billing_monthlybill_change", args=[bill.id])
            return mark_safe(
                f'<a href="{url}">Bill #{bill.id}</a> ({bill.status})'
            )
        return "Not linked to any bill"
    monthly_bill_status.short_description = "Linked Monthly Bill"
    
    @admin.action(description="Compute water & create/update MonthlyBill")
    def compute_and_create_bill(self, request, queryset):
        """Admin action to manually trigger bill creation from readings"""
        success_count = 0
        error_count = 0
        
        for reading in queryset:
            try:
                # Compute values
                compute_water_reading(reading)
                
                # Create or update bill
                bill, created = create_or_update_monthly_bill_from_reading(
                    reading,
                    computed_by=request.user,
                    force_update=True
                )
                
                action = "created" if created else "updated"
                messages.success(
                    request,
                    f"Bill #{bill.id} {action} for {reading} (₱{reading.computed_amount})"
                )
                success_count += 1
                
            except Exception as e:
                messages.error(request, f"Error for {reading}: {str(e)}")
                error_count += 1
        
        if success_count:
            messages.success(request, f"Successfully processed {success_count} reading(s)")
        if error_count:
            messages.error(request, f"Failed to process {error_count} reading(s)")
    
    def save_model(self, request, obj, form, change):
        """Auto-compute values on save"""
        if not obj.read_by:
            obj.read_by = request.user
        
        # Compute consumption and amount
        try:
            compute_water_reading(obj)
        except Exception as e:
            messages.warning(request, f"Warning: {e}")
        
        super().save_model(request, obj, form, change)
    
    def changelist_view(self, request, extra_context=None):
        """Add bulk entry link to changelist"""
        extra_context = extra_context or {}
        extra_context['bulk_entry_url'] = '/water/bulk-entry/'
        return super().changelist_view(request, extra_context=extra_context)


@admin.register(WaterComputationLog)
class WaterComputationLogAdmin(admin.ModelAdmin):
    """Audit log for water computations"""
    list_display = ("water_reading", "monthly_bill", "computed_by", "computed_at")
    list_filter = ("computed_at",)
    search_fields = ("water_reading__lease__unit__number", "notes")
    readonly_fields = ("water_reading", "monthly_bill", "computed_by", "computed_at")
    
    def has_add_permission(self, request):
        return False  # Logs are auto-created
    
    def has_change_permission(self, request, obj=None):
        return False  # Logs are immutable
