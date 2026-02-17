from django.contrib import admin
from .models import Unit, TenantProfile, Lease

@admin.register(Unit)
class UnitAdmin(admin.ModelAdmin):
    list_display = ("number", "is_active")
    search_fields = ("number",)
    list_filter = ("is_active",)

@admin.register(TenantProfile)
class TenantProfileAdmin(admin.ModelAdmin):
    list_display = ("full_name", "user")
    search_fields = ("full_name", "user__email")

@admin.register(Lease)
class LeaseAdmin(admin.ModelAdmin):
    list_display = ("tenant", "unit", "monthly_rent", "due_day", "start_date", "is_active")
    search_fields = ("tenant__email", "unit__number")
    list_filter = ("is_active",)
