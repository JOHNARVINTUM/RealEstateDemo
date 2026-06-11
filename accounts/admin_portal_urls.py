from django.urls import path
from .admin_portal_views import (
    admin_dashboard,
    debug_lease_form,
    simple_debug,
    admin_announcements,
    admin_create_announcement,
    admin_create_unit,
    admin_edit_announcement,
    admin_delete_announcement,
    admin_units,
    admin_unit_detail,
    admin_edit_unit,
    admin_tenant_risk,
    admin_update_tenant_risks,
    admin_delete_unit,
    admin_restore_unit,
    admin_toggle_unit_status,
    api_get_unit_data,
    api_get_unit_data_by_id,
)
from .admin_tenant_views import (
    admin_tenants,
    admin_tenant_detail,
    admin_create_tenant_profile,
    admin_edit_tenant,
    admin_delete_tenant,
    admin_tenant_attachments,
    admin_view_attachment,
    admin_delete_attachment,
)
from .admin_maintenance_views import admin_maintenance, admin_update_maintenance
from .admin_forecasting_views import admin_forecasting, admin_forecasting_data, admin_billed_this_month
from .admin_lease_views import (
    admin_create_lease,
    admin_lease_payment,
    admin_edit_lease,
    admin_delete_lease,
)
from .admin_billing_views import (
    admin_billing,
    admin_cleanup_duplicate_bills,
    admin_billing_export_csv,
    admin_repair_late_fees,
    admin_send_bill_warning,
    admin_mark_bill_paid,
    admin_mark_bill_unpaid,
    admin_delete_bill,
)
from .admin_payment_views import (
    admin_payments,
    admin_payment_calendar,
    admin_payment_detail,
    admin_reschedule_cash_payment,
    admin_approve_payment,
    admin_repair_move_in_payment,
    admin_reject_payment,
    admin_confirm_schedule,
    admin_delete_payment,
)
from .admin_notification_views import (
    admin_notifications,
    admin_delete_all_read_notifications,
    admin_mark_notification_read,
    admin_mark_all_notifications_read,
    admin_delete_notification,
)
from .admin_portal_views_water import (
    admin_water,
    admin_water_export_csv,
    admin_water_process,
    admin_water_rate,
    admin_water_recompute,
)

