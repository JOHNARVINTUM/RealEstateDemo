from django.shortcuts import render, redirect
import logging
from django.db import transaction
from django.utils import timezone

from accounts.decorators import tenant_required
from rentals.models import Lease, Notification
from rentals.notification_copy import maintenance_request_received_notification_copy
from .forms import MaintenanceRequestForm
from .models import MaintenanceRequest

logger = logging.getLogger(__name__)


def _current_maintenance_lease(user, today=None):
    if today is None:
        today = timezone.localdate()

    return (
        Lease.objects.filter(
            tenant=user,
            status=Lease.STATUS_ACTIVE,
            start_date__lte=today,
        )
        .filter(end_date__isnull=True)
        .select_related("unit")
        .order_by("-start_date", "-id")
        .first()
        or Lease.objects.filter(
            tenant=user,
            status=Lease.STATUS_ACTIVE,
            start_date__lte=today,
            end_date__gte=today,
        )
        .select_related("unit")
        .order_by("-start_date", "-id")
        .first()
    )


@tenant_required
def report_issue(request):
    user = request.user
    lease = _current_maintenance_lease(user)

    if request.method == "GET":
        success_report = request.session.pop("maintenance_report_success", None)
    else:
        success_report = None

    if request.method == "POST":
        form = MaintenanceRequestForm(request.POST, request.FILES)
        if form.is_valid():
            obj: MaintenanceRequest = form.save(commit=False)
            obj.tenant = user
            obj.lease = lease
            category_result = None
            try:
                from accounts.ml.maintenance_nlp import classify_issue_category

                category_result = classify_issue_category(f"{obj.title} {obj.description}")
                obj.category = category_result["category"]
            except Exception:
                obj.category = "OTHER"
            # Run NLP priority prediction from description
            try:
                from accounts.ml.maintenance_nlp import predict_priority
                result = predict_priority(obj.description)
                if result.get("available"):
                    obj.nlp_priority = result["priority"]
                    obj.nlp_priority_confidence = result["confidence"]
                    obj.priority = result["priority"]
            except Exception:
                pass
            try:
                with transaction.atomic():
                    obj.save()
            except Exception:
                logger.exception("Failed to save maintenance request for user %s", user.pk)
                return render(
                    request,
                    "maintenance/report_issue.html",
                    {
                        "form": form,
                        "lease": lease,
                        "submission_error": True,
                    },
                )

            try:
                unit = lease.unit if lease else None
                try:
                    tenant_name = user.tenantprofile.full_name
                except Exception:
                    tenant_name = user.email
                notification_title, notification_message = maintenance_request_received_notification_copy(
                    tenant_name=tenant_name,
                    category=obj.get_category_display(),
                    title=obj.title,
                    unit_number=unit.number if unit else "",
                )
                Notification.objects.create(
                    title=notification_title,
                    message=notification_message,
                    notification_type="MAINTENANCE",
                    recipient_type="ADMIN",
                    related_unit=unit,
                    related_tenant=user,
                )
            except Exception as exc:
                logger.exception("Failed to create admin maintenance notification: %s", exc)
            request.session["maintenance_report_success"] = {
                "title": obj.title,
                "unit_number": lease.unit.number if lease else "",
                "priority": obj.get_priority_display(),
            }
            return redirect("report_issue")
    else:
        form = MaintenanceRequestForm()

    # show unit info on the right side
    context = {
        "form": form,
        "lease": lease,
        "success_report": success_report,
        "submission_error": False,
    }
    return render(request, "maintenance/report_issue.html", context)


@tenant_required
def maintenance_list(request):
    user = request.user
    qs = MaintenanceRequest.objects.filter(tenant=user).select_related("assigned_staff", "lease__unit").order_by("-created_at")
    return render(request, "maintenance/my_requests.html", {"requests": qs})
