import logging

from django.contrib import messages
from django.core.paginator import Paginator
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils import timezone as dj_timezone

from maintenance.forms import AdminMaintenanceUpdateForm, StaffMaintenanceChargeSuggestionForm, StaffMaintenanceUpdateForm
from maintenance.models import MaintenanceCharge, MaintenanceRequest
from rentals.models import Lease, Notification
from rentals.services import send_email_via_resend

from .decorators import staff_or_admin_required


logger = logging.getLogger(__name__)


ARCHIVED_ORPHAN_NOTE = "Archived automatically because the linked lease or unit is no longer available."


def _is_staff_portal_user(user):
    return getattr(user, "role", "") == "STAFF"


def _maintenance_request_queryset():
    return MaintenanceRequest.objects.select_related(
        "tenant",
        "tenant__tenantprofile",
        "lease",
        "lease__unit",
        "lease__tenant",
        "lease__tenant__tenantprofile",
        "assigned_staff",
        "assigned_staff__tenantprofile",
    )


def _visible_maintenance_queryset_for_user(user):
    qs = _maintenance_request_queryset()
    if _is_staff_portal_user(user):
        qs = qs.filter(review_status="ACCEPTED", assigned_staff=user)
    return qs


def _display_name(user):
    if not user:
        return "Unknown user"
    profile = getattr(user, "tenantprofile", None)
    if profile and getattr(profile, "full_name", ""):
        return profile.full_name
    return user.email


def _maintenance_charge_for_request(req):
    try:
        return req.charge
    except MaintenanceCharge.DoesNotExist:
        return None


def _staff_can_edit_charge(req, user, charge):
    if getattr(user, "role", "") != "STAFF":
        return False
    if req.review_status != "ACCEPTED" or req.assigned_staff_id != user.id:
        return False
    if charge is None:
        return True
    return charge.status == MaintenanceCharge.STATUS_PENDING_REVIEW


def _charge_lock_message(charge):
    if not charge:
        return ""
    if charge.status == MaintenanceCharge.STATUS_APPROVED:
        return "Admin already finalized this repair cost suggestion."
    if charge.status == MaintenanceCharge.STATUS_NO_CHARGE:
        return "Admin marked this request as no charge."
    if charge.status == MaintenanceCharge.STATUS_READY_FOR_BILLING:
        return "This repair cost suggestion is already approved and waiting for billing."
    if charge.status == MaintenanceCharge.STATUS_ADDED_TO_BILL:
        return "This repair cost suggestion was already linked to billing."
    return ""


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
        req.review_status = "REJECTED"
        req.assigned_staff = None
        req.resolved_at = req.resolved_at or archived_at
        req.schedule_admin_note = notes
        req.save(update_fields=["status", "review_status", "assigned_staff", "resolved_at", "schedule_admin_note"])
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


def _notify_tenant_review_update(req, *, old_review_status):
    if req.review_status == old_review_status:
        return

    unit_number = req.lease.unit.number if req.lease and req.lease.unit else "N/A"
    assigned_staff_name = _display_name(req.assigned_staff) if req.assigned_staff else "No staff assigned yet"

    if req.review_status == "ACCEPTED":
        title = "Maintenance Request Accepted"
        message = (
            f"Your maintenance request '{req.title}' has been accepted.\n"
            f"Assigned staff: {assigned_staff_name}\n"
            f"Unit: {unit_number}"
        )
        email_subject = f"[REALESTATE360+] Maintenance Request Accepted - {req.title}"
    elif req.review_status == "REJECTED":
        title = "Maintenance Request Rejected"
        reason = req.schedule_admin_note or "Please contact administration if you need clarification."
        message = (
            f"Your maintenance request '{req.title}' was not approved for dispatch.\n"
            f"Unit: {unit_number}\n"
            f"Admin note: {reason}"
        )
        email_subject = f"[REALESTATE360+] Maintenance Request Rejected - {req.title}"
    else:
        title = "Maintenance Request Review Reset"
        message = (
            f"Your maintenance request '{req.title}' is back in admin review.\n"
            f"Unit: {unit_number}"
        )
        email_subject = f"[REALESTATE360+] Maintenance Request Review Update - {req.title}"

    try:
        Notification.create_tenant_notification(
            title=title,
            message=message,
            notification_type="MAINTENANCE",
            tenant_user=req.tenant,
            related_unit=req.lease.unit if req.lease else None,
        )
    except Exception as exc:
        logger.exception("Failed to create maintenance review notification: %s", exc)

    try:
        send_email_via_resend(
            to_email=req.tenant.email,
            subject=email_subject,
            message=(
                f"Dear {_display_name(req.tenant)},\n\n"
                f"{message}\n\n"
                "You can view the latest maintenance status in your tenant portal.\n\n"
                "REALESTATE360+ Administration"
            ),
        )
    except Exception as exc:
        logger.exception("Failed to send maintenance review email: %s", exc)


