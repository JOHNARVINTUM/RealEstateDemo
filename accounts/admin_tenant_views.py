from datetime import date
from decimal import Decimal
import logging

from django.contrib import messages
from django.core.paginator import Paginator
from django.db.models import Count, Exists, OuterRef, Q
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.utils import timezone
from django.views.decorators.http import require_GET

from billing.models import MonthlyBill
from maintenance.models import MaintenanceRequest
from payments.models import ManualPayment
from rentals.models import Lease, TenantAttachment, TenantProfile, Unit

from .admin_portal_forms import ComprehensiveTenantEditForm, TenantProfileForm
from .admin_portal_views import admin_password_verified, admin_required, render_admin_password_confirm


logger = logging.getLogger(__name__)


def _apply_tenant_search(queryset, query: str):
    terms = [term for term in query.replace(",", " ").split() if term]
    for term in terms:
        queryset = queryset.filter(
            Q(first_name__icontains=term)
            | Q(last_name__icontains=term)
            | Q(contact_no__icontains=term)
            | Q(user__email__icontains=term)
            | Q(user__username__icontains=term)
        )
    return queryset


def _archive_json_safe(value):
    if isinstance(value, dict):
        return {key: _archive_json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_archive_json_safe(item) for item in value]
    if isinstance(value, Decimal):
        return float(value)
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return value


def tenant_has_records(tenant):
    """Check if tenant has any records that should prevent hard delete."""
    user = tenant.user
    return (
        Lease.objects.filter(tenant=user).exists()
        or ManualPayment.objects.filter(user=user).exists()
        or MaintenanceRequest.objects.filter(tenant=user).exists()
        or TenantAttachment.objects.filter(tenant=user).exists()
    )


def deactivate_tenant(tenant):
    """Deactivate tenant: disable login, close active leases, free units."""
    today = date.today()
    user = tenant.user

    user.is_active = False
    user.save(update_fields=["is_active"])

    active_leases = Lease.objects.select_related("unit").filter(tenant=user, status=Lease.STATUS_ACTIVE)
    for lease in active_leases:
        lease.deactivate(end_date=today)

        unit = lease.unit
        unit.status = "AVAILABLE"
        unit.save(update_fields=["status"])


@admin_required
def admin_tenants(request):
    q = request.GET.get("q", "").strip()
    lease_filter = request.GET.get("lease", "").strip()

    today = timezone.localdate()
    tenants_list = TenantProfile.objects.select_related("user").annotate(
        has_active_lease=Exists(
            Lease.objects.filter(
                tenant=OuterRef("user"),
                start_date__lte=today,
            ).filter(Q(end_date__isnull=True) | Q(end_date__gte=today))
        )
    )
    if q:
        tenants_list = _apply_tenant_search(tenants_list, q)

    if lease_filter == "active":
        tenants_list = tenants_list.filter(has_active_lease=True)
    elif lease_filter == "none":
        tenants_list = tenants_list.filter(has_active_lease=False)

    tenants_list = tenants_list.order_by("first_name", "last_name")

    paginator = Paginator(tenants_list, 10)
    page_number = request.GET.get("page")
    page_obj = paginator.get_page(page_number)

    page_user_ids = [tenant.user_id for tenant in page_obj]
    lease_user_ids = set(
        Lease.objects.filter(tenant_id__in=page_user_ids).values_list("tenant_id", flat=True)
    )
    payment_user_ids = set(
        ManualPayment.objects.filter(user_id__in=page_user_ids).values_list("user_id", flat=True)
    )
    maintenance_user_ids = set(
        MaintenanceRequest.objects.filter(tenant_id__in=page_user_ids).values_list("tenant_id", flat=True)
    )
    attachment_user_ids = set(
        TenantAttachment.objects.filter(tenant_id__in=page_user_ids).values_list("tenant_id", flat=True)
    )

    for tenant in page_obj:
        tenant.has_records = tenant.user_id in (
            lease_user_ids | payment_user_ids | maintenance_user_ids | attachment_user_ids
        )

    now = timezone.now()
    tenant_counts = TenantProfile.objects.aggregate(
        total=Count("id"),
        new_this_month=Count(
            "id",
            filter=Q(user__date_joined__year=now.year, user__date_joined__month=now.month),
        ),
    )
    total_tenants_count = tenant_counts["total"]
    new_tenants_count = tenant_counts["new_this_month"]
    active_tenants_count = Lease.objects.aggregate(
        active=Count("tenant", filter=Q(status=Lease.STATUS_ACTIVE), distinct=True)
    )["active"]

    return render(
        request,
        "admin_portal/tenants.html",
        {
            "page_obj": page_obj,
            "q": q,
            "lease_filter": lease_filter,
            "total_tenants_count": total_tenants_count,
            "active_tenants_count": active_tenants_count,
            "new_tenants_count": new_tenants_count,
        },
    )


