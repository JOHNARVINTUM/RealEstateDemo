from django.contrib import admin
from django.utils.html import format_html
from django.utils import timezone

from .models import Unit, TenantProfile, Lease, CalendarEvent
from billing.models import MonthlyBill
from rentals.unit_status import sync_unit_status


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


# Update Lease admin to include calendar events inline
class CalendarEventInline(admin.TabularInline):
    model = CalendarEvent
    extra = 0
    can_delete = False
    fields = (
        "event_type",
        "event_date",
        "amount",
        "status",
    )
    readonly_fields = ("event_type", "event_date", "amount", "status")
    
    def has_add_permission(self, request, obj=None):
        return False  # Don't allow adding events manually


@admin.register(Unit)
class UnitAdmin(admin.ModelAdmin):
    list_display = ("number", "status", "is_active")
    search_fields = ("number",)
    list_filter = ("status", "is_active")
    ordering = ("number",)
    actions = ["sync_selected_statuses"]

    @admin.action(description="Sync selected unit statuses from active leases")
    def sync_selected_statuses(self, request, queryset):
        updated = 0
        for unit in queryset:
            if sync_unit_status(unit):
                updated += 1
        self.message_user(request, f"Synced {updated} unit status record(s).")


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

    inlines = [MonthlyBillInline, CalendarEventInline]

    @admin.display(description="Tenant Email")
    def tenant_email(self, obj):
        return obj.tenant.email


@admin.register(CalendarEvent)
class CalendarEventAdmin(admin.ModelAdmin):
    list_display = (
        "event_date",
        "event_type_display",
        "tenant_email",
        "unit_number",
        "amount_display",
        "status_display",
        "created_at",
    )
    list_filter = (
        "event_type",
        "status",
        "event_date",
        "created_at",
    )
    search_fields = (
        "tenant__email",
        "tenant__username",
        "lease__unit__number",
    )
    list_select_related = ("tenant", "lease", "lease__unit")
    ordering = ("-event_date", "event_type")
    date_hierarchy = "event_date"
    
    readonly_fields = ("created_at", "updated_at")
    
    fieldsets = (
        ("Event Information", {
            "fields": (
                "lease",
                "tenant",
                "event_type",
                "event_date",
                "amount",
                "status",
            )
        }),
        ("System Information", {
            "fields": (
                "created_at",
                "updated_at",
            ),
            "classes": ("collapse",),
        }),
    )
    
    @admin.display(description="Event Type")
    def event_type_display(self, obj):
        colors = {
            'RENT_DUE': '#007bff',
            'ADVANCE_PAYMENT': '#17a2b8',
            'SECURITY_DEPOSIT': '#ffc107',
            'CONTRACT_START': '#28a745',
            'CONTRACT_END': '#dc3545',
        }
        color = colors.get(obj.event_type, '#6c757d')
        return format_html(
            '<span style="color: {}; font-weight: bold;">{}</span>',
            color,
            obj.get_event_type_display()
        )
    
    @admin.display(description="Tenant")
    def tenant_email(self, obj):
        return obj.tenant.email
    
    @admin.display(description="Unit")
    def unit_number(self, obj):
        return obj.lease.unit.number if obj.lease else "N/A"
    
    @admin.display(description="Amount")
    def amount_display(self, obj):
        if obj.amount:
            return f"₱{obj.amount:,.2f}"
        return "—"
    
    @admin.display(description="Status")
    def status_display(self, obj):
        colors = {
            'PENDING': '#ffc107',
            'PAID': '#28a745',
            'OVERDUE': '#dc3545',
        }
        color = colors.get(obj.status, '#6c757d')
        return format_html(
            '<span style="color: {}; font-weight: bold;">{}</span>',
            color,
            obj.get_status_display()
        )
    
    def get_queryset(self, request):
        qs = super().get_queryset(request)
        # Optimize queries
        return qs.select_related('tenant', 'lease', 'lease__unit')
    
    actions = ['mark_as_paid', 'mark_as_overdue']
    
    @admin.action(description="Mark selected events as paid")
    def mark_as_paid(self, request, queryset):
        updated = queryset.update(status='PAID')
        self.message_user(request, f'{updated} events marked as paid.')
    
    @admin.action(description="Mark selected events as overdue")
    def mark_as_overdue(self, request, queryset):
        updated = queryset.update(status='OVERDUE')
        self.message_user(request, f'{updated} events marked as overdue.')