def _notify_staff_assignment(req, *, previous_staff_id):
    if not req.assigned_staff or req.assigned_staff_id == previous_staff_id:
        return

    unit_number = req.lease.unit.number if req.lease and req.lease.unit else "N/A"
    tenant_name = _display_name(req.tenant)
    assignment_message = (
        f"You were assigned to maintenance request #{req.id}: {req.title}.\n"
        f"Tenant: {tenant_name}\n"
        f"Unit: {unit_number}"
    )

    try:
        Notification.create_notification(
            title="Maintenance Request Assigned",
            message=assignment_message,
            notification_type="MAINTENANCE",
            user=req.assigned_staff,
            related_unit=req.lease.unit if req.lease else None,
            related_tenant=req.tenant,
            recipient_type="SPECIFIC_USER",
        )
    except Exception as exc:
        logger.exception("Failed to create staff maintenance assignment notification: %s", exc)

    try:
        send_email_via_resend(
            to_email=req.assigned_staff.email,
            subject=f"[REALESTATE360+] Assigned Maintenance Request - {req.title}",
            message=(
                f"Hello {_display_name(req.assigned_staff)},\n\n"
                f"{assignment_message}\n\n"
                "Please open the shared admin portal to update the work status.\n\n"
                "REALESTATE360+ Administration"
            ),
        )
    except Exception as exc:
        logger.exception("Failed to send maintenance assignment email: %s", exc)


