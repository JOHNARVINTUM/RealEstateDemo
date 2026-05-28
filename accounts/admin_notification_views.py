from django.contrib import messages
from functools import lru_cache
from django.db import connection
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone

from maintenance.models import MaintenanceRequest
from rentals.models import Notification

from .admin_portal_views import admin_required, admin_password_verified, render_admin_password_confirm


@lru_cache(maxsize=1)
def notification_has_read_at_column() -> bool:
    """Return True when the notifications table already has the read_at column."""
    with connection.cursor() as cursor:
        columns = connection.introspection.get_table_description(cursor, Notification._meta.db_table)
    return any(column.name == "read_at" for column in columns)


def resolve_notification_target_url(notification):
    """Return the best action URL for a notification when one can be resolved safely."""
    if notification.notification_type == "PAYMENT":
        return f"{reverse('admin_payments')}?status=PENDING"

    if notification.notification_type != "MAINTENANCE" or not notification.related_tenant:
        return None

    title_marker = "maintenance request:"
    message_lower = notification.message.lower()
    if title_marker not in message_lower:
        return reverse("admin_maintenance")

    marker_index = message_lower.rfind(title_marker)
    request_title = notification.message[marker_index + len(title_marker):].strip().rstrip(".")
    if not request_title:
        return reverse("admin_maintenance")

    maintenance_qs = MaintenanceRequest.objects.filter(
        tenant=notification.related_tenant,
        title__iexact=request_title,
    ).order_by("-created_at")

    maintenance_request = maintenance_qs.first()
    if maintenance_request:
        return reverse("admin_update_maintenance", args=[maintenance_request.id])

    return reverse("admin_maintenance")


@admin_required
def admin_notifications(request):
    """Admin portal: view admin notifications only."""
    base_notifications = Notification.objects.filter(
        recipient_type__in=["ADMIN", "SPECIFIC_USER"]
    ).select_related("related_tenant__tenantprofile", "related_unit")
    notifications = base_notifications

    status_filter = request.GET.get("status", "all")
    if status_filter == "unread":
        notifications = notifications.filter(is_read=False)
    elif status_filter == "read":
        notifications = notifications.filter(is_read=True)

    notifications = notifications.order_by("-created_at")
    notification_list = list(notifications)
    for notification in notification_list:
        notification.target_url = resolve_notification_target_url(notification)
    unread_count = base_notifications.filter(is_read=False).count()

    is_ajax = (
        request.GET.get("format") == "json"
        and request.headers.get("X-Requested-With") == "XMLHttpRequest"
    )
    if is_ajax:
        return JsonResponse({
            "unread_count": unread_count,
            "notifications": [
                {
                    "id": n.id,
                    "title": n.title,
                    "message": n.message,
                    "notification_type": n.notification_type,
                    "is_read": n.is_read,
                    "target_url": getattr(n, "target_url", None),
                    "created_at": n.created_at.strftime("%Y-%m-%d %H:%M:%S"),
                    "related_tenant": {
                        "email": n.related_tenant.email if n.related_tenant else None,
                        "name": (
                            n.related_tenant.tenantprofile.full_name
                            if n.related_tenant
                            and hasattr(n.related_tenant, "tenantprofile")
                            and n.related_tenant.tenantprofile
                            else n.related_tenant.email if n.related_tenant else None
                        ),
                    } if n.related_tenant else None,
                    "related_unit": {
                        "number": n.related_unit.number if n.related_unit else None,
                        "type": n.related_unit.get_unit_type_display() if n.related_unit else None,
                    } if n.related_unit else None,
                }
                for n in notification_list
            ],
        })

    return render(request, "admin_portal/notifications.html", {
        "notifications": notification_list,
        "unread_count": unread_count,
        "status_filter": status_filter,
    })


@admin_required
def admin_mark_notification_read(request, notification_id):
    """Admin portal: mark notification as read."""
    notification = get_object_or_404(Notification, id=notification_id)
    notification.is_read = True
    if notification_has_read_at_column():
        notification.read_at = timezone.now()
        notification.save(update_fields=["is_read", "read_at"])
    else:
        notification.save(update_fields=["is_read"])

    if request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return JsonResponse({"success": True})

    return redirect("admin_notifications")


@admin_required
def admin_mark_all_notifications_read(request):
    """Admin portal: mark all notifications as read."""
    unread_notifications = Notification.objects.filter(
        recipient_type__in=["ADMIN", "SPECIFIC_USER"],
        is_read=False,
    )
    if notification_has_read_at_column():
        unread_notifications.update(is_read=True, read_at=timezone.now())
    else:
        unread_notifications.update(is_read=True)

    if request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return JsonResponse({"success": True})

    return redirect("admin_notifications")


@admin_required
def admin_delete_notification(request, notification_id):
    """Admin portal: delete notification."""
    notification = get_object_or_404(Notification, id=notification_id)

    if request.method == "POST":
        if not admin_password_verified(request):
            return render_admin_password_confirm(
                request,
                title="Delete Notification",
                message=f"Delete notification '{notification.title}'?",
                post_url=reverse("admin_delete_notification", args=[notification.id]),
                back_url=reverse("admin_notifications"),
                error="Incorrect admin password. Notification was not deleted.",
            )
        notification_title = notification.title
        notification.delete()
        messages.success(request, f"Notification '{notification_title}' has been deleted successfully.")
        return redirect("admin_notifications")

    return render_admin_password_confirm(
        request,
        title="Delete Notification",
        message=f"Delete notification '{notification.title}'?",
        post_url=reverse("admin_delete_notification", args=[notification.id]),
        back_url=reverse("admin_notifications"),
    )
