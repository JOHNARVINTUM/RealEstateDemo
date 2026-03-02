from datetime import date

from django.db.models import Sum, Q
from django.shortcuts import render, get_object_or_404, redirect
from django.urls import reverse
from django.utils import timezone
import logging

from accounts.decorators import admin_required
from rentals.models import Lease, Unit, TenantProfile
from billing.models import MonthlyBill
from billing.services import ensure_bills_since_move_in
from payments.models import ManualPayment
from maintenance.models import MaintenanceRequest
from announcements.models import Announcement
from maintenance.forms import AdminMaintenanceUpdateForm

from .admin_portal_forms import TenantProfileForm, AnnouncementForm, LeaseForm
from .admin_portal_forms import TenantProfileEditForm
from .admin_portal_forms import UnitForm
from django.utils import timezone as dj_timezone
from django.contrib import messages

logger = logging.getLogger(__name__)


@admin_required
def admin_dashboard(request):
    total_tenants = Lease.objects.filter(is_active=True).values("tenant").distinct().count()
    occupied_units = Lease.objects.filter(is_active=True).count()
    vacant_units = Unit.objects.filter(is_active=True).count() - occupied_units

    today = timezone.now().date()
    # Count revenue by when bills were actually paid (paid_at), not by their billing month.
    # This ensures advance payments approved now are included in this month's revenue.
    total_revenue = (
        MonthlyBill.objects.filter(status="PAID", paid_at__year=today.year, paid_at__month=today.month)
        .aggregate(total=Sum("total_due"))["total"] or 0
    )
    overdue_payments = MonthlyBill.objects.filter(status="UNPAID", due_date__lt=today).count()

    return render(request, "admin_portal/dashboard.html", {
        "total_tenants": total_tenants,
        "occupied_units": occupied_units,
        "vacant_units": max(vacant_units, 0),
        "total_revenue": total_revenue,
        "overdue_payments": overdue_payments,
    })


@admin_required
def admin_tenants(request):
    q = request.GET.get("q", "").strip()

    tenants = TenantProfile.objects.select_related("user")
    if q:
        tenants = tenants.filter(
            Q(full_name__icontains=q) |
            Q(contact_no__icontains=q) |
            Q(user__email__icontains=q) |
            Q(user__username__icontains=q)
        )

    tenants = tenants.order_by("full_name")[:500]
    return render(request, "admin_portal/tenants.html", {"tenants": tenants, "q": q})


@admin_required
def admin_tenant_detail(request, tenant_id: int):
    tenant = get_object_or_404(TenantProfile.objects.select_related("user"), pk=tenant_id)
    leases = Lease.objects.select_related("unit", "tenant").filter(tenant=tenant.user).order_by("-start_date")
    return render(request, "admin_portal/tenant_detail.html", {"tenant": tenant, "leases": leases})


@admin_required
def admin_create_tenant_profile(request):
    """
    Admin portal: create a TenantProfile row (linked to an existing User).
    """
    form = TenantProfileForm(request.POST or None)

    if request.method == "POST" and form.is_valid():
        tenant_profile = form.save()
        # after creating a tenant, redirect admin to create a lease for that tenant
        try:
            tenant_id = tenant_profile.user.id
            return redirect(f"{reverse('admin_create_lease')}?tenant_id={tenant_id}")
        except Exception as e:
            logger.exception("Failed to redirect to create lease for tenant %s: %s", getattr(tenant_profile.user, 'id', None), e)
            messages.warning(request, "Tenant created but could not prefill lease form. Redirecting to tenants list.")
            return redirect("admin_tenants")

    return render(request, "admin_portal/form.html", {
        "title": "Add Tenant",
        "form": form,
        "back_url": reverse("admin_tenants"),
    })


@admin_required
def admin_create_unit(request):
    """Admin portal: create a Unit row."""
    form = UnitForm(request.POST or None)

    if request.method == "POST" and form.is_valid():
        form.save()
        return redirect("admin_tenants")

    return render(request, "admin_portal/form.html", {
        "title": "Add Unit",
        "form": form,
        "back_url": reverse("admin_tenants"),
    })


@admin_required
def admin_create_lease(request):
    """
    Admin portal: create a Lease row (linking a tenant to a unit).
    """
    # allow pre-filling tenant via ?tenant_id=... when redirected from tenant creation
    initial = {}
    tenant_id = request.GET.get("tenant_id")
    if tenant_id:
        initial["tenant"] = tenant_id

    form = LeaseForm(request.POST or None, initial=initial)

    if request.method == "POST" and form.is_valid():
        lease = form.save()
        # create initial monthly bill rows from move-in until today
        try:
            ensure_bills_since_move_in(lease)
        except Exception:
            # don't block creation if billing generation fails; admin can regenerate later
            logger.exception("ensure_bills_since_move_in failed for lease id %s", getattr(lease, 'id', None))
            messages.warning(request, "Failed to generate initial bills; you can regenerate later.")
        return redirect("admin_tenants")

    return render(request, "admin_portal/form.html", {
        "title": "Add Lease",
        "form": form,
        "back_url": reverse("admin_tenants"),
    })


