import logging

from django.core.paginator import Paginator
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone

from maintenance.forms import AdminMaintenanceUpdateForm
from maintenance.models import MaintenanceRequest
from rentals.models import Lease, Notification
from rentals.services import send_email_via_resend
from django.utils import timezone as dj_timezone

from .admin_portal_views import admin_required


logger = logging.getLogger(__name__)


ARCHIVED_ORPHAN_NOTE = "Archived automatically because the linked lease or unit is no longer available."


def _archive_orphaned_requests(queryset=None):
    archived_at = dj_timezone.now()
    base_queryset = queryset if queryset is not None else MaintenanceRequest.objects.all()
    orphaned_reqs = base_queryset.filter(Q(lease__isnull=True) | Q(lease__unit__isnull=True)).exclude(status="CLOSED")

    archived_ids = []
    for req in orphaned_reqs.only("id", "status", "resolved_at", "schedule_admin_note"):
        notes = (req.schedule_admin_note or "").strip()
        if ARCHIVED_ORPHAN_NOTE not in notes:
            notes = f"{notes}\n{ARCHIVED_ORPHAN_NOTE}".strip()

        req.status = "CLOSED"
        req.resolved_at = req.resolved_at or archived_at
        req.schedule_admin_note = notes
        req.save(update_fields=["status", "resolved_at", "schedule_admin_note"])
        archived_ids.append(req.id)

    return archived_ids


def _current_active_leases_by_tenant(tenant_ids, today=None):
    if today is None:
        today = timezone.localdate()

    leases = (
        Lease.objects.select_related("unit")
        .filter(
            tenant_id__in=tenant_ids,
            status=Lease.STATUS_ACTIVE,
            start_date__lte=today,
        )
        .filter(Q(end_date__isnull=True) | Q(end_date__gte=today))
        .order_by("tenant_id", "-start_date", "-id")
    )

    current_by_tenant = {}
    for lease in leases:
        current_by_tenant.setdefault(lease.tenant_id, lease)

    missing_tenant_ids = [tenant_id for tenant_id in tenant_ids if tenant_id not in current_by_tenant]
    if missing_tenant_ids:
        latest_leases = (
            Lease.objects.select_related("unit")
            .filter(tenant_id__in=missing_tenant_ids)
            .order_by("tenant_id", "-start_date", "-id")
        )
        for lease in latest_leases:
            current_by_tenant.setdefault(lease.tenant_id, lease)

    return current_by_tenant


@admin_required
def admin_update_maintenance(request, req_id: int):
    req = get_object_or_404(MaintenanceRequest, pk=req_id)
    if req.lease_id is None:
        archived_ids = _archive_orphaned_requests(MaintenanceRequest.objects.filter(pk=req.pk))
        if archived_ids:
            req.refresh_from_db()

    if request.method == "POST":
        old_status = req.status
        old_schedule_decision = req.schedule_decision
        old_admin_scheduled_at = req.admin_scheduled_at
        old_schedule_admin_note = req.schedule_admin_note
        form = AdminMaintenanceUpdateForm(request.POST, instance=req)
        if form.is_valid():
            updated = form.save(commit=False)
            if updated.status == "RESOLVED" and not req.resolved_at:
                updated.resolved_at = dj_timezone.now()
            if updated.status != "RESOLVED":
                updated.resolved_at = None
            updated.save()

            if updated.status != old_status:
                try:
                    status_label = dict(req.STATUS_CHOICES).get(updated.status, updated.status)
                    tenant_name = req.tenant.email
                    if hasattr(req.tenant, "tenantprofile"):
                        tenant_name = req.tenant.tenantprofile.full_name
                    unit_number = req.lease.unit.number if req.lease else "N/A"
                    fixed_by_line = f"  Fixed By:    {updated.fixed_by}\n" if updated.fixed_by else ""
                    send_email_via_resend(
                        to_email=req.tenant.email,
                        subject=f"[REALESTATE360+] Maintenance Request Update - {req.title}",
                        message=(
                            f"Dear {tenant_name},\n\n"
                            f"Your maintenance request has been updated.\n\n"
                            f"  Request:     {req.title}\n"
                            f"  Category:    {req.get_category_display()}\n"
                            f"  Unit:        {unit_number}\n"
                            f"  New Status:  {status_label}\n"
                            f"{fixed_by_line}"
                            f"\n"
                            f"{'Your issue has been resolved. Thank you for your patience!' if updated.status == 'RESOLVED' else 'Our team is working on your request.'}\n\n"
                            f"You can view the status in your tenant portal.\n\n"
                            f"REALESTATE360+ Administration"
                        ),
                    )
                except Exception as e:
                    logger.exception("Failed to send maintenance update email: %s", e)

            schedule_changed = (
                updated.schedule_decision != old_schedule_decision
                or updated.admin_scheduled_at != old_admin_scheduled_at
                or updated.schedule_admin_note != old_schedule_admin_note
            )
            if schedule_changed and updated.requested_schedule_at:
                try:
                    decision_label = dict(req.SCHEDULE_DECISION_CHOICES).get(
                        updated.schedule_decision,
                        updated.schedule_decision,
                    )
                    visit_time = updated.admin_scheduled_at or updated.requested_schedule_at
                    visit_time_label = visit_time.strftime("%b %d, %Y at %I:%M %p") if visit_time else "To be confirmed"
                    note_line = f"\nAdmin note: {updated.schedule_admin_note}" if updated.schedule_admin_note else ""
                    unit_number = req.lease.unit.number if req.lease else "N/A"
                    message = (
                        f"Your maintenance visit schedule for '{req.title}' is {decision_label.lower()}.\n"
                        f"Visit time: {visit_time_label}\n"
                        f"Unit: {unit_number}"
                        f"{note_line}"
                    )
                    Notification.create_tenant_notification(
                        title="Maintenance Schedule Update",
                        message=message,
                        notification_type="MAINTENANCE",
                        tenant_user=req.tenant,
                        related_unit=req.lease.unit if req.lease else None,
                    )
                    send_email_via_resend(
                        to_email=req.tenant.email,
                        subject=f"[REALESTATE360+] Maintenance Schedule Update - {req.title}",
                        message=(
                            f"Dear {req.tenant.email},\n\n"
                            f"{message}\n\n"
                            f"You can view this update in your tenant portal.\n\n"
                            f"REALESTATE360+ Administration"
                        ),
                    )
                except Exception as e:
                    logger.exception("Failed to send maintenance schedule update: %s", e)

            return redirect("admin_maintenance")
    else:
        form = AdminMaintenanceUpdateForm(instance=req)

    return render(
        request,
        "admin_portal/maintenance_update.html",
        {
            "title": "Resolve Maintenance Issue",
            "form": form,
            "req": req,
            "back_url": reverse("admin_maintenance"),
        },
    )