@admin_required
def admin_tenant_detail(request, tenant_id: int):
    tenant = get_object_or_404(
        TenantProfile.objects.select_related("user", "user__tenantriskclassification"),
        pk=tenant_id,
    )
    leases = list(
        Lease.objects.select_related("unit", "tenant").filter(tenant=tenant.user).order_by("-start_date")
    )
    attachments = TenantAttachment.objects.filter(tenant=tenant.user).select_related("uploaded_by").order_by("-uploaded_at")
    tenant.has_records = tenant_has_records(tenant)

    lease_ids = [lease.id for lease in leases]
    current_month = timezone.localdate().replace(day=1)
    bill_history = MonthlyBill.objects.filter(
        lease_id__in=lease_ids,
    ).filter(
        Q(billing_month__lte=current_month) | Q(status="PAID")
    ).select_related("lease__unit").order_by("-billing_month")[:24]

    manual_payments = ManualPayment.objects.filter(user=tenant.user).order_by("-created_at")[:20]
    next_url = request.GET.get("next", "")
    back_url = (
        next_url
        if next_url and url_has_allowed_host_and_scheme(next_url, allowed_hosts={request.get_host()})
        else reverse("admin_tenants")
    )

    return render(
        request,
        "admin_portal/tenant_detail.html",
        {
            "tenant": tenant,
            "leases": leases,
            "attachments": attachments,
            "bill_history": bill_history,
            "manual_payments": manual_payments,
            "back_url": back_url,
        },
    )


@admin_required
def admin_create_tenant_profile(request):
    """
    Admin portal: create a TenantProfile row with auto-generated password and email notification.
    """
    total_units = Unit.objects.filter(is_active=True).count()
    total_tenants = TenantProfile.objects.count()
    if total_tenants >= total_units:
        messages.error(request, f"Cannot add more tenants. Maximum limit ({total_units} tenants for {total_units} units) reached.")
        return redirect("admin_tenants")

    form = TenantProfileForm(request.POST or None, request.FILES or None)

    if request.method == "POST" and form.is_valid():
        try:
            tenant_profile = form.save(uploaded_by=request.user)

            tenant_name = f"{tenant_profile.first_name} {tenant_profile.last_name}"
            success_message = f"Tenant {tenant_name} has been created successfully! "
            if getattr(tenant_profile, "credentials_email_sent", False):
                success_message += f"Credentials email was sent to {tenant_profile.user.email}."
            else:
                success_message += (
                    "Credentials were generated, but the email was not sent. "
                    "Check Resend configuration and delivery logs."
                )

            messages.success(request, success_message)

            try:
                tenant_id = tenant_profile.user.id
                return redirect(f"{reverse('admin_create_lease')}?tenant_id={tenant_id}")
            except Exception as e:
                logger.exception(
                    "Failed to redirect to create lease for tenant %s: %s",
                    getattr(tenant_profile.user, "id", None),
                    e,
                )
                messages.warning(request, "Tenant created but could not prefill lease form. Redirecting to tenants list.")
                return redirect("admin_tenants")

        except Exception as e:
            logger.exception("Failed to create tenant profile: %s", e)
            messages.error(request, f"Error creating tenant: {str(e)}")

    recent_tenants = TenantProfile.objects.all().order_by("-id")[:5]
    return render(
        request,
        "admin_portal/tenant_form.html",
        {
            "title": "Add Tenant",
            "form": form,
            "recent_tenants": recent_tenants,
            "back_url": reverse("admin_tenants"),
        },
    )