urlpatterns = [
    path("dashboard/", admin_dashboard, name="admin_dashboard"),
    path("tenants/", admin_tenants, name="admin_tenants"),
    path("tenants/<int:tenant_id>/", admin_tenant_detail, name="admin_tenant_detail"),
    path("tenants/<int:tenant_id>/edit/", admin_edit_tenant, name="admin_edit_tenant"),
    path("tenants/<int:tenant_id>/delete/", admin_delete_tenant, name="admin_delete_tenant"),
    path("tenants/<int:tenant_id>/attachments/", admin_tenant_attachments, name="admin_tenant_attachments"),
    path("attachments/<int:attachment_id>/view/", admin_view_attachment, name="admin_view_attachment"),
    path("attachments/<int:attachment_id>/delete/", admin_delete_attachment, name="admin_delete_attachment"),
    path("billing/", admin_billing, name="admin_billing"),
    path("billing/cleanup-duplicates/", admin_cleanup_duplicate_bills, name="admin_cleanup_duplicate_bills"),
    path("billing/export/", admin_billing_export_csv, name="admin_billing_export_csv"),
    path("billing/repair-late-fees/", admin_repair_late_fees, name="admin_repair_late_fees"),
    path("billing/<int:bill_id>/send-warning/", admin_send_bill_warning, name="admin_send_bill_warning"),
    path("billing/mark_paid/<int:bill_id>/", admin_mark_bill_paid, name="admin_mark_bill_paid"),
    path("billing/mark_unpaid/<int:bill_id>/", admin_mark_bill_unpaid, name="admin_mark_bill_unpaid"),
    path("billing/<int:bill_id>/delete/", admin_delete_bill, name="admin_delete_bill"),
    
    # Water Management
    path("water/", admin_water, name="admin_water"),
    path("water/export/", admin_water_export_csv, name="admin_water_export_csv"),
    path("water/process/", admin_water_process, name="admin_water_process"),
    path("water/rate/", admin_water_rate, name="admin_water_rate"),
    path("water/recompute/", admin_water_recompute, name="admin_water_recompute"),
    
    path("payments/", admin_payments, name="admin_payments"),
    path("payments/calendar/", admin_payment_calendar, name="admin_payment_calendar"),
    path("payments/<int:payment_id>/detail/", admin_payment_detail, name="admin_payment_detail"),
    path("payments/<int:payment_id>/reschedule/", admin_reschedule_cash_payment, name="admin_reschedule_cash_payment"),
    path("payments/<int:payment_id>/approve/", admin_approve_payment, name="admin_approve_payment"),
    path("payments/<int:payment_id>/repair-move-in/", admin_repair_move_in_payment, name="admin_repair_move_in_payment"),
    path("payments/<int:payment_id>/reject/", admin_reject_payment, name="admin_reject_payment"),
    path("payments/<int:payment_id>/confirm-schedule/", admin_confirm_schedule, name="admin_confirm_schedule"),
    path("payments/<int:payment_id>/delete/", admin_delete_payment, name="admin_delete_payment"),
    path("maintenance/", admin_maintenance, name="admin_maintenance"),
    path("maintenance/<int:req_id>/update/", admin_update_maintenance, name="admin_update_maintenance"),
    path("announcements/", admin_announcements, name="admin_announcements"),
    
    # Tenant Risk Classification
    path("tenant-risk/", admin_tenant_risk, name="admin_tenant_risk"),
    path("tenant-risk/update/", admin_update_tenant_risks, name="admin_update_tenant_risks"),
    
    # Notifications
    path("notifications/", admin_notifications, name="admin_notifications"),
    path("notifications/delete-read/", admin_delete_all_read_notifications, name="admin_delete_all_read_notifications"),
    path("notifications/<int:notification_id>/read/", admin_mark_notification_read, name="admin_mark_notification_read"),
    path("notifications/mark-all-read/", admin_mark_all_notifications_read, name="admin_mark_all_notifications_read"),
    path("notifications/<int:notification_id>/delete/", admin_delete_notification, name="admin_delete_notification"),
    
    # Unit Management
    path("units/", admin_units, name="admin_units"),
    path("units/<int:unit_id>/", admin_unit_detail, name="admin_unit_detail"),
    path("units/<int:unit_id>/edit/", admin_edit_unit, name="admin_edit_unit"),
    path("units/<int:unit_id>/delete/", admin_delete_unit, name="admin_delete_unit"),
    path("units/<int:unit_id>/restore/", admin_restore_unit, name="admin_restore_unit"),
    path("units/<int:unit_id>/toggle-status/", admin_toggle_unit_status, name="admin_toggle_unit_status"),
    path("api/unit/<str:unit_number>/", api_get_unit_data, name="api_get_unit_data"),
    path("api/unit/by-id/<int:unit_id>/", api_get_unit_data_by_id, name="api_get_unit_data_by_id"),
    path("debug-lease-form/", debug_lease_form, name="debug_lease_form"),
    path("simple-debug/", simple_debug, name="simple_debug"),
    
    # Create pages
    path("tenants/add/", admin_create_tenant_profile, name="admin_create_tenant_profile"),
    path("leases/add/", admin_create_lease, name="admin_create_lease"),
    path("leases/<int:lease_id>/payment/", admin_lease_payment, name="admin_lease_payment"),
    path("units/add/", admin_create_unit, name="admin_create_unit"),
    path("leases/<int:lease_id>/edit/", admin_edit_lease, name="admin_edit_lease"),
    path("leases/<int:lease_id>/delete/", admin_delete_lease, name="admin_delete_lease"),
    path("announcements/add/", admin_create_announcement, name="admin_create_announcement"),
    path("announcements/<int:ann_id>/edit/", admin_edit_announcement, name="admin_edit_announcement"),
    path("announcements/<int:ann_id>/delete/", admin_delete_announcement, name="admin_delete_announcement"),

    # Forecasting
    path("forecasting/", admin_forecasting, name="admin_forecasting"),
    path("forecasting/data/", admin_forecasting_data, name="admin_forecasting_data"),

    # Billed This Month Breakdown
    path("billing/billed-this-month/", admin_billed_this_month, name="admin_billed_this_month"),
]
