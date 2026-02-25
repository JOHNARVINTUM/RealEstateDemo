from django.contrib import admin
from django.utils.html import format_html

from .models import Unit, TenantProfile, Lease
from billing.models import MonthlyBill


class MonthlyBillInline(admin.TabularInline):
    model = MonthlyBill
    extra = 0
    can_delete = False
    fields = (
        "billing_month",
        "due_date",
        "base_rent",
        "water_amount",
        "interest",
        "total_due",
        "status",
        "paid_at",
        "payment_reference",
    )
    readonly_fields = ("paid_at",)


@admin.register(Unit)
class UnitAdmin(admin.ModelAdmin):
    list_display = ("number", "is_active")
    search_fields = ("number",)
    list_filter = ("is_active",)
    ordering = ("number",)


@admin.register(TenantProfile)
class TenantProfileAdmin(admin.ModelAdmin):
    list_display = ("full_name", "user_email", "contact_no")
    search_fields = ("full_name", "user__email", "user__username", "contact_no")
    list_select_related = ("user",)

    @admin.display(description="Email")
    def user_email(self, obj):
        return obj.user.email


@admin.register(Lease)
class LeaseAdmin(admin.ModelAdmin):
    list_display = (
        "tenant_email",
        "unit",
        "monthly_rent",
        "due_day",
        "start_date",
        "is_active",
    )
    search_fields = ("tenant__email", "tenant__username", "unit__number")
    list_filter = ("is_active", "start_date", "due_day")
    list_select_related = ("tenant", "unit")
    ordering = ("-start_date",)

    inlines = [MonthlyBillInline]

    @admin.display(description="Tenant Email")
    def tenant_email(self, obj):
        return obj.tenant.email