@admin_required
def admin_edit_tenant(request, tenant_id: int):
    tenant = get_object_or_404(TenantProfile.objects.select_related("user"), pk=tenant_id)
    form = ComprehensiveTenantEditForm(tenant, request.POST or None, request.FILES or None)

    if request.method == "POST" and form.is_valid():
        try:
            updated_tenant = form.save(uploaded_by=request.user)

            try:
                changes_made = []
                if tenant.user.email != form.cleaned_data["email"]:
                    changes_made.append("email")
                if tenant.user.username != form.cleaned_data["username"]:
                    changes_made.append("username")
                if tenant.user.role != form.cleaned_data["role"]:
                    changes_made.append("role")
                if form.cleaned_data.get("new_password"):
                    changes_made.append("password")

                if changes_made:
                    from notifications.models import Notification

                    change_list = ", ".join(changes_made)
                    Notification.create_notification(
                        title="Tenant Account Updated",
                        message=f"Admin updated {updated_tenant.first_name} {updated_tenant.last_name}'s account: {change_list}",
                        notification_type="SYSTEM",
                        related_tenant=updated_tenant.user,
                    )
            except Exception as e:
                logger.exception("Failed to create tenant update notification: %s", e)

            messages.success(request, f"Tenant {updated_tenant.first_name} {updated_tenant.last_name} has been updated successfully!")
            return redirect("admin_tenant_detail", tenant_id=tenant.id)
        except Exception as e:
            messages.error(request, f"Error updating tenant: {str(e)}")
            logger.exception("Error updating tenant")

    return render(
        request,
        "admin_portal/comprehensive_tenant_edit.html",
        {
            "title": "Edit Tenant",
            "form": form,
            "tenant": tenant,
            "back_url": reverse("admin_tenant_detail", args=[tenant.id]),
        },
    )


@admin_required
def admin_delete_tenant(request, tenant_id: int):
    """
    Delete tenant with password confirmation and archive options.
    Phase 1: Password verification
    Phase 2: Choose archive or permanent delete
    """
    from rentals.models import ArchivedTenant

    tenant = get_object_or_404(TenantProfile.objects.select_related("user"), pk=tenant_id)
    user = tenant.user
    has_records = tenant_has_records(tenant)

    if request.method == "POST" and request.POST.get("phase") == "2":
        admin_password = request.POST.get("admin_password", "").strip()
        if not request.user.check_password(admin_password):
            messages.error(request, "Password verification failed. Action cancelled.")
            return redirect("admin_tenant_detail", tenant_id=tenant.id)

        deletion_type = request.POST.get("deletion_type", "")
        deletion_reason = request.POST.get("deletion_reason", "").strip()

        tenant_data = {
            "full_name": tenant.full_name,
            "first_name": tenant.first_name,
            "last_name": tenant.last_name,
            "email": user.email,
            "contact_no": tenant.contact_no,
            "created_at": tenant.created_at.isoformat() if tenant.created_at else None,
            "has_records": has_records,
        }

        if has_records:
            # Convert Decimal fields to float for JSON serialization
            leases_raw = list(
                Lease.objects.filter(tenant=user).values(
                    "id",
                    "unit__number",
                    "monthly_rent",
                    "start_date",
                    "end_date",
                    "is_active",
                )
            )
            leases = [
                {
                    **lease,
                    "monthly_rent": float(lease["monthly_rent"]) if lease["monthly_rent"] else None,
                }
                for lease in leases_raw
            ]
            
            payments_raw = list(
                ManualPayment.objects.filter(user=user).values(
                    "id",
                    "amount",
                    "payment_method",
                    "status",
                    "created_at",
                )[:10]
            )
            payments = [
                {
                    **payment,
                    "amount": float(payment["amount"]) if payment["amount"] else None,
                }
                for payment in payments_raw
            ]
            maintenance = list(
                MaintenanceRequest.objects.filter(tenant=user).values(
                    "id",
                    "title",
                    "status",
                    "created_at",
                )[:10]
            )

            tenant_data["records_summary"] = {
                "leases": leases,
                "payments_count": ManualPayment.objects.filter(user=user).count(),
                "payments_sample": payments,
                "maintenance_count": MaintenanceRequest.objects.filter(tenant=user).count(),
                "maintenance_sample": maintenance,
            }

        tenant_data = _archive_json_safe(tenant_data)

        if deletion_type == "ARCHIVE":
            ArchivedTenant.objects.create(
                original_user_id=user.id,
                original_tenant_id=tenant.id,
                email=user.email,
                tenant_data=tenant_data,
                archive_type="DEACTIVATED",
                deleted_by=request.user,
                deletion_reason=deletion_reason,
                can_be_restored=True,
            )

            deactivate_tenant(tenant)
            messages.success(
                request,
                f"Tenant {tenant.full_name} archived and deactivated. All records preserved. Unit is now available.",
            )

        elif deletion_type == "DELETE":
            ArchivedTenant.objects.create(
                original_user_id=user.id,
                original_tenant_id=tenant.id,
                email=user.email,
                tenant_data=tenant_data,
                archive_type="DELETED_HARD" if has_records else "DELETED_SOFT",
                deleted_by=request.user,
                deletion_reason=deletion_reason,
                can_be_restored=not has_records,
            )

            full_name = tenant.full_name

            if has_records:
                Lease.objects.filter(tenant=user).delete()
                ManualPayment.objects.filter(user=user).delete()
                MaintenanceRequest.objects.filter(tenant=user).delete()
                TenantAttachment.objects.filter(tenant=user).delete()

            tenant.delete()
            user.delete()

            messages.success(
                request,
                f"Tenant {full_name} and all records permanently deleted. Archive created for audit trail.",
            )
        else:
            messages.error(request, "Invalid deletion type selected.")
            return redirect("admin_tenant_detail", tenant_id=tenant.id)

        return redirect("admin_tenants")

    if request.method == "POST":
        admin_password = request.POST.get("admin_password", "").strip()

        if not request.user.check_password(admin_password):
            return render(
                request,
                "admin_portal/confirm_delete_tenant.html",
                {
                    "title": "Security Verification Failed",
                    "error": "Incorrect password. Please try again.",
                    "tenant": tenant,
                    "has_records": has_records,
                    "phase": 1,
                    "post_url": reverse("admin_delete_tenant", args=[tenant.id]),
                    "back_url": reverse("admin_tenant_detail", args=[tenant.id]),
                },
            )

        return render(
            request,
            "admin_portal/confirm_delete_tenant.html",
            {
                "title": "Select Deletion Option",
                "tenant": tenant,
                "has_records": has_records,
                "phase": 2,
                "post_url": reverse("admin_delete_tenant", args=[tenant.id]),
                "back_url": reverse("admin_tenant_detail", args=[tenant.id]),
            },
        )

    return render(
        request,
        "admin_portal/confirm_delete_tenant.html",
        {
            "title": "Security Verification Required",
            "message": (
                f"You are attempting to delete tenant: {tenant.full_name}\n\n"
                f"For security, please enter your admin password to continue. "
                f"You will then be able to choose between archiving or permanent deletion."
            ),
            "tenant": tenant,
            "has_records": has_records,
            "phase": 1,
            "post_url": reverse("admin_delete_tenant", args=[tenant.id]),
            "back_url": reverse("admin_tenant_detail", args=[tenant.id]),
        },
    )