@admin_required
def admin_edit_tenant(request, tenant_id: int):
    tenant = get_object_or_404(TenantProfile, pk=tenant_id)
    form = TenantProfileEditForm(request.POST or None, instance=tenant)
    if request.method == "POST" and form.is_valid():
        form.save()
        return redirect("admin_tenant_detail", tenant_id=tenant.id)
    return render(request, "admin_portal/form.html", {
        "title": "Edit Tenant",
        "form": form,
        "back_url": reverse("admin_tenant_detail", args=[tenant.id]),
    })


@admin_required
def admin_delete_tenant(request, tenant_id: int):
    tenant = get_object_or_404(TenantProfile, pk=tenant_id)
    if request.method == "POST":
        tenant.delete()
        return redirect("admin_tenants")
    return render(request, "admin_portal/confirm.html", {
        "title": "Delete Tenant",
        "message": f"Delete tenant {tenant.full_name}? This cannot be undone.",
        "post_url": reverse("admin_delete_tenant", args=[tenant.id]),
        "back_url": reverse("admin_tenant_detail", args=[tenant.id]),
    })


@admin_required
def admin_edit_lease(request, lease_id: int):
    lease = get_object_or_404(Lease, pk=lease_id)
    form = LeaseForm(request.POST or None, instance=lease)
    if request.method == "POST" and form.is_valid():
        lease = form.save()
        try:
            ensure_bills_since_move_in(lease)
        except Exception:
            logger.exception("ensure_bills_since_move_in failed while editing lease id %s", getattr(lease, 'id', None))
            messages.warning(request, "Failed to update billing rows; please regenerate bills if needed.")
        return redirect("admin_tenant_detail", tenant_id=lease.tenant.tenantprofile.id if hasattr(lease.tenant, 'tenantprofile') else lease.tenant.id)
    return render(request, "admin_portal/form.html", {
        "title": "Edit Lease",
        "form": form,
        "back_url": reverse("admin_tenants"),
    })


@admin_required
def admin_delete_lease(request, lease_id: int):
    lease = get_object_or_404(Lease, pk=lease_id)
    if request.method == "POST":
        lease.delete()
        return redirect("admin_tenants")
    return render(request, "admin_portal/confirm.html", {
        "title": "Delete Lease",
        "message": f"Delete lease for {lease.tenant.email} -> {lease.unit.number}?",
        "post_url": reverse("admin_delete_lease", args=[lease.id]),
        "back_url": reverse("admin_tenant_detail", args=[lease.tenant.id])
    })


@admin_required
def admin_mark_bill_paid(request, bill_id: int):
    bill = get_object_or_404(MonthlyBill, pk=bill_id)
    if request.method == "POST":
        bill.status = "PAID"
        bill.paid_at = dj_timezone.now()
        bill.save()
        return redirect("admin_billing")
    return render(request, "admin_portal/confirm.html", {
        "title": "Mark Bill Paid",
        "message": f"Mark bill {bill.id} as PAID?",
        "post_url": reverse("admin_mark_bill_paid", args=[bill.id]),
        "back_url": reverse("admin_billing"),
    })


@admin_required
def admin_mark_bill_unpaid(request, bill_id: int):
    bill = get_object_or_404(MonthlyBill, pk=bill_id)
    if request.method == "POST":
        bill.status = "UNPAID"
        bill.paid_at = None
        bill.payment_reference = ""
        bill.save()
        return redirect("admin_billing")
    return render(request, "admin_portal/confirm.html", {
        "title": "Mark Bill Unpaid",
        "message": f"Mark bill {bill.id} as UNPAID?",
        "post_url": reverse("admin_mark_bill_unpaid", args=[bill.id]),
        "back_url": reverse("admin_billing"),
    })


@admin_required
def admin_approve_payment(request, payment_id: int):
    p = get_object_or_404(ManualPayment, pk=payment_id)
    if request.method == "POST":
        p.status = "APPROVED"
        p.save()
        # mark linked bills as paid if provided
        if p.bill_ids:
            for bid in [x.strip() for x in p.bill_ids.split(',') if x.strip()]:
                try:
                    b = MonthlyBill.objects.get(pk=int(bid))
                    b.status = "PAID"
                    b.paid_at = dj_timezone.now()
                    b.payment_reference = p.reference_code
                    b.save()
                except Exception as e:
                    logger.exception("Failed to mark bill %s paid from manual payment %s: %s", bid, p.id, e)
                    continue
        return redirect("admin_payments")
    return render(request, "admin_portal/confirm.html", {
        "title": "Approve Payment",
        "message": f"Approve payment {p.reference_code} by {p.user.email}?",
        "post_url": reverse("admin_approve_payment", args=[p.id]),
        "back_url": reverse("admin_payments"),
    })


