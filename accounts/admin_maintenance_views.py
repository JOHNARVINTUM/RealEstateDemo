import logging

from django.core.paginator import Paginator
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse

from maintenance.forms import AdminMaintenanceUpdateForm
from maintenance.models import MaintenanceRequest
from rentals.services import send_email_via_resend
from django.utils import timezone as dj_timezone

from .admin_portal_views import admin_required


logger = logging.getLogger(__name__)


@admin_required
def admin_update_maintenance(request, req_id: int):
    req = get_object_or_404(MaintenanceRequest, pk=req_id)
    if request.method == "POST":
        form = AdminMaintenanceUpdateForm(request.POST, instance=req)
        if form.is_valid():
            updated = form.save(commit=False)
            old_status = req.status
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

    reqs = MaintenanceRequest.objects.select_related("lease", "lease__unit", "lease__tenant")

    if status:
        reqs = reqs.filter(status=status)

    if priority:
        reqs = reqs.filter(priority=priority)

    if q:
        reqs = reqs.filter(
            Q(lease__tenant__email__icontains=q)
            | Q(lease__unit__number__icontains=q)
            | Q(description__icontains=q)
        )

    reqs = reqs.order_by("-created_at")

    all_reqs = MaintenanceRequest.objects.all()
    if q:
        all_reqs = all_reqs.filter(
            Q(lease__tenant__email__icontains=q)
            | Q(lease__unit__number__icontains=q)
            | Q(description__icontains=q)
        )

    total_count = all_reqs.count()
    pending_count = all_reqs.filter(status="PENDING").count()
    in_progress_count = all_reqs.filter(status="IN_PROGRESS").count()
    resolved_count = all_reqs.filter(status="RESOLVED").count()

    paginator = Paginator(reqs, 10)
    page_number = request.GET.get("page")
    page_obj = paginator.get_page(page_number)

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
