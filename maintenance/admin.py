from django.contrib import admin
from .models import MaintenanceRequest


@admin.register(MaintenanceRequest)
class MaintenanceRequestAdmin(admin.ModelAdmin):
    list_display = ("id", "title", "tenant", "category", "status", "priority", "created_at")
    list_filter = ("category", "status", "priority", "created_at")
    search_fields = ("title", "description", "tenant__email")
    ordering = ("-created_at",)
