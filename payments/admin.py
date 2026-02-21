from django.contrib import admin
from .models import ManualPayment


@admin.register(ManualPayment)
class ManualPaymentAdmin(admin.ModelAdmin):
    list_display = ("user", "reference_code", "status", "created_at")
    list_filter = ("status", "created_at")
    search_fields = ("user__email", "reference_code")
    actions = ["approve_selected", "reject_selected"]

    @admin.action(description="Approve selected manual payments")
    def approve_selected(self, request, queryset):
        queryset.filter(status="PENDING").update(status="APPROVED")

    @admin.action(description="Reject selected manual payments")
    def reject_selected(self, request, queryset):
        queryset.filter(status="PENDING").update(status="REJECTED")