@admin_required
def admin_tenant_attachments(request, tenant_id: int):
    """Admin portal: view and manage tenant attachments with image preview"""
    tenant = get_object_or_404(TenantProfile.objects.select_related("user"), pk=tenant_id)
    attachments = TenantAttachment.objects.filter(tenant=tenant.user).select_related("uploaded_by").order_by("-uploaded_at")

    return render(
        request,
        "admin_portal/tenant_attachments.html",
        {
            "tenant": tenant,
            "attachments": attachments,
        },
    )


@admin_required
@require_GET
def admin_view_attachment(request, attachment_id: int):
    """Admin portal: view attachment file with image preview support"""
    attachment = get_object_or_404(TenantAttachment, pk=attachment_id)

    if not attachment.file:
        return HttpResponse("File not found", status=404)

    response = HttpResponse(attachment.file.read(), content_type="application/octet-stream")

    if attachment.is_image:
        response["Content-Type"] = f"image/{attachment.file_extension[1:]}"
    elif attachment.is_pdf:
        response["Content-Type"] = "application/pdf"

    response["Content-Disposition"] = f'inline; filename="{attachment.filename}"'

    return response


@admin_required
def admin_delete_attachment(request, attachment_id: int):
    """Admin portal: delete tenant attachment"""
    attachment = get_object_or_404(TenantAttachment.objects.select_related("tenant__tenantprofile"), pk=attachment_id)
    tenant_id = attachment.tenant.tenantprofile.id

    if request.method == "POST":
        if not admin_password_verified(request):
            return render_admin_password_confirm(
                request,
                title="Delete Attachment",
                message=f"Delete attachment '{attachment.filename}'? This cannot be undone.",
                post_url=reverse("admin_delete_attachment", args=[attachment.id]),
                back_url=reverse("admin_tenant_attachments", args=[tenant_id]),
                error="Incorrect admin password. Attachment deletion was not completed.",
            )
        if attachment.file:
            attachment.file.delete()
        attachment.delete()
        messages.success(request, f"Attachment '{attachment.filename}' has been deleted successfully.")
        return redirect("admin_tenant_attachments", tenant_id=tenant_id)

    return render_admin_password_confirm(
        request,
        title="Delete Attachment",
        message=f"Delete attachment '{attachment.filename}'? This cannot be undone.",
        post_url=reverse("admin_delete_attachment", args=[attachment.id]),
        back_url=reverse("admin_tenant_attachments", args=[tenant_id]),
    )