@admin_required
def admin_reject_payment(request, payment_id: int):
    p = get_object_or_404(ManualPayment, pk=payment_id)
    if request.method == "POST":
        p.status = "REJECTED"
        p.save()
        return redirect("admin_payments")
    return render(request, "admin_portal/confirm.html", {
        "title": "Reject Payment",
        "message": f"Reject payment {p.reference_code} by {p.user.email}?",
        "post_url": reverse("admin_reject_payment", args=[p.id]),
        "back_url": reverse("admin_payments"),
    })


@admin_required
def admin_update_maintenance(request, req_id: int):
    req = get_object_or_404(MaintenanceRequest, pk=req_id)
    if request.method == "POST":
        form = AdminMaintenanceUpdateForm(request.POST, instance=req)
        if form.is_valid():
            updated = form.save(commit=False)
            # set resolved_at when marked resolved
            if updated.status == "RESOLVED" and not req.resolved_at:
                updated.resolved_at = dj_timezone.now()
            if updated.status != "RESOLVED":
                updated.resolved_at = None
            updated.save()
            return redirect("admin_maintenance")
    else:
        form = AdminMaintenanceUpdateForm(instance=req)

    return render(request, "admin_portal/form.html", {
        "title": "Update Maintenance",
        "form": form,
        "back_url": reverse("admin_maintenance"),
    })


@admin_required
def admin_edit_announcement(request, ann_id: int):
    ann = get_object_or_404(Announcement, pk=ann_id)
    form = AnnouncementForm(request.POST or None, instance=ann)
    if request.method == "POST" and form.is_valid():
        form.save()
        return redirect("admin_announcements")
    return render(request, "admin_portal/form.html", {
        "title": "Edit Announcement",
        "form": form,
        "back_url": reverse("admin_announcements"),
    })


@admin_required
def admin_delete_announcement(request, ann_id: int):
    ann = get_object_or_404(Announcement, pk=ann_id)
    if request.method == "POST":
        ann.delete()
        return redirect("admin_announcements")
    return render(request, "admin_portal/confirm.html", {
        "title": "Delete Announcement",
        "message": f"Delete announcement {ann.title}?",
        "post_url": reverse("admin_delete_announcement", args=[ann.id]),
        "back_url": reverse("admin_announcements"),
    })


@admin_required
def admin_billing(request):
    q = request.GET.get("q", "").strip()
    status = request.GET.get("status", "").strip()

    bills = MonthlyBill.objects.select_related("lease", "lease__unit", "lease__tenant")

    if status in ("PAID", "UNPAID"):
        bills = bills.filter(status=status)

    if q:
        bills = bills.filter(
            Q(lease__tenant__email__icontains=q) |
            Q(lease__unit__number__icontains=q) |
            Q(payment_reference__icontains=q)
        )

    bills = bills.order_by("-billing_month")[:500]
    return render(request, "admin_portal/billing.html", {"bills": bills, "q": q, "status": status})


@admin_required
def admin_payments(request):
    q = request.GET.get("q", "").strip()
    status = request.GET.get("status", "").strip()

    payments = ManualPayment.objects.select_related("user")
    if status in ("PENDING", "APPROVED", "REJECTED"):
        payments = payments.filter(status=status)
    if q:
        payments = payments.filter(
            Q(user__email__icontains=q) |
            Q(reference_code__icontains=q) |
            Q(bill_ids__icontains=q)
        )

    payments = payments.order_by("-created_at")[:500]
    return render(request, "admin_portal/payments.html", {"payments": payments, "q": q, "status": status})


@admin_required
def admin_maintenance(request):
    q = request.GET.get("q", "").strip()
    status = request.GET.get("status", "").strip()

    reqs = MaintenanceRequest.objects.select_related("lease", "lease__unit", "lease__tenant")

    if status:
        reqs = reqs.filter(status=status)

    if q:
        reqs = reqs.filter(
            Q(lease__tenant__email__icontains=q) |
            Q(lease__unit__number__icontains=q) |
            Q(description__icontains=q)
        )

    reqs = reqs.order_by("-created_at")[:500]
    return render(request, "admin_portal/maintenance.html", {"reqs": reqs, "q": q, "status": status})


@admin_required
def admin_announcements(request):
    q = request.GET.get("q", "").strip()
    items = Announcement.objects.all()

    # FIX: model field is "body", not "content"
    if q:
        items = items.filter(Q(title__icontains=q) | Q(body__icontains=q))

    items = items.order_by("-created_at")[:200]
    return render(request, "admin_portal/announcements.html", {"items": items, "q": q})


@admin_required
def admin_create_announcement(request):
    form = AnnouncementForm(request.POST or None)

    if request.method == "POST" and form.is_valid():
        form.save(user=request.user)  # uses your custom save(user=...)
        return redirect("admin_announcements")

    return render(request, "admin_portal/form.html", {
        "title": "Add Announcement",
        "form": form,
        "back_url": reverse("admin_announcements"),
    })