@staff_or_admin_required
def admin_update_maintenance(request, req_id: int):
    visible_queryset = _visible_maintenance_queryset_for_user(request.user)
    req = get_object_or_404(visible_queryset, pk=req_id)
    is_staff_portal = _is_staff_portal_user(request.user)
    charge = _maintenance_charge_for_request(req)

    if req.lease_id is None:
        archived_ids = _archive_orphaned_requests(MaintenanceRequest.objects.filter(pk=req.pk))
        if archived_ids:
            req.refresh_from_db()
            charge = _maintenance_charge_for_request(req)

    can_edit_charge = _staff_can_edit_charge(req, request.user, charge)
    locked_charge_message = _charge_lock_message(charge)

    if request.method == "POST":
        old_status = req.status
        old_review_status = req.review_status
        old_assigned_staff_id = req.assigned_staff_id
        old_schedule_decision = req.schedule_decision
        old_admin_scheduled_at = req.admin_scheduled_at
        old_schedule_admin_note = req.schedule_admin_note
        form_class = StaffMaintenanceUpdateForm if is_staff_portal else AdminMaintenanceUpdateForm
        action = request.POST.get("form_action", "progress")

        if is_staff_portal and action == "charge_suggestion":
            form = StaffMaintenanceUpdateForm(instance=req)
            charge_form = StaffMaintenanceChargeSuggestionForm(
                request.POST,
                instance=charge or MaintenanceCharge(),
                maintenance_request=req,
                staff_user=request.user,
            )
            if not can_edit_charge:
                messages.error(request, locked_charge_message or "You cannot edit the repair cost suggestion for this request.")
                return redirect("admin_update_maintenance", req_id=req.id)
            if charge_form.is_valid():
                charge = charge_form.save()
                messages.success(request, "Repair cost suggestion saved.")
                return redirect("admin_update_maintenance", req_id=req.id)
        else:
            form = form_class(request.POST, instance=req)
            charge_form = None
            if is_staff_portal:
                charge_form = StaffMaintenanceChargeSuggestionForm(
                    instance=charge or MaintenanceCharge(),
                    maintenance_request=req,
                    staff_user=request.user,
                ) if can_edit_charge else None
            if form.is_valid():
                updated = form.save(commit=False)

                if is_staff_portal:
                    updated.review_status = req.review_status
                    updated.assigned_staff = req.assigned_staff
                    updated.category = req.category
                    updated.priority = req.priority
                    updated.schedule_decision = req.schedule_decision
                    updated.admin_scheduled_at = req.admin_scheduled_at
                    updated.schedule_admin_note = req.schedule_admin_note
                else:
                    if updated.review_status == "ACCEPTED" and updated.status == "CLOSED":
                        updated.status = "OPEN"
                    if updated.review_status == "REJECTED":
                        updated.assigned_staff = None
                        updated.fixed_by = ""
                        updated.status = "CLOSED"
                        if updated.requested_schedule_at and updated.schedule_decision == "PENDING":
                            updated.schedule_decision = "DECLINED"
                    if updated.review_status == "PENDING":
                        updated.assigned_staff = None
                        updated.fixed_by = ""
                        if updated.status in {"IN_PROGRESS", "RESOLVED", "CLOSED"}:
                            updated.status = "OPEN"

                if updated.status == "RESOLVED":
                    if not req.resolved_at:
                        updated.resolved_at = dj_timezone.now()
                else:
                    updated.resolved_at = None

                updated.save()

                if not is_staff_portal:
                    _notify_tenant_review_update(updated, old_review_status=old_review_status)
                    _notify_staff_assignment(updated, previous_staff_id=old_assigned_staff_id)

                if updated.status != old_status:
                    try:
                        status_label = dict(MaintenanceRequest.STATUS_CHOICES).get(updated.status, updated.status)
                        tenant_name = _display_name(updated.tenant)
                        unit_number = updated.lease.unit.number if updated.lease and updated.lease.unit else "N/A"
                        fixed_by_line = f"  Fixed By:    {updated.fixed_by}\n" if updated.fixed_by else ""
                        send_email_via_resend(
                            to_email=updated.tenant.email,
                            subject=f"[REALESTATE360+] Maintenance Request Update - {updated.title}",
                            message=(
                                f"Dear {tenant_name}\n\n"
                                "Your maintenance request has been updated.\n\n"
                                f"  Request:     {updated.title}\n"
                                f"  Category:    {updated.get_category_display()}\n"
                                f"  Unit:        {unit_number}\n"
                                f"  New Status:  {status_label}\n"
                                f"{fixed_by_line}\n"
                                f"{'Your issue has been resolved. Thank you for your patience!' if updated.status == 'RESOLVED' else 'Our team is working on your request.'}\n\n"
                                "You can view the status in your tenant portal.\n\n"
                                "REALESTATE360+ Administration"
                            ),
                        )
                    except Exception as exc:
                        logger.exception("Failed to send maintenance update email: %s", exc)

                schedule_changed = (
                    updated.schedule_decision != old_schedule_decision
                    or updated.admin_scheduled_at != old_admin_scheduled_at
                    or updated.schedule_admin_note != old_schedule_admin_note
                )
                if (not is_staff_portal) and schedule_changed and updated.requested_schedule_at:
                    try:
                        decision_label = dict(MaintenanceRequest.SCHEDULE_DECISION_CHOICES).get(
                            updated.schedule_decision,
                            updated.schedule_decision,
                        )
                        visit_time = updated.admin_scheduled_at or updated.requested_schedule_at
                        visit_time_label = visit_time.strftime("%b %d, %Y at %I:%M %p") if visit_time else "To be confirmed"
                        note_line = f"\nAdmin note: {updated.schedule_admin_note}" if updated.schedule_admin_note else ""
                        unit_number = updated.lease.unit.number if updated.lease and updated.lease.unit else "N/A"
                        message = (
                            f"Your maintenance visit schedule for '{updated.title}' is {decision_label.lower()}.\n"
                            f"Visit time: {visit_time_label}\n"
                            f"Unit: {unit_number}"
                            f"{note_line}"
                        )
                        Notification.create_tenant_notification(
                            title="Maintenance Schedule Update",
                            message=message,
                            notification_type="MAINTENANCE",
                            tenant_user=updated.tenant,
                            related_unit=updated.lease.unit if updated.lease else None,
                        )
                        send_email_via_resend(
                            to_email=updated.tenant.email,
                            subject=f"[REALESTATE360+] Maintenance Schedule Update - {updated.title}",
                            message=(
                                f"Dear {_display_name(updated.tenant)}\n\n"
                                f"{message}\n\n"
                                "You can view this update in your tenant portal.\n\n"
                                "REALESTATE360+ Administration"
                            ),
                        )
                    except Exception as exc:
                        logger.exception("Failed to send maintenance schedule update: %s", exc)

                messages.success(
                    request,
                    "Maintenance progress updated." if is_staff_portal else "Maintenance review saved.",
                )
                return redirect("admin_maintenance")
    else:
        form = StaffMaintenanceUpdateForm(instance=req) if is_staff_portal else AdminMaintenanceUpdateForm(instance=req)
        charge_form = None
        if is_staff_portal and can_edit_charge:
            charge_form = StaffMaintenanceChargeSuggestionForm(
                instance=charge or MaintenanceCharge(),
                maintenance_request=req,
                staff_user=request.user,
            )

    return render(
        request,
        "admin_portal/maintenance_update.html",
        {
            "title": "Resolve Maintenance Issue",
            "form": form,
            "charge_form": charge_form,
            "charge": charge,
            "can_edit_charge": can_edit_charge,
            "locked_charge_message": locked_charge_message,
            "req": req,
            "is_staff_portal": is_staff_portal,
            "back_url": reverse("admin_maintenance"),
        },
    )