@admin_required
def admin_maintenance(request):
    q = request.GET.get("q", "").strip()
    status = request.GET.get("status", "").strip()
    priority = request.GET.get("priority", "").strip()

    _archive_orphaned_requests()

    reqs = MaintenanceRequest.objects.select_related(
        "tenant",
        "tenant__tenantprofile",
        "lease",
        "lease__unit",
        "lease__tenant",
        "lease__tenant__tenantprofile",
    )

    if status:
        reqs = reqs.filter(status=status)
    else:
        reqs = reqs.exclude(status="CLOSED")

    if priority:
        reqs = reqs.filter(priority=priority)

    if q:
        reqs = reqs.filter(
            Q(tenant__email__icontains=q)
            | Q(tenant__tenantprofile__first_name__icontains=q)
            | Q(tenant__tenantprofile__last_name__icontains=q)
            | Q(lease__tenant__email__icontains=q)
            | Q(lease__unit__number__icontains=q)
            | Q(description__icontains=q)
        )

    reqs = reqs.order_by("-created_at")

    all_reqs = MaintenanceRequest.objects.all()
    if q:
        all_reqs = all_reqs.filter(
            Q(tenant__email__icontains=q)
            | Q(tenant__tenantprofile__first_name__icontains=q)
            | Q(tenant__tenantprofile__last_name__icontains=q)
            | Q(lease__tenant__email__icontains=q)
            | Q(lease__unit__number__icontains=q)
            | Q(description__icontains=q)
        )

    total_count = all_reqs.count()
    pending_count = all_reqs.filter(status="OPEN").count()
    in_progress_count = all_reqs.filter(status="IN_PROGRESS").count()
    resolved_count = all_reqs.filter(status="RESOLVED").count()

    paginator = Paginator(reqs, 10)
    page_number = request.GET.get("page")
    page_obj = paginator.get_page(page_number)
    tenant_ids = [req.tenant_id for req in page_obj.object_list]
    fallback_leases = _current_active_leases_by_tenant(tenant_ids)

    for req in page_obj.object_list:
        display_lease = req.lease or fallback_leases.get(req.tenant_id)
        req.display_lease = display_lease
        req.display_unit_number = display_lease.unit.number if display_lease and display_lease.unit else None

    try:
        from accounts.ml.maintenance_nlp import load_metrics

        nlp_metrics = load_metrics()
    except Exception:
        nlp_metrics = None

    return render(
        request,
        "admin_portal/maintenance.html",
        {
            "page_obj": page_obj,
            "q": q,
            "status": status,
            "priority": priority,
            "total_count": total_count,
            "pending_count": pending_count,
            "in_progress_count": in_progress_count,
            "resolved_count": resolved_count,
            "nlp_metrics": nlp_metrics,
        },
    )