@staff_or_admin_required
def admin_maintenance(request):
    is_staff_portal = _is_staff_portal_user(request.user)
    q = request.GET.get("q", "").strip()
    status = request.GET.get("status", "").strip()
    priority = request.GET.get("priority", "").strip()

    _archive_orphaned_requests()

    reqs = _visible_maintenance_queryset_for_user(request.user)

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
            | Q(assigned_staff__email__icontains=q)
            | Q(assigned_staff__tenantprofile__first_name__icontains=q)
            | Q(assigned_staff__tenantprofile__last_name__icontains=q)
        )

    reqs = reqs.order_by("-created_at")

    all_reqs = _visible_maintenance_queryset_for_user(request.user)
    if q:
        all_reqs = all_reqs.filter(
            Q(tenant__email__icontains=q)
            | Q(tenant__tenantprofile__first_name__icontains=q)
            | Q(tenant__tenantprofile__last_name__icontains=q)
            | Q(lease__tenant__email__icontains=q)
            | Q(lease__unit__number__icontains=q)
            | Q(description__icontains=q)
            | Q(assigned_staff__email__icontains=q)
            | Q(assigned_staff__tenantprofile__first_name__icontains=q)
            | Q(assigned_staff__tenantprofile__last_name__icontains=q)
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
            "is_staff_portal": is_staff_portal,
        },
    )
